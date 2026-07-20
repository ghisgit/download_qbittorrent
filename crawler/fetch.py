from __future__ import annotations

import asyncio
import random
from pathlib import Path

import httpx
from playwright.async_api import Browser, BrowserContext, Page, async_playwright
from playwright_stealth import Stealth

import crawler

from .config import CrawlerConfig, StageConfig

# ── Playwright fetcher ──────────────────────────────────────────────


class PlaywrightFetcher:
    def __init__(self, config: CrawlerConfig):
        self.config = config
        self._pw_cm = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None

    async def __aenter__(self):
        stealth = Stealth()
        self._pw_cm = stealth.use_async(async_playwright())
        p = await self._pw_cm.__aenter__()
        self._browser = await p.chromium.launch(
            headless=self.config.browser.headless,
            args=self.config.browser.args,
        )
        self._context = await self._browser.new_context()
        return self

    async def __aexit__(self, *args):
        try:
            if self._context:
                await self._context.close()
        except Exception as e:
            print(f"  [playwright] context close error: {e}")
        try:
            if self._browser:
                await self._browser.close()
        except Exception as e:
            print(f"  [playwright] browser close error: {e}")
        try:
            if self._pw_cm:
                await self._pw_cm.__aexit__(*args)
        except Exception as e:
            print(f"  [playwright] playwright close error: {e}")

    async def fetch(
        self,
        url: str,
        stage: StageConfig,
        sem: asyncio.Semaphore,
    ) -> str:
        async with sem:
            print(f"  [fetch] playwright GET {url}")
            if self._context is None:
                raise RuntimeError("Playwright context not initialized")
            page = await self._context.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=120000)
                if stage.security:
                    await self._handle_security(page, stage)
                html = await page.content()
                print(f"  [fetch] -> {len(html)} bytes")
                if crawler.settings.debug_save:
                    safe = url.replace("://", "_").replace("/", "_").replace("?", "_")[:80]
                    Path(f"debug_{safe}.html").write_text(html, encoding="utf-8")
                    print(f"  [fetch]  saved to debug_{safe}.html")
                return html
            finally:
                await page.close()

    async def _handle_security(self, page: Page, stage: StageConfig) -> None:
        if not stage.security_selector:
            return
        try:
            btn = await page.wait_for_selector(stage.security_selector, timeout=1000)
        except Exception:
            return  # no security gate on this page
        try:
            if btn:
                print("  [playwright] 点击安全验证按钮")
                await btn.click()
                await page.wait_for_load_state("networkidle", timeout=10000)
                await asyncio.sleep(2)
        except Exception as e:
            print(f"  [playwright] 安全验证按钮点击异常: {e}")


# ── HTTPX fetcher ───────────────────────────────────────────────────


class HttpxFetcher:
    def __init__(self, config: CrawlerConfig):
        self.config = config
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self):
        limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
        self._client = await httpx.AsyncClient(limits=limits, timeout=15.0).__aenter__()
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.__aexit__(*args)

    async def fetch(
        self,
        url: str,
        stage: StageConfig,
        sem: asyncio.Semaphore,
    ) -> str | None:
        retry_cfg = stage.retry
        max_retries = retry_cfg.max_retries if retry_cfg else 1
        retryable = retry_cfg.retryable_codes if retry_cfg else set()

        for attempt in range(max_retries):
            try:
                async with sem:
                    print(f"  [fetch] httpx GET {url}  (attempt {attempt + 1}/{max_retries})")
                    if self._client is None:
                        raise RuntimeError("HTTPX client not initialized")
                    resp = await self._client.get(url, headers=stage.headers)
                    resp.raise_for_status()
                    print(f"  [fetch] -> HTTP {resp.status_code}, {len(resp.text)} bytes")
                    if crawler.settings.debug_save:
                        safe = url.replace("://", "_").replace("/", "_").replace("?", "_")[:80]
                        Path(f"debug_{safe}.html").write_text(resp.text, encoding="utf-8")
                        print(f"  [fetch]  saved to debug_{safe}.html")
                    return resp.text
            except httpx.HTTPStatusError as e:
                code = e.response.status_code
                print(f"  [fetch] HTTP {code} {url}")
                if code in retryable and attempt < max_retries - 1:
                    wait = float(e.response.headers.get("Retry-After", 2**attempt + random.random()))
                    print(f"  [fetch] retry {url} after {wait:.1f}s")
                    await asyncio.sleep(wait)
                    continue
                return None
            except httpx.RequestError as e:
                print(f"  [fetch] error {url}: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2**attempt + random.random())
                    continue
                return None
        return None

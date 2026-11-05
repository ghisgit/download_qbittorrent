from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from scrapling.fetchers import AsyncStealthySession, FetcherSession

import crawler

from .config import CrawlerConfig, StageConfig

# ── helpers ──────────────────────────────────────────────────────────


def debug_enabled(stage: StageConfig) -> bool:
    """Per-stage debug_save overrides the global CLI --debug-save flag."""
    if stage.debug_save is not None:
        return stage.debug_save
    return crawler.settings.debug_save


def save_debug_html(stage: StageConfig, url: str, html: str) -> None:
    safe = url.replace("://", "_").replace("/", "_").replace("?", "_")[:80]
    Path(f"debug_{stage.id}_{safe}.html").write_text(html, encoding="utf-8")
    print(f"  [fetch]  saved to debug_{stage.id}_{safe}.html")


def _retry_settings(stage: StageConfig) -> tuple[int, set[int]]:
    retry_cfg = stage.retry
    if retry_cfg is None:
        return 1, set()
    return retry_cfg.max_retries, retry_cfg.retryable_codes


def _retry_after(headers: Any) -> float | None:
    """Read a numeric Retry-After header; ignore malformed values."""
    try:
        value = headers.get("Retry-After")
    except Exception:
        return None
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except TypeError, ValueError:
        return None


def _response_html(resp: Any) -> str:
    html = resp.html_content
    if isinstance(html, bytes):
        return html.decode("utf-8", errors="replace")
    return str(html or "")


async def _sleep_before_retry(attempt: int, url: str, wait: float | None = None) -> None:
    delay = wait if wait is not None else 2**attempt + random.random()
    print(f"  [fetch] retry {url} after {delay:.1f}s")
    await asyncio.sleep(delay)


_PAGE_OPERATION_TIMEOUT_MS = 30000


async def _tune_page_timeouts(page: Any) -> None:
    """Cap page operation waits such as Cloudflare solver polling.

    Scrapling uses the session timeout as the page's default timeout.  Our
    session timeout stays at 120s for navigation, but the Cloudflare solver's
    internal ``wait_for_networkidle``/``wait_for_load_state`` calls should not
    each block for that long.  Navigation timeout is left untouched.
    """
    page.set_default_timeout(_PAGE_OPERATION_TIMEOUT_MS)


# ── security gate automation ────────────────────────────────────────


def handle_verify(selector: str = ".enter-btn") -> Callable[[Any], Awaitable[Any]]:
    """Build a Scrapling ``page_action`` that clicks a security/age gate.

    The action waits for the initial page to reach network-idle, then looks for
    the configured button.  If the button is absent or hidden, the page needs
    no verification and is returned unchanged.
    """

    async def action(page: Any) -> Any:
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception as e:
            print(f"  [stealthy] 等待 networkidle 超时: {e}")

        try:
            button = await page.query_selector(selector)
            if button is None or not await button.is_visible():
                return page
        except Exception as e:
            print(f"  [stealthy] 查找安全验证按钮异常: {e}")
            return page

        print("  [stealthy] 点击安全验证按钮")
        try:
            await button.click()
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception as e:
            print(f"  [stealthy] 安全验证按钮点击异常: {e}")
        return page

    return action


# ── Scrapling StealthySession fetcher ───────────────────────────────


class StealthyFetcher:
    def __init__(self, config: CrawlerConfig):
        self.config = config
        self._session: AsyncStealthySession | None = None
        concurrency = [
            stage.concurrency if stage.concurrency > 0 else 3 for stage in config.stages if stage.fetcher == "stealthy"
        ]
        self._max_pages = max([5, *concurrency])

    async def __aenter__(self):
        session = AsyncStealthySession(
            headless=self.config.browser.headless,
            extra_flags=self.config.browser.args,
            solve_cloudflare=self.config.browser.solve_cloudflare,
            timeout=120000,
            retries=1,
            max_pages=self._max_pages,
        )
        await session.start()
        self._session = session
        return self

    async def __aexit__(self, *args):
        if self._session is not None:
            try:
                await self._session.close()
            except Exception as e:
                print(f"  [stealthy] close error: {e}")
            self._session = None

    async def fetch(
        self,
        url: str,
        stage: StageConfig,
        sem: asyncio.Semaphore,
    ) -> str:
        max_retries, retryable = _retry_settings(stage)
        page_action = handle_verify(stage.security_selector) if stage.security_selector else None
        solve_cloudflare = (
            stage.solve_cloudflare if stage.solve_cloudflare is not None else self.config.browser.solve_cloudflare
        )

        for attempt in range(max_retries):
            try:
                async with sem:
                    print(f"  [fetch] stealthy GET {url}  (attempt {attempt + 1}/{max_retries})")
                    session = self._session
                    if session is None:
                        raise RuntimeError("StealthySession not initialized")

                    kwargs: dict[str, Any] = {
                        "solve_cloudflare": solve_cloudflare,
                        "page_setup": _tune_page_timeouts,
                    }
                    if page_action is not None:
                        kwargs["page_action"] = page_action
                    if stage.headers:
                        kwargs["extra_headers"] = stage.headers

                    resp = await session.fetch(url, **kwargs)
                    if resp.status in retryable:
                        print(f"  [fetch] HTTP {resp.status} {url}")
                    else:
                        html = _response_html(resp)
                        print(f"  [fetch] -> HTTP {resp.status}, {len(html)} bytes")
                        if debug_enabled(stage):
                            save_debug_html(stage, url, html)
                        return html
            except Exception as e:
                print(f"  [fetch] error {url}: {e}")

            if attempt < max_retries - 1:
                await _sleep_before_retry(attempt, url)

        return ""


# ── Scrapling FetcherSession fetcher ────────────────────────────────


class HttpFetcher:
    def __init__(self, config: CrawlerConfig):
        self.config = config
        self._manager: FetcherSession | None = None
        self._session: Any = None

    async def __aenter__(self):
        manager = FetcherSession(timeout=15, retries=1)
        self._session = await manager.__aenter__()
        self._manager = manager
        return self

    async def __aexit__(self, *args):
        if self._manager is not None:
            try:
                await self._manager.__aexit__(*args)
            except Exception as e:
                print(f"  [http] close error: {e}")
            self._manager = None
            self._session = None

    async def fetch(
        self,
        url: str,
        stage: StageConfig,
        sem: asyncio.Semaphore,
    ) -> str:
        max_retries, retryable = _retry_settings(stage)

        for attempt in range(max_retries):
            retry_after: float | None = None
            try:
                async with sem:
                    print(f"  [fetch] http GET {url}  (attempt {attempt + 1}/{max_retries})")
                    session = self._session
                    if session is None:
                        raise RuntimeError("FetcherSession not initialized")

                    kwargs: dict[str, Any] = {}
                    if stage.headers:
                        kwargs["headers"] = stage.headers

                    resp = await session.get(url, **kwargs)
                    if resp.status in retryable:
                        print(f"  [fetch] HTTP {resp.status} {url}")
                        retry_after = _retry_after(resp.headers)
                    elif resp.status >= 400:
                        print(f"  [fetch] HTTP {resp.status} {url}")
                        return ""
                    else:
                        html = _response_html(resp)
                        print(f"  [fetch] -> HTTP {resp.status}, {len(html)} bytes")
                        if debug_enabled(stage):
                            save_debug_html(stage, url, html)
                        return html
            except Exception as e:
                print(f"  [fetch] error {url}: {e}")

            if attempt < max_retries - 1:
                await _sleep_before_retry(attempt, url, retry_after)

        return ""

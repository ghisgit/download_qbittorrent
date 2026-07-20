from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urljoin

import crawler

from .config import CrawlerConfig, expand_urls
from .extract import apply_filter, extract
from .fetch import HttpxFetcher, PlaywrightFetcher
from .qb import QBClient


async def run_pipeline(config: CrawlerConfig) -> list[str]:
    """Run the crawler pipeline defined by config.  Returns final magnet URLs."""
    output_store: dict[str, list[dict[str, Any]]] = {}
    all_magnets: list[str] = []

    # Pre-launch long-lived fetchers and QB client
    pw_fetcher = None
    hx_fetcher = None
    qb_client = None
    needs_playwright = any(s.fetcher == "playwright" for s in config.stages)
    needs_httpx = any(s.fetcher == "httpx" for s in config.stages)
    needs_qb = any(s.qb_send for s in config.stages)

    if needs_playwright:
        pw_fetcher = PlaywrightFetcher(config)
        await pw_fetcher.__aenter__()
    if needs_httpx:
        hx_fetcher = HttpxFetcher(config)
        await hx_fetcher.__aenter__()
    if needs_qb:
        qb_client = await QBClient(config.qb).__aenter__()

    try:
        for stage in config.stages:
            print(f"\n=== Stage: {stage.id} ===")

            input_items: list[dict[str, Any]] = []
            if isinstance(stage.input, list):
                for src in stage.input:
                    input_items.extend(output_store.get(src, []))
                if not input_items:
                    print(f"[{stage.id}] 所有上游无数据, 跳过")
                    continue
                # dedup by _url across multiple sources
                seen_urls: set[str] = set()
                deduped = []
                for item in input_items:
                    key = item.get("_url")
                    if key:
                        if key in seen_urls:
                            continue
                        seen_urls.add(key)
                    deduped.append(item)
                input_items = deduped
            elif stage.input:
                input_items = output_store.get(stage.input, [])
                if not input_items:
                    print(f"[{stage.id}] 上游无数据, 跳过")
                    continue
            else:
                urls = expand_urls(stage)
                input_items = [{"_url": u} for u in urls]

            if not input_items:
                print(f"[{stage.id}] 无待抓取 URL")
                continue

            print(f"[{stage.id}] 输入: {len(input_items)} 条")
            if stage.dedup_by:
                before = len(input_items)
                seen: set[str] = set()
                deduped = []
                for item in input_items:
                    key = item.get(stage.dedup_by)
                    if key is not None:
                        if key in seen:
                            continue
                        seen.add(key)
                    deduped.append(item)
                input_items = deduped
                if before != len(input_items):
                    print(f"[{stage.id}] 按 {stage.dedup_by} 去重: {before} -> {len(input_items)} 条")
            if stage.resources:
                print(f"[{stage.id}] 资源: {', '.join(stage.resources)}")
            if crawler.settings.verbose and len(input_items) <= 10:
                for inp in input_items:
                    url = inp.get("_url") or inp.get("url") or ""
                    if url:
                        print(f"  input: {url}")

            results: list[dict[str, Any]] = []
            max_conc = stage.concurrency if stage.concurrency > 0 else (10 if stage.fetcher == "httpx" else 3)
            sem = asyncio.Semaphore(max_conc)

            async def process_one(item: dict[str, Any]) -> list[dict[str, Any]]:
                try:
                    if "_url" in item:
                        url = item["_url"]
                    elif stage.url_pattern:
                        url = stage.url_pattern.format(**item)
                    else:
                        url = item.get("url") or item.get("_source") or ""

                    if url and not url.startswith("http"):
                        base = item.get("_source_url") or item.get("_source") or ""
                        if base:
                            url = urljoin(base, url)

                    if not url:
                        if crawler.settings.verbose:
                            print(f"  [pipeline] X no URL for item {item}")
                        return []

                    if crawler.settings.verbose:
                        print(f"  [pipeline] -> fetch: {url}")

                    html = None
                    if stage.fetcher == "playwright" and pw_fetcher:
                        html = await pw_fetcher.fetch(url, stage, sem)
                    elif stage.fetcher == "httpx" and hx_fetcher:
                        html = await hx_fetcher.fetch(url, stage, sem)

                    if not html:
                        return []

                    if not stage.extracts:
                        return [{"_html": html, "_url": url, **item}]

                    all_items: list[dict[str, Any]] = []
                    for extract_cfg in stage.extracts:
                        items = extract(html, extract_cfg, source_url=url)
                        for it in items:
                            it["_source_url"] = url
                            for k, v in item.items():
                                if not k.startswith("_"):
                                    it.setdefault(k, v)
                        all_items.extend(items)

                    if stage.delay > 0:
                        if crawler.settings.verbose:
                            print(f"  [pipeline] delay {stage.delay}s")
                        await asyncio.sleep(stage.delay)

                    return all_items
                except Exception as e:
                    print(f"  [pipeline] process_one error: {e}")
                    return []

            tasks = [process_one(item) for item in input_items]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            for batch in batch_results:
                if isinstance(batch, BaseException):
                    print(f"  [pipeline] task error: {batch}")
                    continue
                results.extend(batch)

            seen = set()
            unique = []
            for r in results:
                key = r.get("match") or r.get("text") or r.get("_url") or str(r)
                if key not in seen:
                    seen.add(key)
                    unique.append(r)
            results = unique

            if stage.filter:
                before = len(results)
                results = apply_filter(results, stage.filter)
                print(f"[{stage.id}] 过滤: {before} -> {len(results)} 条")

            print(f"[{stage.id}] 提取到 {len(results)} 条数据")
            output_store[stage.id] = results

            if stage.qb_send and results:
                stage_magnets = _collect_magnets(results)
                if stage_magnets:
                    cat = stage.category or config.qb.category
                    print(f"[{stage.id}] 发送到 qBittorrent ({len(stage_magnets)} 个磁力, 分类={cat})")
                    assert qb_client is not None
                    await qb_client.add_magnets(stage_magnets, category=cat)
                    all_magnets.extend(stage_magnets)

    finally:
        if pw_fetcher:
            await pw_fetcher.__aexit__(None, None, None)
        if hx_fetcher:
            await hx_fetcher.__aexit__(None, None, None)
        if qb_client:
            await qb_client.__aexit__(None, None, None)

    return all_magnets


def _collect_magnets(items: list[dict[str, Any]]) -> list[str]:
    magnets: list[str] = []
    for item in items:
        for k, v in item.items():
            if k.startswith("_"):
                continue
            if isinstance(v, list):
                for sv in v:
                    if isinstance(sv, str) and sv.startswith("magnet:"):
                        magnets.append(sv)
            elif isinstance(v, str) and v.startswith("magnet:"):
                magnets.append(v)
    return list(dict.fromkeys(magnets))  # dedup preserving order

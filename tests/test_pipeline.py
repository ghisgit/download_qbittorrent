from __future__ import annotations

import asyncio

from crawler.config import CacheConfig, CrawlerConfig, StageConfig
from crawler.pipeline import _collect_magnets, run_pipeline


def _patch_fetch(monkeypatch):
    calls: list[str] = []

    async def fake_fetch(self, url: str, stage, sem) -> str:
        calls.append(url)
        return f"<html>{url}</html>"

    monkeypatch.setattr("crawler.fetch.HttpxFetcher.fetch", fake_fetch)
    return calls


def _seed_config(cache_enabled: bool, cache_dir: str, stage_cache=None) -> CrawlerConfig:
    return CrawlerConfig(
        name="t",
        cache=CacheConfig(enabled=cache_enabled, dir=cache_dir),
        stages=[
            StageConfig(
                id="seed",
                urls=["http://example.com/a", "http://example.com/b"],
                fetcher="httpx",
                cache=stage_cache,
            )
        ],
    )


class TestCachePipeline:
    def test_second_run_uses_cache(self, tmp_path, monkeypatch):
        calls = _patch_fetch(monkeypatch)
        cfg = _seed_config(True, str(tmp_path))
        asyncio.run(run_pipeline(cfg))
        asyncio.run(run_pipeline(cfg))
        assert len(calls) == 2  # 二次运行全部命中缓存, 不再请求

    def test_disabled_fetches_every_run(self, tmp_path, monkeypatch):
        calls = _patch_fetch(monkeypatch)
        cfg = _seed_config(False, str(tmp_path))
        asyncio.run(run_pipeline(cfg))
        asyncio.run(run_pipeline(cfg))
        assert len(calls) == 4

    def test_stage_cache_false_overrides_global(self, tmp_path, monkeypatch):
        calls = _patch_fetch(monkeypatch)
        cfg = _seed_config(True, str(tmp_path), stage_cache=False)
        asyncio.run(run_pipeline(cfg))
        asyncio.run(run_pipeline(cfg))
        assert len(calls) == 4

    def test_stage_cache_true_with_global_disabled(self, tmp_path, monkeypatch):
        calls = _patch_fetch(monkeypatch)
        cfg = _seed_config(False, str(tmp_path), stage_cache=True)
        asyncio.run(run_pipeline(cfg))
        asyncio.run(run_pipeline(cfg))
        assert len(calls) == 2


class TestMultiInputDedupLog:
    def test_log_printed(self, tmp_path, monkeypatch, capsys):
        _patch_fetch(monkeypatch)
        cfg = CrawlerConfig(
            name="t",
            cache=CacheConfig(enabled=False, dir=str(tmp_path)),
            stages=[
                StageConfig(id="a", urls=["http://example.com/same"], fetcher="httpx"),
                StageConfig(id="b", urls=["http://example.com/same"], fetcher="httpx"),
                StageConfig(id="c", input=["a", "b"], fetcher="httpx"),
            ],
        )
        asyncio.run(run_pipeline(cfg))
        out = capsys.readouterr().out
        assert "[c] 合并多 input a(1)+b(1) = 2 条, 按 _url 去重: 2 -> 1 条" in out


class TestCollectMagnets:
    def test_magnet_only(self):
        items = [{"group_0": "magnet:?xt=urn:btih:abc", "_source": "http://x.com"}]
        assert _collect_magnets(items) == ["magnet:?xt=urn:btih:abc"]

    def test_skip_internal_fields(self):
        items = [{"_url": "http://x.com", "group_0": "magnet:?xt=urn:btih:abc"}]
        assert _collect_magnets(items) == ["magnet:?xt=urn:btih:abc"]

    def test_no_magnet(self):
        items = [{"text": "hello"}]
        assert _collect_magnets(items) == []

    def test_dedup(self):
        items = [
            {"group_0": "magnet:?xt=urn:btih:abc"},
            {"group_0": "magnet:?xt=urn:btih:abc"},
        ]
        assert _collect_magnets(items) == ["magnet:?xt=urn:btih:abc"]

    def test_list_value(self):
        items = [{"magnets": ["magnet:?xt=urn:btih:abc", "magnet:?xt=urn:btih:def"]}]
        result = _collect_magnets(items)
        assert result == ["magnet:?xt=urn:btih:abc", "magnet:?xt=urn:btih:def"]

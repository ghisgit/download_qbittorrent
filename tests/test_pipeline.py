from __future__ import annotations

import asyncio

import crawler
from crawler.config import (
    CacheConfig,
    CompareConfig,
    CrawlerConfig,
    ExtractConfig,
    FilterCondition,
    FilterRule,
    QBConfig,
    StageConfig,
)
from crawler.pipeline import (
    _collect_magnets,
    _collect_magnets_by_category,
    _resolve_category,
    run_pipeline,
)


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
        assert "[c] 合并多 input a(1)+b(1) = 2 条, 按目标 URL 去重: 2 -> 1 条" in out


class TestMultiInputTargetUrlDedup:
    def test_extracted_items_dedup_by_computed_url(self, monkeypatch, capsys):
        html_by_url = {
            "http://example.com/a": '<a data-id="1"></a><a data-id="2"></a>',
            "http://example.com/b": '<a data-id="1"></a><a data-id="2"></a>',
        }
        calls: list[str] = []

        async def fake_fetch(self, url: str, stage, sem) -> str:
            calls.append(url)
            return html_by_url.get(url, "<html></html>")

        monkeypatch.setattr("crawler.fetch.HttpxFetcher.fetch", fake_fetch)

        cfg = CrawlerConfig(
            name="t",
            stages=[
                StageConfig(
                    id="a",
                    urls=["http://example.com/a"],
                    fetcher="httpx",
                    extracts=[ExtractConfig(type="regex", pattern=r'data-id="(\d+)"')],
                ),
                StageConfig(
                    id="b",
                    urls=["http://example.com/b"],
                    fetcher="httpx",
                    extracts=[ExtractConfig(type="regex", pattern=r'data-id="(\d+)"')],
                ),
                StageConfig(
                    id="c",
                    input=["a", "b"],
                    fetcher="httpx",
                    url_pattern="http://example.com/detail/{group_0}",
                ),
            ],
        )

        asyncio.run(run_pipeline(cfg))

        out = capsys.readouterr().out
        assert "[c] 合并多 input a(2)+b(2) = 4 条, 按目标 URL 去重: 4 -> 2 条" in out
        assert calls.count("http://example.com/detail/1") == 1
        assert calls.count("http://example.com/detail/2") == 1

    def test_relative_pattern_resolves_before_dedup(self, monkeypatch, capsys):
        html_by_url = {
            "http://example.com/a": '<a href="/detail/1">x</a>',
            "http://example.com/b": '<a href="/detail/1">x</a>',
        }
        calls: list[str] = []

        async def fake_fetch(self, url: str, stage, sem) -> str:
            calls.append(url)
            return html_by_url.get(url, "<html></html>")

        monkeypatch.setattr("crawler.fetch.HttpxFetcher.fetch", fake_fetch)

        cfg = CrawlerConfig(
            name="t",
            stages=[
                StageConfig(
                    id="a",
                    urls=["http://example.com/a"],
                    fetcher="httpx",
                    extracts=[ExtractConfig(type="css", selector="a", attribute="href", multiple=True)],
                ),
                StageConfig(
                    id="b",
                    urls=["http://example.com/b"],
                    fetcher="httpx",
                    extracts=[ExtractConfig(type="css", selector="a", attribute="href", multiple=True)],
                ),
                StageConfig(
                    id="c",
                    input=["a", "b"],
                    fetcher="httpx",
                    url_pattern="{text}",
                ),
            ],
        )

        asyncio.run(run_pipeline(cfg))

        out = capsys.readouterr().out
        assert "[c] 合并多 input a(1)+b(1) = 2 条, 按目标 URL 去重: 2 -> 1 条" in out
        assert calls.count("http://example.com/detail/1") == 1

    def test_no_target_url_does_not_collapse_source_rows(self, monkeypatch, capsys):
        html = '<a data-id="1"></a><a data-id="2"></a>'

        async def fake_fetch(self, url: str, stage, sem) -> str:
            return html

        monkeypatch.setattr("crawler.fetch.HttpxFetcher.fetch", fake_fetch)

        cfg = CrawlerConfig(
            name="t",
            stages=[
                StageConfig(
                    id="a",
                    urls=["http://example.com/a"],
                    fetcher="httpx",
                    extracts=[ExtractConfig(type="regex", pattern=r'data-id="(\d+)"')],
                ),
                StageConfig(
                    id="b",
                    urls=["http://example.com/b"],
                    fetcher="httpx",
                    extracts=[ExtractConfig(type="regex", pattern=r'data-id="(\d+)"')],
                ),
                StageConfig(id="c", input=["a", "b"], fetcher="httpx"),
            ],
        )

        asyncio.run(run_pipeline(cfg))

        out = capsys.readouterr().out
        assert "[c] 合并多 input a(2)+b(2) = 4 条, 按目标 URL 去重: 4 -> 4 条" in out

    def test_does_not_mutate_upstream_items(self, monkeypatch):
        html_by_url = {
            "http://example.com/a": '<a data-id="1"></a>',
            "http://example.com/b": '<a data-id="1"></a>',
        }
        calls: list[str] = []

        async def fake_fetch(self, url: str, stage, sem) -> str:
            calls.append(url)
            return html_by_url.get(url, "<html></html>")

        monkeypatch.setattr("crawler.fetch.HttpxFetcher.fetch", fake_fetch)

        cfg = CrawlerConfig(
            name="t",
            stages=[
                StageConfig(
                    id="a",
                    urls=["http://example.com/a"],
                    fetcher="httpx",
                    extracts=[ExtractConfig(type="regex", pattern=r'data-id="(\d+)"')],
                ),
                StageConfig(
                    id="b",
                    urls=["http://example.com/b"],
                    fetcher="httpx",
                    extracts=[ExtractConfig(type="regex", pattern=r'data-id="(\d+)"')],
                ),
                StageConfig(
                    id="c",
                    input=["a", "b"],
                    fetcher="httpx",
                    url_pattern="http://example.com/c/{group_0}",
                ),
                StageConfig(
                    id="d",
                    input="a",
                    fetcher="httpx",
                    url_pattern="http://example.com/d/{group_0}",
                ),
            ],
        )

        asyncio.run(run_pipeline(cfg))

        assert calls.count("http://example.com/c/1") == 1
        assert calls.count("http://example.com/d/1") == 1


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


class TestCategoryResolution:
    def test_current_stage_resource_template(self):
        item = {"text": "The Matrix"}
        assert _resolve_category("movie/{text}", item, "default") == "movie/The Matrix"

    def test_previous_stage_field_template(self):
        item = {"id": 42}
        assert _resolve_category("movie/{id}", item, "default") == "movie/42"

    def test_literal_category_unchanged(self):
        assert _resolve_category("movie", {"movie": "not-this"}, "default") == "movie"

    def test_missing_field_falls_back_to_default(self):
        assert _resolve_category("movie/{title}", {}, "default") == "default"

    def test_empty_category_falls_back_to_default(self):
        assert _resolve_category("", {"title": "x"}, "default") == "default"

    def test_list_value_is_joined(self):
        item = {"tags": ["action", "sci-fi"]}
        assert _resolve_category("genre/{tags}", item, "default") == "genre/action,sci-fi"


class TestCollectMagnetsByCategory:
    def test_groups_and_preserves_order(self):
        items = [
            {"_url": "a", "group_0": "magnet:a", "text": "Action"},
            {"_url": "b", "group_0": "magnet:b", "text": "Action"},
            {"_url": "c", "group_0": "magnet:c", "text": "Comedy"},
        ]
        grouped = _collect_magnets_by_category(items, "movie/{text}", "default")
        assert grouped == {
            "movie/Action": ["magnet:a", "magnet:b"],
            "movie/Comedy": ["magnet:c"],
        }

    def test_duplicate_magnets_only_once(self):
        items = [
            {"group_0": "magnet:a", "text": "Action"},
            {"group_0": "magnet:a", "text": "Comedy"},
        ]
        grouped = _collect_magnets_by_category(items, "movie/{text}", "default")
        assert grouped == {"movie/Action": ["magnet:a"]}

    def test_literal_category_keeps_single_group(self):
        items = [
            {"group_0": "magnet:a", "text": "Action"},
            {"group_0": "magnet:b", "text": "Comedy"},
        ]
        grouped = _collect_magnets_by_category(items, "movie", "default")
        assert grouped == {"movie": ["magnet:a", "magnet:b"]}


class TestQBSendFilterAndCategory:
    def test_filter_gates_qb_send_and_uses_current_resource_category(self, monkeypatch):
        html_by_url = {
            "http://example.com/1": '<a data-category="Anime">magnet:?xt=urn:btih:aaa</a>',
            "http://example.com/2": '<a data-category="skip">magnet:?xt=urn:btih:bbb</a>',
            "http://example.com/3": '<a data-category="Movie">magnet:?xt=urn:btih:ccc</a>',
        }

        async def fake_fetch(self, url: str, stage, sem) -> str:
            return html_by_url[url]

        monkeypatch.setattr("crawler.fetch.HttpxFetcher.fetch", fake_fetch)

        added: list[tuple[str, list[str]]] = []

        async def fake_add(self, magnets: list[str], category: str = "") -> int:
            added.append((category, list(magnets)))
            return len(magnets)

        monkeypatch.setattr("crawler.pipeline.QBClient.add_magnets", fake_add)

        cfg = CrawlerConfig(
            name="t",
            qb=QBConfig(url="http://localhost:8080", user="u", password="p"),
            stages=[
                StageConfig(
                    id="magnets",
                    urls=list(html_by_url),
                    fetcher="httpx",
                    extracts=[
                        ExtractConfig(
                            type="regex",
                            pattern=r'data-category="([^"]+)">(magnet:[^<]+)<',
                            multiple=True,
                        )
                    ],
                    resources=["group_0", "group_1"],
                    filter=[FilterRule(condition=FilterCondition(field="group_0", not_in=["skip"]))],
                    category="movie/{group_0}",
                    qb_send=True,
                )
            ],
        )

        asyncio.run(run_pipeline(cfg))

        assert added == [
            ("movie/Anime", ["magnet:?xt=urn:btih:aaa"]),
            ("movie/Movie", ["magnet:?xt=urn:btih:ccc"]),
        ]

    def test_category_can_use_previous_stage_resource(self, monkeypatch):
        async def fake_fetch(self, url: str, stage, sem) -> str:
            if stage.id == "list":
                return '<a data-id="7" data-name="Anime">item</a>'
            return '<a data-magnet="magnet:?xt=urn:btih:aaa">item</a>'

        monkeypatch.setattr("crawler.fetch.HttpxFetcher.fetch", fake_fetch)

        added: list[tuple[str, list[str]]] = []

        async def fake_add(self, magnets: list[str], category: str = "") -> int:
            added.append((category, list(magnets)))
            return len(magnets)

        monkeypatch.setattr("crawler.pipeline.QBClient.add_magnets", fake_add)

        cfg = CrawlerConfig(
            name="t",
            qb=QBConfig(url="http://localhost:8080", user="u", password="p"),
            stages=[
                StageConfig(
                    id="list",
                    urls=["http://example.com/list"],
                    fetcher="httpx",
                    extracts=[
                        ExtractConfig(
                            type="regex",
                            pattern=r'data-id="(\d+)" data-name="(\w+)"',
                            multiple=True,
                        )
                    ],
                    resources=["group_0", "group_1"],
                ),
                StageConfig(
                    id="magnets",
                    input="list",
                    fetcher="httpx",
                    url_pattern="http://example.com/detail/{group_0}",
                    extracts=[
                        ExtractConfig(
                            type="regex",
                            pattern=r'data-magnet="(magnet:[^"]+)"',
                            multiple=True,
                        )
                    ],
                    resources=["group_0"],
                    category="movie/{group_1}",
                    qb_send=True,
                ),
            ],
        )

        asyncio.run(run_pipeline(cfg))

        assert added == [("movie/Anime", ["magnet:?xt=urn:btih:aaa"])]


class TestComparePipeline:
    def test_compare_runs_after_filter_and_before_qb_send(self, monkeypatch, capsys):
        html = (
            '<a data-name="A" data-tag="skip" data-magnet="magnet:a">'
            '<a data-name="A" data-tag="ok" data-magnet="magnet:b">'
            '<a data-name="A" data-tag="ok" data-magnet="magnet:c">'
        )

        async def fake_fetch(self, url: str, stage, sem) -> str:
            return html

        monkeypatch.setattr("crawler.fetch.HttpxFetcher.fetch", fake_fetch)

        added: list[tuple[str, list[str]]] = []

        async def fake_add(self, magnets: list[str], category: str = "") -> int:
            added.append((category, list(magnets)))
            return len(magnets)

        monkeypatch.setattr("crawler.pipeline.QBClient.add_magnets", fake_add)

        cfg = CrawlerConfig(
            name="t",
            qb=QBConfig(url="http://localhost:8080", user="u", password="p"),
            stages=[
                StageConfig(
                    id="magnets",
                    urls=["http://example.com/a"],
                    fetcher="httpx",
                    extracts=[
                        ExtractConfig(
                            type="regex",
                            pattern=r'data-name="([^"]+)" data-tag="([^"]+)" data-magnet="(magnet:[^"]+)"',
                            multiple=True,
                        )
                    ],
                    resources=["group_0", "group_1", "group_2"],
                    filter=[FilterRule(condition=FilterCondition(field="group_1", not_in=["skip"]))],
                    compare=CompareConfig(by=["group_0"]),
                    qb_send=True,
                )
            ],
        )

        asyncio.run(run_pipeline(cfg))

        assert added == [("", ["magnet:b"])]
        out = capsys.readouterr().out
        assert "[magnets] 过滤: 3 -> 2 条" in out
        assert "[magnets] 比较: 2 -> 1 条 (by=group_0, keep=first)" in out

    def test_compare_skipped_with_single_result(self, monkeypatch, capsys):
        async def fake_fetch(self, url: str, stage, sem) -> str:
            return '<a data-name="A" data-magnet="magnet:a">'

        monkeypatch.setattr("crawler.fetch.HttpxFetcher.fetch", fake_fetch)

        called: list[int] = []

        def fake_compare(items, cfg):
            called.append(len(items))
            return items

        monkeypatch.setattr("crawler.pipeline.apply_compare", fake_compare)
        monkeypatch.setattr(crawler.settings, "verbose", True)

        cfg = CrawlerConfig(
            name="t",
            stages=[
                StageConfig(
                    id="magnets",
                    urls=["http://example.com/a"],
                    fetcher="httpx",
                    extracts=[
                        ExtractConfig(
                            type="regex",
                            pattern=r'data-name="([^"]+)" data-magnet="(magnet:[^"]+)"',
                            multiple=True,
                        )
                    ],
                    compare=CompareConfig(by=["group_0"]),
                )
            ],
        )

        asyncio.run(run_pipeline(cfg))

        assert called == []
        out = capsys.readouterr().out
        assert "[magnets] 比较: 结果不足 2 条, 跳过" in out

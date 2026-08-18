from __future__ import annotations

from crawler.config import CrawlerConfig, expand_urls


class TestExpandUrls:
    def test_static_urls(self):
        from crawler.config import StageConfig

        stage = StageConfig(id="s", urls=["http://a.com", "http://b.com"])
        assert expand_urls(stage) == ["http://a.com", "http://b.com"]

    def test_url_pattern_and_range(self):
        from crawler.config import StageConfig

        stage = StageConfig(id="s", url_pattern="http://example.com/{n}", url_range={"name": "n", "start": 1, "end": 4})
        assert expand_urls(stage) == [
            "http://example.com/1",
            "http://example.com/2",
            "http://example.com/3",
        ]

    def test_empty(self):
        from crawler.config import StageConfig

        stage = StageConfig(id="s")
        assert expand_urls(stage) == []


class TestFilterParse:
    def test_condition_valid(self):
        from crawler.config import _parse_condition

        cond = _parse_condition({"field": "text", "contains": "foo"})
        assert cond is not None
        assert cond.field == "text"
        assert cond.contains == "foo"

    def test_condition_no_operators(self):
        from crawler.config import _parse_condition

        cond = _parse_condition({"field": "text"})
        assert cond is None

    def test_condition_not_dict(self):
        from crawler.config import _parse_condition

        cond = _parse_condition("hello")
        assert cond is None

    def test_filter_rules_nested(self):
        from crawler.config import _parse_filter_rules

        rules = _parse_filter_rules(
            [
                {"contains": "a"},
                {"any_of": [{"contains": "b"}, {"all_of": [{"contains": "c"}, {"contains": "d"}]}]},
            ]
        )
        assert len(rules) == 2
        assert rules[0].condition is not None
        assert rules[0].condition.contains == "a"
        assert len(rules[1].any_of) == 2
        assert len(rules[1].any_of[1].all_of) == 2


class TestStageInput:
    def test_single_str(self):
        from crawler.config import StageConfig

        s = StageConfig(id="s", input="upstream")
        assert s.input == "upstream"
        assert isinstance(s.input, str)

    def test_list(self):
        from crawler.config import StageConfig

        s = StageConfig(id="s", input=["a", "b"])
        assert s.input == ["a", "b"]
        assert isinstance(s.input, list)

    def test_none_default(self):
        from crawler.config import StageConfig

        s = StageConfig(id="s")
        assert s.input is None


class TestMinimalConfig:
    def test_load(self, minimal_config: CrawlerConfig):
        assert minimal_config.name == "test"
        assert len(minimal_config.stages) == 1
        assert minimal_config.stages[0].id == "seed"
        assert minimal_config.stages[0].urls == ["https://example.com"]


class TestParseFields:
    def test_pattern_and_flags(self):
        from crawler.config import _parse_fields

        fields = _parse_fields(
            {"id": {"selector": "a", "attribute": "href", "pattern": r"id=(\d+)", "flags": ["I"], "type": "int"}}
        )
        fe = fields["id"]
        assert fe.selector == "a"
        assert fe.attribute == "href"
        assert fe.pattern == r"id=(\d+)"
        assert fe.flags == ["I"]
        assert fe.type == "int"

    def test_defaults(self):
        from crawler.config import _parse_fields

        fields = _parse_fields({"t": {}})
        fe = fields["t"]
        assert fe.pattern == ""
        assert fe.flags == []


class TestDebugSave:
    def test_none_default(self):
        from crawler.config import StageConfig

        s = StageConfig(id="s")
        assert s.debug_save is None

    def test_parse_true(self, tmp_path):
        from crawler.config import load_config

        p = tmp_path / "debug_true.yaml"
        p.write_text(
            "name: t\nstages:\n  - id: a\n    debug_save: true\n",
            encoding="utf-8",
        )
        cfg = load_config(p)
        assert cfg.stages[0].debug_save is True

    def test_parse_false(self, tmp_path):
        from crawler.config import load_config

        p = tmp_path / "debug_false.yaml"
        p.write_text(
            "name: t\nstages:\n  - id: a\n    debug_save: false\n",
            encoding="utf-8",
        )
        cfg = load_config(p)
        assert cfg.stages[0].debug_save is False


class TestCacheConfig:
    def test_defaults(self):
        from crawler.config import CacheConfig

        cfg = CacheConfig()
        assert cfg.enabled is False
        assert cfg.dir == "cache"
        assert cfg.ttl == 0

    def test_parse_global(self, tmp_path):
        from crawler.config import load_config

        p = tmp_path / "cache.yaml"
        p.write_text(
            "name: t\ncache:\n  enabled: true\n  dir: /tmp/my-cache\n  ttl: 3600\nstages:\n  - id: a\n",
            encoding="utf-8",
        )
        cfg = load_config(p)
        assert cfg.cache.enabled is True
        assert cfg.cache.dir == "/tmp/my-cache"
        assert cfg.cache.ttl == 3600

    def test_stage_none_default(self):
        from crawler.config import StageConfig

        s = StageConfig(id="s")
        assert s.cache is None

    def test_stage_override(self, tmp_path):
        from crawler.config import load_config

        p = tmp_path / "stage_cache.yaml"
        p.write_text(
            "name: t\nstages:\n  - id: a\n    cache: false\n",
            encoding="utf-8",
        )
        cfg = load_config(p)
        assert cfg.stages[0].cache is False

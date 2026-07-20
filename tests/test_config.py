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

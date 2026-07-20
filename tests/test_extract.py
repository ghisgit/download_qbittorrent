from __future__ import annotations

from crawler.config import ExtractConfig
from crawler.extract import extract


class TestRegexExtract:
    HTML = "hello <a>magnet:?xt=urn:btih:abc123</a> world <a>magnet:?xt=urn:btih:def456</a>"

    def test_single(self):
        cfg = ExtractConfig(type="regex", pattern=r"magnet:\?xt=urn:btih:[0-9a-f]+")
        items = extract(self.HTML, cfg)
        assert len(items) == 2
        assert items[0]["group_0"] == "magnet:?xt=urn:btih:abc123"
        assert items[1]["group_0"] == "magnet:?xt=urn:btih:def456"

    def test_named_groups(self):
        cfg = ExtractConfig(type="regex", pattern=r"(magnet:\?xt=urn:btih:([0-9a-f]+))")
        items = extract(self.HTML, cfg)
        assert len(items) == 2
        assert items[0]["group_0"] == "magnet:?xt=urn:btih:abc123"
        assert items[0]["group_1"] == "abc123"

    def test_no_match(self):
        cfg = ExtractConfig(type="regex", pattern=r"no-match")
        items = extract("hello world", cfg)
        assert items == []


class TestCssExtract:
    HTML = '<ul><li class="x">a</li><li class="x">b</li><li class="y">c</li></ul>'

    def test_simple_text(self):
        cfg = ExtractConfig(type="css", selector="li.x")
        items = extract(self.HTML, cfg)
        assert len(items) == 2
        assert items[0]["text"] == "a"
        assert items[1]["text"] == "b"

    def test_multi_field(self):
        from crawler.config import FieldExtract

        cfg = ExtractConfig(
            type="css",
            selector="ul",
            fields={
                "letters": FieldExtract(selector="li", multiple=True),
                "first": FieldExtract(selector="li:nth-child(1)"),
            },
        )
        items = extract(self.HTML, cfg)
        assert len(items) == 1
        assert items[0]["letters"] == ["a", "b", "c"]
        assert items[0]["first"] == "a"

    def test_no_match(self):
        cfg = ExtractConfig(type="css", selector="span")
        items = extract(self.HTML, cfg)
        assert items == []


class TestFilterEngine:
    def test_contains_pass(self):
        from crawler.config import FilterCondition
        from crawler.extract import _check_condition

        assert _check_condition({"text": "hello world"}, FilterCondition(contains="world"))
        assert not _check_condition({"text": "hello world"}, FilterCondition(contains="foo"))

    def test_not_contains(self):
        from crawler.config import FilterCondition
        from crawler.extract import _check_condition

        assert _check_condition({"text": "hello"}, FilterCondition(not_contains="foo"))
        assert not _check_condition({"text": "hello"}, FilterCondition(not_contains="hello"))

    def test_numeric_comparison(self):
        from crawler.config import _UNSET, FilterCondition
        from crawler.extract import _check_condition

        # gt not set via _UNSET — should always pass
        assert _check_condition({"val": "10"}, FilterCondition(field="val", gt=_UNSET))
        # gt not set — should always pass

    def test_rule_any_of(self):
        from crawler.config import FilterCondition, FilterRule
        from crawler.extract import _check_rule

        rule = FilterRule(
            any_of=[
                FilterRule(condition=FilterCondition(contains="a")),
                FilterRule(condition=FilterCondition(contains="b")),
            ]
        )
        assert _check_rule({"text": "a"}, rule)
        assert _check_rule({"text": "b"}, rule)
        assert not _check_rule({"text": "c"}, rule)

    def test_rule_all_of(self):
        from crawler.config import FilterCondition, FilterRule
        from crawler.extract import _check_rule

        rule = FilterRule(
            all_of=[
                FilterRule(condition=FilterCondition(contains="a")),
                FilterRule(condition=FilterCondition(contains="b")),
            ]
        )
        assert _check_rule({"text": "ab"}, rule)
        assert not _check_rule({"text": "a"}, rule)

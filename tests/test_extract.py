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

    def test_multiple_false_first_only(self):
        cfg = ExtractConfig(type="regex", pattern=r"magnet:\?xt=urn:btih:[0-9a-f]+", multiple=False)
        items = extract(self.HTML, cfg)
        assert len(items) == 1
        assert items[0]["group_0"] == "magnet:?xt=urn:btih:abc123"


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

    def test_multiple_false_first_only(self):
        cfg = ExtractConfig(type="css", selector="li.x", multiple=False)
        items = extract(self.HTML, cfg)
        assert len(items) == 1
        assert items[0]["text"] == "a"

    def test_no_match(self):
        cfg = ExtractConfig(type="css", selector="span")
        items = extract(self.HTML, cfg)
        assert items == []


class TestCssFieldPattern:
    HTML = """
    <div class="item"><h3><a href="article_search.php?id=42">Hello</a></h3></div>
    <div class="item"><h3><a href="article_search.php?id=99">World</a></h3></div>
    """

    def _cfg(self, **field_kwargs):
        from crawler.config import FieldExtract

        return ExtractConfig(
            type="css",
            selector="div.item",
            fields={
                "title": FieldExtract(selector="h3 > a"),
                "id": FieldExtract(selector="h3 > a", attribute="href", **field_kwargs),
            },
        )

    def test_pattern_extracts_id(self):
        items = extract(self.HTML, self._cfg(pattern=r"article_search\.php\?id=(\d+)"))
        assert len(items) == 2
        assert items[0]["id"] == "42"
        assert items[1]["id"] == "99"

    def test_pattern_with_int_cast(self):
        items = extract(
            self.HTML,
            self._cfg(pattern=r"article_search\.php\?id=(\d+)", type="int"),
        )
        assert items[0]["id"] == 42
        assert isinstance(items[0]["id"], int)

    def test_pattern_no_match_omits_field(self):
        items = extract(self.HTML, self._cfg(pattern=r"nomatch=(\d+)"))
        assert len(items) == 2
        assert "id" not in items[0]

    def test_pattern_optional_group_with_int_cast(self):
        from crawler.config import FieldExtract

        html = '<div class="item"><a href="abc42">x</a></div>'
        cfg = ExtractConfig(
            type="css",
            selector="div.item",
            fields={
                "id": FieldExtract(
                    selector="a",
                    attribute="href",
                    pattern=r"(pre)?(\d+)",
                    type="int",
                )
            },
        )
        # group(1) 是可选组 (None), 必须落到 group(2), 不能抛 TypeError
        items = extract(html, cfg)
        assert len(items) == 1
        assert items[0]["id"] == 42

    def test_pattern_multiple_values(self):
        from crawler.config import FieldExtract

        html = '<ul><li><a href="a.php?id=1">x</a></li><li><a href="b.php?id=2">y</a></li></ul>'
        cfg = ExtractConfig(
            type="css",
            selector="ul",
            fields={
                "ids": FieldExtract(
                    selector="li > a",
                    attribute="href",
                    pattern=r"id=(\d+)",
                    multiple=True,
                )
            },
        )
        items = extract(html, cfg)
        assert items[0]["ids"] == ["1", "2"]


class TestXPathFieldPattern:
    HTML = """
    <div class="item"><h3><a href="article_search.php?id=42">Hello</a></h3></div>
    <div class="item"><h3><a href="article_search.php?id=99">World</a></h3></div>
    """

    def test_pattern_extracts_id(self):
        from crawler.config import FieldExtract

        cfg = ExtractConfig(
            type="xpath",
            selector='//div[@class="item"]',
            fields={
                "title": FieldExtract(selector="h3/a"),
                "id": FieldExtract(
                    selector="h3/a",
                    attribute="href",
                    pattern=r"article_search\.php\?id=(\d+)",
                    type="int",
                ),
            },
        )
        items = extract(self.HTML, cfg)
        assert len(items) == 2
        assert items[0]["title"] == "Hello"
        assert items[0]["id"] == 42
        assert items[1]["id"] == 99


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

    def test_not_in(self):
        from crawler.config import FilterCondition
        from crawler.extract import _check_condition

        assert not _check_condition({"text": "hello"}, FilterCondition(not_in=["hello"]))
        assert _check_condition({"text": "hello"}, FilterCondition(not_in=["world"]))

    def test_not_in_multivalue_field(self):
        from crawler.config import FilterCondition
        from crawler.extract import _check_condition

        cond = FilterCondition(field="tags", not_in=["低质量"])
        assert not _check_condition({"tags": ["精华", "低质量"]}, cond)
        assert _check_condition({"tags": ["精华", "推荐"]}, cond)

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

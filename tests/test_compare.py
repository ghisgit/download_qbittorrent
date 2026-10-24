from __future__ import annotations

import crawler
from crawler.config import CompareConfig
from crawler.extract import apply_compare


class TestCompareKeep:
    def test_first_keeps_first_and_preserves_order(self):
        items = [
            {"title": "a", "n": 1},
            {"title": "b", "n": 2},
            {"title": "a", "n": 3},
        ]
        result = apply_compare(items, CompareConfig(by=["title"]))
        assert [item["n"] for item in result] == [1, 2]

    def test_last_keeps_last_occurrence(self):
        items = [
            {"title": "a", "n": 1},
            {"title": "b", "n": 2},
            {"title": "a", "n": 3},
        ]
        result = apply_compare(items, CompareConfig(by=["title"], keep="last"))
        assert [item["n"] for item in result] == [2, 3]

    def test_multiple_fields_form_the_key(self):
        items = [
            {"title": "a", "season": 1, "n": 1},
            {"title": "a", "season": 2, "n": 2},
            {"title": "a", "season": 1, "n": 3},
        ]
        result = apply_compare(items, CompareConfig(by=["title", "season"]))
        assert [item["n"] for item in result] == [1, 2]

    def test_composite_key_requires_every_field(self):
        items = [
            {"title": "a", "season": 1, "n": 1},
            {"title": "a", "n": 2},
        ]
        result = apply_compare(items, CompareConfig(by=["title", "season"]))
        assert [item["n"] for item in result] == [1, 2]

    def test_internal_source_url_can_group_rows_from_one_page(self):
        items = [
            {"_source_url": "http://example.com/page", "seeders": 10, "n": 1},
            {"_source_url": "http://example.com/page", "seeders": 20, "n": 2},
            {"_source_url": "http://example.com/other", "seeders": 1, "n": 3},
        ]
        result = apply_compare(
            items,
            CompareConfig(by=["_source_url"], keep="max", metric=["seeders"]),
        )
        assert [item["n"] for item in result] == [2, 3]

    def test_list_value_is_part_of_the_key(self):
        items = [
            {"tags": ["x", "y"], "n": 1},
            {"tags": ["x", "y"], "n": 2},
            {"tags": ["x"], "n": 3},
        ]
        result = apply_compare(items, CompareConfig(by=["tags"]))
        assert [item["n"] for item in result] == [1, 3]

    def test_missing_or_empty_key_is_kept(self):
        items = [
            {"title": "a", "n": 1},
            {"other": "x", "n": 2},
            {"title": "", "n": 3},
            {"title": "a", "n": 4},
        ]
        result = apply_compare(items, CompareConfig(by=["title"]))
        assert [item["n"] for item in result] == [1, 2, 3]

    def test_fewer_than_two_items_is_returned_unchanged(self):
        items = [{"title": "a"}]
        assert apply_compare(items, CompareConfig(by=["title"])) == items


class TestCompareMetric:
    def test_max_keeps_largest_numeric_metric(self):
        items = [
            {"title": "a", "size": 10, "n": 1},
            {"title": "b", "size": 1, "n": 2},
            {"title": "a", "size": 20, "n": 3},
            {"title": "a", "n": 4},
        ]
        result = apply_compare(items, CompareConfig(by=["title"], keep="max", metric=["size"]))
        assert [item["n"] for item in result] == [2, 3]

    def test_min_keeps_smallest_numeric_metric(self):
        items = [
            {"title": "a", "size": 10, "n": 1},
            {"title": "b", "size": 1, "n": 2},
            {"title": "a", "size": 20, "n": 3},
        ]
        result = apply_compare(items, CompareConfig(by=["title"], keep="min", metric=["size"]))
        assert [item["n"] for item in result] == [1, 2]

    def test_numeric_string_metric_is_supported(self):
        items = [
            {"title": "a", "size": "10", "n": 1},
            {"title": "a", "size": "20", "n": 2},
        ]
        result = apply_compare(items, CompareConfig(by=["title"], keep="max", metric=["size"]))
        assert [item["n"] for item in result] == [2]

    def test_invalid_metrics_fall_back_to_first(self):
        items = [
            {"title": "a", "size": "n/a", "n": 1},
            {"title": "a", "n": 2},
        ]
        result = apply_compare(items, CompareConfig(by=["title"], keep="max", metric=["size"]))
        assert [item["n"] for item in result] == [1]

    def test_tie_keeps_earliest(self):
        items = [
            {"title": "a", "size": 10, "n": 1},
            {"title": "a", "size": 10, "n": 2},
        ]
        result = apply_compare(items, CompareConfig(by=["title"], keep="max", metric=["size"]))
        assert [item["n"] for item in result] == [1]

    def test_missing_metric_falls_back_to_first(self):
        items = [
            {"title": "a", "n": 1},
            {"title": "a", "n": 2},
        ]
        result = apply_compare(items, CompareConfig(by=["title"], keep="max"))
        assert [item["n"] for item in result] == [1]

    def test_primary_metric_has_priority(self):
        items = [
            {"title": "a", "seeders": 10, "leechers": 5, "n": 1},
            {"title": "a", "seeders": 9, "leechers": 100, "n": 2},
        ]
        result = apply_compare(
            items,
            CompareConfig(by=["title"], keep="max", metric=["seeders", "leechers"]),
        )
        assert [item["n"] for item in result] == [1]

    def test_secondary_metric_breaks_tie(self):
        items = [
            {"title": "a", "seeders": 10, "leechers": 5, "n": 1},
            {"title": "a", "seeders": 10, "leechers": 8, "n": 2},
        ]
        result = apply_compare(
            items,
            CompareConfig(by=["title"], keep="max", metric=["seeders", "leechers"]),
        )
        assert [item["n"] for item in result] == [2]

    def test_missing_secondary_metric_only_loses_that_field(self):
        items = [
            {"title": "a", "seeders": 10, "n": 1},
            {"title": "a", "seeders": 10, "leechers": 8, "n": 2},
            {"title": "a", "seeders": 9, "leechers": 100, "n": 3},
        ]
        result = apply_compare(
            items,
            CompareConfig(by=["title"], keep="max", metric=["seeders", "leechers"]),
        )
        assert [item["n"] for item in result] == [2]

    def test_primary_metric_wins_even_with_missing_secondary(self):
        items = [
            {"title": "a", "seeders": 10, "n": 1},
            {"title": "a", "seeders": 9, "leechers": 8, "n": 2},
        ]
        result = apply_compare(
            items,
            CompareConfig(by=["title"], keep="max", metric=["seeders", "leechers"]),
        )
        assert [item["n"] for item in result] == [1]


class TestCompareLogging:
    def test_verbose_logs_dropped_duplicates(self, monkeypatch, capsys):
        monkeypatch.setattr(crawler.settings, "verbose", True)
        items = [
            {"title": "same", "n": 1},
            {"title": "same", "n": 2},
        ]
        apply_compare(items, CompareConfig(by=["title"]))
        out = capsys.readouterr().out
        assert "[compare] -drop: same" in out

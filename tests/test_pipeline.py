from __future__ import annotations

from crawler.pipeline import _collect_magnets


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

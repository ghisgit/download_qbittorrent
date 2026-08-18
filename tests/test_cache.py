from __future__ import annotations

import os
import time

from crawler.cache import HtmlCache
from crawler.config import CacheConfig


class TestHtmlCache:
    def test_roundtrip(self, tmp_path):
        cache = HtmlCache(CacheConfig(enabled=True, dir=str(tmp_path)))
        cache.put("http://example.com/a", "<html>hello</html>")
        assert cache.get("http://example.com/a") == "<html>hello</html>"

    def test_miss(self, tmp_path):
        cache = HtmlCache(CacheConfig(enabled=True, dir=str(tmp_path)))
        assert cache.get("http://example.com/never") is None

    def test_put_empty_ignored(self, tmp_path):
        cache = HtmlCache(CacheConfig(enabled=True, dir=str(tmp_path)))
        cache.put("http://example.com/a", "")
        assert cache.get("http://example.com/a") is None
        assert list(tmp_path.iterdir()) == []

    def test_ttl_expired(self, tmp_path):
        cache = HtmlCache(CacheConfig(enabled=True, dir=str(tmp_path), ttl=100))
        cache.put("http://example.com/a", "<html>x</html>")
        path = next(tmp_path.iterdir())
        old = time.time() - 200
        os.utime(path, (old, old))
        assert cache.get("http://example.com/a") is None
        assert list(tmp_path.iterdir()) == []

    def test_ttl_fresh(self, tmp_path):
        cache = HtmlCache(CacheConfig(enabled=True, dir=str(tmp_path), ttl=100))
        cache.put("http://example.com/a", "<html>x</html>")
        assert cache.get("http://example.com/a") == "<html>x</html>"

    def test_dir_created_on_put(self, tmp_path):
        cache = HtmlCache(CacheConfig(enabled=True, dir=str(tmp_path / "nested" / "dir")))
        cache.put("http://example.com/a", "<html>x</html>")
        assert (tmp_path / "nested" / "dir").is_dir()

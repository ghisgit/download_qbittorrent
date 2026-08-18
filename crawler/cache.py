from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

from .config import CacheConfig


class HtmlCache:
    """On-disk HTML cache keyed by URL.  Stores raw HTML so a re-run can
    skip fetching and replay extraction/filtering."""

    def __init__(self, cfg: CacheConfig):
        self.cfg = cfg

    def _path(self, url: str) -> Path:
        key = hashlib.sha1(url.encode("utf-8")).hexdigest()
        return Path(self.cfg.dir) / f"{key}.html"

    def get(self, url: str) -> str | None:
        path = self._path(url)
        try:
            if not path.is_file():
                return None
            if self.cfg.ttl > 0:
                age = time.time() - path.stat().st_mtime
                if age > self.cfg.ttl:
                    path.unlink(missing_ok=True)
                    return None
            html = path.read_text(encoding="utf-8")
            return html or None
        except OSError:
            return None

    def put(self, url: str, html: str) -> None:
        if not html:
            return
        path = self._path(url)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(f"{path.suffix}.tmp.{os.getpid()}")
            tmp.write_text(html, encoding="utf-8")
            os.replace(tmp, path)
        except OSError as e:
            print(f"  [cache] write error: {e}")

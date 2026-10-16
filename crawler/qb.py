from __future__ import annotations

import base64
import re
from urllib.parse import parse_qs, urlparse

import httpx

import crawler

from .config import QBConfig

_HEX_HASH_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_BASE32_HASH_RE = re.compile(r"^[A-Za-z2-7]{32}$")


def _extract_info_hash(magnet: str) -> str | None:
    """Extract a 40-char hex info hash from a magnet URI."""
    try:
        query = {key.lower(): values for key, values in parse_qs(urlparse(magnet.strip()).query).items()}
    except ValueError:
        return None

    xt_values = query.get("xt", [])
    for xt in xt_values:
        parts = xt.split(":", 2)
        if len(parts) != 3 or parts[0].lower() != "urn" or parts[1].lower() != "btih":
            continue

        raw_hash = parts[2]
        if _HEX_HASH_RE.fullmatch(raw_hash):
            return raw_hash.lower()

        if _BASE32_HASH_RE.fullmatch(raw_hash):
            try:
                decoded = base64.b32decode(raw_hash.upper())
            except ValueError:
                return None
            if len(decoded) == 20:
                return decoded.hex()

    return None


class QBClient:
    def __init__(self, cfg: QBConfig):
        self.cfg = cfg
        self._client: httpx.AsyncClient | None = None
        self._logged_in = False

    async def __aenter__(self):
        self._client = await httpx.AsyncClient(
            base_url=self.cfg.url,
            timeout=httpx.Timeout(self.cfg.timeout),
        ).__aenter__()
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.__aexit__(*args)

    async def _ensure_login(self) -> None:
        if self._logged_in:
            return
        if not self.cfg.url or not self.cfg.user or not self.cfg.password:
            raise RuntimeError("qBittorrent 未配置: 请在 YAML 中设置 qb.url / qb.user / qb.password")
        if self._client is None:
            raise RuntimeError("QB client not initialized")
        resp = await self._client.post(
            "/api/v2/auth/login",
            data={"username": self.cfg.user, "password": self.cfg.password},
        )
        resp.raise_for_status()
        self._logged_in = True
        print("[QB] 登录成功")

    def _build_params(self, category: str = "") -> dict[str, str]:
        params: dict[str, str] = {"category": category or self.cfg.category}
        if self.cfg.sequential_download:
            params["sequentialDownload"] = "true"
        if self.cfg.first_last_piece_prio:
            params["firstLastPiecePrio"] = "true"
        if self.cfg.add_to_top_of_queue:
            params["addToTopOfQueue"] = "true"
        return params

    async def _ensure_category(self, category: str) -> bool:
        """Create ``category`` if it does not exist yet."""
        assert self._client is not None
        try:
            resp = await self._client.post(
                "/api/v2/torrents/createCategory",
                data={"category": category},
            )
        except Exception as e:
            ename = type(e).__name__
            print(f"  [QB] \u2716 创建分类失败: {category} ({ename}: {e})")
            return False

        if resp.status_code in (200, 409):
            return True

        body = resp.text.strip()
        print(f"  [QB] \u2716 创建分类失败: {category} (HTTP {resp.status_code}: {body[:100]})")
        return False

    async def _set_torrent_category(self, info_hash: str, category: str) -> httpx.Response | None:
        """Call ``setCategory`` once; return ``None`` on transport exceptions."""
        assert self._client is not None
        try:
            return await self._client.post(
                "/api/v2/torrents/setCategory",
                data={"hashes": info_hash, "category": category},
            )
        except Exception as e:
            ename = type(e).__name__
            print(f"  [QB] \u2716 移动分类失败: {info_hash[:12]}... ({ename}: {e})")
            return None

    async def _move_to_category(self, magnet: str, category: str) -> bool:
        """Move an existing torrent to ``category`` by its magnet hash."""
        info_hash = _extract_info_hash(magnet)
        if not info_hash:
            print(f"  [QB] \u2716 无法解析 magnet hash: {magnet[:60]}...")
            return False

        resp = await self._set_torrent_category(info_hash, category)
        if resp is not None and resp.status_code == 200:
            return True

        # setCategory requires an existing category, so create it and retry.
        if not await self._ensure_category(category):
            return False

        retry_resp = await self._set_torrent_category(info_hash, category)
        if retry_resp is not None and retry_resp.status_code == 200:
            return True

        if retry_resp is not None:
            body = retry_resp.text.strip()
            print(f"  [QB] \u2716 移动分类失败: {magnet[:60]}... (HTTP {retry_resp.status_code}: {body[:100]})")
        return False

    async def add_magnets(self, magnets: list[str], category: str = "") -> int:
        if not magnets:
            print("[QB] 没有磁力链接, 跳过")
            return 0

        await self._ensure_login()
        effective_category = category or self.cfg.category
        base_params = self._build_params(category=effective_category)
        added = 0
        moved = 0
        existing = 0
        failed = 0
        total = len(magnets)

        for idx, magnet in enumerate(magnets, 1):
            p = dict(base_params)
            p["urls"] = magnet
            try:
                assert self._client is not None
                resp = await self._client.post("/api/v2/torrents/add", data=p)
                if resp.status_code == 200:
                    added += 1
                    if crawler.settings.verbose and total > 1:
                        print(f"  [QB] {idx}/{total} \u2713")
                elif resp.status_code == 409:
                    if not effective_category:
                        existing += 1
                        if crawler.settings.verbose:
                            print(f"  [QB] {idx}/{total} \u2713 任务已存在, 未配置分类, 跳过移动")
                    elif await self._move_to_category(magnet, effective_category):
                        moved += 1
                        if crawler.settings.verbose and total > 1:
                            print(f"  [QB] {idx}/{total} \u2713 任务已存在, 已移动到分类 {effective_category}")
                    else:
                        failed += 1
                else:
                    failed += 1
                    if crawler.settings.verbose:
                        body = resp.text.strip()
                        print(f"  [QB] \u2716 {magnet[:60]}... (HTTP {resp.status_code}: {body[:100]})")
            except Exception as e:
                failed += 1
                ename = type(e).__name__
                print(f"  [QB] \u2716 {magnet[:60]}... ({ename}: {e})")

        details: list[str] = []
        if added:
            details.append(f"新增 {added} 个")
        if moved:
            details.append(f"已存在并移动 {moved} 个")
        if existing:
            details.append(f"已存在未移动 {existing} 个")
        if failed:
            details.append(f"失败 {failed} 个")

        summary = ", ".join(details) if details else "0 个"
        if failed == 0:
            print(f"[QB] 全部处理成功: {summary}")
        else:
            print(f"[QB] 处理完成: {summary}")

        return added + moved + existing

from __future__ import annotations

import httpx

import crawler

from .config import QBConfig


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

    async def add_magnets(self, magnets: list[str], category: str = "") -> int:
        if not magnets:
            print("[QB] 没有磁力链接, 跳过")
            return 0

        await self._ensure_login()
        base_params = self._build_params(category=category)
        done = 0
        total = len(magnets)

        for idx, magnet in enumerate(magnets, 1):
            p = dict(base_params)
            p["urls"] = magnet
            ok = False
            try:
                assert self._client is not None
                resp = await self._client.post("/api/v2/torrents/add", data=p)
                if resp.status_code == 200:
                    ok = True
                elif crawler.settings.verbose:
                    body = resp.text.strip()
                    print(f"  [QB] \u2716 {magnet[:60]}... (HTTP {resp.status_code}: {body[:100]})")
            except Exception as e:
                ename = type(e).__name__
                print(f"  [QB] \u2716 {magnet[:60]}... ({ename}: {e})")
            if ok:
                done += 1
                if crawler.settings.verbose and total > 1:
                    print(f"  [QB] {idx}/{total} \u2713")

        if done == total:
            print(f"[QB] 全部添加成功: {done} 个")
        else:
            print(f"[QB] 添加完成: {done}/{total} 个 (部分失败)")

        return done

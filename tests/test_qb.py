from __future__ import annotations

import asyncio
import base64
from urllib.parse import parse_qs

import httpx

from crawler.config import QBConfig
from crawler.qb import QBClient, _extract_info_hash

HEX_HASH = "0123456789abcdef0123456789abcdef01234567"
BASE32_HASH = base64.b32encode(bytes.fromhex(HEX_HASH)).decode()


def _form(request: httpx.Request) -> dict[str, list[str]]:
    return parse_qs(request.content.decode(), keep_blank_values=True)


def _run_add_magnets(handler, magnets: list[str], category: str = "") -> int:
    async def main() -> int:
        qb = QBClient(QBConfig(url="http://qb", user="u", password="p"))
        qb._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://qb")
        qb._logged_in = True
        try:
            return await qb.add_magnets(magnets, category=category)
        finally:
            assert qb._client is not None
            await qb._client.aclose()

    return asyncio.run(main())


class TestExtractInfoHash:
    def test_hex(self):
        magnet = f"magnet:?xt=urn:btih:{HEX_HASH.upper()}&dn=test"
        assert _extract_info_hash(magnet) == HEX_HASH

    def test_base32(self):
        magnet = f"magnet:?xt=urn:btih:{BASE32_HASH}"
        assert _extract_info_hash(magnet) == HEX_HASH

    def test_invalid(self):
        assert _extract_info_hash("magnet:?xt=urn:btih:not-a-hash") is None


class TestAddMagnetsMoveExisting:
    def test_add_success_does_not_move(self):
        calls: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, request=request)

        result = _run_add_magnets(handler, [f"magnet:?xt=urn:btih:{HEX_HASH}"], category="movie")

        assert result == 1
        assert [request.url.path for request in calls] == ["/api/v2/torrents/add"]

    def test_existing_torrent_is_moved_to_category(self):
        calls: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            if request.url.path == "/api/v2/torrents/add":
                return httpx.Response(409, request=request)
            return httpx.Response(200, request=request)

        result = _run_add_magnets(
            handler,
            [f"magnet:?xt=urn:btih:{HEX_HASH}"],
            category="movie/天下",
        )

        assert result == 1
        assert [request.url.path for request in calls] == [
            "/api/v2/torrents/add",
            "/api/v2/torrents/setCategory",
        ]
        form = _form(calls[1])
        assert form["hashes"] == [HEX_HASH]
        assert form["category"] == ["movie/天下"]

    def test_move_failure_is_counted_as_failed(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/v2/torrents/add":
                return httpx.Response(409, request=request)
            return httpx.Response(409, request=request)

        result = _run_add_magnets(
            handler,
            [f"magnet:?xt=urn:btih:{HEX_HASH}"],
            category="movie",
        )

        assert result == 0

    def test_missing_category_is_created_and_set_category_is_retried(self):
        calls: list[httpx.Request] = []
        set_category_calls = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal set_category_calls
            calls.append(request)
            if request.url.path == "/api/v2/torrents/add":
                return httpx.Response(409, request=request)
            if request.url.path == "/api/v2/torrents/createCategory":
                return httpx.Response(200, request=request)
            set_category_calls += 1
            if set_category_calls == 1:
                return httpx.Response(409, request=request)
            return httpx.Response(200, request=request)

        result = _run_add_magnets(
            handler,
            [f"magnet:?xt=urn:btih:{HEX_HASH}"],
            category="movie/天下",
        )

        assert result == 1
        assert [request.url.path for request in calls] == [
            "/api/v2/torrents/add",
            "/api/v2/torrents/setCategory",
            "/api/v2/torrents/createCategory",
            "/api/v2/torrents/setCategory",
        ]
        assert _form(calls[2])["category"] == ["movie/天下"]

    def test_existing_category_conflict_still_retries_set_category(self):
        calls: list[httpx.Request] = []
        set_category_calls = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal set_category_calls
            calls.append(request)
            if request.url.path == "/api/v2/torrents/add":
                return httpx.Response(409, request=request)
            if request.url.path == "/api/v2/torrents/createCategory":
                return httpx.Response(409, request=request)
            set_category_calls += 1
            if set_category_calls == 1:
                return httpx.Response(409, request=request)
            return httpx.Response(200, request=request)

        result = _run_add_magnets(
            handler,
            [f"magnet:?xt=urn:btih:{HEX_HASH}"],
            category="movie",
        )

        assert result == 1
        assert [request.url.path for request in calls] == [
            "/api/v2/torrents/add",
            "/api/v2/torrents/setCategory",
            "/api/v2/torrents/createCategory",
            "/api/v2/torrents/setCategory",
        ]

    def test_category_creation_failure_is_counted_as_failed(self):
        calls: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            if request.url.path == "/api/v2/torrents/add":
                return httpx.Response(409, request=request)
            if request.url.path == "/api/v2/torrents/createCategory":
                return httpx.Response(500, request=request)
            return httpx.Response(409, request=request)

        result = _run_add_magnets(
            handler,
            [f"magnet:?xt=urn:btih:{HEX_HASH}"],
            category="movie",
        )

        assert result == 0
        assert [request.url.path for request in calls] == [
            "/api/v2/torrents/add",
            "/api/v2/torrents/setCategory",
            "/api/v2/torrents/createCategory",
        ]

    def test_existing_without_category_is_not_moved(self):
        calls: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(409, request=request)

        result = _run_add_magnets(handler, [f"magnet:?xt=urn:btih:{HEX_HASH}"])

        assert result == 1
        assert [request.url.path for request in calls] == ["/api/v2/torrents/add"]

    def test_unparseable_magnet_is_counted_as_failed(self):
        calls: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(409, request=request)

        result = _run_add_magnets(handler, ["not-a-magnet"], category="movie")

        assert result == 0
        assert [request.url.path for request in calls] == ["/api/v2/torrents/add"]

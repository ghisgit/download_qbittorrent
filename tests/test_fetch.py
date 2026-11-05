from __future__ import annotations

import asyncio
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

from crawler.config import BrowserConfig, CrawlerConfig, RetryConfig, StageConfig
from crawler.fetch import HttpFetcher, StealthyFetcher, handle_verify


class _FakeResponse:
    def __init__(
        self,
        status: int = 200,
        html: str = "<html>ok</html>",
        headers: dict[str, str] | None = None,
    ):
        self.status = status
        self.html_content = html
        self.headers = headers or {}


def _page_with_button(visible: bool | None) -> MagicMock:
    page = MagicMock()
    page.wait_for_load_state = AsyncMock()
    if visible is None:
        page.query_selector = AsyncMock(return_value=None)
        return page

    button = MagicMock()
    button.is_visible = AsyncMock(return_value=visible)
    button.click = AsyncMock()
    page.query_selector = AsyncMock(return_value=button)
    page.button = button
    return page


class TestHandleVerify:
    def test_clicks_visible_button(self):
        page = _page_with_button(True)
        action = handle_verify(".enter-btn")

        result = asyncio.run(action(page))

        assert result is page
        assert page.wait_for_load_state.await_count == 2
        page.query_selector.assert_awaited_once_with(".enter-btn")
        page.button.click.assert_awaited_once_with()

    def test_skips_when_button_missing(self):
        page = _page_with_button(None)
        action = handle_verify(".enter-btn")

        result = asyncio.run(action(page))

        assert result is page
        assert page.wait_for_load_state.await_count == 1
        page.query_selector.assert_awaited_once_with(".enter-btn")

    def test_skips_hidden_button(self):
        page = _page_with_button(False)
        action = handle_verify(".enter-btn")

        result = asyncio.run(action(page))

        assert result is page
        page.button.click.assert_not_awaited()


class TestStealthyFetcher:
    def test_cloudflare_is_disabled_by_default_and_builds_session(self, monkeypatch):
        captured: dict[str, Any] = {}

        class FakeSession:
            def __init__(self, **kwargs: Any):
                captured.update(kwargs)

            async def start(self) -> None:
                captured["started"] = True

            async def close(self) -> None:
                captured["closed"] = True

        monkeypatch.setattr("crawler.fetch.AsyncStealthySession", FakeSession)
        config = CrawlerConfig(
            name="t",
            stages=[StageConfig(id="s", fetcher="stealthy", concurrency=7)],
        )
        fetcher = StealthyFetcher(config)

        async def run() -> None:
            await fetcher.__aenter__()
            await fetcher.__aexit__(None, None, None)

        asyncio.run(run())

        assert captured["solve_cloudflare"] is False
        assert captured["retries"] == 1
        assert captured["max_pages"] >= 7
        assert captured["started"] is True
        assert captured["closed"] is True

    def test_passes_page_action_when_selector_configured(self, monkeypatch):
        class FakeSession:
            def __init__(self) -> None:
                self.kwargs: dict[str, Any] = {}

            async def fetch(self, url: str, **kwargs: Any) -> _FakeResponse:
                self.kwargs = kwargs
                return _FakeResponse()

        fetcher = StealthyFetcher(CrawlerConfig(name="t"))
        session = FakeSession()
        monkeypatch.setattr(fetcher, "_session", session)
        stage = StageConfig(id="s", fetcher="stealthy", security_selector=".enter-btn")

        html = asyncio.run(fetcher.fetch("http://example.com", stage, asyncio.Semaphore(1)))

        assert html == "<html>ok</html>"
        assert callable(session.kwargs["page_action"])
        assert session.kwargs["solve_cloudflare"] is False
        page_setup = session.kwargs["page_setup"]
        assert callable(page_setup)
        page = MagicMock()
        asyncio.run(cast(Any, page_setup)(page))
        page.set_default_timeout.assert_called_once_with(30000)

    def test_stage_can_enable_cloudflare(self, monkeypatch):
        class FakeSession:
            def __init__(self) -> None:
                self.kwargs: dict[str, Any] = {}

            async def fetch(self, url: str, **kwargs: Any) -> _FakeResponse:
                self.kwargs = kwargs
                return _FakeResponse()

        fetcher = StealthyFetcher(CrawlerConfig(name="t"))
        session = FakeSession()
        monkeypatch.setattr(fetcher, "_session", session)
        stage = StageConfig(id="s", fetcher="stealthy", solve_cloudflare=True)

        asyncio.run(fetcher.fetch("http://example.com", stage, asyncio.Semaphore(1)))

        assert session.kwargs["solve_cloudflare"] is True

    def test_browser_can_enable_cloudflare(self, monkeypatch):
        class FakeSession:
            def __init__(self) -> None:
                self.kwargs: dict[str, Any] = {}

            async def fetch(self, url: str, **kwargs: Any) -> _FakeResponse:
                self.kwargs = kwargs
                return _FakeResponse()

        config = CrawlerConfig(name="t", browser=BrowserConfig(solve_cloudflare=True))
        fetcher = StealthyFetcher(config)
        session = FakeSession()
        monkeypatch.setattr(fetcher, "_session", session)
        stage = StageConfig(id="s", fetcher="stealthy")

        asyncio.run(fetcher.fetch("http://example.com", stage, asyncio.Semaphore(1)))

        assert session.kwargs["solve_cloudflare"] is True

    def test_no_page_action_without_selector(self, monkeypatch):
        class FakeSession:
            def __init__(self) -> None:
                self.kwargs: dict[str, Any] = {}

            async def fetch(self, url: str, **kwargs: Any) -> _FakeResponse:
                self.kwargs = kwargs
                return _FakeResponse()

        fetcher = StealthyFetcher(CrawlerConfig(name="t"))
        session = FakeSession()
        monkeypatch.setattr(fetcher, "_session", session)
        stage = StageConfig(id="s", fetcher="stealthy")

        asyncio.run(fetcher.fetch("http://example.com", stage, asyncio.Semaphore(1)))

        assert "page_action" not in session.kwargs


class TestHttpFetcher:
    def test_retries_retryable_status_and_honors_retry_after(self, monkeypatch):
        class FakeSession:
            def __init__(self) -> None:
                self.calls = 0

            async def get(self, url: str, **kwargs: Any) -> _FakeResponse:
                self.calls += 1
                if self.calls == 1:
                    return _FakeResponse(status=429, headers={"Retry-After": "3"})
                return _FakeResponse()

        fetcher = HttpFetcher(CrawlerConfig(name="t"))
        session = FakeSession()
        monkeypatch.setattr(fetcher, "_session", session)
        sleeps: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)

        monkeypatch.setattr("crawler.fetch.asyncio.sleep", fake_sleep)
        stage = StageConfig(
            id="s",
            fetcher="http",
            retry=RetryConfig(max_retries=2, retryable_codes={429}),
        )

        html = asyncio.run(fetcher.fetch("http://example.com", stage, asyncio.Semaphore(1)))

        assert html == "<html>ok</html>"
        assert session.calls == 2
        assert sleeps == [3.0]

    def test_non_retryable_error_returns_empty(self, monkeypatch):
        class FakeSession:
            async def get(self, url: str, **kwargs: Any) -> _FakeResponse:
                return _FakeResponse(status=404, html="not found")

        fetcher = HttpFetcher(CrawlerConfig(name="t"))
        monkeypatch.setattr(fetcher, "_session", FakeSession())
        stage = StageConfig(id="s", fetcher="http")

        html = asyncio.run(fetcher.fetch("http://example.com", stage, asyncio.Semaphore(1)))

        assert html == ""

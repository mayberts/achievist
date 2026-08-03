"""
Tests for app/sgdb.py's Heroes-preferred / Grids-fallback backdrop selection.

Uses httpx.MockTransport (built into httpx, no extra test dependency) to
stub SteamGridDB responses so these run without real network access.
"""

import httpx
import pytest

from app import config
from app.sgdb import _best_backdrop, _headers, search_grid


def _json(data: dict, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=data)


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class TestHeaders:
    def test_none_without_api_key(self, monkeypatch):
        monkeypatch.setattr(config, "SGDB_API_KEY", "")
        assert _headers() is None

    def test_bearer_header_with_api_key(self, monkeypatch):
        monkeypatch.setattr(config, "SGDB_API_KEY", "secret123")
        assert _headers() == {"Authorization": "Bearer secret123"}


class TestBestBackdrop:
    async def test_prefers_hero_art(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if "/heroes/game/" in str(request.url):
                return _json({"success": True, "data": [{"url": "https://cdn/hero.png"}]})
            raise AssertionError(f"should not fetch grids when a hero exists: {request.url}")

        async with _client(handler) as client:
            url = await _best_backdrop(client, {}, 42)
        assert url == "https://cdn/hero.png"

    async def test_falls_back_to_no_logo_grid_when_no_hero(self):
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/heroes/game/" in url:
                return _json({"success": True, "data": []})
            if "/grids/game/" in url:
                if request.url.params.get("styles") == "no_logo":
                    return _json({"success": True, "data": [{"url": "https://cdn/no_logo_grid.png"}]})
                raise AssertionError("should not need the any-style grid fallback")
            raise AssertionError(f"unexpected request: {url}")

        async with _client(handler) as client:
            url = await _best_backdrop(client, {}, 42)
        assert url == "https://cdn/no_logo_grid.png"

    async def test_falls_back_to_any_grid_when_no_hero_or_no_logo_grid(self):
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/heroes/game/" in url:
                return _json({"success": True, "data": []})
            if "/grids/game/" in url:
                if request.url.params.get("styles") == "no_logo":
                    return _json({"success": True, "data": []})
                return _json({"success": True, "data": [{"url": "https://cdn/any_grid.png"}]})
            raise AssertionError(f"unexpected request: {url}")

        async with _client(handler) as client:
            url = await _best_backdrop(client, {}, 42)
        assert url == "https://cdn/any_grid.png"

    async def test_none_when_nothing_found(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _json({"success": True, "data": []})

        async with _client(handler) as client:
            url = await _best_backdrop(client, {}, 42)
        assert url is None

    async def test_none_when_heroes_endpoint_errors(self):
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/heroes/game/" in url:
                return httpx.Response(500)
            return _json({"success": True, "data": []})

        async with _client(handler) as client:
            url = await _best_backdrop(client, {}, 42)
        assert url is None


class TestSearchGrid:
    async def test_none_without_api_key(self, monkeypatch):
        monkeypatch.setattr(config, "SGDB_API_KEY", "")
        assert await search_grid("Some Game") is None

    async def test_none_when_no_search_match(self, monkeypatch):
        monkeypatch.setattr(config, "SGDB_API_KEY", "key")

        def handler(request: httpx.Request) -> httpx.Response:
            return _json({"success": True, "data": []})

        real_async_client = httpx.AsyncClient
        monkeypatch.setattr(
            httpx, "AsyncClient", lambda **kw: real_async_client(transport=httpx.MockTransport(handler))
        )
        assert await search_grid("Nonexistent Game") is None

    async def test_end_to_end_prefers_hero(self, monkeypatch):
        monkeypatch.setattr(config, "SGDB_API_KEY", "key")

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/search/autocomplete/" in url:
                return _json({"success": True, "data": [{"id": 7, "name": "Some Game"}]})
            if "/heroes/game/7" in url:
                return _json({"success": True, "data": [{"url": "https://cdn/hero.png"}]})
            raise AssertionError(f"unexpected request: {url}")

        real_async_client = httpx.AsyncClient
        monkeypatch.setattr(
            httpx, "AsyncClient", lambda **kw: real_async_client(transport=httpx.MockTransport(handler))
        )
        assert await search_grid("Some Game") == "https://cdn/hero.png"

    async def test_strips_trademark_symbols_from_name(self, monkeypatch):
        monkeypatch.setattr(config, "SGDB_API_KEY", "key")
        seen_paths = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen_paths.append(str(request.url))
            return _json({"success": True, "data": []})

        real_async_client = httpx.AsyncClient
        monkeypatch.setattr(
            httpx, "AsyncClient", lambda **kw: real_async_client(transport=httpx.MockTransport(handler))
        )
        await search_grid("Some Game®™©")
        assert any("/search/autocomplete/Some%20Game" in p for p in seen_paths)

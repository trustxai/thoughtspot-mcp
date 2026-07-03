"""Unit tests for the token lifecycle in ThoughtSpotClient (httpx mocked)."""

from __future__ import annotations

import time

import httpx
import pytest

from thoughtspot_mcp.client import ThoughtSpotClient
from thoughtspot_mcp.config import Settings, get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()


def _make_client_with_settings(monkeypatch: pytest.MonkeyPatch, **overrides: object) -> ThoughtSpotClient:
    base = {
        "thoughtspot_host": "https://ts.example.com",
        "thoughtspot_username": "svc",
        "thoughtspot_password": "pw",
    }
    base.update(overrides)
    settings = Settings(**base)  # type: ignore[arg-type]
    monkeypatch.setattr("thoughtspot_mcp.client.get_settings", lambda: settings)
    return ThoughtSpotClient()


def test_build_token_payload_prefers_secret_key(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_client_with_settings(
        monkeypatch,
        thoughtspot_secret_key="sekret",
        thoughtspot_org_id="42",
    )
    payload = client._build_token_payload()
    assert payload["secret_key"] == "sekret"
    assert "password" not in payload
    assert payload["org_identifier"] == "42"
    assert payload["username"] == "svc"


def test_build_token_payload_password_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_client_with_settings(monkeypatch)
    payload = client._build_token_payload()
    assert payload["password"] == "pw"
    assert "secret_key" not in payload


async def test_ensure_token_uses_static_token(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_client_with_settings(monkeypatch, thoughtspot_access_token="static-tok")
    async with httpx.AsyncClient() as http:
        token = await client._ensure_token(http)
    assert token == "static-tok"


async def test_ensure_token_caches_until_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_client_with_settings(monkeypatch)
    client._token = "cached"
    client._expires_at = time.time() + 100
    async with httpx.AsyncClient() as http:
        token = await client._ensure_token(http)
    assert token == "cached"


async def test_ensure_token_raises_without_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(thoughtspot_host="https://ts.example.com")  # no username/creds
    monkeypatch.setattr("thoughtspot_mcp.client.get_settings", lambda: settings)
    client = ThoughtSpotClient()
    async with httpx.AsyncClient() as http:
        with pytest.raises(RuntimeError, match="No credentials configured"):
            await client._ensure_token(http)


async def test_ensure_token_exchanges_and_sets_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_client_with_settings(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/rest/2.0/auth/token/full"
        return httpx.Response(200, json={"token": "fresh-tok", "valid_for_in_sec": 300})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        token = await client._ensure_token(http)
    assert token == "fresh-tok"
    # expiry set with the 30s safety margin
    assert client._expires_at <= time.time() + 300 - 30 + 1

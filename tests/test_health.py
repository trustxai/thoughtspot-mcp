"""Unit test for the health-check tool against a mocked client."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from thoughtspot_mcp.tools.health import thoughtspot_health_check


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeClient:
    def __init__(self, payload: dict[str, Any] | None = None, exc: Exception | None = None) -> None:
        self._payload = payload or {}
        self._exc = exc
        self.calls: list[tuple[str, str]] = []

    async def request(self, method: str, path: str, **_: Any) -> _FakeResponse:
        self.calls.append((method, path))
        if self._exc is not None:
            raise self._exc
        return _FakeResponse(self._payload)


async def test_health_check_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient(payload={"release_version": "10.4.0.cl"})
    monkeypatch.setattr("thoughtspot_mcp.tools.health.get_client", lambda: fake)

    result = await thoughtspot_health_check()

    assert "OK" in result
    assert "10.4.0.cl" in result
    assert fake.calls == [("GET", "/system")]


async def test_health_check_unknown_version(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient(payload={})
    monkeypatch.setattr("thoughtspot_mcp.tools.health.get_client", lambda: fake)

    result = await thoughtspot_health_check()

    assert "OK" in result
    assert "unknown" in result


async def test_health_check_connection_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient(exc=httpx.ConnectError("refused"))
    monkeypatch.setattr("thoughtspot_mcp.tools.health.get_client", lambda: fake)

    result = await thoughtspot_health_check()

    assert result.startswith("Error")
    assert "could not connect" in result

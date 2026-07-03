"""Unit tests for the connection tools (T1.3) against a mocked client.

These cover the endpoint traps the module is meant to abstract:
singular vs plural paths, JSON-string-on-create vs dict-on-update,
validate defaults, polymorphic search responses, 204 handling, and idempotency.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from thoughtspot_mcp.formatters import ResponseFormat
from thoughtspot_mcp.tools import connections as conn
from thoughtspot_mcp.tools.connections import (
    CreateConnectionInput,
    DeleteConnectionInput,
    GetConnectionInput,
    SearchConnectionsInput,
    SetConnectionStatusInput,
    UpdateConnectionInput,
    _extract_connections,
    thoughtspot_create_connection,
    thoughtspot_delete_connection,
    thoughtspot_get_connection,
    thoughtspot_search_connections,
    thoughtspot_set_connection_status,
    thoughtspot_update_connection,
)


class _FakeClient:
    """Records requests and returns queued httpx.Response objects (or raises)."""

    def __init__(self, responses: list[httpx.Response] | None = None, exc: Exception | None = None) -> None:
        self._responses = list(responses or [])
        self._exc = exc
        self.calls: list[dict[str, Any]] = []

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        **_: Any,
    ) -> httpx.Response:
        self.calls.append({"method": method, "path": path, "json_body": json_body, "params": params})
        if self._exc is not None:
            raise self._exc
        return self._responses.pop(0)


def _patch(monkeypatch: pytest.MonkeyPatch, client: _FakeClient) -> _FakeClient:
    monkeypatch.setattr("thoughtspot_mcp.tools.connections.get_client", lambda: client)
    return client


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def test_extract_connections_handles_bare_array() -> None:
    assert _extract_connections([{"id": "1"}]) == [{"id": "1"}]


def test_extract_connections_handles_polymorphic_keys() -> None:
    assert _extract_connections({"connections": [{"id": "a"}]}) == [{"id": "a"}]
    assert _extract_connections({"items": [{"id": "b"}]}) == [{"id": "b"}]
    assert _extract_connections({"data": [{"id": "c"}]}) == [{"id": "c"}]
    assert _extract_connections({"unknown": 1}) == []
    assert _extract_connections(None) == []


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


async def test_search_uses_singular_path_and_pagination(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _patch(
        monkeypatch,
        _FakeClient([httpx.Response(200, json=[{"id": "g1", "name": "Acme", "data_warehouse_type": "SNOWFLAKE"}])]),
    )
    result = await thoughtspot_search_connections(
        SearchConnectionsInput(data_warehouse_types=["SNOWFLAKE"], limit=25, offset=50)
    )
    call = client.calls[0]
    assert call["method"] == "POST"
    assert call["path"] == "/connection/search"
    assert call["json_body"]["record_size"] == 25
    assert call["json_body"]["record_offset"] == 50
    assert call["json_body"]["data_warehouse_types"] == ["SNOWFLAKE"]
    assert "Acme" in result


async def test_search_filter_builds_connections_array(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _patch(monkeypatch, _FakeClient([httpx.Response(200, json=[])]))
    await thoughtspot_search_connections(SearchConnectionsInput(identifier="g1", name_pattern="%x%"))
    body = client.calls[0]["json_body"]
    assert body["connections"] == [{"identifier": "g1", "name_pattern": "%x%"}]


async def test_search_json_format(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, _FakeClient([httpx.Response(200, json=[{"id": "g1", "name": "Acme"}])]))
    result = await thoughtspot_search_connections(SearchConnectionsInput(response_format=ResponseFormat.JSON))
    assert json.loads(result)["data"][0]["id"] == "g1"


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


async def test_get_matches_by_id(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = [{"id": "g1", "name": "Acme", "data_warehouse_type": "SNOWFLAKE"}]
    client = _patch(monkeypatch, _FakeClient([httpx.Response(200, json=payload)]))
    result = await thoughtspot_get_connection(GetConnectionInput(connection_id="g1"))
    assert client.calls[0]["json_body"]["include_details"] is True
    assert "Acme" in result and "g1" in result


async def test_get_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, _FakeClient([httpx.Response(200, json=[])]))
    result = await thoughtspot_get_connection(GetConnectionInput(connection_id="missing"))
    assert "No connection found" in result


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


async def test_create_serialises_config_to_json_string(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _patch(
        monkeypatch,
        _FakeClient([httpx.Response(200, json={"id": "new-guid", "name": "Acme", "data_warehouse_type": "SNOWFLAKE"})]),
    )
    cfg = {"configuration": {"user": "svc"}, "externalDatabases": []}
    result = await thoughtspot_create_connection(
        CreateConnectionInput(name="Acme", data_warehouse_config=cfg, description="d")
    )
    body = client.calls[0]["json_body"]
    assert client.calls[0]["path"] == "/connection/create"
    # config sent as a JSON STRING, not a dict, and round-trips back to the original
    assert isinstance(body["data_warehouse_config"], str)
    assert json.loads(body["data_warehouse_config"]) == cfg
    assert body["validate"] is False  # create default
    assert body["description"] == "d"
    assert "new-guid" in result


async def test_create_if_not_exists_returns_existing(monkeypatch: pytest.MonkeyPatch) -> None:
    # first call = search (found existing); create must NOT be called
    existing = [{"id": "existing-guid", "name": "Acme", "data_warehouse_type": "SNOWFLAKE"}]
    client = _patch(monkeypatch, _FakeClient([httpx.Response(200, json=existing)]))
    result = await thoughtspot_create_connection(
        CreateConnectionInput(name="Acme", data_warehouse_config={"configuration": {}}, if_not_exists=True)
    )
    assert len(client.calls) == 1
    assert client.calls[0]["path"] == "/connection/search"
    assert "already exists" in result and "existing-guid" in result


async def test_create_if_not_exists_creates_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _patch(
        monkeypatch,
        _FakeClient(
            [
                httpx.Response(200, json=[]),  # search: none found
                httpx.Response(200, json={"id": "fresh", "name": "Acme", "data_warehouse_type": "SNOWFLAKE"}),
            ]
        ),
    )
    result = await thoughtspot_create_connection(
        CreateConnectionInput(name="Acme", data_warehouse_config={"configuration": {}}, if_not_exists=True)
    )
    assert [c["path"] for c in client.calls] == ["/connection/search", "/connection/create"]
    assert "Connection created" in result and "fresh" in result


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


async def test_update_uses_plural_path_and_dict_config(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _patch(monkeypatch, _FakeClient([httpx.Response(204)]))
    cfg = {"configuration": {"user": "svc"}, "externalDatabases": [{"name": "ACME"}]}
    result = await thoughtspot_update_connection(UpdateConnectionInput(connection_id="g1", data_warehouse_config=cfg))
    call = client.calls[0]
    assert call["path"] == "/connections/g1/update"  # PLURAL
    # config passed through as a DICT (not a JSON string) on update
    assert call["json_body"]["data_warehouse_config"] == cfg
    assert call["json_body"]["validate"] is True  # update default
    assert "updated successfully" in result


async def test_update_rename_only(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _patch(monkeypatch, _FakeClient([httpx.Response(204)]))
    await thoughtspot_update_connection(
        UpdateConnectionInput(connection_id="g1", name="New Name", validate_config=False)
    )
    body = client.calls[0]["json_body"]
    assert body["name"] == "New Name"
    assert body["validate"] is False
    assert "data_warehouse_config" not in body


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


async def test_set_status_posts_enum(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _patch(monkeypatch, _FakeClient([httpx.Response(204)]))
    result = await thoughtspot_set_connection_status(SetConnectionStatusInput(connection_id="g1", status="DEACTIVATED"))
    call = client.calls[0]
    assert call["path"] == "/connections/g1/status"
    assert call["json_body"] == {"status": "DEACTIVATED"}
    assert "DEACTIVATED" in result


def test_status_rejects_invalid_value() -> None:
    with pytest.raises(ValueError):
        SetConnectionStatusInput(connection_id="g1", status="ON")


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


async def test_delete_uses_plural_path(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _patch(monkeypatch, _FakeClient([httpx.Response(204)]))
    result = await thoughtspot_delete_connection(DeleteConnectionInput(connection_id="g1"))
    call = client.calls[0]
    assert call["path"] == "/connections/g1/delete"  # PLURAL
    assert call["json_body"] == {}
    assert "deleted" in result


async def test_delete_annotation_is_destructive() -> None:
    tools = await conn.mcp.list_tools()
    tool = next(t for t in tools if t.name == "thoughtspot_delete_connection")
    assert tool.annotations is not None
    assert tool.annotations.destructiveHint is True


# ---------------------------------------------------------------------------
# error handling
# ---------------------------------------------------------------------------


async def test_error_handling_surfaces_message(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, _FakeClient(exc=httpx.ConnectError("refused")))
    result = await thoughtspot_search_connections(SearchConnectionsInput())
    assert result.startswith("Error")
    assert "could not connect" in result


async def test_success_json_format_on_204(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, _FakeClient([httpx.Response(204)]))
    result = await thoughtspot_delete_connection(
        DeleteConnectionInput(connection_id="g1", response_format=ResponseFormat.JSON)
    )
    parsed = json.loads(result)
    assert parsed["ok"] is True
    assert parsed["data"] is None

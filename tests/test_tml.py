"""Unit tests for the TML tools (task T1.2) against a mocked client."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from thoughtspot_mcp.formatters import ResponseFormat
from thoughtspot_mcp.tools.tml import (
    AsyncImportTmlInput,
    ExportTmlInput,
    ImportTmlInput,
    TmlImportStatusInput,
    _extract_import_statuses,
    _extract_tml_identity,
    thoughtspot_async_import_tml,
    thoughtspot_export_tml,
    thoughtspot_get_tml_import_status,
    thoughtspot_import_tml,
)

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def json(self) -> Any:
        return self._payload


class _FakeClient:
    def __init__(self, payload: Any = None, exc: Exception | None = None) -> None:
        self._payload = payload
        self._exc = exc
        self.calls: list[dict[str, Any]] = []

    async def request(
        self, method: str, path: str, *, json_body: dict[str, Any] | None = None, **_: Any
    ) -> _FakeResponse:
        self.calls.append({"method": method, "path": path, "json_body": json_body})
        if self._exc is not None:
            raise self._exc
        return _FakeResponse(self._payload)


def _patch(monkeypatch: pytest.MonkeyPatch, fake: _FakeClient) -> None:
    monkeypatch.setattr("thoughtspot_mcp.tools.tml.get_client", lambda: fake)


# Sample YAML edocs as returned by /metadata/tml/export.
_CONN_EDOC = "guid: conn-guid-1\nconnection:\n  name: BADGER Analytics\n  type: SNOWFLAKE\n"
_TABLE_EDOC = "guid: tbl-guid-1\ntable:\n  name: ORDER_LINES\n  db: BADGER\n"


# ---------------------------------------------------------------------------
# _extract_tml_identity
# ---------------------------------------------------------------------------


def test_extract_identity_connection() -> None:
    assert _extract_tml_identity(_CONN_EDOC) == ("connection", "BADGER Analytics", "conn-guid-1")


def test_extract_identity_table() -> None:
    assert _extract_tml_identity(_TABLE_EDOC) == ("table", "ORDER_LINES", "tbl-guid-1")


def test_extract_identity_quoted_name() -> None:
    tml = 'guid: g9\ntable:\n  name: "Quoted Name"\n  db: X\n'
    assert _extract_tml_identity(tml) == ("table", "Quoted Name", "g9")


def test_extract_identity_ignores_nested_guid() -> None:
    # A nested guid (indented) must not override the top-level one.
    tml = "guid: top-guid\nliveboard:\n  name: LB\n  guid: nested-guid\n"
    obj_type, name, guid = _extract_tml_identity(tml)
    assert (obj_type, name, guid) == ("liveboard", "LB", "top-guid")


def test_extract_identity_empty() -> None:
    assert _extract_tml_identity("") == (None, None, None)


# ---------------------------------------------------------------------------
# _extract_import_statuses (shape polymorphism)
# ---------------------------------------------------------------------------


def test_extract_statuses_list_with_response() -> None:
    body = [
        {"response": {"status": {"status_code": "OK"}, "header": {"id_guid": "g1", "name": "M1"}}},
    ]
    statuses = _extract_import_statuses(body)
    assert statuses == [{"status_code": "OK", "error_message": None, "name": "M1", "guid": "g1", "type": None}]


def test_extract_statuses_dict_object_key() -> None:
    body = {
        "object": [
            {"status": {"status_code": "ERROR", "error_message": "bad tml"}, "header": {"name": "X"}},
        ]
    }
    statuses = _extract_import_statuses(body)
    assert statuses[0]["status_code"] == "ERROR"
    assert statuses[0]["error_message"] == "bad tml"
    assert statuses[0]["name"] == "X"


# ---------------------------------------------------------------------------
# thoughtspot_export_tml
# ---------------------------------------------------------------------------


async def test_export_basic_markdown(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = [
        {
            "info": {"name": "My Liveboard", "type": "LIVEBOARD", "id": "lb1", "status": {"status_code": "OK"}},
            "edoc": "guid: lb1\nliveboard:\n  name: My Liveboard\n",
        },
    ]
    fake = _FakeClient(payload=payload)
    _patch(monkeypatch, fake)

    result = await thoughtspot_export_tml(ExportTmlInput(object_identifiers=["lb1"], export_associated=True))

    assert "Exported **1** object(s)" in result
    assert "My Liveboard" in result
    assert "`lb1`" in result
    body = fake.calls[0]["json_body"]
    assert body["metadata"] == [{"identifier": "lb1"}]
    assert body["export_associated"] is True
    assert body["export_fqn"] is False


async def test_export_with_type(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient(payload=[])
    _patch(monkeypatch, fake)

    await thoughtspot_export_tml(ExportTmlInput(object_identifiers=["ORDERS"], object_type="LOGICAL_TABLE"))

    assert fake.calls[0]["json_body"]["metadata"] == [{"identifier": "ORDERS", "type": "LOGICAL_TABLE"}]


async def test_export_harvest_forces_flags_and_builds_map(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = [
        {"edoc": _CONN_EDOC},
        {"edoc": _TABLE_EDOC},
    ]
    fake = _FakeClient(payload=payload)
    _patch(monkeypatch, fake)

    result = await thoughtspot_export_tml(ExportTmlInput(object_identifiers=["conn-guid-1"], harvest_fqns=True))

    # Harvest mode forces these flags regardless of defaults.
    body = fake.calls[0]["json_body"]
    assert body["export_associated"] is True
    assert body["export_fqn"] is True
    assert body["edoc_format"] == "YAML"
    # Map surfaces connection + table FQNs.
    assert "conn-guid-1" in result
    assert "tbl-guid-1" in result
    assert "BADGER Analytics" in result
    assert "ORDER_LINES" in result


async def test_export_harvest_json(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = [{"edoc": _CONN_EDOC}, {"edoc": _TABLE_EDOC}]
    fake = _FakeClient(payload=payload)
    _patch(monkeypatch, fake)

    result = await thoughtspot_export_tml(
        ExportTmlInput(
            object_identifiers=["conn-guid-1"],
            harvest_fqns=True,
            response_format=ResponseFormat.JSON,
        )
    )
    data = json.loads(result)
    assert data["fqns"]["connection"] == {"BADGER Analytics": "conn-guid-1"}
    assert data["fqns"]["table"] == {"ORDER_LINES": "tbl-guid-1"}
    assert data["objects_exported"] == 2
    assert data["unparsed"] == 0


async def test_export_dict_metadata_content_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    # Some releases wrap edocs under "metadata_content".
    payload = {"metadata_content": [{"edoc": _TABLE_EDOC}]}
    fake = _FakeClient(payload=payload)
    _patch(monkeypatch, fake)

    result = await thoughtspot_export_tml(ExportTmlInput(object_identifiers=["tbl-guid-1"], harvest_fqns=True))
    assert "tbl-guid-1" in result


async def test_export_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient(payload=[])
    _patch(monkeypatch, fake)
    result = await thoughtspot_export_tml(ExportTmlInput(object_identifiers=["nope"]))
    assert "No TML exported" in result


async def test_export_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient(exc=httpx.ConnectError("refused"))
    _patch(monkeypatch, fake)
    result = await thoughtspot_export_tml(ExportTmlInput(object_identifiers=["x"]))
    assert result.startswith("Error")
    assert "could not connect" in result


# ---------------------------------------------------------------------------
# thoughtspot_import_tml
# ---------------------------------------------------------------------------


async def test_import_success(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = [
        {"response": {"status": {"status_code": "OK"}, "header": {"id_guid": "g1", "name": "Model A"}}},
    ]
    fake = _FakeClient(payload=payload)
    _patch(monkeypatch, fake)

    result = await thoughtspot_import_tml(ImportTmlInput(metadata_tmls=["guid: g1\nmodel:\n  name: Model A\n"]))

    assert "1/1" in result
    assert "Model A" in result
    assert "✅" in result
    body = fake.calls[0]["json_body"]
    assert body["import_policy"] == "PARTIAL"
    assert body["create_new"] is False


async def test_import_partial_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = [
        {"response": {"status": {"status_code": "OK"}, "header": {"name": "Good"}}},
        {
            "response": {
                "status": {"status_code": "ERROR", "error_message": "invalid column"},
                "header": {"name": "Bad"},
            }
        },
    ]
    fake = _FakeClient(payload=payload)
    _patch(monkeypatch, fake)

    result = await thoughtspot_import_tml(ImportTmlInput(metadata_tmls=["a", "b"], create_new=True))
    assert "1/2" in result
    assert "invalid column" in result
    assert fake.calls[0]["json_body"]["create_new"] is True


async def test_import_json(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = [{"response": {"status": {"status_code": "OK"}, "header": {"name": "M"}}}]
    fake = _FakeClient(payload=payload)
    _patch(monkeypatch, fake)
    result = await thoughtspot_import_tml(ImportTmlInput(metadata_tmls=["x"], response_format=ResponseFormat.JSON))
    assert json.loads(result) == payload


# ---------------------------------------------------------------------------
# thoughtspot_async_import_tml
# ---------------------------------------------------------------------------


async def test_async_import(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"task_id": "task-123", "task_status": "IN_QUEUE", "total_object_count": 3}
    fake = _FakeClient(payload=payload)
    _patch(monkeypatch, fake)

    result = await thoughtspot_async_import_tml(
        AsyncImportTmlInput(metadata_tmls=["a", "b", "c"], import_policy="ALL_OR_NONE")
    )
    assert "task-123" in result
    assert "IN_QUEUE" in result
    assert "thoughtspot_get_tml_import_status" in result
    assert fake.calls[0]["path"] == "/metadata/tml/async/import"
    assert fake.calls[0]["json_body"]["import_policy"] == "ALL_OR_NONE"


# ---------------------------------------------------------------------------
# thoughtspot_get_tml_import_status
# ---------------------------------------------------------------------------


async def test_status_basic(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "tasks": [
            {"task_id": "task-123", "task_status": "COMPLETED", "object_processed_count": 3, "total_object_count": 3},
        ]
    }
    fake = _FakeClient(payload=payload)
    _patch(monkeypatch, fake)

    result = await thoughtspot_get_tml_import_status(TmlImportStatusInput(task_ids=["task-123"]))
    assert "task-123" in result
    assert "COMPLETED" in result
    assert "3/3" in result
    assert fake.calls[0]["json_body"]["task_ids"] == ["task-123"]


async def test_status_with_import_response_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = [
        {
            "task_id": "t1",
            "task_status": "FAILED",
            "total_object_count": 2,
            "object_processed_count": 2,
            "import_response": [
                {"response": {"status": {"status_code": "OK"}, "header": {"name": "Good"}}},
                {"response": {"status": {"status_code": "ERROR", "error_message": "boom"}, "header": {"name": "Bad"}}},
            ],
        }
    ]
    fake = _FakeClient(payload=payload)
    _patch(monkeypatch, fake)

    result = await thoughtspot_get_tml_import_status(
        TmlImportStatusInput(task_ids=["t1"], include_import_response=True)
    )
    assert "FAILED" in result
    assert "1/2 OK" in result
    assert "boom" in result


async def test_status_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient(payload={"tasks": []})
    _patch(monkeypatch, fake)
    result = await thoughtspot_get_tml_import_status(TmlImportStatusInput())
    assert "No matching TML import tasks" in result


async def test_status_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient(exc=httpx.TimeoutException("slow"))
    _patch(monkeypatch, fake)
    result = await thoughtspot_get_tml_import_status(TmlImportStatusInput(task_ids=["t1"]))
    assert result.startswith("Error")
    assert "timed out" in result

"""Unit tests for the metadata tools against a mocked client."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from thoughtspot_mcp.tools.metadata import (
    DeleteMetadataInput,
    SearchMetadataInput,
    thoughtspot_delete_metadata,
    thoughtspot_search_metadata,
)


class _FakeResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def json(self) -> Any:
        return self._payload


class _FakeClient:
    """Records requests and replays a queue of canned responses in order."""

    def __init__(self, responses: list[Any] | None = None, exc: Exception | None = None) -> None:
        self._responses = list(responses or [])
        self._exc = exc
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        **_: Any,
    ) -> _FakeResponse:
        self.calls.append((method, path, json_body))
        if self._exc is not None:
            raise self._exc
        payload = self._responses.pop(0) if self._responses else []
        return _FakeResponse(payload)


LIVEBOARD_ITEM = {
    "metadata_id": "lb-guid-1",
    "metadata_name": "Sales Overview",
    "metadata_type": "LIVEBOARD",
}
MODEL_ITEM = {
    "metadata_id": "model-guid-1",
    "metadata_name": "Sales Model",
    "metadata_type": "LOGICAL_TABLE",
    "metadata_header": {"type": "WORKSHEET"},
}


# ---------------------------------------------------------------------------
# thoughtspot_search_metadata
# ---------------------------------------------------------------------------


async def test_search_metadata_basic_markdown(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient(responses=[[LIVEBOARD_ITEM]])
    monkeypatch.setattr("thoughtspot_mcp.tools.metadata.get_client", lambda: fake)

    result = await thoughtspot_search_metadata(SearchMetadataInput(type="LIVEBOARD"))

    assert "Sales Overview" in result
    assert "lb-guid-1" in result
    assert len(fake.calls) == 1
    method, path, body = fake.calls[0]
    assert (method, path) == ("POST", "/metadata/search")
    assert body is not None
    assert body["metadata"] == [{"type": "LIVEBOARD"}]


async def test_search_metadata_json_format(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient(responses=[[LIVEBOARD_ITEM]])
    monkeypatch.setattr("thoughtspot_mcp.tools.metadata.get_client", lambda: fake)

    result = await thoughtspot_search_metadata(SearchMetadataInput(type="LIVEBOARD", response_format="json"))

    assert "lb-guid-1" in result
    assert "Sales Overview" in result


async def test_search_metadata_no_results(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient(responses=[[]])
    monkeypatch.setattr("thoughtspot_mcp.tools.metadata.get_client", lambda: fake)

    result = await thoughtspot_search_metadata(SearchMetadataInput(type="LIVEBOARD"))

    assert result == "No metadata objects found."


async def test_search_metadata_model_alias_resolves_to_logical_table_worksheet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeClient(responses=[[MODEL_ITEM]])
    monkeypatch.setattr("thoughtspot_mcp.tools.metadata.get_client", lambda: fake)

    result = await thoughtspot_search_metadata(SearchMetadataInput(type="MODEL", name_pattern="Sales%"))

    assert "Sales Model" in result
    method, path, body = fake.calls[0]
    assert body is not None
    assert body["metadata"] == [{"type": "LOGICAL_TABLE", "subtypes": ["WORKSHEET"], "name_pattern": "Sales%"}]


async def test_search_metadata_falls_back_unfiltered_when_type_scoped_search_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeClient(responses=[[], [MODEL_ITEM]])
    monkeypatch.setattr("thoughtspot_mcp.tools.metadata.get_client", lambda: fake)

    result = await thoughtspot_search_metadata(SearchMetadataInput(type="MODEL", name_pattern="Sales%"))

    assert "Sales Model" in result
    assert len(fake.calls) == 2
    first_body = fake.calls[0][2]
    second_body = fake.calls[1][2]
    assert first_body is not None and "type" in first_body["metadata"][0]
    assert second_body is not None
    assert second_body["metadata"] == [{"name_pattern": "Sales%"}]


async def test_search_metadata_no_fallback_without_name_pattern(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient(responses=[[]])
    monkeypatch.setattr("thoughtspot_mcp.tools.metadata.get_client", lambda: fake)

    result = await thoughtspot_search_metadata(SearchMetadataInput(type="LIVEBOARD"))

    assert result == "No metadata objects found."
    assert len(fake.calls) == 1


async def test_search_metadata_dict_wrapped_response_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient(responses=[{"metadata": [LIVEBOARD_ITEM]}])
    monkeypatch.setattr("thoughtspot_mcp.tools.metadata.get_client", lambda: fake)

    result = await thoughtspot_search_metadata(SearchMetadataInput(type="LIVEBOARD"))

    assert "Sales Overview" in result


async def test_search_metadata_unfiltered_when_no_filters_given(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient(responses=[[LIVEBOARD_ITEM]])
    monkeypatch.setattr("thoughtspot_mcp.tools.metadata.get_client", lambda: fake)

    result = await thoughtspot_search_metadata(SearchMetadataInput())

    assert "Sales Overview" in result
    body = fake.calls[0][2]
    assert body is not None
    assert "metadata" not in body


async def test_search_metadata_connection_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient(exc=httpx.ConnectError("refused"))
    monkeypatch.setattr("thoughtspot_mcp.tools.metadata.get_client", lambda: fake)

    result = await thoughtspot_search_metadata(SearchMetadataInput(type="LIVEBOARD"))

    assert result.startswith("Error")
    assert "could not connect" in result


# ---------------------------------------------------------------------------
# thoughtspot_delete_metadata
# ---------------------------------------------------------------------------


async def test_delete_metadata_single_identifier(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient(responses=[None])
    monkeypatch.setattr("thoughtspot_mcp.tools.metadata.get_client", lambda: fake)

    result = await thoughtspot_delete_metadata(DeleteMetadataInput(identifiers=["guid-1"]))

    assert "Deleted 1 metadata object" in result
    assert "guid-1" in result
    method, path, body = fake.calls[0]
    assert (method, path) == ("POST", "/metadata/delete")
    assert body == {"metadata": [{"identifier": "guid-1"}], "delete_disabled_objects": False}


async def test_delete_metadata_multiple_with_type(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient(responses=[None])
    monkeypatch.setattr("thoughtspot_mcp.tools.metadata.get_client", lambda: fake)

    result = await thoughtspot_delete_metadata(
        DeleteMetadataInput(
            identifiers=["Old Model", "Another Model"],
            type="LOGICAL_TABLE",
            delete_disabled_objects=True,
        )
    )

    assert "Deleted 2 metadata object" in result
    body = fake.calls[0][2]
    assert body == {
        "metadata": [
            {"identifier": "Old Model", "type": "LOGICAL_TABLE"},
            {"identifier": "Another Model", "type": "LOGICAL_TABLE"},
        ],
        "delete_disabled_objects": True,
    }


async def test_delete_metadata_error_handling(monkeypatch: pytest.MonkeyPatch) -> None:
    request = httpx.Request("POST", "https://example.thoughtspot.cloud/api/rest/2.0/metadata/delete")
    response = httpx.Response(404, request=request, json={"message": "not found"})
    fake = _FakeClient(exc=httpx.HTTPStatusError("not found", request=request, response=response))
    monkeypatch.setattr("thoughtspot_mcp.tools.metadata.get_client", lambda: fake)

    result = await thoughtspot_delete_metadata(DeleteMetadataInput(identifiers=["missing-guid"]))

    assert result.startswith("Error (404)")

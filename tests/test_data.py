"""Unit tests for the data-query tools against a mocked client."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from thoughtspot_mcp.tools.data import (
    MAX_DISPLAY_ROWS,
    GetAnswerDataInput,
    GetLiveboardDataInput,
    SearchDataInput,
    _row_values,
    thoughtspot_get_answer_data,
    thoughtspot_get_liveboard_data,
    thoughtspot_search_data,
)


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeClient:
    def __init__(self, payload: dict[str, Any] | None = None, exc: Exception | None = None) -> None:
        self._payload = payload or {}
        self._exc = exc
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def request(self, method: str, path: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append((method, path, kwargs))
        if self._exc is not None:
            raise self._exc
        return _FakeResponse(self._payload)


def _search_payload(rows: list[Any] | None = None) -> dict[str, Any]:
    return {
        "contents": [
            {
                "column_names": ["store", "sales"],
                "data_rows": rows if rows is not None else [{"store": "Downtown", "sales": 1200}],
                "available_data_row_count": 1,
                "returned_data_row_count": 1,
                "sampling_ratio": 1.0,
                "record_offset": 0,
                "record_size": 50,
            }
        ]
    }


# ---------------------------------------------------------------------------
# _row_values
# ---------------------------------------------------------------------------


def test_row_values_list_passthrough() -> None:
    assert _row_values(["a", 1], ["col1", "col2"]) == ["a", 1]


def test_row_values_dict_keyed_by_column() -> None:
    assert _row_values({"col2": 1, "col1": "a"}, ["col1", "col2"]) == ["a", 1]


def test_row_values_dict_without_matching_columns() -> None:
    assert _row_values({"0": "a", "1": 1}, ["col1", "col2"]) == ["a", 1]


def test_row_values_scalar() -> None:
    assert _row_values(42, ["col1"]) == [42]


# ---------------------------------------------------------------------------
# thoughtspot_search_data
# ---------------------------------------------------------------------------


async def test_search_data_markdown(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient(payload=_search_payload())
    monkeypatch.setattr("thoughtspot_mcp.tools.data.get_client", lambda: fake)

    result = await thoughtspot_search_data(
        SearchDataInput(query_string="[sales] by [store]", logical_table_identifier="guid-1")
    )

    assert "Search Results" in result
    assert "| store | sales |" in result
    assert "Downtown" in result
    method, path, kwargs = fake.calls[0]
    assert method == "POST"
    assert path == "/searchdata"
    body = kwargs["json_body"]
    assert body["query_string"] == "[sales] by [store]"
    assert body["logical_table_identifier"] == "guid-1"
    assert body["data_format"] == "COMPACT"
    assert "runtime_filter" not in body


async def test_search_data_json(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient(payload=_search_payload())
    monkeypatch.setattr("thoughtspot_mcp.tools.data.get_client", lambda: fake)

    result = await thoughtspot_search_data(
        SearchDataInput(
            query_string="[sales] by [store]",
            logical_table_identifier="guid-1",
            response_format="json",
        )
    )

    assert '"display_truncated": false' in result
    assert '"store": "Downtown"' in result


async def test_search_data_no_results(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient(payload={"contents": []})
    monkeypatch.setattr("thoughtspot_mcp.tools.data.get_client", lambda: fake)

    result = await thoughtspot_search_data(SearchDataInput(query_string="[sales]", logical_table_identifier="guid-1"))

    assert result == "No data returned for this query."


async def test_search_data_truncates_display(monkeypatch: pytest.MonkeyPatch) -> None:
    many_rows = [{"store": f"Store {i}", "sales": i} for i in range(MAX_DISPLAY_ROWS + 10)]
    fake = _FakeClient(payload=_search_payload(rows=many_rows))
    monkeypatch.setattr("thoughtspot_mcp.tools.data.get_client", lambda: fake)

    result = await thoughtspot_search_data(
        SearchDataInput(query_string="[sales]", logical_table_identifier="guid-1", record_size=500)
    )

    assert f"Display truncated to the first {MAX_DISPLAY_ROWS}" in result
    assert f"of {len(many_rows)} rows" in result


async def test_search_data_runtime_overrides_included(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient(payload=_search_payload())
    monkeypatch.setattr("thoughtspot_mcp.tools.data.get_client", lambda: fake)

    await thoughtspot_search_data(
        SearchDataInput(
            query_string="[sales] by [item type]",
            logical_table_identifier="guid-1",
            runtime_filter={"col1": "item type", "op1": "EQ", "val1": "Bags"},
            runtime_sort={"sortCol1": "sales", "asc1": True},
            runtime_param_override={"param1": "Double List Param", "paramVal1": 0.5},
        )
    )

    body = fake.calls[0][2]["json_body"]
    assert body["runtime_filter"] == {"col1": "item type", "op1": "EQ", "val1": "Bags"}
    assert body["runtime_sort"] == {"sortCol1": "sales", "asc1": True}
    assert body["runtime_param_override"] == {"param1": "Double List Param", "paramVal1": 0.5}


async def test_search_data_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient(exc=httpx.ConnectError("refused"))
    monkeypatch.setattr("thoughtspot_mcp.tools.data.get_client", lambda: fake)

    result = await thoughtspot_search_data(SearchDataInput(query_string="[sales]", logical_table_identifier="guid-1"))

    assert result.startswith("Error")
    assert "could not connect" in result


# ---------------------------------------------------------------------------
# thoughtspot_get_liveboard_data
# ---------------------------------------------------------------------------


def _liveboard_payload() -> dict[str, Any]:
    return {
        "metadata_id": "lb-1",
        "metadata_name": "Sales Overview",
        "contents": [
            {
                "visualization_id": "viz-1",
                "visualization_name": "Revenue by Region",
                "column_names": ["region", "revenue"],
                "data_rows": [{"region": "West", "revenue": 5000}],
                "available_data_row_count": 1,
                "returned_data_row_count": 1,
                "sampling_ratio": 1.0,
            }
        ],
    }


async def test_get_liveboard_data_markdown(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient(payload=_liveboard_payload())
    monkeypatch.setattr("thoughtspot_mcp.tools.data.get_client", lambda: fake)

    result = await thoughtspot_get_liveboard_data(GetLiveboardDataInput(metadata_identifier="lb-1"))

    assert "Sales Overview" in result
    assert "Revenue by Region" in result
    assert "West" in result
    method, path, kwargs = fake.calls[0]
    assert method == "POST"
    assert path == "/metadata/liveboard/data"
    assert kwargs["json_body"]["metadata_identifier"] == "lb-1"


async def test_get_liveboard_data_with_visualization_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient(payload=_liveboard_payload())
    monkeypatch.setattr("thoughtspot_mcp.tools.data.get_client", lambda: fake)

    await thoughtspot_get_liveboard_data(
        GetLiveboardDataInput(
            metadata_identifier="lb-1",
            visualization_identifiers=["viz-1"],
            transient_content="transient-blob",
        )
    )

    body = fake.calls[0][2]["json_body"]
    assert body["visualization_identifiers"] == ["viz-1"]
    assert body["transient_content"] == "transient-blob"


async def test_get_liveboard_data_no_results(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient(payload={"metadata_id": "lb-1", "metadata_name": "Empty LB", "contents": []})
    monkeypatch.setattr("thoughtspot_mcp.tools.data.get_client", lambda: fake)

    result = await thoughtspot_get_liveboard_data(GetLiveboardDataInput(metadata_identifier="lb-1"))

    assert "No data returned for Liveboard **Empty LB**" in result


async def test_get_liveboard_data_json(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient(payload=_liveboard_payload())
    monkeypatch.setattr("thoughtspot_mcp.tools.data.get_client", lambda: fake)

    result = await thoughtspot_get_liveboard_data(
        GetLiveboardDataInput(metadata_identifier="lb-1", response_format="json")
    )

    assert '"metadata_name": "Sales Overview"' in result
    assert '"display_truncated": false' in result


async def test_get_liveboard_data_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient(
        exc=httpx.HTTPStatusError("not found", request=httpx.Request("POST", "https://x"), response=httpx.Response(404))
    )
    monkeypatch.setattr("thoughtspot_mcp.tools.data.get_client", lambda: fake)

    result = await thoughtspot_get_liveboard_data(GetLiveboardDataInput(metadata_identifier="missing"))

    assert result.startswith("Error (404)")


# ---------------------------------------------------------------------------
# thoughtspot_get_answer_data
# ---------------------------------------------------------------------------


def _answer_payload() -> dict[str, Any]:
    return {
        "metadata_id": "ans-1",
        "metadata_name": "Top Products",
        "contents": [
            {
                "column_names": ["product", "units"],
                "data_rows": [{"product": "Widget", "units": 42}],
                "available_data_row_count": 1,
                "returned_data_row_count": 1,
                "sampling_ratio": 1.0,
            }
        ],
    }


async def test_get_answer_data_markdown(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient(payload=_answer_payload())
    monkeypatch.setattr("thoughtspot_mcp.tools.data.get_client", lambda: fake)

    result = await thoughtspot_get_answer_data(GetAnswerDataInput(metadata_identifier="ans-1"))

    assert "Top Products" in result
    assert "Widget" in result
    method, path, kwargs = fake.calls[0]
    assert method == "POST"
    assert path == "/metadata/answer/data"
    assert kwargs["json_body"]["metadata_identifier"] == "ans-1"


async def test_get_answer_data_no_results(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient(payload={"metadata_id": "ans-1", "metadata_name": "Empty Answer", "contents": []})
    monkeypatch.setattr("thoughtspot_mcp.tools.data.get_client", lambda: fake)

    result = await thoughtspot_get_answer_data(GetAnswerDataInput(metadata_identifier="ans-1"))

    assert "No data returned for Answer **Empty Answer**" in result


async def test_get_answer_data_json(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient(payload=_answer_payload())
    monkeypatch.setattr("thoughtspot_mcp.tools.data.get_client", lambda: fake)

    result = await thoughtspot_get_answer_data(GetAnswerDataInput(metadata_identifier="ans-1", response_format="json"))

    assert '"metadata_name": "Top Products"' in result


async def test_get_answer_data_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient(exc=httpx.ConnectError("refused"))
    monkeypatch.setattr("thoughtspot_mcp.tools.data.get_client", lambda: fake)

    result = await thoughtspot_get_answer_data(GetAnswerDataInput(metadata_identifier="ans-1"))

    assert result.startswith("Error")

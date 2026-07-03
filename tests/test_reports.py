"""Unit tests for report-export tools against a mocked client."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from thoughtspot_mcp.tools.reports import (
    ExportAnswerReportInput,
    ExportLiveboardReportInput,
    thoughtspot_export_answer_report,
    thoughtspot_export_liveboard_report,
)


class _FakeResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content


class _FakeClient:
    def __init__(self, content: bytes = b"", exc: Exception | None = None) -> None:
        self._content = content
        self._exc = exc
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []

    async def request(
        self, method: str, path: str, *, json_body: dict[str, Any] | None = None, **_: Any
    ) -> _FakeResponse:
        self.calls.append((method, path, json_body))
        if self._exc is not None:
            raise self._exc
        return _FakeResponse(self._content)


# ---------------------------------------------------------------------------
# thoughtspot_export_liveboard_report
# ---------------------------------------------------------------------------


async def test_export_liveboard_report_writes_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = _FakeClient(content=b"%PDF-1.4 fake bytes")
    monkeypatch.setattr("thoughtspot_mcp.tools.reports.get_client", lambda: fake)
    output_path = tmp_path / "liveboard.pdf"

    result = await thoughtspot_export_liveboard_report(
        ExportLiveboardReportInput(metadata_identifier="lb-guid", output_path=str(output_path))
    )

    assert "exported successfully" in result
    assert "PDF" in result
    assert str(output_path) in result
    assert output_path.read_bytes() == b"%PDF-1.4 fake bytes"
    assert fake.calls == [("POST", "/report/liveboard", {"metadata_identifier": "lb-guid", "file_format": "PDF"})]


async def test_export_liveboard_report_creates_parent_dirs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = _FakeClient(content=b"csv-bytes")
    monkeypatch.setattr("thoughtspot_mcp.tools.reports.get_client", lambda: fake)
    output_path = tmp_path / "nested" / "dir" / "liveboard.csv"

    result = await thoughtspot_export_liveboard_report(
        ExportLiveboardReportInput(metadata_identifier="lb-guid", output_path=str(output_path), file_format="CSV")
    )

    assert "exported successfully" in result
    assert output_path.exists()
    assert output_path.read_bytes() == b"csv-bytes"


async def test_export_liveboard_report_passes_optional_fields(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = _FakeClient(content=b"bytes")
    monkeypatch.setattr("thoughtspot_mcp.tools.reports.get_client", lambda: fake)
    output_path = tmp_path / "liveboard.xlsx"

    await thoughtspot_export_liveboard_report(
        ExportLiveboardReportInput(
            metadata_identifier="lb-guid",
            output_path=str(output_path),
            file_format="XLSX",
            visualization_identifiers=["viz-1", "viz-2"],
            tab_identifiers=["tab-1"],
            runtime_filter={"col1": "region", "op1": "EQ", "val1": "northeast"},
        )
    )

    _, _, body = fake.calls[0]
    assert body == {
        "metadata_identifier": "lb-guid",
        "file_format": "XLSX",
        "visualization_identifiers": ["viz-1", "viz-2"],
        "tab_identifiers": ["tab-1"],
        "runtime_filter": {"col1": "region", "op1": "EQ", "val1": "northeast"},
    }


async def test_export_liveboard_report_api_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    request = httpx.Request("POST", "https://ts.example.com/api/rest/2.0/report/liveboard")
    response = httpx.Response(403, request=request, json={"message": "no download privilege"})
    fake = _FakeClient(exc=httpx.HTTPStatusError("forbidden", request=request, response=response))
    monkeypatch.setattr("thoughtspot_mcp.tools.reports.get_client", lambda: fake)

    result = await thoughtspot_export_liveboard_report(
        ExportLiveboardReportInput(metadata_identifier="lb-guid", output_path=str(tmp_path / "out.pdf"))
    )

    assert result.startswith("Error (403)")
    assert not (tmp_path / "out.pdf").exists()


async def test_export_liveboard_report_write_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = _FakeClient(content=b"bytes")
    monkeypatch.setattr("thoughtspot_mcp.tools.reports.get_client", lambda: fake)

    def _boom(self: Path, data: bytes) -> int:
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_bytes", _boom)

    result = await thoughtspot_export_liveboard_report(
        ExportLiveboardReportInput(metadata_identifier="lb-guid", output_path=str(tmp_path / "out.pdf"))
    )

    assert result.startswith("Error")
    assert "disk full" in result


# ---------------------------------------------------------------------------
# thoughtspot_export_answer_report
# ---------------------------------------------------------------------------


async def test_export_answer_report_with_metadata_identifier(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = _FakeClient(content=b"col1,col2\n1,2\n")
    monkeypatch.setattr("thoughtspot_mcp.tools.reports.get_client", lambda: fake)
    output_path = tmp_path / "answer.csv"

    result = await thoughtspot_export_answer_report(
        ExportAnswerReportInput(metadata_identifier="answer-guid", output_path=str(output_path))
    )

    assert "exported successfully" in result
    assert "CSV" in result
    assert output_path.read_bytes() == b"col1,col2\n1,2\n"
    assert fake.calls == [("POST", "/report/answer", {"metadata_identifier": "answer-guid", "file_format": "CSV"})]


async def test_export_answer_report_with_session_identifier(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = _FakeClient(content=b"pdf-bytes")
    monkeypatch.setattr("thoughtspot_mcp.tools.reports.get_client", lambda: fake)
    output_path = tmp_path / "answer.pdf"

    result = await thoughtspot_export_answer_report(
        ExportAnswerReportInput(
            session_identifier="session-guid",
            generation_number=3,
            output_path=str(output_path),
            file_format="PDF",
        )
    )

    assert "exported successfully" in result
    _, _, body = fake.calls[0]
    assert body == {
        "file_format": "PDF",
        "session_identifier": "session-guid",
        "generation_number": 3,
    }


async def test_export_answer_report_requires_an_identifier(tmp_path: Path) -> None:
    result = await thoughtspot_export_answer_report(ExportAnswerReportInput(output_path=str(tmp_path / "answer.csv")))

    assert result.startswith("Error")
    assert "metadata_identifier" in result
    assert not (tmp_path / "answer.csv").exists()


async def test_export_answer_report_api_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    request = httpx.Request("POST", "https://ts.example.com/api/rest/2.0/report/answer")
    response = httpx.Response(404, request=request, json={"message": "answer not found"})
    fake = _FakeClient(exc=httpx.HTTPStatusError("not found", request=request, response=response))
    monkeypatch.setattr("thoughtspot_mcp.tools.reports.get_client", lambda: fake)

    result = await thoughtspot_export_answer_report(
        ExportAnswerReportInput(metadata_identifier="missing-guid", output_path=str(tmp_path / "out.csv"))
    )

    assert result.startswith("Error (404)")

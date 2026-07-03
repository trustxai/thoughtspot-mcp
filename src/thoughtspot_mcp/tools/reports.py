"""Report-export tools for the ThoughtSpot API (Wave A — task T1.5).

Covers:
    - thoughtspot_export_liveboard_report: POST /report/liveboard.
    - thoughtspot_export_answer_report: POST /report/answer.

Both endpoints return raw ``application/octet-stream`` bytes (PDF, PNG, CSV,
or XLSX) rather than JSON. Per ADR-0002 (``.memory/decisions/``), the tools
write those bytes to a caller-provided ``output_path`` on disk and return a
short confirmation instead of inlining file content — inlining (e.g. base64)
would bloat the LLM context with payloads that can run multi-MB.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field

from thoughtspot_mcp.client import get_client
from thoughtspot_mcp.errors import handle_api_error
from thoughtspot_mcp.server import mcp

# ---------------------------------------------------------------------------
# Shared types
# ---------------------------------------------------------------------------


class LiveboardReportFormat(StrEnum):
    PDF = "PDF"
    PNG = "PNG"
    CSV = "CSV"
    XLSX = "XLSX"


class AnswerReportFormat(StrEnum):
    CSV = "CSV"
    PDF = "PDF"
    XLSX = "XLSX"
    PNG = "PNG"


# ---------------------------------------------------------------------------
# Input models
# ---------------------------------------------------------------------------


class ExportLiveboardReportInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    metadata_identifier: str = Field(..., min_length=1, description="GUID or name of the Liveboard to export.")
    output_path: str = Field(
        ...,
        min_length=1,
        description="Local filesystem path to write the exported file to. Parent directories are created if missing.",
    )
    file_format: LiveboardReportFormat = Field(
        default=LiveboardReportFormat.PDF,
        description="Export format: PDF, PNG, CSV, or XLSX.",
    )
    visualization_identifiers: list[str] | None = Field(
        default=None,
        description="GUIDs or names of specific visualizations to include. Omit to export all visualizations on the Liveboard.",
    )
    tab_identifiers: list[str] | None = Field(
        default=None,
        description="GUIDs or names of specific Liveboard tabs to include. Omit to export all tabs.",
    )
    runtime_filter: dict[str, Any] | None = Field(
        default=None,
        description=(
            'Runtime filter to apply, e.g. {"col1": "region", "op1": "EQ", "val1": "northeast"}. '
            "Add more filters by incrementing the number suffix (col2/op2/val2, ...)."
        ),
    )


class ExportAnswerReportInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    metadata_identifier: str | None = Field(
        default=None,
        description="GUID or name of the saved Answer to export. Required unless session_identifier is given.",
    )
    session_identifier: str | None = Field(
        default=None,
        description="Unique ID of an unsaved Answer session (used with generation_number instead of metadata_identifier).",
    )
    generation_number: int | None = Field(
        default=None,
        description="Generation number of the Answer session. Required when session_identifier is given.",
    )
    output_path: str = Field(
        ...,
        min_length=1,
        description="Local filesystem path to write the exported file to. Parent directories are created if missing.",
    )
    file_format: AnswerReportFormat = Field(
        default=AnswerReportFormat.CSV,
        description="Export format: CSV, PDF, XLSX, or PNG.",
    )
    runtime_filter: dict[str, Any] | None = Field(
        default=None,
        description=(
            'Runtime filter to apply, e.g. {"col1": "region", "op1": "EQ", "val1": "northeast"}. '
            "Add more filters by incrementing the number suffix (col2/op2/val2, ...)."
        ),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_report_bytes(content: bytes, output_path: str) -> Path:
    """Write exported report bytes to disk, creating parent dirs if needed."""
    path = Path(output_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _fmt_export_result(path: Path, size: int, file_format: str, label: str) -> str:
    return (
        f"{label} exported successfully.\n- **Format**: {file_format}\n- **Path**: `{path}`\n- **Size**: {size:,} bytes"
    )


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool(
    name="thoughtspot_export_liveboard_report",
    annotations=ToolAnnotations(
        title="Export ThoughtSpot Liveboard Report",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
)
async def thoughtspot_export_liveboard_report(params: ExportLiveboardReportInput) -> str:
    """Export a Liveboard (and its visualizations) as a PDF, PNG, CSV, or XLSX file.

    Requires at least view access to the Liveboard, plus the relevant download
    privilege (CAN_DOWNLOAD_DETAILED_DATA for CSV/XLSX, CAN_DOWNLOAD_VISUALS for
    PNG/PDF) if RBAC is enabled. The API returns raw file bytes, which this tool
    writes to ``output_path`` on the MCP server's local filesystem rather than
    inlining them in the response (see ADR-0002 — large reports would blow past
    a usable LLM context budget).

    When to Use:
        - Generate a shareable snapshot of a Liveboard for offline viewing.
        - Export detailed data (CSV/XLSX) or a visual snapshot (PDF/PNG).
        - Export only specific tabs or visualizations instead of the whole Liveboard.

    When NOT to Use:
        - To query live data programmatically — use thoughtspot_get_liveboard_data instead.

    Returns:
        A confirmation with the resolved output path, format, and byte size on
        success. On failure, a human-readable error with the root cause.

    Examples:
        Full Liveboard as PDF:
            params = { "metadata_identifier": "a1b2c3d4-...", "output_path": "/tmp/liveboard.pdf" }
        Specific visualizations as XLSX:
            params = {
                "metadata_identifier": "a1b2c3d4-...",
                "output_path": "/tmp/liveboard.xlsx",
                "file_format": "XLSX",
                "visualization_identifiers": ["viz-guid-1", "viz-guid-2"],
            }

    Error Handling:
        Returns a descriptive message for permission (403), not-found (404), and
        invalid-request (400) errors, as well as local filesystem write failures.
    """
    try:
        body: dict[str, Any] = {
            "metadata_identifier": params.metadata_identifier,
            "file_format": params.file_format.value,
        }
        if params.visualization_identifiers:
            body["visualization_identifiers"] = params.visualization_identifiers
        if params.tab_identifiers:
            body["tab_identifiers"] = params.tab_identifiers
        if params.runtime_filter:
            body["runtime_filter"] = params.runtime_filter

        client = get_client()
        resp = await client.request("POST", "/report/liveboard", json_body=body)

        path = _write_report_bytes(resp.content, params.output_path)
        return _fmt_export_result(path, len(resp.content), params.file_format.value, "Liveboard report")
    except Exception as exc:
        return handle_api_error(exc)


@mcp.tool(
    name="thoughtspot_export_answer_report",
    annotations=ToolAnnotations(
        title="Export ThoughtSpot Answer Report",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
)
async def thoughtspot_export_answer_report(params: ExportAnswerReportInput) -> str:
    """Export an Answer as a CSV, PDF, XLSX, or PNG file.

    Accepts either a saved Answer's ``metadata_identifier``, or an unsaved
    Answer session's ``session_identifier`` + ``generation_number`` pair. The
    API returns raw file bytes, which this tool writes to ``output_path`` on
    the MCP server's local filesystem rather than inlining them (see ADR-0002).

    When to Use:
        - Export a saved Answer's data or visualization for offline use.
        - Export an in-progress (unsaved) Answer session's current state.

    When NOT to Use:
        - To query live Answer data programmatically — use thoughtspot_get_answer_data instead.

    Returns:
        A confirmation with the resolved output path, format, and byte size on
        success. On failure, a human-readable error with the root cause.

    Examples:
        Saved Answer as CSV:
            params = { "metadata_identifier": "a1b2c3d4-...", "output_path": "/tmp/answer.csv" }
        Unsaved Answer session as PDF:
            params = {
                "session_identifier": "session-guid",
                "generation_number": 3,
                "output_path": "/tmp/answer.pdf",
                "file_format": "PDF",
            }

    Error Handling:
        Returns a descriptive message for permission (403), not-found (404), and
        invalid-request (400) errors — including when neither identifier is given
        — as well as local filesystem write failures.
    """
    try:
        if not params.metadata_identifier and not params.session_identifier:
            return "Error: provide either metadata_identifier or session_identifier + generation_number."

        body: dict[str, Any] = {"file_format": params.file_format.value}
        if params.metadata_identifier:
            body["metadata_identifier"] = params.metadata_identifier
        if params.session_identifier:
            body["session_identifier"] = params.session_identifier
        if params.generation_number is not None:
            body["generation_number"] = params.generation_number
        if params.runtime_filter:
            body["runtime_filter"] = params.runtime_filter

        client = get_client()
        resp = await client.request("POST", "/report/answer", json_body=body)

        path = _write_report_bytes(resp.content, params.output_path)
        return _fmt_export_result(path, len(resp.content), params.file_format.value, "Answer report")
    except Exception as exc:
        return handle_api_error(exc)

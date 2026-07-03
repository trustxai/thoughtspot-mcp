"""Unit tests for formatting helpers."""

from __future__ import annotations

from thoughtspot_mcp.formatters import (
    ResponseFormat,
    epoch_to_human,
    paginated_response,
    to_json,
    truncate_records,
)


def test_epoch_to_human_seconds() -> None:
    assert epoch_to_human(1782894600).endswith("UTC")


def test_epoch_to_human_millis() -> None:
    # A millisecond timestamp should be normalised, not projected far into the future.
    assert epoch_to_human(1782894600000).startswith("2026")


def test_epoch_to_human_none() -> None:
    assert epoch_to_human(None) == "N/A"


def test_truncate_records_under_limit() -> None:
    records, truncated = truncate_records([1, 2, 3], 5)
    assert records == [1, 2, 3]
    assert truncated is False


def test_truncate_records_over_limit() -> None:
    records, truncated = truncate_records([1, 2, 3, 4, 5], 3)
    assert records == [1, 2, 3]
    assert truncated is True


def test_to_json_roundtrip() -> None:
    assert '"a": 1' in to_json({"a": 1})


def test_paginated_response_markdown() -> None:
    output = paginated_response(
        items=[{"guid": "1"}],
        total=10,
        limit=1,
        offset=0,
        fmt=ResponseFormat.MARKDOWN,
        title="Objects",
    )
    assert "# Objects" in output
    assert "total **10**" in output
    assert "next offset → **1**" in output


def test_paginated_response_json() -> None:
    output = paginated_response(
        items=[{"guid": "1"}],
        total=10,
        limit=1,
        offset=0,
        fmt=ResponseFormat.JSON,
    )
    assert '"has_more": true' in output
    assert '"total": 10' in output

"""TML (ThoughtSpot Modeling Language) tools (Wave A — task T1.2).

Tools:
    - ``thoughtspot_export_tml``: POST /metadata/tml/export. Exports object
      definitions as TML (YAML/JSON). Supports ``export_associated`` /
      ``export_fqn`` / ``export_dependent`` and a **FQN-harvest convenience
      mode** that parses the exported edocs and returns a ``{type: {name: guid}}``
      map — the trick the masava staging-data-loader uses to inject FQNs into a
      new model TML before importing it.
    - ``thoughtspot_import_tml``: POST /metadata/tml/import with per-object
      status reporting (import policy, create-new).
    - ``thoughtspot_async_import_tml``: POST /metadata/tml/async/import for large
      imports; returns a ``task_id`` to poll.
    - ``thoughtspot_get_tml_import_status``: POST /metadata/tml/async/status.
      The async-status family is rate-limited to ~100 req/min — poll gently.

The v2.0 export/import responses are loosely typed (the OpenAPI spec models the
items as bare ``object``) and their shapes vary across releases, so the helpers
below defensively probe several known keys (``edoc``/``content``,
``response.status``/``status``, ``id_guid``/``guid``) rather than assuming one
layout. FQN parsing avoids a hard PyYAML dependency by extracting only the
top-level ``guid`` and object type/name via a tiny line scanner.
"""

from __future__ import annotations

from typing import Any, Literal

from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field

from thoughtspot_mcp.client import get_client
from thoughtspot_mcp.errors import handle_api_error
from thoughtspot_mcp.formatters import ResponseFormat, to_json
from thoughtspot_mcp.server import mcp

# Top-level TML object types (the key that appears at column 0 in an edoc,
# alongside the top-level ``guid``). Used by the FQN-harvest parser.
_TML_TYPE_KEYS = (
    "connection",
    "table",
    "sql_view",
    "view",
    "worksheet",
    "model",
    "liveboard",
    "answer",
    "pinboard",
)

EdocFormat = Literal["YAML", "JSON"]
SchemaVersion = Literal["DEFAULT", "V1", "V2"]
ImportPolicy = Literal["PARTIAL", "ALL_OR_NONE", "VALIDATE_ONLY", "PARTIAL_OBJECT"]

# ---------------------------------------------------------------------------
# Input models
# ---------------------------------------------------------------------------


class ExportTmlInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    object_identifiers: list[str] = Field(
        ...,
        min_length=1,
        description="GUIDs (or names) of the objects to export. When names are used, "
        "set object_type as well — the API requires a type to disambiguate a name.",
    )
    object_type: (
        Literal[
            "LIVEBOARD",
            "ANSWER",
            "LOGICAL_TABLE",
            "CONNECTION",
            "CUSTOM_ACTION",
            "USER",
            "USER_GROUP",
            "ROLE",
            "FEEDBACK",
            "COLLECTION",
        ]
        | None
    ) = Field(
        default=None,
        description="Object type applied to every identifier. Required when identifiers are names rather than GUIDs.",
    )
    export_associated: bool = Field(
        default=False,
        description="Also export associated objects (e.g. a Liveboard's underlying model).",
    )
    export_fqn: bool = Field(
        default=False,
        description="Add FQNs of referenced objects to the exported TML. Enable this to "
        "later re-import against the same references.",
    )
    export_dependent: bool = Field(
        default=False,
        description="When exporting a connection, also export its dependent tables.",
    )
    export_connection_as_dependent: bool = Field(
        default=False,
        description="When exporting a table/model, also export its connection as a dependent.",
    )
    edoc_format: EdocFormat = Field(default="YAML", description="TML content format: YAML or JSON.")
    export_schema_version: SchemaVersion = Field(
        default="DEFAULT",
        description="Worksheet/model TML schema version: DEFAULT, V1, or V2.",
    )
    harvest_fqns: bool = Field(
        default=False,
        description="Convenience mode: force export_associated + export_fqn + YAML, parse "
        "each exported edoc, and return a {type: {name: guid}} FQN map instead of raw TML. "
        "Use this to collect the GUIDs needed to wire up a new model/liveboard TML.",
    )
    include_content: bool = Field(
        default=True,
        description="Inline the raw TML of each object (default). Set false to return only "
        "per-object metadata (name, type, GUID, status, content size) — useful to inspect a "
        "large export cheaply, then re-export a single object to get its full TML. The response "
        "is always capped at ~900 KB to stay under the client's 1 MB tool-result limit; oversized "
        "content is truncated with a note regardless of this flag.",
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class ImportTmlInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    metadata_tmls: list[str] = Field(
        ...,
        min_length=1,
        description="TML object definitions to import, each as a full YAML (or JSON) string.",
    )
    import_policy: ImportPolicy = Field(
        default="PARTIAL",
        description="PARTIAL imports valid objects and reports failures per object; "
        "ALL_OR_NONE rolls back the whole batch on any failure; VALIDATE_ONLY checks "
        "without persisting; PARTIAL_OBJECT imports the valid parts of each object.",
    )
    create_new: bool = Field(
        default=False,
        description="Create brand-new objects with fresh GUIDs instead of updating existing ones.",
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class AsyncImportTmlInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    metadata_tmls: list[str] = Field(
        ...,
        min_length=1,
        description="TML object definitions to import asynchronously, each as a full string.",
    )
    import_policy: ImportPolicy = Field(
        default="PARTIAL",
        description="Import policy for the async batch (see thoughtspot_import_tml).",
    )
    create_new: bool = Field(
        default=False,
        description="Create brand-new objects with fresh GUIDs instead of updating existing ones.",
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class TmlImportStatusInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    task_ids: list[str] | None = Field(
        default=None,
        description="Task IDs returned by thoughtspot_async_import_tml. Omit to list recent tasks.",
    )
    task_status: list[Literal["IN_QUEUE", "IN_PROGRESS", "COMPLETED", "FAILED"]] | None = Field(
        default=None,
        description="Filter to tasks in these statuses.",
    )
    include_import_response: bool = Field(
        default=False,
        description="Include the full per-object import response for each task (verbose).",
    )
    record_offset: int = Field(default=0, ge=0, description="Pagination offset (record_offset).")
    record_size: int = Field(default=50, ge=1, le=1000, description="Max tasks to return (record_size).")
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


# ---------------------------------------------------------------------------
# Response helpers (defensive against v2.0 shape polymorphism)
# ---------------------------------------------------------------------------

# Cap the whole tool result comfortably under the 1 MB tool-result limit that
# MCP clients (notably Claude Desktop: "Tool result is too large. Maximum size
# is 1MB.") enforce, leaving headroom for the JSON-RPC envelope wrapped around
# this string. Exporting a Liveboard with ``export_associated`` pulls in the
# underlying model plus every referenced table, whose combined TML easily
# exceeds 1 MB — without this guard the client rejects the entire result and the
# caller sees nothing at all.
MAX_TML_RESPONSE_BYTES = 900_000

# Headroom reserved while building the per-object markdown for the closing
# guidance note (truncated/omitted object names).
_FOOTER_RESERVE_BYTES = 800


def _utf8_len(text: str) -> int:
    return len(text.encode("utf-8"))


def _truncate_to_bytes(text: str, max_bytes: int) -> tuple[str, bool]:
    """Cut ``text`` so its UTF-8 encoding fits in ``max_bytes``.

    Returns ``(text, truncated)``; the cut lands on a UTF-8 boundary so the
    result is always valid text.
    """
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text, False
    if max_bytes <= 0:
        return "", True
    return encoded[:max_bytes].decode("utf-8", errors="ignore"), True


def _clamp_response(text: str) -> str:
    """Final safety net: guarantee any returned string fits the byte budget."""
    if _utf8_len(text) <= MAX_TML_RESPONSE_BYTES:
        return text
    suffix = "\n\n… _[response truncated to fit the tool-result size limit]_"
    clipped, _ = _truncate_to_bytes(text, MAX_TML_RESPONSE_BYTES - _utf8_len(suffix))
    return clipped + suffix


def _render_export_markdown(edocs: list[Any], *, include_content: bool) -> str:
    """Build the export markdown, keeping the total under the byte budget.

    Every object's metadata (name / type / GUID / status) is always listed;
    inlined TML content is truncated — or omitted for later objects once the
    budget runs out — with an explicit note, mirroring the row-truncation guard
    the data tools use.
    """
    lines = ["# Exported TML", "", f"Exported **{len(edocs)}** object(s).", ""]
    if not include_content:
        lines.append("_Metadata only — set `include_content: true` to inline the TML._")
        lines.append("")

    truncated: list[str] = []
    omitted: list[str] = []
    fence_overhead = _utf8_len("\n```yaml\n\n```\n")

    for edoc in edocs:
        info = _edoc_info(edoc)
        status = info.get("status", {})
        status_code = status.get("status_code", "?") if isinstance(status, dict) else "?"
        name = info.get("name", "(unnamed)")
        guid = info.get("id", info.get("id_guid", "?"))
        obj_type = info.get("type", "?")

        lines.append(f"## {name} ({obj_type})")
        lines.append(f"- GUID: `{guid}`  •  status: {status_code}")

        content = _edoc_content(edoc) if include_content else ""
        if not content:
            lines.append("")
            continue

        body = content.rstrip()
        used = _utf8_len("\n".join(lines))
        content_budget = MAX_TML_RESPONSE_BYTES - used - _FOOTER_RESERVE_BYTES - fence_overhead

        if content_budget <= 0:
            omitted.append(str(name))
            lines.append(f"- _TML content omitted ({_utf8_len(body)} bytes) — response size limit reached._")
            lines.append("")
            continue

        clipped, was_truncated = _truncate_to_bytes(body, content_budget)
        lines.append("")
        lines.append("```yaml")
        lines.append(clipped.rstrip("\n"))
        lines.append("```")
        if was_truncated:
            truncated.append(str(name))
            lines.append(
                f"- ⚠️ _TML truncated ({_utf8_len(clipped)} of {_utf8_len(body)} bytes shown) "
                f"to fit the response size limit._"
            )
        lines.append("")

    if truncated or omitted:
        note = f"⚠️ Response capped at ~{MAX_TML_RESPONSE_BYTES // 1000} KB to stay under the client tool-result limit."
        if truncated:
            note += f" Truncated: {', '.join(truncated)}."
        if omitted:
            note += f" Content omitted: {', '.join(omitted)}."
        note += (
            " For complete TML, export one object at a time (or with `export_associated: false`), "
            "or use `harvest_fqns: true` if you only need the GUIDs."
        )
        lines.append("---")
        lines.append(note)

    return _clamp_response("\n".join(lines))


def _export_metadata_summary(edocs: list[Any]) -> list[dict[str, Any]]:
    """Small per-object summary used when a full export is too large for JSON."""
    summary: list[dict[str, Any]] = []
    for edoc in edocs:
        info = _edoc_info(edoc)
        summary.append(
            {
                "name": info.get("name"),
                "type": info.get("type"),
                "guid": info.get("id", info.get("id_guid")),
                "content_bytes": _utf8_len(_edoc_content(edoc)),
            }
        )
    return summary


def _edoc_records(body: Any) -> list[Any]:
    """Normalise an export response to a list of edoc records."""
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        content = body.get("metadata_content", body.get("edocs", body.get("data")))
        if isinstance(content, list):
            return content
    return []


def _edoc_content(edoc: Any) -> str:
    """Extract the raw TML string from one edoc record."""
    if isinstance(edoc, str):
        return edoc
    if isinstance(edoc, dict):
        return str(edoc.get("edoc", edoc.get("content", edoc.get("metadata", "")) or ""))
    return ""


def _edoc_info(edoc: Any) -> dict[str, Any]:
    if isinstance(edoc, dict):
        info = edoc.get("info", {})
        if isinstance(info, dict):
            return info
    return {}


def _extract_tml_identity(tml: str) -> tuple[str | None, str | None, str | None]:
    """Pull (type, name, guid) from a YAML TML string without a YAML parser.

    Reads only column-0 keys: the top-level ``guid`` and the first recognised
    object-type key, plus the first ``name:`` nested beneath that type. This is
    the "raw-YAML fallback parser" the export/import flows rely on.
    """
    guid: str | None = None
    obj_type: str | None = None
    name: str | None = None
    in_type_block = False

    for raw in tml.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))

        if indent == 0:
            key = stripped.split(":", 1)[0].strip()
            if key == "guid" and guid is None:
                guid = _yaml_scalar(stripped)
            elif key in _TML_TYPE_KEYS and obj_type is None:
                obj_type = key
                in_type_block = True
            elif key not in ("guid",):
                # Left the type block (some other top-level key).
                in_type_block = in_type_block and key == obj_type
        elif in_type_block and name is None and stripped.split(":", 1)[0].strip() == "name":
            name = _yaml_scalar(stripped)

    return obj_type, name, guid


def _yaml_scalar(line: str) -> str | None:
    """Return the scalar value after the first colon, unquoted."""
    if ":" not in line:
        return None
    value = line.split(":", 1)[1].strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return value or None


def _extract_import_statuses(body: Any) -> list[dict[str, Any]]:
    """Normalise an import response to a list of per-object status dicts."""
    if isinstance(body, dict):
        items = body.get("object", body.get("data", body.get("metadata", [])))
    elif isinstance(body, list):
        items = body
    else:
        items = []
    if not isinstance(items, list):
        return []

    statuses: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            statuses.append({"status_code": "UNKNOWN", "raw": item})
            continue
        response = item.get("response", item)
        status = response.get("status", item.get("status", {}))
        if not isinstance(status, dict):
            status = {}
        header = response.get("header", item.get("header", {}))
        if not isinstance(header, dict):
            header = {}
        statuses.append(
            {
                "status_code": status.get("status_code", "UNKNOWN"),
                "error_message": status.get("error_message", status.get("error_code")),
                "name": header.get("name", item.get("name")),
                "guid": header.get("id_guid", header.get("guid", item.get("response_guid"))),
                "type": header.get("type", item.get("type")),
            }
        )
    return statuses


def _fmt_import_statuses(statuses: list[dict[str, Any]], title: str) -> str:
    ok = sum(1 for s in statuses if s.get("status_code") == "OK")
    lines = [f"# {title}", "", f"**{ok}/{len(statuses)}** object(s) succeeded.", ""]
    for s in statuses:
        code = s.get("status_code", "UNKNOWN")
        mark = "✅" if code == "OK" else "❌"
        name = s.get("name") or "(unnamed)"
        guid = s.get("guid") or "?"
        lines.append(f"- {mark} **{name}** (`{guid}`) — {code}")
        if code != "OK" and s.get("error_message"):
            lines.append(f"    - {s['error_message']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool(
    name="thoughtspot_export_tml",
    annotations=ToolAnnotations(
        title="Export ThoughtSpot TML",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
)
async def thoughtspot_export_tml(params: ExportTmlInput) -> str:
    """Export ThoughtSpot objects as TML (ThoughtSpot Modeling Language).

    Exports Liveboards, Answers, Models/Worksheets, Tables, or Connections as
    portable TML for backup, version control, or re-import into another instance.

    When to Use:
        - Back up or version-control object definitions as TML.
        - Harvest FQN GUIDs to wire up a new model/liveboard before importing it
          (set ``harvest_fqns: true``).
        - Migrate objects between orgs/instances (export here, import there).

    When NOT to Use:
        - To read the *data* behind an object — use the data-query tools instead.

    FQN-harvest mode (``harvest_fqns: true``):
        Forces ``export_associated`` + ``export_fqn`` + YAML, parses every
        exported edoc, and returns a ``{type: {name: guid}}`` map (e.g. the
        connection GUID plus each table GUID) rather than raw TML — the exact
        shortcut needed to inject FQNs into a freshly generated model TML.

    Size limit:
        The result is always capped at ~900 KB so it stays under the 1 MB
        tool-result limit MCP clients (e.g. Claude Desktop) enforce. A large
        export — a Liveboard with ``export_associated`` brings in its model and
        every table — has its inlined TML truncated (with a note) rather than
        returning an oversized result the client would reject. Set
        ``include_content: false`` to list only per-object metadata, or export
        one object at a time to retrieve its full TML.

    Returns:
        Markdown (or JSON) with one section per exported object (type, name,
        GUID, status, and the TML content), or — in harvest mode — the FQN map.

    Examples:
        Export a liveboard with its dependencies:
            { "object_identifiers": ["<liveboard-guid>"], "export_associated": true }
        Harvest connection + table FQNs:
            { "object_identifiers": ["<connection-guid>"], "harvest_fqns": true }

    Error Handling:
        Returns a descriptive message on connection, auth (401), not-found (404),
        or rate-limit (429) failures.
    """
    try:
        metadata: list[dict[str, Any]] = []
        for identifier in params.object_identifiers:
            entry: dict[str, Any] = {"identifier": identifier}
            if params.object_type:
                entry["type"] = params.object_type
            metadata.append(entry)

        harvest = params.harvest_fqns
        json_body: dict[str, Any] = {
            "metadata": metadata,
            "export_associated": True if harvest else params.export_associated,
            "export_fqn": True if harvest else params.export_fqn,
            "export_dependent": True if harvest else params.export_dependent,
            "export_connection_as_dependent": params.export_connection_as_dependent,
            "edoc_format": "YAML" if harvest else params.edoc_format,
            "export_schema_version": params.export_schema_version,
        }

        client = get_client()
        resp = await client.request("POST", "/metadata/tml/export", json_body=json_body)
        body = resp.json()
        edocs = _edoc_records(body)

        if harvest:
            fqn_map: dict[str, dict[str, str]] = {}
            unparsed = 0
            for edoc in edocs:
                obj_type, name, guid = _extract_tml_identity(_edoc_content(edoc))
                if guid and obj_type:
                    fqn_map.setdefault(obj_type, {})[name or guid] = guid
                else:
                    unparsed += 1
            if params.response_format == ResponseFormat.JSON:
                return to_json({"fqns": fqn_map, "objects_exported": len(edocs), "unparsed": unparsed})
            if not fqn_map:
                return "No FQNs harvested — the export returned no parseable TML objects."
            lines = ["# Harvested FQNs", "", f"Parsed **{len(edocs)}** exported object(s)."]
            if unparsed:
                lines.append(f"⚠️ {unparsed} edoc(s) could not be parsed for a GUID.")
            lines.append("")
            for obj_type in sorted(fqn_map):
                lines.append(f"## {obj_type}")
                for name, guid in fqn_map[obj_type].items():
                    lines.append(f"- **{name}**: `{guid}`")
                lines.append("")
            return "\n".join(lines)

        if params.response_format == ResponseFormat.JSON:
            out = to_json(body)
            if _utf8_len(out) <= MAX_TML_RESPONSE_BYTES:
                return out
            # Too large to return raw JSON without breaching the client limit —
            # downgrade to a valid, compact metadata-only summary rather than
            # emit an oversized (and thus rejected) payload.
            return to_json(
                {
                    "error": "response_too_large",
                    "message": (
                        f"Export exceeded the ~{MAX_TML_RESPONSE_BYTES // 1000} KB tool-result limit; "
                        "returning a metadata-only summary. Export one object at a time for full TML."
                    ),
                    "objects_exported": len(edocs),
                    "objects": _export_metadata_summary(edocs),
                }
            )

        if not edocs:
            return "No TML exported — check the object identifiers and type."

        return _render_export_markdown(edocs, include_content=params.include_content)
    except Exception as exc:
        return handle_api_error(exc)


@mcp.tool(
    name="thoughtspot_import_tml",
    annotations=ToolAnnotations(
        title="Import ThoughtSpot TML",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    ),
)
async def thoughtspot_import_tml(params: ImportTmlInput) -> str:
    """Import (create or update) ThoughtSpot objects from TML definitions.

    Sends one or more TML strings to ``/metadata/tml/import`` and reports the
    per-object outcome. By default (import policy ``PARTIAL``) valid objects are
    imported and failures are reported individually.

    When to Use:
        - Create or update models, liveboards, answers, or tables from TML.
        - Restore objects previously exported with ``thoughtspot_export_tml``.
        - Validate TML without persisting (``import_policy: "VALIDATE_ONLY"``).

    When NOT to Use:
        - For very large batches — prefer ``thoughtspot_async_import_tml`` so the
          call does not block on a long-running import.

    Important:
        Use ``create_new: true`` to clone objects under fresh GUIDs; leave it
        false to update the objects the TML GUIDs point at (an in-place edit).

    Returns:
        A per-object status report (OK / error with message) and a success count.

    Examples:
        { "metadata_tmls": ["guid: ...\\ntable:\\n  name: ORDERS\\n..."] }
        Validate only:
            { "metadata_tmls": ["..."], "import_policy": "VALIDATE_ONLY" }

    Error Handling:
        Returns a descriptive message on connection, auth (401), bad-request
        (400 — often malformed TML), or rate-limit (429) failures.
    """
    try:
        client = get_client()
        resp = await client.request(
            "POST",
            "/metadata/tml/import",
            json_body={
                "metadata_tmls": params.metadata_tmls,
                "import_policy": params.import_policy,
                "create_new": params.create_new,
            },
        )
        body = resp.json()
        if params.response_format == ResponseFormat.JSON:
            return to_json(body)
        statuses = _extract_import_statuses(body)
        if not statuses:
            return "Import completed, but the response contained no per-object status."
        return _fmt_import_statuses(statuses, "TML Import")
    except Exception as exc:
        return handle_api_error(exc)


@mcp.tool(
    name="thoughtspot_async_import_tml",
    annotations=ToolAnnotations(
        title="Async Import ThoughtSpot TML",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    ),
)
async def thoughtspot_async_import_tml(params: AsyncImportTmlInput) -> str:
    """Start an asynchronous TML import and return a task ID to poll.

    Submits the TML batch to ``/metadata/tml/async/import``, which returns
    immediately with a ``task_id``. Poll it with
    ``thoughtspot_get_tml_import_status`` until the task completes.

    When to Use:
        - Import large or many TML objects without blocking on the response.
        - Import workloads that may exceed a single request's timeout.

    When NOT to Use:
        - For a handful of small objects where you want the result inline — use
          ``thoughtspot_import_tml`` instead.

    Returns:
        The task ID plus initial status and object counts, and a reminder to poll
        ``thoughtspot_get_tml_import_status``.

    Examples:
        { "metadata_tmls": ["...", "..."], "import_policy": "ALL_OR_NONE" }

    Error Handling:
        Returns a descriptive message on connection, auth (401), or rate-limit
        (429) failures.
    """
    try:
        client = get_client()
        resp = await client.request(
            "POST",
            "/metadata/tml/async/import",
            json_body={
                "metadata_tmls": params.metadata_tmls,
                "import_policy": params.import_policy,
                "create_new": params.create_new,
            },
        )
        body = resp.json()
        if params.response_format == ResponseFormat.JSON:
            return to_json(body)
        task_id = body.get("task_id", "?") if isinstance(body, dict) else "?"
        task_status = body.get("task_status", "IN_QUEUE") if isinstance(body, dict) else "?"
        total = body.get("total_object_count") if isinstance(body, dict) else None
        lines = [
            "# Async TML Import Started",
            "",
            f"- Task ID: `{task_id}`",
            f"- Status: {task_status}",
        ]
        if total is not None:
            lines.append(f"- Objects queued: {total}")
        lines.append("")
        lines.append(
            f"Poll with `thoughtspot_get_tml_import_status` "
            f'(task_ids: ["{task_id}"]) until status is COMPLETED or FAILED.'
        )
        return "\n".join(lines)
    except Exception as exc:
        return handle_api_error(exc)


@mcp.tool(
    name="thoughtspot_get_tml_import_status",
    annotations=ToolAnnotations(
        title="Get ThoughtSpot TML Import Status",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
)
async def thoughtspot_get_tml_import_status(params: TmlImportStatusInput) -> str:
    """Poll the status of asynchronous TML import task(s).

    Queries ``/metadata/tml/async/status`` for the tasks created by
    ``thoughtspot_async_import_tml``.

    When to Use:
        - Check whether an async import has COMPLETED or FAILED.
        - Retrieve the per-object import response of a finished async task
          (``include_import_response: true``).

    Rate limit:
        The async-status endpoints allow only ~100 requests/minute — poll on an
        interval (e.g. a few seconds) rather than in a tight loop.

    Returns:
        One section per task with status, progress counts, and — when requested —
        the per-object import outcome.

    Examples:
        { "task_ids": ["<task-id>"] }
        With per-object detail:
            { "task_ids": ["<task-id>"], "include_import_response": true }

    Error Handling:
        Returns a descriptive message on connection, auth (401), or rate-limit
        (429) failures.
    """
    try:
        json_body: dict[str, Any] = {
            "include_import_response": params.include_import_response,
            "record_offset": params.record_offset,
            "record_size": params.record_size,
        }
        if params.task_ids:
            json_body["task_ids"] = params.task_ids
        if params.task_status:
            json_body["task_status"] = params.task_status

        client = get_client()
        resp = await client.request("POST", "/metadata/tml/async/status", json_body=json_body)
        body = resp.json()
        if params.response_format == ResponseFormat.JSON:
            return to_json(body)

        if isinstance(body, dict):
            tasks = body.get("tasks", body.get("data", body.get("task_status", [])))
        elif isinstance(body, list):
            tasks = body
        else:
            tasks = []
        if not isinstance(tasks, list) or not tasks:
            return "No matching TML import tasks found."

        lines = ["# TML Import Task Status", ""]
        for task in tasks:
            if not isinstance(task, dict):
                continue
            task_id = task.get("task_id", "?")
            status = task.get("task_status", "?")
            processed = task.get("object_processed_count")
            total = task.get("total_object_count")
            lines.append(f"## Task `{task_id}` — {status}")
            if total is not None:
                lines.append(f"- Progress: {processed if processed is not None else '?'}/{total}")
            if params.include_import_response and task.get("import_response") is not None:
                statuses = _extract_import_statuses(task["import_response"])
                if statuses:
                    ok = sum(1 for s in statuses if s.get("status_code") == "OK")
                    lines.append(f"- Objects: {ok}/{len(statuses)} OK")
                    for s in statuses:
                        if s.get("status_code") != "OK":
                            name = s.get("name") or s.get("guid") or "(object)"
                            lines.append(f"    - ❌ {name}: {s.get('error_message', 'failed')}")
            lines.append("")
        return "\n".join(lines)
    except Exception as exc:
        return handle_api_error(exc)

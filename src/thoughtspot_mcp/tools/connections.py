"""Connection tools for the ThoughtSpot REST API v2.0 (Wave A — task T1.3).

Data-warehouse connections (Snowflake, BigQuery, Redshift, …) are the source
that ThoughtSpot models and Liveboards are built on. These tools abstract away
the connection-endpoint traps documented in ``.memory/research/04+05``:

* **Singular vs plural paths** — ``create`` and ``search`` live under the
  singular ``/connection/...``; ``update``, ``status`` and ``delete`` live under
  the plural ``/connections/{id}/...`` (the singular ``/connection/update`` and
  ``/connection/delete`` are ``deprecated: true`` in the OpenAPI spec).
* **``data_warehouse_config`` wrapping** — the warehouse credentials/objects are
  wrapped in a ``data_warehouse_config`` object. On **create** the API expects it
  as a **JSON string**; on **update** it expects a **dict**. Callers of these
  tools always pass a plain object and this module serialises it correctly.
* **``validate`` semantics** — ``create`` defaults ``validate`` to ``False``
  (register first, validate later); ``update`` defaults it to ``True`` (validate
  the tables/schema being registered), matching the proven masava flow.
* **Response-shape polymorphism** — ``search`` may return a bare array or an
  object keyed by ``connections``/``items``/``data``; both are handled.
* **Idempotency** — ``create`` accepts ``if_not_exists`` to look up an existing
  connection by exact name first (the masava find-by-name pattern).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field

from thoughtspot_mcp.client import get_client
from thoughtspot_mcp.errors import handle_api_error
from thoughtspot_mcp.formatters import ResponseFormat, paginated_response, to_json
from thoughtspot_mcp.server import mcp

# ---------------------------------------------------------------------------
# Input models
# ---------------------------------------------------------------------------


class SearchConnectionsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    identifier: str | None = Field(
        default=None,
        description="Filter to a single connection by its GUID or exact name.",
    )
    name_pattern: str | None = Field(
        default=None,
        description="Case-insensitive name pattern; use `%` as a wildcard (e.g. `%Analytics%`).",
    )
    data_warehouse_types: list[str] | None = Field(
        default=None,
        description="Filter by warehouse type(s), e.g. ['SNOWFLAKE', 'BIGQUERY_ANALYTICS'].",
    )
    include_details: bool = Field(
        default=False,
        description="Include full connection details (config + registered warehouse objects). Heavier response.",
    )
    limit: int = Field(default=50, ge=1, le=500, description="Max results (maps to record_size).")
    offset: int = Field(default=0, ge=0, description="Pagination offset (maps to record_offset).")
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class GetConnectionInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    connection_id: str = Field(..., min_length=1, description="GUID or exact name of the connection.")
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class CreateConnectionInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(..., min_length=1, description="Human-readable name for the new connection.")
    data_warehouse_config: dict[str, Any] = Field(
        ...,
        description=(
            "Warehouse configuration object. Typically shaped as "
            '{"configuration": {<credentials>}, "externalDatabases": [<db objects>]}. '
            "Pass a plain object — it is serialised to the JSON string the create endpoint expects."
        ),
    )
    data_warehouse_type: str = Field(
        default="SNOWFLAKE",
        description="Warehouse type, e.g. SNOWFLAKE, BIGQUERY_ANALYTICS, REDSHIFT, DATABRICKS.",
    )
    description: str | None = Field(default=None, description="Optional description for the connection.")
    validate_config: bool = Field(
        default=False,
        description="Validate credentials/objects against the warehouse on create. Defaults False (register first).",
    )
    if_not_exists: bool = Field(
        default=False,
        description="If a connection with this exact name already exists, return it instead of creating a duplicate.",
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class UpdateConnectionInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    connection_id: str = Field(..., min_length=1, description="GUID or name of the connection to update.")
    data_warehouse_config: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Updated warehouse configuration object (passed through as a dict). Use this to register "
            'tables/schemas: {"configuration": {...}, "externalDatabases": [{"name": ..., '
            '"schemas": [{"name": ..., "tables": [...]}]}]}.'
        ),
    )
    name: str | None = Field(default=None, description="New name for the connection.")
    description: str | None = Field(default=None, description="New description for the connection.")
    validate_config: bool = Field(
        default=True,
        description="Validate the config against the warehouse. Defaults True when (re)registering tables/schema.",
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class SetConnectionStatusInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    connection_id: str = Field(..., min_length=1, description="GUID or name of the connection.")
    status: str = Field(
        default="ACTIVATED",
        pattern="^(ACTIVATED|DEACTIVATED)$",
        description="ACTIVATED to enable the connection, DEACTIVATED to disable it.",
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class DeleteConnectionInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    connection_id: str = Field(..., min_length=1, description="GUID or name of the connection to delete.")
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_connections(body: Any) -> list[dict[str, Any]]:
    """Normalise the polymorphic /connection/search response to a list.

    The endpoint may return a bare JSON array or an object keyed by
    ``connections`` / ``items`` / ``data`` depending on version.
    """
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        found = body.get("connections", body.get("items", body.get("data", [])))
        return found if isinstance(found, list) else []
    return []


def _fmt_connection(conn: dict[str, Any]) -> str:
    name = conn.get("name", "Unnamed")
    guid = conn.get("id", conn.get("guid", "?"))
    wh = conn.get("data_warehouse_type", "?")
    lines = [f"## {name} (`{guid}`)", f"- **Warehouse**: {wh}"]
    if conn.get("description"):
        lines.append(f"- **Description**: {conn['description']}")
    objects = conn.get("data_warehouse_objects")
    if isinstance(objects, list):
        lines.append(f"- **Registered objects**: {len(objects)}")
    return "\n".join(lines) + "\n"


def _success(resp: httpx.Response, fmt: ResponseFormat, message: str) -> str:
    """Format a success response for endpoints that return 204 / empty bodies."""
    body: Any = None
    if resp.status_code != 204 and resp.content:
        try:
            body = resp.json()
        except Exception:
            body = None
    if fmt == ResponseFormat.JSON:
        return to_json({"ok": True, "message": message, "data": body})
    if body:
        return f"{message}\n\n{to_json(body)}"
    return message


async def _search_raw(
    *,
    identifier: str | None = None,
    name_pattern: str | None = None,
    data_warehouse_types: list[str] | None = None,
    include_details: bool = False,
    record_offset: int = 0,
    record_size: int = 50,
) -> list[dict[str, Any]]:
    """Run POST /connection/search and return the normalised connection list."""
    client = get_client()
    body: dict[str, Any] = {
        "record_offset": record_offset,
        "record_size": record_size,
        "include_details": include_details,
    }
    if identifier or name_pattern:
        conn_filter: dict[str, Any] = {}
        if identifier:
            conn_filter["identifier"] = identifier
        if name_pattern:
            conn_filter["name_pattern"] = name_pattern
        body["connections"] = [conn_filter]
    if data_warehouse_types:
        body["data_warehouse_types"] = data_warehouse_types
    resp = await client.request("POST", "/connection/search", json_body=body)
    return _extract_connections(resp.json())


async def _find_connection_by_name(name: str) -> dict[str, Any] | None:
    """Idempotency helper: return the connection whose name matches exactly, if any."""
    candidates = await _search_raw(identifier=name, record_size=50)
    for conn in candidates:
        if conn.get("name") == name:
            return conn
    # ``identifier`` matches GUID or name server-side; fall back to a case-insensitive scan.
    for conn in candidates:
        if str(conn.get("name", "")).casefold() == name.casefold():
            return conn
    return None


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool(
    name="thoughtspot_search_connections",
    annotations=ToolAnnotations(
        title="Search ThoughtSpot Connections",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
)
async def thoughtspot_search_connections(params: SearchConnectionsInput) -> str:
    """List or filter data-warehouse connections configured in ThoughtSpot.

    Connections are the warehouse credentials (Snowflake, BigQuery, Redshift, …)
    that ThoughtSpot models and Liveboards read from.

    When to Use:
        - Discover which connections exist and their GUIDs.
        - Check for an existing connection before creating one (idempotency).
        - Filter by warehouse type or name pattern.

    When NOT to Use:
        - If you already have a GUID/name and want one connection's full details,
          use thoughtspot_get_connection.

    Returns:
        Paginated list of connections. Each entry includes name, id (GUID),
        data_warehouse_type, description, and (with include_details) the config
        and registered warehouse objects. JSON format returns the raw array.

    Pagination:
        limit (1–500, default 50) → record_size; offset (default 0) → record_offset.

    Examples:
        All connections:                 params = {}
        Snowflake only, with details:    params = {"data_warehouse_types": ["SNOWFLAKE"], "include_details": true}
        By name pattern:                 params = {"name_pattern": "%Analytics%"}

    Error Handling:
        Returns a descriptive message on auth (401/403) or connectivity failures.
    """
    try:
        connections = await _search_raw(
            identifier=params.identifier,
            name_pattern=params.name_pattern,
            data_warehouse_types=params.data_warehouse_types,
            include_details=params.include_details,
            record_offset=params.offset,
            record_size=params.limit,
        )
        return paginated_response(
            items=connections,
            limit=params.limit,
            offset=params.offset,
            fmt=params.response_format,
            item_formatter=_fmt_connection,
            title="ThoughtSpot Connections",
        )
    except Exception as exc:
        return handle_api_error(exc)


@mcp.tool(
    name="thoughtspot_get_connection",
    annotations=ToolAnnotations(
        title="Get ThoughtSpot Connection",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
)
async def thoughtspot_get_connection(params: GetConnectionInput) -> str:
    """Get full details (config + registered objects) of one connection by GUID or name.

    Implemented via POST /connection/search with include_details, filtered to the
    given identifier — ThoughtSpot has no singular connection-detail GET endpoint.

    When to Use:
        - Inspect a connection's warehouse config or registered tables/schemas.
        - Confirm a connection exists and resolve its GUID from a name.

    When NOT to Use:
        - To browse many connections, use thoughtspot_search_connections.

    Returns:
        The connection's details. Markdown shows a heading with fields; JSON
        returns the full object. Returns a "not found" message if no match.

    Examples:
        By GUID:  params = {"connection_id": "a1b2c3d4-..."}
        By name:  params = {"connection_id": "Acme Analytics Sandbox"}

    Error Handling:
        Returns a descriptive message on auth or connectivity failures.
    """
    try:
        matches = await _search_raw(identifier=params.connection_id, include_details=True, record_size=50)
        conn = next(
            (c for c in matches if params.connection_id in (c.get("id"), c.get("name"))),
            matches[0] if matches else None,
        )
        if conn is None:
            return f"No connection found matching '{params.connection_id}'."
        if params.response_format == ResponseFormat.JSON:
            return to_json(conn)
        return _fmt_connection(conn)
    except Exception as exc:
        return handle_api_error(exc)


@mcp.tool(
    name="thoughtspot_create_connection",
    annotations=ToolAnnotations(
        title="Create ThoughtSpot Connection",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    ),
)
async def thoughtspot_create_connection(params: CreateConnectionInput) -> str:
    """Create a new data-warehouse connection (POST /connection/create).

    The ``data_warehouse_config`` object is serialised to the JSON **string** the
    create endpoint requires — pass a plain object. ``validate_config`` defaults
    to False so you can register the connection first and add tables/schema later
    via thoughtspot_update_connection (the proven onboarding flow).

    When to Use:
        - Provision a brand-new Snowflake/BigQuery/etc. connection.
        - Automate distributor/tenant onboarding pipelines.

    Idempotency:
        Set if_not_exists=true to return an existing connection with the same
        exact name instead of creating a duplicate.

    Returns:
        The created (or existing) connection: id (GUID), name, data_warehouse_type.
        JSON format returns the raw API object.

    Examples:
        params = {
            "name": "Acme Analytics Sandbox",
            "data_warehouse_type": "SNOWFLAKE",
            "data_warehouse_config": {
                "configuration": {
                    "accountName": "abc-xy123", "user": "SVC_TS",
                    "password": "***", "role": "TS_ROLE",
                    "warehouse": "TS_WH", "database": "ACME"
                },
                "externalDatabases": [
                    {"name": "ACME", "isAutoCreated": false, "schemas": []}
                ]
            },
            "if_not_exists": true
        }

    Error Handling:
        A 400 usually means the warehouse config was rejected (bad credentials or
        shape). Returns a descriptive message on auth/connectivity failures.
    """
    try:
        if params.if_not_exists:
            existing = await _find_connection_by_name(params.name)
            if existing is not None:
                note = f"Connection '{params.name}' already exists (`{existing.get('id', '?')}`); returning it.\n\n"
                if params.response_format == ResponseFormat.JSON:
                    return to_json(existing)
                return note + _fmt_connection(existing)

        client = get_client()
        body: dict[str, Any] = {
            "name": params.name,
            "data_warehouse_type": params.data_warehouse_type,
            # create expects the config wrapped and serialised to a JSON string
            "data_warehouse_config": json.dumps(params.data_warehouse_config),
            "validate": params.validate_config,
        }
        if params.description is not None:
            body["description"] = params.description

        resp = await client.request("POST", "/connection/create", json_body=body)
        data = resp.json()
        if params.response_format == ResponseFormat.JSON:
            return to_json(data)
        return "Connection created.\n\n" + _fmt_connection(data)
    except Exception as exc:
        return handle_api_error(exc)


@mcp.tool(
    name="thoughtspot_update_connection",
    annotations=ToolAnnotations(
        title="Update ThoughtSpot Connection",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
)
async def thoughtspot_update_connection(params: UpdateConnectionInput) -> str:
    """Update a connection — rename, re-describe, or register tables/schemas.

    Uses the **plural** POST /connections/{id}/update path (the singular
    /connection/update is deprecated). Unlike create, ``data_warehouse_config`` is
    sent as a **dict** (not a JSON string), and ``validate_config`` defaults to
    True since updates typically (re)register schema objects.

    When to Use:
        - Register/refresh the tables and schemas a connection exposes.
        - Rename a connection or change its description.
        - Rotate warehouse credentials inside data_warehouse_config.

    Recommended Workflow:
        1. thoughtspot_get_connection to see the current config.
        2. Build the updated data_warehouse_config (with externalDatabases/schemas/tables).
        3. Call this tool.

    Returns:
        A success confirmation (the API returns 204 No Content on success).

    Examples:
        Register tables:
            params = {
                "connection_id": "a1b2c3d4-...",
                "data_warehouse_config": {
                    "configuration": {"accountName": "abc-xy123", "user": "SVC_TS", ...},
                    "externalDatabases": [{
                        "name": "ACME", "isAutoCreated": false,
                        "schemas": [{"name": "THOUGHTSPOT_DEMO", "tables": [ ... ]}]
                    }]
                }
            }
        Rename only:
            params = {"connection_id": "a1b2c3d4-...", "name": "New Name", "validate_config": false}

    Error Handling:
        A 400 usually means the warehouse rejected the config during validation.
        Returns a descriptive message on auth/connectivity failures.
    """
    try:
        client = get_client()
        body: dict[str, Any] = {"validate": params.validate_config}
        if params.name is not None:
            body["name"] = params.name
        if params.description is not None:
            body["description"] = params.description
        if params.data_warehouse_config is not None:
            body["data_warehouse_config"] = params.data_warehouse_config

        resp = await client.request("POST", f"/connections/{params.connection_id}/update", json_body=body)
        return _success(
            resp,
            params.response_format,
            f"Connection '{params.connection_id}' updated successfully.",
        )
    except Exception as exc:
        return handle_api_error(exc)


@mcp.tool(
    name="thoughtspot_set_connection_status",
    annotations=ToolAnnotations(
        title="Activate/Deactivate ThoughtSpot Connection",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
)
async def thoughtspot_set_connection_status(params: SetConnectionStatusInput) -> str:
    """Activate or deactivate a connection (POST /connections/{id}/status).

    A DEACTIVATED connection cannot be used for queries or operations until it is
    ACTIVATED again. Requires the DATAMANAGEMENT ("Can manage data") privilege.
    (Beta: 26.6.0.cl or later.)

    When to Use:
        - Temporarily disable a connection without deleting it.
        - Re-enable a previously deactivated connection.

    When NOT to Use:
        - To permanently remove a connection, use thoughtspot_delete_connection.
        - This is NOT a read tool — it does not fetch status. Use
          thoughtspot_get_connection to inspect a connection.

    Returns:
        A success confirmation (the API returns 204 No Content on success).

    Examples:
        Deactivate: params = {"connection_id": "a1b2c3d4-...", "status": "DEACTIVATED"}
        Activate:   params = {"connection_id": "a1b2c3d4-...", "status": "ACTIVATED"}

    Error Handling:
        A 404 means the connection GUID/name does not exist. Returns a descriptive
        message on auth/connectivity failures.
    """
    try:
        client = get_client()
        resp = await client.request(
            "POST",
            f"/connections/{params.connection_id}/status",
            json_body={"status": params.status},
        )
        return _success(
            resp,
            params.response_format,
            f"Connection '{params.connection_id}' set to {params.status}.",
        )
    except Exception as exc:
        return handle_api_error(exc)


@mcp.tool(
    name="thoughtspot_delete_connection",
    annotations=ToolAnnotations(
        title="Delete ThoughtSpot Connection",
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=True,
        openWorldHint=True,
    ),
)
async def thoughtspot_delete_connection(params: DeleteConnectionInput) -> str:
    """Permanently delete a connection (POST /connections/{id}/delete).

    Uses the **plural** delete path (the singular /connection/delete is
    deprecated). This is destructive: models and Liveboards built on the
    connection will break. There is no soft-delete/undo.

    When to Use:
        - Decommission a connection you are certain is no longer needed.
        - Clean up test/onboarding connections.

    When NOT to Use:
        - To temporarily disable a connection, use thoughtspot_set_connection_status
          with DEACTIVATED instead.

    Returns:
        A success confirmation (the API returns 204 No Content on success).

    Examples:
        params = {"connection_id": "a1b2c3d4-..."}

    Error Handling:
        A 404 means the connection does not exist (already deleted). Returns a
        descriptive message on auth/connectivity failures.
    """
    try:
        client = get_client()
        resp = await client.request("POST", f"/connections/{params.connection_id}/delete", json_body={})
        return _success(
            resp,
            params.response_format,
            f"Connection '{params.connection_id}' deleted.",
        )
    except Exception as exc:
        return handle_api_error(exc)

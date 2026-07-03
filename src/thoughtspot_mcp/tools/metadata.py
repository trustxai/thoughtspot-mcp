"""Metadata tools for the ThoughtSpot API (Wave A — task T1.1).

Covers ``POST /metadata/search`` (multi-strategy lookup across Liveboards,
Answers, Worksheets/Models, Connections, Tags, Users, etc.) and
``POST /metadata/delete``.

The v2.0 search API has no literal ``MODEL`` type — Models are Worksheets
under the hood, addressed as ``type: LOGICAL_TABLE`` with
``subtypes: [WORKSHEET]``. ThoughtSpot's own product renamed Worksheets to
"Models" in its UI, so callers naturally ask for ``type=MODEL``; this module
accepts that as a convenience alias and resolves it to the real filter. When
a ``MODEL`` search with a ``name_pattern`` finds nothing, it is retried once
unfiltered by type, since some deployments' Model/Worksheet objects don't
surface consistently under ``LOGICAL_TABLE`` (observed in masava's
staging-data-loader — see research/04). This fallback is scoped to the
``MODEL`` alias only: it never silently drops an explicit, unambiguous type
filter (e.g. ``type=USER``) that a caller asked for directly.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field

from thoughtspot_mcp.client import ThoughtSpotClient, get_client
from thoughtspot_mcp.errors import handle_api_error
from thoughtspot_mcp.formatters import ResponseFormat, paginated_response, to_json
from thoughtspot_mcp.server import mcp

MetadataType = Literal[
    "LIVEBOARD",
    "ANSWER",
    "LOGICAL_TABLE",
    "LOGICAL_COLUMN",
    "CONNECTION",
    "TAG",
    "USER",
    "USER_GROUP",
    "LOGICAL_RELATIONSHIP",
    "INSIGHT_SPEC",
    "COLLECTION",
    "MODEL",
]

MetadataSubtype = Literal[
    "ONE_TO_ONE_LOGICAL",
    "WORKSHEET",
    "PRIVATE_WORKSHEET",
    "USER_DEFINED",
    "AGGR_WORKSHEET",
    "SQL_VIEW",
]

DeleteMetadataType = Literal[
    "LIVEBOARD",
    "ANSWER",
    "LOGICAL_TABLE",
    "LOGICAL_COLUMN",
    "LOGICAL_RELATIONSHIP",
]

# type=MODEL is a convenience alias with no literal API equivalent: Models are
# Worksheets, addressed via LOGICAL_TABLE + subtypes=[WORKSHEET].
_MODEL_ALIAS_TYPE = "LOGICAL_TABLE"
_MODEL_ALIAS_SUBTYPES = ["WORKSHEET"]

# ---------------------------------------------------------------------------
# Input models
# ---------------------------------------------------------------------------


class SearchMetadataInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    identifier: str | None = Field(
        default=None,
        description="GUID or exact name of a single metadata object to look up.",
    )
    type: MetadataType | None = Field(
        default=None,
        description=(
            "Metadata type to filter by. 'MODEL' is a convenience alias for "
            "Models/Worksheets (resolved to LOGICAL_TABLE with subtypes=[WORKSHEET]) "
            "since the v2.0 search API has no literal MODEL type."
        ),
    )
    subtypes: list[MetadataSubtype] | None = Field(
        default=None,
        description="Subtype filter; only applies to LOGICAL_TABLE. Ignored when type is 'MODEL'.",
    )
    name_pattern: str | None = Field(
        default=None,
        description="Case-insensitive name match. Use '%' as a wildcard.",
    )
    include_details: bool = Field(
        default=False,
        description="Include full object detail (metadata_detail) in each result.",
    )
    limit: int = Field(
        default=50,
        ge=-1,
        le=1000,
        description="Max records to return (maps to record_size). Use -1 to fetch all matching records.",
    )
    offset: int = Field(
        default=0,
        ge=0,
        description="Pagination offset (maps to record_offset). Ignored when limit is -1.",
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class DeleteMetadataInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    identifiers: list[str] = Field(
        ...,
        min_length=1,
        description="GUIDs or exact names of the metadata objects to delete.",
    )
    type: DeleteMetadataType | None = Field(
        default=None,
        description="Metadata type of the objects. Required when identifiers are names; optional for GUIDs.",
    )
    delete_disabled_objects: bool = Field(
        default=False,
        description="Also delete objects that are currently disabled.",
    )


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------


def _fmt_metadata_item(item: dict[str, Any]) -> str:
    header = item.get("metadata_header") or {}
    name = item.get("metadata_name") or header.get("name", "Unnamed")
    guid = item.get("metadata_id") or item.get("metadata_obj_id", "?")
    obj_type = item.get("metadata_type") or header.get("type", "?")
    return f"- **{name}** (`{guid}`) — type: `{obj_type}`\n"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_type_filter(type_: str | None, subtypes: Sequence[str] | None) -> tuple[str | None, Sequence[str] | None]:
    """Map the 'MODEL' convenience alias onto its real API filter."""
    if type_ == "MODEL":
        return _MODEL_ALIAS_TYPE, _MODEL_ALIAS_SUBTYPES
    return type_, subtypes


async def _search_metadata(
    client: ThoughtSpotClient,
    *,
    identifier: str | None,
    type_: str | None,
    subtypes: Sequence[str] | None,
    name_pattern: str | None,
    include_details: bool,
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    metadata_filter: dict[str, Any] = {}
    if identifier:
        metadata_filter["identifier"] = identifier
    if type_:
        metadata_filter["type"] = type_
    if subtypes:
        metadata_filter["subtypes"] = subtypes
    if name_pattern:
        metadata_filter["name_pattern"] = name_pattern

    payload: dict[str, Any] = {
        "record_offset": offset,
        "record_size": limit,
        "include_details": include_details,
    }
    if metadata_filter:
        payload["metadata"] = [metadata_filter]

    resp = await client.request("POST", "/metadata/search", json_body=payload)
    body = resp.json()

    # Response-shape polymorphism observed across deployments (research/04):
    # the spec documents a bare array, but some instances wrap it.
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        result = body.get("metadata", body.get("data", []))
        return result if isinstance(result, list) else []
    return []


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool(
    name="thoughtspot_search_metadata",
    annotations=ToolAnnotations(
        title="Search ThoughtSpot Metadata",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
)
async def thoughtspot_search_metadata(params: SearchMetadataInput) -> str:
    """Search for metadata objects (Liveboards, Answers, Models, Connections, Tags, Users, ...).

    Wraps ``POST /metadata/search`` with a multi-strategy fallback scoped to
    the ``MODEL`` alias: a ``type=MODEL`` search that finds nothing is
    retried unfiltered by type when a ``name_pattern`` is also given, since
    Model/Worksheet objects don't always surface consistently under
    ``LOGICAL_TABLE`` across deployments. Any other explicit ``type`` filter
    (e.g. USER, LIVEBOARD) is never silently dropped.

    When to Use:
        - Find the GUID of a Liveboard, Answer, Model/Worksheet, Connection,
          Tag, User, or Group before acting on it (export, delete, share).
        - Discover what objects exist, filtered by type and/or name.
        - Confirm an object with a given name/GUID exists.

    When NOT to Use:
        - To read the full TML/definition of an object once you have its
          GUID — use the tml export tools instead.
        - To browse Liveboard/Answer *data* — use the data-query tools.

    Returns:
        Each match includes: metadata_name, metadata_id (GUID), metadata_type,
        and (if include_details=True) the full metadata_detail object.

        Markdown format lists one bullet per match. JSON format returns the
        raw list of matches.

    Type Filtering:
        'type' accepts the literal v2.0 API types (LIVEBOARD, ANSWER,
        LOGICAL_TABLE, LOGICAL_COLUMN, CONNECTION, TAG, USER, USER_GROUP,
        LOGICAL_RELATIONSHIP, INSIGHT_SPEC, COLLECTION) plus the convenience
        alias 'MODEL' for Worksheets/Models.

    Examples:
        Find a Model/Worksheet by name:
            params = { "type": "MODEL", "name_pattern": "Sales%" }
        Look up a single object by GUID:
            params = { "identifier": "a1b2c3d4-..." }
        List all Liveboards:
            params = { "type": "LIVEBOARD", "limit": -1 }

    Error Handling:
        Returns a descriptive message on authentication, permission, or
        request-validation failures.
    """
    try:
        client = get_client()
        resolved_type, resolved_subtypes = _resolve_type_filter(params.type, params.subtypes)

        items = await _search_metadata(
            client,
            identifier=params.identifier,
            type_=resolved_type,
            subtypes=resolved_subtypes,
            name_pattern=params.name_pattern,
            include_details=params.include_details,
            limit=params.limit,
            offset=params.offset,
        )

        if not items and params.type == "MODEL" and params.name_pattern and not params.identifier:
            items = await _search_metadata(
                client,
                identifier=None,
                type_=None,
                subtypes=None,
                name_pattern=params.name_pattern,
                include_details=params.include_details,
                limit=params.limit,
                offset=params.offset,
            )

        if params.response_format == ResponseFormat.JSON:
            return to_json(items)

        if not items:
            return "No metadata objects found."

        return paginated_response(
            items=items,
            limit=params.limit,
            offset=params.offset,
            fmt=params.response_format,
            item_formatter=_fmt_metadata_item,
            title="ThoughtSpot Metadata",
        )
    except Exception as exc:
        return handle_api_error(exc)


@mcp.tool(
    name="thoughtspot_delete_metadata",
    annotations=ToolAnnotations(
        title="Delete ThoughtSpot Metadata",
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=True,
    ),
)
async def thoughtspot_delete_metadata(params: DeleteMetadataInput) -> str:
    """Permanently delete one or more metadata objects.

    Wraps ``POST /metadata/delete``. Requires edit access to every object
    named. This is a permanent operation with no undo.

    When to Use:
        - Remove obsolete Liveboards, Answers, Models/Worksheets, or joins
          once confirmed unused (e.g. via thoughtspot_search_metadata first).

    When NOT to Use:
        - To delete a Connection — use the connections tool's delete instead;
          this endpoint covers Liveboards, Answers, Logical Tables/Columns,
          and Logical Relationships only.
        - Without first confirming the GUIDs via search — deleting the wrong
          object cannot be undone.

    Returns:
        A confirmation listing the deleted identifiers on success.

    Examples:
        Delete a single object by GUID:
            params = { "identifiers": ["a1b2c3d4-..."] }
        Delete several Worksheets by name:
            params = { "identifiers": ["Old Sales Model"], "type": "LOGICAL_TABLE" }

    Error Handling:
        Returns a descriptive message if any identifier is not found or the
        caller lacks edit access.
    """
    try:
        client = get_client()
        entries: list[dict[str, Any]] = []
        for identifier in params.identifiers:
            entry: dict[str, Any] = {"identifier": identifier}
            if params.type:
                entry["type"] = params.type
            entries.append(entry)

        payload: dict[str, Any] = {
            "metadata": entries,
            "delete_disabled_objects": params.delete_disabled_objects,
        }
        await client.request("POST", "/metadata/delete", json_body=payload)

        ids = ", ".join(f"`{i}`" for i in params.identifiers)
        return f"Deleted {len(params.identifiers)} metadata object(s): {ids}."
    except Exception as exc:
        return handle_api_error(exc)

"""Health-check tool for the ThoughtSpot API."""

from __future__ import annotations

from mcp.types import ToolAnnotations

from thoughtspot_mcp.client import get_client
from thoughtspot_mcp.errors import handle_api_error
from thoughtspot_mcp.server import mcp


@mcp.tool(
    name="thoughtspot_health_check",
    annotations=ToolAnnotations(
        title="ThoughtSpot Health Check",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
)
async def thoughtspot_health_check() -> str:
    """Check whether the ThoughtSpot instance is reachable and credentials are valid.

    Performs a token exchange (unless a static token is configured) and a
    lightweight ``GET /system`` request. Use this as the first call to confirm
    connectivity and authentication before invoking other tools.

    When to Use:
        - Verify the ThoughtSpot instance is up and reachable.
        - Diagnose "connection refused", timeout, or 401 authentication errors.
        - Confirm credentials are valid after initial setup.

    When NOT to Use:
        - As a keep-alive poll — it exchanges a token on each call.

    Returns:
        "OK – ThoughtSpot is healthy (release <version>)." on success, including
        the instance release version when available. On failure, a human-readable
        error with the root cause.

    Examples:
        Call with no parameters: thoughtspot_health_check()

    Error Handling:
        Returns a descriptive message for connection, timeout, and auth failures.
    """
    try:
        client = get_client()
        resp = await client.request("GET", "/system")
        body = resp.json()
        version = body.get("release_version", body.get("version", "unknown"))
        return f"OK – ThoughtSpot is healthy (release {version})."
    except Exception as exc:
        return handle_api_error(exc)

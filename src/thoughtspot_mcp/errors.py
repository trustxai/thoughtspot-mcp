"""Centralised error handling for ThoughtSpot API responses."""

from __future__ import annotations

import httpx


def handle_api_error(exc: Exception) -> str:
    """Return a human-readable, actionable error string."""
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        detail = ""
        try:
            body = exc.response.json()
            # ThoughtSpot v2.0 errors surface under various keys.
            detail = body.get("message", body.get("debug", body.get("error", "")))
            if isinstance(detail, list):
                detail = "; ".join(str(d) for d in detail)
        except Exception:
            detail = exc.response.text[:300]

        messages = {
            400: f"Bad request – the API rejected the input. {detail}",
            401: "Unauthorized – the access token is invalid or expired. "
            "The client will attempt to refresh automatically.",
            403: "Forbidden – your ThoughtSpot user lacks privilege for this resource.",
            404: "Not found – double-check the object identifier (GUID).",
            429: "Rate limited – ThoughtSpot enforces ~100 req/s per IP (async status endpoints "
            "~100 req/min). Wait a moment before retrying.",
        }
        return f"Error ({status}): {messages.get(status, f'API error. {detail}')}"

    if isinstance(exc, httpx.TimeoutException):
        return "Error: request to ThoughtSpot API timed out. Is THOUGHTSPOT_HOST reachable?"

    if isinstance(exc, httpx.ConnectError):
        return "Error: could not connect to ThoughtSpot. Verify THOUGHTSPOT_HOST and network access."

    return f"Error: unexpected failure – {type(exc).__name__}: {exc}"

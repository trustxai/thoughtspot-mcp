"""Async HTTP client for the ThoughtSpot REST API v2.0 with token management.

ThoughtSpot access tokens default to a **300-second** validity window, so the
client refreshes aggressively (safety margin below) and retries once on a 401.
Nearly every v2.0 endpoint is a POST with a JSON body — including search/list
operations — so ``request`` passes the method through unchanged.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from thoughtspot_mcp.config import get_settings

_TOKEN_SAFETY_MARGIN = 30  # seconds before actual expiry to refresh


class ThoughtSpotClient:
    """Thin wrapper around httpx that handles Bearer-token lifecycle.

    Auth precedence (see ``Settings``):
        1. static ``THOUGHTSPOT_ACCESS_TOKEN``
        2. trusted auth: ``THOUGHTSPOT_USERNAME`` + ``THOUGHTSPOT_SECRET_KEY``
        3. password: ``THOUGHTSPOT_USERNAME`` + ``THOUGHTSPOT_PASSWORD``
    """

    def __init__(self) -> None:
        self._token: str = ""
        self._expires_at: float = 0.0

    # -- token management ---------------------------------------------------

    def _build_token_payload(self) -> dict[str, Any]:
        settings = get_settings()
        payload: dict[str, Any] = {
            "username": settings.thoughtspot_username,
            "validity_time_in_sec": settings.thoughtspot_token_validity_seconds,
        }
        if settings.can_use_secret_key:
            payload["secret_key"] = settings.thoughtspot_secret_key
        else:
            payload["password"] = settings.thoughtspot_password
        if settings.thoughtspot_org_id:
            payload["org_identifier"] = settings.thoughtspot_org_id
        return payload

    async def _ensure_token(self, client: httpx.AsyncClient) -> str:
        settings = get_settings()

        if settings.has_static_token:
            return settings.thoughtspot_access_token

        if self._token and time.time() < self._expires_at:
            return self._token

        if not (settings.can_use_secret_key or settings.can_use_password):
            raise RuntimeError(
                "No credentials configured. Set THOUGHTSPOT_USERNAME plus "
                "THOUGHTSPOT_SECRET_KEY (trusted auth) or THOUGHTSPOT_PASSWORD, "
                "or provide THOUGHTSPOT_ACCESS_TOKEN."
            )

        resp = await client.post(
            f"{settings.api_base_url}/auth/token/full",
            json=self._build_token_payload(),
            headers={"accept": "application/json", "content-type": "application/json"},
        )
        resp.raise_for_status()
        body = resp.json()
        self._token = body["token"]
        valid_for = body.get("valid_for_in_sec", settings.thoughtspot_token_validity_seconds)
        self._expires_at = time.time() + valid_for - _TOKEN_SAFETY_MARGIN
        return self._token

    # -- public API ---------------------------------------------------------

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        timeout: float | None = None,
        _retried: bool = False,
    ) -> httpx.Response:
        """Execute an authenticated request against the ThoughtSpot v2.0 API.

        Args:
            method: HTTP verb. Most v2.0 endpoints are ``POST``.
            path: API path relative to ``/api/rest/2.0`` (leading slash optional).
            params: Query-string parameters.
            json_body: JSON request body.
            timeout: Per-request timeout override (seconds).

        Automatically refreshes the token on 401 (once).
        """
        settings = get_settings()
        url = f"{settings.api_base_url}/{path.lstrip('/')}"
        effective_timeout = timeout if timeout is not None else settings.thoughtspot_request_timeout_seconds

        async with httpx.AsyncClient(timeout=effective_timeout) as client:
            token = await self._ensure_token(client)
            headers = {
                "accept": "application/json",
                "content-type": "application/json",
                "authorization": f"Bearer {token}",
            }

            resp = await client.request(
                method,
                url,
                headers=headers,
                params=params,
                json=json_body,
            )

            if resp.status_code == 401 and not _retried and not settings.has_static_token:
                self._token = ""
                self._expires_at = 0.0
                return await self.request(
                    method,
                    path,
                    params=params,
                    json_body=json_body,
                    timeout=timeout,
                    _retried=True,
                )

            resp.raise_for_status()
            return resp


_client: ThoughtSpotClient | None = None


def get_client() -> ThoughtSpotClient:
    global _client
    if _client is None:
        _client = ThoughtSpotClient()
    return _client

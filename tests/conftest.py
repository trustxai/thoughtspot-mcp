"""Pytest configuration and shared fixtures."""

from __future__ import annotations

import os

import httpx
import pytest
from dotenv import load_dotenv


def _has_live_creds() -> bool:
    host = os.getenv("THOUGHTSPOT_HOST")
    if not host:
        return False
    if os.getenv("THOUGHTSPOT_ACCESS_TOKEN"):
        return True
    username = os.getenv("THOUGHTSPOT_USERNAME")
    return bool(username and (os.getenv("THOUGHTSPOT_SECRET_KEY") or os.getenv("THOUGHTSPOT_PASSWORD")))


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "live: integration tests requiring a ThoughtSpot instance")
    config.addinivalue_line("markers", "destructive: mutating integration tests")


@pytest.fixture(autouse=True)
def _isolate_settings_env(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep a developer's real ``.env`` / exported ``THOUGHTSPOT_*`` out of unit tests.

    The collection hook calls ``load_dotenv()`` and ``Settings`` also reads ``.env``
    directly, so on a configured machine either would inject real credentials — which
    breaks tests that assert the no-credentials path. Clear the vars, disable ``.env``
    file loading, and reset the settings cache before each non-live test. Live tests are
    left untouched: they need the real environment.
    """
    if "live" in request.keywords:
        return

    from thoughtspot_mcp.config import Settings, get_settings

    for var in [key for key in os.environ if key.startswith("THOUGHTSPOT_")]:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    get_settings.cache_clear()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    load_dotenv()
    has_creds = _has_live_creds()
    allow_destructive = os.getenv("THOUGHTSPOT_TEST_ALLOW_DESTRUCTIVE") == "1"

    skip_live = pytest.mark.skip(
        reason="THOUGHTSPOT_HOST + credentials (token, secret_key, or password) required for live tests"
    )
    skip_destructive = pytest.mark.skip(reason="Set THOUGHTSPOT_TEST_ALLOW_DESTRUCTIVE=1 to run mutating live tests")

    for item in items:
        if "live" in item.keywords and not has_creds:
            item.add_marker(skip_live)
        if "destructive" in item.keywords and not allow_destructive:
            item.add_marker(skip_destructive)


def _api_base_url() -> str:
    host = os.getenv("THOUGHTSPOT_HOST", "").rstrip("/")
    return f"{host}/api/rest/2.0"


def _get_access_token() -> str:
    load_dotenv()
    token = os.getenv("THOUGHTSPOT_ACCESS_TOKEN", "")
    if token:
        return token
    username = os.getenv("THOUGHTSPOT_USERNAME", "")
    payload: dict[str, object] = {
        "username": username,
        "validity_time_in_sec": int(os.getenv("THOUGHTSPOT_TOKEN_VALIDITY_SECONDS", "300")),
    }
    if os.getenv("THOUGHTSPOT_SECRET_KEY"):
        payload["secret_key"] = os.getenv("THOUGHTSPOT_SECRET_KEY")
    else:
        payload["password"] = os.getenv("THOUGHTSPOT_PASSWORD")
    if os.getenv("THOUGHTSPOT_ORG_ID"):
        payload["org_identifier"] = os.getenv("THOUGHTSPOT_ORG_ID")

    resp = httpx.post(
        f"{_api_base_url()}/auth/token/full",
        json=payload,
        timeout=30.0,
    )
    resp.raise_for_status()
    return str(resp.json()["token"])


@pytest.fixture(scope="session")
def live_token() -> str:
    """A valid bearer token against the configured live instance."""
    return _get_access_token()

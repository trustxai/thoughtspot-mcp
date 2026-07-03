"""Unit tests for Settings URL handling."""

from __future__ import annotations

from thoughtspot_mcp.config import API_V2_PATH, Settings


def test_api_base_url_prepends_https_when_scheme_missing() -> None:
    settings = Settings(thoughtspot_host="analytics.example.ai")
    assert settings.api_base_url == f"https://analytics.example.ai{API_V2_PATH}"


def test_api_base_url_preserves_explicit_https_and_strips_trailing_slash() -> None:
    settings = Settings(thoughtspot_host="https://foo.thoughtspot.cloud/")
    assert settings.api_base_url == f"https://foo.thoughtspot.cloud{API_V2_PATH}"


def test_api_base_url_preserves_http_scheme() -> None:
    settings = Settings(thoughtspot_host="http://localhost:8088")
    assert settings.api_base_url == f"http://localhost:8088{API_V2_PATH}"

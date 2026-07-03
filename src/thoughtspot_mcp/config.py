"""Application settings loaded from environment / .env file."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# ThoughtSpot REST API v2.0 is served under this path on every instance.
API_V2_PATH = "/api/rest/2.0"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Instance base URL, e.g. https://my-instance.thoughtspot.cloud (no /api path).
    thoughtspot_host: str = ""

    # Credentials. Precedence: static token > secret_key (trusted auth) > password.
    thoughtspot_username: str = ""
    thoughtspot_secret_key: str = ""
    thoughtspot_password: str = ""
    thoughtspot_access_token: str = ""

    # Optional Org context for multi-tenant instances.
    thoughtspot_org_id: str = ""

    # Token validity requested at exchange. ThoughtSpot's own default is 300s.
    thoughtspot_token_validity_seconds: int = 300

    # HTTP request timeout (seconds).
    thoughtspot_request_timeout_seconds: float = 30.0

    @property
    def api_base_url(self) -> str:
        """Full v2.0 REST API root, e.g. https://host/api/rest/2.0.

        Accepts a bare host (``my-instance.thoughtspot.cloud``) as well as a full
        URL; a missing scheme defaults to ``https://`` so a schemeless host does
        not produce an opaque transport error.
        """
        host = self.thoughtspot_host.strip().rstrip("/")
        if host and "://" not in host:
            host = f"https://{host}"
        return host + API_V2_PATH

    @property
    def has_static_token(self) -> bool:
        return bool(self.thoughtspot_access_token)

    @property
    def can_use_secret_key(self) -> bool:
        return bool(self.thoughtspot_username and self.thoughtspot_secret_key)

    @property
    def can_use_password(self) -> bool:
        return bool(self.thoughtspot_username and self.thoughtspot_password)

    @property
    def can_authenticate(self) -> bool:
        return self.has_static_token or self.can_use_secret_key or self.can_use_password


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

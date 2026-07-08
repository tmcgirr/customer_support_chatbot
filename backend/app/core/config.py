"""Application configuration.

This is the ONLY place the application reads environment/`.env` values
(CLAUDE.md invariant #73). Everything downstream takes values from `get_settings()`.
"""

from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app import __version__


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: str = "dev"
    app_version: str = __version__

    # --- Persistence (URI may embed credentials; keep it a secret) ---
    mongo_uri: SecretStr = SecretStr("mongodb://localhost:27017/cadre_chatbot")

    # --- Model provider (used from Phase 2) ---
    openai_api_key: SecretStr = SecretStr("")

    # --- Session tokens (HMAC, versioned by key id; contracts §2) ---
    session_key_id: str = "k1"
    session_secret: SecretStr = SecretStr("dev-only-change-me")
    # Retired keys still trusted for verification: "kid:secret,kid2:secret2".
    session_extra_secrets: SecretStr = SecretStr("")

    # --- Abuse caps ---
    message_cap: int = 40
    message_max_chars: int = 2000
    ip_create_cap: int = 10

    # --- Admin (used from Phase 7) ---
    admin_username: str = "admin"
    admin_password: SecretStr = SecretStr("dev-only-change-me")

    # --- Widget dev origins ---
    cors_origins: str = "http://localhost:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def session_key_ring(self) -> dict[str, str]:
        """kid -> secret. Retired keys plus the active key, which always wins."""
        ring: dict[str, str] = {}
        for pair in self.session_extra_secrets.get_secret_value().split(","):
            kid, _, secret = pair.strip().partition(":")
            if kid.strip() and secret.strip():
                ring[kid.strip()] = secret.strip()
        ring[self.session_key_id] = self.session_secret.get_secret_value()
        return ring

    @property
    def mongo_db_name(self) -> str:
        """Database name from the URI path, defaulting to cadre_chatbot.

        Uses urlsplit so pathless (`mongodb://host:port`) and SRV URIs don't
        mis-parse the host or embedded credentials as the database name.
        """
        path = urlsplit(self.mongo_uri.get_secret_value()).path.lstrip("/")
        return path or "cadre_chatbot"


@lru_cache
def get_settings() -> Settings:
    return Settings()

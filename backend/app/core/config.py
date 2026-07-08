"""Application configuration.

This is the ONLY place the application reads environment/`.env` values
(CLAUDE.md invariant #73). Everything downstream takes values from `get_settings()`.
"""

from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app import __version__

# Placeholder secrets shipped in-repo for local dev. A non-dev deployment that
# still uses one is a hard misconfiguration (see the startup guard below).
_INSECURE_DEFAULT = "dev-only-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Defaults to "prod" so a deployment that forgets to set ENV fails CLOSED —
    # the secret guard below runs and rejects the in-repo placeholder secrets.
    # Local dev / tests set ENV=dev explicitly (.env, compose, tests/conftest).
    env: str = "prod"
    app_version: str = __version__

    # --- Persistence (URI may embed credentials; keep it a secret) ---
    mongo_uri: SecretStr = SecretStr("mongodb://localhost:27017/cadre_chatbot")

    # --- Model provider ---
    openai_api_key: SecretStr = SecretStr("")
    openai_model: str = "gpt-5.4-mini"

    # --- Knowledge retrieval (set OPENAI_VECTOR_STORE_ID after upload_knowledge.py) ---
    openai_vector_store_id: str = ""

    # --- Client portal (get_portal_information tool; URL is a placeholder for POC) ---
    portal_url: str = "https://portal.cadre.ai"
    portal_reset_instructions: str = (
        "If you can't sign in, use the 'forgot password' option on the sign-in page. "
        "For security, access issues are handled through a support request — never share "
        "your password or authentication codes."
    )

    # --- Session tokens (HMAC, versioned by key id; contracts §2) ---
    session_key_id: str = "k1"
    session_secret: SecretStr = SecretStr("dev-only-change-me")
    # Retired keys still trusted for verification: "kid:secret,kid2:secret2".
    session_extra_secrets: SecretStr = SecretStr("")

    # --- Abuse caps ---
    message_cap: int = 40
    message_max_chars: int = 2000
    # Per-IP conversation-creation cap over a fixed rolling window (contracts §3.1).
    ip_create_cap: int = 10
    ip_create_window_seconds: int = 3600
    # A run lock older than this is treated as leaked (crashed mid-turn) and may be
    # released opportunistically so a conversation can't brick at CONVERSATION_BUSY.
    # A LIVE turn heartbeats its lock (~ every lock_stale_seconds/3) so however slow
    # it is, it stays young and is never swept; only a stopped turn goes stale.
    lock_stale_seconds: int = 120

    # --- Admin (used from Phase 7) ---
    admin_username: str = "admin"
    admin_password: SecretStr = SecretStr("dev-only-change-me")

    # --- Widget dev origins ---
    cors_origins: str = "http://localhost:5273"

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

    @model_validator(mode="after")
    def _forbid_default_secrets_outside_dev(self) -> "Settings":
        """Fail fast if a non-dev deployment still ships the in-repo placeholder
        secrets. A default admin password or session secret in prod would let
        anyone unlock the admin PII surface or forge session tokens."""
        if self.env == "dev":
            return self
        insecure = [
            name
            for name, value in (
                ("SESSION_SECRET", self.session_secret.get_secret_value()),
                ("ADMIN_PASSWORD", self.admin_password.get_secret_value()),
            )
            if value == _INSECURE_DEFAULT or value == ""
        ]
        if insecure:
            raise ValueError(
                f"insecure default secret(s) in env={self.env!r}: {', '.join(insecure)}. "
                "Set real values via environment before deploying, or set ENV=dev for local dev."
            )
        return self

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

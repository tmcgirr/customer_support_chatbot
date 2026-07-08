"""Application configuration.

This is the ONLY place the application reads environment/`.env` values
(CLAUDE.md invariant #73). Everything downstream takes values from `get_settings()`.
"""

from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app import __version__

# Placeholder values shipped in-repo for local dev. A non-dev deployment that
# still uses one is a hard misconfiguration (see the startup validation below).
_INSECURE_DEFAULT = "dev-only-change-me"
_DEFAULT_MONGO_URI = "mongodb://localhost:27017/cadre_chatbot"
_DEFAULT_CORS = "http://localhost:5273"

# Environments. Only "dev" is allowed to run on the in-repo placeholder config.
_VALID_ENVS = frozenset({"dev", "staging", "prod"})
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _is_local_host(host: str | None) -> bool:
    return host is not None and host.strip("[]").lower() in _LOCAL_HOSTS


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Defaults to "prod" so a deployment that forgets to set ENV fails CLOSED —
    # the config validation below runs and rejects the in-repo placeholder config.
    # Local dev / tests set ENV=dev explicitly (.env, compose, tests/conftest).
    env: str = "prod"
    app_version: str = __version__
    # Build/commit stamp, set from the BUILD_SHA env var at build/deploy time
    # (deploy/staging.env, or `ENV BUILD_SHA` in the Dockerfile from CI); surfaced
    # on the admin system endpoint for deploy verification.
    build_sha: str = "unknown"

    # --- Persistence (URI may embed credentials; keep it a secret) ---
    mongo_uri: SecretStr = SecretStr(_DEFAULT_MONGO_URI)

    # --- Model provider ---
    openai_api_key: SecretStr = SecretStr("")
    openai_model: str = "gpt-5.4-mini"
    # Approved fallback model, tried once if the primary is MODEL_UNAVAILABLE before
    # any output streams. Empty = no fallback (opt-in per environment).
    openai_fallback_model: str = ""

    # --- Knowledge retrieval (set OPENAI_VECTOR_STORE_ID after upload_knowledge.py) ---
    openai_vector_store_id: str = ""
    # Drop retrieval hits scoring below this before grounding (0.0 = keep all).
    # Tune per environment against the store's score distribution.
    retrieval_min_score: float = 0.0

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

    # --- Background worker (V1: dedicated process, `python -m app.worker`) ---
    worker_poll_seconds: float = 2.0  # idle poll interval between claims
    worker_lease_seconds: int = 60  # job lease; a crashed worker's job is reclaimed after this
    # Hard per-job handler timeout. MUST stay < worker_lease_seconds so a handler
    # finishes (or times out) before its lease can be reclaimed — no live double-run.
    worker_job_timeout_seconds: float = 50.0
    job_backoff_base_seconds: float = 5.0  # retry backoff = base * 2^(attempts-1)
    conversation_abandon_seconds: int = 86400  # 24h with no activity → abandoned
    # A request still received/delivering this long after creation is reconciled by
    # the delivery sweep (its job crashed/timed-out, or its enqueue was lost).
    delivery_stuck_seconds: int = 900

    # --- Admin (used from Phase 7) ---
    admin_username: str = "admin"
    admin_password: SecretStr = SecretStr("dev-only-change-me")

    # --- Widget dev origins ---
    cors_origins: str = _DEFAULT_CORS

    # --- Feature flags (V1 surfaces dark-launched OFF; enable per environment) ---
    enable_delivery: bool = False  # V4: external request delivery worker
    enable_citations: bool = False  # V7: citation display on grounded answers
    enable_admin_roles: bool = False  # V5: admin/viewer role enforcement

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def feature_flags(self) -> dict[str, bool]:
        return {
            "delivery": self.enable_delivery,
            "citations": self.enable_citations,
            "admin_roles": self.enable_admin_roles,
        }

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
    def _validate_env_config(self) -> "Settings":
        """Fail CLOSED on startup for a non-dev environment that is missing real
        configuration. Only ``dev`` may run on the in-repo placeholders; ``staging``
        and ``prod`` must supply real secrets AND the required production inputs, so
        a half-configured deploy never boots (a default admin password or an
        unset Vector Store would otherwise ship silently)."""
        if self.env not in _VALID_ENVS:
            raise ValueError(f"ENV must be one of {sorted(_VALID_ENVS)}, got {self.env!r}")
        if self.env == "dev":
            return self
        problems: list[str] = []
        # Placeholder / empty secrets must be replaced (strip so whitespace-only
        # values — which "look set" — are still rejected).
        if self.session_secret.get_secret_value().strip() in ("", _INSECURE_DEFAULT):
            problems.append("SESSION_SECRET (placeholder or empty)")
        if self.admin_password.get_secret_value().strip() in ("", _INSECURE_DEFAULT):
            problems.append("ADMIN_PASSWORD (placeholder or empty)")
        if not self.openai_api_key.get_secret_value().strip():
            problems.append("OPENAI_API_KEY (unset)")
        if not self.openai_vector_store_id.strip():
            problems.append("OPENAI_VECTOR_STORE_ID (unset)")
        # Mongo must not point at localhost — check the parsed host, not a literal
        # string, so 127.0.0.1 / a different db / query params don't slip through.
        mongo = self.mongo_uri.get_secret_value().strip()
        if not mongo or _is_local_host(urlsplit(mongo).hostname):
            problems.append("MONGO_URI (unset or localhost)")
        # CORS must be real https origins — never "*" or a localhost origin, which
        # would silently trust any/dev pages against the public API.
        origins = self.cors_origin_list
        bad_origins = [
            o
            for o in origins
            if o == "*" or not o.startswith("https://") or _is_local_host(urlsplit(o).hostname)
        ]
        if not origins or bad_origins:
            detail = f"; offending: {bad_origins}" if bad_origins else ""
            problems.append(f"CORS_ORIGINS (must be https non-localhost origins{detail})")
        if problems:
            raise ValueError(
                f"invalid config for env={self.env!r}: {'; '.join(problems)}. "
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

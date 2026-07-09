"""Application configuration.

This is the ONLY place the application reads environment/`.env` values
(CLAUDE.md invariant #73). Everything downstream takes values from `get_settings()`.
"""

from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app import __version__

# Placeholder values shipped in-repo for local dev. A non-dev deployment that
# still uses one is a hard misconfiguration (see the startup validation below).
_INSECURE_DEFAULT = "dev-only-change-me"
_DEFAULT_MONGO_URI = "mongodb://localhost:27017/cadre_chatbot"
_DEFAULT_CORS = "http://localhost:5273"
# Minimum length for the session HMAC secret (a real one is `openssl rand -hex 32`).
_MIN_SESSION_SECRET_LEN = 16
# Minimum length for admin/viewer passwords in a non-dev env. The real control is the
# production identity provider (docs/SECURITY_REVIEW_V1.md H2); until that lands this is
# a stopgap floor so a trivially-weak shared password (there is no login lockout yet)
# can't ship past the startup guard.
_MIN_ADMIN_PASSWORD_LEN = 16

# Environments. Only "dev" is allowed to run on the in-repo placeholder config.
_VALID_ENVS = frozenset({"dev", "staging", "prod"})
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _is_local_host(host: str | None) -> bool:
    return host is not None and host.strip("[]").lower() in _LOCAL_HOSTS


def _is_placeholder(value: str) -> bool:
    """A value that is empty, the in-repo dev default, or a template placeholder that
    was never replaced. The `*.env.example` files ship `REPLACE_*` tokens, so any value
    containing "replace" is an un-edited placeholder — the guard MUST reject these in a
    non-dev env, or a half-configured deploy boots with repo-published secrets."""
    v = value.strip().lower()
    return v == "" or v == _INSECURE_DEFAULT or "replace" in v


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
    # Which provider answers the chat turn. This is the STARTUP DEFAULT; an operator can
    # switch it at runtime from the admin portal (persisted in app_settings, read by both
    # the API and the worker). Only a provider whose key is configured can be selected.
    # Changing the model config still requires the golden gate on the target config
    # (invariant #15) — the eval runner can target either provider (`--provider`).
    model_provider: Literal["openai", "anthropic", "openrouter"] = "openai"

    openai_api_key: SecretStr = SecretStr("")
    openai_model: str = "gpt-5.4-mini"
    # Approved fallback model, tried once if the primary is MODEL_UNAVAILABLE before
    # any output streams. Empty = no fallback (opt-in per environment).
    openai_fallback_model: str = ""
    # Hard per-response output-token ceiling on EVERY model call (chat + classify), so a
    # crafted "write forever" prompt can't run up cost or hold the run lock open on a
    # long stream (docs/SECURITY_REVIEW_V1.md L1). Sized well above a normal concise
    # answer; raise per environment if answers are being truncated.
    openai_max_output_tokens: int = 1500

    # Anthropic (Claude) — the alternate chat provider. All Anthropic types/IDs/errors
    # stay inside app/agent/adapter.py (invariant #4). Anthropic has no embeddings API,
    # so the Claude adapter reuses OpenAI embeddings for insights clustering — an OpenAI
    # key remains required for that feature regardless of the active chat provider.
    anthropic_api_key: SecretStr = SecretStr("")
    # Default to the low-cost Claude tier for this public chatbot (Haiku 4.5 ≈ $1/$5 per 1M
    # tokens, vs Opus 4.8 at $5/$25). Gate any model change on the golden set before promoting.
    anthropic_model: str = "claude-haiku-4-5"
    # Approved fallback model (same semantics as openai_fallback_model). Empty = none.
    anthropic_fallback_model: str = ""
    # Same per-response output ceiling as OpenAI; Anthropic requires max_tokens on every call.
    anthropic_max_output_tokens: int = 1500

    # OpenRouter — reach models (including Claude) through OpenRouter's OpenAI-COMPATIBLE
    # Responses API. It reuses OpenAIResponsesAdapter with a base_url override, so no new
    # adapter is needed — only a non-native model id (e.g. "anthropic/claude-haiku-4.5") and
    # this key differ. Insights EMBEDDINGS still go to real OpenAI (an OpenAI key stays
    # required); OpenRouter is a chat proxy, not an embeddings host. The per-response cap
    # reuses `openai_max_output_tokens` (same adapter). Gate on the golden set before selecting.
    openrouter_api_key: SecretStr = SecretStr("")
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "anthropic/claude-haiku-4.5"

    # --- Knowledge retrieval (set OPENAI_VECTOR_STORE_ID after upload_knowledge.py) ---
    openai_vector_store_id: str = ""
    # Drop retrieval hits scoring below this before grounding (0.0 = keep all).
    # Tune per environment against the store's score distribution.
    retrieval_min_score: float = 0.0

    # --- Client portal (get_portal_information tool; real URL owned by Client
    # Success — no public login page yet, so this stays a placeholder) ---
    portal_url: str = "https://portal.cadreai.com"
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
    # Cap the verbatim-question array a conversation accumulates when the model routes
    # to the unsupported-question canonical (keeps the most recent N; §7 / L7).
    unsupported_questions_cap: int = 200
    # Per-IP conversation-creation cap over a fixed rolling window (contracts §3.1).
    ip_create_cap: int = 10
    ip_create_window_seconds: int = 3600
    # Per-IP cap on public privacy-request submissions (V6) — tighter, to blunt
    # enumeration/abuse of the unauthenticated endpoint.
    privacy_request_ip_cap: int = 5
    privacy_request_ip_window_seconds: int = 3600
    # Throttle the chat turn (the paid LLM path) per-session AND per-IP. The
    # per-conversation message_cap bounds the TOTAL turns; these bound the RATE, so a
    # single session/IP can't drive denial-of-wallet (docs/SECURITY_REVIEW_V1.md M1).
    # The edge WAF/CDN is the volumetric backstop (§7) — this is app-level defense.
    message_rate_cap: int = 20
    message_rate_window_seconds: int = 60
    message_ip_cap: int = 60
    message_ip_window_seconds: int = 60
    # Cap request submissions per-conversation AND per-IP. Each fresh Idempotency-Key
    # writes a request and (when delivery is on) fires ONE external CRM/ticket delivery,
    # so an unthrottled session could flood the team inbox (SECURITY_REVIEW_V1 H1).
    request_conversation_cap: int = 10
    request_conversation_window_seconds: int = 3600
    request_ip_cap: int = 20
    request_ip_window_seconds: int = 3600
    # Trusted reverse-proxy hops in front of the app (Caddy = 1; set 2 once a CDN/WAF
    # fronts Caddy). client_ip() reads the real client as the Nth X-Forwarded-For entry
    # FROM THE RIGHT, so a spoofed leftmost value can't defeat the per-IP caps (M2).
    trusted_proxy_hops: int = 1
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
    # Cap the exponential backoff so a job with a large attempt budget (e.g. index
    # polling) doesn't schedule its next attempt hours out. base*2^(attempts-1) is
    # clamped to this ceiling.
    job_backoff_max_seconds: float = 300.0
    # poll_indexing attempt budget: with the capped backoff this spans ~45 min, well
    # past real Vector Store ingestion, so a healthy-but-slow index never dead-letters.
    knowledge_index_poll_attempts: int = 15
    conversation_abandon_seconds: int = 86400  # 24h with no activity → abandoned
    # A request still received/delivering this long after creation is reconciled by
    # the delivery sweep (its job crashed/timed-out, or its enqueue was lost).
    delivery_stuck_seconds: int = 900
    # Pending-job count above which the worker fires a queue-backlog WARNING alert
    # (dead-letter / delivery-failed / privacy-failed alerts fire on any > 0).
    alert_queue_depth_threshold: int = 100

    # --- LLM cost visibility (admin Usage panel) ---
    # $/1M-token overrides merged over the built-in price table (defaults live in
    # app/domain/usage/pricing.py). Format: "model:input:output,model2:input:output".
    # Correct the PLACEHOLDER OpenAI rates here per environment.
    llm_pricing_overrides: str = ""
    # Monthly LLM spend budget in USD for the cost alert + admin budget bar (0 = disabled).
    llm_monthly_budget_usd: float = 0.0

    # Reject any request whose declared Content-Length exceeds this before it is
    # parsed (defends the shared process from an oversized-body memory/disk blowup;
    # well above the 5 MB knowledge-upload cap + multipart overhead, and far above
    # chat/request bodies). Streaming bodies without Content-Length are additionally
    # bounded by the per-endpoint read cap; document a proxy body cap for defense.
    max_request_body_bytes: int = 10 * 1024 * 1024

    # --- Conversation Insights (V1.5): clustering + gap analysis + proposed FAQs ---
    insights_embed_model: str = "text-embedding-3-small"
    # Cosine similarity at/above which two questions are the "same" (connected into one
    # cluster). Higher = stricter (only near-identical group).
    insights_similarity_threshold: float = 0.82
    # A cluster this size is "common" enough to surface + propose a unified FAQ for.
    insights_min_cluster_size: int = 3
    insights_batch_limit: int = 300  # max conversations analyzed per run
    # Shared wall-clock cap for the WHOLE run's LLM steps across all horizons; with the
    # per-call cap below (one straddling call max) this stays under worker_job_timeout_seconds.
    insights_time_budget_seconds: float = 30.0
    # Hard cap on any single embed/classify call, so one hung call can't push the job past
    # the worker timeout (a timeout is treated like a model outage: skip/retry).
    insights_call_timeout_seconds: float = 15.0
    # Which report horizons the scheduled run maintains (all share one code path).
    insights_enable_daily: bool = True
    insights_enable_weekly: bool = True
    insights_enable_monthly: bool = True

    # --- Request delivery transport (pluggable; V1.5). 'simulated' (default) is a
    # functional MOCK: it records what WOULD be sent (visible in admin), needs no creds,
    # and runs the full pipeline. Flip `delivery_transport` + drop in the matching creds
    # to send for real (Slack/Teams via webhook, or email). If the selected transport is
    # misconfigured, the factory FALLS BACK to simulated and logs a warning — so the
    # wiring is always in place and switching on is a config change, never a code change. ---
    delivery_transport: Literal["simulated", "webhook", "email"] = "simulated"
    # Webhook = any inbound endpoint (Slack/Teams incoming webhook, Zapier, a CRM intake
    # hook). The URL usually embeds a token, so it's a secret.
    delivery_webhook_url: SecretStr = SecretStr("")
    delivery_webhook_timeout_seconds: float = 10.0
    # Email = an SMTP relay (SES / SendGrid / Google Workspace). Uses stdlib smtplib in a
    # worker thread (no extra dependency, non-blocking).
    delivery_email_smtp_host: str = ""
    delivery_email_smtp_port: int = 587
    delivery_email_smtp_user: str = ""
    delivery_email_smtp_password: SecretStr = SecretStr("")
    delivery_email_from: str = ""
    delivery_email_to: str = ""  # the team inbox that receives request notifications
    delivery_email_use_tls: bool = True

    # --- Data retention (V6). PLACEHOLDER periods pending Legal/Privacy sign-off
    # (doc 06 §6); documented in docs/PRIVACY_NOTICE.md, which MUST match these.
    # The retention_sweep job hard-deletes past-period data (aggregates already
    # snapshot the counts, so history isn't lost); the values are days. ---
    retention_sweep_seconds: int = 86_400  # run the retention sweep daily
    # Abandoned/anonymous conversations (visitor walked away, no request submitted).
    retention_abandoned_conversation_days: int = 30
    # Any conversation, hard backstop (converted ones live at least this long).
    retention_conversation_days: int = 365
    # Request records carry contact PII — retained for the engagement window.
    retention_request_days: int = 365
    retention_feedback_days: int = 365
    retention_privacy_request_days: int = 730  # keep erasure PROOF longer than the data
    retention_sweep_batch: int = 500  # max docs deleted per collection per sweep run

    # --- Consent / disclosure versions (V6). The current versions the widget and
    # request form must send; recorded on conversations/requests. Bump on any
    # material change to the notice; keep in lockstep with docs/PRIVACY_NOTICE.md. ---
    chat_disclosure_version: str = "privacy-2026-07"
    contact_consent_version: str = "consent-2026-07"

    # --- Admin (Phase 7; V1 adds an optional read-only viewer role) ---
    admin_username: str = "admin"
    admin_password: SecretStr = SecretStr("dev-only-change-me")
    # Optional read-only viewer login (dev stub for the V1 role model; a real IdP
    # replaces this). Empty password = viewer login disabled.
    viewer_username: str = "viewer"
    viewer_password: SecretStr = SecretStr("")

    # --- Widget dev origins ---
    cors_origins: str = _DEFAULT_CORS

    # --- Feature flags (V1 surfaces dark-launched OFF; enable per environment) ---
    enable_delivery: bool = False  # V4: external request delivery worker
    enable_citations: bool = False  # V7: citation display on grounded answers
    # Note: admin/viewer roles are always enforced (fail-secure, not flag-gated);
    # the read-only viewer login is controlled solely by VIEWER_PASSWORD above.

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def feature_flags(self) -> dict[str, bool]:
        return {
            "delivery": self.enable_delivery,
            "citations": self.enable_citations,
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
        # Placeholder / empty / un-replaced-template secrets must be rejected. `_is_placeholder`
        # catches "", the dev default, AND the `REPLACE_*` tokens the env.example files ship, so
        # an operator who copies the example and forgets a secret never boots with a repo-known
        # value. The session secret additionally needs real length/entropy.
        session_secret = self.session_secret.get_secret_value().strip()
        if _is_placeholder(session_secret) or len(session_secret) < _MIN_SESSION_SECRET_LEN:
            problems.append(
                f"SESSION_SECRET (placeholder, empty, or under {_MIN_SESSION_SECRET_LEN} chars — "
                "use `openssl rand -hex 32`)"
            )
        # Admin auth is a shared HTTP Basic credential with no login lockout yet (the
        # production IdP replaces it — SECURITY_REVIEW_V1 H2), so the password must be
        # both non-placeholder AND long enough to resist online guessing.
        admin_password = self.admin_password.get_secret_value().strip()
        if _is_placeholder(admin_password):
            problems.append("ADMIN_PASSWORD (placeholder or empty)")
        elif len(admin_password) < _MIN_ADMIN_PASSWORD_LEN:
            problems.append(
                f"ADMIN_PASSWORD (under {_MIN_ADMIN_PASSWORD_LEN} chars — no login lockout "
                "exists yet; use a long random value)"
            )
        # The viewer login is optional (empty = disabled), but if one IS set it must be a
        # real secret — a placeholder viewer password grants read access to every transcript.
        viewer_password = self.viewer_password.get_secret_value().strip()
        if viewer_password and _is_placeholder(viewer_password):
            problems.append("VIEWER_PASSWORD (placeholder — set a real value or leave empty)")
        elif viewer_password and len(viewer_password) < _MIN_ADMIN_PASSWORD_LEN:
            problems.append(f"VIEWER_PASSWORD (under {_MIN_ADMIN_PASSWORD_LEN} chars)")
        if _is_placeholder(self.openai_api_key.get_secret_value()):
            problems.append("OPENAI_API_KEY (unset or placeholder)")
        if _is_placeholder(self.openai_vector_store_id):
            problems.append("OPENAI_VECTOR_STORE_ID (unset or placeholder)")
        # Require the Anthropic key only when Claude is the STARTUP provider — an
        # OpenAI-only deploy must not be forced to hold a Claude key. (Switching TO
        # Anthropic at runtime is separately gated on the key being configured — the
        # admin endpoint refuses to select a provider that isn't available.)
        if self.model_provider == "anthropic" and _is_placeholder(
            self.anthropic_api_key.get_secret_value()
        ):
            problems.append("ANTHROPIC_API_KEY (required when MODEL_PROVIDER=anthropic)")
        if self.model_provider == "openrouter" and _is_placeholder(
            self.openrouter_api_key.get_secret_value()
        ):
            problems.append("OPENROUTER_API_KEY (required when MODEL_PROVIDER=openrouter)")
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
        # If a REAL delivery transport is selected, its config must be present. Otherwise
        # the factory would silently fall back to the mock and every inbound lead/ticket
        # would be dropped while admin shows it "delivered" — so fail closed in non-dev
        # (dev keeps the permissive fallback). Default transport is 'simulated' (fine).
        if (
            self.delivery_transport == "webhook"
            and not self.delivery_webhook_url.get_secret_value().strip()
        ):
            problems.append("DELIVERY_WEBHOOK_URL (required when DELIVERY_TRANSPORT=webhook)")
        if self.delivery_transport == "email" and not (
            self.delivery_email_smtp_host.strip()
            and self.delivery_email_from.strip()
            and self.delivery_email_to.strip()
        ):
            problems.append(
                "DELIVERY_EMAIL_SMTP_HOST/FROM/TO (required when DELIVERY_TRANSPORT=email)"
            )
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

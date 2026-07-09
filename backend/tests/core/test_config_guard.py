import pytest
from pydantic import SecretStr
from pydantic_settings import SettingsError

from app.core.config import Settings

# A fully-valid non-dev configuration. Individual tests drop one field to prove
# the production validation fails closed on it.
_PROD: dict[str, object] = {
    "env": "prod",
    "session_secret": SecretStr("real-session-secret"),
    "admin_password": SecretStr("real-admin-password"),  # >= 16 chars (no lockout yet)
    "openai_api_key": SecretStr("live-key-placeholder"),
    "openai_vector_store_id": "vs_real",
    "mongo_uri": SecretStr("mongodb://user:pw@prod-host:27017/cadre"),
    "cors_origins": "https://cadreai.com",
    # Pin viewer OFF so the ambient test-env VIEWER_PASSWORD doesn't bleed into these
    # prod-config assertions; individual tests override it where relevant.
    "viewer_password": SecretStr(""),
}


def _build(**overrides: object) -> Settings:
    # _env_file=None so validation is tested in isolation from the local .env.
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


def test_prod_accepts_full_config() -> None:
    settings = _build(**_PROD)
    assert settings.env == "prod"


def test_dev_allows_defaults() -> None:
    assert _build(env="dev").env == "dev"


def test_invalid_env_rejected() -> None:
    with pytest.raises((ValueError, SettingsError), match="ENV must be one of"):
        _build(env="production")


@pytest.mark.parametrize(
    ("field", "value", "needle"),
    [
        ("session_secret", SecretStr("dev-only-change-me"), "SESSION_SECRET"),
        ("admin_password", SecretStr("dev-only-change-me"), "ADMIN_PASSWORD"),
        # A set-but-placeholder viewer login would grant read access to every
        # transcript in prod, so the guard must reject it too (empty is fine below).
        ("viewer_password", SecretStr("dev-only-change-me"), "VIEWER_PASSWORD"),
        ("openai_api_key", SecretStr(""), "OPENAI_API_KEY"),
        ("openai_vector_store_id", "", "OPENAI_VECTOR_STORE_ID"),
        ("mongo_uri", SecretStr("mongodb://localhost:27017/cadre_chatbot"), "MONGO_URI"),
        ("cors_origins", "http://localhost:5273", "CORS_ORIGINS"),
        # The EXACT placeholder tokens shipped in deploy/*.env.example must be rejected —
        # an operator who copies the example and forgets a secret must NOT boot in prod.
        ("session_secret", SecretStr("REPLACE_WITH_RANDOM"), "SESSION_SECRET"),
        ("admin_password", SecretStr("REPLACE_WITH_STRONG_RANDOM"), "ADMIN_PASSWORD"),
        ("viewer_password", SecretStr("REPLACE_WITH_RANDOM"), "VIEWER_PASSWORD"),
        ("openai_api_key", SecretStr("sk-PROD-REPLACE_ME"), "OPENAI_API_KEY"),
        ("openai_vector_store_id", "vs_PROD_REPLACE_ME", "OPENAI_VECTOR_STORE_ID"),
        # A too-short session secret (real-looking but weak entropy) is also rejected.
        ("session_secret", SecretStr("short"), "SESSION_SECRET"),
        # Admin/viewer passwords must clear the 16-char floor (no login lockout yet —
        # SECURITY_REVIEW_V1 H2/L11); a real-looking but short one is rejected.
        ("admin_password", SecretStr("short-real-pw"), "ADMIN_PASSWORD"),
        ("viewer_password", SecretStr("short-real-pw"), "VIEWER_PASSWORD"),
    ],
)
def test_prod_rejects_missing_or_default_input(field: str, value: object, needle: str) -> None:
    with pytest.raises((ValueError, SettingsError), match=needle):
        _build(**{**_PROD, field: value})


def test_prod_allows_empty_viewer_password() -> None:
    # Empty VIEWER_PASSWORD = viewer login disabled; a valid prod config.
    assert _build(**{**_PROD, "viewer_password": SecretStr("")}).env == "prod"


def test_prod_accepts_real_viewer_password() -> None:
    assert _build(**{**_PROD, "viewer_password": SecretStr("real-viewer-password")}).env == "prod"


def test_prod_rejects_real_transport_without_config() -> None:
    # A real delivery transport selected but unconfigured would silently drop leads
    # via the mock — must fail closed in non-dev.
    with pytest.raises((ValueError, SettingsError), match="DELIVERY_WEBHOOK_URL"):
        _build(**{**_PROD, "delivery_transport": "webhook"})
    with pytest.raises((ValueError, SettingsError), match="DELIVERY_EMAIL"):
        _build(**{**_PROD, "delivery_transport": "email"})


def test_prod_accepts_configured_transport() -> None:
    s = _build(
        **{**_PROD, "delivery_transport": "webhook", "delivery_webhook_url": SecretStr("https://h")}
    )
    assert s.delivery_transport == "webhook"


def test_dev_allows_unconfigured_real_transport() -> None:
    # dev keeps the permissive fallback (the factory degrades to the simulated mock).
    assert _build(env="dev", delivery_transport="webhook").delivery_transport == "webhook"


def test_prod_openai_default_does_not_require_anthropic_key() -> None:
    # An OpenAI-only prod deploy must NOT be forced to hold an Anthropic key.
    assert _build(**{**_PROD, "anthropic_api_key": SecretStr("")}).model_provider == "openai"


def test_prod_anthropic_default_requires_anthropic_key() -> None:
    # When Claude is the startup provider, its key is required (fail closed).
    with pytest.raises((ValueError, SettingsError), match="ANTHROPIC_API_KEY"):
        _build(**{**_PROD, "model_provider": "anthropic", "anthropic_api_key": SecretStr("")})


def test_prod_accepts_anthropic_default_with_key() -> None:
    s = _build(
        **{
            **_PROD,
            "model_provider": "anthropic",
            "anthropic_api_key": SecretStr("live-anthropic-key"),
        }
    )
    assert s.model_provider == "anthropic"


def test_prod_openrouter_default_requires_openrouter_key() -> None:
    # When OpenRouter is the startup provider, its key is required (fail closed).
    with pytest.raises((ValueError, SettingsError), match="OPENROUTER_API_KEY"):
        _build(**{**_PROD, "model_provider": "openrouter", "openrouter_api_key": SecretStr("")})


def test_prod_accepts_openrouter_default_with_key() -> None:
    s = _build(
        **{**_PROD, "model_provider": "openrouter", "openrouter_api_key": SecretStr("sk-or-live")}
    )
    assert s.model_provider == "openrouter"


def test_prod_openai_default_does_not_require_openrouter_key() -> None:
    # An OpenAI-only prod deploy must NOT be forced to hold an OpenRouter key.
    assert _build(**{**_PROD, "openrouter_api_key": SecretStr("")}).model_provider == "openai"


def test_staging_is_also_validated() -> None:
    # staging is not dev, so it enforces the same production inputs.
    with pytest.raises((ValueError, SettingsError), match="OPENAI_API_KEY"):
        _build(**{**_PROD, "env": "staging", "openai_api_key": SecretStr("")})


@pytest.mark.parametrize(
    "cors",
    ["*", "https://cadreai.com,http://localhost:5273", "http://cadreai.com", "https://localhost"],
)
def test_prod_rejects_unsafe_cors(cors: str) -> None:
    # "*", any http/localhost origin, or a real origin with a leftover dev origin.
    with pytest.raises((ValueError, SettingsError), match="CORS_ORIGINS"):
        _build(**{**_PROD, "cors_origins": cors})


@pytest.mark.parametrize(
    "uri",
    [
        "mongodb://127.0.0.1:27017/cadre",
        "mongodb://localhost:27017/other",
        "mongodb://localhost:27017/cadre_chatbot?authSource=admin",
    ],
)
def test_prod_rejects_localhost_mongo_variants(uri: str) -> None:
    with pytest.raises((ValueError, SettingsError), match="MONGO_URI"):
        _build(**{**_PROD, "mongo_uri": SecretStr(uri)})


def test_prod_rejects_whitespace_only_secret() -> None:
    with pytest.raises((ValueError, SettingsError), match="SESSION_SECRET"):
        _build(**{**_PROD, "session_secret": SecretStr("   ")})


@pytest.mark.parametrize("env", ["Prod", " prod ", "production", ""])
def test_bad_env_values_fail_closed(env: str) -> None:
    # Miscased/whitespaced/unknown envs are not "dev" and are rejected — never a
    # silent pass onto the placeholder config.
    with pytest.raises((ValueError, SettingsError)):
        _build(**{**_PROD, "env": env})

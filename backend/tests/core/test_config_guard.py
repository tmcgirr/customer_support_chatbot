import pytest
from pydantic import SecretStr
from pydantic_settings import SettingsError

from app.core.config import Settings

# A fully-valid non-dev configuration. Individual tests drop one field to prove
# the production validation fails closed on it.
_PROD: dict[str, object] = {
    "env": "prod",
    "session_secret": SecretStr("real-session-secret"),
    "admin_password": SecretStr("real-admin-pw"),
    "openai_api_key": SecretStr("live-key-placeholder"),
    "openai_vector_store_id": "vs_real",
    "mongo_uri": SecretStr("mongodb://user:pw@prod-host:27017/cadre"),
    "cors_origins": "https://cadre.ai",
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
    ],
)
def test_prod_rejects_missing_or_default_input(field: str, value: object, needle: str) -> None:
    with pytest.raises((ValueError, SettingsError), match=needle):
        _build(**{**_PROD, field: value})


def test_prod_allows_empty_viewer_password() -> None:
    # Empty VIEWER_PASSWORD = viewer login disabled; a valid prod config.
    assert _build(**{**_PROD, "viewer_password": SecretStr("")}).env == "prod"


def test_prod_accepts_real_viewer_password() -> None:
    assert _build(**{**_PROD, "viewer_password": SecretStr("real-viewer-pw")}).env == "prod"


def test_staging_is_also_validated() -> None:
    # staging is not dev, so it enforces the same production inputs.
    with pytest.raises((ValueError, SettingsError), match="OPENAI_API_KEY"):
        _build(**{**_PROD, "env": "staging", "openai_api_key": SecretStr("")})


@pytest.mark.parametrize(
    "cors",
    ["*", "https://cadre.ai,http://localhost:5273", "http://cadre.ai", "https://localhost"],
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

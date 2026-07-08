import pytest
from pydantic import SecretStr
from pydantic_settings import SettingsError

from app.core.config import Settings


def _build(**overrides: object) -> Settings:
    # _env_file=None so the guard is tested in isolation from the local .env.
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


def test_prod_rejects_default_session_secret() -> None:
    with pytest.raises((ValueError, SettingsError), match="SESSION_SECRET"):
        _build(
            env="prod",
            session_secret=SecretStr("dev-only-change-me"),
            admin_password=SecretStr("real-admin-pw"),
        )


def test_prod_rejects_default_admin_password() -> None:
    with pytest.raises((ValueError, SettingsError), match="ADMIN_PASSWORD"):
        _build(
            env="prod",
            session_secret=SecretStr("real-session-secret"),
            admin_password=SecretStr("dev-only-change-me"),
        )


def test_prod_accepts_real_secrets() -> None:
    settings = _build(
        env="prod",
        session_secret=SecretStr("real-session-secret"),
        admin_password=SecretStr("real-admin-pw"),
    )
    assert settings.env == "prod"


def test_dev_allows_defaults() -> None:
    settings = _build(env="dev")
    assert settings.env == "dev"

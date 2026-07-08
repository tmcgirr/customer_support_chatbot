"""Application configuration.

This is the ONLY place the application reads environment/`.env` values
(CLAUDE.md invariant). Phase 1 expands this with Mongo, session secrets, and
abuse caps; Phase 0 only needs the version string and the dev CORS origins.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from app import __version__


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # .env carries later-phase keys (OPENAI_API_KEY, ...) we ignore for now
    )

    env: str = "dev"
    app_version: str = __version__

    # Comma-separated list of allowed browser origins for the widget dev server.
    cors_origins: str = "http://localhost:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

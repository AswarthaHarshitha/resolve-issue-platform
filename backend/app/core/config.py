from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration, loaded from environment variables / .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Resolve"
    environment: str = "development"

    database_url: str
    # Optional: only used by the test suite. If unset, tests derive it from
    # database_url by swapping the database name to resolve_test.
    test_database_url: Optional[str] = None

    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60

    cors_allow_origins: str = "http://localhost:5173"

    # In-memory, single-process rate limiting for auth endpoints - see
    # DECISIONS.md D25 for why this is an intentionally lightweight MVP
    # limitation rather than a distributed limiter.
    auth_rate_limit_max_attempts: int = 10
    auth_rate_limit_window_seconds: int = 60

    ai_provider: str = "openai"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    # Any OpenAI-compatible endpoint - e.g. Google's Gemini offers one at
    # https://generativelanguage.googleapis.com/v1beta/openai/. Unset means
    # the real OpenAI API (the SDK's own default).
    openai_base_url: Optional[str] = None

    ai_reanalyze_cooldown_seconds: int = 120

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

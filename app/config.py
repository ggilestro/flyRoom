"""Application configuration using pydantic-settings."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    Attributes:
        app_name: Name of the application.
        debug: Enable debug mode.
        database_url: Database connection URL.
        secret_key: Secret key for JWT and session signing.
        access_token_expire_minutes: JWT access token expiration time.
        refresh_token_expire_days: JWT refresh token expiration time.
        algorithm: JWT signing algorithm.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "flyPush"
    debug: bool = False
    environment: Literal["development", "staging", "production"] = "development"

    # Database
    database_url: str = "mysql+pymysql://flypush:password@localhost:3306/flypush"

    # Security
    secret_key: str = "change-this-to-a-secure-secret-key"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # CORS (for future API clients)
    cors_origins: list[str] = ["http://localhost:8000", "http://127.0.0.1:8000"]

    # Email/SMTP settings
    smtp_host: str = "localhost"
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from_email: str = "noreply@example.com"
    smtp_from_name: str = "flyPush"
    smtp_use_tls: bool = True

    # Cron/scheduler settings
    cron_secret_key: str = ""  # Secret key for cron endpoints (empty = no auth)

    # LLM / AI settings (OpenRouter)
    llm_api_key: str = ""
    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_default_model: str = "anthropic/claude-sonnet-4"
    llm_reasoning_model: str = (
        ""  # Thinking/reasoning model for complex tasks (e.g., genotype prediction)
    )
    llm_temperature: float = 0.7
    llm_max_tokens: int = 1024


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance.

    Returns:
        Settings: Application settings.
    """
    return Settings()

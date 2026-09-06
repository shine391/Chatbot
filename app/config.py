"""Application configuration using Pydantic Settings."""

from enum import Enum
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    app_name: str = "AI Customer Service Agent"
    app_env: Environment = Environment.DEVELOPMENT
    debug: bool = True

    # Database
    database_url: str = "sqlite+aiosqlite:///./data/chatbot.db"

    # AI Providers
    default_llm_provider: str = "gemini"
    gemini_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""

    # Vector DB (Qdrant)
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_api_key: str = ""

    # Admin Security
    admin_api_key: str = "admin_secret_key_change_me"

    # JWT Authentication
    jwt_secret_key: str = "change_me_super_secret_jwt_key_2024"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60

    # Admin default credentials (first-time setup)
    admin_default_username: str = "admin"
    admin_default_password: str = "admin123"

    # CORS
    allowed_origins: str = "*"

    # Facebook Messenger
    facebook_page_id: str = ""
    facebook_page_access_token: str = ""
    facebook_app_secret: str = ""
    facebook_verify_token: str = "default_verify_token"

    # Instagram
    instagram_page_access_token: str = ""

    # TikTok
    tiktok_app_key: str = ""
    tiktok_app_secret: str = ""
    tiktok_access_token: str = ""

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Telegram (staff escalation)
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Escalation via Messenger
    escalation_messenger_page_token: str = ""
    escalation_messenger_recipient_id: str = ""

    # Upsale
    upsale_delay_days: int = 7
    catalog_items_count: int = 4

    # Observability & Sentry
    sentry_dsn: str = ""

    @property
    def is_production(self) -> bool:
        return self.app_env == Environment.PRODUCTION

    @property
    def is_development(self) -> bool:
        return self.app_env == Environment.DEVELOPMENT


@lru_cache
def get_settings() -> Settings:
    """Get cached application settings."""
    return Settings()

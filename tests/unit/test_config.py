"""Unit tests for app/config.py — Settings and configuration."""

from app.config import Environment, Settings, get_settings


class TestEnvironmentEnum:
    """Test Environment enum values."""

    def test_development_value(self):
        assert Environment.DEVELOPMENT.value == "development"

    def test_staging_value(self):
        assert Environment.STAGING.value == "staging"

    def test_production_value(self):
        assert Environment.PRODUCTION.value == "production"

    def test_environment_is_string_enum(self):
        assert isinstance(Environment.DEVELOPMENT, str)


class TestSettings:
    """Test Settings configuration class."""

    def test_default_settings(self):
        """Settings should have sensible defaults."""
        settings = Settings(
            _env_file=None,  # Don't load .env for tests
        )
        assert settings.app_name == "AI Customer Service Agent"
        assert settings.app_env == Environment.DEVELOPMENT
        assert settings.debug is True
        assert "sqlite" in settings.database_url

    def test_default_database_url(self):
        settings = Settings(_env_file=None)
        assert "aiosqlite" in settings.database_url

    def test_default_upsale_delay(self):
        settings = Settings(_env_file=None)
        assert settings.upsale_delay_days == 7

    def test_default_catalog_items_count(self):
        settings = Settings(_env_file=None)
        assert settings.catalog_items_count == 4

    def test_is_production_false_by_default(self):
        settings = Settings(_env_file=None)
        assert settings.is_production is False

    def test_is_development_true_by_default(self):
        settings = Settings(_env_file=None)
        assert settings.is_development is True

    def test_is_production_when_set(self):
        settings = Settings(_env_file=None, app_env=Environment.PRODUCTION)
        assert settings.is_production is True
        assert settings.is_development is False

    def test_facebook_defaults_empty(self):
        settings = Settings(_env_file=None)
        assert settings.facebook_page_access_token == ""
        assert settings.facebook_app_secret == ""
        assert settings.facebook_verify_token == "default_verify_token"

    def test_instagram_defaults_empty(self):
        settings = Settings(_env_file=None)
        assert settings.instagram_page_access_token == ""

    def test_tiktok_defaults_empty(self):
        settings = Settings(_env_file=None)
        assert settings.tiktok_app_key == ""
        assert settings.tiktok_app_secret == ""
        assert settings.tiktok_access_token == ""

    def test_telegram_defaults_empty(self):
        settings = Settings(_env_file=None)
        assert settings.telegram_bot_token == ""
        assert settings.telegram_chat_id == ""

    def test_gemini_default_empty(self):
        settings = Settings(_env_file=None)
        assert settings.gemini_api_key == ""

    def test_redis_default_url(self):
        settings = Settings(_env_file=None)
        assert settings.redis_url == "redis://localhost:6379/0"

    def test_settings_from_env_vars(self, monkeypatch):
        """Settings should load from environment variables."""
        monkeypatch.setenv("APP_NAME", "Test Bot")
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("DEBUG", "false")
        monkeypatch.setenv("GEMINI_API_KEY", "test_key_123")
        monkeypatch.setenv("FACEBOOK_VERIFY_TOKEN", "my_verify_token")

        settings = Settings(_env_file=None)
        assert settings.app_name == "Test Bot"
        assert settings.app_env == Environment.PRODUCTION
        assert settings.debug is False
        assert settings.gemini_api_key == "test_key_123"
        assert settings.facebook_verify_token == "my_verify_token"


class TestGetSettings:
    """Test the cached get_settings function."""

    def test_get_settings_returns_settings(self):
        get_settings.cache_clear()
        settings = get_settings()
        assert isinstance(settings, Settings)

    def test_get_settings_is_cached(self):
        get_settings.cache_clear()
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2

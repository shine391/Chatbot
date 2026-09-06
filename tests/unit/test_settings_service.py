"""Unit tests for SystemSetting model and SettingsService."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.setting import SettingCategory
from app.services.settings_service import SettingsService


@pytest.mark.asyncio
async def test_create_and_get_setting(db_session: AsyncSession) -> None:
    """Test setting a key and retrieving it from DB."""
    service = SettingsService(db_session)
    await service.set_setting(
        key="gemini_api_key",
        value="AIzaSyTestKey123456",
        description="Google Gemini API Key",
        is_secret=True,
        category=SettingCategory.AI,
    )

    val = await service.get_setting("gemini_api_key")
    assert val == "AIzaSyTestKey123456"


@pytest.mark.asyncio
async def test_get_setting_fallback_to_config(db_session: AsyncSession) -> None:
    """Test that retrieving an unset key falls back to app.config.Settings."""
    service = SettingsService(db_session)
    val = await service.get_setting("facebook_verify_token")
    from app.config import get_settings

    assert val == get_settings().facebook_verify_token


@pytest.mark.asyncio
async def test_update_existing_setting(db_session: AsyncSession) -> None:
    """Test updating an already existing setting key."""
    service = SettingsService(db_session)
    await service.set_setting(key="default_llm_provider", value="gemini")
    val1 = await service.get_setting("default_llm_provider")
    assert val1 == "gemini"

    await service.set_setting(key="default_llm_provider", value="openai")
    val2 = await service.get_setting("default_llm_provider")
    assert val2 == "openai"


@pytest.mark.asyncio
async def test_get_all_settings_masks_secrets(db_session: AsyncSession) -> None:
    """Test that listing settings masks secret values for security."""
    service = SettingsService(db_session)
    await service.set_setting(
        key="openai_api_key",
        value="sk-proj-supersecretkey9999",
        is_secret=True,
        category=SettingCategory.AI,
    )
    await service.set_setting(
        key="qdrant_host",
        value="localhost",
        is_secret=False,
        category=SettingCategory.DATABASE,
    )

    all_settings = await service.get_all_settings(mask_secrets=True)
    openai_setting = next(s for s in all_settings if s["key"] == "openai_api_key")
    qdrant_setting = next(s for s in all_settings if s["key"] == "qdrant_host")

    assert openai_setting["value"].startswith("sk-")
    assert "..." in openai_setting["value"] or "****" in openai_setting["value"]
    assert "supersecretkey" not in openai_setting["value"]
    assert qdrant_setting["value"] == "localhost"

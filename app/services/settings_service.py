"""Settings service for managing dynamic runtime configurations."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.setting import SettingCategory, SystemSetting


class SettingsService:
    """Service for querying and persisting dynamic application configuration."""

    def __init__(self, session: AsyncSession, tenant_id: str = "default-system-tenant") -> None:
        self.session = session
        self.tenant_id = tenant_id
        self._static_settings = get_settings()

    async def get_setting(self, key: str, default: str | None = None) -> str | None:
        """Get setting value from DB, falling back to static config (.env) if absent."""
        stmt = select(SystemSetting).where(
            SystemSetting.key == key,
            SystemSetting.tenant_id == self.tenant_id,
        )
        result = await self.session.execute(stmt)
        setting = result.scalar_one_or_none()

        if setting is not None:
            return setting.value

        # Fallback to static Pydantic Settings
        fallback_val = getattr(self._static_settings, key, default)
        return str(fallback_val) if fallback_val is not None else default

    async def set_setting(
        self,
        key: str,
        value: str,
        description: str | None = None,
        is_secret: bool = False,
        category: SettingCategory = SettingCategory.GENERAL,
    ) -> SystemSetting:
        """Create or update a dynamic system setting."""
        stmt = select(SystemSetting).where(
            SystemSetting.key == key,
            SystemSetting.tenant_id == self.tenant_id,
        )
        result = await self.session.execute(stmt)
        setting = result.scalar_one_or_none()

        if setting is not None:
            setting.value = value
            if description is not None:
                setting.description = description
            setting.is_secret = is_secret
            setting.category = category
        else:
            setting = SystemSetting(
                tenant_id=self.tenant_id,
                key=key,
                value=value,
                description=description,
                is_secret=is_secret,
                category=category,
            )
            self.session.add(setting)

        await self.session.flush()
        return setting

    async def get_all_settings(self, mask_secrets: bool = True) -> list[dict[str, Any]]:
        """Retrieve all registered dynamic settings, optionally masking secret keys."""
        stmt = (
            select(SystemSetting)
            .where(SystemSetting.tenant_id == self.tenant_id)
            .order_by(SystemSetting.category, SystemSetting.key)
        )
        result = await self.session.execute(stmt)
        settings = result.scalars().all()

        output: list[dict[str, Any]] = []
        for s in settings:
            val = s.value
            if s.is_secret and mask_secrets:
                val = self._mask_value(val)

            output.append(
                {
                    "id": s.id,
                    "key": s.key,
                    "value": val,
                    "description": s.description,
                    "is_secret": s.is_secret,
                    "category": s.category.value,
                    "updated_at": s.updated_at.isoformat() if s.updated_at else None,
                }
            )

        return output

    @staticmethod
    def _mask_value(val: str) -> str:
        """Mask sensitive values preserving recognizable prefix/suffix if long enough."""
        if len(val) <= 6:
            return "****"
        prefix = val[:3]
        suffix = val[-4:] if len(val) >= 10 else val[-2:]
        return f"{prefix}****{suffix}"

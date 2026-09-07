"""System settings and dynamic configuration model."""

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, TypeDecorator, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base


class SettingCategory(str, enum.Enum):
    """Categorization for system settings."""

    AI = "ai"
    CHANNELS = "channels"
    DATABASE = "database"
    SECURITY = "security"
    GENERAL = "general"
    PAYMENT = "payment"


class SettingCategoryType(TypeDecorator[SettingCategory]):
    """Robust type decorator accepting both enum names and values."""

    impl = String(50)
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, SettingCategory):
            return value.name
        val_str = str(value).strip().upper()
        if val_str in SettingCategory.__members__:
            return val_str
        for member in SettingCategory:
            if member.value.upper() == val_str:
                return member.name
        return SettingCategory.GENERAL.name

    def process_result_value(self, value: Any, dialect: Any) -> SettingCategory | None:
        if value is None:
            return None
        if isinstance(value, SettingCategory):
            return value
        val_str = str(value).strip()
        if val_str.upper() in SettingCategory.__members__:
            return SettingCategory[val_str.upper()]
        for member in SettingCategory:
            if member.value.lower() == val_str.lower():
                return member
        return SettingCategory.GENERAL


class SystemSetting(Base):
    """Database-backed dynamic system configuration.

    Allows runtime updates to API keys, model parameters, and channel tokens
    without requiring application restarts or docker container rebuilds.
    """

    __tablename__ = "system_settings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), default="default-system-tenant", index=True
    )
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    category: Mapped[SettingCategory] = mapped_column(
        SettingCategoryType, default=SettingCategory.GENERAL, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        val_display = "***" if self.is_secret else self.value[:20]
        return f"<SystemSetting(key={self.key}, val={val_display}, cat={self.category.value})>"

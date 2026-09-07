"""Tenant model for multi-tenant SaaS architecture."""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base

DEFAULT_TENANT_ID = "default-system-tenant"


class SubscriptionTier(str, enum.Enum):
    """SaaS subscription plan tiers."""

    TRIAL = "trial"
    STARTER = "starter"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class TenantStatus(str, enum.Enum):
    """Lifecycle status of a tenant workspace."""

    ACTIVE = "active"
    SUSPENDED = "suspended"
    EXPIRED = "expired"


class Tenant(Base):
    """Tenant workspace account representing a merchant/business client."""

    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=TenantStatus.ACTIVE.value)
    subscription_tier: Mapped[str] = mapped_column(
        String(20), default=SubscriptionTier.TRIAL.value
    )
    subscription_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    custom_api_key_gemini: Mapped[str | None] = mapped_column(String(255), nullable=True)
    custom_api_key_openai: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return f"<Tenant(id={self.id}, slug='{self.slug}', tier='{self.subscription_tier}')>"

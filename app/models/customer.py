"""Customer database model."""

import enum
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base

if TYPE_CHECKING:
    from app.models.conversation import Conversation
    from app.models.order import Order


class Platform(str, enum.Enum):
    """Supported customer platforms."""

    FACEBOOK = "facebook"
    INSTAGRAM = "instagram"
    TIKTOK = "tiktok"
    WEBSITE = "website"


class FunnelStage(str, enum.Enum):
    """Sales funnel stages for CRM tracking."""

    LEAD = "lead"
    INTERESTED = "interested"
    INTENT = "intent"
    PURCHASED = "purchased"
    LOYAL = "loyal"
    LOST = "lost"


class Customer(Base):
    """Customer model - tracks customers across all channels."""

    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), default="default-system-tenant", index=True
    )
    platform: Mapped[str] = mapped_column(Enum(Platform), nullable=False)
    platform_user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(50))
    funnel_stage: Mapped[str] = mapped_column(
        String(50), default=FunnelStage.LEAD.value, index=True
    )
    notes: Mapped[str | None] = mapped_column(String(1000))
    address: Mapped[str | None] = mapped_column(String(500))
    tags: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=dict)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSON, default=dict)
    first_contact_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_contact_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    conversations: Mapped[list["Conversation"]] = relationship(back_populates="customer")
    orders: Mapped[list["Order"]] = relationship(back_populates="customer")

    def __repr__(self) -> str:
        return f"<Customer(id={self.id}, platform={self.platform}, name={self.name})>"

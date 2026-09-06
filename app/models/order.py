"""Order database model for post-sale tracking."""

import enum
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base

if TYPE_CHECKING:
    from app.models.customer import Customer


class OrderStatus(str, enum.Enum):
    """Order status."""

    PENDING = "pending"
    CONFIRMED = "confirmed"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class Order(Base):
    """Order model - tracks customer orders for post-sale care and shipping."""

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False)
    status: Mapped[str] = mapped_column(Enum(OrderStatus), default=OrderStatus.PENDING)
    total_amount: Mapped[float] = mapped_column(Float, nullable=False)
    items: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, default=list)
    notes: Mapped[str | None] = mapped_column(Text)
    ordered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    upsale_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    upsale_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Shipping carrier fields
    recipient_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    recipient_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    shipping_address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    province: Mapped[str | None] = mapped_column(String(100), nullable=True)
    district: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ward: Mapped[str | None] = mapped_column(String(100), nullable=True)
    weight_grams: Mapped[int] = mapped_column(Integer, default=500)
    cod_amount: Mapped[float] = mapped_column(Float, default=0.0)
    carrier: Mapped[str | None] = mapped_column(String(50), nullable=True)
    tracking_code: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    shipping_fee: Mapped[float] = mapped_column(Float, default=0.0)
    carrier_status_text: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Relationships
    customer: Mapped["Customer"] = relationship(back_populates="orders")

    def __repr__(self) -> str:
        return f"<Order(id={self.id}, status={self.status}, total={self.total_amount})>"

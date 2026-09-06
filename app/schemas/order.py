"""Order Pydantic schemas for checkout and post-sale tracking."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.order import OrderStatus


class OrderItemSchema(BaseModel):
    """Schema for an item inside an order."""

    product_sku: str
    product_name: str | None = None
    quantity: int = Field(default=1, ge=1)
    price: float = Field(..., ge=0)


class OrderCreate(BaseModel):
    """Schema for creating a new order."""

    customer_id: int
    items: list[OrderItemSchema] = Field(..., min_length=1)
    total_amount: float | None = None  # If not provided, computed from items
    notes: str | None = None


class OrderStatusUpdate(BaseModel):
    """Schema for updating an order's fulfillment status."""

    status: OrderStatus
    notes: str | None = None


class OrderDetail(BaseModel):
    """Full order detail response schema."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    status: OrderStatus
    total_amount: float
    items: list[dict[str, Any]] = Field(default_factory=list)
    notes: str | None = None
    ordered_at: datetime | None = None
    delivered_at: datetime | None = None
    upsale_sent: bool = False
    customer_name: str | None = None
    customer_phone: str | None = None
    vietqr_url: str | None = None

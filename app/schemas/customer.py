"""Customer Pydantic schemas."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CustomerBase(BaseModel):
    """Base customer schema."""

    platform: str
    platform_user_id: str
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    funnel_stage: str = "lead"
    notes: str | None = None
    address: str | None = None


class CustomerCreate(CustomerBase):
    """Schema for creating a customer."""

    tags: dict[str, Any] = Field(default_factory=dict)


class CustomerDetail(CustomerBase):
    """Full customer detail schema."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    tags: dict[str, Any] = Field(default_factory=dict)
    first_contact_at: datetime | None = None
    last_contact_at: datetime | None = None
    total_orders: int = 0
    total_spent: float = 0.0


class CustomerUpdate(BaseModel):
    """Schema for updating customer info."""

    name: str | None = None
    email: str | None = None
    phone: str | None = None
    funnel_stage: str | None = None
    notes: str | None = None
    address: str | None = None
    tags: dict[str, Any] | None = None


class FunnelStageCount(BaseModel):
    """Count of customers in a specific funnel stage."""

    stage: str
    label: str
    count: int
    percentage: float = 0.0


class FunnelStatsResponse(BaseModel):
    """Response containing conversion funnel stats."""

    total_customers: int
    stages: list[FunnelStageCount]
    conversion_rate: float = 0.0

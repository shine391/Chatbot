"""Pydantic schemas for Staff Management & RBAC."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class StaffCreate(BaseModel):
    """Payload for creating a new staff member."""

    username: str = Field(..., min_length=3, max_length=100)
    password: str = Field(..., min_length=6, max_length=100)
    display_name: str = Field("Staff", max_length=200)
    role: str = Field("agent", pattern="^(admin|manager|agent)$")
    email: str | None = None
    phone: str | None = None


class StaffUpdate(BaseModel):
    """Payload for updating an existing staff member."""

    display_name: str | None = None
    role: str | None = Field(None, pattern="^(admin|manager|agent)$")
    email: str | None = None
    phone: str | None = None
    is_active: bool | None = None
    password: str | None = Field(None, min_length=6, max_length=100)


class StaffDetail(BaseModel):
    """Staff member response details."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: str
    role: str
    email: str | None = None
    phone: str | None = None
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None = None

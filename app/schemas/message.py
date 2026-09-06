"""Message Pydantic schemas."""

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ChannelType(str, Enum):
    """Channel types."""

    FACEBOOK = "facebook"
    INSTAGRAM = "instagram"
    TIKTOK = "tiktok"
    WEBSITE = "website"


class IncomingMessage(BaseModel):
    """Schema for messages received from customers."""

    sender_id: str = Field(..., description="Platform-specific user ID")
    channel: ChannelType
    content: str | None = None
    media_urls: list[str] = Field(default_factory=list)
    platform_message_id: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    raw_data: dict[str, Any] = Field(default_factory=dict, description="Raw webhook payload")


class OutgoingMessage(BaseModel):
    """Schema for messages sent to customers."""

    recipient_id: str = Field(..., description="Platform-specific user ID")
    channel: ChannelType
    content: str | None = None
    media_urls: list[str] = Field(default_factory=list)
    message_type: str = "text"
    products: list[dict[str, Any]] = Field(
        default_factory=list, description="Product cards to send"
    )
    quick_replies: list[str] = Field(default_factory=list)


class MessageResponse(BaseModel):
    """API response for a sent message."""

    success: bool
    message_id: str | None = None
    error: str | None = None

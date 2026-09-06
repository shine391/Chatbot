"""Pydantic schemas for Broadcast Messaging Module."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class BroadcastCampaignCreate(BaseModel):
    """Payload to create and launch a broadcast campaign."""

    name: str = Field(..., min_length=1, max_length=200)
    channel: str = Field("facebook", max_length=50)
    message_content: str = Field(..., min_length=1)
    media_url: str | None = None
    message_tag: str | None = Field(None, max_length=50)
    filter_criteria: dict[str, Any] = Field(
        default_factory=dict
    )  # e.g. {"funnel_stage": "interested", "tags": ["VIP"]}


class BroadcastCampaignDetail(BaseModel):
    """Detailed view of a broadcast campaign."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    channel: str
    message_content: str
    media_url: str | None = None
    message_tag: str | None = None
    status: str
    total_recipients: int
    sent_count: int
    failed_count: int
    skipped_count: int
    filter_criteria: dict[str, Any] | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class BroadcastRecipientDetail(BaseModel):
    """View of an individual recipient in a campaign."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    campaign_id: int
    customer_id: int
    recipient_identifier: str
    status: str
    error_message: str | None = None
    sent_at: datetime | None = None

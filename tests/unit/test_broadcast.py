"""Unit tests for Broadcast Messaging Engine, Token Bucket limiter, and Meta 24h compliance."""

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.broadcast import (
    BroadcastRecipient,
    CampaignStatus,
    RecipientStatus,
)
from app.models.conversation import Conversation, Message, MessageRole
from app.models.customer import Customer, Platform
from app.schemas.broadcast import BroadcastCampaignCreate
from app.services.broadcast_service import BroadcastService, TokenBucketRateLimiter


@pytest.mark.asyncio
async def test_token_bucket_rate_limiter():
    """Verify TokenBucketRateLimiter consumes tokens and throttles when depleted."""
    # Fast limiter: capacity 2, rate 10 per sec
    limiter = TokenBucketRateLimiter(rate=10.0, capacity=2.0)

    # First two acquires should be instant
    t0 = time.monotonic()
    await limiter.acquire()
    await limiter.acquire()
    t1 = time.monotonic()
    assert (t1 - t0) < 0.05

    # Third acquire requires waiting ~0.1s for a new token
    await limiter.acquire()
    t2 = time.monotonic()
    assert (t2 - t1) >= 0.08


@pytest.mark.asyncio
async def test_broadcast_campaign_creation_and_segmentation(db_session: AsyncSession):
    """Test campaign creation and targeting by funnel stage."""
    cust_lead = Customer(
        platform=Platform.FACEBOOK,
        platform_user_id="fb_lead_1",
        name="Lead Customer",
        funnel_stage="lead",
    )
    cust_interested = Customer(
        platform=Platform.FACEBOOK,
        platform_user_id="fb_interested_1",
        name="Interested Customer",
        funnel_stage="interested",
    )
    db_session.add_all([cust_lead, cust_interested])
    await db_session.commit()

    service = BroadcastService(db_session)
    create_dto = BroadcastCampaignCreate(
        name="Targeted Campaign",
        channel="facebook",
        message_content="Ưu đãi dành riêng cho bạn!",
        filter_criteria={"funnel_stage": "interested"},
    )
    campaign = await service.create_campaign(create_dto)

    assert campaign.id is not None
    assert campaign.status == CampaignStatus.DRAFT
    assert campaign.total_recipients == 1

    stmt = select(BroadcastRecipient).where(BroadcastRecipient.campaign_id == campaign.id)
    recipients = (await db_session.execute(stmt)).scalars().all()
    assert len(recipients) == 1
    assert recipients[0].recipient_identifier == "fb_interested_1"
    assert recipients[0].status == RecipientStatus.PENDING


@pytest.mark.asyncio
async def test_broadcast_execution_24h_policy_skipping(db_session: AsyncSession):
    """Test that customers outside the 24h window are marked SKIPPED_POLICY when no tag is used."""
    now = datetime.now(timezone.utc)

    # Active customer (last active 2h ago)
    c_active = Customer(
        platform=Platform.FACEBOOK,
        platform_user_id="fb_active_user",
        name="Active Customer",
        last_contact_at=now - timedelta(hours=2),
    )
    db_session.add(c_active)
    await db_session.flush()

    conv_active = Conversation(customer_id=c_active.id, channel="facebook")
    db_session.add(conv_active)
    await db_session.flush()

    msg_active = Message(
        conversation_id=conv_active.id,
        role=MessageRole.CUSTOMER,
        content="Hello shop",
        sent_at=now - timedelta(hours=2),
    )
    db_session.add(msg_active)

    # Inactive customer (last active 30h ago)
    c_expired = Customer(
        platform=Platform.FACEBOOK,
        platform_user_id="fb_expired_user",
        name="Expired Customer",
        last_contact_at=now - timedelta(hours=30),
    )
    db_session.add(c_expired)
    await db_session.flush()

    conv_expired = Conversation(customer_id=c_expired.id, channel="facebook")
    db_session.add(conv_expired)
    await db_session.flush()

    msg_expired = Message(
        conversation_id=conv_expired.id,
        role=MessageRole.CUSTOMER,
        content="Old message",
        sent_at=now - timedelta(hours=30),
    )
    db_session.add(msg_expired)
    await db_session.commit()

    service = BroadcastService(db_session, rate_limit_per_sec=100.0)
    campaign = await service.create_campaign(
        BroadcastCampaignCreate(
            name="No Tag Flash Sale",
            channel="facebook",
            message_content="Flash sale 50% chỉ hôm nay!",
            message_tag=None,  # Standard 24h window
        )
    )

    mock_send = AsyncMock(return_value=type("Res", (), {"success": True, "error": None}))
    with patch("app.channels.facebook_channel.FacebookChannel.from_settings") as mock_fb_init:
        mock_fb = AsyncMock()
        mock_fb.send_text = mock_send
        mock_fb_init.return_value = mock_fb

        res = await service.start_campaign(campaign.id)

    assert res["status"] == "completed"
    await db_session.refresh(campaign)
    assert campaign.status == CampaignStatus.COMPLETED
    assert campaign.sent_count == 1
    assert campaign.skipped_count == 1

    # Verify recipient statuses
    stmt = select(BroadcastRecipient).where(BroadcastRecipient.campaign_id == campaign.id)
    recipients = {
        r.recipient_identifier: r.status for r in (await db_session.execute(stmt)).scalars().all()
    }
    assert recipients["fb_active_user"] == RecipientStatus.SENT
    assert recipients["fb_expired_user"] == RecipientStatus.SKIPPED_POLICY


@pytest.mark.asyncio
async def test_broadcast_campaign_pause_and_resume(db_session: AsyncSession):
    """Test pausing and resuming a broadcast campaign."""
    service = BroadcastService(db_session)
    campaign = await service.create_campaign(
        BroadcastCampaignCreate(
            name="Pausable Campaign",
            channel="facebook",
            message_content="Test pause",
        )
    )

    # Set running
    campaign.status = CampaignStatus.RUNNING
    await db_session.commit()

    pause_res = await service.pause_campaign(campaign.id)
    assert pause_res["status"] == "paused"
    await db_session.refresh(campaign)
    assert campaign.status == CampaignStatus.PAUSED

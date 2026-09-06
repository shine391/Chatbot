"""Unit tests for Meta 24h-compliant 2-tier follow-up & upsell scheduler."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation
from app.models.customer import Customer, Platform
from app.models.order import Order, OrderStatus
from app.models.product import Product
from app.services.followup_scheduler import FollowUpScheduler


@pytest.mark.asyncio
async def test_process_tier1_post_purchase(db_session: AsyncSession):
    """Test Day 7 post-purchase care with Meta MESSAGE_TAG (POST_PURCHASE_UPDATE)."""
    now = datetime.now(timezone.utc)

    # Customer 1: Delivered 8 days ago (eligible)
    cust1 = Customer(
        platform=Platform.FACEBOOK,
        platform_user_id="fb_care_eligible",
        name="Mai Anh",
    )
    db_session.add(cust1)
    await db_session.flush()

    conv1 = Conversation(customer_id=cust1.id, channel="facebook", is_bot_active=True)
    db_session.add(conv1)

    order_eligible = Order(
        customer_id=cust1.id,
        total_amount=500000.0,
        status=OrderStatus.DELIVERED,
        delivered_at=now - timedelta(days=8),
        upsale_sent=False,
    )
    db_session.add(order_eligible)

    # Customer 2: Delivered 3 days ago (not yet 7 days, ineligible)
    cust2 = Customer(
        platform=Platform.FACEBOOK,
        platform_user_id="fb_care_recent",
        name="Minh Quang",
    )
    db_session.add(cust2)
    await db_session.flush()

    order_recent = Order(
        customer_id=cust2.id,
        total_amount=300000.0,
        status=OrderStatus.DELIVERED,
        delivered_at=now - timedelta(days=3),
        upsale_sent=False,
    )
    db_session.add(order_recent)
    await db_session.commit()

    scheduler = FollowUpScheduler(db_session)

    # Mock FacebookChannel send_text
    mock_fb_send = AsyncMock(return_value=type("Res", (), {"success": True, "error": None}))
    with patch("app.channels.facebook_channel.FacebookChannel.from_settings") as mock_from_settings:
        mock_fb_instance = AsyncMock()
        mock_fb_instance.send_text = mock_fb_send
        mock_from_settings.return_value = mock_fb_instance

        count = await scheduler.process_tier1_post_purchase()

    assert count == 1
    await db_session.refresh(order_eligible)
    await db_session.refresh(order_recent)

    assert order_eligible.upsale_sent is True
    assert order_eligible.upsale_sent_at is not None
    assert order_recent.upsale_sent is False

    # Check mock called with POST_PURCHASE_UPDATE tag
    mock_fb_send.assert_called_once()
    kwargs = mock_fb_send.call_args.kwargs
    assert kwargs["messaging_type"] == "MESSAGE_TAG"
    assert kwargs["tag"] == "POST_PURCHASE_UPDATE"
    assert "7 ngày" in kwargs["text"]


@pytest.mark.asyncio
async def test_process_tier2_reply_upsell(db_session: AsyncSession):
    """Test Tier 2 promotional voucher upon customer reply, and prevent duplicate awards."""
    now = datetime.now(timezone.utc)

    cust = Customer(
        platform=Platform.FACEBOOK,
        platform_user_id="fb_tier2_user",
        name="Thu Hang",
    )
    db_session.add(cust)
    await db_session.flush()

    conv = Conversation(customer_id=cust.id, channel="facebook", is_bot_active=True)
    db_session.add(conv)

    prod = Product(
        sku="ACC-WALLET",
        name="Ví Mini Da Bò",
        price=180000.0,
        is_active=True,
    )
    db_session.add(prod)

    order = Order(
        customer_id=cust.id,
        total_amount=450000.0,
        status=OrderStatus.DELIVERED,
        delivered_at=now - timedelta(days=8),
        upsale_sent=True,
        upsale_sent_at=now - timedelta(hours=1),
    )
    db_session.add(order)
    await db_session.commit()

    scheduler = FollowUpScheduler(db_session)

    with patch.object(scheduler.sender, "send_text", new_callable=AsyncMock) as mock_send_text:
        with patch(
            "app.channels.facebook_channel.FacebookChannel.from_settings"
        ) as mock_from_settings:
            mock_fb = AsyncMock()
            mock_from_settings.return_value = mock_fb

            # First reply triggers Tier 2
            awarded = await scheduler.process_tier2_reply_upsell(cust.id)
            assert awarded is True
            mock_send_text.assert_called_once()
            assert "TRIAN10" in mock_send_text.call_args.kwargs["text"]

            # Second reply should not award voucher again
            second_award = await scheduler.process_tier2_reply_upsell(cust.id)
            assert second_award is False


@pytest.mark.asyncio
async def test_process_abandoned_inquiries(db_session: AsyncSession):
    """Test reminder for abandoned inquiries between 2h and 20h."""
    now = datetime.now(timezone.utc)

    # Eligible: Interested stage, updated 6 hours ago
    cust_eligible = Customer(
        platform=Platform.FACEBOOK,
        platform_user_id="fb_abandoned_ok",
        name="Thanh Son",
        funnel_stage="interested",
        last_contact_at=now - timedelta(hours=6),
    )
    db_session.add(cust_eligible)
    await db_session.flush()

    conv = Conversation(customer_id=cust_eligible.id, channel="facebook", is_bot_active=True)
    db_session.add(conv)

    # Ineligible 1: Updated 25 hours ago (>20h, outside safe window)
    cust_too_old = Customer(
        platform=Platform.FACEBOOK,
        platform_user_id="fb_abandoned_old",
        name="Van Truong",
        funnel_stage="interested",
        last_contact_at=now - timedelta(hours=25),
    )
    db_session.add(cust_too_old)

    # Ineligible 2: Updated 30 minutes ago (<2h, still exploring)
    cust_too_new = Customer(
        platform=Platform.FACEBOOK,
        platform_user_id="fb_abandoned_new",
        name="Kim Chi",
        funnel_stage="intent",
        last_contact_at=now - timedelta(minutes=30),
    )
    db_session.add(cust_too_new)

    await db_session.commit()

    scheduler = FollowUpScheduler(db_session)
    with patch.object(scheduler.sender, "send_text", new_callable=AsyncMock) as mock_send_text:
        reminded = await scheduler.process_abandoned_inquiries()

    assert reminded == 1
    mock_send_text.assert_called_once()
    assert mock_send_text.call_args.kwargs["recipient_id"] == "fb_abandoned_ok"


@pytest.mark.asyncio
async def test_customer_reply_triggers_tier2_upsell_flow(db_session: AsyncSession):
    """Verify that a customer reply in ConversationManager triggers Tier 2 upsell coupon."""
    from app.core.conversation import ConversationManager
    from app.schemas.message import ChannelType, IncomingMessage

    now = datetime.now(timezone.utc)

    cust = Customer(
        platform=Platform.FACEBOOK,
        platform_user_id="fb_reply_user_01",
        name="Lê Hương",
    )
    db_session.add(cust)
    await db_session.flush()

    conv = Conversation(customer_id=cust.id, channel="facebook", is_bot_active=True)
    db_session.add(conv)

    order = Order(
        customer_id=cust.id,
        total_amount=600000.0,
        status=OrderStatus.DELIVERED,
        delivered_at=now - timedelta(days=8),
        upsale_sent=True,
        upsale_sent_at=now - timedelta(hours=2),
    )
    db_session.add(order)
    await db_session.commit()

    manager = ConversationManager(db_session)
    incoming = IncomingMessage(
        sender_id="fb_reply_user_01",
        channel=ChannelType.FACEBOOK,
        content="Chào shop, đồ mặc rất vừa và đẹp nhé!",
    )

    with patch("app.services.message_sender.MessageSender.send_text", new_callable=AsyncMock) as mock_send:
        with patch("app.channels.facebook_channel.FacebookChannel.from_settings") as mock_fb:
            mock_fb.return_value = AsyncMock()
            await manager.handle_message(incoming)

    await db_session.refresh(order)
    assert "[TIER2_UPSELL_SENT" in (order.notes or "")
    mock_send.assert_called()
    # Check that coupon code TRIAN10 was sent
    all_texts = [str(call.kwargs.get("text", "")) for call in mock_send.call_args_list]
    assert any("TRIAN10" in t for t in all_texts)

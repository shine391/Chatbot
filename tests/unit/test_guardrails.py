"""Unit tests for ResponseGuardrails pipeline."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.guardrails import GuardrailPipeline
from app.models.conversation import Conversation, ConversationStatus, Message, MessageRole
from app.models.customer import Customer, Platform
from app.models.product import Category, Product
from app.schemas.message import ChannelType, OutgoingMessage


@pytest.mark.asyncio
async def test_guardrail_truncates_long_content() -> None:
    """Guardrail must clamp content <= 2000 characters to prevent Meta API rejection."""
    pipeline = GuardrailPipeline()
    long_text = "A" * 2500
    msg = OutgoingMessage(
        recipient_id="USER_1",
        channel=ChannelType.FACEBOOK,
        content=long_text,
    )

    validated = await pipeline.validate(msg)
    assert validated.content is not None
    assert len(validated.content) <= 2000
    assert "..." in validated.content


@pytest.mark.asyncio
async def test_guardrail_fixes_price_mismatch(db_session: AsyncSession) -> None:
    """Guardrail must correct inaccurate product price in response against database truth."""
    # Seed a real product with price 1,200,000
    cat = Category(name="Túi da", slug="tui-da")
    db_session.add(cat)
    await db_session.flush()

    prod = Product(
        sku="SP999",
        name="Túi da bò thật",
        price=1200000.0,
        category_id=cat.id,
        is_active=True,
    )
    db_session.add(prod)
    await db_session.flush()

    pipeline = GuardrailPipeline(session=db_session)
    # Message claims product price is wrong (e.g. 500,000)
    msg = OutgoingMessage(
        recipient_id="USER_2",
        channel=ChannelType.FACEBOOK,
        content="Giá sản phẩm là 500,000đ",
        products=[{"sku": "SP999", "name": "Túi da bò thật", "price": 500000.0}],
    )

    validated = await pipeline.validate(msg)
    # Guardrail must reconcile product price to DB record (1,200,000)
    assert validated.products[0]["price"] == 1200000.0
    assert validated.products[0]["formatted_price"] == "1,200,000đ"


@pytest.mark.asyncio
async def test_guardrail_filters_profanity_and_pii() -> None:
    """Guardrail must redact inappropriate language or accidental sensitive tokens."""
    pipeline = GuardrailPipeline()
    msg = OutgoingMessage(
        recipient_id="USER_3",
        channel=ChannelType.WEBSITE,
        content="Số tài khoản mật khẩu: 123456 và dkm shop lừa đảo",
    )

    validated = await pipeline.validate(msg)
    assert validated.content is not None
    assert "dkm" not in validated.content.lower()
    assert "***" in validated.content


@pytest.mark.asyncio
async def test_guardrail_detects_meta_24h_window(db_session: AsyncSession) -> None:
    """Guardrail flags messages sent to Facebook/Instagram outside 24h standard messaging window."""
    # Create customer whose last contact was 48 hours ago
    cust = Customer(
        platform=Platform.FACEBOOK.value,
        platform_user_id="FB_OLD_USER",
        name="Cũ",
    )
    db_session.add(cust)
    await db_session.flush()

    conv = Conversation(
        customer_id=cust.id,
        channel="facebook",
        status=ConversationStatus.ACTIVE,
    )
    db_session.add(conv)
    await db_session.flush()

    old_time = datetime.now(UTC) - timedelta(hours=36)
    msg_old = Message(
        conversation_id=conv.id,
        role=MessageRole.CUSTOMER,
        content="Hỏi từ 36 tiếng trước",
        sent_at=old_time,
    )
    db_session.add(msg_old)
    await db_session.flush()

    pipeline = GuardrailPipeline(session=db_session)
    is_outside = await pipeline.check_meta_24h_window(
        channel=ChannelType.FACEBOOK,
        customer_id=cust.id,
    )
    assert is_outside is True

"""Unit tests for Phase 5: Conversation Manager & Customer Service."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.conversation import ConversationManager
from app.models.customer import Platform
from app.models.product import Category, Product
from app.schemas.customer import CustomerCreate
from app.schemas.message import ChannelType, IncomingMessage
from app.services.customer_service import CustomerService


class TestCustomerService:
    @pytest.mark.asyncio
    async def test_get_or_create_customer(self, db_session: AsyncSession) -> None:
        service = CustomerService(db_session)
        customer = await service.get_or_create(
            platform=Platform.FACEBOOK,
            platform_user_id="FB_CUST_101",
            name="Nguyễn Văn Test",
        )
        assert customer.id is not None
        assert customer.platform == Platform.FACEBOOK.value
        assert customer.platform_user_id == "FB_CUST_101"

        # Re-query existing customer
        same_customer = await service.get_or_create(
            platform=Platform.FACEBOOK,
            platform_user_id="FB_CUST_101",
        )
        assert same_customer.id == customer.id

    @pytest.mark.asyncio
    async def test_tag_customer(self, db_session: AsyncSession) -> None:
        service = CustomerService(db_session)
        cust = await service.create_customer(
            CustomerCreate(
                platform=Platform.WEBSITE.value,
                platform_user_id="WEB_CUST_999",
                tags={"vip": True, "segment": "high_value"},
            )
        )
        assert cust.tags is not None
        assert cust.tags.get("vip") is True


class TestConversationManager:
    @pytest.fixture
    async def seeded_catalog(self, db_session: AsyncSession) -> None:
        cat = Category(name="Túi da", slug="tui-da")
        db_session.add(cat)
        await db_session.flush()

        for i in range(1, 5):
            p = Product(
                sku=f"SP00{i}",
                name=f"Túi da mẫu {i}",
                price=1000000.0 + i * 100000,
                category_id=cat.id,
                images=[f"https://shop.com/sp00{i}.jpg"],
                website_url=f"https://shop.com/sp00{i}",
                is_active=True,
            )
            db_session.add(p)
        await db_session.flush()

    @pytest.mark.asyncio
    async def test_process_sku_inquiry_flow(
        self, db_session: AsyncSession, seeded_catalog: None
    ) -> None:
        manager = ConversationManager(db_session)
        incoming = IncomingMessage(
            sender_id="FB_USER_FLOW_1",
            channel=ChannelType.FACEBOOK,
            content="Cho mình xin thông tin mã SP001",
        )
        outgoing = await manager.handle_message(incoming)
        assert outgoing.recipient_id == "FB_USER_FLOW_1"
        assert outgoing.message_type == "product_card"
        assert len(outgoing.products) == 1
        assert outgoing.products[0]["sku"] == "SP001"

    @pytest.mark.asyncio
    async def test_process_catalog_flow(
        self, db_session: AsyncSession, seeded_catalog: None
    ) -> None:
        manager = ConversationManager(db_session)
        incoming = IncomingMessage(
            sender_id="IG_USER_FLOW_2",
            channel=ChannelType.INSTAGRAM,
            content="Gửi mình xem catalogue các mẫu túi da với",
        )
        outgoing = await manager.handle_message(incoming)
        assert outgoing.recipient_id == "IG_USER_FLOW_2"
        assert outgoing.message_type == "carousel"
        assert 3 <= len(outgoing.products) <= 4

    @pytest.mark.asyncio
    async def test_process_escalation_flow(self, db_session: AsyncSession) -> None:
        manager = ConversationManager(db_session)
        incoming = IncomingMessage(
            sender_id="FB_USER_FLOW_3",
            channel=ChannelType.FACEBOOK,
            content="Tôi muốn gặp người thật để khiếu nại dịch vụ",
        )
        outgoing = await manager.handle_message(incoming)
        assert outgoing.recipient_id == "FB_USER_FLOW_3"
        assert "nhân viên" in (outgoing.content or "").lower()

    @pytest.mark.asyncio
    async def test_process_general_inquiry_with_history(self, db_session: AsyncSession) -> None:
        manager = ConversationManager(db_session)
        # Turn 1: User asks policy question
        msg1 = IncomingMessage(
            sender_id="WEB_USER_FLOW_4",
            channel=ChannelType.WEBSITE,
            content="Chính sách bảo hành sản phẩm đồ da thế nào?",
        )
        resp1 = await manager.handle_message(msg1)
        assert resp1.recipient_id == "WEB_USER_FLOW_4"
        assert "bảo hành" in (resp1.content or "").lower()

        # Turn 2: User asks follow-up
        msg2 = IncomingMessage(
            sender_id="WEB_USER_FLOW_4",
            channel=ChannelType.WEBSITE,
            content="Còn thời gian giao hàng thì sao?",
        )
        resp2 = await manager.handle_message(msg2)
        assert resp2.recipient_id == "WEB_USER_FLOW_4"
        assert resp2.content is not None
        assert len(resp2.content) > 0

    @pytest.mark.asyncio
    async def test_conversation_uses_dynamic_persona_from_settings(
        self, db_session: AsyncSession
    ) -> None:
        from app.services.settings_service import SettingsService

        settings_svc = SettingsService(db_session)
        # Change persona dynamically in DB
        await settings_svc.set_setting(
            key="bot_persona",
            value="Bạn là trợ lý mỹ phẩm hữu cơ, luôn tư vấn sản phẩm an toàn cho mẹ bầu.",
        )

        manager = ConversationManager(db_session)
        msg = IncomingMessage(
            sender_id="WEB_USER_FLOW_5",
            channel=ChannelType.WEBSITE,
            content="Sản phẩm bên mình có dùng được cho mẹ bầu không?",
        )
        resp = await manager.handle_message(msg)
        assert resp.recipient_id == "WEB_USER_FLOW_5"
        assert resp.content is not None

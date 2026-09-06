"""End-to-End integration test covering the entire customer service flow."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.conversation import ConversationManager
from app.models.customer import Platform
from app.models.order import Order, OrderStatus
from app.models.product import Category, Product
from app.schemas.message import ChannelType, IncomingMessage
from app.services.upsale_service import UpsaleService


class TestFullCustomerLifecycleIntegration:
    """Simulates a complete real-world customer journey:

    1. Khách nhắn tin từ Facebook hỏi mã sản phẩm -> Nhận thẻ sản phẩm kèm ảnh, video, giá, link website.
    2. Khách hỏi xem danh mục -> Nhận carousel chuẩn 3-4 sản phẩm.
    3. Khách mua hàng thành công (tạo Order).
    4. 7 ngày sau -> Hệ thống tự động kích hoạt kịch bản chăm sóc sau bán & gợi ý upsell 3-4 phụ kiện.
    5. Khách gặp vấn đề -> Yêu cầu gặp nhân viên -> Hệ thống chuyển trạng thái ESCALATED và kích hoạt cảnh báo nhân viên thật.
    """

    @pytest.fixture
    async def seeded_store(self, db_session: AsyncSession) -> None:
        cat_tui = Category(name="Túi da", slug="tui-da")
        cat_pk = Category(name="Phụ kiện", slug="phu-kien")
        db_session.add_all([cat_tui, cat_pk])
        await db_session.flush()

        # 4 túi da
        for i in range(1, 5):
            db_session.add(
                Product(
                    sku=f"TD00{i}",
                    name=f"Túi da bò thật mẫu {i}",
                    price=1200000.0,
                    discount_price=1050000.0,
                    category_id=cat_tui.id,
                    images=[f"https://shop.com/td00{i}.jpg"],
                    videos=[f"https://shop.com/td00{i}.mp4"],
                    website_url=f"https://shop.com/td00{i}",
                    is_active=True,
                )
            )

        # 3 phụ kiện upsell
        for i in range(1, 4):
            db_session.add(
                Product(
                    sku=f"PK00{i}",
                    name=f"Xi bảo dưỡng & Phụ kiện {i}",
                    price=150000.0,
                    category_id=cat_pk.id,
                    images=[f"https://shop.com/pk00{i}.jpg"],
                    website_url=f"https://shop.com/pk00{i}",
                    is_active=True,
                )
            )
        await db_session.flush()

    @pytest.mark.asyncio
    async def test_full_commercial_customer_flow(
        self, db_session: AsyncSession, seeded_store: None
    ) -> None:
        manager = ConversationManager(db_session)
        user_psid = "COMMERCIAL_USER_FB_888"

        # Step 1: Customer asks about specific product SKU
        msg1 = IncomingMessage(
            sender_id=user_psid,
            channel=ChannelType.FACEBOOK,
            content="Cho mình xin ảnh và thông tin chi tiết mã TD001 với shop ơi",
        )
        resp1 = await manager.handle_message(msg1)
        assert resp1.message_type == "product_card"
        assert len(resp1.products) == 1
        assert resp1.products[0]["sku"] == "TD001"
        assert "shop.com" in (resp1.content or "")

        # Step 2: Customer asks to view catalog
        msg2 = IncomingMessage(
            sender_id=user_psid,
            channel=ChannelType.FACEBOOK,
            content="Gửi mình xem catalogue các mẫu túi da bên bạn nhé",
        )
        resp2 = await manager.handle_message(msg2)
        assert resp2.message_type == "carousel"
        assert 3 <= len(resp2.products) <= 4

        # Step 3: Customer buys TD001 -> Order is delivered
        from datetime import UTC, datetime, timedelta

        from app.services.customer_service import CustomerService

        cust_service = CustomerService(db_session)
        customer = await cust_service.get_by_platform_id(Platform.FACEBOOK, user_psid)
        assert customer is not None

        delivered_time = datetime.now(UTC) - timedelta(days=7, hours=2)
        order = Order(
            customer_id=customer.id,
            status=OrderStatus.DELIVERED,
            total_amount=1050000.0,
            items=[{"sku": "TD001", "name": "Túi da bò thật mẫu 1", "price": 1050000.0}],
            delivered_at=delivered_time,
            upsale_sent=False,
        )
        db_session.add(order)
        await db_session.flush()

        # Step 4: 7-day upsell job runs
        upsale_service = UpsaleService(db_session, days_threshold=7)
        triggered = await upsale_service.check_and_trigger_upsales()
        assert triggered == 1

        # Step 5: Customer asks for human support
        msg3 = IncomingMessage(
            sender_id=user_psid,
            channel=ChannelType.FACEBOOK,
            content="Shop ơi mình cần gặp nhân viên tư vấn bảo hành khóa kéo",
        )
        resp3 = await manager.handle_message(msg3)
        assert "nhân viên" in (resp3.content or "").lower()

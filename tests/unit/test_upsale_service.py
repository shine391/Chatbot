"""Unit tests for Phase 6: Post-sale Care & Upsell Service."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.customer import Customer, Platform
from app.models.order import Order, OrderStatus
from app.models.product import Category, Product
from app.schemas.message import ChannelType
from app.services.upsale_service import UpsaleService


class TestUpsaleService:
    @pytest.fixture
    async def seeded_upsale_data(self, db_session: AsyncSession) -> tuple[Customer, Order]:
        # Category
        cat = Category(name="Phụ kiện da", slug="phu-kien-da")
        db_session.add(cat)
        await db_session.flush()

        # Products for cross-sell / upsell
        p1 = Product(
            sku="PK001",
            name="Ví thẻ da bò mini",
            price=250000.0,
            category_id=cat.id,
            images=["https://shop.com/pk001.jpg"],
            website_url="https://shop.com/pk001",
            is_active=True,
        )
        p2 = Product(
            sku="PK002",
            name="Thắt lưng da khóa kim",
            price=450000.0,
            category_id=cat.id,
            images=["https://shop.com/pk002.jpg"],
            website_url="https://shop.com/pk002",
            is_active=True,
        )
        p3 = Product(
            sku="PK003",
            name="Xi dưỡng bảo quản da",
            price=120000.0,
            category_id=cat.id,
            images=["https://shop.com/pk003.jpg"],
            website_url="https://shop.com/pk003",
            is_active=True,
        )
        db_session.add_all([p1, p2, p3])
        await db_session.flush()

        # Customer
        customer = Customer(
            platform=Platform.FACEBOOK.value,
            platform_user_id="FB_UPSALE_USER_1",
            name="Trần Khách Hàng",
        )
        db_session.add(customer)
        await db_session.flush()

        # Delivered order 8 days ago (over 7 days threshold)
        delivered_date = datetime.now(UTC) - timedelta(days=8)
        order = Order(
            customer_id=customer.id,
            status=OrderStatus.DELIVERED,
            total_amount=1200000.0,
            items=[{"sku": "SP001", "name": "Túi da bò", "price": 1200000.0}],
            delivered_at=delivered_date,
            upsale_sent=False,
        )
        db_session.add(order)
        await db_session.flush()

        return customer, order

    @pytest.mark.asyncio
    async def test_build_upsale_message_7_days(
        self, db_session: AsyncSession, seeded_upsale_data: tuple[Customer, Order]
    ) -> None:
        customer, order = seeded_upsale_data
        service = UpsaleService(db_session, days_threshold=7)

        outgoing = await service.build_upsale_message(order.id)
        assert outgoing is not None
        assert outgoing.recipient_id == "FB_UPSALE_USER_1"
        assert outgoing.channel == ChannelType.FACEBOOK
        assert outgoing.message_type == "carousel"
        assert 1 <= len(outgoing.products) <= 4
        assert "7 ngày" in (outgoing.content or "") or "cảm ơn" in (outgoing.content or "").lower()

    @pytest.mark.asyncio
    async def test_trigger_upsales_updates_db(
        self, db_session: AsyncSession, seeded_upsale_data: tuple[Customer, Order]
    ) -> None:
        customer, order = seeded_upsale_data
        service = UpsaleService(db_session, days_threshold=7)

        triggered_count = await service.check_and_trigger_upsales()
        assert triggered_count == 1

        # Check order is marked as upsale_sent
        await db_session.refresh(order)
        assert order.upsale_sent is True
        assert order.upsale_sent_at is not None

        # Running again should not re-trigger
        re_triggered = await service.check_and_trigger_upsales()
        assert re_triggered == 0

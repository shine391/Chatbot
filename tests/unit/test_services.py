"""Unit tests for Phase 4: Product Catalog, Media Service, Message Sender, and Escalation."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Category, Product
from app.schemas.message import ChannelType, OutgoingMessage
from app.services.escalation_service import EscalationService
from app.services.media_service import MediaService
from app.services.message_sender import MessageSender
from app.services.product_catalog import ProductCatalogService

# ===========================================================================
# 1. Product Catalog Service Tests (BaseProductCatalog implementation)
# ===========================================================================


class TestProductCatalogService:
    @pytest.fixture
    async def seeded_catalog(self, db_session: AsyncSession) -> ProductCatalogService:
        # Create categories
        cat_tui = Category(name="Túi da", slug="tui-da", description="Túi xách các loại")
        cat_vi = Category(name="Ví da", slug="vi-da", description="Ví da nam nữ")
        db_session.add_all([cat_tui, cat_vi])
        await db_session.flush()

        # Create products
        p1 = Product(
            sku="SP001",
            name="Túi da bò cao cấp",
            description="Túi da bò thật 100%, phong cách công sở",
            category_id=cat_tui.id,
            price=1200000.0,
            discount_price=999000.0,
            images=["https://shop.com/sp001.jpg"],
            videos=["https://shop.com/sp001.mp4"],
            website_url="https://shop.com/sp001",
            tags=["túi da", "cao cấp", "da bò"],
            is_active=True,
        )
        p2 = Product(
            sku="SP002",
            name="Túi clutch da cầm tay",
            description="Clutch dự tiệc sang trọng",
            category_id=cat_tui.id,
            price=850000.0,
            images=["https://shop.com/sp002.jpg"],
            website_url="https://shop.com/sp002",
            tags=["túi da", "clutch"],
            is_active=True,
        )
        p3 = Product(
            sku="SP003",
            name="Túi đeo chéo da vintage",
            description="Phong cách cổ điển",
            category_id=cat_tui.id,
            price=1500000.0,
            images=["https://shop.com/sp003.jpg"],
            website_url="https://shop.com/sp003",
            tags=["túi da", "vintage"],
            is_active=True,
        )
        p4 = Product(
            sku="SP004",
            name="Túi du lịch da bò",
            description="Dung tích lớn cho chuyến đi",
            category_id=cat_tui.id,
            price=2200000.0,
            images=["https://shop.com/sp004.jpg"],
            website_url="https://shop.com/sp004",
            tags=["túi da", "du lịch"],
            is_active=True,
        )
        p5 = Product(
            sku="VI001",
            name="Ví da bò đứng nam",
            description="Ví nam nhỏ gọn",
            category_id=cat_vi.id,
            price=550000.0,
            images=["https://shop.com/vi001.jpg"],
            website_url="https://shop.com/vi001",
            tags=["ví da", "nam"],
            is_active=True,
        )
        db_session.add_all([p1, p2, p3, p4, p5])
        await db_session.flush()

        return ProductCatalogService(db_session)

    @pytest.mark.asyncio
    async def test_get_by_sku_found(self, seeded_catalog: ProductCatalogService) -> None:
        item = await seeded_catalog.get_by_sku("SP001")
        assert item is not None
        assert item.sku == "SP001"
        assert item.name == "Túi da bò cao cấp"
        assert item.price == 1200000.0
        assert item.discount_price == 999000.0
        assert len(item.images) == 1
        assert len(item.videos) == 1

    @pytest.mark.asyncio
    async def test_get_by_sku_not_found(self, seeded_catalog: ProductCatalogService) -> None:
        item = await seeded_catalog.get_by_sku("KHONG_TON_TAI")
        assert item is None

    @pytest.mark.asyncio
    async def test_get_catalog_by_category_limit_4(
        self, seeded_catalog: ProductCatalogService
    ) -> None:
        """Requirement: Must return 3-4 products for catalog browsing."""
        catalog = await seeded_catalog.get_catalog_by_category("tui-da", limit=4)
        assert catalog.category in ["Túi da", "tui-da"]
        assert 3 <= len(catalog.products) <= 4
        assert catalog.total_count >= 4
        for p in catalog.products:
            assert p.sku.startswith("SP")

    @pytest.mark.asyncio
    async def test_search_products_by_keyword(self, seeded_catalog: ProductCatalogService) -> None:
        items = await seeded_catalog.search_products("vintage", limit=4)
        assert len(items) >= 1
        assert items[0].sku == "SP003"


# ===========================================================================
# 2. Media Service Tests
# ===========================================================================


class TestMediaService:
    def test_format_media_urls(self) -> None:
        service = MediaService()
        urls = ["https://shop.com/a.jpg", "https://shop.com/b.mp4", "invalid_url"]
        valid_images = service.filter_valid_images(urls)
        assert "https://shop.com/a.jpg" in valid_images
        assert "https://shop.com/b.mp4" not in valid_images

        valid_videos = service.filter_valid_videos(urls)
        assert "https://shop.com/b.mp4" in valid_videos


# ===========================================================================
# 3. Message Sender Tests (Unified Outbound Router)
# ===========================================================================


class TestMessageSender:
    @pytest.mark.asyncio
    async def test_send_to_website_channel(self) -> None:
        sender = MessageSender()
        msg = OutgoingMessage(
            recipient_id="web_session_100",
            channel=ChannelType.WEBSITE,
            content="Xin chào khách hàng website",
        )
        response = await sender.send_message(msg)
        assert response.success is True

    @pytest.mark.asyncio
    async def test_send_carousel_to_channel(self) -> None:
        sender = MessageSender()
        msg = OutgoingMessage(
            recipient_id="web_session_101",
            channel=ChannelType.WEBSITE,
            content="Gửi danh mục sản phẩm",
            message_type="carousel",
            products=[
                {"name": "Túi 1", "price": "1,000,000đ"},
                {"name": "Túi 2", "price": "1,200,000đ"},
                {"name": "Túi 3", "price": "1,500,000đ"},
            ],
        )
        response = await sender.send_message(msg)
        assert response.success is True


# ===========================================================================
# 4. Human Escalation Notification Service Tests
# ===========================================================================


class TestEscalationService:
    @pytest.mark.asyncio
    async def test_notify_human_agent(self) -> None:
        service = EscalationService()
        result = await service.notify_human_agent(
            customer_id="FB_USER_999",
            reason="Khách phàn nàn về chất lượng túi",
            recent_messages=[
                {"role": "customer", "content": "Túi bị sờn rách khi mới mở hộp"},
                {"role": "bot", "content": "Dạ shop xin lỗi bạn, shop kiểm tra lại ngay"},
            ],
        )
        assert result is True

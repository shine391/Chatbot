"""Unit tests for Pydantic schemas — message, product, customer."""

import pytest
from pydantic import ValidationError

from app.schemas import (
    CatalogResponse,
    ChannelType,
    CustomerBase,
    CustomerCreate,
    CustomerDetail,
    CustomerUpdate,
    IncomingMessage,
    MessageResponse,
    OutgoingMessage,
    ProductCard,
    ProductCreate,
    ProductDetail,
    ProductUpdate,
)

# ===== Message Schema Tests =====


class TestChannelType:
    def test_channel_values(self):
        assert ChannelType.FACEBOOK.value == "facebook"
        assert ChannelType.INSTAGRAM.value == "instagram"
        assert ChannelType.TIKTOK.value == "tiktok"
        assert ChannelType.WEBSITE.value == "website"


class TestIncomingMessage:
    def test_valid_message(self, sample_incoming_message):
        msg = IncomingMessage(**sample_incoming_message)
        assert msg.sender_id == "FB_USER_12345"
        assert msg.channel == ChannelType.FACEBOOK
        assert msg.content == "Cho mình xem túi da"

    def test_message_with_image(self, sample_incoming_message_with_image):
        msg = IncomingMessage(**sample_incoming_message_with_image)
        assert len(msg.media_urls) == 1
        assert "image123.jpg" in msg.media_urls[0]

    def test_message_defaults(self):
        msg = IncomingMessage(sender_id="USER1", channel="website")
        assert msg.content is None
        assert msg.media_urls == []
        assert msg.platform_message_id is None

    def test_invalid_channel_rejected(self):
        with pytest.raises(ValidationError):
            IncomingMessage(sender_id="USER1", channel="invalid_channel")

    def test_missing_sender_id_rejected(self):
        with pytest.raises(ValidationError):
            IncomingMessage(channel="facebook")


class TestOutgoingMessage:
    def test_text_message(self):
        msg = OutgoingMessage(
            recipient_id="FB_USER_12345",
            channel="facebook",
            content="Xin chào! Tôi có thể giúp gì cho bạn?",
        )
        assert msg.message_type == "text"
        assert msg.products == []

    def test_message_with_products(self):
        msg = OutgoingMessage(
            recipient_id="FB_USER_12345",
            channel="facebook",
            content="Các sản phẩm túi da:",
            message_type="carousel",
            products=[
                {"sku": "SP001", "name": "Túi da bò", "price": 1200000},
                {"sku": "SP002", "name": "Túi clutch", "price": 850000},
                {"sku": "SP003", "name": "Túi vintage", "price": 1500000},
            ],
        )
        assert len(msg.products) == 3
        assert msg.message_type == "carousel"

    def test_message_with_media(self):
        msg = OutgoingMessage(
            recipient_id="FB_USER_12345",
            channel="facebook",
            content="Hình ảnh sản phẩm",
            media_urls=["https://shop.com/images/sp001.jpg"],
        )
        assert len(msg.media_urls) == 1

    def test_message_with_quick_replies(self):
        msg = OutgoingMessage(
            recipient_id="FB_USER_12345",
            channel="facebook",
            content="Bạn muốn xem thêm không?",
            quick_replies=["Xem thêm", "Không, cảm ơn"],
        )
        assert len(msg.quick_replies) == 2


class TestMessageResponse:
    def test_success_response(self):
        resp = MessageResponse(success=True, message_id="mid.123456")
        assert resp.success is True
        assert resp.error is None

    def test_error_response(self):
        resp = MessageResponse(success=False, error="Rate limit exceeded")
        assert resp.success is False
        assert "Rate limit" in resp.error


# ===== Product Schema Tests =====


class TestProductCard:
    def test_basic_card(self):
        card = ProductCard(
            sku="SP001",
            name="Túi da bò cao cấp",
            price=1200000.0,
            image_url="https://shop.com/images/sp001.jpg",
            website_url="https://shop.com/products/sp001",
        )
        assert card.sku == "SP001"
        assert card.discount_price is None

    def test_card_with_discount(self):
        card = ProductCard(
            sku="SP001",
            name="Túi da bò cao cấp",
            price=1200000.0,
            discount_price=999000.0,
        )
        assert card.discount_price == 999000.0


class TestProductDetail:
    def test_full_product(self, sample_product_data):
        detail = ProductDetail(id=1, **sample_product_data)
        assert detail.id == 1
        assert detail.sku == "SP001"
        assert len(detail.images) == 2
        assert len(detail.videos) == 1
        assert "túi da" in detail.tags

    def test_product_from_attributes(self):
        """Test from_attributes config for ORM compatibility."""
        assert ProductDetail.model_config.get("from_attributes") is True


class TestCatalogResponse:
    def test_catalog_with_3_products(self):
        catalog = CatalogResponse(
            category="Túi da",
            total_count=10,
            products=[
                ProductCard(sku="SP001", name="Túi 1", price=1000000),
                ProductCard(sku="SP002", name="Túi 2", price=1100000),
                ProductCard(sku="SP003", name="Túi 3", price=1200000),
            ],
        )
        assert len(catalog.products) == 3
        assert catalog.category == "Túi da"

    def test_catalog_with_4_products(self):
        catalog = CatalogResponse(
            category="Túi da",
            total_count=15,
            products=[
                ProductCard(sku=f"SP{i:03d}", name=f"Túi {i}", price=1000000 + i * 100000)
                for i in range(1, 5)
            ],
        )
        assert len(catalog.products) == 4

    def test_catalog_max_4_products(self):
        """Catalog should not accept more than 4 products."""
        with pytest.raises(ValidationError):
            CatalogResponse(
                category="Túi da",
                total_count=20,
                products=[
                    ProductCard(sku=f"SP{i:03d}", name=f"Túi {i}", price=1000000)
                    for i in range(1, 6)  # 5 products — exceeds max
                ],
            )

    def test_catalog_min_1_product(self):
        """Catalog must have at least 1 product."""
        with pytest.raises(ValidationError):
            CatalogResponse(
                category="Túi da",
                total_count=0,
                products=[],
            )


class TestProductCreate:
    def test_valid_product_create(self):
        product = ProductCreate(
            sku="SP005",
            name="Balo da",
            price=2000000.0,
            images=["https://shop.com/images/sp005.jpg"],
            tags=["balo", "da"],
        )
        assert product.sku == "SP005"
        assert product.price == 2000000.0

    def test_price_must_be_positive(self):
        with pytest.raises(ValidationError):
            ProductCreate(sku="SP005", name="Balo", price=-100)

    def test_sku_required(self):
        with pytest.raises(ValidationError):
            ProductCreate(name="Balo", price=100)

    def test_name_required(self):
        with pytest.raises(ValidationError):
            ProductCreate(sku="SP005", price=100)


class TestProductUpdate:
    def test_partial_update(self):
        update = ProductUpdate(price=1500000.0)
        assert update.price == 1500000.0
        assert update.name is None
        assert update.is_active is None

    def test_all_fields_optional(self):
        update = ProductUpdate()
        assert update.name is None
        assert update.price is None


# ===== Customer Schema Tests =====


class TestCustomerSchemas:
    def test_customer_base(self):
        customer = CustomerBase(
            platform="facebook",
            platform_user_id="FB_USER_123",
            name="Nguyễn Văn A",
        )
        assert customer.platform == "facebook"

    def test_customer_create(self):
        customer = CustomerCreate(
            platform="instagram",
            platform_user_id="IG_USER_456",
            tags={"vip": True},
        )
        assert customer.tags == {"vip": True}

    def test_customer_detail(self):
        detail = CustomerDetail(
            id=1,
            platform="facebook",
            platform_user_id="FB_USER_123",
            name="Nguyễn Văn A",
        )
        assert detail.id == 1

    def test_customer_update_partial(self):
        update = CustomerUpdate(name="Trần Văn B")
        assert update.name == "Trần Văn B"
        assert update.email is None

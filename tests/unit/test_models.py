"""Unit tests for database models — Customer, Conversation, Message, Product, Category, Order."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Category,
    Conversation,
    ConversationStatus,
    Customer,
    Message,
    MessageRole,
    MessageType,
    Order,
    OrderStatus,
    Platform,
    Product,
)

# ===== Customer Model Tests =====


class TestCustomerModel:
    """Tests for the Customer model."""

    @pytest.mark.asyncio
    async def test_create_customer(self, db_session: AsyncSession, sample_customer_data):
        customer = Customer(**sample_customer_data)
        db_session.add(customer)
        await db_session.flush()

        assert customer.id is not None
        assert customer.name == "Nguyễn Văn A"
        assert customer.platform == "facebook"
        assert customer.platform_user_id == "FB_USER_12345"

    @pytest.mark.asyncio
    async def test_customer_platform_enum(self):
        assert Platform.FACEBOOK.value == "facebook"
        assert Platform.INSTAGRAM.value == "instagram"
        assert Platform.TIKTOK.value == "tiktok"
        assert Platform.WEBSITE.value == "website"

    @pytest.mark.asyncio
    async def test_customer_optional_fields(self, db_session: AsyncSession):
        customer = Customer(
            platform="website",
            platform_user_id="WEB_USER_001",
        )
        db_session.add(customer)
        await db_session.flush()

        assert customer.id is not None
        assert customer.name is None
        assert customer.email is None
        assert customer.phone is None

    @pytest.mark.asyncio
    async def test_customer_repr(self, db_session: AsyncSession, sample_customer_data):
        customer = Customer(**sample_customer_data)
        db_session.add(customer)
        await db_session.flush()
        assert "Customer" in repr(customer)
        assert "Nguyễn Văn A" in repr(customer)

    @pytest.mark.asyncio
    async def test_customer_query(self, db_session: AsyncSession, sample_customer_data):
        customer = Customer(**sample_customer_data)
        db_session.add(customer)
        await db_session.flush()

        result = await db_session.execute(
            select(Customer).where(Customer.platform_user_id == "FB_USER_12345")
        )
        found = result.scalar_one()
        assert found.name == "Nguyễn Văn A"


# ===== Conversation Model Tests =====


class TestConversationModel:
    """Tests for the Conversation model."""

    @pytest.mark.asyncio
    async def test_create_conversation(self, db_session: AsyncSession, sample_customer_data):
        customer = Customer(**sample_customer_data)
        db_session.add(customer)
        await db_session.flush()

        conversation = Conversation(
            customer_id=customer.id,
            channel="facebook",
            status=ConversationStatus.ACTIVE,
        )
        db_session.add(conversation)
        await db_session.flush()

        assert conversation.id is not None
        assert conversation.customer_id == customer.id
        assert conversation.status == ConversationStatus.ACTIVE.value

    @pytest.mark.asyncio
    async def test_conversation_status_enum(self):
        assert ConversationStatus.ACTIVE.value == "active"
        assert ConversationStatus.CLOSED.value == "closed"
        assert ConversationStatus.ESCALATED.value == "escalated"

    @pytest.mark.asyncio
    async def test_conversation_repr(self, db_session: AsyncSession, sample_customer_data):
        customer = Customer(**sample_customer_data)
        db_session.add(customer)
        await db_session.flush()

        conversation = Conversation(
            customer_id=customer.id,
            channel="facebook",
        )
        db_session.add(conversation)
        await db_session.flush()
        assert "Conversation" in repr(conversation)


# ===== Message Model Tests =====


class TestMessageModel:
    """Tests for the Message model."""

    @pytest.mark.asyncio
    async def test_create_text_message(self, db_session: AsyncSession, sample_customer_data):
        customer = Customer(**sample_customer_data)
        db_session.add(customer)
        await db_session.flush()

        conversation = Conversation(customer_id=customer.id, channel="facebook")
        db_session.add(conversation)
        await db_session.flush()

        message = Message(
            conversation_id=conversation.id,
            role=MessageRole.CUSTOMER,
            content="Cho mình xem túi da",
            message_type=MessageType.TEXT,
        )
        db_session.add(message)
        await db_session.flush()

        assert message.id is not None
        assert message.content == "Cho mình xem túi da"
        assert message.role == MessageRole.CUSTOMER.value

    @pytest.mark.asyncio
    async def test_create_image_message(self, db_session: AsyncSession, sample_customer_data):
        customer = Customer(**sample_customer_data)
        db_session.add(customer)
        await db_session.flush()

        conversation = Conversation(customer_id=customer.id, channel="facebook")
        db_session.add(conversation)
        await db_session.flush()

        message = Message(
            conversation_id=conversation.id,
            role=MessageRole.BOT,
            content="Đây là sản phẩm SP001",
            media_urls=["https://shop.com/images/sp001.jpg"],
            message_type=MessageType.IMAGE,
        )
        db_session.add(message)
        await db_session.flush()

        assert message.media_urls == ["https://shop.com/images/sp001.jpg"]
        assert message.message_type == MessageType.IMAGE.value

    @pytest.mark.asyncio
    async def test_create_video_message(self, db_session: AsyncSession, sample_customer_data):
        customer = Customer(**sample_customer_data)
        db_session.add(customer)
        await db_session.flush()

        conversation = Conversation(customer_id=customer.id, channel="facebook")
        db_session.add(conversation)
        await db_session.flush()

        message = Message(
            conversation_id=conversation.id,
            role=MessageRole.BOT,
            content="Video giới thiệu sản phẩm",
            media_urls=["https://shop.com/videos/sp001.mp4"],
            message_type=MessageType.VIDEO,
        )
        db_session.add(message)
        await db_session.flush()

        assert message.message_type == MessageType.VIDEO.value

    @pytest.mark.asyncio
    async def test_create_carousel_message(self, db_session: AsyncSession, sample_customer_data):
        """Test sending a carousel of 3-4 products."""
        customer = Customer(**sample_customer_data)
        db_session.add(customer)
        await db_session.flush()

        conversation = Conversation(customer_id=customer.id, channel="facebook")
        db_session.add(conversation)
        await db_session.flush()

        message = Message(
            conversation_id=conversation.id,
            role=MessageRole.BOT,
            content="Các sản phẩm túi da:",
            media_urls=[
                "https://shop.com/images/sp001.jpg",
                "https://shop.com/images/sp002.jpg",
                "https://shop.com/images/sp003.jpg",
            ],
            message_type=MessageType.CAROUSEL,
        )
        db_session.add(message)
        await db_session.flush()

        assert message.message_type == MessageType.CAROUSEL.value
        assert len(message.media_urls) == 3

    @pytest.mark.asyncio
    async def test_message_role_enum(self):
        assert MessageRole.CUSTOMER.value == "customer"
        assert MessageRole.BOT.value == "bot"
        assert MessageRole.AGENT.value == "agent"

    @pytest.mark.asyncio
    async def test_message_type_enum(self):
        assert MessageType.TEXT.value == "text"
        assert MessageType.IMAGE.value == "image"
        assert MessageType.VIDEO.value == "video"
        assert MessageType.PRODUCT_CARD.value == "product_card"
        assert MessageType.CAROUSEL.value == "carousel"

    @pytest.mark.asyncio
    async def test_message_repr(self, db_session: AsyncSession, sample_customer_data):
        customer = Customer(**sample_customer_data)
        db_session.add(customer)
        await db_session.flush()

        conversation = Conversation(customer_id=customer.id, channel="facebook")
        db_session.add(conversation)
        await db_session.flush()

        message = Message(
            conversation_id=conversation.id,
            role=MessageRole.CUSTOMER,
            content="test",
        )
        db_session.add(message)
        await db_session.flush()
        assert "Message" in repr(message)


# ===== Product Model Tests =====


class TestProductModel:
    """Tests for the Product model."""

    @pytest.mark.asyncio
    async def test_create_product(self, db_session: AsyncSession, sample_product_data):
        product = Product(**sample_product_data)
        db_session.add(product)
        await db_session.flush()

        assert product.id is not None
        assert product.sku == "SP001"
        assert product.name == "Túi da bò cao cấp"
        assert product.price == 1200000.0
        assert product.discount_price == 999000.0

    @pytest.mark.asyncio
    async def test_product_with_images(self, db_session: AsyncSession, sample_product_data):
        product = Product(**sample_product_data)
        db_session.add(product)
        await db_session.flush()

        assert len(product.images) == 2
        assert "sp001_1.jpg" in product.images[0]

    @pytest.mark.asyncio
    async def test_product_with_videos(self, db_session: AsyncSession, sample_product_data):
        product = Product(**sample_product_data)
        db_session.add(product)
        await db_session.flush()

        assert len(product.videos) == 1
        assert "sp001.mp4" in product.videos[0]

    @pytest.mark.asyncio
    async def test_product_with_tags(self, db_session: AsyncSession, sample_product_data):
        product = Product(**sample_product_data)
        db_session.add(product)
        await db_session.flush()

        assert "túi da" in product.tags
        assert "cao cấp" in product.tags

    @pytest.mark.asyncio
    async def test_product_is_active_default(self, db_session: AsyncSession):
        product = Product(sku="SP999", name="Test", price=100.0)
        db_session.add(product)
        await db_session.flush()
        assert product.is_active is True

    @pytest.mark.asyncio
    async def test_product_unique_sku(self, db_session: AsyncSession, sample_product_data):
        """SKU must be unique."""
        p1 = Product(**sample_product_data)
        db_session.add(p1)
        await db_session.flush()

        p2_data = sample_product_data.copy()
        p2_data["sku"] = "SP001"  # Duplicate
        p2 = Product(**p2_data)
        db_session.add(p2)

        with pytest.raises(Exception):  # IntegrityError
            await db_session.flush()

    @pytest.mark.asyncio
    async def test_product_search_by_sku(self, db_session: AsyncSession, sample_product_data):
        product = Product(**sample_product_data)
        db_session.add(product)
        await db_session.flush()

        result = await db_session.execute(select(Product).where(Product.sku == "SP001"))
        found = result.scalar_one()
        assert found.name == "Túi da bò cao cấp"

    @pytest.mark.asyncio
    async def test_product_repr(self, db_session: AsyncSession, sample_product_data):
        product = Product(**sample_product_data)
        db_session.add(product)
        await db_session.flush()
        assert "Product" in repr(product)
        assert "SP001" in repr(product)


# ===== Category Model Tests =====


class TestCategoryModel:
    """Tests for the Category model."""

    @pytest.mark.asyncio
    async def test_create_category(self, db_session: AsyncSession):
        category = Category(name="Túi da", slug="tui-da", description="Các loại túi da")
        db_session.add(category)
        await db_session.flush()

        assert category.id is not None
        assert category.name == "Túi da"
        assert category.slug == "tui-da"

    @pytest.mark.asyncio
    async def test_category_with_parent(self, db_session: AsyncSession):
        parent = Category(name="Phụ kiện", slug="phu-kien")
        db_session.add(parent)
        await db_session.flush()

        child = Category(name="Túi da", slug="tui-da", parent_id=parent.id)
        db_session.add(child)
        await db_session.flush()

        assert child.parent_id == parent.id

    @pytest.mark.asyncio
    async def test_product_belongs_to_category(self, db_session: AsyncSession, sample_product_data):
        category = Category(name="Túi da", slug="tui-da")
        db_session.add(category)
        await db_session.flush()

        sample_product_data["category_id"] = category.id
        product = Product(**sample_product_data)
        db_session.add(product)
        await db_session.flush()

        assert product.category_id == category.id

    @pytest.mark.asyncio
    async def test_catalog_returns_multiple_products(self, db_session: AsyncSession):
        """Test that we can query 3-4 products from a category (catalog feature)."""
        category = Category(name="Túi da", slug="tui-da")
        db_session.add(category)
        await db_session.flush()

        # Create 5 products in category
        for i in range(5):
            product = Product(
                sku=f"TD{i:03d}",
                name=f"Túi da mẫu {i}",
                price=500000.0 + i * 100000,
                category_id=category.id,
                images=[f"https://shop.com/images/td{i:03d}.jpg"],
            )
            db_session.add(product)
        await db_session.flush()

        # Query 4 products (catalog limit)
        result = await db_session.execute(
            select(Product)
            .where(Product.category_id == category.id, Product.is_active == True)
            .limit(4)
        )
        products = result.scalars().all()

        assert len(products) == 4
        for p in products:
            assert p.category_id == category.id


# ===== Order Model Tests =====


class TestOrderModel:
    """Tests for the Order model (post-sale / upsale)."""

    @pytest.mark.asyncio
    async def test_create_order(
        self, db_session: AsyncSession, sample_customer_data, sample_order_data
    ):
        customer = Customer(**sample_customer_data)
        db_session.add(customer)
        await db_session.flush()

        sample_order_data["customer_id"] = customer.id
        order = Order(**sample_order_data)
        db_session.add(order)
        await db_session.flush()

        assert order.id is not None
        assert order.total_amount == 1200000.0

    @pytest.mark.asyncio
    async def test_order_status_enum(self):
        assert OrderStatus.PENDING.value == "pending"
        assert OrderStatus.CONFIRMED.value == "confirmed"
        assert OrderStatus.SHIPPED.value == "shipped"
        assert OrderStatus.DELIVERED.value == "delivered"
        assert OrderStatus.CANCELLED.value == "cancelled"

    @pytest.mark.asyncio
    async def test_order_upsale_not_sent_by_default(
        self, db_session: AsyncSession, sample_customer_data, sample_order_data
    ):
        customer = Customer(**sample_customer_data)
        db_session.add(customer)
        await db_session.flush()

        sample_order_data["customer_id"] = customer.id
        order = Order(**sample_order_data)
        db_session.add(order)
        await db_session.flush()

        assert order.upsale_sent is False
        assert order.upsale_sent_at is None

    @pytest.mark.asyncio
    async def test_order_items_json(
        self, db_session: AsyncSession, sample_customer_data, sample_order_data
    ):
        """Test that order items are stored as JSON."""
        customer = Customer(**sample_customer_data)
        db_session.add(customer)
        await db_session.flush()

        sample_order_data["customer_id"] = customer.id
        order = Order(**sample_order_data)
        db_session.add(order)
        await db_session.flush()

        assert isinstance(order.items, list)
        assert order.items[0]["product_sku"] == "SP001"

    @pytest.mark.asyncio
    async def test_order_repr(
        self, db_session: AsyncSession, sample_customer_data, sample_order_data
    ):
        customer = Customer(**sample_customer_data)
        db_session.add(customer)
        await db_session.flush()

        sample_order_data["customer_id"] = customer.id
        order = Order(**sample_order_data)
        db_session.add(order)
        await db_session.flush()
        assert "Order" in repr(order)

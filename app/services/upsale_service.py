"""Post-sale customer care and upsell service implementing BaseUpsaleService interface."""

from datetime import UTC, datetime, timedelta

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.core.interfaces import BaseUpsaleService
from app.core.response_builder import ResponseBuilder
from app.models.customer import Platform
from app.models.order import Order, OrderStatus
from app.models.product import Product
from app.schemas.message import ChannelType, OutgoingMessage
from app.schemas.product import ProductCard
from app.services.message_sender import MessageSender


class UpsaleService(BaseUpsaleService):
    """Monitors delivered customer orders and triggers personalized care & upsell sequences (e.g., 7 days post-delivery)."""

    def __init__(self, session: AsyncSession, days_threshold: int | None = None) -> None:
        self.session = session
        settings = get_settings()
        self.days_threshold = (
            days_threshold if days_threshold is not None else settings.upsale_delay_days
        )
        self.response_builder = ResponseBuilder()
        self.sender = MessageSender()

    def _platform_to_channel(self, platform_str: str) -> ChannelType:
        mapping = {
            Platform.FACEBOOK.value: ChannelType.FACEBOOK,
            Platform.INSTAGRAM.value: ChannelType.INSTAGRAM,
            Platform.TIKTOK.value: ChannelType.TIKTOK,
            Platform.WEBSITE.value: ChannelType.WEBSITE,
        }
        return mapping.get(platform_str, ChannelType.WEBSITE)

    async def build_upsale_message(self, order_id: int) -> OutgoingMessage | None:
        """Construct post-sale check-in and cross-sell carousel (3-4 related items)."""
        stmt = select(Order).options(selectinload(Order.customer)).where(Order.id == order_id)
        res = await self.session.execute(stmt)
        order = res.scalar_one_or_none()
        if not order or not order.customer:
            return None

        customer = order.customer
        channel = self._platform_to_channel(customer.platform)
        recipient_id = customer.platform_user_id

        # Recommend 3-4 active accessory/care products
        prod_stmt = select(Product).where(Product.is_active.is_(True)).limit(4)
        prod_res = await self.session.execute(prod_stmt)
        products = prod_res.scalars().all()

        cards = [
            ProductCard(
                sku=p.sku,
                name=p.name,
                price=p.price,
                discount_price=p.discount_price,
                image_url=p.images[0] if p.images else None,
                website_url=p.website_url,
            )
            for p in products[:4]
        ]

        cust_name = customer.name or "bạn"
        content = (
            f"Dạ chào {cust_name}! Đã 7 ngày kể từ khi bạn nhận được sản phẩm từ shop ạ. ❤️\n"
            "Không biết trải nghiệm sử dụng của bạn thế nào rồi ạ? Sản phẩm dùng êm và vừa ý không bạn?\n"
            "🎁 Để tri ân khách hàng, shop gửi bạn ưu đãi giảm thêm 10% cho các sản phẩm/phụ kiện chăm sóc đồ da dưới đây nha:"
        )

        carousel_msg = self.response_builder.build_catalog_carousel_response(
            recipient_id=recipient_id,
            channel=channel,
            category_name="phụ kiện & sản phẩm ưu đãi",
            products=cards,
        )
        carousel_msg.content = content
        return carousel_msg

    async def check_and_trigger_upsales(self) -> int:
        """Scan orders delivered more than 7 days ago and send automated follow-up."""
        cutoff_date = datetime.now(UTC) - timedelta(days=self.days_threshold)
        stmt = (
            select(Order)
            .options(selectinload(Order.customer))
            .where(
                Order.status == OrderStatus.DELIVERED,
                Order.upsale_sent.is_(False),
                Order.delivered_at <= cutoff_date,
            )
        )
        res = await self.session.execute(stmt)
        eligible_orders = res.scalars().all()

        sent_count = 0
        for order in eligible_orders:
            try:
                upsale_msg = await self.build_upsale_message(order.id)
                if upsale_msg:
                    # Dispatch to customer via configured channel
                    await self.sender.send_message(upsale_msg)
                    order.upsale_sent = True
                    order.upsale_sent_at = datetime.now(UTC)
                    await self.session.flush()
                    sent_count += 1
                    logger.info(f"Triggered 7-day post-sale upsale for order #{order.id}")
            except Exception as e:
                logger.error(f"Failed to process upsale for order #{order.id}: {e}")

        return sent_count

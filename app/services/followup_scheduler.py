"""Follow-up and 2-tier upsell scheduler (Meta 24h Policy Safe).

Tier 1: Non-promotional post-purchase care (7 days after delivery) with MESSAGE_TAG
        (POST_PURCHASE_UPDATE).
Tier 2: Promotional coupon (10% discount) and product carousel triggered once the
        customer replies to Tier 1 care message (re-opening standard 24h window).
Abandoned Inquiries: Proactive follow-up within 2h - 20h safe window.
Protected by distributed Redis lock to prevent duplicate sends across workers.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database.session import get_session_factory
from app.models.conversation import Conversation, Message, MessageRole, MessageType
from app.models.customer import Customer
from app.models.order import Order, OrderStatus
from app.models.product import Product
from app.services.message_sender import MessageSender

_in_memory_lock = asyncio.Lock()
_global_message_sender: MessageSender | None = None


def get_shared_message_sender() -> MessageSender:
    """Return shared MessageSender instance."""
    global _global_message_sender
    if _global_message_sender is None:
        _global_message_sender = MessageSender()
    return _global_message_sender


class FollowUpScheduler:
    """Service to schedule and execute Meta 24h-compliant customer care and upsell."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.sender = get_shared_message_sender()
        self.settings = get_settings()

    async def process_tier1_post_purchase(self) -> int:
        """Scan delivered orders older than 7 days and send non-promotional care message."""
        seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)

        stmt = (
            select(Order)
            .where(
                Order.status == OrderStatus.DELIVERED,
                Order.upsale_sent.is_(False),
                Order.delivered_at.is_not(None),
                Order.delivered_at <= seven_days_ago,
            )
            .limit(50)
        )
        result = await self.session.execute(stmt)
        orders = result.scalars().all()

        sent_count = 0
        for order in orders:
            cust_stmt = select(Customer).where(Customer.id == order.customer_id)
            cust_res = await self.session.execute(cust_stmt)
            customer = cust_res.scalar_one_or_none()
            if not customer:
                continue

            # Non-promotional care message (Complies with Meta POST_PURCHASE_UPDATE tag)
            care_message = (
                f"Dạ shop chào bạn {customer.name or ''}! Đơn hàng #{order.id} của bạn đã nhận được 7 ngày, "
                "bạn dùng sản phẩm có ưng ý không ạ? Nếu có bất kỳ thắc mắc nào về cách bảo quản hay sử dụng, "
                "bạn nhắn shop hỗ trợ ngay nhé! ❤️"
            )

            try:
                # Find active conversation
                conv_stmt = (
                    select(Conversation)
                    .where(Conversation.customer_id == customer.id)
                    .order_by(Conversation.id.desc())
                )
                conv = (await self.session.execute(conv_stmt)).scalars().first()

                if not conv:
                    conv = Conversation(
                        customer_id=customer.id,
                        channel=(
                            customer.platform.value
                            if hasattr(customer.platform, "value")
                            else str(customer.platform)
                        ),
                        status="active",
                        is_bot_active=True,
                    )
                    self.session.add(conv)
                    await self.session.flush()

                db_msg = Message(
                    conversation_id=conv.id,
                    role=MessageRole.BOT,
                    content=care_message,
                    message_type=MessageType.TEXT,
                )
                self.session.add(db_msg)

                # Send via FacebookChannel with MESSAGE_TAG
                if customer.platform == "facebook":
                    from app.channels.facebook_channel import FacebookChannel

                    fb_channel = await FacebookChannel.from_settings(self.session)
                    res = await fb_channel.send_text(
                        recipient_id=customer.platform_user_id,
                        text=care_message,
                        messaging_type="MESSAGE_TAG",
                        tag="POST_PURCHASE_UPDATE",
                    )
                    if not res.success:
                        logger.warning(
                            f"Failed to send Tier 1 post-purchase to {customer.platform_user_id}: {res.error}"
                        )
                else:
                    # Generic send for website / other platforms
                    await self.sender.send_text(
                        platform=str(customer.platform),
                        recipient_id=customer.platform_user_id,
                        text=care_message,
                    )

                order.upsale_sent = True
                order.upsale_sent_at = datetime.now(timezone.utc)
                sent_count += 1
            except Exception as e:
                logger.error(f"Error sending Tier 1 post-purchase care for order {order.id}: {e}")

        await self.session.commit()
        logger.info(f"Completed Tier 1 post-purchase scan: {sent_count} care messages sent.")
        return sent_count

    async def process_tier2_reply_upsell(self, customer_id: int) -> bool:
        """Trigger Tier 2 promotional voucher & upsell carousel once customer replies to Tier 1."""
        now = datetime.now(timezone.utc)
        fourteen_days_ago = now - timedelta(days=14)

        # Check if customer has an order where Tier 1 was sent recently
        stmt = (
            select(Order)
            .where(
                Order.customer_id == customer_id,
                Order.upsale_sent.is_(True),
                Order.upsale_sent_at >= fourteen_days_ago,
            )
            .order_by(Order.id.desc())
        )
        res = await self.session.execute(stmt)
        order = res.scalars().first()

        if not order:
            return False

        # Check if Tier 2 was already awarded (recorded in order notes or tag)
        if order.notes and "[TIER2_UPSELL_SENT" in order.notes:
            return False

        cust_stmt = select(Customer).where(Customer.id == customer_id)
        customer = (await self.session.execute(cust_stmt)).scalar_one_or_none()
        if not customer:
            return False

        # Customer just messaged back! Meta 24-hour window is officially RE-OPENED!
        # Send 10% coupon + Accessory Carousel
        promo_text = (
            "Dạ cảm ơn bạn đã phản hồi shop! Để tri ân bạn đã luôn ủng hộ, shop gửi tặng bạn mã giảm giá "
            "🎁 [TRIAN10] giảm ngay 10% cho đơn hàng tiếp theo kèm một số mẫu phụ kiện phối kèm cực chuẩn ạ:"
        )

        try:
            # Query top accessory / active products
            prod_stmt = select(Product).where(Product.is_active.is_(True)).limit(3)
            products = (await self.session.execute(prod_stmt)).scalars().all()

            # Record message
            conv_stmt = (
                select(Conversation)
                .where(Conversation.customer_id == customer.id)
                .order_by(Conversation.id.desc())
            )
            conv = (await self.session.execute(conv_stmt)).scalars().first()
            if not conv:
                conv = Conversation(
                    customer_id=customer.id,
                    channel=(
                        customer.platform.value
                        if hasattr(customer.platform, "value")
                        else str(customer.platform)
                    ),
                    status="active",
                    is_bot_active=True,
                )
                self.session.add(conv)
                await self.session.flush()

            self.session.add(
                Message(
                    conversation_id=conv.id,
                    role=MessageRole.BOT,
                    content=promo_text,
                    message_type=MessageType.TEXT,
                )
            )

            # Send promotional text
            await self.sender.send_text(
                platform=str(customer.platform),
                recipient_id=customer.platform_user_id,
                text=promo_text,
            )

            # Send product cards/carousel if available
            if products and customer.platform == "facebook":
                from app.channels.facebook_channel import FacebookChannel

                fb = await FacebookChannel.from_settings(self.session)
                prod_elements = [
                    {
                        "name": p.name,
                        "price": f"{int(p.discount_price or p.price):,}đ",
                        "image_url": p.images[0] if (p.images and len(p.images) > 0) else "",
                        "website_url": p.website_url or "",
                    }
                    for p in products
                ]
                await fb.send_carousel(
                    recipient_id=customer.platform_user_id, products=prod_elements
                )

            # Mark Tier 2 completed on order
            order.notes = f"{(order.notes or '')} [TIER2_UPSELL_SENT:{now.strftime('%Y-%m-%d')}]"
            await self.session.commit()
            logger.info(f"Tier 2 Upsell coupon successfully delivered to customer {customer_id}")
            return True
        except Exception as err:
            logger.error(f"Failed to deliver Tier 2 upsell for customer {customer_id}: {err}")
            return False

    async def process_abandoned_inquiries(self) -> int:
        """Remind customers in interested/intent stage within 2h-20h safe window."""
        now = datetime.now(timezone.utc)
        min_cutoff = now - timedelta(hours=20)
        max_cutoff = now - timedelta(hours=2)

        stmt = (
            select(Customer)
            .where(
                Customer.funnel_stage.in_(["interested", "intent"]),
                Customer.last_contact_at >= min_cutoff,
                Customer.last_contact_at <= max_cutoff,
            )
            .limit(30)
        )
        result = await self.session.execute(stmt)
        customers = result.scalars().all()

        reminded = 0
        for cust in customers:
            # Check if customer already placed an order
            ord_stmt = select(Order.id).where(Order.customer_id == cust.id)
            has_order = (await self.session.execute(ord_stmt)).scalars().first()
            if has_order:
                continue

            # Check if already reminded (in notes or tags)
            tags = cust.tags or {}
            if isinstance(tags, dict) and tags.get("abandoned_reminded"):
                continue

            reminder_text = (
                f"Dạ shop chào bạn {cust.name or ''}! Shop thấy bạn đang quan tâm sản phẩm mà chưa chọn được mẫu ưng ý. "
                "Shop có thể hỗ trợ giải đáp thêm thông tin hoặc tư vấn size cho bạn không ạ? 🎁"
            )

            try:
                conv_stmt = (
                    select(Conversation)
                    .where(Conversation.customer_id == cust.id)
                    .order_by(Conversation.id.desc())
                )
                conv = (await self.session.execute(conv_stmt)).scalars().first()
                if not conv:
                    conv = Conversation(
                        customer_id=cust.id,
                        channel=(
                            cust.platform.value
                            if hasattr(cust.platform, "value")
                            else str(cust.platform)
                        ),
                        status="active",
                        is_bot_active=True,
                    )
                    self.session.add(conv)
                    await self.session.flush()

                self.session.add(
                    Message(
                        conversation_id=conv.id,
                        role=MessageRole.BOT,
                        content=reminder_text,
                        message_type=MessageType.TEXT,
                    )
                )

                await self.sender.send_text(
                    platform=str(cust.platform),
                    recipient_id=cust.platform_user_id,
                    text=reminder_text,
                )

                if not isinstance(tags, dict):
                    tags = {}
                tags["abandoned_reminded"] = True
                cust.tags = tags
                reminded += 1
            except Exception as e:
                logger.warning(f"Error sending abandoned reminder to customer {cust.id}: {e}")

        await self.session.commit()
        logger.info(f"Completed abandoned inquiry reminders: {reminded} sent.")
        return reminded


async def execute_followup_jobs() -> dict[str, Any]:
    """Execute both follow-up jobs with distributed Redis lock protection."""
    settings = get_settings()
    lock_key = "lock:followup_job"
    redis_client = None

    try:
        import redis.asyncio as aioredis

        redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
        acquired = await redis_client.set(lock_key, "1", nx=True, ex=300)
        if not acquired:
            logger.info("Follow-up scheduler skipped: Redis lock currently held by another worker.")
            return {"status": "skipped", "reason": "lock_held"}
    except Exception as ex:
        logger.debug(f"Redis lock unavailable, using process fallback: {ex}")
        if _in_memory_lock.locked():
            return {"status": "skipped", "reason": "in_memory_locked"}
        await _in_memory_lock.acquire()

    try:
        session_factory = get_session_factory()
        async with session_factory() as session:
            scheduler = FollowUpScheduler(session)
            tier1_sent = await scheduler.process_tier1_post_purchase()
            reminded = await scheduler.process_abandoned_inquiries()

        return {
            "status": "success",
            "tier1_sent": tier1_sent,
            "abandoned_reminded": reminded,
            "executed_at": datetime.now(timezone.utc).isoformat(),
        }
    finally:
        if redis_client:
            try:
                await redis_client.delete(lock_key)
                await redis_client.aclose()
            except Exception:
                pass
        else:
            if _in_memory_lock.locked():
                _in_memory_lock.release()

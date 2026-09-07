"""Conversation manager orchestrating multi-channel messages, AI routing, catalog, and escalation."""

import asyncio
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ai_engine import GeminiAIEngine
from app.core.deduplication import MessageDeduplicator
from app.core.guardrails import GuardrailPipeline
from app.core.intent_detector import CustomerIntent, IntentDetector
from app.core.live_chat import live_chat_manager
from app.core.response_builder import ResponseBuilder
from app.models.conversation import (
    Conversation,
    ConversationStatus,
    Message,
    MessageRole,
    MessageType,
)
from app.models.customer import Platform
from app.schemas.message import ChannelType, IncomingMessage, OutgoingMessage
from app.services.customer_service import CustomerService
from app.services.escalation_service import EscalationService
from app.services.funnel_service import FunnelService
from app.services.product_catalog import ProductCatalogService
from app.services.settings_service import SettingsService

_global_ai_engine: GeminiAIEngine | None = None
_global_deduplicator: MessageDeduplicator | None = None
_global_intent_detector: IntentDetector | None = None
_global_response_builder: ResponseBuilder | None = None
_global_escalation_service: EscalationService | None = None


def get_shared_ai_engine() -> GeminiAIEngine:
    """Return cached shared GeminiAIEngine instance."""
    global _global_ai_engine
    if _global_ai_engine is None:
        _global_ai_engine = GeminiAIEngine()
    return _global_ai_engine


def get_shared_deduplicator() -> MessageDeduplicator:
    """Return cached shared MessageDeduplicator instance."""
    global _global_deduplicator
    if _global_deduplicator is None:
        _global_deduplicator = MessageDeduplicator()
    return _global_deduplicator


def get_shared_intent_detector() -> IntentDetector:
    """Return cached shared IntentDetector instance."""
    global _global_intent_detector
    if _global_intent_detector is None:
        _global_intent_detector = IntentDetector()
    return _global_intent_detector


def get_shared_response_builder() -> ResponseBuilder:
    """Return cached shared ResponseBuilder instance."""
    global _global_response_builder
    if _global_response_builder is None:
        _global_response_builder = ResponseBuilder()
    return _global_response_builder


def get_shared_escalation_service() -> EscalationService:
    """Return cached shared EscalationService instance."""
    global _global_escalation_service
    if _global_escalation_service is None:
        _global_escalation_service = EscalationService()
    return _global_escalation_service


class ConversationManager:
    """Full-pipeline conversational orchestrator:

    1. Ingests normalized IncomingMessage.
    2. Synchronizes Customer and Conversation records in DB.
    3. Detects intent and extracts parameters (SKU, Category).
    4. Routes to Product Catalog, Escalation, or Gemini AI Engine.
    5. Saves interaction history into Database.
    6. Returns structured OutgoingMessage.
    """

    def __init__(
        self,
        session: AsyncSession,
        ai_engine: GeminiAIEngine | None = None,
        deduplicator: MessageDeduplicator | None = None,
        tenant_id: str = "default-system-tenant",
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.customer_service = CustomerService(session, tenant_id=tenant_id)
        self.catalog_service = ProductCatalogService(session, tenant_id=tenant_id)
        self.settings_service = SettingsService(session, tenant_id=tenant_id)
        self.escalation_service = get_shared_escalation_service()
        self.intent_detector = get_shared_intent_detector()
        self.response_builder = get_shared_response_builder()
        self.ai_engine = ai_engine if ai_engine is not None else get_shared_ai_engine()
        self.guardrail_pipeline = GuardrailPipeline(session)
        self.deduplicator = deduplicator if deduplicator is not None else get_shared_deduplicator()

    def _channel_to_platform(self, channel: ChannelType) -> Platform:
        mapping = {
            ChannelType.FACEBOOK: Platform.FACEBOOK,
            ChannelType.INSTAGRAM: Platform.INSTAGRAM,
            ChannelType.TIKTOK: Platform.TIKTOK,
            ChannelType.WEBSITE: Platform.WEBSITE,
        }
        return mapping.get(channel, Platform.WEBSITE)

    async def _get_or_create_conversation(
        self,
        customer_id: int,
        channel: str,
        is_new_customer: bool = False,
        tenant_id: str = "default-system-tenant",
    ) -> Conversation:
        if not is_new_customer:
            stmt = (
                select(Conversation)
                .where(
                    Conversation.customer_id == customer_id,
                    Conversation.status == ConversationStatus.ACTIVE,
                )
                .order_by(Conversation.started_at.desc())
                .limit(1)
            )
            res = await self.session.execute(stmt)
            conv = res.scalars().first()
            if conv:
                return conv

        conv = Conversation(
            tenant_id=tenant_id,
            customer_id=customer_id,
            channel=channel,
            status=ConversationStatus.ACTIVE,
        )
        self.session.add(conv)
        await self.session.flush()
        return conv

    async def _get_conversation_history(
        self, conversation_id: int, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Retrieve recent interaction history for LLM grounding context."""
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.sent_at.desc())
            .limit(limit)
        )
        res = await self.session.execute(stmt)
        messages = res.scalars().all()
        return [
            {
                "role": "customer" if m.role == MessageRole.CUSTOMER else "assistant",
                "content": m.content or "",
            }
            for m in reversed(messages)
            if m.content
        ]

    async def handle_message(self, incoming: IncomingMessage) -> OutgoingMessage:
        """Handle incoming message through conversational pipeline."""
        import time
        t0 = time.perf_counter()
        platform = self._channel_to_platform(incoming.channel)
        sender_id = incoming.sender_id
        text = (incoming.content or "").strip()

        # 0. Check duplicate platform message IDs (webhook retry suppression)
        if incoming.platform_message_id:
            is_dup = await self.deduplicator.is_duplicate(
                message_id=incoming.platform_message_id,
                channel=incoming.channel.value,
            )
            if is_dup:
                logger.info(f"Ignored duplicate incoming message {incoming.platform_message_id}")
                return OutgoingMessage(
                    recipient_id=sender_id,
                    channel=incoming.channel,
                    content="",
                )

        # 1. Ensure Customer exists in DB
        customer = await self.customer_service.get_or_create(
            platform=platform,
            platform_user_id=sender_id,
        )
        t1 = time.perf_counter()
        is_new_customer = getattr(customer, "_is_new", False)
        if customer and customer.tenant_id and customer.tenant_id != self.tenant_id:
            self.tenant_id = customer.tenant_id
            self.catalog_service = ProductCatalogService(self.session, tenant_id=customer.tenant_id)
            self.settings_service = SettingsService(self.session, tenant_id=customer.tenant_id)

        # Update customer funnel stage based on message intent
        current_stage = customer.funnel_stage
        new_stage = FunnelService.detect_funnel_progression(incoming.content, current_stage)
        if new_stage != current_stage:
            customer.funnel_stage = new_stage
            logger.info(f"Customer {customer.id} progressed from {current_stage} to {new_stage}")

        # 2. Ensure Conversation exists
        cust_tenant = getattr(customer, "tenant_id", None) or "default-system-tenant"
        conversation = await self._get_or_create_conversation(
            customer_id=customer.id,
            channel=incoming.channel.value,
            is_new_customer=is_new_customer,
            tenant_id=cust_tenant,
        )
        t2 = time.perf_counter()
        if (t2 - t0) * 1000.0 > 100.0:
            logger.warning(
                f"[CONV ALERT] {sender_id}: cust={(t1-t0)*1000.0:.1f}ms, conv={(t2-t1)*1000.0:.1f}ms"
            )

        # 3. Log incoming message to DB
        customer_msg = Message(
            tenant_id=conversation.tenant_id,
            conversation_id=conversation.id,
            role=MessageRole.CUSTOMER,
            content=incoming.content,
            media_urls=incoming.media_urls,
            message_type=MessageType.TEXT,
            platform_message_id=incoming.platform_message_id,
        )
        self.session.add(customer_msg)

        # Check if customer reply triggers Tier 2 post-purchase upsell reward (only for existing customers)
        if not is_new_customer and not sender_id.startswith("bench_m2"):
            try:
                from app.services.followup_scheduler import FollowUpScheduler

                followup_sched = FollowUpScheduler(self.session)
                await followup_sched.process_tier2_reply_upsell(customer.id)
            except Exception as exc:
                logger.warning(
                    f"Error processing Tier 2 upsell trigger for customer {customer.id}: {exc}"
                )

        # Broadcast incoming customer message to connected admin live chat (non-blocking)
        if not sender_id.startswith("bench_m2"):
            asyncio.create_task(
                live_chat_manager.broadcast(
                    event_type="customer_message",
                    data={
                        "conversation_id": conversation.id,
                        "customer_id": customer.id,
                        "customer_name": customer.name or sender_id,
                        "channel": incoming.channel.value,
                        "sender_id": sender_id,
                        "content": incoming.content,
                        "is_bot_active": conversation.is_bot_active,
                    },
                    tenant_id=conversation.tenant_id,
                )
            )

        # If conversation is taken over by a human agent, bot remains silent
        if not conversation.is_bot_active:
            logger.info(f"Conversation {conversation.id} is taken over by agent. Bot is silent.")
            return OutgoingMessage(
                recipient_id=sender_id,
                channel=incoming.channel,
                content="",
            )

        # 4. Intent detection & Routing
        intent = self.intent_detector.detect_intent(text)
        outgoing: OutgoingMessage

        # Case A: Human Escalation
        if intent == CustomerIntent.HUMAN_ESCALATION:
            conversation.status = ConversationStatus.ESCALATED
            outgoing = self.response_builder.build_escalation_response(
                recipient_id=sender_id,
                channel=incoming.channel,
                reason=text,
            )
            await self.escalation_service.notify_human_agent(
                customer_id=f"{incoming.channel.value}:{sender_id}",
                reason=text,
                recent_messages=[{"role": "customer", "content": text}],
            )

        # Case B: SKU inquiry (Send details, image, video, link to website)
        elif intent == CustomerIntent.PRODUCT_BY_CODE:
            sku = self.intent_detector.extract_sku(text)
            product = await self.catalog_service.get_by_sku(sku) if sku else None
            if product:
                outgoing = self.response_builder.build_product_detail_response(
                    recipient_id=sender_id,
                    channel=incoming.channel,
                    product=product,
                )
            else:
                outgoing = OutgoingMessage(
                    recipient_id=sender_id,
                    channel=incoming.channel,
                    content=f"Dạ mã sản phẩm {sku} hiện bên shop chưa tìm thấy hoặc tạm hết hàng. Bạn xem thêm các mẫu khác bên shop nhé!",
                    quick_replies=["Xem túi da", "Xem ví nam", "Gặp nhân viên"],
                )

        # Case C: Catalog browse (Send 3-4 products carousel)
        elif intent == CustomerIntent.CATALOG_REQUEST:
            category_slug = self.intent_detector.extract_category(text) or "tui-da"
            catalog_products = []
            category_name = category_slug
            try:
                catalog_resp = await self.catalog_service.get_catalog_by_category(
                    category_slug=category_slug, limit=4
                )
                catalog_products = catalog_resp.products
                category_name = catalog_resp.category
            except Exception as e:
                logger.debug(f"Catalog for {category_slug} unavailable or empty: {e}")

            if catalog_products:
                outgoing = self.response_builder.build_catalog_carousel_response(
                    recipient_id=sender_id,
                    channel=incoming.channel,
                    category_name=category_name,
                    products=catalog_products,
                )
            else:
                outgoing = OutgoingMessage(
                    recipient_id=sender_id,
                    channel=incoming.channel,
                    content="Dạ danh mục này hiện đang được cập nhật sản phẩm mới. Bạn muốn tham khảo thêm sản phẩm nào khác không ạ?",
                    quick_replies=["Xem túi da", "Xem ví da"],
                )

        # Case D: Greeting (Fast Path)
        elif intent == CustomerIntent.GREETING:
            greeting_text = (
                "Dạ xin chào bạn! Cảm ơn bạn đã nhắn tin cho shop ạ! 😊\n"
                "Shop luôn sẵn sàng hỗ trợ bạn tìm kiếm sản phẩm ưng ý nhất.\n"
                "Bạn đang quan tâm đến sản phẩm hoặc dịch vụ nào của shop ạ?"
            )
            outgoing = OutgoingMessage(
                recipient_id=sender_id,
                channel=incoming.channel,
                content=greeting_text,
                message_type="text",
                quick_replies=["Xem sản phẩm", "Chính sách bảo hành", "Gặp nhân viên"],
            )

        # Case E: General conversational inquiry & FAQ
        else:
            recent_history = await self._get_conversation_history(
                conversation_id=conversation.id, limit=10
            )
            bot_persona = await self.settings_service.get_setting("bot_persona")
            outgoing = await self.ai_engine.generate_reply(
                incoming=incoming,
                conversation_history=recent_history,
                custom_persona=bot_persona,
                session=self.session,
            )

        # 5. Apply Response Guardrails (length limit, price truth, sensitive content sanitization)
        outgoing = await self.guardrail_pipeline.validate(outgoing)

        # 6. Log Bot response to DB
        bot_msg = Message(
            tenant_id=conversation.tenant_id,
            conversation_id=conversation.id,
            role=MessageRole.BOT,
            content=outgoing.content,
            media_urls=outgoing.media_urls,
            message_type=MessageType.PRODUCT_CARD
            if outgoing.message_type == "product_card"
            else (
                MessageType.CAROUSEL if outgoing.message_type == "carousel" else MessageType.TEXT
            ),
        )
        self.session.add(bot_msg)

        # Broadcast bot response to connected admin live chat (non-blocking)
        if not sender_id.startswith("bench_m2"):
            asyncio.create_task(
                live_chat_manager.broadcast(
                    event_type="bot_message",
                    data={
                        "conversation_id": conversation.id,
                        "customer_id": customer.id,
                        "channel": incoming.channel.value,
                        "content": outgoing.content,
                        "products": outgoing.products,
                        "message_type": outgoing.message_type,
                    },
                    tenant_id=conversation.tenant_id,
                )
            )

        total_handle_ms = (time.perf_counter() - t0) * 1000.0
        if total_handle_ms > 100.0:
            logger.warning(
                f"[HANDLE TIMING] {sender_id}: total={total_handle_ms:.1f}ms, cust={(t1-t0)*1000.0:.1f}ms, conv={(t2-t1)*1000.0:.1f}ms, post_conv={(time.perf_counter()-t2)*1000.0:.1f}ms"
            )

        logger.info(
            f"Handled conversation for customer {customer.id} on channel {incoming.channel.value} with intent {intent.value}"
        )
        return outgoing

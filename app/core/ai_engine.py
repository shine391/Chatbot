"""Conversational AI Engine with Multi-LLM support (Gemini, OpenAI, Claude)."""

import re
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.intent_detector import CustomerIntent, IntentDetector
from app.core.interfaces import BaseAIEngine
from app.core.llm_providers import ClaudeProvider, GeminiProvider, OpenAIProvider
from app.core.llm_router import LLMRouter
from app.core.prompt_templates import build_grounded_system_prompt
from app.core.response_builder import ResponseBuilder
from app.knowledge.vector_store import KnowledgeStore
from app.models.knowledge import KnowledgeItem
from app.schemas.message import IncomingMessage, OutgoingMessage


class GeminiAIEngine(BaseAIEngine):
    """Conversational AI Engine powered by Multi-LLM Router and grounded Knowledge Base."""

    def __init__(self, router: LLMRouter | None = None) -> None:
        self.settings = get_settings()
        self.intent_detector = IntentDetector()
        self.response_builder = ResponseBuilder()
        self.knowledge_store = KnowledgeStore()

        # Initialize LLM Router and register concrete providers
        if router is not None:
            self.router = router
        else:
            self.router = LLMRouter()
            if self.settings.gemini_api_key:
                self.router.register_provider(
                    "gemini", GeminiProvider(self.settings.gemini_api_key)
                )
            if self.settings.openai_api_key:
                self.router.register_provider(
                    "openai", OpenAIProvider(self.settings.openai_api_key)
                )
            if self.settings.anthropic_api_key:
                self.router.register_provider(
                    "claude", ClaudeProvider(self.settings.anthropic_api_key)
                )

    async def generate_reply(
        self,
        incoming: IncomingMessage,
        conversation_history: list[dict[str, Any]] | None = None,
        custom_persona: str | None = None,
        session: AsyncSession | None = None,
    ) -> OutgoingMessage:
        """Process query, consult knowledge base, invoke LLM via Router, with fallback."""
        content = (incoming.content or "").strip()
        recipient_id = incoming.sender_id
        channel = incoming.channel

        intent = self.intent_detector.detect_intent(content)
        logger.info(f"Detected intent '{intent.value}' for query from {recipient_id}")

        # 1. Escalation check
        if intent == CustomerIntent.HUMAN_ESCALATION:
            return self.response_builder.build_escalation_response(
                recipient_id=recipient_id,
                channel=channel,
                reason="Khách hàng yêu cầu gặp nhân viên tư vấn.",
            )

        # 2. Greeting
        if intent == CustomerIntent.GREETING:
            greeting_text = (
                "Dạ xin chào bạn! Cảm ơn bạn đã nhắn tin cho shop ạ! 😊\n"
                "Shop luôn sẵn sàng hỗ trợ bạn tìm kiếm sản phẩm ưng ý nhất.\n"
                "Bạn đang quan tâm đến sản phẩm hoặc dịch vụ nào của shop ạ?"
            )
            return OutgoingMessage(
                recipient_id=recipient_id,
                channel=channel,
                content=greeting_text,
                message_type="text",
                quick_replies=["Xem sản phẩm", "Chính sách bảo hành", "Gặp nhân viên"],
            )

        # 3. Grounded context retrieval from Knowledge Base & Database
        faq_context = self.knowledge_store.search_faq(content)
        content_lower = content.lower()
        default_provider = "gemini"

        if session is not None:
            try:
                stmt = select(KnowledgeItem).where(KnowledgeItem.is_active.is_(True))
                res = await session.execute(stmt)
                db_items = res.scalars().all()
                for item in db_items:
                    qa_text = f"Q: {item.question}\nA: {item.answer}"
                    if qa_text in faq_context:
                        continue
                    q_words = [w for w in re.findall(r"\w+", item.question.lower()) if len(w) >= 2]
                    cat_words = [
                        w for w in re.findall(r"\w+", item.category.lower()) if len(w) >= 2
                    ]
                    if (
                        any(w in content_lower for w in q_words)
                        or any(w in content_lower for w in cat_words)
                        or item.question.lower() in content_lower
                    ):
                        faq_context.append(qa_text)
            except Exception as e:
                logger.warning(f"Could not load dynamic knowledge items: {e}")

            # Dynamic LLM provider sync from settings
            try:
                from app.services.settings_service import SettingsService

                ss = SettingsService(session)
                g_key = await ss.get_setting("gemini_api_key")
                o_key = await ss.get_setting("openai_api_key")
                c_key = await ss.get_setting("anthropic_api_key")
                default_provider = (await ss.get_setting("default_llm_provider")) or "gemini"

                if g_key and not g_key.startswith("***") and "****" not in g_key:
                    self.router.register_provider("gemini", GeminiProvider(g_key))
                if o_key and not o_key.startswith("***") and "****" not in o_key:
                    self.router.register_provider("openai", OpenAIProvider(o_key))
                if c_key and not c_key.startswith("***") and "****" not in c_key:
                    self.router.register_provider("claude", ClaudeProvider(c_key))
            except Exception as e:
                logger.warning(f"Could not load dynamic LLM keys: {e}")

        context_str = "\n".join(faq_context)
        system_instruction = build_grounded_system_prompt(
            faq_context=faq_context,
            custom_persona=custom_persona,
        )

        # 4. Attempt LLM generation if providers are configured
        reply_text: str = ""
        has_providers = bool(self.router.providers)

        if has_providers:
            try:
                pref = [default_provider] + [
                    p for p in self.router.providers.keys() if p != default_provider
                ]
                router_result = await self.router.generate(
                    prompt=content,
                    system_instruction=system_instruction,
                    history=conversation_history,
                    provider_preference=pref,
                )
                if router_result.success and router_result.response:
                    reply_text = router_result.response.content.strip()
                    logger.info(
                        f"Generated reply via {router_result.response.provider} "
                        f"({router_result.response.model}) in {router_result.response.latency_ms}ms"
                    )
            except Exception as e:
                logger.error(f"Unexpected error in LLM Router: {e}")

        # 5. Graceful Fallback if LLM unavailable or failed
        if not reply_text:
            logger.warning("No LLM response available, activating knowledge base fallback.")
            shop_name = "shop"
            if session is not None:
                try:
                    from app.services.settings_service import SettingsService

                    ss = SettingsService(session)
                    shop_name = (await ss.get_setting("shop_name")) or "shop"
                except Exception:
                    pass
            reply_text = (
                f"Dạ cảm ơn bạn đã quan tâm đến {shop_name} ạ!\n{context_str}\n"
                "Nếu bạn cần thêm thông tin hoặc tư vấn chi tiết hơn, bạn cứ nhắn tin cho shop nhé! ❤️"
            )

        return OutgoingMessage(
            recipient_id=recipient_id,
            channel=channel,
            content=reply_text,
            message_type="text",
            quick_replies=["Xem catalogue", "Chính sách đổi trả", "Gặp nhân viên"],
        )

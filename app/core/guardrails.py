"""Response guardrails pipeline for omnichannel customer messaging.

Protects against:
1. Message length exceeding Meta / TikTok limits (> 2000 chars).
2. Hallucinated or inconsistent product pricing against database truth.
3. Leaking sensitive credentials (PII, passwords, secret keys) or abusive language.
4. Meta 24-hour standard messaging policy violations.
"""

import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation, Message, MessageRole
from app.models.guardrail_log import GuardrailLog
from app.models.product import Product
from app.schemas.message import ChannelType, OutgoingMessage

logger = logging.getLogger(__name__)

# Sensitive patterns
PII_PATTERNS = [
    re.compile(r"(?i)(mật\s*khẩu|password|pass)\s*[:=]\s*([^\s,]+)"),
    re.compile(r"\b(sk-[a-zA-Z0-9_\-]{15,})\b"),
]

# Profanity patterns
PROFANITY_PATTERN = re.compile(
    r"\b(dkm|đkm|dm|đm|vcl|clgt|địt|đụ|buồi|lồn|cặc|chó chết)\b",
    re.IGNORECASE,
)


class GuardrailPipeline:
    """Validates and sanitizes outgoing customer service messages."""

    def __init__(self, session: AsyncSession | None = None) -> None:
        self.session = session

    async def validate(self, msg: OutgoingMessage) -> OutgoingMessage:
        """Run all guardrail checks sequentially on the outgoing message."""
        original_content = msg.content

        # 1. Profanity and PII sanitization
        if msg.content:
            msg.content = self._sanitize_text(msg.content)

        # 2. Length truncation (Meta 2000 char hard limit)
        if msg.content and len(msg.content) > 2000:
            msg.content = msg.content[:1997] + "..."
            logger.warning("Outgoing message truncated to 2000 characters.")

        # 3. Product price verification against database truth
        if msg.products and self.session is not None:
            await self._reconcile_product_prices(msg.products)

        # 4. Optional audit log if content changed
        if (
            self.session is not None
            and original_content is not None
            and msg.content != original_content
        ):
            await self._log_intervention(
                guardrail_type="content_sanitization",
                original=original_content,
                modified=msg.content or "",
            )

        return msg

    def _sanitize_text(self, text: str) -> str:
        """Redact profanity and sensitive credential patterns."""
        sanitized = text

        # Redact passwords/secrets
        for pattern in PII_PATTERNS:
            if "mật" in pattern.pattern or "pass" in pattern.pattern:
                sanitized = pattern.sub(r"\1: ***", sanitized)
            else:
                sanitized = pattern.sub("***", sanitized)

        # Redact profanities
        sanitized = PROFANITY_PATTERN.sub("***", sanitized)

        return sanitized

    async def _reconcile_product_prices(self, products: list[dict[str, Any]]) -> None:
        """Verify and overwrite product card prices using database ground truth."""
        if not self.session:
            return

        for prod in products:
            sku = prod.get("sku")
            if not sku:
                continue

            stmt = select(Product).where(Product.sku == sku)
            result = await self.session.execute(stmt)
            db_product = result.scalar_one_or_none()

            if db_product is not None:
                real_price = float(db_product.price)
                if prod.get("price") != real_price:
                    logger.info(
                        "Reconciled price for SKU %s from %s to %s",
                        sku,
                        prod.get("price"),
                        real_price,
                    )
                prod["price"] = real_price
                prod["formatted_price"] = f"{int(real_price):,}đ"

    async def check_meta_24h_window(
        self,
        channel: ChannelType | str,
        customer_id: int,
    ) -> bool:
        """Check if message is outside Meta 24-hour standard messaging window.

        Returns True if outside the 24h window (sending standard message would be rejected).
        Returns False if inside the 24h window or channel is not Meta.
        """
        ch_str = channel.value if isinstance(channel, ChannelType) else channel
        if ch_str not in (ChannelType.FACEBOOK.value, ChannelType.INSTAGRAM.value):
            return False

        if not self.session:
            return False

        stmt = (
            select(Message.sent_at)
            .join(Conversation, Message.conversation_id == Conversation.id)
            .where(
                Conversation.customer_id == customer_id,
                Message.role == MessageRole.CUSTOMER,
            )
            .order_by(Message.sent_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        last_sent = result.scalar_one_or_none()

        if last_sent is None:
            # Customer has never sent a message or no history
            return True

        now_utc = datetime.now(UTC)
        if last_sent.tzinfo is None:
            last_sent = last_sent.replace(tzinfo=UTC)

        return (now_utc - last_sent) > timedelta(hours=24)

    async def _log_intervention(
        self,
        guardrail_type: str,
        original: str,
        modified: str,
        conversation_id: int | None = None,
    ) -> None:
        """Record guardrail audit log to database."""
        if not self.session:
            return

        try:
            log_entry = GuardrailLog(
                conversation_id=conversation_id,
                guardrail_type=guardrail_type,
                original_text=original,
                modified_text=modified,
                action_taken="sanitized",
            )
            self.session.add(log_entry)
            await self.session.flush()
        except Exception as exc:
            logger.warning("Failed to record guardrail log: %s", exc)

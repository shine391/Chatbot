"""Staff escalation notification service implementing BaseNotificationService contract."""

from typing import Any

import httpx
from loguru import logger

from app.config import get_settings
from app.core.interfaces import BaseNotificationService


class EscalationService(BaseNotificationService):
    """Notifies human customer support agents via Telegram Bot or Messenger notification."""

    def __init__(self) -> None:
        self.settings = get_settings()

    async def notify_human_agent(
        self,
        customer_id: str,
        reason: str,
        recent_messages: list[dict[str, Any]],
    ) -> bool:
        """Send alert to staff via Telegram channel/group or log notification."""
        summary_lines = [
            "🚨 [HỖ TRỢ KHÁCH HÀNG CẦN CAN THIỆP]",
            f"👤 Khách hàng ID: {customer_id}",
            f"⚠️ Lý do: {reason}",
            "💬 Lịch sử gần nhất:",
        ]
        for msg in recent_messages[-3:]:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            summary_lines.append(f"- {role}: {content}")

        alert_text = "\n".join(summary_lines)
        logger.warning(f"ESCALATION ALERT:\n{alert_text}")

        # If Telegram Bot Token and Chat ID configured, send notification
        if self.settings.telegram_bot_token and self.settings.telegram_chat_id:
            telegram_url = (
                f"https://api.telegram.org/bot{self.settings.telegram_bot_token}/sendMessage"
            )
            payload = {
                "chat_id": self.settings.telegram_chat_id,
                "text": alert_text,
                "parse_mode": "Markdown",
            }
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(telegram_url, json=payload, timeout=5.0)
                    resp.raise_for_status()
                    logger.info("Successfully dispatched escalation alert to Telegram")
                    return True
            except Exception as e:
                logger.error(f"Failed to dispatch Telegram escalation: {e}")
                return False

        # If not configured, successful local logging
        return True

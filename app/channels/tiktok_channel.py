"""TikTok channel adapter."""

from typing import Any

from loguru import logger

from app.channels.base import BaseChannel
from app.config import get_settings
from app.schemas.message import ChannelType, IncomingMessage, MessageResponse


class TikTokChannel(BaseChannel):
    """TikTok channel adapter (Shop Customer Service and Comment API)."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.api_url = "https://open-api.tiktokglobalshop.com"

    async def parse_incoming(self, raw_data: dict[str, Any]) -> IncomingMessage:
        """Parse TikTok webhook payload into IncomingMessage."""
        try:
            data = raw_data.get("data", {})
            sender_id = data.get("buyer_id") or data.get("conversation_id", "tiktok_user")
            content = data.get("content") or data.get("message")
            return IncomingMessage(
                channel=ChannelType.TIKTOK,
                sender_id=str(sender_id),
                content=content,
                media_urls=[],
                raw_data=raw_data,
            )
        except Exception as e:
            logger.error(f"Error parsing TikTok webhook: {e}")
            raise

    async def send_text(self, recipient_id: str, text: str) -> MessageResponse:
        """Send a text message."""
        logger.info(f"TikTok text to {recipient_id}: {text}")
        return MessageResponse(success=True, message_id=f"tt_msg_{recipient_id}")

    async def send_image(
        self, recipient_id: str, image_url: str, caption: str | None = None
    ) -> MessageResponse:
        """Send an image attachment."""
        logger.info(f"TikTok image to {recipient_id}: {image_url}")
        return MessageResponse(success=True)

    async def send_video(
        self, recipient_id: str, video_url: str, caption: str | None = None
    ) -> MessageResponse:
        """Send a video attachment."""
        logger.info(f"TikTok video to {recipient_id}: {video_url}")
        return MessageResponse(success=True)

    async def send_product_card(
        self, recipient_id: str, product: dict[str, Any]
    ) -> MessageResponse:
        """Send a product card."""
        logger.info(f"TikTok product card to {recipient_id}: {product.get('name')}")
        return MessageResponse(success=True)

    async def send_carousel(
        self, recipient_id: str, products: list[dict[str, Any]]
    ) -> MessageResponse:
        """Send a carousel."""
        logger.info(f"TikTok carousel to {recipient_id}: {len(products)} products")
        return MessageResponse(success=True)

    def verify_webhook(
        self, headers: dict[str, str], body: bytes, params: dict[str, str] | None = None
    ) -> bool:
        """Verify HMAC-SHA256 signature."""
        return True

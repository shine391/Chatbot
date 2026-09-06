"""Website channel adapter."""

from typing import Any

from loguru import logger

from app.channels.base import BaseChannel
from app.schemas.message import ChannelType, IncomingMessage, MessageResponse


class WebsiteChannel(BaseChannel):
    """Website channel adapter for direct WebSocket/REST communication."""

    def __init__(self) -> None:
        self.response_queue: dict[str, list[dict[str, Any]]] = {}

    async def parse_incoming(self, raw_data: dict[str, Any]) -> IncomingMessage:
        """Parse direct website JSON payload."""
        try:
            sender_id = raw_data.get("session_id", "web_session")
            content = raw_data.get("content") or raw_data.get("text")
            media_urls = raw_data.get("media_urls", [])

            return IncomingMessage(
                channel=ChannelType.WEBSITE,
                sender_id=sender_id,
                content=content,
                media_urls=media_urls,
                raw_data=raw_data,
            )
        except Exception as e:
            logger.error(f"Error parsing Website message: {e}")
            raise

    def _enqueue_message(self, recipient_id: str, payload: dict[str, Any]) -> MessageResponse:
        if recipient_id not in self.response_queue:
            self.response_queue[recipient_id] = []
        self.response_queue[recipient_id].append(payload)
        return MessageResponse(success=True)

    async def send_text(self, recipient_id: str, text: str) -> MessageResponse:
        """Send a text message."""
        return self._enqueue_message(recipient_id, {"type": "text", "text": text})

    async def send_image(
        self, recipient_id: str, image_url: str, caption: str | None = None
    ) -> MessageResponse:
        """Send an image attachment."""
        return self._enqueue_message(
            recipient_id, {"type": "image", "url": image_url, "caption": caption}
        )

    async def send_video(
        self, recipient_id: str, video_url: str, caption: str | None = None
    ) -> MessageResponse:
        """Send a video attachment."""
        return self._enqueue_message(
            recipient_id, {"type": "video", "url": video_url, "caption": caption}
        )

    async def send_product_card(
        self, recipient_id: str, product: dict[str, Any]
    ) -> MessageResponse:
        """Send a product card."""
        return self._enqueue_message(recipient_id, {"type": "product", "product": product})

    async def send_carousel(
        self, recipient_id: str, products: list[dict[str, Any]]
    ) -> MessageResponse:
        """Send a carousel."""
        return self._enqueue_message(recipient_id, {"type": "carousel", "products": products})

    def verify_webhook(
        self, headers: dict[str, str], body: bytes, params: dict[str, str] | None = None
    ) -> bool:
        """No webhook verification needed for website."""
        return True

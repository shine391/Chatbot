"""Unified Outbound Message Sender for routing and dispatching messages across channels."""

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.base import BaseChannel
from app.channels.facebook_channel import FacebookChannel
from app.channels.instagram_channel import InstagramChannel
from app.channels.tiktok_channel import TikTokChannel
from app.channels.website_channel import WebsiteChannel
from app.schemas.message import ChannelType, MessageResponse, OutgoingMessage


class MessageSender:
    """Dispatches outgoing messages to their respective channel adapters."""

    def __init__(self, channels: dict[ChannelType, BaseChannel] | None = None) -> None:
        self.channels: dict[ChannelType, BaseChannel] = channels or {
            ChannelType.FACEBOOK: FacebookChannel(),
            ChannelType.INSTAGRAM: InstagramChannel(),
            ChannelType.TIKTOK: TikTokChannel(),
            ChannelType.WEBSITE: WebsiteChannel(),
        }

    @classmethod
    async def from_settings(cls, session: AsyncSession) -> "MessageSender":
        """Construct MessageSender with adapters configured dynamically from database."""
        fb_channel = await FacebookChannel.from_settings(session)
        channels: dict[ChannelType, BaseChannel] = {
            ChannelType.FACEBOOK: fb_channel,
            ChannelType.INSTAGRAM: InstagramChannel(),
            ChannelType.TIKTOK: TikTokChannel(),
            ChannelType.WEBSITE: WebsiteChannel(),
        }
        return cls(channels=channels)

    async def send_message(self, outgoing: OutgoingMessage) -> MessageResponse:
        """Route message to the correct channel adapter based on ChannelType."""
        channel_adapter = self.channels.get(outgoing.channel)
        if not channel_adapter:
            logger.error(f"Unsupported channel type: {outgoing.channel}")
            return MessageResponse(success=False, error=f"Channel {outgoing.channel} not supported")

        recipient_id = outgoing.recipient_id

        # 1. Carousel template (3-4 products)
        if outgoing.message_type == "carousel" and outgoing.products:
            logger.info(f"Sending carousel of {len(outgoing.products)} items to {recipient_id}")
            return await channel_adapter.send_carousel(recipient_id, outgoing.products)

        # 2. Single product card
        if outgoing.message_type == "product_card" and outgoing.products:
            logger.info(f"Sending product card to {recipient_id}")
            return await channel_adapter.send_product_card(recipient_id, outgoing.products[0])

        # 3. Video attachment
        if outgoing.media_urls and any(u.endswith((".mp4", ".mov")) for u in outgoing.media_urls):
            video_url = outgoing.media_urls[0]
            logger.info(f"Sending video to {recipient_id}")
            return await channel_adapter.send_video(
                recipient_id, video_url, caption=outgoing.content
            )

        # 4. Image attachment
        if outgoing.media_urls:
            image_url = outgoing.media_urls[0]
            logger.info(f"Sending image to {recipient_id}")
            return await channel_adapter.send_image(
                recipient_id, image_url, caption=outgoing.content
            )

        # 5. Default text message
        text_content = outgoing.content or ""
        logger.info(f"Sending text message to {recipient_id}: {text_content[:40]}...")
        return await channel_adapter.send_text(recipient_id, text_content)

    async def send_text(self, platform: str, recipient_id: str, text: str) -> MessageResponse:
        """Convenience helper to send a simple text message across any platform."""
        try:
            clean_platform = platform.split(".")[-1].lower()
            ch_type = ChannelType(clean_platform)
        except ValueError:
            ch_type = ChannelType.WEBSITE
        outgoing = OutgoingMessage(channel=ch_type, recipient_id=recipient_id, content=text)
        return await self.send_message(outgoing)

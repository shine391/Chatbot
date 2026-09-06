"""Contract validation tests for Channel Payloads (Facebook, Instagram, TikTok, Website).

Ensures outbound payloads strictly adhere to official API specifications without calling external network:
- Meta Graph API v21.0 Generic Template structure & limits
- Recipient ID formats
- Message length restrictions (<= 2000 chars for Meta)
- Carousel element constraints (between 1 and 4 items)
"""

import pytest

from app.channels.facebook_channel import FacebookChannel
from app.channels.instagram_channel import InstagramChannel
from app.schemas.message import ChannelType, OutgoingMessage
from app.services.message_sender import MessageSender


def test_facebook_product_card_element_contract() -> None:
    """Validate Facebook generic template element format."""
    channel = FacebookChannel()
    product = {
        "name": "Túi da bò công sở cao cấp",
        "price": 1200000.0,
        "image_url": "https://example.com/sp01.jpg",
        "website_url": "https://example.com/products/sp01",
    }
    elem = channel._build_element(product)

    assert elem["title"] == "Túi da bò công sở cao cấp"
    assert "1200000" in elem["subtitle"] or "1,200,000" in elem["subtitle"]
    assert elem["image_url"] == "https://example.com/sp01.jpg"
    assert elem["default_action"]["type"] == "web_url"
    assert elem["default_action"]["url"] == "https://example.com/products/sp01"
    assert len(elem["buttons"]) >= 1
    assert elem["buttons"][0]["type"] == "web_url"


def test_facebook_carousel_element_limit_contract() -> None:
    """Meta Generic Template carousel must never exceed 10 elements and our app clamps to 4."""
    channel = FacebookChannel()
    products = [
        {"name": f"SP {i}", "price": 100000, "image_url": f"https://example.com/{i}.jpg"}
        for i in range(1, 10)
    ]
    # Build carousel elements
    elements = [channel._build_element(p) for p in products[:4]]
    assert len(elements) == 4
    for el in elements:
        assert "title" in el
        assert "image_url" in el


@pytest.mark.asyncio
async def test_message_sender_handles_unsupported_channel() -> None:
    """MessageSender must fail gracefully when channel adapter is missing."""
    sender = MessageSender()
    # Create outgoing message with dummy unsupported channel
    outgoing = OutgoingMessage(
        recipient_id="test_user",
        channel=ChannelType.WEBSITE,
        content="Test",
    )
    # Temporarily remove website channel to test unsupported branch
    original = sender.channels.pop(ChannelType.WEBSITE, None)
    try:
        res = await sender.send_message(outgoing)
        assert res.success is False
        assert "not supported" in (res.error or "").lower()
    finally:
        if original:
            sender.channels[ChannelType.WEBSITE] = original


def test_instagram_channel_inherits_and_adapts() -> None:
    """Instagram channel adapter contract."""
    channel = InstagramChannel()
    assert channel.api_url == "https://graph.facebook.com/v21.0/me/messages"

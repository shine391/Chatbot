"""Unit tests for channel adapters (Facebook, Instagram, TikTok, Website)."""

import pytest

from app.channels.facebook_channel import FacebookChannel
from app.channels.instagram_channel import InstagramChannel
from app.channels.tiktok_channel import TikTokChannel
from app.channels.website_channel import WebsiteChannel
from app.schemas.message import ChannelType

# ===== Facebook Channel =====


class TestFacebookChannel:
    @pytest.mark.asyncio
    async def test_parse_incoming_text(self):
        channel = FacebookChannel()
        raw_data = {
            "entry": [
                {
                    "messaging": [
                        {
                            "sender": {"id": "USER_FB_1"},
                            "message": {
                                "mid": "mid.12345",
                                "text": "Cho mình xem túi da",
                            },
                        }
                    ]
                }
            ]
        }
        msg = await channel.parse_incoming(raw_data)
        assert msg.channel == ChannelType.FACEBOOK
        assert msg.sender_id == "USER_FB_1"
        assert msg.content == "Cho mình xem túi da"
        assert msg.media_urls == []

    @pytest.mark.asyncio
    async def test_parse_incoming_media(self):
        channel = FacebookChannel()
        raw_data = {
            "entry": [
                {
                    "messaging": [
                        {
                            "sender": {"id": "USER_FB_1"},
                            "message": {
                                "mid": "mid.12346",
                                "attachments": [
                                    {"payload": {"url": "https://cdn.fb.com/pic1.jpg"}}
                                ],
                            },
                        }
                    ]
                }
            ]
        }
        msg = await channel.parse_incoming(raw_data)
        assert msg.channel == ChannelType.FACEBOOK
        assert msg.content is None
        assert msg.media_urls == ["https://cdn.fb.com/pic1.jpg"]

    def test_verify_webhook_subscription(self):
        channel = FacebookChannel()
        challenge = channel.verify_webhook_subscription(
            {
                "hub.mode": "subscribe",
                "hub.verify_token": "default_verify_token",
                "hub.challenge": "CHALLENGE_TEST",
            }
        )
        assert challenge == "CHALLENGE_TEST"


# ===== Instagram Channel =====


class TestInstagramChannel:
    @pytest.mark.asyncio
    async def test_parse_incoming_text(self):
        channel = InstagramChannel()
        raw_data = {
            "entry": [
                {
                    "messaging": [
                        {
                            "sender": {"id": "IG_USER_1"},
                            "message": {
                                "mid": "ig_mid.111",
                                "text": "Túi này giá sao?",
                            },
                        }
                    ]
                }
            ]
        }
        msg = await channel.parse_incoming(raw_data)
        assert msg.channel == ChannelType.INSTAGRAM
        assert msg.sender_id == "IG_USER_1"
        assert msg.content == "Túi này giá sao?"


# ===== TikTok Channel =====


class TestTikTokChannel:
    @pytest.mark.asyncio
    async def test_parse_incoming_and_send(self):
        channel = TikTokChannel()
        raw_data = {
            "data": {
                "buyer_id": "buyer_999",
                "content": "Có freeship không?",
            }
        }
        msg = await channel.parse_incoming(raw_data)
        assert msg.channel == ChannelType.TIKTOK
        assert msg.sender_id == "buyer_999"
        assert msg.content == "Có freeship không?"

        res = await channel.send_text("buyer_999", "Dạ có freeship đơn từ 500k ạ!")
        assert res.success is True

        res_card = await channel.send_product_card("buyer_999", {"name": "Túi da", "price": 500000})
        assert res_card.success is True

        res_carousel = await channel.send_carousel(
            "buyer_999", [{"name": "Túi 1"}, {"name": "Túi 2"}]
        )
        assert res_carousel.success is True


# ===== Website Channel =====


class TestWebsiteChannel:
    @pytest.mark.asyncio
    async def test_parse_incoming_and_queue(self):
        channel = WebsiteChannel()
        raw_data = {
            "session_id": "web_sess_1",
            "content": "Tư vấn túi da cho nam",
            "media_urls": [],
        }
        msg = await channel.parse_incoming(raw_data)
        assert msg.channel == ChannelType.WEBSITE
        assert msg.sender_id == "web_sess_1"
        assert msg.content == "Tư vấn túi da cho nam"

        # Send text
        res = await channel.send_text("web_sess_1", "Dạ chào bạn!")
        assert res.success is True
        assert len(channel.response_queue["web_sess_1"]) == 1

        # Send image
        res_img = await channel.send_image("web_sess_1", "https://shop.com/tui.jpg")
        assert res_img.success is True

        # Send carousel
        res_car = await channel.send_carousel("web_sess_1", [{"sku": "SP1"}, {"sku": "SP2"}])
        assert res_car.success is True
        assert len(channel.response_queue["web_sess_1"]) == 3

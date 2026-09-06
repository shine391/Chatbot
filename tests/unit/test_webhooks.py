"""Unit tests for webhook endpoints."""

import hashlib
import hmac
import json

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.fixture
def test_app():
    return create_app()


@pytest.fixture
async def client(test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def make_fb_signature(body: bytes, secret: str = "") -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


# ===== Health Check =====


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health_returns_200(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"


# ===== Facebook Webhook =====


class TestFacebookWebhook:
    @pytest.mark.asyncio
    async def test_verify_success(self, client):
        resp = await client.get(
            "/webhook/facebook",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "default_verify_token",
                "hub.challenge": "CHALLENGE_123",
            },
        )
        assert resp.status_code == 200
        assert resp.text == "CHALLENGE_123"

    @pytest.mark.asyncio
    async def test_verify_wrong_token(self, client):
        resp = await client.get(
            "/webhook/facebook",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "wrong_token",
                "hub.challenge": "CHALLENGE_123",
            },
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_receive_text_message(self, client):
        payload = {
            "object": "page",
            "entry": [
                {
                    "id": "PAGE_ID",
                    "time": 1234567890,
                    "messaging": [
                        {
                            "sender": {"id": "USER_123"},
                            "recipient": {"id": "PAGE_ID"},
                            "timestamp": 1234567890,
                            "message": {
                                "mid": "mid.123",
                                "text": "Cho mình xem túi da",
                            },
                        }
                    ],
                }
            ],
        }
        body = json.dumps(payload).encode()
        sig = make_fb_signature(body)
        resp = await client.post(
            "/webhook/facebook",
            content=body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "EVENT_RECEIVED"

    @pytest.mark.asyncio
    async def test_receive_image_message(self, client):
        payload = {
            "object": "page",
            "entry": [
                {
                    "messaging": [
                        {
                            "sender": {"id": "USER_123"},
                            "recipient": {"id": "PAGE_ID"},
                            "message": {
                                "mid": "mid.456",
                                "attachments": [
                                    {
                                        "type": "image",
                                        "payload": {"url": "https://cdn.facebook.com/image.jpg"},
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
        }
        body = json.dumps(payload).encode()
        sig = make_fb_signature(body)
        resp = await client.post(
            "/webhook/facebook",
            content=body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_invalid_object_type(self, client):
        payload = {"object": "not_page"}
        body = json.dumps(payload).encode()
        sig = make_fb_signature(body)
        resp = await client.post(
            "/webhook/facebook",
            content=body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
        )
        assert resp.status_code == 400


# ===== Instagram Webhook =====


class TestInstagramWebhook:
    @pytest.mark.asyncio
    async def test_verify_success(self, client):
        resp = await client.get(
            "/webhook/instagram",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "default_verify_token",
                "hub.challenge": "IG_CHALLENGE_456",
            },
        )
        assert resp.status_code == 200
        assert resp.text == "IG_CHALLENGE_456"

    @pytest.mark.asyncio
    async def test_receive_dm(self, client):
        payload = {
            "object": "instagram",
            "entry": [
                {
                    "messaging": [
                        {
                            "sender": {"id": "IGSID_789"},
                            "recipient": {"id": "IG_PAGE"},
                            "message": {"mid": "ig_mid.123", "text": "Giá bao nhiêu?"},
                        }
                    ],
                }
            ],
        }
        body = json.dumps(payload).encode()
        sig = make_fb_signature(body)
        resp = await client.post(
            "/webhook/instagram",
            content=body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "EVENT_RECEIVED"


# ===== TikTok Webhook =====


class TestTikTokWebhook:
    @pytest.mark.asyncio
    async def test_receive_event(self, client):
        payload = {
            "type": "customer_service",
            "event": "new_message",
            "data": {"conversation_id": "conv_123", "content": "Sản phẩm còn không?"},
        }
        resp = await client.post("/webhook/tiktok", json=payload)
        assert resp.status_code == 200


# ===== Website Chat =====


class TestWebsiteChat:
    @pytest.mark.asyncio
    async def test_send_message(self, client):
        payload = {
            "session_id": "sess_abc123",
            "content": "Cho mình hỏi về sản phẩm SP001",
            "media_urls": [],
        }
        resp = await client.post("/api/chat/send", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert "session_id" in data

    @pytest.mark.asyncio
    async def test_send_message_with_image(self, client):
        payload = {
            "session_id": "sess_abc123",
            "content": "Sản phẩm này có màu khác không?",
            "media_urls": ["https://example.com/photo.jpg"],
        }
        resp = await client.post("/api/chat/send", json=payload)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_get_history(self, client):
        resp = await client.get("/api/chat/history/sess_abc123")
        assert resp.status_code == 200
        data = resp.json()
        assert "messages" in data

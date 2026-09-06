"""Unit tests for Two-Way Webhook outward dispatching to channels."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.main import app
from app.schemas.message import ChannelType, MessageResponse


@pytest.fixture
def client(db_session: AsyncSession) -> TestClient:
    from app.core.auth import get_current_user
    from app.models.user import AdminUser

    async def _fake_user() -> AdminUser:
        return AdminUser(id=1, username="test", hashed_password="x", role="admin", is_active=True)

    app.dependency_overrides[get_db_session] = lambda: db_session
    app.dependency_overrides[get_current_user] = _fake_user
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_facebook_webhook_dispatches_outward(client: TestClient) -> None:
    """Facebook webhook must process message and dispatch outward via MessageSender."""
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "PAGE_ID",
                "messaging": [
                    {
                        "sender": {"id": "PSID_TEST_USER_999"},
                        "recipient": {"id": "PAGE_ID"},
                        "message": {
                            "mid": "mid.unique_test_123",
                            "text": "Chào shop mình muốn tư vấn",
                        },
                    }
                ],
            }
        ],
    }

    mock_send = AsyncMock(return_value=MessageResponse(success=True, message_id="mid.sent.1"))

    with patch("app.services.message_sender.MessageSender.send_message", mock_send):
        response = client.post("/webhook/facebook", json=payload)
        assert response.status_code == 200
        assert response.json()["status"] == "EVENT_RECEIVED"

        # Check that outbound message was scheduled/dispatched to MessageSender
        assert mock_send.call_count == 1
        dispatched_msg = mock_send.call_args[0][0]
        assert dispatched_msg.recipient_id == "PSID_TEST_USER_999"
        assert dispatched_msg.channel == ChannelType.FACEBOOK
        assert dispatched_msg.content is not None

"""Unit tests for Omnichannel Live Chat, Human Takeover, and AI Inspector."""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.conversation import ConversationManager
from app.core.live_chat import live_chat_manager
from app.database.session import get_db_session
from app.main import app
from app.models.conversation import Conversation, ConversationStatus, Message, MessageRole
from app.models.customer import Customer, Platform
from app.schemas.message import ChannelType, IncomingMessage


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
async def test_live_chat_manager_broadcast() -> None:
    """LiveChatManager should broadcast JSON events to all connected WebSockets."""
    mock_ws = AsyncMock()
    await live_chat_manager.connect(mock_ws)

    await live_chat_manager.broadcast("test_event", {"hello": "world"})
    assert mock_ws.send_json.call_count == 1
    call_args = mock_ws.send_json.call_args[0][0]
    assert call_args["type"] == "test_event"
    assert call_args["data"]["hello"] == "world"

    live_chat_manager.disconnect(mock_ws)
    assert mock_ws not in live_chat_manager.active_connections


@pytest.mark.asyncio
async def test_takeover_and_handover_flow(db_session: AsyncSession, client: TestClient) -> None:
    """Taking over a conversation should silence the bot; handing over resumes bot."""
    # Seed customer and conversation
    cust = Customer(
        platform=Platform.FACEBOOK.value,
        platform_user_id="FB_TAKEOVER_1",
        name="Khách Takeover",
    )
    db_session.add(cust)
    await db_session.flush()

    conv = Conversation(
        customer_id=cust.id,
        channel="facebook",
        status=ConversationStatus.ACTIVE,
        is_bot_active=True,
    )
    db_session.add(conv)
    await db_session.commit()
    await db_session.refresh(conv)

    # 1. Takeover via Admin API
    res_takeover = client.post(f"/api/admin/conversations/{conv.id}/takeover")
    assert res_takeover.status_code == 200
    assert res_takeover.json()["is_bot_active"] is False

    # 2. When taken over, incoming message from customer yields SILENT bot (content="")
    manager = ConversationManager(db_session)
    msg_silent = await manager.handle_message(
        IncomingMessage(
            sender_id="FB_TAKEOVER_1",
            channel=ChannelType.FACEBOOK,
            content="Alo shop ơi có ai trực không?",
        )
    )
    assert msg_silent.content == ""

    # 3. Handover back to Bot via Admin API
    res_handover = client.post(f"/api/admin/conversations/{conv.id}/handover")
    assert res_handover.status_code == 200
    assert res_handover.json()["is_bot_active"] is True

    # 4. Now incoming message is handled by Bot normally
    msg_active = await manager.handle_message(
        IncomingMessage(
            sender_id="FB_TAKEOVER_1",
            channel=ChannelType.FACEBOOK,
            content="Xin chào shop",
        )
    )
    assert msg_active.content != ""


@pytest.mark.asyncio
async def test_agent_send_message_and_inspect(db_session: AsyncSession, client: TestClient) -> None:
    """Human agent can send a direct reply and inspect conversation X-Ray."""
    # Seed customer and conversation
    cust = Customer(
        platform=Platform.WEBSITE.value,
        platform_user_id="WEB_INSPECT_1",
        name="Khách Web",
    )
    db_session.add(cust)
    await db_session.flush()

    conv = Conversation(
        customer_id=cust.id,
        channel="website",
        status=ConversationStatus.ACTIVE,
    )
    db_session.add(conv)
    await db_session.flush()

    msg1 = Message(
        conversation_id=conv.id,
        role=MessageRole.CUSTOMER,
        content="Cho mình hỏi địa chỉ cửa hàng",
    )
    db_session.add(msg1)
    await db_session.commit()

    # Agent sends message
    send_res = client.post(
        f"/api/admin/conversations/{conv.id}/send",
        json={"content": "Dạ shop ở số 123 đường ABC, Q1, TP.HCM bạn nhé!"},
    )
    assert send_res.status_code == 200
    assert send_res.json()["success"] is True

    # AI Inspector X-Ray
    inspect_res = client.get(f"/api/admin/conversations/{conv.id}/inspect")
    assert inspect_res.status_code == 200
    inspect_data = inspect_res.json()
    assert inspect_data["conversation_id"] == conv.id
    assert inspect_data["channel"] == "website"
    assert "active_persona" in inspect_data
    assert len(inspect_data["recent_messages"]) >= 2
    roles = [m["role"] for m in inspect_data["recent_messages"]]
    assert "customer" in roles
    assert "agent" in roles

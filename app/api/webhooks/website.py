"""Website chat and webhook endpoints."""

from typing import Any

from fastapi import APIRouter, Depends
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.conversation import ConversationManager
from app.database.session import get_db_session
from app.schemas.message import ChannelType, IncomingMessage

router = APIRouter(tags=["website-chat"])


class ChatMessage(BaseModel):
    """Website chat message payload."""

    session_id: str | None = None
    sender_id: str | None = None
    message_id: str | None = None
    platform_message_id: str | None = None
    content: str
    media_urls: list[str] = Field(default_factory=list)


@router.post("/api/chat/send")
@router.post("/webhook/website")
@router.post("/webhook/chat")
async def send_message(
    message: ChatMessage,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Receive message from website chat widget or webhook and route to AI Conversation Manager."""
    sender_id = message.session_id or message.sender_id or "web_user"
    logger.info(f"Chat message from {sender_id}: {message.content[:50]}")

    manager = ConversationManager(session)
    platform_msg_id = message.platform_message_id or message.message_id
    incoming = IncomingMessage(
        sender_id=sender_id,
        channel=ChannelType.WEBSITE,
        content=message.content,
        media_urls=message.media_urls,
        platform_message_id=platform_msg_id,
    )

    outgoing = await manager.handle_message(incoming)

    return {
        "status": "success",
        "session_id": sender_id,
        "message_type": outgoing.message_type,
        "content": outgoing.content,
        "reply": outgoing.content,
        "media_urls": outgoing.media_urls,
        "products": outgoing.products,
        "quick_replies": outgoing.quick_replies,
    }


@router.get("/api/chat/history/{session_id}")
async def get_chat_history(session_id: str) -> dict[str, Any]:
    """Get chat history for a session."""
    logger.info(f"Fetching chat history for {session_id}")
    return {
        "session_id": session_id,
        "messages": [],
    }

"""Conversation and Message database models."""

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base

if TYPE_CHECKING:
    from app.models.customer import Customer


class ConversationStatus(str, enum.Enum):
    """Conversation status."""

    ACTIVE = "active"
    CLOSED = "closed"
    ESCALATED = "escalated"


class MessageRole(str, enum.Enum):
    """Message sender role."""

    CUSTOMER = "customer"
    BOT = "bot"
    AGENT = "agent"


class MessageType(str, enum.Enum):
    """Message content type."""

    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    PRODUCT_CARD = "product_card"
    CAROUSEL = "carousel"


class Conversation(Base):
    """Conversation model - tracks a chat session with a customer."""

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), default="default-system-tenant", index=True
    )
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False)
    channel: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(Enum(ConversationStatus), default=ConversationStatus.ACTIVE)
    is_bot_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationships
    customer: Mapped["Customer"] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", order_by="Message.sent_at"
    )

    def __repr__(self) -> str:
        return f"<Conversation(id={self.id}, channel={self.channel}, status={self.status})>"


class Message(Base):
    """Message model - individual messages within a conversation."""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), default="default-system-tenant", index=True
    )
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), nullable=False)
    role: Mapped[str] = mapped_column(Enum(MessageRole), nullable=False)
    content: Mapped[str | None] = mapped_column(Text)
    media_urls: Mapped[list[str] | None] = mapped_column(JSON, default=list)
    message_type: Mapped[str] = mapped_column(Enum(MessageType), default=MessageType.TEXT)
    platform_message_id: Mapped[str | None] = mapped_column(String(255), index=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    conversation: Mapped["Conversation"] = relationship(back_populates="messages")

    def __repr__(self) -> str:
        return f"<Message(id={self.id}, role={self.role}, type={self.message_type})>"

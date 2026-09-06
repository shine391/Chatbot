"""GuardrailLog database model."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base


class GuardrailLog(Base):
    """Tracks automated guardrail interventions and adjustments."""

    __tablename__ = "guardrail_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversations.id"), nullable=True, index=True
    )
    guardrail_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    action_taken: Mapped[str] = mapped_column(String(50), default="modified", nullable=False)
    original_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    modified_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<GuardrailLog(id={self.id}, type={self.guardrail_type}, action={self.action_taken})>"
        )

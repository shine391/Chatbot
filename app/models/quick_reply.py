"""Quick reply template model for live chat support."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base


class QuickReply(Base):
    """Pre-configured canned response templates for customer care agents."""

    __tablename__ = "quick_replies"
    __table_args__ = (
        UniqueConstraint("tenant_id", "shortcut", name="uq_quick_replies_tenant_shortcut"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), default="default-system-tenant", index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    shortcut: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(50), default="general", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<QuickReply(id={self.id}, shortcut='{self.shortcut}', title='{self.title}')>"

"""Quick reply Pydantic schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class QuickReplyBase(BaseModel):
    """Base quick reply template schema."""

    title: str = Field(..., min_length=1, max_length=255, description="Tiêu đề mẫu trả lời")
    shortcut: str = Field(
        ..., min_length=1, max_length=50, description="Phím tắt gọi nhanh, VD: /chao, /bank"
    )
    content: str = Field(..., min_length=1, description="Nội dung tin nhắn mẫu")
    category: str = Field(
        default="general",
        max_length=50,
        description="Phân loại: greeting, payment, shipping, policy, general",
    )


class QuickReplyCreate(QuickReplyBase):
    """Payload for creating a new quick reply."""

    pass


class QuickReplyUpdate(BaseModel):
    """Payload for updating an existing quick reply."""

    title: str | None = Field(None, min_length=1, max_length=255)
    shortcut: str | None = Field(None, min_length=1, max_length=50)
    content: str | None = Field(None, min_length=1)
    category: str | None = Field(None, max_length=50)


class QuickReplyDetail(QuickReplyBase):
    """Full quick reply representation."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime | None = None
    updated_at: datetime | None = None

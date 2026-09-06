"""Common reusable Pydantic schemas."""

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic schema for server-side paginated collections."""

    items: list[T]
    total: int
    page: int
    limit: int
    total_pages: int

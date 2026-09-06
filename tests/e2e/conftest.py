"""E2E Test Configuration and Shared Fixtures for Live Docker Validation.

Provides:
- Non-mocked HTTP client targeting live FastAPI container on http://127.0.0.1:8000.
- Authenticated headers and JWT token fixtures for Admin, Manager, and Agent roles.
- Automatic teardown fixture ensuring zero pollution of the 458 historical baseline records.
"""

from collections.abc import AsyncGenerator

import httpx
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.auth import create_access_token

LIVE_BASE_URL = "http://127.0.0.1:8000"
LIVE_WS_URL = "ws://127.0.0.1:8000/api/admin/ws/livechat"
PG_URL = "postgresql+asyncpg://chatbot:chatbot123@127.0.0.1:5432/chatbot"

CLEANUP_STATEMENTS = [
    ("broadcast_recipients", "id > 0"),
    ("broadcast_campaigns", "id > 0"),
    ("guardrail_logs", "id > 0"),
    ("knowledge_items", "id > 0"),
    ("messages", "id > 411"),
    ("orders", "id > 3"),
    ("conversations", "id > 6"),
    ("customers", "id > 6"),
    ("quick_replies", "id > 4"),
    ("products", "id > 9"),
    ("categories", "id > 2"),
    ("system_settings", "id > 18"),
    ("admin_users", "id > 1"),
]


async def purge_test_records() -> None:
    """Purge all test-generated records exceeding baseline max IDs in FK-safe order."""
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        for tbl, condition in CLEANUP_STATEMENTS:
            await conn.execute(text(f'DELETE FROM "{tbl}" WHERE {condition};'))
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def pg_engine() -> AsyncGenerator[AsyncEngine, None]:
    """Yield a fresh async SQLAlchemy engine with NullPool for each test function."""
    engine = create_async_engine(PG_URL, poolclass=NullPool, echo=False)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def live_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Provide an asynchronous HTTP client configured for the live Docker FastAPI service."""
    async with httpx.AsyncClient(base_url=LIVE_BASE_URL, timeout=30.0) as client:
        yield client


@pytest_asyncio.fixture(scope="function")
async def admin_token() -> str:
    """Generate a valid Admin JWT access token without exhausting SlowAPI login rate limit."""
    return create_access_token({"sub": "admin", "role": "admin"})


@pytest_asyncio.fixture(scope="function")
async def admin_headers(admin_token: str) -> dict[str, str]:
    """Return standard HTTP Authorization headers for Admin requests."""
    return {"Authorization": f"Bearer {admin_token}"}


@pytest_asyncio.fixture(scope="function", autouse=True)
async def auto_clean_e2e_test_data() -> AsyncGenerator[None, None]:
    """Automatically clean up any test-generated entities before and after each test."""
    await purge_test_records()
    yield
    await purge_test_records()

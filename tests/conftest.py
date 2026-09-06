"""Shared test fixtures for the AI Customer Service Agent."""

import asyncio
import os
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.database.session import Base, get_db_session
from app.main import create_app


@pytest.fixture(scope="session", autouse=True)
def configure_test_environment() -> None:
    """Ensure tests run with clean default environment variables."""
    os.environ["FACEBOOK_VERIFY_TOKEN"] = "default_verify_token"
    os.environ["FACEBOOK_APP_SECRET"] = ""
    os.environ["TELEGRAM_BOT_TOKEN"] = ""
    os.environ["TELEGRAM_CHAT_ID"] = ""
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Event loop
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def event_loop():
    """Create a session-scoped event loop."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="function")
async def db_engine():
    """Create a fresh in-memory database engine for each test."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create a fresh database session for each test."""
    session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()


# ---------------------------------------------------------------------------
# FastAPI test client
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="function")
async def app_client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Create a test client for the FastAPI app with in-memory DB override.

    Auth is automatically bypassed: get_current_user returns a fake admin user.
    """
    app = create_app()

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    async def _override_get_current_user() -> "AdminUser":
        """Return a fake admin user to bypass JWT auth in existing tests."""
        from app.models.user import AdminUser as _AU

        return _AU(
            id=1,
            username="test_admin",
            hashed_password="fake",
            display_name="Test Admin",
            role="admin",
            is_active=True,
        )

    from app.core.auth import get_current_user

    app.dependency_overrides[get_db_session] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_get_current_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# ---------------------------------------------------------------------------
# Sample data factories
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_customer_data() -> dict:
    """Sample customer data for testing."""
    return {
        "platform": "facebook",
        "platform_user_id": "FB_USER_12345",
        "name": "Nguyễn Văn A",
        "email": "nguyenvana@example.com",
        "phone": "0901234567",
    }


@pytest.fixture
def sample_product_data() -> dict:
    """Sample product data for testing."""
    return {
        "sku": "SP001",
        "name": "Túi da bò cao cấp",
        "description": "Túi da bò thật 100%, thiết kế sang trọng",
        "price": 1200000.0,
        "discount_price": 999000.0,
        "images": [
            "https://shop.com/images/sp001_1.jpg",
            "https://shop.com/images/sp001_2.jpg",
        ],
        "videos": ["https://shop.com/videos/sp001.mp4"],
        "website_url": "https://shop.com/products/sp001",
        "tags": ["túi da", "cao cấp", "da bò"],
        "is_active": True,
    }


@pytest.fixture
def sample_product_list() -> list[dict]:
    """Sample product list for catalog/carousel testing (3-4 items)."""
    return [
        {
            "sku": "SP001",
            "name": "Túi da bò cao cấp",
            "price": 1200000.0,
            "discount_price": 999000.0,
            "images": ["https://shop.com/images/sp001.jpg"],
            "website_url": "https://shop.com/products/sp001",
        },
        {
            "sku": "SP002",
            "name": "Túi clutch da",
            "price": 850000.0,
            "images": ["https://shop.com/images/sp002.jpg"],
            "website_url": "https://shop.com/products/sp002",
        },
        {
            "sku": "SP003",
            "name": "Túi xách da vintage",
            "price": 1500000.0,
            "images": ["https://shop.com/images/sp003.jpg"],
            "website_url": "https://shop.com/products/sp003",
        },
        {
            "sku": "SP004",
            "name": "Ví da nam",
            "price": 650000.0,
            "images": ["https://shop.com/images/sp004.jpg"],
            "website_url": "https://shop.com/products/sp004",
        },
    ]


@pytest.fixture
def sample_incoming_message() -> dict:
    """Sample incoming message from customer."""
    return {
        "sender_id": "FB_USER_12345",
        "channel": "facebook",
        "content": "Cho mình xem túi da",
        "media_urls": [],
        "platform_message_id": "mid.1234567890",
    }


@pytest.fixture
def sample_incoming_message_with_image() -> dict:
    """Sample incoming message with image attachment."""
    return {
        "sender_id": "FB_USER_12345",
        "channel": "facebook",
        "content": "Sản phẩm này có màu khác không?",
        "media_urls": ["https://cdn.facebook.com/user_upload/image123.jpg"],
        "platform_message_id": "mid.1234567891",
    }


@pytest.fixture
def sample_order_data() -> dict:
    """Sample order data for upsale testing."""
    return {
        "customer_id": 1,
        "status": "delivered",
        "total_amount": 1200000.0,
        "items": [{"product_sku": "SP001", "quantity": 1, "price": 1200000.0}],
        "notes": "Giao hàng thành công",
    }

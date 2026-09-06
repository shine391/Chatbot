"""Unit tests for Admin Settings and System Status endpoints."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.main import app


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


def test_get_and_update_admin_settings(client: TestClient) -> None:
    """Settings endpoint should return masked values and allow updates."""
    # 1. Update setting
    save_res = client.post(
        "/api/admin/settings",
        json={
            "key": "OPENAI_API_KEY",
            "value": "sk-proj-testkey1234567890abcdef",
            "category": "ai",
            "is_secret": True,
            "description": "OpenAI API Key for GPT-4o fallback",
        },
    )
    assert save_res.status_code == 200
    assert save_res.json()["success"] is True

    # 2. Get settings list
    list_res = client.get("/api/admin/settings")
    assert list_res.status_code == 200
    settings = list_res.json()["settings"]
    target = next((s for s in settings if s["key"] == "OPENAI_API_KEY"), None)
    assert target is not None
    assert "sk-" in target["value"]
    assert "****" in target["value"]  # Masked!


def test_get_system_status(client: TestClient) -> None:
    """Should report status of Database, Qdrant, and AI configurations."""
    status_res = client.get("/api/admin/system/status")
    assert status_res.status_code == 200
    data = status_res.json()
    assert "database" in data
    assert data["database"]["status"] == "connected"
    assert "qdrant" in data
    assert "ai_providers" in data

"""Unit tests for Admin Prompt & Persona Studio endpoints."""

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


def test_get_persona_presets(client: TestClient) -> None:
    """Should return available industry presets."""
    response = client.get("/api/admin/persona/presets")
    assert response.status_code == 200
    data = response.json()
    assert "presets" in data
    preset_keys = [p["key"] for p in data["presets"]]
    assert "general" in preset_keys
    assert "fashion" in preset_keys
    assert "cosmetics" in preset_keys
    assert "leather" in preset_keys
    assert "electronics" in preset_keys


def test_get_and_save_current_persona(client: TestClient) -> None:
    """Should retrieve current persona and allow hot-reload update."""
    # 1. Get current
    res_curr = client.get("/api/admin/persona/current")
    assert res_curr.status_code == 200
    current_data = res_curr.json()
    assert "persona" in current_data

    # 2. Save new persona
    new_data = {
        "preset": "cosmetics",
        "persona": "Bạn là chuyên gia tư vấn da liễu và mỹ phẩm organic.",
        "greeting": "Chào mừng bạn đến với Skincare Store!",
    }
    res_save = client.post("/api/admin/persona/save", json=new_data)
    assert res_save.status_code == 200
    assert res_save.json()["success"] is True

    # 3. Verify hot-reloaded values
    res_updated = client.get("/api/admin/persona/current")
    assert res_updated.status_code == 200
    updated_data = res_updated.json()
    assert updated_data["preset"] == "cosmetics"
    assert "chuyên gia tư vấn da liễu" in updated_data["persona"]
    assert updated_data["greeting"] == "Chào mừng bạn đến với Skincare Store!"


def test_playground_test_persona(client: TestClient) -> None:
    """Playground should generate trial reply using supplied persona without saving to chat history."""
    payload = {
        "message": "Shop ơi có kem chống nắng cho da dầu không?",
        "persona": "Bạn là chuyên viên mỹ phẩm, luôn xưng Shop và gọi khách là Bạn.",
    }
    response = client.post("/api/admin/persona/test", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "reply" in data
    assert len(data["reply"]) > 0
    assert "latency_ms" in data

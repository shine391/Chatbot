"""Unit tests for Admin Knowledge Studio endpoints."""

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


def test_knowledge_crud_flow(client: TestClient) -> None:
    """Test full CRUD lifecycle for KnowledgeItem."""
    # 1. Create Knowledge Item
    payload = {
        "category": "policy",
        "question": "Chính sách bảo hành sản phẩm như thế nào?",
        "answer": "Bảo hành 12 tháng đối với đường chỉ và khóa kéo.",
    }
    create_res = client.post("/api/admin/knowledge", json=payload)
    assert create_res.status_code == 200
    created = create_res.json()
    assert created["id"] is not None
    item_id = created["id"]
    assert created["category"] == "policy"

    # 2. List Knowledge Items
    list_res = client.get("/api/admin/knowledge")
    assert list_res.status_code == 200
    items = list_res.json()
    assert any(i["id"] == item_id for i in items)

    # 3. Update Knowledge Item
    update_payload = {
        "answer": "Bảo hành 24 tháng toàn quốc miễn phí.",
    }
    update_res = client.put(f"/api/admin/knowledge/{item_id}", json=update_payload)
    assert update_res.status_code == 200
    assert "24 tháng" in update_res.json()["answer"]

    # 4. Delete Knowledge Item
    del_res = client.delete(f"/api/admin/knowledge/{item_id}")
    assert del_res.status_code == 200
    assert del_res.json()["success"] is True

    # 5. Confirm deletion
    list_after = client.get("/api/admin/knowledge").json()
    assert not any(i["id"] == item_id for i in list_after)


def test_reindex_knowledge_to_qdrant(client: TestClient) -> None:
    """Triggering reindex should embed all active knowledge items to Qdrant."""
    # Seed 1 item
    client.post(
        "/api/admin/knowledge",
        json={
            "category": "faq",
            "question": "Có được kiểm tra hàng trước khi thanh toán không?",
            "answer": "Dạ khách hàng được đồng kiểm thoải mái trước khi nhận.",
        },
    )

    reindex_res = client.post("/api/admin/knowledge/reindex")
    assert reindex_res.status_code == 200
    data = reindex_res.json()
    assert data["success"] is True
    assert data["indexed_count"] >= 1

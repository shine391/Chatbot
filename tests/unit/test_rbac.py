"""Unit tests for Role-Based Access Control (RBAC) and Staff Management."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.database.session import get_db_session
from app.main import create_app
from app.models.user import AdminUser


@pytest.mark.asyncio
async def test_agent_role_forbidden_on_admin_and_manager_endpoints(db_session: AsyncSession):
    """Test that an Agent receives 403 Forbidden on staff and settings endpoints."""
    app = create_app()

    async def _override_get_db():
        yield db_session

    async def _override_agent_user() -> AdminUser:
        return AdminUser(
            id=10,
            username="agent_joe",
            hashed_password="fake",
            display_name="Joe Agent",
            role="agent",
            is_active=True,
        )

    app.dependency_overrides[get_db_session] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_agent_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Agent accessing staff management (Admin only)
        res_staff = await client.get("/api/admin/staff")
        assert res_staff.status_code == 403
        assert "Quyền truy cập bị từ chối" in res_staff.json()["detail"]

        # Agent accessing system settings (Admin only)
        res_settings = await client.get("/api/admin/settings")
        assert res_settings.status_code == 403

        # Agent trying to create a product (Admin & Manager only)
        res_prod = await client.post(
            "/api/admin/products",
            json={"sku": "SKU-FAIL", "name": "Fail Product", "price": 100000},
        )
        assert res_prod.status_code == 403

        # Agent accessing analytics (Admin & Manager only)
        res_analytics = await client.get("/api/admin/dashboard/analytics")
        assert res_analytics.status_code == 403

        # Agent accessing customer and order exports (Admin & Manager only)
        res_exp_cust = await client.get("/api/admin/customers/export")
        assert res_exp_cust.status_code == 403
        res_exp_ord = await client.get("/api/admin/orders/export")
        assert res_exp_ord.status_code == 403

        # Agent deleting a category (Admin & Manager only)
        res_del_cat = await client.delete("/api/admin/categories/999")
        assert res_del_cat.status_code == 403


@pytest.mark.asyncio
async def test_manager_role_permissions(db_session: AsyncSession):
    """Test that a Manager can access campaigns/products, but is forbidden from staff/settings."""
    app = create_app()

    async def _override_get_db():
        yield db_session

    async def _override_manager_user() -> AdminUser:
        return AdminUser(
            id=5,
            username="mgr_alice",
            hashed_password="fake",
            display_name="Alice Manager",
            role="manager",
            is_active=True,
        )

    app.dependency_overrides[get_db_session] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_manager_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Manager accessing staff (Forbidden)
        res_staff = await client.get("/api/admin/staff")
        assert res_staff.status_code == 403

        # Manager accessing broadcast campaigns (Allowed)
        res_bc = await client.get("/api/admin/broadcast/campaigns")
        assert res_bc.status_code == 200

        # Manager creating a product (Allowed)
        res_prod = await client.post(
            "/api/admin/products",
            json={"sku": "SKU-MGR-01", "name": "Manager Product", "price": 150000},
        )
        assert res_prod.status_code == 200
        assert res_prod.json()["sku"] == "SKU-MGR-01"

        # Manager accessing analytics (Allowed)
        res_analytics = await client.get("/api/admin/dashboard/analytics")
        assert res_analytics.status_code == 200


@pytest.mark.asyncio
async def test_admin_staff_crud_and_safeguards(db_session: AsyncSession):
    """Test full Staff CRUD for Admin and self/root deletion protections."""
    app = create_app()

    admin_user = AdminUser(
        username="admin",
        hashed_password="fake",
        display_name="System Admin",
        role="admin",
        is_active=True,
    )
    db_session.add(admin_user)
    await db_session.commit()
    await db_session.refresh(admin_user)

    async def _override_get_db():
        yield db_session

    async def _override_admin_user() -> AdminUser:
        return admin_user

    app.dependency_overrides[get_db_session] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_admin_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Create a new staff member (agent)
        create_res = await client.post(
            "/api/admin/staff",
            json={
                "username": "agent_sarah",
                "password": "password123",
                "display_name": "Sarah Agent",
                "role": "agent",
                "email": "sarah@example.com",
                "phone": "0987654321",
            },
        )
        assert create_res.status_code == 200
        staff_data = create_res.json()
        new_staff_id = staff_data["id"]
        assert staff_data["username"] == "agent_sarah"
        assert staff_data["role"] == "agent"

        # 2. Duplicate username error
        dup_res = await client.post(
            "/api/admin/staff",
            json={
                "username": "agent_sarah",
                "password": "password123",
                "display_name": "Sarah Dupe",
                "role": "agent",
            },
        )
        assert dup_res.status_code == 400

        # 3. List staff members
        list_res = await client.get("/api/admin/staff")
        assert list_res.status_code == 200
        staff_list = list_res.json()
        assert any(s["username"] == "agent_sarah" for s in staff_list)

        # 4. Update staff member (promote to manager)
        upd_res = await client.put(
            f"/api/admin/staff/{new_staff_id}",
            json={"role": "manager", "display_name": "Sarah Manager"},
        )
        assert upd_res.status_code == 200
        assert upd_res.json()["role"] == "manager"
        assert upd_res.json()["display_name"] == "Sarah Manager"

        # 5. Safeguard: Prevent deleting oneself
        self_del_res = await client.delete(f"/api/admin/staff/{admin_user.id}")
        assert self_del_res.status_code == 400
        assert "Không thể tự xóa" in self_del_res.json()["detail"]

        # 6. Delete created staff member
        del_res = await client.delete(f"/api/admin/staff/{new_staff_id}")
        assert del_res.status_code == 200
        assert del_res.json()["success"] is True

        # 7. Verify deletion
        not_found_res = await client.put(
            f"/api/admin/staff/{new_staff_id}",
            json={"display_name": "Ghost"},
        )
        assert not_found_res.status_code == 404

"""Unit tests for Phase 17: Multi-Tenancy Architecture & Core Data Isolation."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import (
    create_access_token,
    decode_token,
    get_current_tenant,
    require_superadmin,
)
from app.knowledge.qdrant_service import QdrantVectorService
from app.models.product import Product
from app.models.tenant import (
    DEFAULT_TENANT_ID,
    SubscriptionTier,
    Tenant,
    TenantStatus,
)
from app.models.user import AdminUser


@pytest.mark.asyncio
async def test_tenant_model_creation_and_defaults(db_session: AsyncSession) -> None:
    """Test Tenant model instantiation with default fields and UUID."""
    slug = f"shop-{uuid.uuid4().hex[:6]}"
    tenant = Tenant(
        name="Tiệm Trà Sữa Thơm Ngon",
        slug=slug,
    )
    db_session.add(tenant)
    await db_session.commit()
    await db_session.refresh(tenant)

    assert tenant.id is not None
    assert len(tenant.id) > 10
    assert tenant.status == TenantStatus.ACTIVE.value
    assert tenant.subscription_tier == SubscriptionTier.TRIAL.value
    assert tenant.name == "Tiệm Trà Sữa Thơm Ngon"
    assert tenant.slug == slug
    assert tenant.created_at is not None


@pytest.mark.asyncio
async def test_multi_tenant_database_isolation(db_session: AsyncSession) -> None:
    """Verify that records associated with Tenant A are completely invisible to Tenant B."""
    tenant_a_id = f"tenant-{uuid.uuid4().hex[:8]}"
    tenant_b_id = f"tenant-{uuid.uuid4().hex[:8]}"

    # 1. Create two distinct tenants
    t_a = Tenant(id=tenant_a_id, name="Tenant A", slug=f"slug-{tenant_a_id}")
    t_b = Tenant(id=tenant_b_id, name="Tenant B", slug=f"slug-{tenant_b_id}")
    db_session.add_all([t_a, t_b])
    await db_session.commit()

    # 2. Create products for each tenant
    prod_a = Product(
        tenant_id=tenant_a_id,
        sku=f"SKU-A-{uuid.uuid4().hex[:4]}",
        name="Sản Phẩm Của Shop A",
        price=150000.0,
    )
    prod_b = Product(
        tenant_id=tenant_b_id,
        sku=f"SKU-B-{uuid.uuid4().hex[:4]}",
        name="Sản Phẩm Của Shop B",
        price=300000.0,
    )
    db_session.add_all([prod_a, prod_b])
    await db_session.commit()

    # 3. Query filtered by Tenant A
    stmt_a = select(Product).where(Product.tenant_id == tenant_a_id)
    items_a = (await db_session.execute(stmt_a)).scalars().all()
    assert len(items_a) == 1
    assert items_a[0].name == "Sản Phẩm Của Shop A"

    # 4. Query filtered by Tenant B
    stmt_b = select(Product).where(Product.tenant_id == tenant_b_id)
    items_b = (await db_session.execute(stmt_b)).scalars().all()
    assert len(items_b) == 1
    assert items_b[0].name == "Sản Phẩm Của Shop B"

    # Cross-query must return nothing
    stmt_cross = select(Product).where(
        Product.tenant_id == tenant_a_id, Product.name == "Sản Phẩm Của Shop B"
    )
    cross_items = (await db_session.execute(stmt_cross)).scalars().all()
    assert len(cross_items) == 0


@pytest.mark.asyncio
async def test_jwt_token_encodes_tenant_id() -> None:
    """JWT access token must contain tenant_id claim."""
    custom_tenant_id = "tenant-custom-999"
    token = create_access_token({"sub": "merchant_user", "role": "admin", "tenant_id": custom_tenant_id})
    payload = decode_token(token)

    assert payload.get("sub") == "merchant_user"
    assert payload.get("role") == "admin"
    assert payload.get("tenant_id") == custom_tenant_id


@pytest.mark.asyncio
async def test_get_current_tenant_dependency() -> None:
    """Dependency get_current_tenant returns user's tenant_id or default."""
    user_with_tenant = AdminUser(
        username="user_t1",
        hashed_password="pw",
        role="admin",
        tenant_id="tenant-xyz-123",
    )
    extracted = await get_current_tenant(current_user=user_with_tenant)
    assert extracted == "tenant-xyz-123"

    user_without_tenant = AdminUser(
        username="user_default",
        hashed_password="pw",
        role="admin",
        tenant_id=None,  # type: ignore[arg-type]
    )
    extracted_default = await get_current_tenant(current_user=user_without_tenant)
    assert extracted_default == DEFAULT_TENANT_ID


@pytest.mark.asyncio
async def test_require_superadmin_dependency() -> None:
    """Dependency require_superadmin raises 403 for non-superadmin users."""
    from fastapi import HTTPException

    regular_admin = AdminUser(
        username="shop_admin",
        hashed_password="pw",
        role="admin",
        is_superadmin=False,
    )
    with pytest.raises(HTTPException) as exc_info:
        await require_superadmin(current_user=regular_admin)
    assert exc_info.value.status_code == 403

    platform_superadmin = AdminUser(
        username="platform_root",
        hashed_password="pw",
        role="admin",
        is_superadmin=True,
    )
    res = await require_superadmin(current_user=platform_superadmin)
    assert res.username == "platform_root"


@pytest.mark.asyncio
async def test_qdrant_vector_service_tenant_filtering() -> None:
    """Qdrant service should isolate search results by tenant_id."""
    service = QdrantVectorService(location=":memory:")
    collection_name = "test_multi_tenant_products"
    service.ensure_collection(collection_name, vector_size=4)

    # Upsert vector points for Tenant 1 and Tenant 2
    points = [
        {
            "id": 1,
            "vector": [1.0, 0.0, 0.0, 0.0],
            "payload": {"name": "Túi da Tenant 1", "tenant_id": "tenant_1"},
        },
        {
            "id": 2,
            "vector": [0.99, 0.01, 0.0, 0.0],
            "payload": {"name": "Túi da Tenant 2", "tenant_id": "tenant_2"},
        },
    ]
    service.upsert_points(collection_name, points)

    # Query targeting tenant_1
    results_t1 = service.search(
        collection_name=collection_name,
        query_vector=[1.0, 0.0, 0.0, 0.0],
        limit=5,
        tenant_id="tenant_1",
    )
    assert len(results_t1) == 1
    assert results_t1[0]["payload"]["tenant_id"] == "tenant_1"
    assert results_t1[0]["payload"]["name"] == "Túi da Tenant 1"

    # Query targeting tenant_2
    results_t2 = service.search(
        collection_name=collection_name,
        query_vector=[1.0, 0.0, 0.0, 0.0],
        limit=5,
        tenant_id="tenant_2",
    )
    assert len(results_t2) == 1
    assert results_t2[0]["payload"]["tenant_id"] == "tenant_2"
    assert results_t2[0]["payload"]["name"] == "Túi da Tenant 2"


@pytest.mark.asyncio
async def test_tenant_info_api_endpoint(app_client: AsyncClient, db_session: AsyncSession) -> None:
    """Endpoint GET /api/admin/tenant/info returns the active tenant workspace details."""
    resp = await app_client.get("/api/admin/tenant/info")
    assert resp.status_code == 200
    data = resp.json()
    assert "name" in data
    assert "slug" in data
    assert "status" in data
    assert "subscription_tier" in data


@pytest.mark.asyncio
async def test_orders_and_customers_tenant_isolation(db_session: AsyncSession) -> None:
    """Verify that orders and customers are isolated by tenant_id."""
    from app.models.customer import Customer, Platform
    from app.models.order import Order, OrderStatus

    tenant_1 = "tenant-shop-alpha"
    tenant_2 = "tenant-shop-beta"

    cust_1 = Customer(tenant_id=tenant_1, platform=Platform.FACEBOOK, platform_user_id="user_fb_alpha", name="Khách Alpha")
    cust_2 = Customer(tenant_id=tenant_2, platform=Platform.FACEBOOK, platform_user_id="user_fb_beta", name="Khách Beta")
    db_session.add_all([cust_1, cust_2])
    await db_session.flush()

    order_1 = Order(tenant_id=tenant_1, customer_id=cust_1.id, status=OrderStatus.PENDING, total_amount=500000.0)
    order_2 = Order(tenant_id=tenant_2, customer_id=cust_2.id, status=OrderStatus.PENDING, total_amount=900000.0)
    db_session.add_all([order_1, order_2])
    await db_session.commit()

    # Query orders for tenant 1
    orders_1 = (await db_session.execute(select(Order).where(Order.tenant_id == tenant_1))).scalars().all()
    assert len(orders_1) == 1
    assert orders_1[0].total_amount == 500000.0

    # Query orders for tenant 2
    orders_2 = (await db_session.execute(select(Order).where(Order.tenant_id == tenant_2))).scalars().all()
    assert len(orders_2) == 1
    assert orders_2[0].total_amount == 900000.0


@pytest.mark.asyncio
async def test_quick_replies_tenant_isolation(db_session: AsyncSession) -> None:
    """Verify that quick replies are isolated by tenant_id."""
    from app.models.quick_reply import QuickReply

    tenant_1 = "tenant-shop-alpha"
    tenant_2 = "tenant-shop-beta"

    qr_1 = QuickReply(tenant_id=tenant_1, title="Chào Alpha", shortcut="/chao", content="Chào shop Alpha")
    qr_2 = QuickReply(tenant_id=tenant_2, title="Chào Beta", shortcut="/chao_beta", content="Chào shop Beta")
    db_session.add_all([qr_1, qr_2])
    await db_session.commit()

    replies_1 = (await db_session.execute(select(QuickReply).where(QuickReply.tenant_id == tenant_1))).scalars().all()
    assert len(replies_1) == 1
    assert replies_1[0].title == "Chào Alpha"

    replies_2 = (await db_session.execute(select(QuickReply).where(QuickReply.tenant_id == tenant_2))).scalars().all()
    assert len(replies_2) == 1
    assert replies_2[0].title == "Chào Beta"


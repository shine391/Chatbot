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


@pytest.mark.asyncio
async def test_cross_tenant_product_and_category_protection(db_session: AsyncSession) -> None:
    """Bug 1: Verify cross-tenant updates/deletions on products and categories are blocked."""
    from fastapi import HTTPException

    from app.api.admin import (
        CategoryCreate,
        create_category,
        delete_category,
        delete_product,
        list_categories,
        update_product,
    )
    from app.models.product import Category, Product
    from app.schemas.product import ProductUpdate

    tenant_a = "shop-alpha-1"
    tenant_b = "shop-beta-2"

    user_a = AdminUser(id=101, username="admin_a", hashed_password="pw", role="admin", tenant_id=tenant_a)
    user_b = AdminUser(id=102, username="admin_b", hashed_password="pw", role="admin", tenant_id=tenant_b)

    # 1. Category creation & duplicate slug across tenants
    cat_data = CategoryCreate(name="Thời Trang", slug="thoi-trang", description="Mô tả")
    cat_a = await create_category(cat_data, session=db_session, _user=user_a)
    row_a = (await db_session.execute(select(Category).where(Category.id == cat_a.id))).scalar_one()
    assert row_a.tenant_id == tenant_a

    # Same slug in Tenant B must succeed (slug uniqueness is scoped to tenant)
    cat_b = await create_category(cat_data, session=db_session, _user=user_b)
    row_b = (await db_session.execute(select(Category).where(Category.id == cat_b.id))).scalar_one()
    assert row_b.tenant_id == tenant_b

    # Same slug again in Tenant A must fail
    with pytest.raises(HTTPException) as exc_info:
        await create_category(cat_data, session=db_session, _user=user_a)
    assert exc_info.value.status_code == 400

    # 2. Category list scoping
    cats_a = await list_categories(session=db_session, _user=user_a)
    assert len(cats_a) == 1
    assert cats_a[0].id == cat_a.id

    # 3. Category deletion cross-tenant blocked
    with pytest.raises(HTTPException) as exc_info:
        await delete_category(cat_a.id, session=db_session, _user=user_b)
    assert exc_info.value.status_code == 404

    # 4. Product creation and cross-tenant update/delete blocked
    prod_a = Product(
        tenant_id=tenant_a,
        sku="SKU-A-001",
        name="Áo thun Shop A",
        price=100000.0,
    )
    db_session.add(prod_a)
    await db_session.commit()
    await db_session.refresh(prod_a)

    # User B tries to update Product A -> 404
    with pytest.raises(HTTPException) as exc_info:
        await update_product(
            prod_a.id,
            ProductUpdate(name="Hacked Name"),
            session=db_session,
            _user=user_b,
        )
    assert exc_info.value.status_code == 404

    # User B tries to delete Product A -> 404
    with pytest.raises(HTTPException) as exc_info:
        await delete_product(prod_a.id, session=db_session, _user=user_b)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_cross_tenant_order_protection(db_session: AsyncSession) -> None:
    """Bug 1: Verify cross-tenant order creation, update, and VietQR access are blocked."""
    from fastapi import HTTPException

    from app.api.admin import create_order, get_order_vietqr, update_order_status
    from app.models.customer import Customer, Platform
    from app.models.order import OrderStatus
    from app.schemas.order import OrderCreate, OrderItemSchema, OrderStatusUpdate

    tenant_a = "shop-alpha-1"
    tenant_b = "shop-beta-2"

    user_a = AdminUser(id=101, username="admin_a", hashed_password="pw", role="admin", tenant_id=tenant_a)
    user_b = AdminUser(id=102, username="admin_b", hashed_password="pw", role="admin", tenant_id=tenant_b)

    cust_a = Customer(tenant_id=tenant_a, platform=Platform.FACEBOOK, platform_user_id="fb_a", name="Khách A")
    db_session.add(cust_a)
    await db_session.commit()
    await db_session.refresh(cust_a)

    # User B tries to create order for customer of Shop A -> 404
    with pytest.raises(HTTPException) as exc_info:
        await create_order(
            OrderCreate(customer_id=cust_a.id, items=[OrderItemSchema(product_sku="SKU1", product_name="Váy", price=200000.0, quantity=1)]),
            session=db_session,
            _user=user_b,
        )
    assert exc_info.value.status_code == 404

    # User A creates order successfully
    ord_a = await create_order(
        OrderCreate(customer_id=cust_a.id, items=[OrderItemSchema(product_sku="SKU1", product_name="Váy", price=200000.0, quantity=1)]),
        session=db_session,
        _user=user_a,
    )
    assert ord_a.id is not None

    # User B tries to update status of Shop A's order -> 404
    with pytest.raises(HTTPException) as exc_info:
        await update_order_status(
            ord_a.id,
            OrderStatusUpdate(status=OrderStatus.CONFIRMED),
            session=db_session,
            _user=user_b,
        )
    assert exc_info.value.status_code == 404

    # User B tries to generate VietQR for Shop A's order -> 404
    with pytest.raises(HTTPException) as exc_info:
        await get_order_vietqr(ord_a.id, session=db_session, _user=user_b)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_cross_tenant_quick_reply_and_faq_protection(db_session: AsyncSession) -> None:
    """Bug 1: Verify Quick Replies & FAQ isolation and cross-tenant mutation protection."""
    from fastapi import HTTPException

    from app.api.admin import (
        KnowledgeCreate,
        KnowledgeUpdate,
        create_knowledge_item,
        create_quick_reply,
        delete_knowledge_item,
        delete_quick_reply,
        update_knowledge_item,
        update_quick_reply,
    )
    from app.schemas.quick_reply import QuickReplyCreate, QuickReplyUpdate

    tenant_a = "shop-alpha-1"
    tenant_b = "shop-beta-2"

    user_a = AdminUser(id=101, username="admin_a", hashed_password="pw", role="admin", tenant_id=tenant_a)
    user_b = AdminUser(id=102, username="admin_b", hashed_password="pw", role="admin", tenant_id=tenant_b)

    # 1. Quick replies: same shortcut in different tenants allowed
    qr_data = QuickReplyCreate(title="Chào", shortcut="/chao", content="Xin chào quý khách")
    qr_a = await create_quick_reply(qr_data, session=db_session, _user=user_a)
    qr_b = await create_quick_reply(qr_data, session=db_session, _user=user_b)
    assert qr_a.id != qr_b.id

    # User B cannot edit or delete Shop A's quick reply
    with pytest.raises(HTTPException) as exc_info:
        await update_quick_reply(qr_a.id, QuickReplyUpdate(title="Sửa"), session=db_session, _user=user_b)
    assert exc_info.value.status_code == 404

    with pytest.raises(HTTPException) as exc_info:
        await delete_quick_reply(qr_a.id, session=db_session, _user=user_b)
    assert exc_info.value.status_code == 404

    # 2. Knowledge items (FAQ)
    faq_data = KnowledgeCreate(category="shipping", question="Ship bao lâu?", answer="1-2 ngày")
    faq_a = await create_knowledge_item(faq_data, session=db_session, _user=user_a)

    with pytest.raises(HTTPException) as exc_info:
        await update_knowledge_item(faq_a["id"], KnowledgeUpdate(answer="Hacked"), session=db_session, _user=user_b)
    assert exc_info.value.status_code == 404

    with pytest.raises(HTTPException) as exc_info:
        await delete_knowledge_item(faq_a["id"], session=db_session, _user=user_b)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_cross_tenant_conversation_takeover_protection(db_session: AsyncSession) -> None:
    """Bug 2: Verify conversation takeover, message retrieval, and messaging cross-tenant protection."""
    from fastapi import HTTPException

    from app.api.admin import (
        get_conversation_messages,
        handover_conversation,
        inspect_conversation,
        takeover_conversation,
    )
    from app.models.conversation import Conversation
    from app.models.customer import Customer, Platform

    tenant_a = "shop-alpha-1"
    tenant_b = "shop-beta-2"

    user_a = AdminUser(id=101, username="admin_a", hashed_password="pw", role="admin", tenant_id=tenant_a)
    user_b = AdminUser(id=102, username="admin_b", hashed_password="pw", role="admin", tenant_id=tenant_b)

    cust_a = Customer(tenant_id=tenant_a, platform=Platform.FACEBOOK, platform_user_id="fb_a2", name="Khách A2")
    db_session.add(cust_a)
    await db_session.flush()

    conv_a = Conversation(tenant_id=tenant_a, customer_id=cust_a.id, channel="facebook")
    db_session.add(conv_a)
    await db_session.commit()
    await db_session.refresh(conv_a)

    # Owner User A can inspect own conversation
    conv_detail = await inspect_conversation(conv_a.id, session=db_session, _user=user_a)
    assert conv_detail["channel"] == "facebook"

    # User B attempts takeover -> 404
    with pytest.raises(HTTPException) as exc_info:
        await takeover_conversation(conv_a.id, session=db_session, _user=user_b)
    assert exc_info.value.status_code == 404

    # User B attempts handover -> 404
    with pytest.raises(HTTPException) as exc_info:
        await handover_conversation(conv_a.id, session=db_session, _user=user_b)
    assert exc_info.value.status_code == 404

    # User B attempts inspect -> 404
    with pytest.raises(HTTPException) as exc_info:
        await inspect_conversation(conv_a.id, session=db_session, _user=user_b)
    assert exc_info.value.status_code == 404

    # User B attempts read messages -> 404
    with pytest.raises(HTTPException) as exc_info:
        await get_conversation_messages(conv_a.id, session=db_session, _user=user_b)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_live_chat_websocket_tenant_isolation() -> None:
    """Bug 3: Verify WebSocket live chat manager routes events strictly per tenant_id."""
    from unittest.mock import AsyncMock

    from app.core.live_chat import LiveChatManager

    manager = LiveChatManager()
    ws_tenant_a = AsyncMock()
    ws_tenant_b = AsyncMock()

    await manager.connect(ws_tenant_a, tenant_id="tenant_a")
    await manager.connect(ws_tenant_b, tenant_id="tenant_b")

    # Broadcast event for tenant_a
    await manager.broadcast("new_message", {"text": "Hello shop A"}, tenant_id="tenant_a")

    ws_tenant_a.send_json.assert_awaited_once()
    ws_tenant_b.send_json.assert_not_awaited()

    # Disconnect
    manager.disconnect(ws_tenant_a, tenant_id="tenant_a")
    manager.disconnect(ws_tenant_b, tenant_id="tenant_b")


@pytest.mark.asyncio
async def test_settings_and_vietqr_tenant_isolation(db_session: AsyncSession) -> None:
    """Bug 4: Settings & VietQR configuration are scoped to tenant_id without key collisions."""
    from app.services.settings_service import SettingsService
    from app.services.vietqr_service import VietQRService

    tenant_a = "shop-alpha-1"
    tenant_b = "shop-beta-2"

    svc_a = SettingsService(db_session, tenant_id=tenant_a)
    svc_b = SettingsService(db_session, tenant_id=tenant_b)

    # Set same setting key for both tenants
    await svc_a.set_setting("vietqr_account_number", "11111111")
    await svc_b.set_setting("vietqr_account_number", "22222222")

    val_a = await svc_a.get_setting("vietqr_account_number")
    val_b = await svc_b.get_setting("vietqr_account_number")

    assert val_a == "11111111"
    assert val_b == "22222222"

    # VietQRService from settings loads appropriate account per tenant
    vietqr_a = await VietQRService.from_settings(db_session, tenant_id=tenant_a)
    vietqr_b = await VietQRService.from_settings(db_session, tenant_id=tenant_b)

    assert vietqr_a.account_number == "11111111"
    assert vietqr_b.account_number == "22222222"


@pytest.mark.asyncio
async def test_staff_management_tenant_isolation(db_session: AsyncSession) -> None:
    """Bug 5: Staff management endpoints restrict visibility and mutation by tenant."""
    from fastapi import HTTPException

    from app.api.admin import (
        create_staff_member,
        delete_staff_member,
        list_staff_members,
        update_staff_member,
    )
    from app.schemas.staff import StaffCreate, StaffUpdate

    tenant_a = "shop-alpha-1"
    tenant_b = "shop-beta-2"

    admin_a = AdminUser(id=201, username="admin_alpha", hashed_password="pw", role="admin", tenant_id=tenant_a)
    admin_b = AdminUser(id=202, username="admin_beta", hashed_password="pw", role="admin", tenant_id=tenant_b)
    db_session.add_all([admin_a, admin_b])
    await db_session.commit()

    # Admin A creates staff in shop A
    staff_a = await create_staff_member(
        StaffCreate(username="staff_a_emp", password="password123", display_name="Nhân viên A", role="agent"),
        session=db_session,
        current_user=admin_a,
    )
    row_staff_a = (await db_session.execute(select(AdminUser).where(AdminUser.id == staff_a.id))).scalar_one()
    assert row_staff_a.tenant_id == tenant_a

    # Admin B lists staff -> cannot see staff_a
    list_b = await list_staff_members(session=db_session, _user=admin_b)
    staff_ids_b = [s.id for s in list_b]
    assert staff_a.id not in staff_ids_b

    # Admin B tries to update staff_a -> 404
    with pytest.raises(HTTPException) as exc_info:
        await update_staff_member(staff_a.id, StaffUpdate(display_name="Hacked"), session=db_session, _user=admin_b)
    assert exc_info.value.status_code == 404

    # Admin B tries to delete staff_a -> 404
    with pytest.raises(HTTPException) as exc_info:
        await delete_staff_member(staff_a.id, session=db_session, current_user=admin_b)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_dashboard_stats_and_analytics_tenant_isolation(db_session: AsyncSession) -> None:
    """Bug 6: Dashboard stats and analytics aggregate strictly within the current tenant."""
    from app.api.admin import get_dashboard_analytics, get_dashboard_stats
    from app.models.customer import Customer, Platform
    from app.models.order import Order, OrderStatus

    tenant_a = "shop-stats-alpha"
    tenant_b = "shop-stats-beta"

    user_a = AdminUser(id=301, username="admin_stats_a", hashed_password="pw", role="admin", tenant_id=tenant_a)
    user_b = AdminUser(id=302, username="admin_stats_b", hashed_password="pw", role="admin", tenant_id=tenant_b)

    # Tenant A: 1 customer, 1 delivered order (amount 150000)
    cust_a = Customer(tenant_id=tenant_a, platform=Platform.FACEBOOK, platform_user_id="cust_a_s", name="A")
    db_session.add(cust_a)
    await db_session.flush()
    ord_a = Order(tenant_id=tenant_a, customer_id=cust_a.id, status=OrderStatus.DELIVERED, total_amount=150000.0)
    db_session.add(ord_a)

    # Tenant B: 2 customers, 2 delivered orders (amount 500000 each)
    cust_b1 = Customer(tenant_id=tenant_b, platform=Platform.FACEBOOK, platform_user_id="cust_b_s1", name="B1")
    cust_b2 = Customer(tenant_id=tenant_b, platform=Platform.FACEBOOK, platform_user_id="cust_b_s2", name="B2")
    db_session.add_all([cust_b1, cust_b2])
    await db_session.flush()
    ord_b1 = Order(tenant_id=tenant_b, customer_id=cust_b1.id, status=OrderStatus.DELIVERED, total_amount=500000.0)
    ord_b2 = Order(tenant_id=tenant_b, customer_id=cust_b2.id, status=OrderStatus.DELIVERED, total_amount=500000.0)
    db_session.add_all([ord_b1, ord_b2])
    await db_session.commit()

    stats_a = await get_dashboard_stats(session=db_session, _user=user_a)
    stats_b = await get_dashboard_stats(session=db_session, _user=user_b)

    assert stats_a["total_customers"] == 1
    assert stats_a["total_orders"] == 1
    assert stats_a["total_revenue"] == 150000.0

    assert stats_b["total_customers"] == 2
    assert stats_b["total_orders"] == 2
    assert stats_b["total_revenue"] == 1000000.0

    # Analytics isolation
    analytics_a = await get_dashboard_analytics(days=7, session=db_session, _user=user_a)
    analytics_b = await get_dashboard_analytics(days=7, session=db_session, _user=user_b)

    assert analytics_a["summary"]["total_revenue"] == 150000.0
    assert analytics_b["summary"]["total_revenue"] == 1000000.0


@pytest.mark.asyncio
async def test_broadcast_campaign_recipient_isolation(db_session: AsyncSession) -> None:
    """Bug 7: Broadcast campaign recipient population excludes customers of other tenants."""
    from app.models.broadcast import BroadcastRecipient
    from app.models.customer import Customer, Platform
    from app.schemas.broadcast import BroadcastCampaignCreate
    from app.services.broadcast_service import BroadcastService

    tenant_a = "shop-bc-alpha"
    tenant_b = "shop-bc-beta"

    # 2 customers in Shop A
    c_a1 = Customer(tenant_id=tenant_a, platform=Platform.FACEBOOK, platform_user_id="fb_a1", name="Alpha 1")
    c_a2 = Customer(tenant_id=tenant_a, platform=Platform.FACEBOOK, platform_user_id="fb_a2", name="Alpha 2")

    # 3 customers in Shop B
    c_b1 = Customer(tenant_id=tenant_b, platform=Platform.FACEBOOK, platform_user_id="fb_b1", name="Beta 1")
    c_b2 = Customer(tenant_id=tenant_b, platform=Platform.FACEBOOK, platform_user_id="fb_b2", name="Beta 2")
    c_b3 = Customer(tenant_id=tenant_b, platform=Platform.FACEBOOK, platform_user_id="fb_b3", name="Beta 3")

    db_session.add_all([c_a1, c_a2, c_b1, c_b2, c_b3])
    await db_session.commit()

    service_a = BroadcastService(db_session, tenant_id=tenant_a)
    camp_a = await service_a.create_campaign(
        BroadcastCampaignCreate(name="Chiến dịch Shop A", message_content="Khuyến mãi cho shop A!")
    )

    assert camp_a.total_recipients == 2

    # Check recipient records
    recipients = (
        await db_session.execute(
            select(BroadcastRecipient).where(BroadcastRecipient.campaign_id == camp_a.id)
        )
    ).scalars().all()

    assert len(recipients) == 2
    for r in recipients:
        assert r.tenant_id == tenant_a


@pytest.mark.asyncio
async def test_reindex_knowledge_to_qdrant_tenant_isolation(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug 8: reindex_knowledge_to_qdrant uses configured Qdrant and indexes strictly per tenant."""
    from unittest.mock import MagicMock

    from app.api.admin import reindex_knowledge_to_qdrant
    from app.models.knowledge import KnowledgeItem

    tenant_a = "shop-faq-alpha"
    tenant_b = "shop-faq-beta"

    user_a = AdminUser(id=401, username="admin_faq_a", hashed_password="pw", role="admin", tenant_id=tenant_a)

    faq_a = KnowledgeItem(tenant_id=tenant_a, category="general", question="Hỏi Shop A", answer="Đáp Shop A")
    faq_b = KnowledgeItem(tenant_id=tenant_b, category="general", question="Hỏi Shop B", answer="Đáp Shop B")
    db_session.add_all([faq_a, faq_b])
    await db_session.commit()

    mock_qdrant = MagicMock()
    monkeypatch.setattr("app.api.admin.QdrantVectorService", lambda: mock_qdrant)

    result = await reindex_knowledge_to_qdrant(session=db_session, _user=user_a)

    assert result["success"] is True
    assert result["indexed_count"] == 1

    # Verify upsert_points was called with points only belonging to tenant_a
    mock_qdrant.upsert_points.assert_called_once()
    called_points = mock_qdrant.upsert_points.call_args[0][1]
    assert len(called_points) == 1
    assert called_points[0]["payload"]["tenant_id"] == tenant_a
    assert called_points[0]["payload"]["question"] == "Hỏi Shop A"


@pytest.mark.asyncio
async def test_inspect_conversation_tenant_settings_isolation(db_session: AsyncSession) -> None:
    """Bug 2 & 4: inspect_conversation resolves tenant-specific persona/preset settings."""
    from app.api.admin import inspect_conversation
    from app.models.conversation import Conversation
    from app.models.customer import Customer, Platform
    from app.services.settings_service import SettingsService

    tenant_a = "shop-insp-alpha"
    user_a = AdminUser(id=501, username="admin_insp_a", hashed_password="pw", role="admin", tenant_id=tenant_a)

    svc_a = SettingsService(db_session, tenant_id=tenant_a)
    await svc_a.set_setting("bot_persona", "Shop A Custom Persona")
    await svc_a.set_setting("bot_preset", "cosmetics")

    # Default system tenant settings
    svc_def = SettingsService(db_session, tenant_id="default-system-tenant")
    await svc_def.set_setting("bot_persona", "Default System Persona")
    await svc_def.set_setting("bot_preset", "general")

    cust_a = Customer(tenant_id=tenant_a, platform=Platform.FACEBOOK, platform_user_id="cust_insp_a", name="Khách A")
    db_session.add(cust_a)
    await db_session.flush()

    conv_a = Conversation(tenant_id=tenant_a, customer_id=cust_a.id, channel="facebook")
    db_session.add(conv_a)
    await db_session.commit()

    detail = await inspect_conversation(conv_a.id, session=db_session, _user=user_a)
    assert detail["active_persona"] == "Shop A Custom Persona"
    assert detail["active_preset"] == "cosmetics"


@pytest.mark.asyncio
async def test_live_chat_incoming_and_bot_events_tenant_isolation(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug 3: ConversationManager broadcast events are strictly tagged with the conversation tenant."""
    import asyncio

    from app.core.conversation import ConversationManager
    from app.models.customer import Customer, Platform
    from app.schemas.message import ChannelType, IncomingMessage

    tenant_a = "shop-live-alpha"
    cust_a = Customer(tenant_id=tenant_a, platform=Platform.FACEBOOK, platform_user_id="fb_live_user_1", name="Alpha User")
    db_session.add(cust_a)
    await db_session.commit()

    broadcast_calls: list[dict[str, Any]] = []

    async def mock_broadcast(event_type: str, data: dict[str, Any], tenant_id: str | None = None) -> None:
        broadcast_calls.append({"event_type": event_type, "data": data, "tenant_id": tenant_id})

    from app.core.live_chat import live_chat_manager
    monkeypatch.setattr(live_chat_manager, "broadcast", mock_broadcast)

    manager = ConversationManager(db_session, tenant_id=tenant_a)
    msg = IncomingMessage(
        sender_id="fb_live_user_1",
        channel=ChannelType.FACEBOOK,
        content="Xin chào shop",
    )
    await manager.handle_message(msg)

    # Wait for async background broadcast tasks
    await asyncio.sleep(0.05)

    assert len(broadcast_calls) >= 2
    for call in broadcast_calls:
        assert call["tenant_id"] == tenant_a


@pytest.mark.asyncio
async def test_funnel_statistics_tenant_isolation(db_session: AsyncSession) -> None:
    """Bug 6: Funnel statistics endpoint isolates conversion metrics per tenant."""
    from app.api.admin import get_funnel_stats
    from app.models.customer import Customer, FunnelStage, Platform

    tenant_a = "shop-fn-alpha"
    tenant_b = "shop-fn-beta"

    user_a = AdminUser(id=601, username="admin_fn_a", hashed_password="pw", role="admin", tenant_id=tenant_a)
    user_b = AdminUser(id=602, username="admin_fn_b", hashed_password="pw", role="admin", tenant_id=tenant_b)

    # Tenant A: 1 lead, 1 purchased
    c_a1 = Customer(tenant_id=tenant_a, platform=Platform.FACEBOOK, platform_user_id="fn_a1", funnel_stage=FunnelStage.LEAD.value)
    c_a2 = Customer(tenant_id=tenant_a, platform=Platform.FACEBOOK, platform_user_id="fn_a2", funnel_stage=FunnelStage.PURCHASED.value)

    # Tenant B: 3 loyal
    c_b1 = Customer(tenant_id=tenant_b, platform=Platform.FACEBOOK, platform_user_id="fn_b1", funnel_stage=FunnelStage.LOYAL.value)
    c_b2 = Customer(tenant_id=tenant_b, platform=Platform.FACEBOOK, platform_user_id="fn_b2", funnel_stage=FunnelStage.LOYAL.value)
    c_b3 = Customer(tenant_id=tenant_b, platform=Platform.FACEBOOK, platform_user_id="fn_b3", funnel_stage=FunnelStage.LOYAL.value)

    db_session.add_all([c_a1, c_a2, c_b1, c_b2, c_b3])
    await db_session.commit()

    stats_a = await get_funnel_stats(session=db_session, _user=user_a)
    stats_b = await get_funnel_stats(session=db_session, _user=user_b)

    assert stats_a.total_customers == 2
    assert stats_b.total_customers == 3


@pytest.mark.asyncio
async def test_broadcast_service_message_history_tenant_isolation(db_session: AsyncSession) -> None:
    """Bug 7: Messages logged during broadcast dispatch are tagged with the campaign tenant_id."""
    from app.models.broadcast import (
        BroadcastCampaign,
        BroadcastRecipient,
        CampaignStatus,
        RecipientStatus,
    )
    from app.models.conversation import Conversation, Message
    from app.models.customer import Customer, Platform
    from app.services.broadcast_service import BroadcastService

    tenant_a = "shop-bc-msg-alpha"

    cust = Customer(tenant_id=tenant_a, platform=Platform.WEBSITE, platform_user_id="web_cust_bc", name="Web Cust")
    db_session.add(cust)
    await db_session.flush()

    conv = Conversation(tenant_id=tenant_a, customer_id=cust.id, channel="website")
    db_session.add(conv)
    await db_session.flush()

    campaign = BroadcastCampaign(
        tenant_id=tenant_a,
        name="Test Campaign",
        channel=None,
        message_content="Thong bao uu dai",
        status=CampaignStatus.RUNNING,
    )
    db_session.add(campaign)
    await db_session.flush()

    rec = BroadcastRecipient(
        tenant_id=tenant_a,
        campaign_id=campaign.id,
        customer_id=cust.id,
        recipient_identifier="web_cust_bc",
        status=RecipientStatus.PENDING,
    )
    db_session.add(rec)
    await db_session.commit()

    service = BroadcastService(db_session, tenant_id=tenant_a)
    result = await service._execute_delivery(campaign.id)
    assert result["status"] == "completed"

    # Verify message was logged with tenant_a
    msgs = (
        await db_session.execute(
            select(Message).where(Message.conversation_id == conv.id)
        )
    ).scalars().all()
    assert len(msgs) == 1
    assert msgs[0].tenant_id == tenant_a




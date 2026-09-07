"""Admin management API router for products, categories, orders, settings, and persona."""

import asyncio
import csv
import hashlib
import io
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import String, cast, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
    hash_password,
    require_roles,
    verify_password,
)
from app.core.limiter import limiter
from app.core.live_chat import live_chat_manager
from app.core.llm_providers import ClaudeProvider, GeminiProvider, OpenAIProvider
from app.core.llm_router import LLMRouter
from app.core.prompt_templates import DEFAULT_COMMERCE_PERSONA, PERSONA_PRESETS
from app.database.session import get_db_session, get_session_factory
from app.knowledge.qdrant_service import QdrantVectorService
from app.models.broadcast import (
    BroadcastCampaign,
)
from app.models.conversation import Conversation, Message, MessageRole, MessageType
from app.models.customer import Customer
from app.models.guardrail_log import GuardrailLog
from app.models.knowledge import KnowledgeItem
from app.models.order import Order, OrderStatus
from app.models.product import Category, Product
from app.models.quick_reply import QuickReply
from app.models.setting import SettingCategory
from app.models.tenant import Tenant
from app.models.user import AdminUser
from app.schemas.broadcast import (
    BroadcastCampaignCreate,
    BroadcastCampaignDetail,
)
from app.schemas.common import PaginatedResponse
from app.schemas.customer import CustomerCreate, CustomerDetail, CustomerUpdate, FunnelStatsResponse
from app.schemas.message import ChannelType, OutgoingMessage
from app.schemas.order import OrderCreate, OrderDetail, OrderStatusUpdate
from app.schemas.product import ProductCreate, ProductDetail, ProductUpdate
from app.schemas.quick_reply import (
    QuickReplyCreate,
    QuickReplyDetail,
    QuickReplyUpdate,
)
from app.schemas.shipping import (
    CreateShipmentRequest,
    ShipmentDetailResponse,
    ShippingCalculationRequest,
    ShippingCalculationResponse,
)
from app.schemas.staff import StaffCreate, StaffDetail, StaffUpdate
from app.services.broadcast_service import BroadcastService
from app.services.customer_service import CustomerService
from app.services.facebook_sync_service import FacebookSyncService
from app.services.funnel_service import FunnelService
from app.services.message_sender import MessageSender
from app.services.settings_service import SettingsService
from app.services.shipping import get_shipping_carrier
from app.services.vietqr_service import VietQRService

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ===========================================================================
# Industry Presets Configuration
# ===========================================================================

INDUSTRY_PRESETS = [
    {
        "key": "general",
        "name": "Bán lẻ đa ngành tổng hợp",
        "description": "Tư vấn tổng quát, thân thiện, xưng Shop - gọi Bạn",
        "prompt": DEFAULT_COMMERCE_PERSONA,
    },
    {
        "key": "fashion",
        "name": "Thời trang & Phụ kiện",
        "description": "Tư vấn phối đồ, chọn size chuẩn, gợi ý outfit hợp vóc dáng",
        "prompt": PERSONA_PRESETS.get("fashion", DEFAULT_COMMERCE_PERSONA),
    },
    {
        "key": "cosmetics",
        "name": "Mỹ phẩm & Skincare",
        "description": "Tư vấn theo tình trạng da, thành phần an toàn, chu trình dưỡng da",
        "prompt": PERSONA_PRESETS.get("cosmetics", DEFAULT_COMMERCE_PERSONA),
    },
    {
        "key": "leather",
        "name": "Đồ da cao cấp",
        "description": "Chuyên gia đồ da thật thủ công, hướng dẫn bảo dưỡng da bền đẹp",
        "prompt": PERSONA_PRESETS.get("leather", DEFAULT_COMMERCE_PERSONA),
    },
    {
        "key": "electronics",
        "name": "Thiết bị điện tử & Công nghệ",
        "description": "Tư vấn thông số kỹ thuật, tính năng tương thích, bảo hành điện tử",
        "prompt": PERSONA_PRESETS.get("electronics", DEFAULT_COMMERCE_PERSONA),
    },
]


def _generate_text_embedding(text_content: str, dim: int = 768) -> list[float]:
    """Generate deterministic normalized vector representation for text indexing."""
    raw_hash = hashlib.sha256(text_content.encode("utf-8")).digest()
    vec: list[float] = []
    for i in range(dim):
        b = raw_hash[i % len(raw_hash)]
        vec.append(round((b / 127.5) - 1.0, 4))
    norm = sum(x * x for x in vec) ** 0.5 or 1.0
    return [round(x / norm, 4) for x in vec]


# ===========================================================================
# Authentication Endpoints (Public - No Auth Required)
# ===========================================================================


class LoginRequest(BaseModel):
    """Login request body."""

    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1, max_length=200)


class TokenResponse(BaseModel):
    """JWT token response."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict[str, Any]


class RefreshRequest(BaseModel):
    """Refresh token request body."""

    refresh_token: str


@router.post("/login")
@limiter.limit("5/minute")
async def admin_login(
    request: Request,
    body: LoginRequest,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Authenticate admin user and return JWT tokens."""
    stmt = select(AdminUser).where(AdminUser.username == body.username)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None or not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=401,
            detail="Tên đăng nhập hoặc mật khẩu không đúng.",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=403,
            detail="Tài khoản đã bị vô hiệu hóa.",
        )

    # Update last login
    user.last_login_at = datetime.now(timezone.utc)

    settings = get_settings()
    tenant_id = getattr(user, "tenant_id", None) or "default-system-tenant"
    token_data = {"sub": user.username, "role": user.role, "tenant_id": tenant_id}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": settings.jwt_access_token_expire_minutes * 60,
        "user": {
            "username": user.username,
            "display_name": user.display_name,
            "role": user.role,
            "tenant_id": tenant_id,
            "is_superadmin": getattr(user, "is_superadmin", False),
        },
    }


@router.post("/refresh-token")
async def refresh_access_token(
    body: RefreshRequest,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Refresh an expired access token using a valid refresh token."""
    payload = decode_token(body.refresh_token)

    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Token không đúng loại.")

    username = payload.get("sub", "")
    stmt = select(AdminUser).where(AdminUser.username == username)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Tài khoản không hợp lệ.")

    settings = get_settings()
    tenant_id = getattr(user, "tenant_id", None) or "default-system-tenant"
    new_access = create_access_token({"sub": user.username, "role": user.role, "tenant_id": tenant_id})
    return {
        "access_token": new_access,
        "token_type": "bearer",
        "expires_in": settings.jwt_access_token_expire_minutes * 60,
    }


@router.get("/me")
async def get_current_admin_info(
    current_user: AdminUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Get current authenticated admin user info."""
    return {
        "username": current_user.username,
        "display_name": current_user.display_name,
        "role": current_user.role,
        "tenant_id": getattr(current_user, "tenant_id", "default-system-tenant"),
        "is_superadmin": getattr(current_user, "is_superadmin", False),
        "last_login_at": current_user.last_login_at.isoformat()
        if current_user.last_login_at
        else None,
    }


@router.get("/tenant/info")
async def get_current_tenant_info(
    current_user: AdminUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Get metadata for the currently active tenant workspace."""
    tenant_id = getattr(current_user, "tenant_id", None) or "default-system-tenant"
    stmt = select(Tenant).where(Tenant.id == tenant_id)
    res = await session.execute(stmt)
    tenant = res.scalar_one_or_none()
    if tenant is None:
        return {
            "id": tenant_id,
            "name": "Default Workspace",
            "slug": "default",
            "status": "active",
            "subscription_tier": "enterprise",
            "subscription_expires_at": None,
        }
    return {
        "id": tenant.id,
        "name": tenant.name,
        "slug": tenant.slug,
        "status": tenant.status,
        "subscription_tier": tenant.subscription_tier,
        "subscription_expires_at": tenant.subscription_expires_at.isoformat()
        if tenant.subscription_expires_at
        else None,
        "created_at": tenant.created_at.isoformat(),
    }



# ===========================================================================
# Schemas
# ===========================================================================


class CategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    parent_id: int | None = None


class CategoryResponse(BaseModel):
    id: int
    name: str
    slug: str
    description: str | None = None
    parent_id: int | None = None


class SettingUpsertRequest(BaseModel):
    key: str = Field(..., min_length=1, max_length=100)
    value: str
    category: str = "general"
    is_secret: bool = False
    description: str | None = None


class PersonaSaveRequest(BaseModel):
    preset: str = "general"
    persona: str = Field(..., min_length=10)
    greeting: str | None = None


class PlaygroundTestRequest(BaseModel):
    message: str = Field(..., min_length=1)
    persona: str | None = None
    industry: str | None = None
    provider: str | None = None


class FacebookTestRequest(BaseModel):
    access_token: str | None = None


class FacebookSyncRequest(BaseModel):
    max_conversations: int = Field(default=50, ge=1, le=500)
    page_id: str | None = None
    access_token: str | None = None
    force: bool = False


class LLMTestRequest(BaseModel):
    provider: str = "gemini"
    api_key: str | None = None


class KnowledgeCreate(BaseModel):
    question: str = Field(..., min_length=3)
    answer: str = Field(..., min_length=3)
    category: str = "faq"


class KnowledgeUpdate(BaseModel):
    question: str | None = None
    answer: str | None = None
    category: str | None = None
    is_active: bool | None = None


# ===========================================================================
# Categories Endpoints
# ===========================================================================


@router.get("/categories", response_model=list[CategoryResponse])
async def list_categories(
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(get_current_user),
) -> list[CategoryResponse]:
    stmt = select(Category).order_by(Category.name)
    res = await session.execute(stmt)
    categories = res.scalars().all()
    return [
        CategoryResponse(
            id=c.id,
            name=c.name,
            slug=c.slug,
            description=c.description,
            parent_id=c.parent_id,
        )
        for c in categories
    ]


@router.post("/categories", response_model=CategoryResponse)
async def create_category(
    data: CategoryCreate,
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(require_roles("admin", "manager")),
) -> CategoryResponse:
    stmt = select(Category).where(Category.slug == data.slug)
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="Slug already exists")

    cat = Category(
        name=data.name,
        slug=data.slug,
        description=data.description,
        parent_id=data.parent_id,
    )
    session.add(cat)
    await session.commit()
    await session.refresh(cat)
    return CategoryResponse(
        id=cat.id,
        name=cat.name,
        slug=cat.slug,
        description=cat.description,
        parent_id=cat.parent_id,
    )


@router.delete("/categories/{category_id}")
async def delete_category(
    category_id: int,
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(require_roles("admin", "manager")),
) -> dict[str, Any]:
    stmt = select(Category).where(Category.id == category_id)
    cat = (await session.execute(stmt)).scalar_one_or_none()
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    await session.delete(cat)
    await session.commit()
    return {"success": True, "id": category_id}


# ===========================================================================
# Media & Products Endpoints
# ===========================================================================


@router.post("/media/upload")
async def upload_media(
    file: UploadFile = File(...),
    _user: AdminUser = Depends(require_roles("admin", "manager")),
) -> dict[str, Any]:
    """Upload product image or video file and return public static URL."""
    content_type = file.content_type or ""
    if not any(content_type.startswith(p) for p in ("image/", "video/")):
        raise HTTPException(status_code=400, detail="Chỉ hỗ trợ tải lên file hình ảnh hoặc video")

    ext = Path(file.filename or "upload.jpg").suffix.lower()
    if not ext:
        ext = ".jpg" if "image" in content_type else ".mp4"

    unique_name = f"{int(time.time())}_{uuid.uuid4().hex[:8]}{ext}"
    upload_dir = Path(__file__).resolve().parent.parent.parent / "static" / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    target_path = upload_dir / unique_name

    contents = await file.read()
    if len(contents) > 25 * 1024 * 1024:  # 25MB limit
        raise HTTPException(status_code=400, detail="Kích thước file vượt quá giới hạn 25MB")

    target_path.write_bytes(contents)
    public_url = f"/static/uploads/{unique_name}"

    return {
        "url": public_url,
        "filename": unique_name,
        "content_type": content_type,
        "size": len(contents),
    }


@router.get("/products", response_model=PaginatedResponse[ProductDetail])
async def list_products(
    category_id: int | None = None,
    search: str | None = None,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    sort_by: str = Query("id"),
    sort_order: str = Query("desc"),
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(get_current_user),
) -> PaginatedResponse[ProductDetail]:
    tenant_id = getattr(_user, "tenant_id", None) or "default-system-tenant"
    count_stmt = select(func.count(Product.id))
    stmt = select(Product)
    if not getattr(_user, "is_superadmin", False):
        count_stmt = count_stmt.where(Product.tenant_id == tenant_id)
        stmt = stmt.where(Product.tenant_id == tenant_id)
    if category_id is not None:
        count_stmt = count_stmt.where(Product.category_id == category_id)
        stmt = stmt.where(Product.category_id == category_id)
    if search:
        pattern = f"%{search}%"
        filter_expr = (
            (Product.name.ilike(pattern))
            | (Product.sku.ilike(pattern))
            | (Product.description.ilike(pattern))
        )
        count_stmt = count_stmt.where(filter_expr)
        stmt = stmt.where(filter_expr)

    total = (await session.execute(count_stmt)).scalar() or 0

    sort_map = {
        "id": Product.id,
        "name": Product.name,
        "price": Product.price,
        "discount_price": Product.discount_price,
        "sku": Product.sku,
        "created_at": Product.created_at,
    }
    col = sort_map.get(sort_by, Product.id)
    order_clause = col.desc() if sort_order.lower() == "desc" else col.asc()

    offset = (page - 1) * limit
    stmt = stmt.order_by(order_clause).offset(offset).limit(limit)
    res = await session.execute(stmt)
    products = res.scalars().all()
    items = [ProductDetail.model_validate(p) for p in products]
    total_pages = (total + limit - 1) // limit if total > 0 else 1

    return PaginatedResponse[ProductDetail](
        items=items,
        total=total,
        page=page,
        limit=limit,
        total_pages=total_pages,
    )


@router.post("/products", response_model=ProductDetail)
async def create_product(
    data: ProductCreate,
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(require_roles("admin", "manager")),
) -> ProductDetail:
    tenant_id = getattr(_user, "tenant_id", None) or "default-system-tenant"
    stmt = select(Product).where(Product.sku == data.sku.upper())
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="SKU already exists")

    prod = Product(
        tenant_id=tenant_id,
        sku=data.sku.upper(),
        name=data.name,
        description=data.description,
        category_id=data.category_id,
        price=data.price,
        discount_price=data.discount_price,
        images=data.images,
        videos=data.videos,
        website_url=data.website_url,
        tags=data.tags,
        is_active=data.is_active,
    )
    session.add(prod)
    await session.commit()
    await session.refresh(prod)

    # Sync into Qdrant vector database
    try:
        qdrant = QdrantVectorService()
        qdrant.ensure_collection("products", vector_size=768)
        vec = _generate_text_embedding(
            f"{prod.name} {prod.description or ''} {' '.join(prod.tags or [])}"
        )
        qdrant.upsert_points(
            collection_name="products",
            points=[
                {
                    "id": prod.id,
                    "vector": vec,
                    "payload": {
                        "sku": prod.sku,
                        "name": prod.name,
                        "price": prod.price,
                        "category_id": prod.category_id,
                    },
                }
            ],
        )
    except Exception as e:
        logger.warning(f"Could not index product vector into Qdrant: {e}")

    return ProductDetail.model_validate(prod)


@router.put("/products/{product_id}", response_model=ProductDetail)
async def update_product(
    product_id: int,
    data: ProductUpdate,
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(require_roles("admin", "manager")),
) -> ProductDetail:
    stmt = select(Product).where(Product.id == product_id)
    prod = (await session.execute(stmt)).scalar_one_or_none()
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")

    if data.name is not None:
        prod.name = data.name
    if data.description is not None:
        prod.description = data.description
    if data.category_id is not None:
        prod.category_id = data.category_id
    if data.price is not None:
        prod.price = data.price
    if data.discount_price is not None:
        prod.discount_price = data.discount_price
    if data.images is not None:
        prod.images = data.images
    if data.videos is not None:
        prod.videos = data.videos
    if data.website_url is not None:
        prod.website_url = data.website_url
    if data.tags is not None:
        prod.tags = data.tags
    if data.is_active is not None:
        prod.is_active = data.is_active

    await session.commit()
    await session.refresh(prod)

    # Re-sync into Qdrant
    try:
        qdrant = QdrantVectorService()
        qdrant.ensure_collection("products", vector_size=768)
        vec = _generate_text_embedding(
            f"{prod.name} {prod.description or ''} {' '.join(prod.tags or [])}"
        )
        qdrant.upsert_points(
            collection_name="products",
            points=[
                {
                    "id": prod.id,
                    "vector": vec,
                    "payload": {
                        "sku": prod.sku,
                        "name": prod.name,
                        "price": prod.price,
                        "category_id": prod.category_id,
                    },
                }
            ],
        )
    except Exception as e:
        logger.warning(f"Could not re-index product vector into Qdrant: {e}")

    return ProductDetail.model_validate(prod)


@router.delete("/products/{product_id}")
async def delete_product(
    product_id: int,
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(require_roles("admin", "manager")),
) -> dict[str, Any]:
    stmt = select(Product).where(Product.id == product_id)
    prod = (await session.execute(stmt)).scalar_one_or_none()
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")

    await session.delete(prod)
    await session.commit()
    return {"success": True, "message": f"Product {product_id} deleted"}


# ===========================================================================
# Dashboard Analytics Endpoints
# ===========================================================================


@router.get("/dashboard/stats")
async def get_dashboard_stats(
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(get_current_user),
) -> dict[str, Any]:
    total_customers = (await session.execute(select(func.count(Customer.id)))).scalar() or 0
    total_conversations = (await session.execute(select(func.count(Conversation.id)))).scalar() or 0
    total_products = (await session.execute(select(func.count(Product.id)))).scalar() or 0
    total_orders = (await session.execute(select(func.count(Order.id)))).scalar() or 0
    total_revenue = (
        await session.execute(select(func.coalesce(func.sum(Order.total_amount), 0.0)))
    ).scalar() or 0.0

    return {
        "total_customers": total_customers,
        "total_conversations": total_conversations,
        "total_products": total_products,
        "total_orders": total_orders,
        "total_revenue": float(total_revenue),
    }


@router.get("/dashboard/analytics")
async def get_dashboard_analytics(
    days: int = Query(30, ge=7, le=90),
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(require_roles("admin", "manager")),
) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # 1. Total summary stats
    total_customers = (await session.execute(select(func.count(Customer.id)))).scalar() or 0
    total_conversations = (await session.execute(select(func.count(Conversation.id)))).scalar() or 0
    total_products = (await session.execute(select(func.count(Product.id)))).scalar() or 0
    total_orders = (await session.execute(select(func.count(Order.id)))).scalar() or 0
    total_revenue = (
        await session.execute(select(func.coalesce(func.sum(Order.total_amount), 0.0)))
    ).scalar() or 0.0

    # 2. Paying customers (customers with at least 1 order)
    paying_customers = (
        await session.execute(select(func.count(func.distinct(Order.customer_id))))
    ).scalar() or 0

    conversion_rate = (
        round((paying_customers / total_customers) * 100, 2) if total_customers > 0 else 0.0
    )

    # 3. Channel distribution
    channel_counts_raw = (
        await session.execute(
            select(Customer.platform, func.count(Customer.id)).group_by(Customer.platform)
        )
    ).all()
    channel_distribution: dict[str, int] = {
        "facebook": 0,
        "instagram": 0,
        "tiktok": 0,
        "website": 0,
    }
    for plat, count in channel_counts_raw:
        plat_key = plat.value if hasattr(plat, "value") else str(plat).lower()
        channel_distribution[plat_key] = int(count)

    # 4. Funnel breakdown
    funnel_counts_raw = (
        await session.execute(
            select(Customer.funnel_stage, func.count(Customer.id)).group_by(Customer.funnel_stage)
        )
    ).all()
    funnel_breakdown: dict[str, int] = {
        "lead": 0,
        "interested": 0,
        "intent": 0,
        "purchased": 0,
        "loyal": 0,
        "lost": 0,
    }
    for stg, count in funnel_counts_raw:
        if stg:
            funnel_breakdown[str(stg).lower()] = int(count)

    # 5. Order status distribution
    status_counts_raw = (
        await session.execute(select(Order.status, func.count(Order.id)).group_by(Order.status))
    ).all()
    order_status_distribution: dict[str, int] = {}
    for st, count in status_counts_raw:
        st_key = st.value if hasattr(st, "value") else str(st).lower()
        order_status_distribution[st_key] = int(count)

    # 6. Daily timeline initialization for [today - days + 1 ... today]
    today = datetime.now(timezone.utc).date()
    dates_list = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days - 1, -1, -1)]
    revenue_by_date: dict[str, float] = {d: 0.0 for d in dates_list}
    orders_by_date: dict[str, int] = {d: 0 for d in dates_list}
    messages_by_date: dict[str, int] = {d: 0 for d in dates_list}

    # Query daily orders & revenue within timeframe
    orders_query = select(Order.ordered_at, Order.total_amount).where(Order.ordered_at >= cutoff)
    recent_orders = (await session.execute(orders_query)).all()
    for o_date, amount in recent_orders:
        if o_date:
            d_str = o_date.strftime("%Y-%m-%d")
            if d_str in revenue_by_date:
                revenue_by_date[d_str] += float(amount)
                orders_by_date[d_str] += 1

    # Query daily messages within timeframe
    messages_query = select(Message.sent_at).where(Message.sent_at >= cutoff)
    recent_messages = (await session.execute(messages_query)).scalars().all()
    for m_date in recent_messages:
        if m_date:
            d_str = m_date.strftime("%Y-%m-%d")
            if d_str in messages_by_date:
                messages_by_date[d_str] += 1

    revenue_trend = [
        {
            "date": d,
            "revenue": round(revenue_by_date[d], 2),
            "orders_count": orders_by_date[d],
            "count": orders_by_date[d],
        }
        for d in dates_list
    ]
    order_volume_trend = [
        {
            "date": d,
            "orders_count": orders_by_date[d],
            "count": orders_by_date[d],
        }
        for d in dates_list
    ]
    message_trend = [
        {
            "date": d,
            "messages_count": messages_by_date[d],
            "count": messages_by_date[d],
        }
        for d in dates_list
    ]

    return {
        "timeframe_days": days,
        "summary": {
            "total_customers": total_customers,
            "total_conversations": total_conversations,
            "total_products": total_products,
            "total_orders": total_orders,
            "total_revenue": float(total_revenue),
            "conversion_rate": conversion_rate,
        },
        "revenue_trend": revenue_trend,
        "revenue_trends": revenue_trend,
        "order_volume_trend": order_volume_trend,
        "order_trends": order_volume_trend,
        "message_trend": message_trend,
        "message_trends": message_trend,
        "channel_distribution": channel_distribution,
        "customer_conversion": {
            "total_customers": total_customers,
            "paying_customers": paying_customers,
            "rate_percentage": conversion_rate,
            "funnel_breakdown": funnel_breakdown,
        },
        "order_status_distribution": order_status_distribution,
    }


# ===========================================================================
# Prompt & Persona Studio Endpoints
# ===========================================================================


@router.get("/persona/presets")
async def get_persona_presets(_user: AdminUser = Depends(get_current_user)) -> dict[str, Any]:
    """Retrieve all available commercial industry persona presets."""
    return {"presets": INDUSTRY_PRESETS}


@router.get("/persona/current")
async def get_current_persona(
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Get the active persona, preset, and greeting message from database."""
    settings_service = SettingsService(session)
    persona = await settings_service.get_setting("bot_persona") or DEFAULT_COMMERCE_PERSONA
    preset = await settings_service.get_setting("bot_preset") or "general"
    greeting = (
        await settings_service.get_setting("bot_greeting")
        or "Dạ shop chào bạn! Shop có thể hỗ trợ bạn tìm mẫu sản phẩm nào hôm nay ạ?"
    )
    return {
        "preset": preset,
        "persona": persona,
        "greeting": greeting,
    }


@router.post("/persona/save")
async def save_persona(
    data: PersonaSaveRequest,
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Save persona and greeting settings with hot-reload."""
    settings_service = SettingsService(session)
    await settings_service.set_setting(
        key="bot_persona",
        value=data.persona,
        description="Active system prompt persona",
        category=SettingCategory.AI,
    )
    await settings_service.set_setting(
        key="bot_preset",
        value=data.preset,
        description="Active industry preset",
        category=SettingCategory.AI,
    )
    if data.greeting is not None:
        await settings_service.set_setting(
            key="bot_greeting",
            value=data.greeting,
            description="Custom greeting message",
            category=SettingCategory.AI,
        )
    return {"success": True, "preset": data.preset}


@router.post("/persona/test")
async def test_persona_playground(
    data: PlaygroundTestRequest,
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Playground endpoint to preview AI response without altering live chats."""
    start_time = time.perf_counter()
    system_prompt = data.persona or DEFAULT_COMMERCE_PERSONA

    settings_service = SettingsService(session)
    static = get_settings()

    gemini_key = await settings_service.get_setting("gemini_api_key") or static.gemini_api_key
    openai_key = await settings_service.get_setting("openai_api_key") or static.openai_api_key
    claude_key = await settings_service.get_setting("anthropic_api_key") or static.anthropic_api_key
    default_provider = (
        await settings_service.get_setting("default_llm_provider")
        or static.default_llm_provider
        or "gemini"
    )

    router_instance = LLMRouter()
    if gemini_key and not gemini_key.startswith("***") and "****" not in gemini_key:
        router_instance.register_provider("gemini", GeminiProvider(api_key=gemini_key))
    if openai_key and not openai_key.startswith("***") and "****" not in openai_key:
        router_instance.register_provider("openai", OpenAIProvider(api_key=openai_key))
    if claude_key and not claude_key.startswith("***") and "****" not in claude_key:
        router_instance.register_provider("claude", ClaudeProvider(api_key=claude_key))

    try:
        if not router_instance.providers:
            raise RuntimeError(
                "Chưa cấu hình API Key nào cho LLM. Vui lòng vào tab 'Cấu hình & API' để nhập API Key."
            )

        preferred_provider = (data.provider or default_provider).lower()
        router_result = await router_instance.generate(
            prompt=data.message,
            system_instruction=system_prompt,
            provider_preference=[preferred_provider],
        )
        if router_result.success and router_result.response is not None:
            return {
                "reply": router_result.response.content,
                "provider": router_result.response.provider,
                "latency_ms": router_result.response.latency_ms,
            }
        raise RuntimeError(router_result.error or "Router generation failed")
    except Exception as exc:
        latency = round((time.perf_counter() - start_time) * 1000, 2)
        # Fallback simulation response when live API key is unavailable
        sample_response = (
            f"Dạ shop chào bạn! Shop đã nhận được yêu cầu: '{data.message}'. "
            f"Hiện shop đang áp dụng phong cách tư vấn mới. Bạn tham khảo thêm nhé! (Mô phỏng: {exc})"
        )
        return {
            "reply": sample_response,
            "provider": "simulation",
            "latency_ms": max(latency, 12.5),
        }


# ===========================================================================
# Knowledge Studio Endpoints
# ===========================================================================


@router.get("/knowledge")
async def list_knowledge_items(
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(get_current_user),
) -> list[dict[str, Any]]:
    stmt = select(KnowledgeItem).order_by(KnowledgeItem.id.desc())
    res = await session.execute(stmt)
    items = res.scalars().all()
    return [
        {
            "id": it.id,
            "category": it.category,
            "question": it.question,
            "answer": it.answer,
            "is_active": it.is_active,
            "created_at": it.created_at.isoformat() if it.created_at else None,
        }
        for it in items
    ]


@router.post("/knowledge")
async def create_knowledge_item(
    data: KnowledgeCreate,
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(get_current_user),
) -> dict[str, Any]:
    item = KnowledgeItem(
        category=data.category,
        question=data.question,
        answer=data.answer,
        is_active=True,
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return {
        "id": item.id,
        "category": item.category,
        "question": item.question,
        "answer": item.answer,
        "is_active": item.is_active,
    }


@router.put("/knowledge/{item_id}")
async def update_knowledge_item(
    item_id: int,
    data: KnowledgeUpdate,
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(get_current_user),
) -> dict[str, Any]:
    stmt = select(KnowledgeItem).where(KnowledgeItem.id == item_id)
    item = (await session.execute(stmt)).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Knowledge item not found")

    if data.question is not None:
        item.question = data.question
    if data.answer is not None:
        item.answer = data.answer
    if data.category is not None:
        item.category = data.category
    if data.is_active is not None:
        item.is_active = data.is_active

    await session.commit()
    await session.refresh(item)
    return {
        "id": item.id,
        "category": item.category,
        "question": item.question,
        "answer": item.answer,
        "is_active": item.is_active,
    }


@router.delete("/knowledge/{item_id}")
async def delete_knowledge_item(
    item_id: int,
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(get_current_user),
) -> dict[str, Any]:
    stmt = select(KnowledgeItem).where(KnowledgeItem.id == item_id)
    item = (await session.execute(stmt)).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Knowledge item not found")

    await session.delete(item)
    await session.commit()
    return {"success": True, "id": item_id}


@router.post("/knowledge/reindex")
async def reindex_knowledge_to_qdrant(
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Re-embed and index all active knowledge items into Qdrant."""
    stmt = select(KnowledgeItem).where(KnowledgeItem.is_active.is_(True))
    res = await session.execute(stmt)
    items = res.scalars().all()

    qdrant = QdrantVectorService(location=":memory:")
    qdrant.ensure_collection("ecommerce_faq", vector_size=768)

    points: list[dict[str, Any]] = []
    for it in items:
        full_text = f"{it.question} {it.answer}"
        vec = _generate_text_embedding(full_text, dim=768)
        points.append(
            {
                "id": it.id,
                "vector": vec,
                "payload": {
                    "category": it.category,
                    "question": it.question,
                    "answer": it.answer,
                },
            }
        )

    if points:
        qdrant.upsert_points("ecommerce_faq", points)

    return {"success": True, "indexed_count": len(items)}


# ===========================================================================
# Settings & System Status Endpoints
# ===========================================================================


@router.get("/settings")
async def list_admin_settings(
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(require_roles("admin")),
) -> dict[str, Any]:
    settings_service = SettingsService(session)
    settings_list = await settings_service.get_all_settings(mask_secrets=True)
    return {"settings": settings_list}


@router.post("/settings")
async def update_admin_setting(
    data: SettingUpsertRequest,
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(require_roles("admin")),
) -> dict[str, Any]:
    if data.is_secret and ("****" in data.value or data.value == "****"):
        return {"success": True, "key": data.key, "note": "Unchanged masked secret"}

    settings_service = SettingsService(session)
    cat_lower = str(data.category).strip().lower()
    category = (
        SettingCategory(cat_lower)
        if cat_lower in [c.value for c in SettingCategory]
        else SettingCategory.GENERAL
    )
    await settings_service.set_setting(
        key=data.key,
        value=data.value,
        description=data.description,
        is_secret=data.is_secret,
        category=category,
    )
    await session.commit()
    return {"success": True, "key": data.key}


@router.post("/channels/facebook/test")
async def test_facebook_connection(
    data: FacebookTestRequest | None = None,
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Verify Facebook Page Access Token via Meta Graph API."""
    token = data.access_token if data else None
    if not token or token.startswith("***") or "****" in token:
        settings_service = SettingsService(session)
        token = await settings_service.get_setting("facebook_page_access_token")
        if not token or token.startswith("***") or "****" in token:
            token = get_settings().facebook_page_access_token

    if not token or token.strip() == "":
        return {
            "valid": False,
            "error": "Chưa cấu hình Facebook Page Access Token. Vui lòng nhập token để kiểm tra.",
        }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://graph.facebook.com/v21.0/me",
                params={"fields": "id,name,picture", "access_token": token.strip()},
            )
            data_json = resp.json()
            if resp.status_code == 200 and "id" in data_json:
                pic_url = data_json.get("picture", {}).get("data", {}).get("url")
                page_id = data_json.get("id")
                page_name = data_json.get("name")
                # Auto update facebook_page_id and facebook_page_name in settings if connected
                settings_service = SettingsService(session)
                if page_id:
                    await settings_service.set_setting(
                        key="facebook_page_id",
                        value=str(page_id),
                        description="Facebook Page ID",
                        category=SettingCategory.CHANNELS,
                    )
                if page_name:
                    await settings_service.set_setting(
                        key="facebook_page_name",
                        value=str(page_name),
                        description="Tên Facebook Fanpage",
                        category=SettingCategory.CHANNELS,
                    )
                await session.commit()
                return {
                    "valid": True,
                    "id": page_id,
                    "name": page_name,
                    "picture_url": pic_url,
                    "message": f"Kết nối thành công tới Fanpage: {page_name} (ID: {page_id})",
                }
            error_msg = data_json.get("error", {}).get("message", "Lỗi xác thực token Facebook")
            return {"valid": False, "error": error_msg}
    except Exception as exc:
        return {"valid": False, "error": f"Lỗi kết nối Graph API: {exc}"}


@router.post("/channels/facebook/sync")
async def sync_facebook_conversations(
    background_tasks: BackgroundTasks,
    data: FacebookSyncRequest | None = None,
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Trigger background sync of historical conversations and messages from Facebook Fanpage."""
    if FacebookSyncService.is_running() and not (data and data.force):
        return {
            "status": "running",
            "message": "Quá trình đồng bộ đang diễn ra, vui lòng chờ.",
            "progress": FacebookSyncService.get_status(),
        }

    settings_service = SettingsService(session)
    token = (
        data.access_token
        if (
            data
            and data.access_token
            and not data.access_token.startswith("***")
            and "****" not in data.access_token
        )
        else None
    )
    if not token or token.strip() == "":
        token = await settings_service.get_setting("facebook_page_access_token")
        if not token or token.startswith("***") or "****" in token:
            token = get_settings().facebook_page_access_token

    if not token or token.strip() == "":
        raise HTTPException(
            status_code=400,
            detail="Chưa cấu hình Facebook Page Access Token. Vui lòng nhập và lưu cấu hình trước khi đồng bộ.",
        )

    page_id = data.page_id if (data and data.page_id and data.page_id.strip()) else None
    if not page_id or page_id.strip() == "":
        page_id = await settings_service.get_setting("facebook_page_id")
        if not page_id:
            page_id = getattr(get_settings(), "facebook_page_id", "")

    if not page_id or page_id.strip() == "":
        # Try auto-discovery via Meta Graph API /me
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://graph.facebook.com/v21.0/me",
                    params={"fields": "id,name", "access_token": token.strip()},
                )
                if resp.status_code == 200:
                    me_data = resp.json()
                    resolved_id = me_data.get("id")
                    if resolved_id:
                        page_id = str(resolved_id)
                        await settings_service.set_setting(
                            key="facebook_page_id",
                            value=page_id,
                            description="Facebook Page ID",
                            category=SettingCategory.CHANNELS,
                        )
                        resolved_name = me_data.get("name")
                        if resolved_name:
                            await settings_service.set_setting(
                                key="facebook_page_name",
                                value=str(resolved_name),
                                description="Tên Facebook Fanpage",
                                category=SettingCategory.CHANNELS,
                            )
                        await session.commit()
        except Exception as e:
            logger.warning("Could not auto-resolve Facebook Page ID: %s", e)

    if not page_id or page_id.strip() == "":
        raise HTTPException(
            status_code=400,
            detail="Chưa xác định được Facebook Page ID. Vui lòng bấm 'Kiểm Tra Kết Nối Meta' trước khi đồng bộ.",
        )

    max_convs = data.max_conversations if (data and data.max_conversations > 0) else 50

    FacebookSyncService.set_running(max_convs)

    bind_engine = session.bind

    async def _run_bg_sync(pid: str, tok: str, max_c: int) -> None:
        from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

        if isinstance(bind_engine, AsyncEngine):
            sf = async_sessionmaker(bind_engine, class_=AsyncSession, expire_on_commit=False)
        else:
            sf = get_session_factory()
        try:
            async with sf() as bg_session:
                await FacebookSyncService.sync_page_conversations(
                    session=bg_session,
                    page_id=pid,
                    access_token=tok,
                    max_conversations=max_c,
                )
        except Exception as e:
            logger.exception("Background Facebook sync error: %s", e)
            FacebookSyncService._state["status"] = "error"
            FacebookSyncService._state["error_message"] = str(e)

    background_tasks.add_task(_run_bg_sync, page_id, token, max_convs)

    return {
        "status": "started",
        "message": f"Đã bắt đầu tác vụ đồng bộ tối đa {max_convs} hội thoại từ Facebook Fanpage.",
        "max_conversations": max_convs,
        "page_id": page_id,
    }


@router.get("/channels/facebook/sync/status")
async def get_facebook_sync_status(_user: AdminUser = Depends(get_current_user)) -> dict[str, Any]:
    """Get current status and statistics of Facebook historical sync."""
    return FacebookSyncService.get_status()


@router.post("/channels/llm/test")
async def test_llm_connection(
    data: LLMTestRequest,
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Test LLM provider connectivity and measure API latency."""
    provider = data.provider.lower()
    api_key = data.api_key

    # If key is omitted or masked, pull real key from DB or static settings
    if not api_key or "****" in api_key:
        settings_service = SettingsService(session)
        key_name = f"{provider}_api_key" if provider != "claude" else "anthropic_api_key"
        api_key = await settings_service.get_setting(key_name)
        if not api_key or "****" in api_key:
            static = get_settings()
            api_key = getattr(static, key_name, None)

    if not api_key or api_key.strip() == "":
        return {
            "valid": False,
            "provider": provider,
            "error": f"Chưa cấu hình API Key cho provider '{provider}'.",
            "latency_ms": None,
        }

    start = time.perf_counter()
    try:
        if provider == "gemini":
            gemini_prov = GeminiProvider(api_key=api_key.strip())
            resp = await gemini_prov.generate_response("Trả lời ngắn gọn: OK", temperature=0.1)
            latency = round((time.perf_counter() - start) * 1000, 2)
            return {
                "valid": True,
                "provider": "gemini",
                "model": gemini_prov.model_name,
                "latency_ms": latency,
                "sample_reply": resp.content.strip()[:100],
                "message": f"Kết nối Gemini thành công ({latency}ms)",
            }
        elif provider == "openai":
            openai_prov = OpenAIProvider(api_key=api_key.strip())
            resp = await openai_prov.generate_response("Trả lời ngắn gọn: OK", temperature=0.1)
            latency = round((time.perf_counter() - start) * 1000, 2)
            return {
                "valid": True,
                "provider": "openai",
                "model": openai_prov.model_name,
                "latency_ms": latency,
                "sample_reply": resp.content.strip()[:100],
                "message": f"Kết nối OpenAI thành công ({latency}ms)",
            }
        elif provider in ["claude", "anthropic"]:
            claude_prov = ClaudeProvider(api_key=api_key.strip())
            resp = await claude_prov.generate_response("Trả lời ngắn gọn: OK", temperature=0.1)
            latency = round((time.perf_counter() - start) * 1000, 2)
            return {
                "valid": True,
                "provider": "claude",
                "model": claude_prov.model_name,
                "latency_ms": latency,
                "sample_reply": resp.content.strip()[:100],
                "message": f"Kết nối Claude thành công ({latency}ms)",
            }
        else:
            return {
                "valid": False,
                "provider": provider,
                "error": f"Provider '{provider}' không được hỗ trợ",
                "latency_ms": None,
            }
    except Exception as exc:
        latency = round((time.perf_counter() - start) * 1000, 2)
        return {
            "valid": False,
            "provider": provider,
            "latency_ms": latency,
            "error": f"Lỗi gọi API {provider}: {exc}",
        }


@router.get("/system/status")
async def get_system_status(
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Check health and live status of Database, Qdrant, and AI provider configurations."""
    # 1. Database check
    try:
        await session.execute(text("SELECT 1"))
        db_info = {"status": "connected", "type": "sqlite"}
    except Exception as exc:
        db_info = {"status": "error", "error": str(exc)}

    # 2. Qdrant check
    try:
        q_service = QdrantVectorService(location=":memory:")
        q_service.ensure_collection("system_check", vector_size=4)
        qdrant_info = {"status": "connected", "mode": "in-memory-ready"}
    except Exception as exc:
        qdrant_info = {"status": "degraded", "error": str(exc)}

    # 3. AI Providers check
    config = get_settings()
    ai_info = {
        "gemini_configured": bool(config.gemini_api_key),
        "openai_configured": bool(config.openai_api_key),
        "claude_configured": bool(config.anthropic_api_key),
    }

    return {
        "database": db_info,
        "qdrant": qdrant_info,
        "ai_providers": ai_info,
    }


# ===========================================================================
# Omnichannel Live Chat, Human Takeover & AI Inspector Endpoints
# ===========================================================================


class AgentSendMessageRequest(BaseModel):
    content: str = Field(..., min_length=1)


@router.get("/conversations")
async def list_conversations(
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """List recent conversations with latest customer info and bot status."""
    stmt = (
        select(Conversation, Customer)
        .outerjoin(Customer, Conversation.customer_id == Customer.id)
        .order_by(Conversation.id.desc())
        .limit(50)
    )
    res = await session.execute(stmt)
    rows = res.all()
    if not rows:
        return []

    conv_ids = [c.id for c, _ in rows]
    msg_stmt = (
        select(Message)
        .where(Message.conversation_id.in_(conv_ids))
        .order_by(Message.conversation_id, Message.sent_at.desc())
    )
    msg_res = await session.execute(msg_stmt)
    all_msgs = msg_res.scalars().all()
    latest_msg_by_conv: dict[int, Message] = {}
    for m in all_msgs:
        if m.conversation_id not in latest_msg_by_conv:
            latest_msg_by_conv[m.conversation_id] = m

    results = []
    for c, cust in rows:
        last_msg = latest_msg_by_conv.get(c.id)
        results.append(
            {
                "id": c.id,
                "customer_id": c.customer_id,
                "customer_name": cust.name if cust else f"Khách #{c.customer_id}",
                "platform_user_id": cust.platform_user_id if cust else "",
                "channel": c.channel,
                "status": c.status.value if hasattr(c.status, "value") else str(c.status),
                "is_bot_active": c.is_bot_active,
                "started_at": c.started_at.isoformat() if c.started_at else None,
                "last_message": last_msg.content if last_msg else None,
                "last_message_role": (
                    last_msg.role.value
                    if (last_msg and hasattr(last_msg.role, "value"))
                    else (last_msg.role if last_msg else None)
                ),
            }
        )
    return results


@router.get("/conversations/{conversation_id}/messages")
async def get_conversation_messages(
    conversation_id: int,
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """Get all messages for a specific conversation."""
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.sent_at.asc())
    )
    res = await session.execute(stmt)
    messages = res.scalars().all()
    return [
        {
            "id": m.id,
            "role": m.role.value if hasattr(m.role, "value") else str(m.role),
            "content": m.content,
            "media_urls": m.media_urls,
            "message_type": (
                m.message_type.value if hasattr(m.message_type, "value") else str(m.message_type)
            ),
            "sent_at": m.sent_at.isoformat() if m.sent_at else None,
        }
        for m in messages
    ]


@router.post("/conversations/{conversation_id}/takeover")
async def takeover_conversation(
    conversation_id: int,
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Take over conversation: silence bot so human agent can handle chat directly."""
    stmt = select(Conversation).where(Conversation.id == conversation_id)
    conv = (await session.execute(stmt)).scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conv.is_bot_active = False
    await session.commit()

    await live_chat_manager.broadcast(
        event_type="bot_status_changed",
        data={"conversation_id": conversation_id, "is_bot_active": False},
    )
    return {"success": True, "conversation_id": conversation_id, "is_bot_active": False}


@router.post("/conversations/{conversation_id}/handover")
async def handover_conversation(
    conversation_id: int,
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Hand over conversation back to automated AI bot."""
    stmt = select(Conversation).where(Conversation.id == conversation_id)
    conv = (await session.execute(stmt)).scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conv.is_bot_active = True
    await session.commit()

    await live_chat_manager.broadcast(
        event_type="bot_status_changed",
        data={"conversation_id": conversation_id, "is_bot_active": True},
    )
    return {"success": True, "conversation_id": conversation_id, "is_bot_active": True}


@router.post("/conversations/{conversation_id}/send")
async def send_agent_message(
    conversation_id: int,
    data: AgentSendMessageRequest,
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Send message from staff/agent directly to customer."""
    stmt = select(Conversation).where(Conversation.id == conversation_id)
    conv = (await session.execute(stmt)).scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    cust = (
        await session.execute(select(Customer).where(Customer.id == conv.customer_id))
    ).scalar_one_or_none()
    recipient_id = cust.platform_user_id if cust else str(conv.customer_id)

    # Log agent message to database
    agent_msg = Message(
        conversation_id=conversation_id,
        role=MessageRole.AGENT,
        content=data.content,
        message_type=MessageType.TEXT,
    )
    session.add(agent_msg)
    await session.commit()
    await session.refresh(agent_msg)

    # Attempt to dispatch to outward channel
    try:
        sender = await MessageSender.from_settings(session)
        ch_enum = (
            ChannelType(conv.channel)
            if conv.channel in ChannelType._value2member_map_
            else ChannelType.WEBSITE
        )
        outgoing = OutgoingMessage(
            recipient_id=recipient_id,
            channel=ch_enum,
            content=data.content,
        )
        await sender.send_message(outgoing)
    except Exception as exc:
        logger.warning(f"Could not dispatch agent message outward: {exc}")

    # Broadcast event to connected admin dashboards
    await live_chat_manager.broadcast(
        event_type="agent_message",
        data={
            "conversation_id": conversation_id,
            "content": data.content,
            "sent_at": agent_msg.sent_at.isoformat() if agent_msg.sent_at else None,
        },
    )

    return {"success": True, "message_id": agent_msg.id, "content": data.content}


@router.get("/conversations/{conversation_id}/inspect")
async def inspect_conversation(
    conversation_id: int,
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(get_current_user),
) -> dict[str, Any]:
    """AI Inspector: X-Ray view into prompts, context, and guardrail intervention logs."""
    stmt = select(Conversation).where(Conversation.id == conversation_id)
    conv = (await session.execute(stmt)).scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    cust = (
        await session.execute(select(Customer).where(Customer.id == conv.customer_id))
    ).scalar_one_or_none()
    messages = (
        (
            await session.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.sent_at.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )

    # Query guardrail logs
    g_logs = (
        (
            await session.execute(
                select(GuardrailLog)
                .where(GuardrailLog.conversation_id == conversation_id)
                .order_by(GuardrailLog.id.desc())
                .limit(10)
            )
        )
        .scalars()
        .all()
    )

    settings_service = SettingsService(session)
    active_persona = await settings_service.get_setting("bot_persona") or DEFAULT_COMMERCE_PERSONA
    active_preset = await settings_service.get_setting("bot_preset") or "general"

    return {
        "conversation_id": conv.id,
        "channel": conv.channel,
        "customer": {
            "id": cust.id if cust else conv.customer_id,
            "name": cust.name if cust else None,
            "platform_user_id": cust.platform_user_id if cust else "",
        },
        "is_bot_active": conv.is_bot_active,
        "status": conv.status.value if hasattr(conv.status, "value") else str(conv.status),
        "active_persona": active_persona,
        "active_preset": active_preset,
        "messages_count": len(messages),
        "recent_messages": [
            {
                "id": m.id,
                "role": m.role.value if hasattr(m.role, "value") else str(m.role),
                "content": m.content,
                "sent_at": m.sent_at.isoformat() if m.sent_at else None,
            }
            for m in reversed(messages)
        ],
        "guardrail_interventions": [
            {
                "id": g.id,
                "type": g.guardrail_type,
                "action": g.action_taken,
                "original": g.original_text,
                "modified": g.modified_text,
                "created_at": g.created_at.isoformat() if g.created_at else None,
            }
            for g in g_logs
        ],
    }


# ===========================================================================
# Customer CRM & Funnel Endpoints
# ===========================================================================


@router.get("/customers", response_model=PaginatedResponse[CustomerDetail])
async def list_customers(
    funnel_stage: str | None = None,
    platform: str | None = None,
    search: str | None = None,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    sort_by: str = Query("last_contact_at"),
    sort_order: str = Query("desc"),
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(get_current_user),
) -> PaginatedResponse[CustomerDetail]:
    tenant_id = getattr(_user, "tenant_id", None) or "default-system-tenant"
    count_stmt = select(func.count(Customer.id))
    stmt = select(Customer)
    if not getattr(_user, "is_superadmin", False):
        count_stmt = count_stmt.where(Customer.tenant_id == tenant_id)
        stmt = stmt.where(Customer.tenant_id == tenant_id)
    if funnel_stage:
        count_stmt = count_stmt.where(Customer.funnel_stage == funnel_stage)
        stmt = stmt.where(Customer.funnel_stage == funnel_stage)
    if platform:
        count_stmt = count_stmt.where(Customer.platform == platform)
        stmt = stmt.where(Customer.platform == platform)
    if search:
        pattern = f"%{search}%"
        filter_expr = (
            (Customer.name.ilike(pattern))
            | (Customer.phone.ilike(pattern))
            | (Customer.platform_user_id.ilike(pattern))
        )
        count_stmt = count_stmt.where(filter_expr)
        stmt = stmt.where(filter_expr)

    total = (await session.execute(count_stmt)).scalar() or 0

    sort_map = {
        "id": Customer.id,
        "name": Customer.name,
        "phone": Customer.phone,
        "first_contact_at": Customer.first_contact_at,
        "last_contact_at": Customer.last_contact_at,
        "funnel_stage": Customer.funnel_stage,
    }
    col = sort_map.get(sort_by, Customer.last_contact_at)
    order_clause = col.desc() if sort_order.lower() == "desc" else col.asc()

    offset = (page - 1) * limit
    stmt = stmt.order_by(order_clause).offset(offset).limit(limit)
    res = await session.execute(stmt)
    customers = res.scalars().all()

    result: list[CustomerDetail] = []
    for c in customers:
        orders_stmt = select(
            func.count(Order.id),
            func.coalesce(func.sum(Order.total_amount), 0.0),
        ).where(Order.customer_id == c.id)
        order_res = await session.execute(orders_stmt)
        count, order_total = order_res.one()

        detail = CustomerDetail(
            id=c.id,
            platform=c.platform.value if hasattr(c.platform, "value") else str(c.platform),
            platform_user_id=c.platform_user_id,
            name=c.name,
            email=c.email,
            phone=c.phone,
            funnel_stage=c.funnel_stage or "lead",
            notes=c.notes,
            address=c.address,
            tags=c.tags or {},
            first_contact_at=c.first_contact_at,
            last_contact_at=c.last_contact_at,
            total_orders=int(count),
            total_spent=float(order_total),
        )
        result.append(detail)

    total_pages = (total + limit - 1) // limit if total > 0 else 1
    return PaginatedResponse[CustomerDetail](
        items=result,
        total=total,
        page=page,
        limit=limit,
        total_pages=total_pages,
    )


@router.get("/customers/export")
async def export_customers_csv(
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(require_roles("admin", "manager")),
) -> Response:
    tenant_id = getattr(_user, "tenant_id", None) or "default-system-tenant"
    stmt = (
        select(
            Customer,
            func.count(Order.id).label("order_count"),
            func.coalesce(func.sum(Order.total_amount), 0.0).label("total_spent"),
        )
        .outerjoin(Order, Customer.id == Order.customer_id)
    )
    if not getattr(_user, "is_superadmin", False):
        stmt = stmt.where(Customer.tenant_id == tenant_id)
    stmt = stmt.group_by(Customer.id).order_by(Customer.id.asc())
    rows = (await session.execute(stmt)).all()

    output = io.StringIO()
    writer = csv.writer(output, dialect="excel")
    writer.writerow(
        [
            "Mã khách",
            "Nền tảng",
            "Mã người dùng nền tảng",
            "Họ và tên",
            "Số điện thoại",
            "Email",
            "Giai đoạn phễu",
            "Địa chỉ",
            "Số đơn hàng",
            "Tổng chi tiêu (VNĐ)",
            "Nhãn / Tags",
            "Ghi chú",
            "Ngày tương tác đầu",
            "Ngày tương tác gần nhất",
        ]
    )

    for c, order_count, total_spent in rows:
        tags_list: list[str] = []
        if isinstance(c.tags, dict):
            if "labels" in c.tags and isinstance(c.tags["labels"], list):
                tags_list = [str(x) for x in c.tags["labels"]]
            else:
                tags_list = [str(k) for k, v in c.tags.items() if v]
        elif isinstance(c.tags, list):
            tags_list = [str(t) for t in c.tags]

        writer.writerow(
            [
                c.id,
                c.platform.value if hasattr(c.platform, "value") else str(c.platform),
                c.platform_user_id,
                c.name or "",
                c.phone or "",
                c.email or "",
                c.funnel_stage or "lead",
                c.address or "",
                int(order_count or 0),
                f"{float(total_spent or 0.0):,.0f}",
                ", ".join(tags_list),
                c.notes or "",
                c.first_contact_at.strftime("%Y-%m-%d %H:%M:%S") if c.first_contact_at else "",
                c.last_contact_at.strftime("%Y-%m-%d %H:%M:%S") if c.last_contact_at else "",
            ]
        )

    csv_bytes = output.getvalue().encode("utf-8-sig")
    now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename=customers_{now_str}.csv",
        },
    )


@router.post("/customers", response_model=CustomerDetail)
async def create_customer(
    data: CustomerCreate,
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(get_current_user),
) -> CustomerDetail:
    """Manually create a new customer record."""
    service = CustomerService(session)
    existing = await service.get_by_platform_id(data.platform, data.platform_user_id)
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Khách hàng với mã {data.platform_user_id} ({data.platform}) đã tồn tại",
        )
    cust = await service.create_customer(data)
    if data.funnel_stage:
        cust.funnel_stage = data.funnel_stage
    if data.notes:
        cust.notes = data.notes
    if data.address:
        cust.address = data.address
    await session.commit()
    await session.refresh(cust)

    return CustomerDetail(
        id=cust.id,
        platform=cust.platform.value if hasattr(cust.platform, "value") else str(cust.platform),
        platform_user_id=cust.platform_user_id,
        name=cust.name,
        email=cust.email,
        phone=cust.phone,
        funnel_stage=cust.funnel_stage or "lead",
        notes=cust.notes,
        address=cust.address,
        tags=cust.tags or {},
        first_contact_at=cust.first_contact_at,
        last_contact_at=cust.last_contact_at,
        total_orders=0,
        total_spent=0.0,
    )


@router.get("/customers/funnel-stats", response_model=FunnelStatsResponse)
async def get_funnel_stats(
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(get_current_user),
) -> FunnelStatsResponse:
    return await FunnelService.get_funnel_statistics(session)


@router.get("/customers/{customer_id}")
async def get_customer_detail(
    customer_id: int,
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(get_current_user),
) -> dict[str, Any]:
    stmt = select(Customer).where(Customer.id == customer_id)
    cust = (await session.execute(stmt)).scalar_one_or_none()
    if not cust:
        raise HTTPException(status_code=404, detail="Customer not found")

    ord_stmt = (
        select(Order).where(Order.customer_id == customer_id).order_by(Order.ordered_at.desc())
    )
    orders = (await session.execute(ord_stmt)).scalars().all()

    conv_stmt = (
        select(Conversation)
        .where(Conversation.customer_id == customer_id)
        .order_by(Conversation.started_at.desc())
    )
    convs = (await session.execute(conv_stmt)).scalars().all()

    vietqr = await VietQRService.from_settings(session)
    return {
        "customer": CustomerDetail(
            id=cust.id,
            platform=cust.platform.value if hasattr(cust.platform, "value") else str(cust.platform),
            platform_user_id=cust.platform_user_id,
            name=cust.name,
            email=cust.email,
            phone=cust.phone,
            funnel_stage=cust.funnel_stage or "lead",
            notes=cust.notes,
            address=cust.address,
            tags=cust.tags or {},
            first_contact_at=cust.first_contact_at,
            last_contact_at=cust.last_contact_at,
            total_orders=len(orders),
            total_spent=sum(float(o.total_amount) for o in orders),
        ),
        "orders": [
            {
                "id": o.id,
                "status": o.status.value if hasattr(o.status, "value") else str(o.status),
                "total_amount": float(o.total_amount),
                "items": o.items,
                "notes": o.notes,
                "ordered_at": o.ordered_at.isoformat() if o.ordered_at else None,
                "vietqr_url": vietqr.generate_qr_url(amount=o.total_amount, memo=f"DH{o.id}"),
            }
            for o in orders
        ],
        "conversations": [
            {
                "id": cv.id,
                "channel": cv.channel,
                "status": cv.status.value if hasattr(cv.status, "value") else str(cv.status),
                "is_bot_active": cv.is_bot_active,
                "started_at": cv.started_at.isoformat() if cv.started_at else None,
            }
            for cv in convs
        ],
    }


@router.put("/customers/{customer_id}", response_model=CustomerDetail)
async def update_customer(
    customer_id: int,
    data: CustomerUpdate,
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(get_current_user),
) -> CustomerDetail:
    stmt = select(Customer).where(Customer.id == customer_id)
    cust = (await session.execute(stmt)).scalar_one_or_none()
    if not cust:
        raise HTTPException(status_code=404, detail="Customer not found")

    if data.name is not None:
        cust.name = data.name
    if data.email is not None:
        cust.email = data.email
    if data.phone is not None:
        cust.phone = data.phone
    if data.funnel_stage is not None:
        cust.funnel_stage = data.funnel_stage
    if data.notes is not None:
        cust.notes = data.notes
    if data.address is not None:
        cust.address = data.address
    if data.tags is not None:
        cust.tags = dict(data.tags)

    await session.commit()
    await session.refresh(cust)

    orders_stmt = select(
        func.count(Order.id),
        func.coalesce(func.sum(Order.total_amount), 0.0),
    ).where(Order.customer_id == cust.id)
    order_res = await session.execute(orders_stmt)
    count, total = order_res.one()

    return CustomerDetail(
        id=cust.id,
        platform=cust.platform.value if hasattr(cust.platform, "value") else str(cust.platform),
        platform_user_id=cust.platform_user_id,
        name=cust.name,
        email=cust.email,
        phone=cust.phone,
        funnel_stage=cust.funnel_stage or "lead",
        notes=cust.notes,
        address=cust.address,
        tags=cust.tags or {},
        first_contact_at=cust.first_contact_at,
        last_contact_at=cust.last_contact_at,
        total_orders=int(count),
        total_spent=float(total),
    )


# ===========================================================================
# Orders Management Endpoints
# ===========================================================================


@router.get("/orders", response_model=PaginatedResponse[OrderDetail])
async def list_orders(
    status: OrderStatus | None = None,
    customer_id: int | None = None,
    search: str | None = None,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    sort_by: str = Query("ordered_at"),
    sort_order: str = Query("desc"),
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(get_current_user),
) -> PaginatedResponse[OrderDetail]:
    tenant_id = getattr(_user, "tenant_id", None) or "default-system-tenant"
    base_filter: list[Any] = []
    if not getattr(_user, "is_superadmin", False):
        base_filter.append(Order.tenant_id == tenant_id)
    if status is not None:
        base_filter.append(Order.status == status)
    if customer_id is not None:
        base_filter.append(Order.customer_id == customer_id)
    if search:
        search_pattern = f"%{search.strip()}%"
        filters: list[Any] = [
            Customer.name.ilike(search_pattern),
            Customer.phone.ilike(search_pattern),
            Order.notes.ilike(search_pattern),
            cast(Order.items, String).ilike(search_pattern),
        ]
        s_clean = search.strip()
        if s_clean.isdigit():
            filters.append(Order.id == int(s_clean))
        elif s_clean.upper().startswith("DH") and s_clean[2:].isdigit():
            filters.append(Order.id == int(s_clean[2:]))
        base_filter.append(or_(*filters))

    count_stmt = select(func.count(Order.id)).join(Customer, Order.customer_id == Customer.id)
    if base_filter:
        count_stmt = count_stmt.where(*base_filter)

    total = (await session.execute(count_stmt)).scalar() or 0

    sort_map = {
        "id": Order.id,
        "ordered_at": Order.ordered_at,
        "total_amount": Order.total_amount,
        "status": Order.status,
    }
    col = sort_map.get(sort_by, Order.ordered_at)
    order_clause = col.desc() if sort_order.lower() == "desc" else col.asc()

    offset = (page - 1) * limit
    stmt = select(Order, Customer.name, Customer.phone).join(
        Customer, Order.customer_id == Customer.id
    )
    if base_filter:
        stmt = stmt.where(*base_filter)

    stmt = stmt.order_by(order_clause).offset(offset).limit(limit)

    rows = (await session.execute(stmt)).all()
    vietqr = await VietQRService.from_settings(session)

    results: list[OrderDetail] = []
    for order, c_name, c_phone in rows:
        vietqr_url = vietqr.generate_qr_url(amount=order.total_amount, memo=f"DH{order.id}")
        st = order.status if isinstance(order.status, OrderStatus) else OrderStatus(order.status)
        results.append(
            OrderDetail(
                id=order.id,
                customer_id=order.customer_id,
                status=st,
                total_amount=float(order.total_amount),
                items=order.items or [],
                notes=order.notes,
                ordered_at=order.ordered_at,
                delivered_at=order.delivered_at,
                upsale_sent=order.upsale_sent,
                customer_name=c_name,
                customer_phone=c_phone,
                vietqr_url=vietqr_url,
            )
        )

    total_pages = (total + limit - 1) // limit if total > 0 else 1
    return PaginatedResponse[OrderDetail](
        items=results,
        total=total,
        page=page,
        limit=limit,
        total_pages=total_pages,
    )


@router.get("/orders/export")
async def export_orders_csv(
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(require_roles("admin", "manager")),
) -> Response:
    tenant_id = getattr(_user, "tenant_id", None) or "default-system-tenant"
    stmt = (
        select(Order, Customer.name, Customer.phone, Customer.platform)
        .join(Customer, Order.customer_id == Customer.id)
    )
    if not getattr(_user, "is_superadmin", False):
        stmt = stmt.where(Order.tenant_id == tenant_id)
    stmt = stmt.order_by(Order.ordered_at.desc())
    rows = (await session.execute(stmt)).all()
    vietqr = await VietQRService.from_settings(session)

    output = io.StringIO()
    writer = csv.writer(output, dialect="excel")
    writer.writerow(
        [
            "Mã đơn",
            "Mã hiển thị",
            "Tên khách hàng",
            "Số điện thoại",
            "Nền tảng",
            "Trạng thái",
            "Tổng tiền (VNĐ)",
            "Sản phẩm",
            "Ghi chú",
            "Link VietQR",
            "Ngày đặt",
        ]
    )

    for order, c_name, c_phone, c_platform in rows:
        items_summary: list[str] = []
        for it in order.items or []:
            if isinstance(it, dict):
                p_name = it.get("name") or it.get("product_name") or it.get("sku") or "Sản phẩm"
                qty = it.get("quantity", 1)
                items_summary.append(f"{p_name} (x{qty})")
        items_str = "; ".join(items_summary)
        qr_url = vietqr.generate_qr_url(amount=order.total_amount, memo=f"DH{order.id}")
        st = order.status.value if hasattr(order.status, "value") else str(order.status)
        writer.writerow(
            [
                order.id,
                f"DH{order.id}",
                c_name or "",
                c_phone or "",
                c_platform.value if hasattr(c_platform, "value") else str(c_platform),
                st,
                f"{float(order.total_amount):,.0f}",
                items_str,
                order.notes or "",
                qr_url,
                order.ordered_at.strftime("%Y-%m-%d %H:%M:%S") if order.ordered_at else "",
            ]
        )

    csv_bytes = output.getvalue().encode("utf-8-sig")
    now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename=orders_{now_str}.csv",
        },
    )


@router.post("/orders", response_model=OrderDetail)
async def create_order(
    data: OrderCreate,
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(get_current_user),
) -> OrderDetail:
    stmt_cust = select(Customer).where(Customer.id == data.customer_id)
    cust = (await session.execute(stmt_cust)).scalar_one_or_none()
    if not cust:
        raise HTTPException(status_code=404, detail="Customer not found")

    total = data.total_amount
    if total is None:
        total = sum(item.price * item.quantity for item in data.items)

    order = Order(
        customer_id=data.customer_id,
        status=OrderStatus.PENDING,
        total_amount=float(total),
        items=[item.model_dump() for item in data.items],
        notes=data.notes,
    )
    session.add(order)
    await session.commit()
    await session.refresh(order)

    # Auto-promote customer funnel stage
    await FunnelService.check_and_promote_after_order(session, data.customer_id)

    vietqr = await VietQRService.from_settings(session)
    qr_url = vietqr.generate_qr_url(amount=order.total_amount, memo=f"DH{order.id}")
    st = order.status if isinstance(order.status, OrderStatus) else OrderStatus(order.status)

    return OrderDetail(
        id=order.id,
        customer_id=order.customer_id,
        status=st,
        total_amount=float(order.total_amount),
        items=order.items or [],
        notes=order.notes,
        ordered_at=order.ordered_at,
        delivered_at=order.delivered_at,
        upsale_sent=order.upsale_sent,
        customer_name=cust.name,
        customer_phone=cust.phone,
        vietqr_url=qr_url,
    )


@router.put("/orders/{order_id}/status", response_model=OrderDetail)
async def update_order_status(
    order_id: int,
    data: OrderStatusUpdate,
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(get_current_user),
) -> OrderDetail:
    stmt = (
        select(Order, Customer.name, Customer.phone)
        .join(Customer, Order.customer_id == Customer.id)
        .where(Order.id == order_id)
    )
    row = (await session.execute(stmt)).first()
    if not row:
        raise HTTPException(status_code=404, detail="Order not found")

    order, c_name, c_phone = row
    order.status = data.status
    if data.notes:
        order.notes = (order.notes or "") + f" | {data.notes}"
    if data.status == OrderStatus.DELIVERED and not order.delivered_at:
        order.delivered_at = datetime.now(timezone.utc)

    await session.commit()
    await session.refresh(order)

    vietqr = await VietQRService.from_settings(session)
    qr_url = vietqr.generate_qr_url(amount=order.total_amount, memo=f"DH{order.id}")
    st = order.status if isinstance(order.status, OrderStatus) else OrderStatus(order.status)

    return OrderDetail(
        id=order.id,
        customer_id=order.customer_id,
        status=st,
        total_amount=float(order.total_amount),
        items=order.items or [],
        notes=order.notes,
        ordered_at=order.ordered_at,
        delivered_at=order.delivered_at,
        upsale_sent=order.upsale_sent,
        customer_name=c_name,
        customer_phone=c_phone,
        vietqr_url=qr_url,
    )


@router.get("/orders/{order_id}/vietqr")
async def get_order_vietqr(
    order_id: int,
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(get_current_user),
) -> dict[str, Any]:
    stmt = select(Order).where(Order.id == order_id)
    order = (await session.execute(stmt)).scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    vietqr = await VietQRService.from_settings(session)
    return vietqr.generate_order_payment(order_id=order.id, amount=order.total_amount)


@router.websocket("/ws/livechat")
async def livechat_websocket(
    websocket: WebSocket,
    token: str | None = Query(None),
) -> None:
    """WebSocket endpoint for real-time live chat inbox and takeover events.

    Requires valid JWT access token passed via query parameter: ?token=<jwt>
    """
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    try:
        payload = decode_token(token)
        if payload.get("type") != "access" or not payload.get("sub"):
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
    except Exception:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await live_chat_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        live_chat_manager.disconnect(websocket)
    except Exception:
        live_chat_manager.disconnect(websocket)


# ===========================================================================
# Quick Reply Templates Endpoints (Phase 13)
# ===========================================================================


@router.get("/quick-replies", response_model=list[QuickReplyDetail])
async def list_quick_replies(
    category: str | None = None,
    search: str | None = None,
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(get_current_user),
) -> list[QuickReplyDetail]:
    """List all quick reply canned templates."""
    tenant_id = getattr(_user, "tenant_id", None) or "default-system-tenant"
    stmt = select(QuickReply)
    if not getattr(_user, "is_superadmin", False):
        stmt = stmt.where(QuickReply.tenant_id == tenant_id)
    if category:
        stmt = stmt.where(QuickReply.category == category)
    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(
            (QuickReply.title.ilike(pattern))
            | (QuickReply.shortcut.ilike(pattern))
            | (QuickReply.content.ilike(pattern))
        )
    stmt = stmt.order_by(QuickReply.id.asc())
    rows = (await session.execute(stmt)).scalars().all()
    return [QuickReplyDetail.model_validate(r) for r in rows]


@router.post("/quick-replies", response_model=QuickReplyDetail)
async def create_quick_reply(
    data: QuickReplyCreate,
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(get_current_user),
) -> QuickReplyDetail:
    """Create a new quick reply template."""
    tenant_id = getattr(_user, "tenant_id", None) or "default-system-tenant"
    existing = (
        await session.execute(
            select(QuickReply).where(
                QuickReply.shortcut == data.shortcut.strip(),
                QuickReply.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Phím tắt '{data.shortcut}' đã được sử dụng bởi mẫu khác",
        )

    qr = QuickReply(
        tenant_id=tenant_id,
        title=data.title.strip(),
        shortcut=data.shortcut.strip(),
        content=data.content.strip(),
        category=data.category.strip() if data.category else "general",
    )
    session.add(qr)
    await session.commit()
    await session.refresh(qr)
    return QuickReplyDetail.model_validate(qr)


@router.put("/quick-replies/{reply_id}", response_model=QuickReplyDetail)
async def update_quick_reply(
    reply_id: int,
    data: QuickReplyUpdate,
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(get_current_user),
) -> QuickReplyDetail:
    """Update an existing quick reply template."""
    qr = (
        await session.execute(select(QuickReply).where(QuickReply.id == reply_id))
    ).scalar_one_or_none()
    if not qr:
        raise HTTPException(status_code=404, detail="Quick reply not found")

    if data.shortcut is not None and data.shortcut.strip() != qr.shortcut:
        dup = (
            await session.execute(
                select(QuickReply).where(
                    QuickReply.shortcut == data.shortcut.strip(),
                    QuickReply.id != reply_id,
                )
            )
        ).scalar_one_or_none()
        if dup:
            raise HTTPException(
                status_code=400,
                detail=f"Phím tắt '{data.shortcut}' đã được sử dụng bởi mẫu khác",
            )
        qr.shortcut = data.shortcut.strip()

    if data.title is not None:
        qr.title = data.title.strip()
    if data.content is not None:
        qr.content = data.content.strip()
    if data.category is not None:
        qr.category = data.category.strip()

    await session.commit()
    await session.refresh(qr)
    return QuickReplyDetail.model_validate(qr)


@router.delete("/quick-replies/{reply_id}")
async def delete_quick_reply(
    reply_id: int,
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Delete a quick reply template."""
    qr = (
        await session.execute(select(QuickReply).where(QuickReply.id == reply_id))
    ).scalar_one_or_none()
    if not qr:
        raise HTTPException(status_code=404, detail="Quick reply not found")

    await session.delete(qr)
    await session.commit()
    return {"success": True, "message": f"Quick reply {reply_id} deleted"}


# ===========================================================================
# Real-time Notification Center Endpoints (Phase 13)
# ===========================================================================

_admin_notifications_read_at: dict[str, datetime] = {}


@router.get("/notifications")
async def list_notifications(
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """Retrieve recent notifications synthesized from database events."""
    recent_orders = (
        await session.execute(
            select(Order, Customer.name)
            .join(Customer, Order.customer_id == Customer.id)
            .order_by(Order.ordered_at.desc())
            .limit(5)
        )
    ).all()

    escalations = (
        await session.execute(
            select(Conversation, Customer.name)
            .join(Customer, Conversation.customer_id == Customer.id)
            .where(Conversation.is_bot_active.is_(False))
            .order_by(Conversation.started_at.desc())
            .limit(5)
        )
    ).all()

    user_read_at = _admin_notifications_read_at.get(_user.username)
    notifications: list[dict[str, Any]] = []

    for ord_obj, c_name in recent_orders:
        ord_dt = ord_obj.ordered_at if ord_obj.ordered_at else datetime.now(timezone.utc)
        if ord_dt.tzinfo is None:
            ord_dt = ord_dt.replace(tzinfo=timezone.utc)
        is_read = bool(user_read_at and ord_dt <= user_read_at)
        notifications.append(
            {
                "id": f"order-{ord_obj.id}",
                "type": "order",
                "title": f"Đơn hàng mới #DH{ord_obj.id}",
                "message": f"Khách hàng {c_name or 'Ẩn danh'} đã đặt đơn {ord_obj.total_amount:,.0f}đ",
                "timestamp": ord_dt.isoformat(),
                "created_at": ord_dt.isoformat(),
                "read": is_read,
                "is_read": is_read,
                "link": "#orders",
            }
        )

    for conv, c_name in escalations:
        c_plat = conv.platform.value if hasattr(conv.platform, "value") else str(conv.platform)
        conv_dt = conv.started_at if conv.started_at else datetime.now(timezone.utc)
        if conv_dt.tzinfo is None:
            conv_dt = conv_dt.replace(tzinfo=timezone.utc)
        is_read = bool(user_read_at and conv_dt <= user_read_at)
        notifications.append(
            {
                "id": f"esc-{conv.id}",
                "type": "escalation",
                "title": "Yêu cầu hỗ trợ (Takeover)",
                "message": f"Khách hàng {c_name or 'Ẩn danh'} ({c_plat}) đã yêu cầu nhân viên hỗ trợ",
                "timestamp": conv_dt.isoformat(),
                "created_at": conv_dt.isoformat(),
                "read": is_read,
                "is_read": is_read,
                "link": "#livechat",
            }
        )

    notifications.sort(key=lambda n: str(n["timestamp"]), reverse=True)
    return notifications


@router.post("/notifications/mark-read")
async def mark_notifications_read(
    _user: AdminUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Acknowledge and mark all current notifications as read."""
    _admin_notifications_read_at[_user.username] = datetime.now(timezone.utc)
    return {"success": True, "message": "All notifications marked as read"}


# ===========================================================================
# Infrastructure & Database Backup Endpoint (Phase 11)
# ===========================================================================


@router.post("/system/backup")
async def trigger_system_backup(
    _user: AdminUser = Depends(require_roles("admin")),
) -> dict[str, Any]:
    """Trigger manual database and vector store backup to ./data/backups/."""
    try:
        from scripts.backup_db import perform_backup

        res = await asyncio.to_thread(perform_backup)
        await live_chat_manager.broadcast(
            "backup_completed",
            {
                "timestamp": res["timestamp"],
                "total_size": res["total_size_bytes"],
                "file_count": len(res["files"]),
            },
        )
        return res
    except Exception as exc:
        logger.error(f"System backup error: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"Lỗi khi thực hiện sao lưu cơ sở dữ liệu: {exc}",
        )


@router.get("/system/backup/latest")
async def get_latest_backup_metadata(
    _user: AdminUser = Depends(require_roles("admin")),
) -> dict[str, Any]:
    """Retrieve metadata of the latest database backup."""
    from scripts.backup_db import get_latest_backup_info

    info = get_latest_backup_info()
    if not info:
        return {"status": "none", "message": "Chưa có bản sao lưu nào"}
    return {"status": "success", "manifest": info}


# ===========================================================================
# Staff Management Endpoints (RBAC - Admin Only)
# ===========================================================================


@router.get("/staff", response_model=list[StaffDetail])
async def list_staff_members(
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(require_roles("admin")),
) -> list[StaffDetail]:
    """List all staff accounts with their RBAC roles (Admin only)."""
    stmt = select(AdminUser).order_by(AdminUser.id.asc())
    users = (await session.execute(stmt)).scalars().all()
    return [StaffDetail.model_validate(u) for u in users]


@router.post("/staff", response_model=StaffDetail)
async def create_staff_member(
    data: StaffCreate,
    session: AsyncSession = Depends(get_db_session),
    current_user: AdminUser = Depends(require_roles("admin")),
) -> StaffDetail:
    """Create a new staff user with designated role (Admin only)."""
    stmt = select(AdminUser).where(AdminUser.username == data.username)
    if (await session.execute(stmt)).scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tên đăng nhập '{data.username}' đã tồn tại.",
        )

    new_user = AdminUser(
        username=data.username,
        hashed_password=hash_password(data.password),
        display_name=data.display_name,
        role=data.role,
        email=data.email,
        phone=data.phone,
        is_active=True,
        created_by_id=current_user.id,
    )
    session.add(new_user)
    await session.commit()
    await session.refresh(new_user)
    return StaffDetail.model_validate(new_user)


@router.put("/staff/{user_id}", response_model=StaffDetail)
async def update_staff_member(
    user_id: int,
    data: StaffUpdate,
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(require_roles("admin")),
) -> StaffDetail:
    """Update staff details, status, or role (Admin only)."""
    stmt = select(AdminUser).where(AdminUser.id == user_id)
    target = (await session.execute(stmt)).scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Nhân viên không tồn tại.")

    if data.display_name is not None:
        target.display_name = data.display_name
    if data.role is not None:
        target.role = data.role
    if data.email is not None:
        target.email = data.email
    if data.phone is not None:
        target.phone = data.phone
    if data.is_active is not None:
        target.is_active = data.is_active
    if data.password:
        target.hashed_password = hash_password(data.password)

    await session.commit()
    await session.refresh(target)
    return StaffDetail.model_validate(target)


@router.delete("/staff/{user_id}")
async def delete_staff_member(
    user_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: AdminUser = Depends(require_roles("admin")),
) -> dict[str, Any]:
    """Delete a staff member account (with safeguard against self/root deletion)."""
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Không thể tự xóa tài khoản của chính mình.",
        )

    stmt = select(AdminUser).where(AdminUser.id == user_id)
    target = (await session.execute(stmt)).scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Nhân viên không tồn tại.")

    if target.username == "admin":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Không thể xóa tài khoản quản trị viên mặc định.",
        )

    await session.delete(target)
    await session.commit()
    return {"success": True, "message": f"Đã xóa tài khoản '{target.username}' thành công."}


# ===========================================================================
# Broadcast Messaging Campaign Endpoints (Admin & Manager)
# ===========================================================================


@router.get("/broadcast/campaigns", response_model=list[BroadcastCampaignDetail])
async def list_broadcast_campaigns(
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(require_roles("admin", "manager")),
) -> list[BroadcastCampaignDetail]:
    """List all broadcast campaigns (Admin & Manager)."""
    stmt = select(BroadcastCampaign).order_by(BroadcastCampaign.id.desc())
    campaigns = (await session.execute(stmt)).scalars().all()
    return [BroadcastCampaignDetail.model_validate(c) for c in campaigns]


@router.post("/broadcast/campaigns", response_model=BroadcastCampaignDetail)
async def create_broadcast_campaign(
    data: BroadcastCampaignCreate,
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(require_roles("admin", "manager")),
) -> BroadcastCampaignDetail:
    """Create a new broadcast campaign and populate eligible recipients."""
    service = BroadcastService(session)
    campaign = await service.create_campaign(data)
    return BroadcastCampaignDetail.model_validate(campaign)


@router.get("/broadcast/campaigns/{campaign_id}", response_model=BroadcastCampaignDetail)
async def get_broadcast_campaign(
    campaign_id: int,
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(require_roles("admin", "manager")),
) -> BroadcastCampaignDetail:
    """Get detailed progress of a broadcast campaign."""
    stmt = select(BroadcastCampaign).where(BroadcastCampaign.id == campaign_id)
    campaign = (await session.execute(stmt)).scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=404, detail="Chiến dịch không tồn tại.")
    return BroadcastCampaignDetail.model_validate(campaign)


@router.post("/broadcast/campaigns/{campaign_id}/start")
async def start_broadcast_campaign(
    campaign_id: int,
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(require_roles("admin", "manager")),
) -> dict[str, Any]:
    """Start or resume execution of a broadcast campaign."""
    service = BroadcastService(session)
    return await service.start_campaign(campaign_id)


@router.post("/broadcast/campaigns/{campaign_id}/pause")
async def pause_broadcast_campaign(
    campaign_id: int,
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(require_roles("admin", "manager")),
) -> dict[str, Any]:
    """Pause an active broadcast campaign."""
    service = BroadcastService(session)
    return await service.pause_campaign(campaign_id)


# ===========================================================================
# Shipping Carrier Integration Endpoints (GHTK, GHN, Viettel Post)
# ===========================================================================


@router.post("/shipping/estimate-fee", response_model=ShippingCalculationResponse)
async def estimate_shipping_fee(
    data: ShippingCalculationRequest,
    _user: AdminUser = Depends(get_current_user),
) -> ShippingCalculationResponse:
    """Calculate estimated shipping fee from carrier."""
    carrier = get_shipping_carrier(data.carrier)
    fee_data = await carrier.calculate_fee(
        province=data.province,
        district=data.district,
        ward=data.ward,
        weight_grams=data.weight_grams,
        order_value=data.order_value,
    )
    return ShippingCalculationResponse(
        carrier=carrier.carrier_name,
        fee=float(fee_data.get("fee", 30000.0)),
        insurance_fee=float(fee_data.get("insurance_fee", 0.0)),
        estimated_days=str(fee_data.get("estimated_days", "2-3 ngày")),
    )


@router.post("/orders/{order_id}/shipment", response_model=ShipmentDetailResponse)
async def create_order_shipment(
    order_id: int,
    data: CreateShipmentRequest,
    session: AsyncSession = Depends(get_db_session),
    _user: AdminUser = Depends(get_current_user),
) -> ShipmentDetailResponse:
    """Create waybill with shipping carrier and link tracking code to order."""
    stmt = select(Order).where(Order.id == order_id)
    order = (await session.execute(stmt)).scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Đơn hàng không tồn tại.")

    cust_stmt = select(Customer).where(Customer.id == order.customer_id)
    customer = (await session.execute(cust_stmt)).scalar_one_or_none()

    recipient_name: str = (
        data.recipient_name
        or order.recipient_name
        or (customer.name if customer and customer.name else "")
        or "Khách Hàng"
    )
    recipient_phone: str = (
        data.recipient_phone
        or order.recipient_phone
        or (customer.phone if customer and customer.phone else "")
        or "0901234567"
    )
    shipping_address: str = (
        data.shipping_address
        or order.shipping_address
        or (customer.address if customer and customer.address else "")
        or "Hà Nội"
    )
    province = data.province or order.province or "Hà Nội"
    district = data.district or order.district or "Cầu Giấy"
    ward = data.ward or order.ward

    carrier = get_shipping_carrier(data.carrier)
    result = await carrier.create_shipment(
        order_id=order.id,
        recipient_name=recipient_name,
        recipient_phone=recipient_phone,
        shipping_address=shipping_address,
        province=province,
        district=district,
        ward=ward,
        weight_grams=data.weight_grams,
        cod_amount=data.cod_amount or order.total_amount,
        notes=data.note or order.notes,
    )

    if result.get("success"):
        order.carrier = carrier.carrier_name
        order.tracking_code = result["tracking_code"]
        order.shipping_fee = result.get("shipping_fee", 30000.0)
        order.carrier_status_text = "Đã tạo vận đơn - Chờ lấy hàng"
        order.recipient_name = recipient_name
        order.recipient_phone = recipient_phone
        order.shipping_address = shipping_address
        order.province = province
        order.district = district
        order.ward = ward
        order.status = OrderStatus.CONFIRMED
        await session.commit()
        await session.refresh(order)

        return ShipmentDetailResponse(
            success=True,
            carrier=carrier.carrier_name,
            tracking_code=order.tracking_code,
            shipping_fee=order.shipping_fee,
            estimated_delivery=result.get("estimated_delivery"),
            message="Tạo vận đơn thành công",
        )

    raise HTTPException(status_code=400, detail="Không thể tạo vận đơn với hãng vận chuyển.")

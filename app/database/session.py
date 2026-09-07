"""Database session management with async SQLAlchemy."""

from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy import Connection, inspect, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


def normalize_database_url(url: str) -> str:
    """Normalize database connection URL to async driver."""
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://") and not url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


_global_engine: AsyncEngine | None = None
_global_session_factory: async_sessionmaker[AsyncSession] | None = None


def create_engine_instance(database_url: str | None = None) -> AsyncEngine:
    """Create a new async database engine instance with dual SQLite & PostgreSQL compatibility."""
    raw_url = database_url or get_settings().database_url
    url = normalize_database_url(raw_url)
    engine_kwargs: dict[str, Any] = {
        "echo": False,
        "future": True,
    }
    if "postgresql" in url or "asyncpg" in url:
        pool_size = 50
        max_overflow = 30
        pool_pre_ping = False
        pool_recycle = 1800
        if "testdb" in url:
            pool_size = 10
            max_overflow = 20
            pool_pre_ping = True
            pool_recycle = 3600
        engine_kwargs.update(
            {
                "pool_size": pool_size,
                "max_overflow": max_overflow,
                "pool_pre_ping": pool_pre_ping,
                "pool_recycle": pool_recycle,
                "pool_timeout": 30,
            }
        )
    elif "sqlite" in url:
        engine_kwargs["connect_args"] = {"check_same_thread": False}

    return create_async_engine(url, **engine_kwargs)


def get_engine(database_url: str | None = None) -> AsyncEngine:
    """Get or create singleton async database engine."""
    global _global_engine
    if database_url is not None:
        return create_engine_instance(database_url)
    if _global_engine is None:
        _global_engine = create_engine_instance()
    return _global_engine


def get_session_factory(
    engine: AsyncEngine | None = None,
) -> async_sessionmaker[AsyncSession]:
    """Create or return cached async session factory."""
    global _global_session_factory
    if engine is not None:
        return async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
    if _global_session_factory is None:
        eng = get_engine()
        _global_session_factory = async_sessionmaker(
            eng,
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _global_session_factory


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for FastAPI to get a database session."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db(engine: AsyncEngine | None = None) -> None:
    """Create all database tables and perform lightweight schema updates."""
    eng = engine if engine is not None else get_engine()
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        def _migrate_schema(connection: Connection) -> None:
            try:
                inspector = inspect(connection)
                existing_tables = set(inspector.get_table_names())

                # Seed default tenant
                if "tenants" in existing_tables:
                    try:
                        connection.execute(
                            text(
                                "INSERT INTO tenants (id, name, slug, status, subscription_tier, created_at, updated_at) "
                                "VALUES ('default-system-tenant', 'Hệ Thống Mặc Định', 'default', 'active', 'enterprise', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) "
                                "ON CONFLICT (id) DO NOTHING"
                            )
                        )
                    except Exception:
                        pass

                # Migrate tenant_id on all multi-tenant tables
                tenant_tables = [
                    "admin_users",
                    "categories",
                    "products",
                    "customers",
                    "conversations",
                    "messages",
                    "orders",
                    "quick_replies",
                    "broadcast_campaigns",
                    "broadcast_recipients",
                    "system_settings",
                    "knowledge_items",
                ]
                for tbl in tenant_tables:
                    if tbl in existing_tables:
                        cols = {c["name"] for c in inspector.get_columns(tbl)}
                        if "tenant_id" not in cols:
                            connection.execute(
                                text(
                                    f"ALTER TABLE {tbl} ADD COLUMN tenant_id VARCHAR(36) DEFAULT 'default-system-tenant'"
                                )
                            )

                # Migrate admin_users columns
                if "admin_users" in existing_tables:
                    au_cols = {c["name"] for c in inspector.get_columns("admin_users")}
                    if "is_superadmin" not in au_cols:
                        connection.execute(
                            text("ALTER TABLE admin_users ADD COLUMN is_superadmin BOOLEAN DEFAULT FALSE")
                        )
                    if "email" not in au_cols:
                        connection.execute(
                            text("ALTER TABLE admin_users ADD COLUMN email VARCHAR(255)")
                        )
                    if "phone" not in au_cols:
                        connection.execute(
                            text("ALTER TABLE admin_users ADD COLUMN phone VARCHAR(50)")
                        )
                    if "created_by_id" not in au_cols:
                        connection.execute(
                            text("ALTER TABLE admin_users ADD COLUMN created_by_id INTEGER")
                        )

                # Migrate orders shipping columns
                if "orders" in existing_tables:
                    o_cols = {c["name"] for c in inspector.get_columns("orders")}
                    order_shipping_fields = [
                        ("recipient_name", "VARCHAR(200)"),
                        ("recipient_phone", "VARCHAR(50)"),
                        ("shipping_address", "VARCHAR(500)"),
                        ("province", "VARCHAR(100)"),
                        ("district", "VARCHAR(100)"),
                        ("ward", "VARCHAR(100)"),
                        ("weight_grams", "INTEGER DEFAULT 500"),
                        ("cod_amount", "FLOAT DEFAULT 0.0"),
                        ("carrier", "VARCHAR(50)"),
                        ("tracking_code", "VARCHAR(100)"),
                        ("shipping_fee", "FLOAT DEFAULT 0.0"),
                        ("carrier_status_text", "VARCHAR(200)"),
                    ]
                    for col_name, col_type in order_shipping_fields:
                        if col_name not in o_cols:
                            connection.execute(
                                text(f"ALTER TABLE orders ADD COLUMN {col_name} {col_type}")
                            )

                # Migrate conversations table
                if "conversations" in existing_tables:
                    cols = {c["name"] for c in inspector.get_columns("conversations")}
                    if "is_bot_active" not in cols:
                        connection.execute(
                            text(
                                "ALTER TABLE conversations ADD COLUMN is_bot_active BOOLEAN DEFAULT TRUE"
                            )
                        )

                # Migrate customers table
                if "customers" in existing_tables:
                    c_cols = {c["name"] for c in inspector.get_columns("customers")}
                    if "funnel_stage" not in c_cols:
                        connection.execute(
                            text(
                                "ALTER TABLE customers ADD COLUMN funnel_stage VARCHAR(50) DEFAULT 'lead'"
                            )
                        )
                    if "notes" not in c_cols:
                        connection.execute(
                            text("ALTER TABLE customers ADD COLUMN notes VARCHAR(1000)")
                        )
                    if "address" not in c_cols:
                        connection.execute(
                            text("ALTER TABLE customers ADD COLUMN address VARCHAR(500)")
                        )

                # Migrate products table
                if "products" in existing_tables:
                    p_cols = {c["name"] for c in inspector.get_columns("products")}
                    if "is_active" not in p_cols:
                        connection.execute(
                            text("ALTER TABLE products ADD COLUMN is_active BOOLEAN DEFAULT TRUE")
                        )

                # Migrate performance indexes
                try:
                    connection.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS ix_messages_platform_message_id ON messages (platform_message_id)"
                        )
                    )
                    connection.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS ix_conversations_customer_status ON conversations (customer_id, status)"
                        )
                    )
                    connection.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS ix_messages_conversation_id ON messages (conversation_id)"
                        )
                    )
                except Exception:
                    pass

                # Seed system_settings defaults using ON CONFLICT DO NOTHING
                app_cfg = get_settings()
                default_settings = [
                    # general
                    ("shop_name", "AI Fashion & Retail Shop", "Tên cửa hàng", False, "general"),
                    ("shop_hotline", "0988888888", "Hotline hỗ trợ khách hàng", False, "general"),
                    ("shop_address", "Hà Nội, Việt Nam", "Địa chỉ cửa hàng", False, "general"),
                    (
                        "public_base_url",
                        "https://your-domain.com",
                        "Public Webhook URL (ngrok hoặc domain)",
                        False,
                        "general",
                    ),
                    # channels
                    (
                        "facebook_page_id",
                        getattr(app_cfg, "facebook_page_id", "") or "",
                        "Facebook Page ID",
                        False,
                        "channels",
                    ),
                    ("facebook_page_name", "", "Tên Facebook Fanpage", False, "channels"),
                    (
                        "facebook_page_access_token",
                        getattr(app_cfg, "facebook_page_access_token", "") or "",
                        "Page Access Token",
                        True,
                        "channels",
                    ),
                    (
                        "facebook_app_secret",
                        getattr(app_cfg, "facebook_app_secret", "") or "",
                        "Facebook App Secret",
                        True,
                        "channels",
                    ),
                    (
                        "facebook_verify_token",
                        getattr(app_cfg, "facebook_verify_token", "") or "my_fb_token_123",
                        "Facebook Webhook Verify Token",
                        False,
                        "channels",
                    ),
                    # payment
                    (
                        "vietqr_bank_code",
                        "TCB",
                        "Mã ngân hàng VietQR (VD: TCB, VCB, MB)",
                        False,
                        "payment",
                    ),
                    (
                        "vietqr_account_number",
                        "19036588999018",
                        "Số tài khoản ngân hàng thụ hưởng",
                        False,
                        "payment",
                    ),
                    (
                        "vietqr_account_name",
                        "NGUYEN VAN SHOP",
                        "Tên chủ tài khoản thụ hưởng",
                        False,
                        "payment",
                    ),
                    # ai
                    (
                        "default_llm_provider",
                        getattr(app_cfg, "default_llm_provider", "") or "gemini",
                        "Mô hình LLM mặc định (gemini, openai, anthropic)",
                        False,
                        "ai",
                    ),
                    (
                        "gemini_api_key",
                        getattr(app_cfg, "gemini_api_key", "") or "",
                        "Google Gemini API Key",
                        True,
                        "ai",
                    ),
                    (
                        "openai_api_key",
                        getattr(app_cfg, "openai_api_key", "") or "",
                        "OpenAI API Key",
                        True,
                        "ai",
                    ),
                    (
                        "anthropic_api_key",
                        getattr(app_cfg, "anthropic_api_key", "") or "",
                        "Anthropic Claude API Key",
                        True,
                        "ai",
                    ),
                ]
                for key, val, desc, is_sec, cat in default_settings:
                    connection.execute(
                        text(
                            "INSERT INTO system_settings (key, value, description, is_secret, category, updated_at) "
                            "VALUES (:key, :val, :desc, :is_sec, :cat, CURRENT_TIMESTAMP) "
                            "ON CONFLICT (key) DO NOTHING"
                        ),
                        {
                            "key": key,
                            "val": str(val),
                            "desc": desc,
                            "is_sec": is_sec,
                            "cat": cat.upper(),
                        },
                    )
                connection.execute(
                    text(
                        "UPDATE system_settings SET category = UPPER(category) WHERE category IS NOT NULL"
                    )
                )

                # Seed default admin user
                try:
                    from app.core.auth import hash_password as _hash_pw

                    hashed = _hash_pw(app_cfg.admin_default_password)
                    connection.execute(
                        text(
                            "INSERT INTO admin_users (username, hashed_password, display_name, role, is_active, is_superadmin, tenant_id, created_at) "
                            "VALUES (:username, :hashed_pw, :display_name, :role, TRUE, TRUE, 'default-system-tenant', CURRENT_TIMESTAMP) "
                            "ON CONFLICT (username) DO NOTHING"
                        ),
                        {
                            "username": app_cfg.admin_default_username,
                            "hashed_pw": hashed,
                            "display_name": "Administrator",
                            "role": "admin",
                        },
                    )
                except Exception:
                    pass

                # Seed default quick replies
                try:
                    default_quick_replies = [
                        (
                            "Lời chào khách hàng",
                            "/chao",
                            "Dạ shop chào bạn ạ! Shop có thể tư vấn mẫu sản phẩm hoặc chọn size giúp bạn nhé!",
                            "greeting",
                        ),
                        (
                            "Tài khoản VietQR",
                            "/bank",
                            "Dạ shop gửi bạn thông tin chuyển khoản VietQR. Bạn quét mã QR để chuyển khoản nhanh và chuẩn xác nhất ạ!",
                            "payment",
                        ),
                        (
                            "Chính sách freeship",
                            "/freeship",
                            "Dạ đơn hàng từ 500.000đ shop sẽ được miễn phí vận chuyển toàn quốc bạn nhé!",
                            "shipping",
                        ),
                        (
                            "Chính sách đổi trả",
                            "/doitra",
                            "Dạ shop hỗ trợ đổi size hoặc đổi mẫu trong vòng 7 ngày kể từ khi nhận hàng nếu còn nguyên tem mác bạn nhé!",
                            "policy",
                        ),
                    ]
                    for qr_title, qr_shortcut, qr_content, qr_cat in default_quick_replies:
                        connection.execute(
                            text(
                                "INSERT INTO quick_replies (title, shortcut, content, category, created_at, updated_at) "
                                "VALUES (:title, :shortcut, :content, :cat, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) "
                                "ON CONFLICT (shortcut) DO NOTHING"
                            ),
                            {
                                "title": qr_title,
                                "shortcut": qr_shortcut,
                                "content": qr_content,
                                "cat": qr_cat,
                            },
                        )
                except Exception:
                    pass
            except Exception:
                pass

        await conn.run_sync(_migrate_schema)


async def close_db(engine: AsyncEngine | None = None) -> None:
    """Dispose database engine and reset singletons."""
    global _global_engine, _global_session_factory
    if engine is not None:
        await engine.dispose()
        if engine is _global_engine:
            _global_engine = None
            _global_session_factory = None
    elif _global_engine is not None:
        await _global_engine.dispose()
        _global_engine = None
        _global_session_factory = None

"""Multi-tenant schema migration adding tenants table and tenant_id isolation.

Revision ID: 002
Revises: 001
Create Date: 2026-09-07 00:00:00.000000

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MULTI_TENANT_TABLES: list[str] = [
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


def upgrade() -> None:
    # 1. Create tenants table
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("subscription_tier", sa.String(length=20), nullable=False, server_default="trial"),
        sa.Column("subscription_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("custom_api_key_gemini", sa.String(length=255), nullable=True),
        sa.Column("custom_api_key_openai", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tenants_slug", "tenants", ["slug"], unique=True)

    # 2. Seed default system tenant
    op.execute(
        sa.text(
            "INSERT INTO tenants (id, name, slug, status, subscription_tier, created_at, updated_at) "
            "VALUES ('default-system-tenant', 'Hệ Thống Mặc Định', 'default', 'active', 'enterprise', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
    )

    # 3. Add is_superadmin to admin_users
    op.add_column(
        "admin_users",
        sa.Column("is_superadmin", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute(
        sa.text("UPDATE admin_users SET is_superadmin = TRUE WHERE username = 'admin'")
    )

    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"

    # 4. Add tenant_id to all multi-tenant tables
    for tbl in MULTI_TENANT_TABLES:
        op.add_column(
            tbl,
            sa.Column(
                "tenant_id",
                sa.String(length=36),
                nullable=False,
                server_default="default-system-tenant",
            ),
        )
        op.create_index(f"ix_{tbl}_tenant_id", tbl, ["tenant_id"])
        if not is_sqlite:
            op.create_foreign_key(
                f"fk_{tbl}_tenant_id_tenants",
                tbl,
                "tenants",
                ["tenant_id"],
                ["id"],
                ondelete="CASCADE",
            )


def downgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"

    for tbl in reversed(MULTI_TENANT_TABLES):
        if not is_sqlite:
            op.drop_constraint(f"fk_{tbl}_tenant_id_tenants", tbl, type_="foreignkey")
        op.drop_index(f"ix_{tbl}_tenant_id", table_name=tbl)
        op.drop_column(tbl, "tenant_id")

    op.drop_column("admin_users", "is_superadmin")
    op.drop_index("ix_tenants_slug", table_name="tenants")
    op.drop_table("tenants")


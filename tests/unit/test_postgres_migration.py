"""Unit tests for SQLite to PostgreSQL migration transformers and utilities."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import JSON, Boolean, Column, DateTime, Integer, MetaData, String, Table

from scripts.migrate_sqlite_to_postgres import (
    TOPOLOGICAL_TABLES,
    transform_boolean,
    transform_datetime,
    transform_json,
    transform_row,
)


def test_transform_boolean():
    """Verify robust conversion of heterogeneous SQLite boolean representations."""
    # Integers
    assert transform_boolean(1) is True
    assert transform_boolean(0) is False
    assert transform_boolean(2) is True

    # Strings
    assert transform_boolean("true") is True
    assert transform_boolean("True") is True
    assert transform_boolean("1") is True
    assert transform_boolean("yes") is True
    assert transform_boolean("false") is False
    assert transform_boolean("0") is False
    assert transform_boolean("no") is False
    assert transform_boolean("") is False

    # None and native bool
    assert transform_boolean(None) is None
    assert transform_boolean(True) is True
    assert transform_boolean(False) is False


def test_transform_datetime():
    """Verify UTC normalization and parsing for datetime strings and timestamps."""
    # None and empty
    assert transform_datetime(None) is None
    assert transform_datetime("") is None

    # Native naive datetime -> UTC aware
    dt_naive = datetime(2026, 9, 6, 12, 0, 0)
    res_dt = transform_datetime(dt_naive)
    assert res_dt.tzinfo == timezone.utc
    assert res_dt.hour == 12

    # ISO string with UTC Z
    iso_str = "2026-09-06T12:00:00Z"
    res_iso = transform_datetime(iso_str)
    assert res_iso is not None
    assert res_iso.year == 2026
    assert res_iso.tzinfo == timezone.utc

    # Standard SQLite string format: YYYY-MM-DD HH:MM:SS
    sqlite_str = "2026-09-06 05:30:15"
    res_sqlite = transform_datetime(sqlite_str)
    assert res_sqlite is not None
    assert res_sqlite.second == 15
    assert res_sqlite.tzinfo == timezone.utc

    # Unix timestamp
    ts = 1700000000
    res_ts = transform_datetime(ts)
    assert res_ts is not None
    assert res_ts.tzinfo == timezone.utc


def test_transform_json():
    """Verify deserialization of JSON strings and preservation of objects."""
    assert transform_json(None) is None
    assert transform_json({"a": 1}) == {"a": 1}
    assert transform_json([1, 2, 3]) == [1, 2, 3]

    # Valid JSON string
    json_str = '{"key": "value", "list": [10, 20]}'
    parsed = transform_json(json_str)
    assert parsed == {"key": "value", "list": [10, 20]}

    # Primitive string JSON
    assert transform_json('"hello"') == "hello"

    # Non-JSON string falls back to raw string
    assert transform_json("plain text") == "plain text"


def test_transform_row_with_target_table():
    """Verify transform_row applies correct transformers based on target SQLAlchemy Table schema."""
    metadata = MetaData()
    sample_table = Table(
        "sample",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("is_active", Boolean),
        Column("created_at", DateTime),
        Column("metadata_json", JSON),
        Column("title", String),
    )

    raw_row = {
        "id": 1,
        "is_active": "1",
        "created_at": "2026-09-06 10:00:00",
        "metadata_json": '{"source": "test"}',
        "title": "Sample Title",
    }

    cleaned = transform_row(raw_row, sample_table)
    assert cleaned["id"] == 1
    assert cleaned["is_active"] is True
    assert isinstance(cleaned["created_at"], datetime)
    assert cleaned["created_at"].tzinfo == timezone.utc
    assert cleaned["metadata_json"] == {"source": "test"}
    assert cleaned["title"] == "Sample Title"


def test_topological_table_ordering():
    """Verify topological table ordering preserves dependencies."""
    assert "admin_users" in TOPOLOGICAL_TABLES
    assert "categories" in TOPOLOGICAL_TABLES
    assert "products" in TOPOLOGICAL_TABLES
    assert "customers" in TOPOLOGICAL_TABLES
    assert "conversations" in TOPOLOGICAL_TABLES
    assert "messages" in TOPOLOGICAL_TABLES
    assert "orders" in TOPOLOGICAL_TABLES
    assert "broadcast_campaigns" in TOPOLOGICAL_TABLES
    assert "broadcast_recipients" in TOPOLOGICAL_TABLES

    # Parents must come before children
    assert TOPOLOGICAL_TABLES.index("categories") < TOPOLOGICAL_TABLES.index("products")
    assert TOPOLOGICAL_TABLES.index("customers") < TOPOLOGICAL_TABLES.index("conversations")
    assert TOPOLOGICAL_TABLES.index("conversations") < TOPOLOGICAL_TABLES.index("messages")
    assert TOPOLOGICAL_TABLES.index("customers") < TOPOLOGICAL_TABLES.index("orders")
    assert TOPOLOGICAL_TABLES.index("broadcast_campaigns") < TOPOLOGICAL_TABLES.index(
        "broadcast_recipients"
    )


@pytest.mark.asyncio
async def test_migrate_data_end_to_end(tmp_path):
    """Verify live migrate_data reads chatbot.db and migrates 100% of records into target."""
    from scripts.migrate_sqlite_to_postgres import PROJECT_ROOT, migrate_data

    source_db = PROJECT_ROOT / "data" / "chatbot.db"
    if not source_db.exists():
        pytest.skip("Source chatbot.db does not exist")

    target_db_path = tmp_path / "target_test.db"
    target_url = f"sqlite+aiosqlite:///{target_db_path.as_posix()}"

    report = await migrate_data(source_db, target_url)

    assert report["status"] == "success"
    assert report["total_records_migrated"] > 0
    # Every table present in SQLite source must match exactly in target
    for tbl, counts in report["migrated_tables"].items():
        assert counts["target"] == counts["source"], f"Count mismatch for {tbl}"


def test_alembic_baseline_upgrade_matches_metadata(tmp_path):
    """Verify Alembic migration 001 upgrades cleanly and reflects all models."""
    import sqlite3

    from alembic.config import Config

    import app.models  # noqa: F401
    from alembic import command
    from app.database.session import Base

    alembic_db = tmp_path / "alembic_check.db"
    alembic_url = f"sqlite+aiosqlite:///{alembic_db.as_posix()}"

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", alembic_url)
    command.upgrade(cfg, "head")

    # Connect to the created SQLite database and inspect table columns
    conn = sqlite3.connect(str(alembic_db))
    cursor = conn.cursor()
    tables_in_db = {
        row[0]
        for row in cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name != 'alembic_version'"
        ).fetchall()
    }

    # Verify all SQLAlchemy models exist in migrated schema
    expected_tables = set(Base.metadata.tables.keys())
    assert expected_tables.issubset(tables_in_db)

    # Verify columns for key models
    for table_name, table_obj in Base.metadata.tables.items():
        cursor.execute(f"PRAGMA table_info({table_name})")
        db_cols = {row[1] for row in cursor.fetchall()}
        model_cols = {col.name for col in table_obj.columns}
        assert model_cols.issubset(db_cols), f"Missing columns in table {table_name}: {model_cols - db_cols}"

    conn.close()

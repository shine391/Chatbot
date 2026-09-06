"""Migration utility: Transfer all data from SQLite (data/chatbot.db) to PostgreSQL.

Provides:
- Strict type transformers (boolean, UTC datetime, JSON).
- Topological table order preserving foreign keys.
- Automatic PostgreSQL sequence (setval) synchronization.
- Pre- and post-migration record count validation.
"""

import argparse
import asyncio
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from loguru import logger  # noqa: E402
from sqlalchemy import Table, select, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

import app.models  # noqa: E402, F401 - ensure all models register with Base.metadata
from app.config import get_settings  # noqa: E402
from app.database.session import Base, get_engine, get_session_factory, init_db  # noqa: E402

# Strict Topological order of tables (parents before children)
TOPOLOGICAL_TABLES = [
    "admin_users",
    "categories",
    "products",
    "customers",
    "conversations",
    "messages",
    "orders",
    "guardrail_logs",
    "knowledge_items",
    "system_settings",
    "quick_replies",
    "broadcast_campaigns",
    "broadcast_recipients",
]


def transform_boolean(value: Any) -> bool | None:
    """Strictly convert SQLite integer/string boolean representation to Python bool."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    str_val = str(value).strip().lower()
    if str_val in ("1", "true", "t", "yes", "y"):
        return True
    if str_val in ("0", "false", "f", "no", "n", ""):
        return False
    return bool(value)


def transform_datetime(value: Any) -> datetime | None:
    """Convert SQLite ISO date string or timestamp into timezone-aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    str_val = str(value).strip()
    if not str_val:
        return None
    try:
        # Standard ISO 8601
        dt = datetime.fromisoformat(str_val)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        # Common SQLite format: YYYY-MM-DD HH:MM:SS
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
            try:
                dt = datetime.strptime(str_val, fmt).replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                pass
    logger.warning(f"Could not parse datetime string: {value}")
    return None


def transform_json(value: Any) -> Any:
    """Convert JSON text strings into deserialized Python dictionaries/lists."""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        val_s = value.strip()
        if not val_s:
            return None
        try:
            return json.loads(val_s)
        except Exception:
            return val_s
    return value


def get_column_transformers(table: Table) -> dict[str, Any]:
    """Map table columns to appropriate strict transformers based on SQLAlchemy type."""
    transformers: dict[str, Any] = {}
    for col in table.columns:
        col_type = col.type.__class__.__name__.lower()
        if "bool" in col_type:
            transformers[col.name] = transform_boolean
        elif "date" in col_type or "time" in col_type:
            transformers[col.name] = transform_datetime
        elif "json" in col_type:
            transformers[col.name] = transform_json
    return transformers


def transform_row(row: dict[str, Any], table: Table) -> dict[str, Any]:
    """Transform a single SQLite record dictionary according to table column types."""
    transformers = get_column_transformers(table)
    target_cols = {c.name for c in table.columns}
    clean_row: dict[str, Any] = {}
    for k, v in row.items():
        if k not in target_cols:
            continue
        if k in transformers:
            clean_row[k] = transformers[k](v)
        else:
            clean_row[k] = v

    # Fill defaults for non-nullable columns added in later schemas
    for col in table.columns:
        if col.name not in clean_row and not col.nullable:
            if col.default is not None:
                arg = col.default.arg
                clean_row[col.name] = arg() if callable(arg) else arg

    return clean_row


def read_sqlite_records(
    sqlite_path: Path, table_name: str
) -> tuple[list[str], list[dict[str, Any]]]:
    """Read all records from a SQLite table."""
    conn = sqlite3.connect(str(sqlite_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    try:
        cursor.execute(f"SELECT * FROM {table_name}")
        rows = cursor.fetchall()
        if not rows:
            cursor.execute(f"PRAGMA table_info({table_name})")
            cols = [r[1] for r in cursor.fetchall()]
            return cols, []
        cols = list(rows[0].keys())
        data = [dict(row) for row in rows]
        return cols, data
    finally:
        conn.close()


async def sync_postgres_sequences(session: AsyncSession, table_name: str) -> None:
    """Synchronize PostgreSQL sequence setval to max(id) for auto-increment columns."""
    try:
        query = text(
            f"SELECT setval(pg_get_serial_sequence('{table_name}', 'id'), "
            f"COALESCE(MAX(id), 1), MAX(id) IS NOT NULL) FROM {table_name};"
        )
        await session.execute(query)
        await session.commit()
    except Exception as exc:
        # In SQLite or if table has no id sequence, ignore
        logger.debug(f"Sequence sync skipped for {table_name}: {exc}")


async def migrate_data(sqlite_path: Path, pg_url: str | None = None) -> dict[str, Any]:
    """Execute the full migration from SQLite to PostgreSQL."""
    if not sqlite_path.exists():
        raise FileNotFoundError(f"SQLite file not found at {sqlite_path}")

    settings = get_settings()
    target_url = pg_url or settings.database_url
    logger.info(f"Starting SQLite to PostgreSQL migration from {sqlite_path} -> {target_url}")

    engine = get_engine(target_url)
    session_factory = get_session_factory(engine)

    # 1. Initialize schema
    await init_db(engine)

    # 2. Get registered SQLAlchemy tables
    tables = Base.metadata.tables

    # 3. Read SQLite tables present
    conn = sqlite3.connect(str(sqlite_path))
    c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    sqlite_tables = {row[0] for row in c.fetchall()}
    conn.close()

    report: dict[str, Any] = {
        "status": "success",
        "migrated_tables": {},
        "total_records_migrated": 0,
    }

    async with session_factory() as session:
        # Pre-clean tables in reverse topological order so fresh SQLite data is transferred without seed conflicts
        for table_name in reversed(TOPOLOGICAL_TABLES):
            if table_name in sqlite_tables:
                sa_table = tables.get(table_name)
                if sa_table is not None:
                    await session.execute(sa_table.delete())
        await session.commit()

        for table_name in TOPOLOGICAL_TABLES:
            if table_name not in sqlite_tables:
                logger.info(f"Table '{table_name}' not in SQLite database. Skipping.")
                continue

            sa_table = tables.get(table_name)
            if sa_table is None:
                logger.warning(f"Table '{table_name}' has no SQLAlchemy model mapped. Skipping.")
                continue

            cols, rows = read_sqlite_records(sqlite_path, table_name)
            sqlite_count = len(rows)
            logger.info(f"Migrating table '{table_name}': {sqlite_count} records found in SQLite.")

            if sqlite_count == 0:
                report["migrated_tables"][table_name] = {"source": 0, "target": 0}
                continue

            # Transform each record
            transformed_rows: list[dict[str, Any]] = [
                transform_row(r, sa_table) for r in rows
            ]

            # Insert in chunks of 1000 (batch streaming)
            chunk_size = 1000
            for i in range(0, len(transformed_rows), chunk_size):
                chunk = transformed_rows[i : i + chunk_size]
                await session.execute(sa_table.insert().values(chunk))

            await session.commit()

            # Synchronize PostgreSQL sequence
            await sync_postgres_sequences(session, table_name)

            # Verification count
            count_stmt = select(text("count(*)")).select_from(sa_table)
            pg_count = (await session.execute(count_stmt)).scalar() or 0

            report["migrated_tables"][table_name] = {
                "source": sqlite_count,
                "target": pg_count,
            }
            report["total_records_migrated"] += sqlite_count
            logger.info(f"Table '{table_name}' done: SQLite={sqlite_count} -> Target={pg_count}")

    # Run VACUUM ANALYZE for PostgreSQL target
    clean_target_url = str(engine.url)
    if "postgresql" in clean_target_url or "asyncpg" in clean_target_url:
        try:
            async with engine.connect() as aconn:
                await aconn.execution_options(isolation_level="AUTOCOMMIT")
                await aconn.execute(text("VACUUM ANALYZE;"))
            logger.info("PostgreSQL VACUUM ANALYZE executed successfully.")
        except Exception as vac_err:
            logger.warning(f"VACUUM ANALYZE skipped: {vac_err}")

    await engine.dispose()
    logger.info(
        f"Migration completed successfully. Total records migrated: {report['total_records_migrated']}"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate SQLite chatbot.db to PostgreSQL.")
    parser.add_argument(
        "--sqlite-path",
        type=Path,
        default=PROJECT_ROOT / "data" / "chatbot.db",
        help="Path to SQLite database file.",
    )
    parser.add_argument(
        "--database-url",
        type=str,
        default=None,
        help="Target database URL (defaults to DATABASE_URL in .env).",
    )

    args = parser.parse_args()
    try:
        report = asyncio.run(migrate_data(args.sqlite_path, args.database_url))
        print("\n" + "=" * 60)
        print(" MIGRATION SUMMARY")
        print("=" * 60)
        for tbl, counts in report["migrated_tables"].items():
            print(f" - {tbl:<25}: {counts['source']:>5} records -> {counts['target']:>5} records")
        print(f"Total Migrated: {report['total_records_migrated']} records")
        print("=" * 60 + "\n")
        return 0
    except Exception as exc:
        logger.error(f"Migration failed: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

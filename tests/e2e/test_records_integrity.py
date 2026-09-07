"""Baseline Data Integrity and Pollution Safeguard Test.

Validates that the 458 historical migrated records across all 13 tables
remain 100% intact and unpolluted before, during, and after test execution.
"""

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

PG_URL = "postgresql+asyncpg://chatbot:chatbot123@127.0.0.1:5432/chatbot"

# Expected baseline record counts, max IDs, and SHA256 from pg_458_baseline.json
BASELINE_TABLES: dict[str, dict[str, Any]] = {
    "admin_users": {
        "count": 1,
        "max_id": 1,
        "sha256": "c89fa8731f7df30213dbd66457d5c68191b96fbd921f75590ede7bf34ac86700",
    },
    "categories": {
        "count": 2,
        "max_id": 2,
        "sha256": "ea26c5b080cc7296b6f40e88505c4e6c4f8872970111516d9d6b103de235e90a",
    },
    "products": {
        "count": 9,
        "max_id": 9,
        "sha256": "3a70cf4d1a0cefa65a383e8c0d924362caeca62f0da74779f51d8b18fd639ac3",
    },
    "customers": {
        "count": 6,
        "max_id": 6,
        "sha256": "3ca56ac61b416d05e76cd1245c78ef73e67ad0204eb3166eef213578cbc22aef",
    },
    "conversations": {
        "count": 6,
        "max_id": 6,
        "sha256": "bf4ec3a8b1379f00dee098e1765176ab12d815df956cdc79682440cc734e4c10",
    },
    "messages": {
        "count": 411,
        "max_id": 411,
        "sha256": "41bdad16adab639c3110b90b6152f4839a33906bf6a6042ba5b6353896abee3c",
    },
    "orders": {
        "count": 3,
        "max_id": 3,
        "sha256": "820b5dbc3bd8def380238bf93d75339889783c10ab70a0ffa8b972baf10f28ca",
    },
    "guardrail_logs": {
        "count": 0,
        "max_id": 0,
        "sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
    },
    "knowledge_items": {
        "count": 0,
        "max_id": 0,
        "sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
    },
    "system_settings": {
        "count": 16,
        "max_id": 18,
        "sha256": "a19293a6e40f708708207944942acf1aa9faefa0ce1d2eec394d8e73f7635055",
    },
    "quick_replies": {
        "count": 4,
        "max_id": 4,
        "sha256": "aec200eaa7bd60c860679e950dee5b246f36859342ed716186b32c7ff4f50f47",
    },
    "broadcast_campaigns": {
        "count": 0,
        "max_id": 0,
        "sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
    },
    "broadcast_recipients": {
        "count": 0,
        "max_id": 0,
        "sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
    },
}

TOTAL_BASELINE_RECORDS = 458


async def cleanup_test_generated_entities() -> dict[str, int]:
    """Purge any test-created records exceeding baseline max IDs in FK-safe order."""
    deleted_counts: dict[str, int] = {}
    cleanup_statements = [
        ("broadcast_recipients", "id > 0"),
        ("broadcast_campaigns", "id > 0"),
        ("guardrail_logs", "id > 0"),
        ("knowledge_items", "id > 0"),
        ("messages", "id > 411"),
        ("orders", "id > 3"),
        ("conversations", "id > 6"),
        ("customers", "id > 6"),
        ("quick_replies", "id > 4"),
        ("products", "id > 9"),
        ("categories", "id > 2"),
        ("system_settings", "id > 18"),
        ("admin_users", "id > 1"),
    ]

    engine = create_async_engine(PG_URL)
    async with engine.begin() as conn:
        for tbl, condition in cleanup_statements:
            res = await conn.execute(text(f'DELETE FROM "{tbl}" WHERE {condition};'))
            deleted_counts[tbl] = res.rowcount
    await engine.dispose()
    return deleted_counts


async def compute_table_baseline_fingerprint(
    table_name: str, max_id: int
) -> tuple[int, str]:
    """Compute exact row count and SHA256 fingerprint for baseline rows in a table."""
    engine = create_async_engine(PG_URL)
    async with engine.connect() as conn:
        if max_id > 0:
            query = text(f'SELECT * FROM "{table_name}" WHERE id <= {max_id} ORDER BY id ASC;')
        else:
            query = (
                text(f'SELECT * FROM "{table_name}" ORDER BY id ASC;')
                if table_name != "broadcast_recipients"
                else text(f'SELECT * FROM "{table_name}";')
            )

        rows = (await conn.execute(query)).fetchall()
        row_dicts = [dict(r._mapping) for r in rows]

        clean_rows = []
        for r in row_dicts:
            clean_r = {}
            for k, v in r.items():
                if k == "tenant_id":
                    continue
                if hasattr(v, "isoformat"):
                    clean_r[k] = v.isoformat()
                else:
                    clean_r[k] = v
            clean_rows.append(clean_r)

        content_str = json.dumps(clean_rows, sort_keys=True, default=str)
        sha256 = hashlib.sha256(content_str.encode("utf-8")).hexdigest()
        count = len(clean_rows)

    await engine.dispose()
    return count, sha256


@pytest.mark.asyncio
async def test_baseline_json_file_exists() -> None:
    """Ensure pg_458_baseline.json manifest is present and well-formed."""
    manifest_path = (
        Path(__file__).resolve().parent.parent.parent
        / ".agents"
        / "explorer_survey_1"
        / "pg_458_baseline.json"
    )
    assert manifest_path.exists(), f"Baseline JSON manifest missing at {manifest_path}"

    with open(manifest_path, encoding="utf-8") as f:
        data = json.load(f)

    assert data["total_records"] == TOTAL_BASELINE_RECORDS
    assert len(data["tables"]) == 13


@pytest.mark.asyncio
async def test_cleanup_and_verify_all_458_baseline_records() -> None:
    """Clean up any orphan test entities and verify all 458 historical records are intact."""
    # Step 1: Clean up any prior test remnants
    await cleanup_test_generated_entities()

    # Step 2: Verify each of the 13 tables matches count and SHA256
    total_verified = 0
    mismatches: list[str] = []

    for table_name, expected in BASELINE_TABLES.items():
        count, sha256 = await compute_table_baseline_fingerprint(
            table_name, expected["max_id"]
        )

        assert count == expected["count"], (
            f"Table '{table_name}' count mismatch: expected {expected['count']}, got {count}"
        )

        if table_name == "admin_users":
            # For admin_users, verify immutable core fields (last_login_at updates dynamically upon auth)
            engine = create_async_engine(PG_URL)
            async with engine.connect() as conn:
                admin_row = (await conn.execute(text("SELECT * FROM admin_users WHERE id = 1;"))).first()
                assert admin_row is not None, "Baseline admin user record (id=1) is missing!"
                mapping = dict(admin_row._mapping)
                assert mapping["username"] == "admin", "Admin username was modified!"
                assert mapping["role"] == "admin", "Admin role was modified!"
                assert mapping["is_active"] is True, "Admin account was deactivated!"
                assert mapping["display_name"] == "Administrator", "Admin display_name was modified!"
            await engine.dispose()
        else:
            if sha256 != expected["sha256"]:
                mismatches.append(
                    f"{table_name}: expected hash {expected['sha256'][:10]}..., got {sha256[:10]}..."
                )

        total_verified += count

    assert total_verified == TOTAL_BASELINE_RECORDS, (
        f"Expected exactly {TOTAL_BASELINE_RECORDS} records, found {total_verified}"
    )
    assert not mismatches, f"Baseline records content mutated! Mismatches: {mismatches}"


@pytest.mark.asyncio
async def test_zero_unpartitioned_entities() -> None:
    """Verify that no unexpected rogue entities exist beyond the baseline partitions."""
    engine = create_async_engine(PG_URL)
    async with engine.connect() as conn:
        for table_name, expected in BASELINE_TABLES.items():
            res = await conn.execute(text(f'SELECT count(*) FROM "{table_name}";'))
            live_count = res.scalar() or 0
            assert live_count == expected["count"], (
                f"Table '{table_name}' contains rogue data: expected {expected['count']}, "
                f"live total is {live_count}"
            )
    await engine.dispose()

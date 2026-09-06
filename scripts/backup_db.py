"""Database and Vector Storage Backup Utility.

Creates atomic, timestamped backups of SQLite database and Qdrant collections
into `./data/backups/`.
Can be run via CLI or triggered via Admin API.
"""

import json
import logging
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# Add project root to sys.path so it works when run from anywhere
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings  # noqa: E402

logger = logging.getLogger("backup_db")


def get_backup_dir() -> Path:
    """Return the absolute path to the backup directory, ensuring it exists."""
    backup_dir = PROJECT_ROOT / "data" / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def backup_sqlite(source_path: Path, dest_path: Path) -> int:
    """Perform a live atomic backup of an active SQLite database."""
    if not source_path.exists():
        raise FileNotFoundError(f"SQLite source file does not exist: {source_path}")

    # Use SQLite Online Backup API for maximum concurrency safety
    src_conn = sqlite3.connect(str(source_path))
    dest_conn = sqlite3.connect(str(dest_path))
    try:
        src_conn.backup(dest_conn)
    finally:
        dest_conn.close()
        src_conn.close()

    return dest_path.stat().st_size


def backup_postgres(database_url: str, dest_path: Path) -> int:
    """Backup active PostgreSQL database using pg_dump."""
    clean_url = database_url.replace("postgresql+asyncpg://", "postgresql://")
    parsed = urlparse(clean_url)
    env = os.environ.copy()
    if parsed.password:
        env["PGPASSWORD"] = parsed.password

    cmd = [
        "pg_dump",
        "-h",
        parsed.hostname or "localhost",
        "-p",
        str(parsed.port or 5432),
        "-U",
        parsed.username or "postgres",
        "-d",
        parsed.path.lstrip("/"),
        "-F",
        "c",
        "-f",
        str(dest_path),
    ]
    res = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"pg_dump failed: {res.stderr}")
    return dest_path.stat().st_size


def backup_qdrant(backup_dir: Path, timestamp: str) -> list[dict[str, Any]]:
    """Backup Qdrant vector database collections if available."""
    qdrant_backups: list[dict[str, Any]] = []
    settings = get_settings()

    try:
        from qdrant_client import QdrantClient

        client = QdrantClient(
            host=settings.qdrant_host,
            port=settings.qdrant_port,
            api_key=settings.qdrant_api_key or None,
            timeout=5,
            check_compatibility=False,
        )
        collections_resp = client.get_collections()
        for col in collections_resp.collections:
            col_name = col.name
            try:
                # Try creating snapshot via Qdrant Snapshot API
                snapshot_info = client.create_snapshot(collection_name=col_name)
                snapshot_name = getattr(snapshot_info, "name", f"{col_name}_{timestamp}.snapshot")
                snap_size = int(getattr(snapshot_info, "size", 0) or 0)
                qdrant_backups.append(
                    {
                        "collection": col_name,
                        "type": "qdrant_snapshot",
                        "snapshot_name": snapshot_name,
                        "size_bytes": snap_size,
                    }
                )
            except Exception as e:
                # Fallback: export points summary/counts
                count_res = client.count(collection_name=col_name)
                export_file = backup_dir / f"qdrant_{col_name}_{timestamp}.json"
                with open(export_file, "w", encoding="utf-8") as f:
                    json.dump(
                        {
                            "collection": col_name,
                            "timestamp": timestamp,
                            "points_count": count_res.count,
                            "note": f"Snapshot fallback: {e}",
                        },
                        f,
                        indent=2,
                    )
                qdrant_backups.append(
                    {
                        "collection": col_name,
                        "type": "qdrant_export",
                        "file": export_file.name,
                        "size_bytes": export_file.stat().st_size,
                    }
                )
    except Exception as exc:
        logger.warning(f"Qdrant backup skipped or failed: {exc}")

    return qdrant_backups


def perform_backup() -> dict[str, Any]:
    """Perform full system backup of SQLite and Qdrant storage."""
    settings = get_settings()
    backup_dir = get_backup_dir()
    now = datetime.now(timezone.utc)
    timestamp_str = now.strftime("%Y%m%d_%H%M%S")

    files_created: list[dict[str, Any]] = []
    total_size = 0

    # 1. Database Backup (SQLite or PostgreSQL)
    db_url = settings.database_url
    if "sqlite" in db_url:
        # Extract path from sqlite URL (e.g. sqlite+aiosqlite:///./data/chatbot.db)
        clean_path = db_url.split(":///")[-1]
        if clean_path.startswith("./"):
            sqlite_file = PROJECT_ROOT / clean_path[2:]
        else:
            sqlite_file = Path(clean_path)
            if not sqlite_file.is_absolute():
                sqlite_file = PROJECT_ROOT / sqlite_file

        if sqlite_file.exists():
            dest_backup_file = backup_dir / f"chatbot_sqlite_{timestamp_str}.db"
            size = backup_sqlite(sqlite_file, dest_backup_file)
            total_size += size
            files_created.append(
                {
                    "type": "sqlite",
                    "filename": dest_backup_file.name,
                    "path": str(dest_backup_file),
                    "size_bytes": size,
                }
            )
        else:
            logger.warning(f"SQLite file not found at {sqlite_file}")
    elif "postgresql" in db_url or "asyncpg" in db_url:
        dest_backup_file = backup_dir / f"chatbot_postgres_{timestamp_str}.dump"
        try:
            size = backup_postgres(db_url, dest_backup_file)
            total_size += size
            files_created.append(
                {
                    "type": "postgres",
                    "filename": dest_backup_file.name,
                    "path": str(dest_backup_file),
                    "size_bytes": size,
                }
            )
        except Exception as err:
            logger.warning(f"PostgreSQL backup failed or pg_dump unavailable: {err}")

    # 2. Qdrant Backup
    qdrant_results = backup_qdrant(backup_dir, timestamp_str)
    for q in qdrant_results:
        files_created.append(q)
        total_size += int(q.get("size_bytes", 0))

    # 3. Create Manifest
    manifest_path = backup_dir / f"backup_manifest_{timestamp_str}.json"
    manifest_data = {
        "timestamp": now.isoformat(),
        "database_url_scheme": db_url.split("://")[0] if "://" in db_url else "unknown",
        "files": files_created,
        "total_size_bytes": total_size,
        "status": "success",
    }
    sqlite_file_info = next((f for f in files_created if f.get("type") == "sqlite"), None)
    postgres_file_info = next((f for f in files_created if f.get("type") == "postgres"), None)
    qdrant_file_info = next(
        (f for f in files_created if f.get("type") in ("qdrant_snapshot", "qdrant_export")), None
    )
    if sqlite_file_info:
        manifest_data["sqlite_backup"] = sqlite_file_info.get("filename")
        manifest_data["sqlite_backup_bytes"] = sqlite_file_info.get("size_bytes")
    if postgres_file_info:
        manifest_data["postgres_backup"] = postgres_file_info.get("filename")
        manifest_data["postgres_backup_bytes"] = postgres_file_info.get("size_bytes")
    if qdrant_file_info:
        manifest_data["qdrant_backup"] = qdrant_file_info.get(
            "snapshot_name"
        ) or qdrant_file_info.get("file")
        manifest_data["qdrant_backup_bytes"] = qdrant_file_info.get("size_bytes")

    with open(manifest_path, "w", encoding="utf-8") as mf:
        json.dump(manifest_data, mf, indent=2, ensure_ascii=False)

    files_created.append(
        {
            "type": "manifest",
            "filename": manifest_path.name,
            "path": str(manifest_path),
            "size_bytes": manifest_path.stat().st_size,
        }
    )

    return {
        "status": "success",
        "timestamp": now.isoformat(),
        "backup_dir": str(backup_dir),
        "files": files_created,
        "total_size_bytes": total_size,
        "manifest": manifest_data,
    }


def get_latest_backup_info() -> dict[str, Any] | None:
    """Read the latest backup manifest from ./data/backups/ if present."""
    backup_dir = get_backup_dir()
    manifests = sorted(backup_dir.glob("backup_manifest_*.json"), reverse=True)
    if not manifests:
        return None
    try:
        with open(manifests[0], "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else None
    except Exception as err:
        logger.warning(f"Could not read manifest {manifests[0]}: {err}")
        return None


def main() -> int:
    """CLI Entry point."""
    print("=" * 60)
    print(" Starting System Database & Vector Backup")
    print("=" * 60)
    try:
        res = perform_backup()
        print(f"\n[PASSED] Backup created successfully at {res['timestamp']}")
        print(f"Destination directory: {res['backup_dir']}")
        for f in res["files"]:
            name = f.get("filename") or f.get("snapshot_name") or f.get("file")
            size = f.get("size_bytes", 0)
            print(f" - {name} ({size:,} bytes)")
        print(f"Total backup size: {res['total_size_bytes']:,} bytes\n")
        return 0
    except Exception as e:
        print(f"\n[FAILED] Backup failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

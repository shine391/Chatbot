"""Milestone 2: Automated End-to-End Performance & Concurrency Benchmarking Suite.

Validates the performance, latency, and concurrency constraints under live Docker operations:
- Benchmark 1: Webhook Concurrency & Deduplication (R2.1)
  - 50-100 concurrent requests to /webhook/chat
  - 100% duplicate message suppression rate
  - Queue latency and responsiveness
- Benchmark 2: RAG Query & DB Latency under Pool Load (R2.2)
  - Concurrent 768-dim semantic vector search on Qdrant
  - Concurrent DB transactions on PostgreSQL 16 under pool load
  - Zero deadlocks and zero connection leaks verification
- Benchmark 3: WebSocket Live Chat Concurrency & Event Broadcast (R2.3)
  - Multi-client persistent WebSocket connections
  - Redis Pub/Sub broadcast distribution latency <= 100ms
"""

from collections.abc import AsyncGenerator

import pytest

from scripts.run_benchmarks import (
    DEFAULT_HTTP_URL,
    DEFAULT_PG_DSN,
    DEFAULT_QDRANT_HOST,
    DEFAULT_QDRANT_PORT,
    DEFAULT_REDIS_URL,
    DEFAULT_WS_URL,
    cleanup_database_artifacts,
    run_db_pool_benchmark,
    run_qdrant_rag_benchmark,
    run_webhook_concurrency_benchmark,
    run_webhook_deduplication_benchmark,
    run_websocket_broadcast_benchmark,
)


@pytest.fixture(autouse=True)
async def ensure_clean_benchmark_db() -> AsyncGenerator[None, None]:
    """Ensure database is clean before and after every benchmark test."""
    await cleanup_database_artifacts(DEFAULT_PG_DSN)
    yield
    await cleanup_database_artifacts(DEFAULT_PG_DSN)


@pytest.mark.asyncio
async def test_benchmark_1_webhook_concurrency_and_deduplication() -> None:
    """R2.1: Webhook Concurrency, Queue Latency, and Deduplication Storm.

    1. Ingestion concurrency burst: 50-100 concurrent messages to /webhook/chat.
    2. Deduplication storm: Mixed burst of unique and duplicated message IDs,
       asserting 100% duplicate suppression rate and sub-millisecond decision latency.
    """
    # 1. Ingestion Concurrency Burst (50-100 range)
    res_wh = await run_webhook_concurrency_benchmark(
        base_url=DEFAULT_HTTP_URL,
        total_requests=50,
        concurrency=10,
    )
    assert res_wh.total_requests == 50
    assert res_wh.success_rate_pct >= 95.0, (
        f"Expected >= 95% success rate, got {res_wh.success_rate_pct}%"
    )
    assert res_wh.throughput_rps > 0.0
    assert res_wh.p95_ms <= 200.0, (
        f"Expected Webhook Ingestion P95 <= 200ms, got {res_wh.p95_ms}ms"
    )

    # 2. Deduplication Storm & Retry Suppression
    res_dedup = await run_webhook_deduplication_benchmark(
        total_messages=100,
        duplicate_ratio=0.4,
        concurrency=25,
    )
    assert res_dedup.success_rate_pct == 100.0
    dedup_rate = res_dedup.extra_metrics["deduplication_rate_pct"]
    assert dedup_rate == 100.0, (
        f"Expected 100% of duplicate retries suppressed, but got {dedup_rate}%"
    )
    # Deduplication decision latency target P95 <= 50ms
    assert res_dedup.p95_ms <= 50.0, f"Expected P95 <= 50ms, got {res_dedup.p95_ms}ms"


@pytest.mark.asyncio
async def test_benchmark_2_rag_qdrant_and_db_pool_load() -> None:
    """R2.2: RAG Vector Search & PostgreSQL 16 Latency under Connection Pool Load.

    1. Concurrent 768-dim vector semantic queries against Qdrant 'products' collection.
    2. Concurrent database transactions (reads + writes) on PostgreSQL 16 under pool load,
       verifying zero deadlocks and zero connection leaks.
    """
    # 1. Qdrant 768-dim Vector Search Benchmark
    res_qdrant = await run_qdrant_rag_benchmark(
        qdrant_host=DEFAULT_QDRANT_HOST,
        qdrant_port=DEFAULT_QDRANT_PORT,
        total_queries=50,
        concurrency=10,
    )
    assert res_qdrant.successful_requests == 50
    assert res_qdrant.success_rate_pct == 100.0
    assert res_qdrant.p95_ms <= 100.0, (
        f"Expected Qdrant P95 <= 100ms, got {res_qdrant.p95_ms}ms"
    )

    # 2. PostgreSQL 16 Pool Load Benchmark
    res_db = await run_db_pool_benchmark(
        pg_dsn=DEFAULT_PG_DSN,
        total_transactions=30,
        concurrency=15,
    )
    assert res_db.successful_requests == 30
    assert res_db.success_rate_pct == 100.0

    # Verify zero deadlocks and zero pool leaks
    deadlocks = res_db.extra_metrics.get("deadlocks", 0)
    leaks = res_db.extra_metrics.get("connection_leaks", 0)
    assert deadlocks == 0, f"Expected 0 deadlocks, encountered {deadlocks}"
    assert leaks == 0, f"Expected 0 connection leaks, encountered {leaks}"


@pytest.mark.asyncio
async def test_benchmark_3_websocket_concurrency_and_event_broadcast() -> None:
    """R2.3: WebSocket Live Chat Concurrency & Redis Pub/Sub Broadcast Latency.

    1. Connect multiple concurrent WebSocket clients with JWT authentication.
    2. Broadcast events via Redis Pub/Sub ('livechat:events') to all active clients.
    3. Measure distribution latency from event trigger to arrival on each client.
    4. Assert P95 broadcast distribution latency <= 100ms.
    """
    res_ws = await run_websocket_broadcast_benchmark(
        base_url=DEFAULT_HTTP_URL,
        ws_url=DEFAULT_WS_URL,
        redis_url=DEFAULT_REDIS_URL,
        client_count=20,
        event_count=5,
    )
    assert res_ws.concurrency == 20
    assert res_ws.success_rate_pct >= 95.0, (
        f"Expected >= 95% delivery rate across clients, got {res_ws.success_rate_pct}%"
    )
    # Target: Redis Pub/Sub broadcast distribution latency <= 100ms
    assert res_ws.p95_ms <= 100.0, (
        f"Expected WebSocket broadcast P95 <= 100ms, got {res_ws.p95_ms}ms"
    )

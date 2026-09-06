"""Unit tests for Webhook Deduplication and Message Debouncing."""

import asyncio
import uuid

import pytest

from app.core.deduplication import MessageDebouncer, MessageDeduplicator


@pytest.mark.asyncio
async def test_deduplicator_in_memory_catches_duplicates() -> None:
    """Duplicate platform message IDs must be detected and blocked."""
    dedup = MessageDeduplicator()
    tag = uuid.uuid4().hex[:6]
    try:
        is_dup1 = await dedup.is_duplicate(f"mid.123456_{tag}", channel="facebook")
        assert is_dup1 is False  # First time: not a duplicate

        is_dup2 = await dedup.is_duplicate(f"mid.123456_{tag}", channel="facebook")
        assert is_dup2 is True  # Second time: caught as duplicate

        is_dup3 = await dedup.is_duplicate(f"mid.789012_{tag}", channel="facebook")
        assert is_dup3 is False  # Different ID: not a duplicate
    finally:
        await dedup.aclose()


@pytest.mark.asyncio
async def test_deduplicator_expires_after_ttl() -> None:
    """Deduplication record should expire after TTL."""
    dedup = MessageDeduplicator()
    tag = uuid.uuid4().hex[:6]
    try:
        is_dup1 = await dedup.is_duplicate(f"mid.temp_{tag}", channel="facebook", ttl_seconds=1)
        assert is_dup1 is False

        is_dup2 = await dedup.is_duplicate(f"mid.temp_{tag}", channel="facebook", ttl_seconds=1)
        assert is_dup2 is True

        # Wait for TTL to expire
        await asyncio.sleep(1.1)
        is_dup3 = await dedup.is_duplicate(f"mid.temp_{tag}", channel="facebook", ttl_seconds=1)
        assert is_dup3 is False
    finally:
        await dedup.aclose()


@pytest.mark.asyncio
async def test_debouncer_aggregates_rapid_messages() -> None:
    """Debouncer should combine messages sent in rapid succession into a single aggregated prompt."""
    debouncer = MessageDebouncer(window_seconds=0.2)
    results: list[str] = []

    async def on_debounced(user_key: str, aggregated_text: str) -> None:
        results.append(aggregated_text)

    # Customer sends 3 messages in quick succession
    await debouncer.push("user_101", "Chào shop", on_debounced)
    await asyncio.sleep(0.05)
    await debouncer.push("user_101", "Cho mình hỏi túi da", on_debounced)
    await asyncio.sleep(0.05)
    await debouncer.push("user_101", "Có ship COD không?", on_debounced)

    # Wait for debounce window to fire
    await asyncio.sleep(0.3)

    assert len(results) == 1
    assert "Chào shop" in results[0]
    assert "Cho mình hỏi túi da" in results[0]
    assert "Có ship COD không?" in results[0]

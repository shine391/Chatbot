"""Webhook deduplication and message debouncing buffer.

Prevents:
1. Meta / TikTok webhook retries causing duplicate responses.
2. Rapid-fire customer messages triggering multiple concurrent AI responses.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)


class MessageDeduplicator:
    """Detects and suppresses duplicate webhook deliveries using Redis with in-memory fallback."""

    def __init__(self, redis_url: str | None = None) -> None:
        self.redis_url: str | None = redis_url
        if self.redis_url is None:
            try:
                from app.config import get_settings

                self.redis_url = get_settings().redis_url
            except Exception:
                self.redis_url = None
        self._memory_cache: dict[str, float] = {}
        self._redis_client: Any = None
        self._redis_failed: bool = False

    async def _get_redis_client(self) -> Any:
        if self._redis_client is None and not self._redis_failed and self.redis_url:
            try:
                import redis.asyncio as aioredis

                target_url = self.redis_url
                if "localhost" in target_url:
                    target_url = target_url.replace("localhost", "127.0.0.1")

                self._redis_client = aioredis.from_url(
                    target_url,
                    decode_responses=True,
                    socket_connect_timeout=2.0,
                    socket_timeout=2.0,
                )
            except Exception as e:
                logger.warning(f"Failed to connect to Redis for deduplication: {e}")
                self._redis_failed = True
        return self._redis_client

    async def is_duplicate(
        self,
        message_id: str,
        channel: str = "default",
        ttl_seconds: int = 300,
    ) -> bool:
        """Check if message_id was already processed within ttl_seconds.

        Returns True if duplicate (should be dropped).
        Returns False if new (recorded and should be processed).
        """
        if not message_id:
            return False

        dedup_key = f"dedup:{channel}:{message_id}"

        # 1. Check Redis if available
        client = await self._get_redis_client()
        if client is not None:
            try:
                res = await client.set(dedup_key, "1", ex=ttl_seconds, nx=True)
                if not res:
                    logger.info("Duplicate message detected via Redis: %s", dedup_key)
                    return True
                return False
            except Exception as exc:
                logger.warning("Redis dedup check error, falling back to memory: %s", exc)
                self._redis_failed = True
                self._redis_client = None

        # 2. In-memory fallback dictionary: {cache_key: expire_timestamp}
        now = time.time()
        cache_key = f"{channel}:{message_id}"
        if len(self._memory_cache) > 1000:
            self._memory_cache = {k: exp for k, exp in self._memory_cache.items() if exp > now}

        exp = self._memory_cache.get(cache_key)
        if exp is not None and exp > now:
            logger.info("Duplicate message detected and dropped: %s", cache_key)
            return True

        self._memory_cache[cache_key] = now + ttl_seconds
        return False

    async def aclose(self) -> None:
        """Close Redis connection."""
        if self._redis_client is not None:
            try:
                await self._redis_client.aclose()
            except Exception:
                pass
            self._redis_client = None


class MessageDebouncer:
    """Aggregates multiple quick messages from the same user into a unified prompt."""

    def __init__(self, window_seconds: float = 1.5) -> None:
        self.window_seconds = window_seconds
        self._buffers: dict[str, list[str]] = {}
        self._timers: dict[str, asyncio.Task[None]] = {}

    async def push(
        self,
        user_key: str,
        message: str,
        callback: Callable[[str, str], Awaitable[None]],
    ) -> None:
        """Buffer a message and reset the timer for user_key.

        When the timer expires after window_seconds of silence,
        callback is called with (user_key, aggregated_text).
        """
        if user_key not in self._buffers:
            self._buffers[user_key] = []
        self._buffers[user_key].append(message)

        # Cancel previous pending timer if active
        existing_task = self._timers.get(user_key)
        if existing_task and not existing_task.done():
            existing_task.cancel()

        # Schedule execution after window_seconds
        async def _timer_worker() -> None:
            try:
                await asyncio.sleep(self.window_seconds)
                msgs = self._buffers.pop(user_key, [])
                self._timers.pop(user_key, None)
                if msgs:
                    aggregated = "\n".join(msgs)
                    await callback(user_key, aggregated)
            except asyncio.CancelledError:
                # Cancelled because a newer message arrived in the window
                pass
            except Exception as exc:
                logger.error("Error in debounce callback for %s: %s", user_key, exc)

        self._timers[user_key] = asyncio.create_task(_timer_worker())

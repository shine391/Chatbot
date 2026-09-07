"""WebSocket manager for omnichannel real-time live chat and human takeover."""

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class LiveChatManager:
    """Manages active WebSocket connections and synchronizes events across workers via Redis Pub/Sub."""

    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []
        self.tenant_connections: dict[str, list[WebSocket]] = {}
        self._redis_client: Any = None
        self._pubsub_task: asyncio.Task[None] | None = None
        self._channel_name: str = "livechat:events"

    async def connect(
        self,
        websocket: WebSocket,
        tenant_id: str = "default-system-tenant",
        is_superadmin: bool = False,
    ) -> None:
        """Register and accept an incoming admin WebSocket client partitioned by tenant."""
        await websocket.accept()
        if hasattr(websocket, "state"):
            setattr(websocket.state, "tenant_id", tenant_id)
            setattr(websocket.state, "is_superadmin", is_superadmin)
        self.active_connections.append(websocket)
        if tenant_id not in self.tenant_connections:
            self.tenant_connections[tenant_id] = []
        self.tenant_connections[tenant_id].append(websocket)
        logger.info(
            "Admin connected to Live Chat WebSocket (tenant: %s). Total: %d",
            tenant_id,
            len(self.active_connections),
        )

    def disconnect(self, websocket: WebSocket, tenant_id: str | None = None) -> None:
        """Remove a disconnected WebSocket client."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

        t_id = tenant_id or getattr(getattr(websocket, "state", None), "tenant_id", None)
        if t_id and t_id in self.tenant_connections and websocket in self.tenant_connections[t_id]:
            self.tenant_connections[t_id].remove(websocket)
        else:
            for bucket in self.tenant_connections.values():
                if websocket in bucket:
                    bucket.remove(websocket)

        logger.info(
            "Admin disconnected from Live Chat. Remaining: %d", len(self.active_connections)
        )

    async def start_redis_sync(self, redis_url: str) -> None:
        """Initialize Redis Pub/Sub subscriber loop for multi-worker synchronization."""
        try:
            import redis.asyncio as aioredis

            self._redis_client = aioredis.from_url(redis_url, decode_responses=True)
            self._pubsub_task = asyncio.create_task(self._listen_redis_events())
            logger.info("LiveChatManager Redis Pub/Sub synchronization initialized.")
        except Exception as err:
            logger.warning("Could not initialize Redis Pub/Sub sync for LiveChatManager: %s", err)

    async def stop_redis_sync(self) -> None:
        """Stop Redis Pub/Sub synchronization."""
        if self._pubsub_task and not self._pubsub_task.done():
            self._pubsub_task.cancel()
        if self._redis_client:
            try:
                await self._redis_client.aclose()
            except Exception:
                pass
            self._redis_client = None

    async def _listen_redis_events(self) -> None:
        """Background listener for Redis Pub/Sub events."""
        try:
            pubsub = self._redis_client.pubsub()
            await pubsub.subscribe(self._channel_name)
            async for message in pubsub.listen():
                if message["type"] == "message":
                    raw_data = message["data"]
                    try:
                        payload = json.loads(raw_data)
                        await self._local_broadcast(payload)
                    except Exception as parse_err:
                        logger.warning("Error parsing Redis Pub/Sub message: %s", parse_err)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.warning("Redis Pub/Sub listener encountered error: %s", exc)

    async def _local_broadcast(self, payload: dict[str, Any]) -> None:
        """Broadcast payload to connected WebSockets matching tenant_id (or all if None/superadmin)."""
        if not self.active_connections:
            return

        target_tenant = payload.get("tenant_id")
        disconnected: list[WebSocket] = []
        if target_tenant and target_tenant != "superadmin":
            recipients = list(self.tenant_connections.get(target_tenant, []))
            for ws in self.active_connections:
                if getattr(getattr(ws, "state", None), "is_superadmin", None) is True and ws not in recipients:
                    recipients.append(ws)
        else:
            recipients = list(self.active_connections)

        for ws in recipients:
            try:
                await ws.send_json(payload)
            except Exception as exc:
                logger.warning("Error broadcasting to admin WebSocket: %s", exc)
                disconnected.append(ws)

        for ws in disconnected:
            self.disconnect(ws)

    async def broadcast(
        self, event_type: str, data: dict[str, Any], tenant_id: str | None = None
    ) -> None:
        """Broadcast real-time event to connected admin dashboards across all workers."""
        payload = {
            "type": event_type,
            "data": data,
            "timestamp": datetime.now(UTC).isoformat(),
            "tenant_id": tenant_id,
        }

        # If Redis is active, publish to Pub/Sub channel
        if self._redis_client:
            try:
                await self._redis_client.publish(self._channel_name, json.dumps(payload))
                return
            except Exception as exc:
                logger.warning(
                    "Failed to publish event to Redis Pub/Sub: %s. Falling back to local.", exc
                )

        # Fallback to local process broadcast
        await self._local_broadcast(payload)


# Global singleton instance
live_chat_manager = LiveChatManager()

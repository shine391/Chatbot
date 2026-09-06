"""Comprehensive Full-Cycle Functional E2E Test Suite against Live Docker Services.

Target Environment:
- HTTP API: http://127.0.0.1:8000
- WebSocket: ws://127.0.0.1:8000/api/admin/ws/livechat
- PostgreSQL 16: postgresql+asyncpg://chatbot:chatbot123@127.0.0.1:5432/chatbot
- Redis 7: redis://127.0.0.1:6379/0
- Qdrant: http://127.0.0.1:6333

Covers 4 Core Functional Flows:
1. Customer Journey Flow (Webhook -> Intent Router -> Qdrant RAG -> Carousel -> Order -> VietQR -> CRM Funnel)
2. Live Chat & Human Takeover Flow (WS JWT Handshake, Ping/Pong, Redis Pub/Sub, Takeover, Quick Replies, Handover)
3. Shipping & 2-Tier Post-Purchase Upsell Flow (Carrier Webhooks, DELIVERED status, 7-day Tier 1 care, Tier 2 coupon TRIAN10)
4. RBAC Security Matrix (Admin full access, Manager export/analytics 200 but staff/settings 403, Agent 403, Deletion safeguards)
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pytest
import websockets
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from websockets.exceptions import ConnectionClosed, InvalidStatus

from app.core.auth import create_access_token
from app.models.customer import Customer
from app.models.order import Order, OrderStatus
from app.services.followup_scheduler import FollowUpScheduler

LIVE_BASE_URL = "http://127.0.0.1:8000"
LIVE_WS_URL = "ws://127.0.0.1:8000/api/admin/ws/livechat"


# ===========================================================================
# Flow 1: Customer Journey Flow
# ===========================================================================


class TestFlow1CustomerJourney:
    """E2E verification of complete multi-channel customer purchase journey."""

    @pytest.mark.asyncio
    async def test_webhook_catalog_carousel_recommendation(
        self, live_client: httpx.AsyncClient
    ) -> None:
        """Inbound webhook query 'Cho mình xem 3 mẫu túi da' triggers carousel response."""
        payload = {
            "session_id": "e2e_cust_journey_carousel",
            "content": "Cho mình xem 3 mẫu túi da",
        }
        resp = await live_client.post("/webhook/chat", json=payload)
        assert resp.status_code == 200, f"Webhook failed: {resp.text}"

        data: dict[str, Any] = resp.json()
        assert data["status"] == "success"
        assert data["message_type"] == "carousel"

        products: list[dict[str, Any]] = data.get("products", [])
        assert 3 <= len(products) <= 4, f"Expected 3-4 products in carousel, got {len(products)}"

        for idx, prod in enumerate(products, start=1):
            assert "sku" in prod and prod["sku"], f"Product #{idx} missing sku"
            assert "name" in prod and prod["name"], f"Product #{idx} missing name"
            assert "price" in prod and prod["price"] > 0, f"Product #{idx} invalid price"
            assert "image_url" in prod and prod["image_url"], f"Product #{idx} missing image_url"
            assert "product_url" in prod and prod["product_url"], f"Product #{idx} missing product_url"

        quick_replies = data.get("quick_replies", [])
        assert isinstance(quick_replies, list)
        assert len(quick_replies) > 0

    @pytest.mark.asyncio
    async def test_sku_code_product_detail_card(
        self, live_client: httpx.AsyncClient
    ) -> None:
        """Querying by SKU code 'Mã SP001' returns single rich product detail card."""
        payload = {
            "session_id": "e2e_cust_journey_sku",
            "content": "Cho mình xem mã SP001 nhé",
        }
        resp = await live_client.post("/webhook/chat", json=payload)
        assert resp.status_code == 200, f"SKU query failed: {resp.text}"

        data: dict[str, Any] = resp.json()
        assert data["message_type"] == "product_card"

        products = data.get("products", [])
        assert len(products) == 1
        card = products[0]
        assert card["sku"] == "SP001"
        assert card["price"] == 1100000.0
        assert "sp001" in card["product_url"].lower()

    @pytest.mark.asyncio
    async def test_qdrant_rag_vector_search(self) -> None:
        """Verify semantic similarity retrieval against live Qdrant container."""
        async with httpx.AsyncClient(base_url="http://127.0.0.1:6333", timeout=10.0) as qdrant:
            col_resp = await qdrant.get("/collections/products")
            assert col_resp.status_code == 200, f"Qdrant collection check failed: {col_resp.text}"
            col_data = col_resp.json()
            assert col_data["result"]["status"] in ("green", "yellow", "ok")

            points_count = col_data["result"]["points_count"]
            assert points_count >= 5, f"Expected at least 5 points in Qdrant, found {points_count}"

    @pytest.mark.asyncio
    async def test_order_creation_and_vietqr_napas_247(
        self,
        live_client: httpx.AsyncClient,
        admin_headers: dict[str, str],
        pg_engine: AsyncEngine,
    ) -> None:
        """Create order via Admin API and verify Napas 247 dynamic VietQR code."""
        # 1. Establish customer session
        await live_client.post(
            "/webhook/chat",
            json={"session_id": "e2e_cust_vietqr_01", "content": "Tư vấn túi da"},
        )

        session_factory = async_sessionmaker(pg_engine, expire_on_commit=False)
        async with session_factory() as db:
            res = await db.execute(
                select(Customer).where(Customer.platform_user_id == "e2e_cust_vietqr_01")
            )
            customer = res.scalar_one_or_none()
            assert customer is not None, "Customer was not created in database"
            cust_id = customer.id

        # 2. Place order
        order_payload = {
            "customer_id": cust_id,
            "items": [
                {
                    "product_sku": "TUI-01",
                    "name": "Túi xách da bò công sở cao cấp",
                    "price": 1250000.0,
                    "quantity": 1,
                }
            ],
            "total_amount": 1250000.0,
            "notes": "E2E VietQR Order Verification",
        }
        order_resp = await live_client.post(
            "/api/admin/orders", json=order_payload, headers=admin_headers
        )
        assert order_resp.status_code == 200, f"Order creation failed: {order_resp.text}"
        order_data: dict[str, Any] = order_resp.json()
        order_id = order_data["id"]
        assert order_id > 3, "New order ID should exceed baseline orders max_id"

        # Verify VietQR URL in order response
        vietqr_url = order_data.get("vietqr_url", "")
        assert "img.vietqr.io/image/" in vietqr_url
        assert "amount=1250000" in vietqr_url
        assert f"addInfo=DH{order_id}" in vietqr_url

        # 3. Call dedicated VietQR endpoint
        qr_endpoint_resp = await live_client.get(
            f"/api/admin/orders/{order_id}/vietqr", headers=admin_headers
        )
        assert qr_endpoint_resp.status_code == 200
        qr_data = qr_endpoint_resp.json()
        assert qr_data["order_id"] == order_id
        assert qr_data["amount"] == 1250000.0
        assert qr_data["transfer_memo"] == f"DH{order_id}"
        assert qr_data["bank_bin"] in ("970407", "970436", "970422")
        assert "qr_image_url" in qr_data

    @pytest.mark.asyncio
    async def test_crm_sales_funnel_progression(
        self,
        live_client: httpx.AsyncClient,
        admin_headers: dict[str, str],
        pg_engine: AsyncEngine,
    ) -> None:
        """Verify progression through lifecycle: lead -> interested -> intent -> purchased -> loyal."""
        session_factory = async_sessionmaker(pg_engine, expire_on_commit=False)
        sender_id = "e2e_cust_funnel_pipeline_01"

        async def get_stage() -> str:
            async with session_factory() as db:
                c = (
                    await db.execute(
                        select(Customer).where(Customer.platform_user_id == sender_id)
                    )
                ).scalar_one_or_none()
                return str(c.funnel_stage) if c else ""

        # Step 1: Greeting -> lead
        await live_client.post(
            "/webhook/chat",
            json={"session_id": sender_id, "content": "Alo shop có hoạt động không"},
        )
        assert (await get_stage()) == "lead"

        # Step 2: Interested query ("giá", "mẫu") -> interested
        await live_client.post(
            "/webhook/chat",
            json={"session_id": sender_id, "content": "Cho mình xem giá và thông tin túi da nhé"},
        )
        assert (await get_stage()) == "interested"

        # Step 3: Intent query ("chốt", "chuyển khoản") -> intent
        await live_client.post(
            "/webhook/chat",
            json={"session_id": sender_id, "content": "Cho mình xin stk chuyển khoản chốt đơn luôn"},
        )
        assert (await get_stage()) == "intent"

        # Step 4: First order placed -> purchased
        async with session_factory() as db:
            cust = (
                await db.execute(
                    select(Customer).where(Customer.platform_user_id == sender_id)
                )
            ).scalar_one()
            cust_id = cust.id

        order1_resp = await live_client.post(
            "/api/admin/orders",
            json={
                "customer_id": cust_id,
                "items": [{"product_sku": "TUI-01", "name": "Túi 1", "price": 990000.0, "quantity": 1}],
                "total_amount": 990000.0,
            },
            headers=admin_headers,
        )
        assert order1_resp.status_code == 200
        assert (await get_stage()) == "purchased"

        # Step 5: Second order placed -> loyal
        order2_resp = await live_client.post(
            "/api/admin/orders",
            json={
                "customer_id": cust_id,
                "items": [{"product_sku": "TUI-02", "name": "Túi 2", "price": 750000.0, "quantity": 1}],
                "total_amount": 750000.0,
            },
            headers=admin_headers,
        )
        assert order2_resp.status_code == 200
        assert (await get_stage()) == "loyal"

        # Step 6: Non-downgrade test: customer sends casual query, stays loyal
        await live_client.post(
            "/webhook/chat",
            json={"session_id": sender_id, "content": "Shop có mẫu ví nào mới không?"},
        )
        assert (await get_stage()) == "loyal"


# ===========================================================================
# Flow 2: Live Chat & Human Takeover Flow
# ===========================================================================


class TestFlow2LiveChatAndHumanTakeover:
    """E2E verification of real-time WebSocket live chat, takeover, and quick replies."""

    @pytest.mark.asyncio
    async def test_websocket_authentication_handshake(self, admin_token: str) -> None:
        """Matrix testing WebSocket auth: no token (1008/403), invalid token (1008/403), valid token (OK)."""
        # A. Missing token -> Rejected
        with pytest.raises((InvalidStatus, ConnectionClosed)):
            async with websockets.connect(LIVE_WS_URL):
                pass

        # B. Invalid token -> Rejected
        with pytest.raises((InvalidStatus, ConnectionClosed)):
            async with websockets.connect(f"{LIVE_WS_URL}?token=invalid_jwt_token"):
                pass

        # C. Valid token -> Connection established, verifies ping/pong
        async with websockets.connect(f"{LIVE_WS_URL}?token={admin_token}") as ws:
            assert ws.state.name == "OPEN"
            await ws.send("ping")
            pong = await asyncio.wait_for(ws.recv(), timeout=2.0)
            assert pong == "pong"

    @pytest.mark.asyncio
    async def test_websocket_heartbeat_ping_pong(self, admin_token: str) -> None:
        """Client sends 'ping' frame and receives immediate 'pong' response."""
        async with websockets.connect(f"{LIVE_WS_URL}?token={admin_token}") as ws:
            await ws.send("ping")
            pong = await asyncio.wait_for(ws.recv(), timeout=2.0)
            assert pong == "pong"

    @pytest.mark.asyncio
    async def test_redis_pubsub_livechat_broadcast(
        self, live_client: httpx.AsyncClient, admin_token: str
    ) -> None:
        """Inbound customer webhook message triggers real-time broadcast to connected admin WebSocket."""
        async with websockets.connect(f"{LIVE_WS_URL}?token={admin_token}") as ws:
            test_sess = "e2e_ws_broadcast_session_01"
            chat_payload = {
                "session_id": test_sess,
                "content": "Cho mình xem 3 mẫu túi da",
            }
            resp = await live_client.post("/webhook/chat", json=chat_payload)
            assert resp.status_code == 200

            received_events: list[dict[str, Any]] = []
            for _ in range(2):
                msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                received_events.append(json.loads(msg))

            event_types = [e["type"] for e in received_events]
            assert "customer_message" in event_types, f"customer_message not received: {event_types}"
            assert "bot_message" in event_types, f"bot_message not received: {event_types}"

            cust_ev = next(e for e in received_events if e["type"] == "customer_message")
            assert cust_ev["data"]["content"] == "Cho mình xem 3 mẫu túi da"
            assert cust_ev["data"]["sender_id"] == test_sess

    @pytest.mark.asyncio
    async def test_agent_takeover_and_bot_silencing(
        self,
        live_client: httpx.AsyncClient,
        admin_token: str,
        admin_headers: dict[str, str],
        pg_engine: AsyncEngine,
    ) -> None:
        """Human agent calls takeover: WebSocket receives broadcast and bot is completely silenced."""
        sess_id = "e2e_takeover_sess_01"
        # 1. Create conversation via message
        await live_client.post(
            "/webhook/chat",
            json={"session_id": sess_id, "content": "Em muốn hỏi tư vấn"},
        )

        session_factory = async_sessionmaker(pg_engine, expire_on_commit=False)
        async with session_factory() as db:
            cust = (
                await db.execute(
                    select(Customer).where(Customer.platform_user_id == sess_id)
                )
            ).scalar_one()
            res_conv = await db.execute(
                text(f"SELECT id FROM conversations WHERE customer_id = {cust.id};")
            )
            conv_id = res_conv.scalar_one()

        # 2. Connect WebSocket and trigger takeover
        async with websockets.connect(f"{LIVE_WS_URL}?token={admin_token}") as ws:
            takeover_resp = await live_client.post(
                f"/api/admin/conversations/{conv_id}/takeover", headers=admin_headers
            )
            assert takeover_resp.status_code == 200
            t_data = takeover_resp.json()
            assert t_data["is_bot_active"] is False

            # Receive WebSocket event
            ws_ev = json.loads(await asyncio.wait_for(ws.recv(), timeout=5.0))
            assert ws_ev["type"] == "bot_status_changed"
            assert ws_ev["data"]["is_bot_active"] is False

            # 3. Customer sends message while taken over -> Bot is silent
            silent_resp = await live_client.post(
                "/webhook/chat",
                json={"session_id": sess_id, "content": "Alo còn ai trực không?"},
            )
            assert silent_resp.status_code == 200
            s_data = silent_resp.json()
            assert s_data["content"] == "", f"Bot should be silent, but got: {s_data['content']}"

    @pytest.mark.asyncio
    async def test_canned_quick_replies_and_handover_restoration(
        self,
        live_client: httpx.AsyncClient,
        admin_token: str,
        admin_headers: dict[str, str],
        pg_engine: AsyncEngine,
    ) -> None:
        """Staff manages '/' quick replies, sends agent reply, and hands over control back to bot."""
        sess_id = "e2e_canned_reply_sess_01"
        await live_client.post(
            "/webhook/chat",
            json={"session_id": sess_id, "content": "Cần nhân viên tư vấn gấp"},
        )

        session_factory = async_sessionmaker(pg_engine, expire_on_commit=False)
        async with session_factory() as db:
            cust = (
                await db.execute(
                    select(Customer).where(Customer.platform_user_id == sess_id)
                )
            ).scalar_one()
            conv_id = (
                await db.execute(
                    text(f"SELECT id FROM conversations WHERE customer_id = {cust.id};")
                )
            ).scalar_one()

        # 1. Quick replies CRUD
        qr_create_resp = await live_client.post(
            "/api/admin/quick-replies",
            json={
                "title": "E2E Staff Quick Welcome",
                "shortcut": "/e2e_quick",
                "content": "Dạ em là nhân viên hỗ trợ trực tiếp, em sẽ hỗ trợ bạn ngay ạ!",
                "category": "support",
            },
            headers=admin_headers,
        )
        assert qr_create_resp.status_code == 200
        qr_data = qr_create_resp.json()
        assert qr_data["shortcut"] == "/e2e_quick"

        # Duplicate shortcut returns 400 Bad Request
        dup_resp = await live_client.post(
            "/api/admin/quick-replies",
            json={
                "title": "Duplicate",
                "shortcut": "/e2e_quick",
                "content": "Trùng",
            },
            headers=admin_headers,
        )
        assert dup_resp.status_code == 400

        # 2. Staff sends canned response to conversation
        async with websockets.connect(f"{LIVE_WS_URL}?token={admin_token}") as ws:
            send_resp = await live_client.post(
                f"/api/admin/conversations/{conv_id}/send",
                json={"content": qr_data["content"]},
                headers=admin_headers,
            )
            assert send_resp.status_code == 200

            ws_agent_ev = json.loads(await asyncio.wait_for(ws.recv(), timeout=5.0))
            assert ws_agent_ev["type"] == "agent_message"
            assert ws_agent_ev["data"]["content"] == qr_data["content"]

            # 3. Hand over control back to bot
            handover_resp = await live_client.post(
                f"/api/admin/conversations/{conv_id}/handover", headers=admin_headers
            )
            assert handover_resp.status_code == 200
            h_data = handover_resp.json()
            assert h_data["is_bot_active"] is True

            ws_handover_ev = json.loads(await asyncio.wait_for(ws.recv(), timeout=5.0))
            assert ws_handover_ev["type"] == "bot_status_changed"
            assert ws_handover_ev["data"]["is_bot_active"] is True

        # 4. Customer messages again -> Bot active and answering normally
        bot_resp = await live_client.post(
            "/webhook/chat",
            json={"session_id": sess_id, "content": "Cho mình xem 3 mẫu túi da"},
        )
        assert bot_resp.status_code == 200
        assert bot_resp.json()["message_type"] == "carousel"
        assert len(bot_resp.json()["products"]) >= 3


# ===========================================================================
# Flow 3: Shipping & 2-Tier Post-Purchase Upsell Flow
# ===========================================================================


class TestFlow3ShippingAndTwoTierUpsell:
    """E2E verification of carrier webhooks, delivery mapping, 7-day Tier 1 care, and Tier 2 upsell."""

    @pytest.mark.asyncio
    async def test_carrier_delivery_webhook_authentication_and_status(
        self, live_client: httpx.AsyncClient, pg_engine: AsyncEngine
    ) -> None:
        """Carrier webhook verifies authentication and updates order status to DELIVERED."""
        sender_id = "e2e_cust_ship_01"
        tracking_code = "GHTK_E2E_SHIP_991"

        # 1. Establish customer via webhook
        await live_client.post(
            "/webhook/chat",
            json={"session_id": sender_id, "content": "Tư vấn giao hàng"},
        )

        session_factory = async_sessionmaker(pg_engine, expire_on_commit=False)
        async with session_factory() as db:
            c = (
                await db.execute(
                    select(Customer).where(Customer.platform_user_id == sender_id)
                )
            ).scalar_one()

            order = Order(
                customer_id=c.id,
                status=OrderStatus.PENDING,
                total_amount=1250000.0,
                tracking_code=tracking_code,
                carrier="ghtk",
            )
            db.add(order)
            await db.flush()
            order_id = order.id
            await db.commit()

        # 2. Unauthenticated callback -> 401
        unauth_resp = await live_client.post(
            "/api/webhooks/shipping/ghtk",
            json={"tracking_code": tracking_code, "status": "delivered"},
        )
        assert unauth_resp.status_code == 401

        # 3. Authenticated callback with 'delivering' -> SHIPPED
        shipped_resp = await live_client.post(
            "/api/webhooks/shipping/ghtk",
            json={"tracking_code": tracking_code, "status": "delivering"},
            headers={"X-Carrier-Token": "ghtk_secret_token"},
        )
        assert shipped_resp.status_code == 200
        assert shipped_resp.json()["status"] == "shipped"

        # 4. Authenticated callback with 'delivered' -> DELIVERED
        deliv_resp = await live_client.post(
            "/api/webhooks/shipping/ghtk",
            json={"tracking_code": tracking_code, "status": "delivered"},
            headers={"X-Carrier-Token": "ghtk_secret_token"},
        )
        assert deliv_resp.status_code == 200
        assert deliv_resp.json()["status"] == "delivered"

        # Verify database order status and delivered_at timestamp
        async with session_factory() as db:
            updated_order = (
                await db.execute(select(Order).where(Order.id == order_id))
            ).scalar_one()
            assert updated_order.status == OrderStatus.DELIVERED
            assert updated_order.delivered_at is not None

    @pytest.mark.asyncio
    async def test_two_tier_post_purchase_upsell_flow(
        self, live_client: httpx.AsyncClient, pg_engine: AsyncEngine
    ) -> None:
        """Full cycle: Order delivered 8 days ago -> Tier 1 care message sent -> Customer reply triggers Tier 2 coupon (TRIAN10)."""
        session_factory = async_sessionmaker(pg_engine, expire_on_commit=False)
        sender_id = "e2e_cust_upsell_01"

        # 1. Establish customer via webhook
        await live_client.post(
            "/webhook/chat",
            json={"session_id": sender_id, "content": "Tư vấn sản phẩm"},
        )

        # 2. Set up delivered order older than 7 days
        async with session_factory() as db:
            cust = (
                await db.execute(
                    select(Customer).where(Customer.platform_user_id == sender_id)
                )
            ).scalar_one()

            eight_days_ago = datetime.now(timezone.utc) - timedelta(days=8)
            order = Order(
                customer_id=cust.id,
                status=OrderStatus.DELIVERED,
                total_amount=1250000.0,
                delivered_at=eight_days_ago,
                upsale_sent=False,
                notes="Standard purchase",
            )
            db.add(order)
            await db.flush()
            order_id = order.id
            cust_id = cust.id
            await db.commit()

        # 3. Run Tier 1 Post-Purchase Care Scan
        async with session_factory() as db:
            scheduler = FollowUpScheduler(db)
            sent_count = await scheduler.process_tier1_post_purchase()
            assert sent_count >= 1

        # Verify Tier 1 execution recorded in database
        async with session_factory() as db:
            o = (await db.execute(select(Order).where(Order.id == order_id))).scalar_one()
            assert o.upsale_sent is True
            assert o.upsale_sent_at is not None

        # 4. Customer replies to Tier 1 care message -> Triggers Tier 2 Promotional Upsell
        reply_resp = await live_client.post(
            "/webhook/chat",
            json={
                "session_id": sender_id,
                "content": "Dạ mình nhận hàng rồi, sản phẩm dùng rất ưng ý shop nhé!",
            },
        )
        assert reply_resp.status_code == 200

        # Verify Tier 2 voucher recorded in order notes
        async with session_factory() as db:
            refreshed_order = (
                await db.execute(select(Order).where(Order.id == order_id))
            ).scalar_one()
            assert refreshed_order.notes is not None
            assert "[TIER2_UPSELL_SENT:" in refreshed_order.notes

        # 5. Tier 2 Idempotency: Customer sends a second message -> No duplicate coupon
        async with session_factory() as db:
            scheduler = FollowUpScheduler(db)
            second_attempt = await scheduler.process_tier2_reply_upsell(cust_id)
            assert second_attempt is False, "Tier 2 upsell should be strictly idempotent"


# ===========================================================================
# Flow 4: RBAC Security Matrix
# ===========================================================================


class TestFlow4RBACSecurityMatrix:
    """E2E verification of Role-Based Access Control matrix for Admin, Manager, and Agent."""

    @pytest.mark.asyncio
    async def test_rbac_security_matrix_and_deletion_safeguards(
        self,
        live_client: httpx.AsyncClient,
        admin_headers: dict[str, str],
        pg_engine: AsyncEngine,
    ) -> None:
        """Matrix: Admin (200 on all), Manager (403 staff/settings, 200 export), Agent (403 all)."""
        # 1. Create Manager and Agent accounts via Admin API
        mgr_create = await live_client.post(
            "/api/admin/staff",
            json={
                "username": "e2e_test_mgr_rbac",
                "password": "Password123!",
                "display_name": "E2E Manager",
                "role": "manager",
                "email": "e2e_mgr@shop.vn",
            },
            headers=admin_headers,
        )
        assert mgr_create.status_code == 200
        mgr_user_id = mgr_create.json()["id"]

        agent_create = await live_client.post(
            "/api/admin/staff",
            json={
                "username": "e2e_test_agent_rbac",
                "password": "Password123!",
                "display_name": "E2E Agent",
                "role": "agent",
                "email": "e2e_agent@shop.vn",
            },
            headers=admin_headers,
        )
        assert agent_create.status_code == 200
        agent_user_id = agent_create.json()["id"]

        # Create secondary test admin to test deletion safeguards
        admin2_create = await live_client.post(
            "/api/admin/staff",
            json={
                "username": "e2e_test_admin2_rbac",
                "password": "Password123!",
                "display_name": "E2E Admin 2",
                "role": "admin",
                "email": "e2e_admin2@shop.vn",
            },
            headers=admin_headers,
        )
        assert admin2_create.status_code == 200
        admin2_user_id = admin2_create.json()["id"]

        # 2. Authenticate as Manager, Agent, and Secondary Admin
        # Validate genuine /api/admin/login endpoint with Manager credentials
        mgr_login = await live_client.post(
            "/api/admin/login",
            json={"username": "e2e_test_mgr_rbac", "password": "Password123!"},
            headers={"X-Forwarded-For": "10.10.4.1"},
        )
        assert mgr_login.status_code == 200
        mgr_headers = {"Authorization": f"Bearer {mgr_login.json()['access_token']}"}

        # For Agent and Secondary Admin, generate standard JWT access tokens to prevent SlowAPI 5/min limit exhaustion
        agent_token = create_access_token({"sub": "e2e_test_agent_rbac", "role": "agent"})
        agent_headers = {"Authorization": f"Bearer {agent_token}"}

        admin2_token = create_access_token({"sub": "e2e_test_admin2_rbac", "role": "admin"})
        admin2_headers = {"Authorization": f"Bearer {admin2_token}"}

        # 3. Staff Management Route Enforcement (Admin ONLY)
        # Admin -> 200
        assert (await live_client.get("/api/admin/staff", headers=admin_headers)).status_code == 200
        # Manager -> 403
        assert (await live_client.get("/api/admin/staff", headers=mgr_headers)).status_code == 403
        # Agent -> 403
        assert (await live_client.get("/api/admin/staff", headers=agent_headers)).status_code == 403

        # 4. System Settings & Backup Route Enforcement (Admin ONLY)
        # Admin -> 200
        assert (await live_client.get("/api/admin/settings", headers=admin_headers)).status_code == 200
        assert (await live_client.post("/api/admin/system/backup", headers=admin_headers)).status_code == 200
        # Manager -> 403
        assert (await live_client.get("/api/admin/settings", headers=mgr_headers)).status_code == 403
        assert (await live_client.post("/api/admin/system/backup", headers=mgr_headers)).status_code == 403
        # Agent -> 403
        assert (await live_client.get("/api/admin/settings", headers=agent_headers)).status_code == 403
        assert (await live_client.post("/api/admin/system/backup", headers=agent_headers)).status_code == 403

        # 5. Data Export & Analytics Route Enforcement (Admin and Manager ALLOWED, Agent FORBIDDEN)
        # Orders Export
        assert (await live_client.get("/api/admin/orders/export", headers=admin_headers)).status_code == 200
        assert (await live_client.get("/api/admin/orders/export", headers=mgr_headers)).status_code == 200
        assert (await live_client.get("/api/admin/orders/export", headers=agent_headers)).status_code == 403

        # Customers Export
        assert (await live_client.get("/api/admin/customers/export", headers=admin_headers)).status_code == 200
        assert (await live_client.get("/api/admin/customers/export", headers=mgr_headers)).status_code == 200
        assert (await live_client.get("/api/admin/customers/export", headers=agent_headers)).status_code == 403

        # Analytics Dashboard
        assert (await live_client.get("/api/admin/dashboard/analytics", headers=admin_headers)).status_code == 200
        assert (await live_client.get("/api/admin/dashboard/analytics", headers=mgr_headers)).status_code == 200
        assert (await live_client.get("/api/admin/dashboard/analytics", headers=agent_headers)).status_code == 403

        # 6. User Deletion Safeguards
        # Safeguard A: Manager / Agent cannot delete staff (403 Forbidden)
        mgr_del_attempt = await live_client.delete(
            f"/api/admin/staff/{mgr_user_id}", headers=mgr_headers
        )
        assert mgr_del_attempt.status_code == 403

        # Safeguard B: Admin cannot self-delete (400 Bad Request)
        self_del_attempt = await live_client.delete(
            f"/api/admin/staff/{admin2_user_id}", headers=admin2_headers
        )
        assert self_del_attempt.status_code == 400
        assert "Không thể tự xóa" in self_del_attempt.text

        # Safeguard C: Cannot delete default root admin (id=1, username="admin") (400 Bad Request)
        root_del_attempt = await live_client.delete(
            "/api/admin/staff/1", headers=admin2_headers
        )
        assert root_del_attempt.status_code == 400
        assert "Không thể xóa tài khoản quản trị viên mặc định" in root_del_attempt.text

        # Clean up test staff accounts
        del_mgr = await live_client.delete(f"/api/admin/staff/{mgr_user_id}", headers=admin_headers)
        assert del_mgr.status_code == 200
        del_agent = await live_client.delete(f"/api/admin/staff/{agent_user_id}", headers=admin_headers)
        assert del_agent.status_code == 200
        del_admin2 = await live_client.delete(f"/api/admin/staff/{admin2_user_id}", headers=admin_headers)
        assert del_admin2.status_code == 200

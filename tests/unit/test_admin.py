"""Unit tests for Phase 8: Admin Management API."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from httpx import AsyncClient

from app.core.llm_providers import GeminiProvider


class TestAdminAPI:
    @pytest.mark.asyncio
    async def test_create_and_get_category(self, app_client: AsyncClient) -> None:
        payload = {
            "name": "Balo Da Nam",
            "slug": "balo-da-nam",
            "description": "Balo da bò thật thời trang",
        }
        resp = await app_client.post("/api/admin/categories", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Balo Da Nam"
        assert data["slug"] == "balo-da-nam"
        assert "id" in data

        # List categories
        list_resp = await app_client.get("/api/admin/categories")
        assert list_resp.status_code == 200
        cats = list_resp.json()
        assert len(cats) >= 1
        assert any(c["slug"] == "balo-da-nam" for c in cats)

    @pytest.mark.asyncio
    async def test_create_and_list_products(self, app_client: AsyncClient) -> None:
        # Create a category first
        cat_resp = await app_client.post(
            "/api/admin/categories",
            json={"name": "Ví Cầm Tay", "slug": "vi-cam-tay"},
        )
        cat_id = cat_resp.json()["id"]

        # Create product
        prod_payload = {
            "sku": "ADM001",
            "name": "Ví dài cầm tay da cá sấu",
            "description": "Hàng thủ công cao cấp",
            "category_id": cat_id,
            "price": 2500000.0,
            "discount_price": 2100000.0,
            "images": ["https://shop.com/adm001.jpg"],
            "videos": ["https://shop.com/adm001.mp4"],
            "website_url": "https://shop.com/adm001",
            "tags": ["ví dài", "da cá sấu"],
        }
        p_resp = await app_client.post("/api/admin/products", json=prod_payload)
        assert p_resp.status_code == 200
        p_data = p_resp.json()
        assert p_data["sku"] == "ADM001"
        assert p_data["price"] == 2500000.0

        # List products
        p_list = await app_client.get("/api/admin/products")
        assert p_list.status_code == 200
        p_json = p_list.json()
        items = p_json["items"] if isinstance(p_json, dict) and "items" in p_json else p_json
        assert len(items) >= 1
        assert any(p["sku"] == "ADM001" for p in items)

    @pytest.mark.asyncio
    async def test_get_dashboard_analytics(self, app_client: AsyncClient) -> None:
        resp = await app_client.get("/api/admin/dashboard/stats")
        assert resp.status_code == 200
        stats = resp.json()
        assert "total_customers" in stats
        assert "total_conversations" in stats
        assert "total_products" in stats
        assert "total_orders" in stats

    @pytest.mark.asyncio
    async def test_serve_admin_dashboard(self, app_client: AsyncClient) -> None:
        resp = await app_client.get("/admin")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "AI Customer Service Agent" in resp.text
        assert "Prompt & Persona Studio" in resp.text

    @pytest.mark.asyncio
    async def test_delete_category(self, app_client: AsyncClient) -> None:
        cat_resp = await app_client.post(
            "/api/admin/categories",
            json={"name": "Túi Du Lịch", "slug": "tui-du-lich"},
        )
        assert cat_resp.status_code == 200
        cat_id = cat_resp.json()["id"]

        del_resp = await app_client.delete(f"/api/admin/categories/{cat_id}")
        assert del_resp.status_code == 200
        assert del_resp.json()["success"] is True

        del_404 = await app_client.delete(f"/api/admin/categories/{cat_id}")
        assert del_404.status_code == 404

    @pytest.mark.asyncio
    async def test_test_facebook_channel_connection(self, app_client: AsyncClient) -> None:
        resp_empty = await app_client.post(
            "/api/admin/channels/facebook/test",
            json={"access_token": ""},
        )
        assert resp_empty.status_code == 200
        assert resp_empty.json()["valid"] is False

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": "10099887766",
            "name": "Shop Thoi Trang AI",
            "picture": {"data": {"url": "https://graph.facebook.com/avatar.jpg"}},
        }
        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=mock_resp):
            resp_valid = await app_client.post(
                "/api/admin/channels/facebook/test",
                json={"access_token": "EAAValidToken123"},
            )
            assert resp_valid.status_code == 200
            data = resp_valid.json()
            assert data["valid"] is True
            assert data["id"] == "10099887766"
            assert data["name"] == "Shop Thoi Trang AI"

    @pytest.mark.asyncio
    async def test_test_llm_channel_latency(self, app_client: AsyncClient) -> None:
        resp_empty = await app_client.post(
            "/api/admin/channels/llm/test",
            json={"provider": "gemini", "api_key": ""},
        )
        assert resp_empty.status_code == 200
        assert resp_empty.json()["valid"] is False

        from app.core.llm_providers.base import LLMResponse

        mock_response = LLMResponse(content="OK", provider="gemini", model="gemini-2.0-flash")
        with patch.object(
            GeminiProvider, "generate_response", new_callable=AsyncMock, return_value=mock_response
        ):
            resp_valid = await app_client.post(
                "/api/admin/channels/llm/test",
                json={"provider": "gemini", "api_key": "AIzaSyValidKey123"},
            )
            assert resp_valid.status_code == 200
            data = resp_valid.json()
            assert data["valid"] is True
            assert data["provider"] == "gemini"
            assert "latency_ms" in data
            assert data["latency_ms"] is not None

    @pytest.mark.asyncio
    async def test_order_search_functionality(self, app_client: AsyncClient) -> None:
        await app_client.post(
            "/webhook/website",
            json={
                "session_id": "cust_search_test_01",
                "content": "Tôi tên là Nguyễn Văn An, số 0912345678",
            },
        )
        custs_resp = (await app_client.get("/api/admin/customers")).json()
        custs = (
            custs_resp["items"]
            if isinstance(custs_resp, dict) and "items" in custs_resp
            else custs_resp
        )
        cust = next(c for c in custs if c["platform_user_id"] == "cust_search_test_01")

        await app_client.put(
            f"/api/admin/customers/{cust['id']}",
            json={
                "name": "Nguyễn Văn An",
                "phone": "0912345678",
            },
        )

        order_resp = await app_client.post(
            "/api/admin/orders",
            json={
                "customer_id": cust["id"],
                "items": [
                    {
                        "product_sku": "SRCH-01",
                        "product_name": "Túi Test",
                        "quantity": 1,
                        "price": 500000.0,
                    }
                ],
                "total_amount": 500000.0,
                "notes": "Ghi chú đơn đặc biệt XYZ",
            },
        )
        order_id = order_resp.json()["id"]

        res_by_id = await app_client.get(f"/api/admin/orders?search=DH{order_id}")
        assert res_by_id.status_code == 200
        orders_by_id = (
            res_by_id.json()["items"] if isinstance(res_by_id.json(), dict) else res_by_id.json()
        )
        assert any(o["id"] == order_id for o in orders_by_id)

        res_by_phone = await app_client.get("/api/admin/orders?search=0912345678")
        assert res_by_phone.status_code == 200
        orders_by_phone = (
            res_by_phone.json()["items"]
            if isinstance(res_by_phone.json(), dict)
            else res_by_phone.json()
        )
        assert any(o["id"] == order_id for o in orders_by_phone)

        res_by_notes = await app_client.get("/api/admin/orders?search=XYZ")
        assert res_by_notes.status_code == 200
        orders_by_notes = (
            res_by_notes.json()["items"]
            if isinstance(res_by_notes.json(), dict)
            else res_by_notes.json()
        )
        assert any(o["id"] == order_id for o in orders_by_notes)

        # Test search by item SKU
        res_by_sku = await app_client.get("/api/admin/orders?search=SRCH-01")
        assert res_by_sku.status_code == 200
        orders_by_sku = (
            res_by_sku.json()["items"] if isinstance(res_by_sku.json(), dict) else res_by_sku.json()
        )
        assert any(o["id"] == order_id for o in orders_by_sku)

    @pytest.mark.asyncio
    async def test_manual_customer_creation(self, app_client: AsyncClient) -> None:
        payload = {
            "platform": "website",
            "platform_user_id": f"walkin_{int(time.time() * 1000)}",
            "name": "Khách Vãng Lai Trực Tiếp",
            "phone": "0987654321",
            "address": "456 Kim Mã, Ba Đình, Hà Nội",
            "funnel_stage": "intent",
            "notes": "Khách ghé cửa hàng trực tiếp",
        }
        resp = await app_client.post("/api/admin/customers", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Khách Vãng Lai Trực Tiếp"
        assert data["phone"] == "0987654321"
        assert data["funnel_stage"] == "intent"
        assert "id" in data

    @pytest.mark.asyncio
    async def test_setting_category_case_insensitivity(self, app_client: AsyncClient) -> None:
        # Save setting with uppercase category "PAYMENT"
        resp = await app_client.post(
            "/api/admin/settings",
            json={
                "key": "test_bank_code",
                "value": "VCB",
                "category": "PAYMENT",
                "is_secret": False,
                "description": "Test bank",
            },
        )
        assert resp.status_code == 200

        # Verify category preserved as payment (not defaulted to general)
        list_resp = await app_client.get("/api/admin/settings")
        assert list_resp.status_code == 200
        items = list_resp.json()["settings"]
        target = next((s for s in items if s["key"] == "test_bank_code"), None)
        assert target is not None
        assert target["category"] == "payment"

    @pytest.mark.asyncio
    async def test_facebook_channel_and_sender_from_settings(
        self, db_session: AsyncSession
    ) -> None:
        from app.channels.facebook_channel import FacebookChannel
        from app.services.message_sender import MessageSender
        from app.services.settings_service import SettingsService

        ss = SettingsService(db_session)
        await ss.set_setting("facebook_page_access_token", "EAA_dynamic_test_token_123")
        await ss.set_setting("facebook_app_secret", "secret_dynamic_xyz")
        await ss.set_setting("facebook_verify_token", "verify_dynamic_abc")
        await db_session.commit()

        fb = await FacebookChannel.from_settings(db_session)
        assert fb.access_token == "EAA_dynamic_test_token_123"
        assert fb.app_secret == "secret_dynamic_xyz"
        assert fb.verify_token == "verify_dynamic_abc"

        sender = await MessageSender.from_settings(db_session)
        from app.schemas.message import ChannelType

        fb_adapter = sender.channels[ChannelType.FACEBOOK]
        assert isinstance(fb_adapter, FacebookChannel)
        assert fb_adapter.access_token == "EAA_dynamic_test_token_123"

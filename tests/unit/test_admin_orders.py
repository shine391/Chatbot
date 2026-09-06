"""Unit tests for Admin Order Management API and VietQR checkout integration."""

import pytest
from httpx import AsyncClient


class TestAdminOrderAPI:
    @pytest.mark.asyncio
    async def test_order_lifecycle_and_vietqr(self, app_client: AsyncClient) -> None:
        """Test creating, listing, and updating orders with VietQR generation."""
        # 1. Create a customer first
        msg_payload = {
            "session_id": "order_cust_001",
            "content": "Mình muốn đặt hàng túi xách này",
        }
        await app_client.post("/webhook/website", json=msg_payload)

        res_custs = await app_client.get("/api/admin/customers")
        cust_data = res_custs.json()
        cust_items = (
            cust_data["items"]
            if isinstance(cust_data, dict) and "items" in cust_data
            else cust_data
        )
        cust = next(c for c in cust_items if c["platform_user_id"] == "order_cust_001")
        cust_id = cust["id"]

        # 2. Create order
        order_payload = {
            "customer_id": cust_id,
            "items": [
                {
                    "product_sku": "TUI-VIP-01",
                    "product_name": "Túi Da Cá Sấu Hoàng Gia",
                    "quantity": 1,
                    "price": 3500000.0,
                }
            ],
            "total_amount": 3500000.0,
            "notes": "Giao giờ hành chính, gọi trước khi giao",
        }
        res_order = await app_client.post("/api/admin/orders", json=order_payload)
        assert res_order.status_code == 200
        order_data = res_order.json()
        order_id = order_data["id"]
        assert order_data["status"] == "pending"
        assert order_data["total_amount"] == 3500000.0
        assert "vietqr_url" in order_data
        assert "img.vietqr.io" in order_data["vietqr_url"]

        # 3. Customer should be automatically promoted to PURCHASED
        res_cust_after = await app_client.get(f"/api/admin/customers/{cust_id}")
        assert res_cust_after.status_code == 200
        assert res_cust_after.json()["customer"]["funnel_stage"] == "purchased"

        # 4. List orders
        res_list = await app_client.get("/api/admin/orders")
        assert res_list.status_code == 200
        ord_data = res_list.json()
        orders_list = (
            ord_data["items"] if isinstance(ord_data, dict) and "items" in ord_data else ord_data
        )
        assert len(orders_list) >= 1

        # 5. Update order status to shipped and delivered
        res_status = await app_client.put(
            f"/api/admin/orders/{order_id}/status",
            json={"status": "delivered", "notes": "Đã giao thành công"},
        )
        assert res_status.status_code == 200
        assert res_status.json()["status"] == "delivered"
        assert res_status.json()["delivered_at"] is not None

        # 6. Retrieve VietQR package for the order
        res_qr = await app_client.get(f"/api/admin/orders/{order_id}/vietqr")
        assert res_qr.status_code == 200
        qr_pkg = res_qr.json()
        assert qr_pkg["order_id"] == order_id
        assert qr_pkg["amount"] == 3500000
        assert "qr_image_url" in qr_pkg

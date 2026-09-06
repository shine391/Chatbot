"""Unit tests for Phase 11 (Infrastructure & Resilience), Phase 12 (Analytics & UX), and Phase 13 (Business Features)."""

import pytest
from httpx import AsyncClient

from app.database.session import get_engine
from scripts.backup_db import perform_backup


class TestPhase12AnalyticsAndVisualizations:
    """Tests for Phase 12 Analytics API."""

    @pytest.mark.asyncio
    async def test_dashboard_analytics_default(self, app_client: AsyncClient) -> None:
        resp = await app_client.get("/api/admin/dashboard/analytics")
        assert resp.status_code == 200
        data = resp.json()

        assert data["timeframe_days"] == 30
        assert "summary" in data
        assert "revenue_trend" in data
        assert "revenue_trends" in data
        assert "order_volume_trend" in data
        assert "order_trends" in data
        assert "message_trend" in data
        assert "message_trends" in data
        assert "channel_distribution" in data
        assert "customer_conversion" in data

        # Check channel keys
        assert "facebook" in data["channel_distribution"]
        assert "instagram" in data["channel_distribution"]
        assert "tiktok" in data["channel_distribution"]
        assert "website" in data["channel_distribution"]

        # Check daily points length
        assert len(data["revenue_trend"]) == 30
        assert len(data["order_volume_trend"]) == 30
        assert len(data["message_trend"]) == 30

        # Check property compatibility
        first_order = data["order_trends"][0]
        assert "count" in first_order
        assert "orders_count" in first_order

        first_msg = data["message_trends"][0]
        assert "count" in first_msg
        assert "messages_count" in first_msg

    @pytest.mark.asyncio
    async def test_dashboard_analytics_7_days(self, app_client: AsyncClient) -> None:
        resp = await app_client.get("/api/admin/dashboard/analytics?days=7")
        assert resp.status_code == 200
        data = resp.json()
        assert data["timeframe_days"] == 7
        assert len(data["revenue_trend"]) == 7
        assert len(data["order_trends"]) == 7
        assert len(data["message_trends"]) == 7


class TestPhase12PaginationAndSorting:
    """Tests for server-side pagination & sorting on products, customers, and orders."""

    @pytest.mark.asyncio
    async def test_products_pagination_and_sorting(self, app_client: AsyncClient) -> None:
        # Create test products
        for i in range(1, 6):
            await app_client.post(
                "/api/admin/products",
                json={
                    "sku": f"PAGE-TEST-{i:02d}",
                    "name": f"Sản phẩm phân trang {i}",
                    "price": float(i * 100000),
                },
            )

        # Page 1, limit 2
        p1 = await app_client.get("/api/admin/products?page=1&limit=2")
        assert p1.status_code == 200
        d1 = p1.json()
        assert "items" in d1
        assert "total" in d1
        assert d1["page"] == 1
        assert d1["limit"] == 2
        assert len(d1["items"]) == 2
        assert d1["total"] >= 5

        # Page 2, limit 2
        p2 = await app_client.get("/api/admin/products?page=2&limit=2")
        assert p2.status_code == 200
        d2 = p2.json()
        assert d2["page"] == 2
        assert len(d2["items"]) == 2
        # Ensure items on page 1 and page 2 are different
        ids_p1 = {item["id"] for item in d1["items"]}
        ids_p2 = {item["id"] for item in d2["items"]}
        assert ids_p1.isdisjoint(ids_p2)

        # Sorting test by price asc
        p_asc = await app_client.get("/api/admin/products?sort_by=price&sort_order=asc&limit=10")
        assert p_asc.status_code == 200
        items_asc = p_asc.json()["items"]
        prices_asc = [p["price"] for p in items_asc]
        assert prices_asc == sorted(prices_asc)

        # Sorting test by price desc
        p_desc = await app_client.get("/api/admin/products?sort_by=price&sort_order=desc&limit=10")
        assert p_desc.status_code == 200
        items_desc = p_desc.json()["items"]
        prices_desc = [p["price"] for p in items_desc]
        assert prices_desc == sorted(prices_desc, reverse=True)

    @pytest.mark.asyncio
    async def test_customers_pagination(self, app_client: AsyncClient) -> None:
        for i in range(1, 4):
            await app_client.post(
                "/api/admin/customers",
                json={
                    "platform": "website",
                    "platform_user_id": f"cust_pg_{i}",
                    "name": f"Khách Hàng PG {i}",
                },
            )

        resp = await app_client.get("/api/admin/customers?page=1&limit=2")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert data["page"] == 1
        assert data["limit"] == 2
        assert len(data["items"]) <= 2

    @pytest.mark.asyncio
    async def test_orders_pagination(self, app_client: AsyncClient) -> None:
        resp = await app_client.get("/api/admin/orders?page=1&limit=2")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert data["page"] == 1
        assert data["limit"] == 2


class TestPhase12CSVExport:
    """Tests for UTF-8 with BOM CSV streaming exports."""

    @pytest.mark.asyncio
    async def test_customers_csv_export(self, app_client: AsyncClient) -> None:
        resp = await app_client.get("/api/admin/customers/export")
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]
        assert "attachment" in resp.headers.get("content-disposition", "")
        # UTF-8 BOM check: b'\xef\xbb\xbf'
        assert resp.content.startswith(b"\xef\xbb\xbf")
        text = resp.content.decode("utf-8-sig")
        assert "Mã khách" in text
        assert "Họ và tên" in text

    @pytest.mark.asyncio
    async def test_orders_csv_export(self, app_client: AsyncClient) -> None:
        resp = await app_client.get("/api/admin/orders/export")
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]
        assert "attachment" in resp.headers.get("content-disposition", "")
        # UTF-8 BOM check: b'\xef\xbb\xbf'
        assert resp.content.startswith(b"\xef\xbb\xbf")
        text = resp.content.decode("utf-8-sig")
        assert "Mã đơn" in text
        assert "Tổng tiền (VNĐ)" in text


class TestPhase13QuickReplies:
    """Tests for Quick Reply canned response template management."""

    @pytest.mark.asyncio
    async def test_quick_replies_crud(self, app_client: AsyncClient) -> None:
        # 1. Create quick reply
        create_payload = {
            "title": "Mẫu hướng dẫn thanh toán",
            "shortcut": "/testpay",
            "content": "Quý khách vui lòng chuyển khoản theo mã QR đính kèm.",
            "category": "payment",
        }
        res_create = await app_client.post("/api/admin/quick-replies", json=create_payload)
        assert res_create.status_code == 200
        created = res_create.json()
        qr_id = created["id"]
        assert created["shortcut"] == "/testpay"
        assert created["title"] == "Mẫu hướng dẫn thanh toán"

        # 2. Prevent duplicate shortcut
        res_dup = await app_client.post("/api/admin/quick-replies", json=create_payload)
        assert res_dup.status_code == 400

        # 3. List and search quick replies
        res_list = await app_client.get("/api/admin/quick-replies?category=payment")
        assert res_list.status_code == 200
        assert any(q["id"] == qr_id for q in res_list.json())

        res_search = await app_client.get("/api/admin/quick-replies?search=/testpay")
        assert res_search.status_code == 200
        assert any(q["id"] == qr_id for q in res_search.json())

        # 4. Update quick reply
        update_payload = {
            "title": "Mẫu chuyển khoản VietQR mới",
            "content": "Quét mã VietQR chuyển khoản nhanh 24/7.",
        }
        res_up = await app_client.put(f"/api/admin/quick-replies/{qr_id}", json=update_payload)
        assert res_up.status_code == 200
        assert res_up.json()["title"] == "Mẫu chuyển khoản VietQR mới"

        # 5. Delete quick reply
        res_del = await app_client.delete(f"/api/admin/quick-replies/{qr_id}")
        assert res_del.status_code == 200
        assert res_del.json()["success"] is True

        # Verify not found on update
        res_del_404 = await app_client.delete(f"/api/admin/quick-replies/{qr_id}")
        assert res_del_404.status_code == 404


class TestPhase13CustomerTaggingAndNotifications:
    """Tests for Customer tagging system and notification center."""

    @pytest.mark.asyncio
    async def test_customer_tagging_management(self, app_client: AsyncClient) -> None:
        # Create customer
        cust_resp = await app_client.post(
            "/api/admin/customers",
            json={
                "platform": "facebook",
                "platform_user_id": "fb_tag_test_01",
                "name": "Nguyễn Thị VIP",
            },
        )
        assert cust_resp.status_code == 200
        cust_id = cust_resp.json()["id"]

        # Add tags: VIP and Cần tư vấn thêm
        tag_payload = {"tags": {"labels": ["VIP", "Cần tư vấn thêm"], "priority": "high"}}
        res_tag = await app_client.put(f"/api/admin/customers/{cust_id}", json=tag_payload)
        assert res_tag.status_code == 200
        assert res_tag.json()["tags"]["labels"] == ["VIP", "Cần tư vấn thêm"]

        # Remove a tag ("Cần tư vấn thêm") and add "Đã chốt"
        tag_payload_2 = {"tags": {"labels": ["VIP", "Đã chốt"]}}
        res_tag_2 = await app_client.put(f"/api/admin/customers/{cust_id}", json=tag_payload_2)
        assert res_tag_2.status_code == 200
        assert res_tag_2.json()["tags"]["labels"] == ["VIP", "Đã chốt"]
        assert "Cần tư vấn thêm" not in res_tag_2.json()["tags"]["labels"]

    @pytest.mark.asyncio
    async def test_notification_center_endpoints(self, app_client: AsyncClient) -> None:
        res = await app_client.get("/api/admin/notifications")
        assert res.status_code == 200
        assert isinstance(res.json(), list)

        # Mark read
        res_read = await app_client.post("/api/admin/notifications/mark-read")
        assert res_read.status_code == 200
        assert res_read.json()["success"] is True

        # Verify notifications are now marked read
        res_after = await app_client.get("/api/admin/notifications")
        assert res_after.status_code == 200
        notifs = res_after.json()
        assert all(n["is_read"] is True and n["read"] is True for n in notifs)


class TestPhase11InfrastructureAndBackups:
    """Tests for database backups and dual database driver compatibility."""

    def test_perform_backup_utility(self) -> None:
        result = perform_backup()
        assert result["status"] == "success"
        assert "timestamp" in result
        assert "files" in result
        assert "manifest" in result
        assert len(result["files"]) >= 1

    @pytest.mark.asyncio
    async def test_system_backup_endpoint(self, app_client: AsyncClient) -> None:
        resp = await app_client.post("/api/admin/system/backup")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "files" in data
        assert "manifest" in data
        assert data["total_size_bytes"] >= 0

    @pytest.mark.asyncio
    async def test_get_latest_backup_endpoint(self, app_client: AsyncClient) -> None:
        resp = await app_client.get("/api/admin/system/backup/latest")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("success", "none")

    def test_dual_database_engine_configuration(self) -> None:
        from unittest.mock import patch

        # Test postgres engine parameters
        with patch("app.database.session.create_async_engine") as mock_create:
            get_engine("postgresql+asyncpg://user:pass@localhost:5432/testdb")
            mock_create.assert_called_once()
            _, kwargs = mock_create.call_args
            assert kwargs["pool_size"] == 10
            assert kwargs["max_overflow"] == 20
            assert kwargs["pool_pre_ping"] is True
            assert kwargs["pool_recycle"] == 3600

        # Test sqlite engine parameters
        sqlite_engine = get_engine("sqlite+aiosqlite:///:memory:")
        assert sqlite_engine is not None

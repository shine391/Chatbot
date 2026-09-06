"""Unit tests for Admin Product Catalog CRUD and Media Upload API."""

import io

import pytest
from httpx import AsyncClient


class TestAdminProductCatalog:
    @pytest.mark.asyncio
    async def test_upload_image_media(self, app_client: AsyncClient) -> None:
        """Test uploading product image file."""
        file_bytes = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"fake_image_content"
        files = {"file": ("test_product.jpg", io.BytesIO(file_bytes), "image/jpeg")}

        resp = await app_client.post("/api/admin/media/upload", files=files)
        assert resp.status_code == 200
        data = resp.json()
        assert "url" in data
        assert data["url"].startswith("/static/uploads/")
        assert data["url"].endswith(".jpg")
        assert data["content_type"] == "image/jpeg"

    @pytest.mark.asyncio
    async def test_upload_invalid_media_rejected(self, app_client: AsyncClient) -> None:
        """Test uploading disallowed file types (e.g. .txt)."""
        files = {"file": ("malicious.txt", io.BytesIO(b"hello text"), "text/plain")}
        resp = await app_client.post("/api/admin/media/upload", files=files)
        assert resp.status_code == 400
        assert "Chỉ hỗ trợ tải lên file hình ảnh hoặc video" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_product_crud_and_search(self, app_client: AsyncClient) -> None:
        """Test creating, updating, searching, and deleting a product."""
        # 1. Create product
        payload = {
            "sku": "CRUD-BAG-01",
            "name": "Túi Tote Da Thật Handmade",
            "description": "Túi xách nữ thanh lịch cao cấp",
            "price": 1500000.0,
            "discount_price": 1200000.0,
            "images": ["/static/uploads/bag1.jpg"],
            "videos": ["/static/uploads/bag1.mp4"],
            "website_url": "https://shop.vn/tote-01",
            "tags": ["túi tote", "handmade"],
        }
        res_create = await app_client.post("/api/admin/products", json=payload)
        assert res_create.status_code == 200
        prod = res_create.json()
        prod_id = prod["id"]
        assert prod["sku"] == "CRUD-BAG-01"
        assert prod["price"] == 1500000.0

        # 2. Search product by keyword
        res_search = await app_client.get("/api/admin/products?search=Handmade")
        assert res_search.status_code == 200
        matched_json = res_search.json()
        matched = (
            matched_json["items"]
            if isinstance(matched_json, dict) and "items" in matched_json
            else matched_json
        )
        assert len(matched) >= 1
        assert any(p["id"] == prod_id for p in matched)

        # 3. Update product
        update_payload = {
            "name": "Túi Tote Da Thật Handmade Bản Mới",
            "price": 1600000.0,
            "discount_price": 1350000.0,
            "tags": ["túi tote", "handmade", "new"],
        }
        res_update = await app_client.put(f"/api/admin/products/{prod_id}", json=update_payload)
        assert res_update.status_code == 200
        updated = res_update.json()
        assert updated["name"] == "Túi Tote Da Thật Handmade Bản Mới"
        assert updated["price"] == 1600000.0
        assert "new" in updated["tags"]

        # 4. Delete product
        res_del = await app_client.delete(f"/api/admin/products/{prod_id}")
        assert res_del.status_code == 200
        assert res_del.json()["success"] is True

        # 5. Verify deleted
        res_list = await app_client.get("/api/admin/products")
        list_json = res_list.json()
        items_remaining = (
            list_json["items"]
            if isinstance(list_json, dict) and "items" in list_json
            else list_json
        )
        assert not any(p["id"] == prod_id for p in items_remaining)

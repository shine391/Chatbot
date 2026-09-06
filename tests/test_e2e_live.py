"""End-to-End Live Integration Test for AI Customer Service Agent.

This test validates the entire real flow using FastAPI's TestClient without
mocking any catalog service, router, or database modules.
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

# Ensure project root in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database.session import close_db, get_engine, get_session_factory, init_db
from app.main import app
from app.models.product import Category, Product


def seed_real_catalog_data() -> None:
    """Seed real category and products directly into the database."""

    async def _seed() -> None:
        engine = get_engine()
        await init_db(engine)
        session_factory = get_session_factory(engine)
        async with session_factory() as session:
            # Check or create 'Túi da' category
            res = await session.execute(select(Category).where(Category.slug == "tui-da"))
            cat = res.scalars().first()
            if not cat:
                cat = Category(
                    name="Túi da", slug="tui-da", description="Túi da thời trang cao cấp"
                )
                session.add(cat)
                await session.flush()

            # Seed 4 realistic leather bag products
            sample_products = [
                {
                    "sku": "TUI-01",
                    "name": "Túi xách da bò công sở cao cấp",
                    "price": 1250000.0,
                    "discount_price": 990000.0,
                    "images": ["https://shop.vn/media/tui-da-01.jpg"],
                    "website_url": "https://shop.vn/san-pham/tui-01",
                    "tags": ["túi da", "công sở"],
                },
                {
                    "sku": "TUI-02",
                    "name": "Túi đeo chéo da sáp vintage",
                    "price": 890000.0,
                    "discount_price": 750000.0,
                    "images": ["https://shop.vn/media/tui-da-02.jpg"],
                    "website_url": "https://shop.vn/san-pham/tui-02",
                    "tags": ["túi da", "vintage"],
                },
                {
                    "sku": "TUI-03",
                    "name": "Túi tote da bò dập vân thanh lịch",
                    "price": 1450000.0,
                    "discount_price": None,
                    "images": ["https://shop.vn/media/tui-da-03.jpg"],
                    "website_url": "https://shop.vn/san-pham/tui-03",
                    "tags": ["túi da", "tote"],
                },
                {
                    "sku": "TUI-04",
                    "name": "Túi trống du lịch da bò đa năng",
                    "price": 1850000.0,
                    "discount_price": 1600000.0,
                    "images": ["https://shop.vn/media/tui-da-04.jpg"],
                    "website_url": "https://shop.vn/san-pham/tui-04",
                    "tags": ["túi da", "du lịch"],
                },
            ]

            for item in sample_products:
                p_res = await session.execute(select(Product).where(Product.sku == item["sku"]))
                if not p_res.scalars().first():
                    session.add(
                        Product(
                            sku=item["sku"],
                            name=item["name"],
                            price=item["price"],
                            discount_price=item["discount_price"],
                            images=item["images"],
                            website_url=item["website_url"],
                            category_id=cat.id,
                            tags=item["tags"],
                            is_active=True,
                        )
                    )
            await session.commit()
        await close_db(engine)

    asyncio.run(_seed())


def test_e2e_live_webhook_catalog_flow() -> None:
    """End-to-End Live test:

    1. Seeds actual products into catalog database.
    2. Sends real live request to webhook: 'Cho mình xem 3 mẫu túi da'.
    3. Asserts:
       - Status code == 200
       - Products list length between 3 and 4
       - Every product contains image_url, product_url, and price.
    4. Prints full response log to terminal.
    """
    # 1. Ensure live database has real products (NO MOCKS)
    seed_real_catalog_data()

    # 2. Use real TestClient without mocking router or catalog
    with TestClient(app) as client:
        payload = {
            "session_id": "live_customer_test_001",
            "content": "Cho mình xem 3 mẫu túi da",
        }

        # Send request to webhook endpoint
        response = client.post("/webhook/chat", json=payload)

        # 3. Assertions
        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text}"
        )

        data: dict[str, Any] = response.json()

        # Display actual response for user inspection
        print("\n" + "=" * 70)
        print(">>> [LIVE E2E TEST RESPONSE LOG]")
        print("=" * 70)
        print(f"HTTP Status: {response.status_code}")
        print(f"Response Payload:\n{json.dumps(data, ensure_ascii=False, indent=2)}")
        print("=" * 70)

        # Check products list
        products = data.get("products", [])
        assert isinstance(products, list), "Field 'products' must be a list"
        assert 3 <= len(products) <= 4, f"Expected 3 to 4 products, but got {len(products)}"

        # Validate each product attributes
        for idx, item in enumerate(products, start=1):
            print(f"\nVerifying Product #{idx}: {item.get('name')} (SKU: {item.get('sku')})")
            print(f"  - price: {item.get('price')}")
            print(f"  - image_url: {item.get('image_url')}")
            print(f"  - product_url: {item.get('product_url')}")

            assert "price" in item and item["price"] is not None, f"Item #{idx} missing 'price'"
            assert "image_url" in item and item["image_url"], (
                f"Item #{idx} missing or empty 'image_url'"
            )
            assert "product_url" in item and item["product_url"], (
                f"Item #{idx} missing or empty 'product_url'"
            )

        print("\n" + "=" * 70)
        print(">>> ALL ASSERTIONS PASSED SUCCESSFULLY (100% REAL LIVE FLOW)")
        print("=" * 70 + "\n")


if __name__ == "__main__":
    pytest.main(["-s", "-v", __file__])

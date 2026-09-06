"""Unit tests for Shipping Carrier Integration (GHTK, GHN, Viettel Post, Mock)."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.database.session import get_db_session
from app.main import create_app
from app.models.customer import Customer, Platform
from app.models.order import Order, OrderStatus
from app.models.user import AdminUser
from app.services.shipping import (
    GHNShippingCarrier,
    GHTKShippingCarrier,
    MockShippingCarrier,
    ViettelPostShippingCarrier,
    get_shipping_carrier,
)


def test_shipping_carrier_factory():
    """Verify carrier factory returns correct adapter for each identifier."""
    assert isinstance(get_shipping_carrier("ghtk"), GHTKShippingCarrier)
    assert isinstance(get_shipping_carrier("ghn"), GHNShippingCarrier)
    assert isinstance(get_shipping_carrier("viettelpost"), ViettelPostShippingCarrier)
    assert isinstance(get_shipping_carrier("vtp"), ViettelPostShippingCarrier)
    assert isinstance(get_shipping_carrier("mock"), MockShippingCarrier)
    assert isinstance(get_shipping_carrier("unknown_carrier"), MockShippingCarrier)


@pytest.mark.asyncio
async def test_mock_carrier_operations():
    """Test fee calculation, shipment creation, and tracking in mock adapter."""
    carrier = MockShippingCarrier(api_token="test_token")

    # Fee estimation
    fee_data = await carrier.calculate_fee(
        province="Hà Nội",
        district="Cầu Giấy",
        ward="Dịch Vọng",
        weight_grams=500,
        order_value=250000.0,
    )
    assert "fee" in fee_data
    assert fee_data["fee"] > 0
    assert "estimated_days" in fee_data

    # Create shipment
    shipment_res = await carrier.create_shipment(
        order_id=99,
        recipient_name="Tran Thi B",
        recipient_phone="0911222333",
        shipping_address="123 Xuan Thuy",
        province="Hà Nội",
        district="Cầu Giấy",
        ward="Dịch Vọng",
        weight_grams=500,
        cod_amount=250000.0,
    )
    assert shipment_res["success"] is True
    assert shipment_res["tracking_code"].startswith("MOCK")

    # Webhook verification
    assert carrier.verify_webhook_token("test_token") is True
    assert carrier.verify_webhook_token("invalid_token") is False


@pytest.mark.asyncio
async def test_shipping_webhook_lifecycle(db_session: AsyncSession):
    """Test receiving carrier webhook, updating order status to DELIVERED, and notifying customer."""
    cust = Customer(
        platform=Platform.FACEBOOK,
        platform_user_id="fb_shipping_cust",
        name="Hoang Nam",
    )
    db_session.add(cust)
    await db_session.flush()

    order = Order(
        customer_id=cust.id,
        total_amount=350000.0,
        status=OrderStatus.PENDING,
        tracking_code="MOCK-TRACK-12345",
        carrier="mock",
    )
    db_session.add(order)
    await db_session.commit()

    app = create_app()

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db_session] = _override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Unauthorized webhook call
        unauth_res = await client.post(
            "/api/webhooks/shipping/mock",
            headers={"X-Carrier-Token": "bad_token"},
            json={"tracking_code": "MOCK-TRACK-12345", "status": "delivered"},
        )
        assert unauth_res.status_code == 401

        # 2. Authorized delivery webhook
        with patch(
            "app.services.shipping.mock_adapter.MockShippingCarrier.verify_webhook_token",
            return_value=True,
        ):
            with patch(
                "app.services.message_sender.MessageSender.send_text", new_callable=AsyncMock
            ) as mock_send_text:
                res = await client.post(
                    "/api/webhooks/shipping/mock",
                    headers={"X-Carrier-Token": "valid_token"},
                    json={
                        "tracking_code": "MOCK-TRACK-12345",
                        "status": "delivered",
                        "status_text": "Giao thành công cho người nhận",
                    },
                )
                assert res.status_code == 200
                data = res.json()
                assert data["success"] is True
                assert data["status"] == "delivered"

                # Verify order updated in database
                await db_session.refresh(order)
                assert order.status == OrderStatus.DELIVERED
                assert order.delivered_at is not None
                assert "Giao thành công" in order.carrier_status_text

                # Verify customer notification was sent
                mock_send_text.assert_called_once()
                assert "giao thành công" in mock_send_text.call_args.kwargs["text"]


@pytest.mark.asyncio
async def test_admin_shipping_estimate_and_create_shipment(db_session: AsyncSession):
    """Test admin shipping endpoints for estimating fees and creating waybills."""
    cust = Customer(
        platform=Platform.FACEBOOK,
        platform_user_id="fb_ship_adm",
        name="Le Thi C",
    )
    db_session.add(cust)
    await db_session.flush()

    order = Order(
        customer_id=cust.id,
        total_amount=400000.0,
        status=OrderStatus.CONFIRMED,
        recipient_name="Le Thi C",
        recipient_phone="0933444555",
        shipping_address="456 Nguyen Trai",
        province="Hà Nội",
        district="Thanh Xuân",
        ward="Thanh Xuân Bắc",
    )
    db_session.add(order)
    await db_session.commit()

    app = create_app()

    async def _override_get_db():
        yield db_session

    async def _override_admin() -> AdminUser:
        return AdminUser(
            id=1,
            username="admin",
            role="admin",
            is_active=True,
        )

    app.dependency_overrides[get_db_session] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_admin

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Estimate fee
        est_res = await client.post(
            "/api/admin/shipping/estimate-fee",
            json={
                "carrier": "mock",
                "province": "Hà Nội",
                "district": "Thanh Xuân",
                "ward": "Thanh Xuân Bắc",
                "weight_grams": 400,
                "order_value": 400000.0,
            },
        )
        assert est_res.status_code == 200
        assert "fee" in est_res.json()

        # Create shipment
        ship_res = await client.post(
            f"/api/admin/orders/{order.id}/shipment",
            json={
                "carrier": "mock",
                "recipient_name": "Le Thi C",
                "recipient_phone": "0933444555",
                "shipping_address": "456 Nguyen Trai, Thanh Xuan, Ha Noi",
                "province": "Hà Nội",
                "district": "Thanh Xuân",
                "ward": "Thanh Xuân Bắc",
                "weight_grams": 400,
                "cod_amount": 400000.0,
            },
        )
        assert ship_res.status_code == 200
        ship_data = ship_res.json()
        assert ship_data["success"] is True
        assert ship_data["tracking_code"].startswith("MOCK")

        # Verify order now has tracking code linked
        await db_session.refresh(order)
        assert order.tracking_code == ship_data["tracking_code"]

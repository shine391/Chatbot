"""Mock Shipping Carrier Adapter for local testing and sandbox simulation."""

import time
from typing import Any

from app.services.shipping.base import BaseShippingCarrier


class MockShippingCarrier(BaseShippingCarrier):
    """Mock carrier generating deterministic tracking codes and instant responses."""

    carrier_name: str = "mock"

    async def calculate_fee(
        self,
        province: str,
        district: str,
        ward: str | None = None,
        weight_grams: int = 500,
        order_value: float = 0.0,
    ) -> dict[str, Any]:
        base_fee = 25000.0
        # Remote provinces fee
        if any(p in province.lower() for p in ["hồ chí minh", "hà nội", "đà nẵng"]):
            shipping_fee = base_fee
        else:
            shipping_fee = base_fee + 10000.0

        if weight_grams > 1000:
            extra_kg = (weight_grams - 1000) / 1000
            shipping_fee += extra_kg * 5000.0

        return {
            "success": True,
            "carrier": self.carrier_name,
            "fee": shipping_fee,
            "insurance_fee": 0.0,
            "estimated_days": "1-2 ngày" if shipping_fee == base_fee else "2-4 ngày",
        }

    async def create_shipment(
        self,
        order_id: int,
        recipient_name: str,
        recipient_phone: str,
        shipping_address: str,
        province: str,
        district: str,
        ward: str | None = None,
        weight_grams: int = 500,
        cod_amount: float = 0.0,
        notes: str | None = None,
    ) -> dict[str, Any]:
        ts = int(time.time())
        tracking_code = f"MOCK{order_id}{ts % 10000:04d}"
        fee_info = await self.calculate_fee(province, district, ward, weight_grams, cod_amount)
        return {
            "success": True,
            "carrier": self.carrier_name,
            "tracking_code": tracking_code,
            "shipping_fee": fee_info["fee"],
            "estimated_delivery": fee_info["estimated_days"],
            "tracking_url": f"https://tracking.mockship.vn/{tracking_code}",
            "raw_response": {"order_id": order_id, "status": "ready_to_pick"},
        }

    async def cancel_shipment(self, tracking_code: str) -> bool:
        return True

    async def get_tracking_status(self, tracking_code: str) -> dict[str, Any]:
        return {
            "tracking_code": tracking_code,
            "carrier": self.carrier_name,
            "status": "delivering",
            "status_text": "Đang giao hàng đến người nhận",
            "updated_at": "2026-09-06T00:00:00Z",
        }

    def verify_webhook_token(self, token_or_signature: str) -> bool:
        if self.api_token and token_or_signature == self.api_token:
            return True
        return token_or_signature in (
            "mock_secret_token",
            "default_verify_token",
            "my_fb_token_123",
            "",
        )

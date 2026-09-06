"""Abstract Base Class for Shipping Carrier Adapters."""

from abc import ABC, abstractmethod
from typing import Any


class BaseShippingCarrier(ABC):
    """Abstract base class establishing the contract for logistics carriers."""

    carrier_name: str = "base"

    def __init__(self, api_token: str | None = None, secret_key: str | None = None) -> None:
        self.api_token = api_token
        self.secret_key = secret_key

    @abstractmethod
    async def calculate_fee(
        self,
        province: str,
        district: str,
        ward: str | None = None,
        weight_grams: int = 500,
        order_value: float = 0.0,
    ) -> dict[str, Any]:
        """Calculate shipping fee and estimate transit days."""
        pass

    @abstractmethod
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
        """Create a new waybill/shipment with the carrier.

        Returns dict with keys:
            success: bool
            tracking_code: str
            shipping_fee: float
            estimated_delivery: str
            raw_response: dict
        """
        pass

    @abstractmethod
    async def cancel_shipment(self, tracking_code: str) -> bool:
        """Cancel an existing shipment using tracking code."""
        pass

    @abstractmethod
    async def get_tracking_status(self, tracking_code: str) -> dict[str, Any]:
        """Query current waybill tracking status."""
        pass

    @abstractmethod
    def verify_webhook_token(self, token_or_signature: str) -> bool:
        """Verify authenticity of webhook payload from carrier."""
        pass

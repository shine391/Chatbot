"""Shipping carrier integration adapters package."""

from typing import Any

from app.services.shipping.base import BaseShippingCarrier
from app.services.shipping.ghn_adapter import GHNShippingCarrier
from app.services.shipping.ghtk_adapter import GHTKShippingCarrier
from app.services.shipping.mock_adapter import MockShippingCarrier
from app.services.shipping.viettelpost_adapter import ViettelPostShippingCarrier


def get_shipping_carrier(
    carrier_name: str,
    api_token: str | None = None,
    secret_key: str | None = None,
    **kwargs: Any,
) -> BaseShippingCarrier:
    """Factory creating appropriate shipping carrier adapter instance."""
    normalized = (carrier_name or "mock").strip().lower()

    if normalized == "ghtk":
        return GHTKShippingCarrier(api_token=api_token, secret_key=secret_key, **kwargs)
    elif normalized == "ghn":
        return GHNShippingCarrier(api_token=api_token, secret_key=secret_key, **kwargs)
    elif normalized in ("viettelpost", "vtp"):
        return ViettelPostShippingCarrier(api_token=api_token, secret_key=secret_key, **kwargs)
    else:
        return MockShippingCarrier(api_token=api_token, secret_key=secret_key)


__all__ = [
    "BaseShippingCarrier",
    "GHNShippingCarrier",
    "GHTKShippingCarrier",
    "MockShippingCarrier",
    "ViettelPostShippingCarrier",
    "get_shipping_carrier",
]

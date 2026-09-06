"""Pydantic schemas for Shipping Carrier Integration."""

from pydantic import BaseModel, Field


class ShippingCalculationRequest(BaseModel):
    """Request payload for estimating shipping fee."""

    carrier: str = Field(..., description="Carrier name (ghtk, ghn, viettelpost, mock)")
    province: str = Field(..., min_length=1)
    district: str = Field(..., min_length=1)
    ward: str | None = None
    weight_grams: int = Field(500, ge=1)
    order_value: float = Field(0.0, ge=0.0)


class ShippingCalculationResponse(BaseModel):
    """Calculated shipping fee estimate."""

    carrier: str
    fee: float
    insurance_fee: float = 0.0
    estimated_days: str = "2-3 ngày"


class CreateShipmentRequest(BaseModel):
    """Request to create carrier tracking number and dispatch order."""

    carrier: str = Field("mock", description="Carrier name (ghtk, ghn, viettelpost, mock)")
    recipient_name: str | None = None
    recipient_phone: str | None = None
    shipping_address: str | None = None
    province: str | None = None
    district: str | None = None
    ward: str | None = None
    weight_grams: int = 500
    cod_amount: float = 0.0
    note: str | None = None


class ShipmentDetailResponse(BaseModel):
    """Result of shipment creation."""

    success: bool
    carrier: str
    tracking_code: str
    shipping_fee: float
    estimated_delivery: str | None = None
    message: str | None = None

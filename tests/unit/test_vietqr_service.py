"""Unit tests for VietQR payment service."""

from app.services.vietqr_service import VietQRService


def test_vietqr_url_generation() -> None:
    """Should generate standard Napas 247 image URL with correct query params."""
    service = VietQRService(
        bank_code="TCB",
        account_number="123456789",
        account_name="SHOP DEMO",
    )
    url = service.generate_qr_url(amount=550000, memo="DH102")
    assert "https://img.vietqr.io/image/970407-123456789-compact2.png" in url
    assert "amount=550000" in url
    assert "addInfo=DH102" in url
    assert "accountName=SHOP+DEMO" in url


def test_vietqr_order_payment_package() -> None:
    """Should return full payment payload with formatted instructions."""
    service = VietQRService(
        bank_code="VCB",
        account_number="987654321",
        account_name="LEATHER SHOP",
    )
    payment = service.generate_order_payment(order_id=456, amount=1200000)
    assert payment["order_id"] == 456
    assert payment["bank_bin"] == "970436"  # Vietcombank BIN
    assert payment["transfer_memo"] == "DH456"
    assert payment["formatted_amount"] == "1,200,000đ"
    assert "1,200,000đ" in payment["instructions"]
    assert "DH456" in payment["instructions"]
    assert payment["qr_image_url"].startswith("https://img.vietqr.io/image/")

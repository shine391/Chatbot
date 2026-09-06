"""VietQR payment generator service adhering to Napas 247 banking standards."""

import logging
from typing import Any
from urllib.parse import quote_plus

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Popular Bank BIN mappings
BANK_BINS = {
    "TCB": "970407",  # Techcombank
    "VCB": "970436",  # Vietcombank
    "MB": "970422",  # MBBank
    "ACB": "970416",  # ACB
    "VPB": "970432",  # VPBank
    "BIDV": "970418",  # BIDV
    "CTG": "970415",  # VietinBank
}


class VietQRService:
    """Generates dynamic Napas 247 VietQR codes and payment instructions for checkout."""

    def __init__(
        self,
        bank_code: str = "TCB",
        account_number: str = "19036588999018",
        account_name: str = "NGUYEN VAN SHOP",
    ) -> None:
        self.bank_code = bank_code.upper()
        self.bank_bin = BANK_BINS.get(self.bank_code, "970407")
        self.account_number = account_number
        self.account_name = account_name

    @classmethod
    async def from_settings(cls, session: AsyncSession) -> "VietQRService":
        """Construct VietQRService using dynamic settings from database."""
        from app.services.settings_service import SettingsService

        settings_service = SettingsService(session)
        bank_code = (await settings_service.get_setting("vietqr_bank_code", "TCB")) or "TCB"
        account_number = (
            await settings_service.get_setting("vietqr_account_number", "19036588999018")
        ) or "19036588999018"
        account_name = (
            await settings_service.get_setting("vietqr_account_name", "NGUYEN VAN SHOP")
        ) or "NGUYEN VAN SHOP"
        return cls(
            bank_code=bank_code,
            account_number=account_number,
            account_name=account_name,
        )

    def generate_qr_url(
        self,
        amount: int | float,
        memo: str,
    ) -> str:
        """Construct Napas 247 VietQR dynamic image URL."""
        amount_int = int(amount)
        encoded_memo = quote_plus(memo)
        encoded_name = quote_plus(self.account_name)
        return (
            f"https://img.vietqr.io/image/{self.bank_bin}-{self.account_number}-compact2.png"
            f"?amount={amount_int}&addInfo={encoded_memo}&accountName={encoded_name}"
        )

    def generate_order_payment(
        self,
        order_id: int,
        amount: int | float,
    ) -> dict[str, Any]:
        """Generate complete payment package including QR code, memo, and formatted bank guide."""
        amount_int = int(amount)
        memo = f"DH{order_id}"
        qr_url = self.generate_qr_url(amount=amount_int, memo=memo)

        instructions = (
            f"Quý khách vui lòng quét mã VietQR hoặc chuyển khoản {amount_int:,}đ "
            f"tới ngân hàng {self.bank_code} STK: {self.account_number} ({self.account_name}) "
            f"với nội dung: {memo}."
        )

        return {
            "order_id": order_id,
            "bank_code": self.bank_code,
            "bank_bin": self.bank_bin,
            "account_number": self.account_number,
            "account_name": self.account_name,
            "amount": amount_int,
            "formatted_amount": f"{amount_int:,}đ",
            "transfer_memo": memo,
            "qr_image_url": qr_url,
            "instructions": instructions,
        }

"""Intent detection module for categorizing customer queries and extracting entities."""

import re
from enum import Enum


class CustomerIntent(str, Enum):
    """Classified customer inquiry intents."""

    GREETING = "greeting"
    PRODUCT_INQUIRY = "product_inquiry"
    PRODUCT_BY_CODE = "product_by_code"
    CATALOG_REQUEST = "catalog_request"
    ORDER_STATUS = "order_status"
    COMPLAINT = "complaint"
    HUMAN_ESCALATION = "human_escalation"
    GENERAL_FAQ = "general_faq"


class IntentDetector:
    """Detects customer intent and extracts parameters (SKU, categories)."""

    def __init__(self) -> None:
        # Regex patterns for SKUs like SP001, TD002, PK123, #1234
        self.sku_pattern = re.compile(
            r"\b(?:mã\s*(?:sp)?[:\s]*)?([a-zA-Z]{2,4}\d{2,5})\b", re.IGNORECASE
        )
        self.order_pattern = re.compile(
            r"\b(?:đơn\s*(?:hàng)?|ord|mã\s*đơn)[:\s#]*([a-zA-Z0-9_-]{4,15})\b",
            re.IGNORECASE,
        )

        self.escalation_keywords = [
            "nhân viên",
            "người thật",
            "khiếu nại",
            "quản lý",
            "hỗ trợ viên",
            "gặp người",
            "tư vấn viên",
            "chăm sóc khách hàng",
        ]

        self.greeting_keywords = [
            "chào",
            "chao",
            "hello",
            "hi ",
            "hi",
            "alo",
            "hoạt động không",
            "có ai không",
        ]

        self.catalog_keywords = [
            "catalogue",
            "catalog",
            "danh mục",
            "các mẫu",
            "mẫu nào",
            "xem thêm",
            "bộ sưu tập",
        ]

        self.category_keywords = {
            "túi da": "tui-da",
            "túi": "tui-da",
            "ví nam": "vi-da",
            "ví": "vi-da",
            "balo": "balo",
            "dây nịt": "that-lung",
            "thắt lưng": "that-lung",
        }

    def extract_sku(self, text: str) -> str | None:
        """Extract SKU or product code from customer message."""
        match = self.sku_pattern.search(text)
        if match:
            return match.group(1).upper()
        return None

    def extract_category(self, text: str) -> str | None:
        """Extract category slug from message text."""
        lowered = text.lower()
        for kw, slug in self.category_keywords.items():
            if kw in lowered:
                return slug
        return None

    def detect_intent(self, text: str) -> CustomerIntent:
        """Categorize customer intent using keyword heuristics and pattern matching."""
        lowered = text.lower().strip()

        # 1. Escalation check
        if any(kw in lowered for kw in self.escalation_keywords):
            return CustomerIntent.HUMAN_ESCALATION

        # 2. Order tracking
        if any(
            kw in lowered for kw in ["đơn hàng", "mã đơn", "tình trạng đơn", "tra cứu tình trạng"]
        ):
            return CustomerIntent.ORDER_STATUS

        # 3. Product by SKU code
        if self.extract_sku(text):
            return CustomerIntent.PRODUCT_BY_CODE

        # 4. Catalog / category browse request
        if any(kw in lowered for kw in self.catalog_keywords) or (
            any(cat in lowered for cat in self.category_keywords)
            and any(w in lowered for w in ["xem", "mẫu", "gửi", "có", "danh sách"])
        ):
            return CustomerIntent.CATALOG_REQUEST

        # 5. Greeting
        if any(kw in lowered for kw in self.greeting_keywords):
            return CustomerIntent.GREETING

        return CustomerIntent.PRODUCT_INQUIRY

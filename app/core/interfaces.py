"""Core interfaces, Abstract Base Classes, and contract definitions."""

from abc import ABC, abstractmethod
from typing import Any

from app.schemas.message import IncomingMessage, MessageResponse, OutgoingMessage
from app.schemas.product import CatalogResponse, ProductDetail


class BaseChannel(ABC):
    """Abstract base class for all channel adapters (Facebook, Instagram, TikTok, Website)."""

    @abstractmethod
    async def parse_incoming(self, raw_data: dict[str, Any]) -> IncomingMessage:
        """Parse raw webhook data into a standardized IncomingMessage."""
        ...

    @abstractmethod
    async def send_text(self, recipient_id: str, text: str) -> MessageResponse:
        """Send a text message to a customer."""
        ...

    @abstractmethod
    async def send_image(
        self, recipient_id: str, image_url: str, caption: str | None = None
    ) -> MessageResponse:
        """Send an image to a customer."""
        ...

    @abstractmethod
    async def send_video(
        self, recipient_id: str, video_url: str, caption: str | None = None
    ) -> MessageResponse:
        """Send a video to a customer."""
        ...

    @abstractmethod
    async def send_product_card(
        self, recipient_id: str, product: dict[str, Any]
    ) -> MessageResponse:
        """Send a single product card to a customer."""
        ...

    @abstractmethod
    async def send_carousel(
        self, recipient_id: str, products: list[dict[str, Any]]
    ) -> MessageResponse:
        """Send a carousel of 3-4 products to a customer."""
        ...

    @abstractmethod
    def verify_webhook(
        self, headers: dict[str, str], body: bytes, params: dict[str, str] | None = None
    ) -> bool:
        """Verify incoming webhook signature/token."""
        ...


class BaseAIEngine(ABC):
    """Abstract base class for AI conversation engines."""

    @abstractmethod
    async def generate_reply(
        self,
        incoming: IncomingMessage,
        conversation_history: list[dict[str, Any]] | None = None,
        custom_persona: str | None = None,
    ) -> OutgoingMessage:
        """Generate response for an incoming message given history, persona, and context."""
        ...


class BaseProductCatalog(ABC):
    """Abstract base class for product catalog services."""

    @abstractmethod
    async def search_products(self, query: str, limit: int = 4) -> list[ProductDetail]:
        """Search products by keyword/intent."""
        ...

    @abstractmethod
    async def get_by_sku(self, sku: str) -> ProductDetail | None:
        """Retrieve product by exact SKU."""
        ...

    @abstractmethod
    async def get_catalog_by_category(self, category_slug: str, limit: int = 4) -> CatalogResponse:
        """Get 3-4 catalog items by category."""
        ...


class BaseNotificationService(ABC):
    """Abstract base class for staff notification/escalation (Telegram, Messenger)."""

    @abstractmethod
    async def notify_human_agent(
        self,
        customer_id: str,
        reason: str,
        recent_messages: list[dict[str, Any]],
    ) -> bool:
        """Alert human agent via Telegram or Messenger."""
        ...


class BaseUpsaleService(ABC):
    """Abstract base class for post-sale care and upsell campaigns (e.g. 7 days post-purchase)."""

    @abstractmethod
    async def check_and_trigger_upsales(self) -> int:
        """Scan delivered orders past delay threshold and dispatch upsell messages."""
        ...

    @abstractmethod
    async def build_upsale_message(self, order_id: int) -> OutgoingMessage | None:
        """Construct personalized upsell message with related products (3-4 items) and discount."""
        ...

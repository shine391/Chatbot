"""Unit tests for Phase 3: AI Engine, Intent Detector, Response Builder, and Knowledge Base."""

import pytest

from app.core.intent_detector import CustomerIntent, IntentDetector
from app.core.response_builder import ResponseBuilder
from app.schemas.message import ChannelType, IncomingMessage, OutgoingMessage
from app.schemas.product import ProductCard, ProductDetail

# ===========================================================================
# 1. Intent Detector Tests
# ===========================================================================


class TestIntentDetector:
    """Test natural language intent classification for Vietnamese customer queries."""

    @pytest.fixture
    def detector(self) -> IntentDetector:
        return IntentDetector()

    def test_greeting_intent(self, detector: IntentDetector) -> None:
        intents = [
            "Chào shop",
            "hello bot",
            "alo shop ơi",
            "Shop còn hoạt động không?",
        ]
        for query in intents:
            result = detector.detect_intent(query)
            assert result == CustomerIntent.GREETING

    def test_product_by_code_intent(self, detector: IntentDetector) -> None:
        queries = [
            "Cho mình xin thông tin mã SP001",
            "Mã túi TD002 giá bao nhiêu?",
            "sp003 còn hàng không",
            "Mã SP: PK123",
        ]
        for query in queries:
            result = detector.detect_intent(query)
            assert result == CustomerIntent.PRODUCT_BY_CODE
            sku = detector.extract_sku(query)
            assert sku is not None
            assert len(sku) >= 3

    def test_catalog_request_intent(self, detector: IntentDetector) -> None:
        queries = [
            "Gửi mình xem catalogue túi da",
            "Cho mình xem các mẫu túi da với",
            "Bên shop có mẫu ví nam nào đẹp không",
            "Xem danh mục balo",
        ]
        for query in queries:
            result = detector.detect_intent(query)
            assert result == CustomerIntent.CATALOG_REQUEST
            category = detector.extract_category(query)
            assert category is not None

    def test_human_escalation_intent(self, detector: IntentDetector) -> None:
        queries = [
            "Gặp nhân viên tư vấn giúp tôi",
            "Cho nói chuyện với người thật",
            "Tôi muốn khiếu nại dịch vụ",
            "Gọi quản lý ra đây",
            "Cần gặp hỗ trợ viên gấp",
        ]
        for query in queries:
            result = detector.detect_intent(query)
            assert result == CustomerIntent.HUMAN_ESCALATION

    def test_order_status_intent(self, detector: IntentDetector) -> None:
        queries = [
            "Đơn hàng của mình tới đâu rồi?",
            "Kiểm tra mã đơn #ORD12345",
            "Tra cứu tình trạng đơn",
        ]
        for query in queries:
            result = detector.detect_intent(query)
            assert result == CustomerIntent.ORDER_STATUS


# ===========================================================================
# 2. Response Builder Tests
# ===========================================================================


class TestResponseBuilder:
    """Test building structured responses matching each channel requirements."""

    @pytest.fixture
    def builder(self) -> ResponseBuilder:
        return ResponseBuilder()

    @pytest.fixture
    def mock_product(self) -> ProductDetail:
        return ProductDetail(
            id=1,
            sku="SP001",
            name="Túi da bò cao cấp",
            description="Da thật 100%, bảo hành 1 năm",
            price=1200000.0,
            discount_price=999000.0,
            images=["https://shop.com/images/sp001.jpg"],
            videos=["https://shop.com/videos/sp001.mp4"],
            website_url="https://shop.com/sp001",
            tags=["túi da", "cao cấp"],
        )

    @pytest.fixture
    def mock_catalog_cards(self) -> list[ProductCard]:
        return [
            ProductCard(
                sku="SP001",
                name="Túi da bò cao cấp",
                price=1200000.0,
                discount_price=999000.0,
                image_url="https://shop.com/sp001.jpg",
                website_url="https://shop.com/sp001",
            ),
            ProductCard(
                sku="SP002",
                name="Túi clutch da",
                price=850000.0,
                image_url="https://shop.com/sp002.jpg",
                website_url="https://shop.com/sp002",
            ),
            ProductCard(
                sku="SP003",
                name="Túi xách vintage",
                price=1500000.0,
                image_url="https://shop.com/sp003.jpg",
                website_url="https://shop.com/sp003",
            ),
            ProductCard(
                sku="SP004",
                name="Ví da nam",
                price=650000.0,
                image_url="https://shop.com/sp004.jpg",
                website_url="https://shop.com/sp004",
            ),
        ]

    def test_build_product_detail_response_facebook(
        self, builder: ResponseBuilder, mock_product: ProductDetail
    ) -> None:
        msg = builder.build_product_detail_response(
            recipient_id="FB_USER_1",
            channel=ChannelType.FACEBOOK,
            product=mock_product,
        )
        assert msg.recipient_id == "FB_USER_1"
        assert msg.channel == ChannelType.FACEBOOK
        assert msg.message_type == "product_card"
        assert len(msg.products) == 1
        assert msg.products[0]["sku"] == "SP001"
        assert "999,000" in (msg.content or "") or "SP001" in (msg.content or "")

    def test_build_catalog_carousel_response(
        self, builder: ResponseBuilder, mock_catalog_cards: list[ProductCard]
    ) -> None:
        """Catalog must present 3-4 products in a carousel."""
        msg = builder.build_catalog_carousel_response(
            recipient_id="IG_USER_1",
            channel=ChannelType.INSTAGRAM,
            category_name="Túi da",
            products=mock_catalog_cards,
        )
        assert msg.recipient_id == "IG_USER_1"
        assert msg.channel == ChannelType.INSTAGRAM
        assert msg.message_type == "carousel"
        assert 3 <= len(msg.products) <= 4
        assert any("Túi da bò cao cấp" in p["name"] for p in msg.products)

    def test_build_escalation_response(self, builder: ResponseBuilder) -> None:
        msg = builder.build_escalation_response(
            recipient_id="USER_99",
            channel=ChannelType.WEBSITE,
            reason="Yêu cầu hỗ trợ từ nhân viên",
        )
        assert msg.recipient_id == "USER_99"
        assert msg.channel == ChannelType.WEBSITE
        assert "nhân viên" in (msg.content or "").lower()
        assert len(msg.quick_replies) > 0


# ===========================================================================
# 3. AI Engine Tests (Mocking LLM backend)
# ===========================================================================


class TestAIEngine:
    """Test AI Engine conversational routing, fallback, and tool usage."""

    @pytest.mark.asyncio
    async def test_ai_engine_handles_greeting(self) -> None:
        from app.core.ai_engine import GeminiAIEngine

        engine = GeminiAIEngine()
        incoming = IncomingMessage(
            sender_id="FB_USER_100",
            channel=ChannelType.FACEBOOK,
            content="Xin chào shop, shop có những mặt hàng gì?",
        )
        reply: OutgoingMessage = await engine.generate_reply(incoming)
        assert reply.recipient_id == "FB_USER_100"
        assert reply.channel == ChannelType.FACEBOOK
        assert reply.content is not None
        assert len(reply.content) > 0

    @pytest.mark.asyncio
    async def test_ai_engine_escalates_when_requested(self) -> None:
        from app.core.ai_engine import GeminiAIEngine

        engine = GeminiAIEngine()
        incoming = IncomingMessage(
            sender_id="FB_USER_101",
            channel=ChannelType.FACEBOOK,
            content="Tôi muốn gặp nhân viên thật ngay lập tức",
        )
        reply: OutgoingMessage = await engine.generate_reply(incoming)
        assert reply.recipient_id == "FB_USER_101"
        assert "nhân viên" in (reply.content or "").lower()

    @pytest.mark.asyncio
    async def test_ai_engine_generates_reply_via_router(self) -> None:
        from app.core.ai_engine import GeminiAIEngine
        from app.core.llm_providers.base import BaseLLMProvider, LLMResponse
        from app.core.llm_router import LLMRouter

        class CustomProvider(BaseLLMProvider):
            @property
            def provider_name(self) -> str:
                return "custom_test"

            @property
            def model_name(self) -> str:
                return "test-model"

            async def generate_response(self, *args, **kwargs) -> LLMResponse:
                return LLMResponse(
                    content="Dạ da bò sáp bên shop là da bò thật 100% cực kỳ bền đẹp ạ!",
                    provider="custom_test",
                    model="test-model",
                    latency_ms=150.0,
                )

        router = LLMRouter()
        router.register_provider("custom_test", CustomProvider())

        engine = GeminiAIEngine(router=router)
        incoming = IncomingMessage(
            sender_id="USER_INQUIRY_1",
            channel=ChannelType.WEBSITE,
            content="Da bò sáp dùng có bền không shop?",
        )
        reply = await engine.generate_reply(incoming)
        assert reply.recipient_id == "USER_INQUIRY_1"
        assert "da bò sáp" in (reply.content or "").lower()
        assert "bền đẹp" in (reply.content or "").lower()

    @pytest.mark.asyncio
    async def test_ai_engine_falls_back_when_no_provider(self) -> None:
        from app.core.ai_engine import GeminiAIEngine
        from app.core.llm_router import LLMRouter

        empty_router = LLMRouter()
        engine = GeminiAIEngine(router=empty_router)
        incoming = IncomingMessage(
            sender_id="USER_FALLBACK_1",
            channel=ChannelType.WEBSITE,
            content="Chính sách bảo hành như thế nào?",
        )
        reply = await engine.generate_reply(incoming)
        assert reply.recipient_id == "USER_FALLBACK_1"
        assert "bảo hành" in (reply.content or "").lower()


# ===========================================================================
# 4. Knowledge Base & Vector Store Tests
# ===========================================================================


class TestKnowledgeStore:
    """Test Vector Store and FAQ retrieval."""

    def test_knowledge_retriever_query(self) -> None:
        from app.knowledge.vector_store import KnowledgeStore

        store = KnowledgeStore()
        # Search returns relevant context snippet for policies
        results = store.search_faq("Chính sách đổi trả hàng như thế nào?")
        assert isinstance(results, list)
        assert len(results) > 0
        assert any("đổi trả" in r.lower() or "bảo hành" in r.lower() for r in results)

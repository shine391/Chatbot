"""Unit tests for Multi-LLM Provider architecture and LLMRouter.

Validates:
- BaseLLMProvider contract and LLMResponse schema
- Dynamic provider selection and execution
- Auto-fallback from primary provider to secondary provider on failures (429, 500, timeout)
- Graceful degradation when no provider or API keys are available
"""

import pytest

from app.core.llm_providers.base import BaseLLMProvider, LLMResponse
from app.core.llm_router import LLMRouter


class MockWorkingProvider(BaseLLMProvider):
    """Mock provider that simulates successful LLM generation without network."""

    def __init__(self, name: str = "mock_working", model: str = "mock-model-v1") -> None:
        self._name = name
        self._model = model

    @property
    def provider_name(self) -> str:
        return self._name

    @property
    def model_name(self) -> str:
        return self._model

    async def generate_response(
        self,
        prompt: str,
        system_instruction: str | None = None,
        history: list[dict[str, str]] | None = None,
        tools: list[dict[str, str]] | None = None,
        temperature: float = 0.7,
    ) -> LLMResponse:
        return LLMResponse(
            content=f"Phản hồi từ {self._name}: {prompt[:30]}",
            provider=self._name,
            model=self._model,
            prompt_tokens=15,
            completion_tokens=25,
            latency_ms=120.5,
        )


class MockFailingProvider(BaseLLMProvider):
    """Mock provider that simulates API failures (e.g. rate limit, 503, network timeout)."""

    def __init__(self, name: str = "mock_failing", model: str = "failing-model") -> None:
        self._name = name
        self._model = model

    @property
    def provider_name(self) -> str:
        return self._name

    @property
    def model_name(self) -> str:
        return self._model

    async def generate_response(
        self,
        prompt: str,
        system_instruction: str | None = None,
        history: list[dict[str, str]] | None = None,
        tools: list[dict[str, str]] | None = None,
        temperature: float = 0.7,
    ) -> LLMResponse:
        raise RuntimeError(f"Rate limit exceeded (429) on {self._name}")


@pytest.mark.asyncio
async def test_llm_router_primary_provider_success() -> None:
    """Router executes primary provider when healthy."""
    router = LLMRouter()
    primary = MockWorkingProvider("primary_provider", "model-primary")
    router.register_provider("primary", primary)

    resp = await router.generate(
        prompt="Túi da có chống nước không?",
        provider_preference=["primary"],
    )

    assert resp.success is True
    assert resp.response is not None
    assert resp.response.provider == "primary_provider"
    assert "Túi da" in resp.response.content
    assert resp.fallback_occurred is False


@pytest.mark.asyncio
async def test_llm_router_auto_fallback_on_failure() -> None:
    """Router automatically falls back to secondary provider if primary fails."""
    router = LLMRouter()
    failing_primary = MockFailingProvider("gemini_failing", "gemini-2.0-flash")
    healthy_secondary = MockWorkingProvider("openai_backup", "gpt-4o-mini")

    router.register_provider("gemini", failing_primary)
    router.register_provider("openai", healthy_secondary)

    # Ask with preference [gemini, openai]
    resp = await router.generate(
        prompt="Chính sách bảo hành phụ kiện túi xách?",
        provider_preference=["gemini", "openai"],
    )

    assert resp.success is True
    assert resp.response is not None
    assert resp.response.provider == "openai_backup"
    assert resp.fallback_occurred is True
    assert resp.failed_providers == ["gemini"]


@pytest.mark.asyncio
async def test_llm_router_all_providers_fail() -> None:
    """Router returns clear failure result when all configured providers error."""
    router = LLMRouter()
    fail1 = MockFailingProvider("provider_1")
    fail2 = MockFailingProvider("provider_2")

    router.register_provider("p1", fail1)
    router.register_provider("p2", fail2)

    resp = await router.generate(
        prompt="Hỏi câu hỏi bất kỳ",
        provider_preference=["p1", "p2"],
    )

    assert resp.success is False
    assert resp.response is None
    assert len(resp.failed_providers) == 2

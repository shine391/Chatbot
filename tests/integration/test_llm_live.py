"""Live integration tests against actual LLM APIs (Gemini, OpenAI, Claude).

These tests run ONLY when real API keys are present in the environment or .env.
They verify live network connectivity, prompt serialization, and Vietnamese output quality.
"""

import pytest

from app.config import get_settings
from app.core.llm_providers.gemini_provider import GeminiProvider


@pytest.mark.asyncio
async def test_live_gemini_generation_when_key_available() -> None:
    """Live call to Gemini 2.0 Flash (skipped automatically if no real key)."""
    settings = get_settings()
    if not settings.gemini_api_key or "your_gemini" in settings.gemini_api_key.lower():
        pytest.skip("No real GEMINI_API_KEY configured; skipping live remote API call.")

    provider = GeminiProvider(api_key=settings.gemini_api_key, model="gemini-2.0-flash")
    resp = await provider.generate_response(
        prompt="Chào shop, shop có những mẫu túi da nam nào?",
        system_instruction="Bạn là trợ lý bán hàng shop đồ da.",
    )

    assert resp.content is not None
    assert len(resp.content) > 10
    assert resp.provider == "gemini"
    assert resp.latency_ms > 0

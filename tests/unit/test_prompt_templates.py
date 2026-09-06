"""Unit tests for dynamic system prompt templates and multi-industry personas."""

from app.core.prompt_templates import (
    DEFAULT_COMMERCE_PERSONA,
    LEATHER_SHOP_PERSONA,
    PERSONA_PRESETS,
    build_grounded_system_prompt,
)


def test_default_commerce_persona_contents() -> None:
    """Validate that the universal commerce persona is industry-agnostic."""
    assert "chăm sóc khách hàng" in DEFAULT_COMMERCE_PERSONA.lower()
    assert "thân thiện" in DEFAULT_COMMERCE_PERSONA.lower()
    assert "sản phẩm" in DEFAULT_COMMERCE_PERSONA.lower()


def test_leather_shop_preset_contents() -> None:
    """Validate that the leather shop preset contains domain-specific guidelines."""
    assert "đồ da" in LEATHER_SHOP_PERSONA.lower()
    assert "bảo hành" in LEATHER_SHOP_PERSONA.lower()
    assert "thân thiện" in LEATHER_SHOP_PERSONA.lower()


def test_persona_presets_coverage() -> None:
    """Validate available industry presets for cosmetics, fashion, etc."""
    assert "general" in PERSONA_PRESETS
    assert "leather" in PERSONA_PRESETS
    assert "fashion" in PERSONA_PRESETS
    assert "cosmetics" in PERSONA_PRESETS


def test_build_grounded_system_prompt_with_custom_persona() -> None:
    """Validate dynamic injection of a custom persona configured by the shop owner."""
    custom_cosmetics = "Bạn là trợ lý mỹ phẩm thiên nhiên, luôn tư vấn nhẹ nhàng."
    faq_snippets = ["Q: Nguồn gốc? A: 100% thảo mộc."]
    catalog_snippets = ["SP01 - Serum dưỡng trắng - 350.000đ"]

    prompt = build_grounded_system_prompt(
        faq_context=faq_snippets,
        catalog_context=catalog_snippets,
        custom_persona=custom_cosmetics,
    )

    assert "trợ lý mỹ phẩm thiên nhiên" in prompt
    assert "Serum dưỡng trắng" in prompt
    assert "100% thảo mộc" in prompt
    # Ensure leather persona was NOT injected
    assert "đồ da" not in prompt.lower()

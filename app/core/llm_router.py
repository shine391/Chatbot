"""LLM Router managing dynamic model switching and auto-fallback."""

import time
from typing import Any

from loguru import logger

from app.config import get_settings
from app.core.llm_providers.base import BaseLLMProvider, RouterResult


class LLMRouter:
    """Manages LLM providers with automatic fallback on failure."""

    def __init__(self) -> None:
        self.providers: dict[str, BaseLLMProvider] = {}
        self.settings = get_settings()

    def register_provider(self, name: str, provider: BaseLLMProvider) -> None:
        """Register a provider instance by name."""
        self.providers[name.lower()] = provider

    def get_provider(self, name: str) -> BaseLLMProvider | None:
        """Retrieve a registered provider by name."""
        return self.providers.get(name.lower())

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        history: list[dict[str, Any]] | None = None,
        tools: list[dict[str, Any]] | None = None,
        provider_preference: list[str] | None = None,
        temperature: float = 0.7,
    ) -> RouterResult:
        """Attempt generation following the provider preference order, falling back on error."""
        if provider_preference:
            preferences = provider_preference
        else:
            preferences = []
            for default_p in [self.settings.default_llm_provider, "openai", "claude"]:
                if default_p in self.providers and default_p not in preferences:
                    preferences.append(default_p)
            for p in self.providers.keys():
                if p not in preferences:
                    preferences.append(p)

        failed_providers: list[str] = []
        fallback_occurred = False

        for idx, provider_key in enumerate(preferences):
            provider = self.get_provider(provider_key)
            if not provider:
                continue

            start_time = time.perf_counter()
            try:
                logger.info(
                    f"Invoking LLM provider '{provider.provider_name}' with model '{provider.model_name}'"
                )
                response = await provider.generate_response(
                    prompt=prompt,
                    system_instruction=system_instruction,
                    history=history,
                    tools=tools,
                    temperature=temperature,
                )
                latency = (time.perf_counter() - start_time) * 1000
                if response.latency_ms <= 0:
                    response.latency_ms = round(latency, 2)

                if idx > 0:
                    fallback_occurred = True
                    logger.warning(
                        f"Fallback succeeded on '{provider.provider_name}' after failures on: {failed_providers}"
                    )

                return RouterResult(
                    success=True,
                    response=response,
                    failed_providers=failed_providers,
                    fallback_occurred=fallback_occurred,
                )
            except Exception as e:
                logger.error(
                    f"LLM Provider '{provider.provider_name}' failed: {e}. Attempting next fallback..."
                )
                failed_providers.append(provider_key)

        return RouterResult(
            success=False,
            response=None,
            failed_providers=failed_providers,
            fallback_occurred=len(failed_providers) > 1,
            error=f"All configured LLM providers failed: {failed_providers}",
        )

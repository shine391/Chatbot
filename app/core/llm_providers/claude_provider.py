"""Anthropic Claude LLM provider implementation using httpx."""

import time
from typing import Any

import httpx

from app.config import get_settings
from app.core.llm_providers.base import BaseLLMProvider, LLMResponse


class ClaudeProvider(BaseLLMProvider):
    """Anthropic Claude provider (supports Claude 3.5 Haiku, Claude 3.5 Sonnet)."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-3-5-haiku-20241022",
    ) -> None:
        settings = get_settings()
        self._api_key = api_key or settings.anthropic_api_key
        self._model = model

    @property
    def provider_name(self) -> str:
        return "claude"

    @property
    def model_name(self) -> str:
        return self._model

    async def generate_response(
        self,
        prompt: str,
        system_instruction: str | None = None,
        history: list[dict[str, Any]] | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """Execute Anthropic messages API request."""
        if not self._api_key:
            raise ValueError("Anthropic API key is not configured.")

        messages: list[dict[str, str]] = []
        if history:
            for item in history:
                role_val = item.get("role", "customer")
                role = "user" if role_val in ["user", "customer"] else "assistant"
                text = item.get("content", "")
                if text:
                    messages.append({"role": role, "content": text})

        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": self._model,
            "max_tokens": 1024,
            "messages": messages,
            "temperature": temperature,
        }
        if system_instruction:
            payload["system"] = system_instruction

        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        start_time = time.perf_counter()
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()

        latency = (time.perf_counter() - start_time) * 1000

        text_content = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                text_content += block.get("text", "")

        usage = data.get("usage", {})

        return LLMResponse(
            content=text_content,
            provider=self.provider_name,
            model=self.model_name,
            prompt_tokens=usage.get("input_tokens", 0),
            completion_tokens=usage.get("output_tokens", 0),
            latency_ms=round(latency, 2),
        )

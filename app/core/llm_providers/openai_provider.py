"""OpenAI & DeepSeek compatible LLM provider using httpx."""

import time
from typing import Any

import httpx

from app.config import get_settings
from app.core.llm_providers.base import BaseLLMProvider, LLMResponse


class OpenAIProvider(BaseLLMProvider):
    """OpenAI compatible provider (supports GPT-4o-mini, GPT-4o, DeepSeek)."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gpt-4o-mini",
        base_url: str = "https://api.openai.com/v1",
        provider_name: str = "openai",
    ) -> None:
        settings = get_settings()
        self._api_key = api_key or settings.openai_api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._provider_name = provider_name

    @property
    def provider_name(self) -> str:
        return self._provider_name

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
        """Execute chat completion request."""
        if not self._api_key:
            raise ValueError(f"{self._provider_name.capitalize()} API key is not configured.")

        messages: list[dict[str, str]] = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})

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
            "messages": messages,
            "temperature": temperature,
        }

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        start_time = time.perf_counter()
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self._base_url}/chat/completions",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()

        latency = (time.perf_counter() - start_time) * 1000

        choice = data.get("choices", [{}])[0]
        content = choice.get("message", {}).get("content", "") or ""
        usage = data.get("usage", {})

        return LLMResponse(
            content=content,
            provider=self.provider_name,
            model=self.model_name,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            latency_ms=round(latency, 2),
        )

"""Abstract base class and schemas for LLM providers."""

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


class LLMResponse(BaseModel):
    """Standardized response schema returned by any LLM provider."""

    content: str
    provider: str
    model: str
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0


class RouterResult(BaseModel):
    """Result of an LLM router request, including fallback tracking."""

    success: bool
    response: LLMResponse | None = None
    failed_providers: list[str] = Field(default_factory=list)
    fallback_occurred: bool = False
    error: str | None = None


class BaseLLMProvider(ABC):
    """Abstract Base Class for Large Language Model providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name of the provider (e.g. 'gemini', 'openai', 'claude')."""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Model identifier (e.g. 'gemini-2.0-flash', 'gpt-4o-mini')."""
        ...

    @abstractmethod
    async def generate_response(
        self,
        prompt: str,
        system_instruction: str | None = None,
        history: list[dict[str, Any]] | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """Generate response from the underlying LLM."""
        ...

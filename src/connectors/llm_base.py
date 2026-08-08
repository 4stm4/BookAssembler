"""
Universal LLM Connector Base Interface according to Knowledge Assembly Engine (KAE) specs.

Provides LLMProviderUnavailableError, LLMRequest, LLMResponse, and BaseLLMAdapter.

Guarantees:
- Strict typing (100% mypy --strict compatible)
- Standard library dependencies only (abc, dataclasses, typing)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


class LLMProviderUnavailableError(Exception):
    """
    Raised when an LLM provider endpoint is unreachable, timed out, or unavailable.
    """
    pass


@dataclass
class LLMRequest:
    """
    Unified LLM request payload.
    """
    prompt: str
    system_prompt: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 1024
    response_format_json: bool = False


@dataclass
class LLMResponse:
    """
    Unified LLM response payload.
    """
    text_content: str
    raw_json: Optional[Dict[str, Any]] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    provider_name: str = ""


class BaseLLMAdapter(ABC):
    """
    Abstract Base Class for all LLM adapters in Knowledge Assembly Engine.
    """

    @abstractmethod
    async def generate(self, request: LLMRequest) -> LLMResponse:
        """
        Sends generation request to LLM endpoint.
        Must raise LLMProviderUnavailableError if provider fails.
        """
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """
        Checks availability of LLM provider endpoint.
        Returns True if operational, False otherwise.
        """
        pass

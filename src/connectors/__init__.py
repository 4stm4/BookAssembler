"""
Connectors module for Knowledge Assembly Engine (KAE).

Provides BaseLLMAdapter, LLMRequest, LLMResponse, LLMProviderUnavailableError,
OpenAICompatibleAdapter, and HybridLLMRouter.
"""

from src.connectors.llm_base import (
    BaseLLMAdapter,
    LLMProviderUnavailableError,
    LLMRequest,
    LLMResponse,
)
from src.connectors.openai_compatible import (
    HybridLLMRouter,
    OpenAICompatibleAdapter,
)

__all__ = [
    "BaseLLMAdapter",
    "HybridLLMRouter",
    "LLMProviderUnavailableError",
    "LLMRequest",
    "LLMResponse",
    "OpenAICompatibleAdapter",
]

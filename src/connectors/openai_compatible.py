"""
OpenAI-Compatible REST API Adapter & Hybrid LLM Router for Knowledge Assembly Engine (KAE).

Implements OpenAICompatibleAdapter and HybridLLMRouter.

Guarantees:
- Strict typing (100% mypy --strict compatible)
- Standard library dependencies only (asyncio, json, typing, urllib.request, urllib.error)
- Resilience: Failover between Primary (Colab) and Secondary (Local Ollama/llama.cpp) adapters
"""

import asyncio
import json
from typing import Any, Dict, List, Optional
import urllib.error
import urllib.request

from src.connectors.llm_base import (
    BaseLLMAdapter,
    LLMProviderUnavailableError,
    LLMRequest,
    LLMResponse,
)


class OpenAICompatibleAdapter(BaseLLMAdapter):
    """
    Adapter for any OpenAI-compatible REST API endpoint (Colab, Ollama, vLLM, llama.cpp).
    """

    def __init__(
        self,
        endpoint_url: str,
        api_key: Optional[str] = None,
        model_name: str = "default",
        provider_name: str = "openai_compatible",
        timeout: float = 30.0,
    ) -> None:
        self.endpoint_url = endpoint_url.rstrip("/")
        self.api_key = api_key or "no-key"
        self.model_name = model_name
        self.provider_name = provider_name
        self.timeout = timeout

    def _sync_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Synchronous HTTP request worker executed in thread pool.
        """
        url = self.endpoint_url
        if not url.endswith("/chat/completions"):
            url = f"{url}/v1/chat/completions"

        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        req = urllib.request.Request(url, data=data, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                resp_bytes = response.read()
                res_dict: Dict[str, Any] = json.loads(resp_bytes.decode("utf-8"))
                return res_dict
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, Exception) as exc:
            raise LLMProviderUnavailableError(
                f"LLM Provider '{self.provider_name}' at '{self.endpoint_url}' unavailable: {exc}"
            ) from exc

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """
        Sends chat completion request to OpenAI-compatible endpoint.
        """
        messages: List[Dict[str, str]] = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.append({"role": "user", "content": request.prompt})

        payload: Dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }

        if request.response_format_json:
            payload["response_format"] = {"type": "json_object"}

        try:
            res_json = await asyncio.to_thread(self._sync_request, payload)
        except LLMProviderUnavailableError:
            raise
        except Exception as exc:
            raise LLMProviderUnavailableError(
                f"Unexpected error calling provider '{self.provider_name}': {exc}"
            ) from exc

        choices = res_json.get("choices", [])
        if not choices:
            raise LLMProviderUnavailableError(
                f"Invalid response from provider '{self.provider_name}': missing 'choices'"
            )

        text_content = choices[0].get("message", {}).get("content", "")

        raw_json: Optional[Dict[str, Any]] = None
        if request.response_format_json:
            try:
                parsed = json.loads(text_content)
                if isinstance(parsed, dict):
                    raw_json = parsed
            except Exception:
                raw_json = None

        usage = res_json.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)

        return LLMResponse(
            text_content=text_content,
            raw_json=raw_json,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            provider_name=self.provider_name,
        )

    def _sync_health(self) -> bool:
        """
        Synchronous health check ping.
        """
        url = f"{self.endpoint_url}/v1/models" if not self.endpoint_url.endswith("/models") else self.endpoint_url
        headers = {"Authorization": f"Bearer {self.api_key}"}
        req = urllib.request.Request(url, headers=headers, method="GET")

        try:
            with urllib.request.urlopen(req, timeout=5.0) as response:
                return response.status in (200, 204)
        except Exception:
            return False

    async def health_check(self) -> bool:
        """
        Performs health check on provider endpoint.
        """
        try:
            return await asyncio.to_thread(self._sync_health)
        except Exception:
            return False


class HybridLLMRouter(BaseLLMAdapter):
    """
    Hybrid LLM Router managing primary (e.g. Colab) and secondary (e.g. Local Ollama) adapters.
    Provides automated failover on LLMProviderUnavailableError.
    """

    def __init__(self, adapters: List[BaseLLMAdapter]) -> None:
        if not adapters:
            raise ValueError("HybridLLMRouter requires at least one BaseLLMAdapter")
        self.adapters = list(adapters)

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """
        Iterates over adapters in order, failing over if LLMProviderUnavailableError is raised.
        """
        last_exception: Optional[Exception] = None

        for adapter in self.adapters:
            try:
                response = await adapter.generate(request)
                return response
            except LLMProviderUnavailableError as exc:
                last_exception = exc
                continue
            except Exception as exc:
                last_exception = exc
                continue

        raise LLMProviderUnavailableError(
            f"All LLM adapters in HybridLLMRouter failed. Last error: {last_exception}"
        )

    async def health_check(self) -> bool:
        """
        Returns True if at least one adapter in the pool passes health check.
        """
        for adapter in self.adapters:
            if await adapter.health_check():
                return True
        return False

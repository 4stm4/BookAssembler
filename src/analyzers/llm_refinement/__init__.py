"""
LLMRefinementAnalyzer — refines low-confidence blocks using a local LLM.

Connects to ollama (qwen2.5) on OrangePi. Sequential batch processing
with total time budget to avoid blocking the pipeline too long.

Env vars:
- LLM_AGENT_URL: ollama API base (default: http://192.168.88.199:11434)
- LLM_AGENT_MODEL: model name (default: qwen2.5:7b)
- LLM_CONFIDENCE_THRESHOLD: process blocks below this (default: 0.60)
- LLM_MAX_TOTAL_TIME: max seconds for all LLM calls (default: 300)
"""

from src.analyzers.llm_refinement.config import CONFIDENCE_THRESHOLD, MAX_TOTAL_TIME, OLLAMA_MODEL, OLLAMA_URL
from src.analyzers.llm_refinement.prompts import CLASSIFICATION_PROMPT
from src.analyzers.llm_refinement.signals import BATCH_SIZE, REQUEST_TIMEOUT, VALID_TYPES, logger
from src.analyzers.llm_refinement.analyzer import LLMRefinementAnalyzer

__all__ = [
    "BATCH_SIZE",
    "CLASSIFICATION_PROMPT",
    "CONFIDENCE_THRESHOLD",
    "LLMRefinementAnalyzer",
    "MAX_TOTAL_TIME",
    "OLLAMA_MODEL",
    "OLLAMA_URL",
    "REQUEST_TIMEOUT",
    "VALID_TYPES",
    "logger",
]

"""llm_refinement: Tunables, all overridable from the environment."""

import os

OLLAMA_URL = os.environ.get("LLM_AGENT_URL", "http://192.168.88.199:11434")

OLLAMA_MODEL = os.environ.get("LLM_AGENT_MODEL", "qwen2.5:7b")

CONFIDENCE_THRESHOLD = float(os.environ.get("LLM_CONFIDENCE_THRESHOLD", "0.60"))

MAX_TOTAL_TIME = int(os.environ.get("LLM_MAX_TOTAL_TIME", "300"))

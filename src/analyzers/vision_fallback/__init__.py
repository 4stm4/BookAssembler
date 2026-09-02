"""
VisionFallbackAnalyzer — sends low-confidence and needs_vision_ocr blocks
to a vision model for reclassification or LaTeX extraction.

Runs after LLMRefinement. Uses AgentRouter to discover vision-capable
ollama hosts. Gracefully degrades to no-op when no vision model is available.

For FormulaBlock with needs_vision_ocr: extracts LaTeX via vision model.
For low-confidence ParagraphBlock: reclassifies via vision prompt.
"""

from src.analyzers.vision_fallback.config import MAX_VISION_CALLS, MAX_VISION_TIME, VISION_CONFIDENCE_THRESHOLD
from src.analyzers.vision_fallback.prompts import CLASSIFY_PROMPT, FORMULA_PROMPT
from src.analyzers.vision_fallback.signals import _TYPE_MAP, log
from src.analyzers.vision_fallback.rules import _get_text, _page_crop_b64, _parse_classify_response
from src.analyzers.vision_fallback.analyzer import VisionFallbackAnalyzer

__all__ = [
    "CLASSIFY_PROMPT",
    "FORMULA_PROMPT",
    "MAX_VISION_CALLS",
    "MAX_VISION_TIME",
    "VISION_CONFIDENCE_THRESHOLD",
    "VisionFallbackAnalyzer",
    "_TYPE_MAP",
    "_get_text",
    "_page_crop_b64",
    "_parse_classify_response",
    "log",
]

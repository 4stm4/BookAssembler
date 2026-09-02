"""
FormulaDetectorAnalyzer — promote display-formula ParagraphBlocks to
FormulaBlock so the assembler and chunker treat them atomically
(KRM_ENTITIES_MAP P0.3, RFC 0002).

The block's `latex_expression` is set to the raw source text as a
fallback — a follow-up pass (vision agent / GOT-OCR) can replace it
with the real LaTeX. `metadata["needs_vision_ocr"] = True` marks that
handoff.

Heuristics (any of these triggers a promotion):
  1. Math-family font: FONT contains 'CMMI', 'CMSY', 'CMEX', 'MSAM',
     'MSBM', 'STIX', 'Symbol', 'Math'.
  2. Short line (≤ 60 chars) with high math-symbol density
     (≥ 15 % non-alphanumeric-non-space math chars).
  3. Trailing "(N.M)" formula number after either signal above.
"""

from src.analyzers.formula.signals import _FORMULA_NUMBER_RE, _MATH_CHARS, _MATH_FONT_HINTS
from src.analyzers.formula.rules import _extract_formula_number, _font_family, _looks_like_formula, _math_font, _symbol_density
from src.analyzers.formula.analyzer import FormulaDetectorAnalyzer

__all__ = [
    "FormulaDetectorAnalyzer",
    "_FORMULA_NUMBER_RE",
    "_MATH_CHARS",
    "_MATH_FONT_HINTS",
    "_extract_formula_number",
    "_font_family",
    "_looks_like_formula",
    "_math_font",
    "_symbol_density",
]

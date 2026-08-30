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

import re
from typing import Any, Dict, List, Optional, Tuple

from src.analyzers.base import (
    AnalyzerManifest,
    BaseAnalyzer,
    KGPermission,
    KRMPermission,
)
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import (
    ContainerUnit,
    FormulaBlock,
    KnowledgeDocument,
    ParagraphBlock,
)


_MATH_FONT_HINTS = (
    "cmmi", "cmsy", "cmex", "msam", "msbm", "stix", "symbol", "math",
    "mtmi", "mtsy", "mtex", "asana", "esint", "yhmath",
)

_MATH_CHARS = set(
    "∫∑∏∐√∞±∓×÷≠≈≤≥≪≫∈∉⊂⊆⊃⊇∪∩∀∃∄∇∂ℝℤℕℚℂ∆Ω"
    "αβγδεζηθικλμνξοπρστυφχψω"
    "ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ"
    "→←↔⇒⇐⇔≡≺≻⊕⊗⊥∠"
)

_FORMULA_NUMBER_RE = re.compile(r"[\(\[]\s*([\d.]+)\s*[\)\]]\s*$")


def _block_text(block: ParagraphBlock) -> str:
    parts: List[str] = []
    for inline in block.inlines or []:
        for span in getattr(inline, "spans", []) or []:
            txt = getattr(span, "text", "")
            if txt:
                parts.append(txt)
    return "".join(parts)


def _font_family(block: ParagraphBlock) -> str:
    vl = getattr(block, "visual_layout", None)
    st = getattr(vl, "style", None) if vl else None
    return (getattr(st, "font_family", "") or "").lower() if st else ""


def _math_font(block: ParagraphBlock) -> bool:
    font = _font_family(block)
    return any(hint in font for hint in _MATH_FONT_HINTS)


def _symbol_density(text: str) -> float:
    if not text:
        return 0.0
    hits = sum(1 for ch in text if ch in _MATH_CHARS)
    return hits / len(text)


def _looks_like_formula(text: str) -> bool:
    stripped = text.strip()
    if not stripped or len(stripped) > 120:
        return False
    density = _symbol_density(stripped)
    if density >= 0.15:
        return True
    # Equations without unicode symbols: 'x = a + b^2', 'f(x) = ...'
    if len(stripped) <= 60 and "=" in stripped and len(stripped.split()) <= 8:
        alpha = sum(1 for c in stripped if c.isalpha())
        digits_ops = sum(1 for c in stripped if c.isdigit() or c in "+-*/^=()[]{}")
        if alpha and digits_ops and digits_ops / max(1, alpha) >= 0.5:
            return True
    return False


def _extract_formula_number(text: str) -> Tuple[str, Optional[str]]:
    m = _FORMULA_NUMBER_RE.search(text.rstrip())
    if not m:
        return text, None
    return text[: m.start()].rstrip(), m.group(1)


class FormulaDetectorAnalyzer(BaseAnalyzer):
    """
    Replaces ParagraphBlocks that look like display formulas with
    FormulaBlock (RFC 0002 §Formula). Original block identity is preserved
    (RFC 0001 §2.3).
    """

    def __init__(self) -> None:
        super().__init__(
            AnalyzerManifest(
                name="FormulaDetectorAnalyzer",
                version="1.0.0",
                description="Promote display-formula paragraphs to FormulaBlock",
                krm_permissions={
                    KRMPermission.READ,
                    KRMPermission.TRANSFORM_NODE,
                    KRMPermission.INSERT,
                    KRMPermission.MUTATE_ATTRIBUTES,
                },
                rg_permissions=set(),
                kg_permissions={KGPermission.READ},
                depends_on=["NormalizationAnalyzer", "HeadingAnalyzer"],
            )
        )

    def run(
        self,
        doc: KnowledgeDocument,
        rg: ReadingGraph,
        kg: KnowledgeGraph,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        for root in doc.root_containers:
            self._process(root)

    def _process(self, container: ContainerUnit) -> None:
        for child in container.children:
            if isinstance(child, ContainerUnit):
                self._process(child)

        new_children: List[Any] = []
        for child in container.children:
            if not isinstance(child, ParagraphBlock) or child.is_tombstoned:
                new_children.append(child)
                continue

            text = _block_text(child)
            if not text.strip():
                new_children.append(child)
                continue

            math_font = _math_font(child)
            font_role_math = (child.metadata or {}).get("font_role") == "math"
            heuristic = _looks_like_formula(text)
            if not (math_font or heuristic or font_role_math):
                new_children.append(child)
                continue

            body_text, number = _extract_formula_number(text)
            formula = FormulaBlock(
                latex_expression=body_text.strip(),
                is_numbered=number is not None,
                formula_number=number,
                visual_layout=child.visual_layout,
                extraction_confidence=child.extraction_confidence,
                classification_confidence=0.80 if (math_font or font_role_math) else 0.60,
                confidence_score=min(
                    child.extraction_confidence,
                    0.80 if (math_font or font_role_math) else 0.60,
                ),
            )
            formula.id = child.id  # RFC 0001 §2.3
            formula.metadata = dict(child.metadata or {})
            formula.metadata["needs_vision_ocr"] = True
            signal = "font" if math_font else ("font_role" if font_role_math else "density")
            formula.metadata["detector_signal"] = signal
            new_children.append(formula)

        container.children = new_children

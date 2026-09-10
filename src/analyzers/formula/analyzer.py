"""formula: The analyzer itself: orchestration and KRM writes."""

from src.analyzers.access import block_text
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

from src.analyzers.formula.rules import _extract_formula_number, _looks_like_formula, _math_font

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

            text = block_text(child, sep="")
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

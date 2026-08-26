"""
DefinitionDetectorAnalyzer — detect formal definitions in text.

Detection heuristics:
  1. Prefix "Definition N." / "Определение N."
  2. Pattern "X — это" / "X is defined as" / "X means"
  3. Italic/bold leading term followed by "—" or ":" definition

Attaches a DefinitionSpec (SemanticUnit) to the paragraph via target_block_id.
Populates DefinitionSpec.term and .definition_text from the detected content.
"""

import re
from typing import Any, Dict, List, Optional

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
    DefinitionSpec,
    KnowledgeDocument,
    ParagraphBlock,
    StyledTextSpan,
)

_DEFINITION_PREFIX_RE = re.compile(
    r"^\s*(?:definition|определение)\s+(?P<number>\d+(?:\.\d+)*)?\s*[.:—–\-]?\s*(?P<rest>.*)$",
    re.IGNORECASE,
)

_DEFINITION_PATTERN_RE = re.compile(
    r"^(?P<term>.{2,60}?)\s+(?:—\s*это|is\s+defined\s+as|is\s+called|means|называется)\s+(?P<def>.+)$",
    re.IGNORECASE,
)


def _first_text(block: ParagraphBlock) -> str:
    for inline in block.inlines or []:
        for span in getattr(inline, "spans", []) or []:
            txt = getattr(span, "text", "")
            if txt:
                return str(txt)
    return ""


def _has_styled_lead(block: ParagraphBlock) -> Optional[str]:
    """Return the text of the first span if it's italic or bold."""
    for inline in block.inlines or []:
        spans = getattr(inline, "spans", []) or []
        if not spans:
            continue
        first = spans[0]
        if not isinstance(first, StyledTextSpan):
            return None
        style = getattr(first, "style", None)
        if style and (getattr(style, "is_italic", False) or getattr(style, "is_bold", False)):
            return getattr(first, "text", "") or ""
    return None


class DefinitionDetectorAnalyzer(BaseAnalyzer):
    def __init__(self) -> None:
        super().__init__(
            AnalyzerManifest(
                name="DefinitionDetectorAnalyzer",
                version="1.0.0",
                description="Detect formal definitions and attach DefinitionSpec decorators",
                krm_permissions={
                    KRMPermission.READ,
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
            self._process(root, doc)

    def _process(self, container: ContainerUnit, doc: KnowledgeDocument) -> None:
        for child in container.children:
            if isinstance(child, ContainerUnit):
                self._process(child, doc)

        for child in container.children:
            if not isinstance(child, ParagraphBlock) or child.is_tombstoned:
                continue
            if type(child) is not ParagraphBlock:
                continue
            if child.metadata and child.metadata.get("semantic_decorator"):
                continue

            text = _first_text(child)
            if not text:
                continue

            m = _DEFINITION_PREFIX_RE.match(text)
            if m:
                rest = m.group("rest") or ""
                term, defn = self._split_term_def(rest)
                spec = DefinitionSpec(
                    target_block_id=child.id,
                    term=term,
                    definition_text=defn,
                )
                child.metadata = child.metadata or {}
                child.metadata["semantic_decorator"] = "definition"
                doc.semantic_units.append(spec)
                continue

            m = _DEFINITION_PATTERN_RE.match(text)
            if m:
                spec = DefinitionSpec(
                    target_block_id=child.id,
                    term=m.group("term").strip(),
                    definition_text=m.group("def").strip(),
                )
                child.metadata = child.metadata or {}
                child.metadata["semantic_decorator"] = "definition"
                doc.semantic_units.append(spec)
                continue

    @staticmethod
    def _split_term_def(text: str) -> tuple:
        for sep in (" — ", " – ", ": ", " — это "):
            if sep in text:
                parts = text.split(sep, 1)
                return parts[0].strip(), parts[1].strip()
        return "", text.strip()

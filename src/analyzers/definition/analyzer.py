"""definition: The analyzer itself: orchestration and KRM writes."""

from src.analyzers.access import first_span_text
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

from src.analyzers.definition.signals import _DEFINITION_PATTERN_RE, _DEFINITION_PREFIX_RE

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

            text = first_span_text(child)
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

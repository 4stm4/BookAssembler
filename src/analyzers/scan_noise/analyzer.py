"""scan_noise: The analyzer itself: orchestration and KRM writes."""

from typing import Any, Dict, Optional

from src.analyzers.access import block_text
from src.analyzers.base import AnalyzerManifest, BaseAnalyzer, KRMPermission
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import ContainerUnit, KnowledgeDocument, ParagraphBlock

from src.analyzers.scan_noise.rules import is_scan_noise


class ScanNoiseAnalyzer(BaseAnalyzer):
    """Tombstones letter debris that a scan's text layer made of a logo,
    crest or smudge, before it can pollute headings or the title page.

    This used to happen inside the PDF adapter, which dropped such blocks
    outright. That is a judgement about content, not conversion (RFC 0008
    §5.2), and it deleted without a trace (RFC 0001 §2.4) — measured on the
    test books it also discarded every dotted-leader contents line and every
    Cyrillic paragraph without a Latin word in it.
    """

    def __init__(self) -> None:
        super().__init__(
            AnalyzerManifest(
                name="ScanNoiseAnalyzer",
                version="1.0.0",
                description="Tombstones letter debris from scanned non-text regions",
                krm_permissions={KRMPermission.READ, KRMPermission.TOMBSTONE},
                rg_permissions=set(),
                kg_permissions=set(),
                depends_on=["NormalizationAnalyzer"],
            )
        )

    def run(
        self,
        doc: KnowledgeDocument,
        rg: ReadingGraph,
        kg: KnowledgeGraph,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        for container in doc.root_containers:
            self._process(container)

    def _process(self, container: ContainerUnit) -> None:
        for child in container.children:
            if isinstance(child, ContainerUnit):
                self._process(child)
            elif (
                type(child) is ParagraphBlock
                and not child.is_tombstoned
                and is_scan_noise(block_text(child))
            ):
                child.is_tombstoned = True
                if not child.metadata:
                    child.metadata = {}
                child.metadata["tombstone_reason"] = "scan_noise"

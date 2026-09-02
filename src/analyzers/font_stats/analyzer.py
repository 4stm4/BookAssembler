"""font_stats: The analyzer itself: orchestration and KRM writes."""

from collections import Counter
from typing import Any, Dict, List, Optional, Tuple
from src.analyzers.base import (
    AnalyzerManifest,
    BaseAnalyzer,
    KRMPermission,
)
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import (
    ContainerUnit,
    KnowledgeDocument,
    ParagraphBlock,
)

from src.analyzers.font_stats.signals import log
from src.analyzers.font_stats.rules import FontFingerprint, _classify_role, _extract_font

class FontStatsAnalyzer(BaseAnalyzer):
    def __init__(self) -> None:
        super().__init__(
            AnalyzerManifest(
                name="FontStatsAnalyzer",
                version="1.0.0",
                description="Document-level font statistics and font-role classification",
                krm_permissions={
                    KRMPermission.READ,
                    KRMPermission.MUTATE_ATTRIBUTES,
                },
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
        fingerprints: List[Tuple[ParagraphBlock, FontFingerprint]] = []
        self._collect(doc.root_containers, fingerprints)

        if not fingerprints:
            return

        # Find body font: most frequent fingerprint key
        counter: Counter = Counter()
        for _, fp in fingerprints:
            counter[fp.key] += 1

        body_key = counter.most_common(1)[0][0]
        body_fp = next(fp for _, fp in fingerprints if fp.key == body_key)

        doc.metadata = doc.metadata or {}
        doc.metadata["font_stats"] = {
            "body_family": body_fp.family,
            "body_size": body_fp.size,
            "unique_fonts": len(counter),
            "total_blocks_with_font": len(fingerprints),
        }

        log.info(
            "Font stats: body='%s' size=%.1f, %d unique fonts across %d blocks",
            body_fp.family, body_fp.size, len(counter), len(fingerprints),
        )

        for block, fp in fingerprints:
            role = _classify_role(fp, body_fp.family, body_fp.size)
            block.metadata = block.metadata or {}
            block.metadata["font_role"] = role
            block.metadata["font_family"] = fp.family
            block.metadata["font_size"] = fp.size

    def _collect(
        self,
        containers: list,
        results: List[Tuple[ParagraphBlock, FontFingerprint]],
    ) -> None:
        for node in containers:
            if isinstance(node, ContainerUnit):
                for child in node.children:
                    if isinstance(child, ParagraphBlock) and not child.is_tombstoned:
                        fp = _extract_font(child)
                        if fp:
                            results.append((child, fp))
                    elif isinstance(child, ContainerUnit):
                        self._collect([child], results)

"""
FontStatsAnalyzer — compute document-level font statistics and classify
blocks by font role (body/heading/caption/footnote/code).

Runs early in the pipeline (after Normalization). Collects font fingerprints
(family + size + bold + italic) across all ParagraphBlocks, identifies the
dominant "body" font by frequency, then tags outlier blocks with font_role
metadata that downstream detectors can use as a signal.

Font roles:
- body: most frequent font fingerprint
- heading: same family as body but larger, or bold variant
- caption: smaller than body
- footnote: significantly smaller than body, or at page bottom
- code: monospace font family
- math: math-family font (CMMI, STIX, Symbol, etc.)
"""

import logging
from collections import Counter
from dataclasses import dataclass
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

log = logging.getLogger(__name__)

_MONO_HINTS = (
    "courier", "consolas", "mono", "menlo", "source code", "fira code",
    "inconsolata", "dejavu sans mono", "liberation mono", "andale",
)

_MATH_HINTS = (
    "cmmi", "cmsy", "cmex", "msam", "msbm", "stix", "symbol", "math",
    "mtmi", "mtsy", "asana", "esint", "yhmath",
)

HEADING_SIZE_RATIO = 1.15
CAPTION_SIZE_RATIO = 0.88
FOOTNOTE_SIZE_RATIO = 0.75


@dataclass
class FontFingerprint:
    family: str
    size: float
    bold: bool
    italic: bool

    @property
    def key(self) -> str:
        return f"{self.family}|{self.size:.1f}|{int(self.bold)}|{int(self.italic)}"


def _extract_font(block: ParagraphBlock) -> Optional[FontFingerprint]:
    vl = getattr(block, "visual_layout", None)
    if not vl:
        return None
    style = getattr(vl, "style", None)
    if not style:
        return None
    family = (getattr(style, "font_family", "") or "").strip()
    size = getattr(style, "font_size_pt", 0.0) or 0.0
    bold = bool(getattr(style, "is_bold", False))
    italic = bool(getattr(style, "is_italic", False))
    if not family and size == 0.0:
        return None
    return FontFingerprint(family=family.lower(), size=size, bold=bold, italic=italic)


def _classify_role(
    fp: FontFingerprint,
    body_family: str,
    body_size: float,
) -> str:
    family = fp.family

    if any(hint in family for hint in _MATH_HINTS):
        return "math"
    if any(hint in family for hint in _MONO_HINTS):
        return "code"

    if body_size > 0:
        ratio = fp.size / body_size if fp.size > 0 else 1.0
        if ratio >= HEADING_SIZE_RATIO:
            return "heading"
        if ratio <= FOOTNOTE_SIZE_RATIO:
            return "footnote"
        if ratio <= CAPTION_SIZE_RATIO:
            return "caption"

    if fp.bold and fp.size >= body_size and family == body_family:
        return "heading"

    return "body"


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

"""
BlockClassifierAnalyzer — adjusts classification_confidence and detects TOC.

Adaptive TOC detection: finds clusters of short blocks ending with page numbers
on the same pages. No hardcoded patterns — works across different book formats.

Algorithm:
1. For each container, scan ParagraphBlocks for "ends with number" pattern
2. Find runs of 4+ consecutive such blocks on the same or adjacent pages
3. Group runs into ContainerUnit(semantic_type='toc')
4. For remaining ParagraphBlocks, compute classification_confidence from features
"""

import re
from typing import Any, Dict, List, Optional, Tuple

from src.analyzers.base import AnalyzerManifest, BaseAnalyzer, KRMPermission
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import (
    ContainerUnit,
    KnowledgeDocument,
    ParagraphBlock,
)

_ENDS_WITH_PAGE_NUM = re.compile(r"\s(\d{1,4})\s*$")

MIN_TOC_RUN = 4
MAX_TOC_TEXT_LEN = 120


def _get_text(block: ParagraphBlock) -> str:
    parts = []
    for inline in (block.inlines or []):
        for span in getattr(inline, "spans", []):
            if hasattr(span, "text"):
                parts.append(span.text)
    return " ".join(parts)


def _page_of(block: ParagraphBlock) -> Optional[int]:
    vl = getattr(block, "visual_layout", None)
    if vl is None:
        return None
    return getattr(vl, "page_or_screen_index", None)


def _looks_like_toc_entry(text: str) -> bool:
    stripped = text.strip()
    if not stripped or len(stripped) > MAX_TOC_TEXT_LEN or len(stripped) < 5:
        return False
    if not _ENDS_WITH_PAGE_NUM.search(stripped):
        return False
    title_part = _ENDS_WITH_PAGE_NUM.sub("", stripped).strip()
    long_words = [w for w in title_part.split() if len(w) >= 3 and any(c.isalpha() for c in w)]
    if len(long_words) < 2:
        return False
    return True


def _classify_paragraph_confidence(text: str) -> float:
    stripped = text.strip()
    if not stripped:
        return 0.10

    length = len(stripped)
    words = stripped.split()
    word_count = len(words)
    alpha_ratio = sum(c.isalpha() for c in stripped) / length if length else 0
    has_period = "." in stripped
    has_sentence = has_period and word_count > 3

    score = 0.50

    if has_sentence and length > 80:
        score += 0.30
    elif has_sentence:
        score += 0.20
    elif length > 50:
        score += 0.10

    if word_count >= 5:
        score += 0.05
    elif word_count == 1:
        score -= 0.15

    if alpha_ratio > 0.6:
        score += 0.05
    elif alpha_ratio < 0.3:
        score -= 0.10

    if length < 5:
        score -= 0.15

    return max(0.10, min(0.95, score))


class BlockClassifierAnalyzer(BaseAnalyzer):
    def __init__(self) -> None:
        super().__init__(
            AnalyzerManifest(
                name="BlockClassifierAnalyzer",
                version="1.0.0",
                description="Adjusts classification confidence, detects TOC entries",
                krm_permissions={
                    KRMPermission.READ,
                    KRMPermission.TRANSFORM_NODE,
                    KRMPermission.INSERT,
                },
                rg_permissions=set(),
                kg_permissions=set(),
                depends_on=["CaptionAnalyzer"],
            )
        )

    def run(
        self,
        doc: KnowledgeDocument,
        rg: ReadingGraph,
        kg: KnowledgeGraph,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._heading_titles: set = set()
        self._collect_headings(doc.root_containers)
        self._total_pages = doc.metadata.get("page_count", 100) if doc.metadata else 100
        for container in doc.root_containers:
            self._process_container(container)

    def _collect_headings(self, containers: list) -> None:
        for c in containers:
            if isinstance(c, ContainerUnit) and c.title:
                normalized = re.sub(r"\s+", " ", c.title.strip().lower())
                self._heading_titles.add(normalized)
                if hasattr(c, "children"):
                    self._collect_headings(c.children)

    def _process_container(self, container: ContainerUnit) -> None:
        for child in list(container.children):
            if isinstance(child, ContainerUnit):
                self._process_container(child)

        toc_runs: List[List[Tuple[int, ParagraphBlock]]] = []
        current_run: List[Tuple[int, ParagraphBlock]] = []
        last_page: Optional[int] = None

        for idx, child in enumerate(container.children):
            if not isinstance(child, ParagraphBlock):
                if len(current_run) >= MIN_TOC_RUN:
                    toc_runs.append(current_run)
                current_run = []
                last_page = None
                continue

            text = _get_text(child)
            page = _page_of(child)

            if _looks_like_toc_entry(text):
                if last_page is not None and page is not None and abs(page - last_page) > 2:
                    if len(current_run) >= MIN_TOC_RUN:
                        toc_runs.append(current_run)
                    current_run = []
                current_run.append((idx, child))
                if page is not None:
                    last_page = page
            else:
                if len(current_run) >= MIN_TOC_RUN:
                    toc_runs.append(current_run)
                current_run = []
                last_page = None

                cls_conf = _classify_paragraph_confidence(text)
                child.classification_confidence = cls_conf
                child.update_confidence()

        if len(current_run) >= MIN_TOC_RUN:
            toc_runs.append(current_run)

        if not toc_runs:
            return

        toc_page_threshold = max(3, int(self._total_pages * 0.12))
        end_threshold = self._total_pages - toc_page_threshold

        validated_runs = []
        for run in toc_runs:
            pages = [_page_of(b) for _, b in run if _page_of(b) is not None]
            if pages:
                avg_page = sum(pages) / len(pages)
                if avg_page > toc_page_threshold and avg_page < end_threshold:
                    continue

            match_count = 0
            for _, block in run:
                text = _get_text(block).strip()
                title_part = _ENDS_WITH_PAGE_NUM.sub("", text).strip()
                title_norm = re.sub(r"\s+", " ", title_part.lower())
                for heading in self._heading_titles:
                    if title_norm and (title_norm in heading or heading in title_norm):
                        match_count += 1
                        break
            match_ratio = match_count / len(run) if run else 0
            if match_ratio >= 0.10 or len(run) >= MIN_TOC_RUN:
                validated_runs.append((run, match_ratio))

        if not validated_runs:
            for run in toc_runs:
                for _, block in run:
                    text = _get_text(block)
                    cls_conf = _classify_paragraph_confidence(text)
                    block.classification_confidence = cls_conf
                    block.update_confidence()
            return

        indices_to_remove: set = set()
        insertions: Dict[int, ContainerUnit] = {}

        for run, match_ratio in validated_runs:
            first_idx = run[0][0]
            run_confidence = min(0.90, 0.60 + match_ratio * 0.30 + len(run) * 0.01)
            toc_container = ContainerUnit(
                title="Оглавление",
                level=container.level + 1,
                semantic_type="toc",
                classification_confidence=run_confidence,
                extraction_confidence=0.85,
                confidence_score=min(0.85, run_confidence),
            )
            for orig_idx, block in run:
                block.classification_confidence = run_confidence
                block.update_confidence()
                toc_container.children.append(block)
                indices_to_remove.add(orig_idx)

            insertions[first_idx] = toc_container

        new_children = []
        for idx, child in enumerate(container.children):
            if idx in insertions:
                new_children.append(insertions[idx])
            elif idx not in indices_to_remove:
                new_children.append(child)
        container.children = new_children

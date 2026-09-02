"""block_classifier: The analyzer itself: orchestration and KRM writes."""

from src.analyzers.access import page_of
import re
from typing import Any, Dict, List, Optional, Tuple
from src.analyzers.base import AnalyzerManifest, BaseAnalyzer, KRMPermission
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.identity import derive_composite_id
from src.krm.models import (
    ContainerUnit,
    KnowledgeDocument,
    ParagraphBlock,
    TextLineInline,
    TocEntryBlock,
    StyledTextSpan,
    VisualLayout,
    NormalizedRect,
)

from src.analyzers.block_classifier.signals import MIN_TOC_RUN, _ENDS_WITH_PAGE_NUM
from src.analyzers.block_classifier.rules import _classify_paragraph_confidence, _get_text, _looks_like_toc_entry, _parse_toc_entry

class BlockClassifierAnalyzer(BaseAnalyzer):
    def __init__(self) -> None:
        super().__init__(
            AnalyzerManifest(
                name="BlockClassifierAnalyzer",
                version="1.1.0",
                description="Adjusts classification confidence, detects TOC entries",
                krm_permissions={
                    KRMPermission.READ,
                    KRMPermission.TRANSFORM_NODE,
                    KRMPermission.INSERT,
                    KRMPermission.TOMBSTONE,
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
        self._link_toc_anchors(doc.root_containers)

    def _link_toc_anchors(self, containers: list) -> None:
        """Populate TocEntryBlock.anchor_id by matching against ContainerUnit
        titles (chapter_number prefix first, then normalized-title equality).
        """
        headings: Dict[str, str] = {}  # normalized title/number → container id
        toc_entries: List[TocEntryBlock] = []

        def walk(nodes: list) -> None:
            for n in nodes:
                if isinstance(n, ContainerUnit):
                    if n.semantic_type != "toc" and n.title:
                        norm = re.sub(r"\s+", " ", n.title.strip().lower())
                        headings[norm] = n.id
                        m_num = re.match(r"^\s*([\d.]+|[A-Za-zА-Яа-я]\.)\s+", n.title)
                        if m_num:
                            headings[m_num.group(1).strip().rstrip(".")] = n.id
                    for ch in n.children:
                        walk([ch])
                elif isinstance(n, TocEntryBlock):
                    toc_entries.append(n)

        walk(containers)

        for e in toc_entries:
            if e.anchor_id:
                continue
            if e.chapter_number:
                key = e.chapter_number.strip().rstrip(".")
                if key in headings:
                    e.anchor_id = headings[key]
                    continue
            body = re.sub(r"^\s*([\d.]+|[A-Za-zА-Яа-я]\.)\s+", "", e.entry_text or "")
            body_norm = re.sub(r"\s+", " ", body.strip().lower())
            if body_norm and body_norm in headings:
                e.anchor_id = headings[body_norm]

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

        if any(
            isinstance(c, ContainerUnit) and getattr(c, "semantic_type", None) == "toc"
            for c in container.children
        ):
            return

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
            page = page_of(child)

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
            pages = [page_of(b) for _, b in run if page_of(b) is not None]
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
                id=derive_composite_id(
                    "toc-container", *[b.id for _, b in run]
                ),
                title="Оглавление",
                level=container.level + 1,
                semantic_type="toc",
                classification_confidence=run_confidence,
                extraction_confidence=0.85,
                confidence_score=min(0.85, run_confidence),
            )
            for orig_idx, block in run:
                text = _get_text(block)
                if not text.strip():
                    indices_to_remove.add(orig_idx)
                    continue
                entry_text, chapter_number, target_page = _parse_toc_entry(text)
                entry = TocEntryBlock(
                    entry_text=entry_text,
                    chapter_number=chapter_number,
                    target_page=target_page,
                    visual_layout=block.visual_layout,
                    extraction_confidence=0.85,
                    classification_confidence=run_confidence,
                    confidence_score=min(0.85, run_confidence),
                )
                entry.id = block.id  # RFC 0001 §2.3 — preserve identity
                toc_container.children.append(entry)
                indices_to_remove.add(orig_idx)

            insertions[first_idx] = toc_container

        # RFC 0001 §2.4 / 0005 §2: no physical deletion. Original TOC lines are
        # tombstoned in place (exporters skip them); the merged TOC container is inserted.
        new_children = []
        for idx, child in enumerate(container.children):
            if idx in insertions:
                new_children.append(insertions[idx])
            if idx in indices_to_remove:
                child.is_tombstoned = True
                if not child.metadata:
                    child.metadata = {}
                child.metadata["tombstone_reason"] = "merged_into_toc"
            new_children.append(child)
        container.children = new_children

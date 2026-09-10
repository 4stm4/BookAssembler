"""toc: detects the table of contents and types its entries.

Was a ~140-line block inside BlockClassifierAnalyzer, whose stated job is
adjusting classification confidence. It only recognised the dotted-leader form
("Registers .......... 45") — a contents page that is a plain section list
under a "CONTENTS" heading (the PDP-11 lab report, most old manuals) produced
nothing, and the editor showed the entries as ordinary paragraphs.

This owns all of it now:
  * find a "CONTENTS" / "Оглавление" heading near the front (or a dense run of
    page-numbered lines with no heading);
  * collect the entry lines that follow, at line granularity — a column
    layout mashes several entries into one text block, so a block is split;
  * build one ContainerUnit(semantic_type="toc") of TocEntryBlocks, tombstone
    the originals in place (RFC 0001 §2.4);
  * link each entry to its heading once the tree exists.
"""

import re
from typing import Any, Dict, List, Optional, Tuple

from src.analyzers.access import lines, page_of
from src.analyzers.base import AnalyzerManifest, BaseAnalyzer, KRMPermission
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.identity import derive_composite_id
from src.krm.models import (
    ContainerUnit,
    KnowledgeDocument,
    ParagraphBlock,
    TocEntryBlock,
    VisualLayout,
)

from src.analyzers.toc.signals import MIN_TOC_RUN, TOC_PAGE_FRACTION
from src.analyzers.toc.rules import (
    is_toc_entry,
    is_toc_heading,
    parse_entry,
    split_merged_entries,
)


class TocAnalyzer(BaseAnalyzer):
    def __init__(self) -> None:
        super().__init__(
            AnalyzerManifest(
                name="TocAnalyzer",
                version="1.0.0",
                description="Detects the table of contents and types its entries",
                krm_permissions={
                    KRMPermission.READ,
                    KRMPermission.INSERT,
                    KRMPermission.TOMBSTONE,
                },
                rg_permissions=set(),
                kg_permissions=set(),
                depends_on=["HeadingAnalyzer", "TitlePageAnalyzer"],
            )
        )

    def run(
        self,
        doc: KnowledgeDocument,
        rg: ReadingGraph,
        kg: KnowledgeGraph,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._total_pages = (
            doc.metadata.get("page_count", 100) if doc.metadata else 100
        )
        for container in doc.root_containers:
            self._process_container(container)
        self._link_anchors(doc.root_containers)

    # -- detection --------------------------------------------------------

    def _process_container(self, container: ContainerUnit) -> None:
        for child in list(container.children):
            if isinstance(child, ContainerUnit):
                self._process_container(child)

        if any(
            isinstance(c, ContainerUnit)
            and getattr(c, "semantic_type", None) == "toc"
            for c in container.children
        ):
            return

        # Per-line candidates: (child_index, source_block, entry_text, page).
        # A block contributes several rows when its lines split into entries.
        rows: List[Tuple[int, ParagraphBlock, str, Optional[int]]] = []
        for idx, child in enumerate(container.children):
            if not isinstance(child, ParagraphBlock) or child.is_tombstoned:
                rows.append((idx, child, "\x00non-para", None))  # a hard break
                continue
            page = page_of(child)
            block_lines = list(lines(child)) or [""]
            for ln in block_lines:
                for seg in split_merged_entries(ln):
                    rows.append((idx, child, seg, page))

        anchored_run, plain_runs = self._collect_runs(rows)

        runs: List[Tuple[List[Tuple[int, ParagraphBlock, str]], bool]] = []
        if anchored_run:
            runs.append((anchored_run, True))
        for r in plain_runs:
            if self._run_is_positioned_like_a_toc(r):
                runs.append((r, False))

        if not runs:
            return

        self._materialise(container, runs)

    def _collect_runs(
        self,
        rows: List[Tuple[int, ParagraphBlock, str, Optional[int]]],
    ) -> Tuple[
        List[Tuple[int, ParagraphBlock, str]],
        List[List[Tuple[int, ParagraphBlock, str]]],
    ]:
        """One anchored run (right after a CONTENTS heading) plus any dense
        page-numbered runs found without a heading."""
        anchored: List[Tuple[int, ParagraphBlock, str]] = []
        plain: List[List[Tuple[int, ParagraphBlock, str]]] = []
        current: List[Tuple[int, ParagraphBlock, str]] = []
        last_page: Optional[int] = None
        seen_heading = False
        heading_row: Optional[Tuple[int, ParagraphBlock, str]] = None

        def flush() -> None:
            nonlocal current
            if len(current) >= MIN_TOC_RUN:
                plain.append(current)
            current = []

        for idx, block, text, page in rows:
            if text == "\x00non-para":
                flush()
                last_page = None
                continue

            if not seen_heading and is_toc_heading(text):
                seen_heading = True
                heading_row = (idx, block, text)
                last_page = page
                continue

            if seen_heading and len(anchored) < 400:
                if is_toc_entry(text, anchored=True):
                    anchored.append((idx, block, text))
                    continue
                # First non-entry line after the anchored run ends it.
                if anchored:
                    seen_heading = False

            if is_toc_entry(text):
                if (
                    last_page is not None
                    and page is not None
                    and abs(page - last_page) > 2
                ):
                    flush()
                current.append((idx, block, text))
                if page is not None:
                    last_page = page
            else:
                flush()
                last_page = None

        flush()
        # The heading line ("CONTENTS") is folded into the TOC container it
        # names, so it is tombstoned with the run it introduced.
        if anchored and heading_row is not None:
            anchored.insert(0, heading_row)
        return anchored, plain

    def _run_is_positioned_like_a_toc(
        self, run: List[Tuple[int, ParagraphBlock, str]]
    ) -> bool:
        pages = [page_of(b) for _, b, _ in run if page_of(b) is not None]
        if not pages:
            return len(run) >= MIN_TOC_RUN
        avg = sum(pages) / len(pages)
        front = max(3, int(self._total_pages * TOC_PAGE_FRACTION))
        back = self._total_pages - front
        return avg <= front or avg >= back

    # -- materialisation -------------------------------------------------

    def _materialise(
        self,
        container: ContainerUnit,
        runs: List[Tuple[List[Tuple[int, ParagraphBlock, str]], bool]],
    ) -> None:
        insertions: Dict[int, ContainerUnit] = {}
        tombstone: set = set()

        for run, anchored in runs:
            conf = 0.88 if anchored else min(0.85, 0.55 + len(run) * 0.02)
            block_ids = sorted({b.id for _, b, _ in run})
            toc = ContainerUnit(
                id=derive_composite_id("toc-container", *block_ids),
                title="Оглавление",
                level=container.level + 1,
                semantic_type="toc",
                classification_confidence=conf,
                extraction_confidence=0.85,
                confidence_score=min(0.85, conf),
            )
            # How many entries each source block yields — a block split into
            # several lines cannot give all of them its own id.
            per_block: Dict[str, int] = {}
            for _, block, text in run:
                if text.strip() and not is_toc_heading(text):
                    per_block[block.id] = per_block.get(block.id, 0) + 1

            for orig_idx, block, text in run:
                if not text.strip() or is_toc_heading(text):
                    # The "CONTENTS" line is folded into the container, not
                    # turned into an entry — but still tombstoned.
                    tombstone.add(orig_idx)
                    continue
                entry_text, chapter_number, target_page = parse_entry(text)
                # RFC 0001 §2.3: a 1:1 reclassification keeps the source id; a
                # block that split into several entries derives per line.
                entry_id = (
                    block.id if per_block.get(block.id) == 1
                    else derive_composite_id("toc-entry", block.id, entry_text)
                )
                entry = TocEntryBlock(
                    id=entry_id,
                    entry_text=entry_text,
                    chapter_number=chapter_number,
                    target_page=target_page,
                    visual_layout=_line_layout(block),
                    extraction_confidence=0.85,
                    classification_confidence=conf,
                    confidence_score=min(0.85, conf),
                )
                toc.children.append(entry)
                tombstone.add(orig_idx)

            first_idx = run[0][0]
            insertions[first_idx] = toc

        # RFC 0001 §2.4: originals stay, tombstoned; the merged container is
        # inserted before the first line of its run.
        new_children: List[Any] = []
        for idx, child in enumerate(container.children):
            if idx in insertions:
                new_children.append(insertions[idx])
            if idx in tombstone and isinstance(child, ParagraphBlock):
                child.is_tombstoned = True
                if not child.metadata:
                    child.metadata = {}
                child.metadata["tombstone_reason"] = "merged_into_toc"
            new_children.append(child)
        container.children = new_children

    # -- anchor linking -------------------------------------------------

    def _link_anchors(self, containers: list) -> None:
        headings: Dict[str, str] = {}
        entries: List[TocEntryBlock] = []

        def walk(nodes: list) -> None:
            for n in nodes:
                if isinstance(n, ContainerUnit):
                    if n.semantic_type != "toc" and n.title:
                        norm = re.sub(r"\s+", " ", n.title.strip().lower())
                        headings[norm] = n.id
                        m = re.match(
                            r"^\s*([\d.]+|[A-Za-zА-Яа-я]\.)\s+", n.title
                        )
                        if m:
                            headings[m.group(1).strip().rstrip(".")] = n.id
                    for ch in n.children:
                        walk([ch])
                elif isinstance(n, TocEntryBlock):
                    entries.append(n)

        walk(containers)

        for e in entries:
            if e.anchor_id:
                continue
            if e.chapter_number:
                key = e.chapter_number.strip().rstrip(".")
                if key in headings:
                    e.anchor_id = headings[key]
                    continue
            body = re.sub(
                r"^\s*([\d.]+|[A-Za-zА-Яа-я]\.)\s+", "", e.entry_text or ""
            )
            body_norm = re.sub(r"\s+", " ", body.strip().lower())
            if body_norm and body_norm in headings:
                e.anchor_id = headings[body_norm]


def _line_layout(block: ParagraphBlock) -> Optional[VisualLayout]:
    """The block's own layout — a TOC entry has no separate box of its own,
    it inherits the source line's page."""
    return getattr(block, "visual_layout", None)

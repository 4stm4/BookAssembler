"""toc: The analyzer itself: orchestration and KRM writes.

Reads the contents list from line geometry (layout.py) and replaces its
source blocks with one ContainerUnit(semantic_type="toc") of TocEntryBlocks.

Runs on the flat block list, before HeadingAnalyzer. A contents line set in
a chapter-heading size ("1 Command Line Editing", 14pt in texinfo; Intel
Series 3000 section lines) was promoted to a heading first, and a promoted
block keeps no line geometry to read an entry from. Linking the entries to
the headings they name needs the heading tree: TocLinkAnalyzer (linker.py).
"""

from typing import Any, Dict, List, Optional, Tuple

from src.analyzers.base import AnalyzerManifest, BaseAnalyzer, KRMPermission
from src.analyzers.toc.layout import Entry, Line, TocRead, read_toc
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.identity import derive_composite_id
from src.krm.models import (
    ContainerUnit,
    KnowledgeDocument,
    NormalizedRect,
    ParagraphBlock,
    StyleDescriptor,
    TocEntryBlock,
    VisualLayout,
)

# A contents list found under its own heading is surer than one recognised
# by its shape alone.
_CONF_HEADING = 0.9
_CONF_SHAPE = 0.8
_DEFAULT_TITLE = "Оглавление"


class TocAnalyzer(BaseAnalyzer):
    def __init__(self) -> None:
        super().__init__(
            AnalyzerManifest(
                name="TocAnalyzer",
                version="2.0.0",
                description="Detects the table of contents and reads its entries from line geometry",
                krm_permissions={
                    KRMPermission.READ,
                    KRMPermission.INSERT,
                    KRMPermission.TOMBSTONE,
                },
                rg_permissions=set(),
                kg_permissions=set(),
                # Running headers and folios on the contents pages are
                # EphemeraBlocks by now, not lines to read.
                depends_on=["EphemeraDetectorAnalyzer"],
            )
        )

    def run(
        self,
        doc: KnowledgeDocument,
        rg: ReadingGraph,
        kg: KnowledgeGraph,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        blocks: List[Tuple[ParagraphBlock, ContainerUnit]] = []
        for container in doc.root_containers:
            _collect(container, blocks)
        pages, block_lines, styles = _lines(blocks)
        if not pages:
            return
        toc = read_toc(pages)
        if toc.entries:
            _materialise(toc, blocks, block_lines, styles)


def _collect(container: ContainerUnit, out: List[Tuple[ParagraphBlock, ContainerUnit]]) -> None:
    for child in container.children:
        if isinstance(child, ContainerUnit):
            if child.semantic_type != "toc":
                _collect(child, out)
        elif type(child) is ParagraphBlock and not child.is_tombstoned:
            out.append((child, container))


def _lines(
    blocks: List[Tuple[ParagraphBlock, ContainerUnit]],
) -> Tuple[Dict[int, List[Line]], Dict[int, List[int]], Dict[int, Optional[StyleDescriptor]]]:
    """Every source line with its own box — one TextLineInline per PDF line
    (RFC 0021 §5.4). A block with several lines but no per-line geometry
    cannot be read this way and is left out."""
    pages: Dict[int, List[Line]] = {}
    block_lines: Dict[int, List[int]] = {}
    styles: Dict[int, Optional[StyleDescriptor]] = {}
    idx = 0
    for b, (block, _) in enumerate(blocks):
        bvl = block.visual_layout
        if bvl is None:
            continue
        inlines = block.inlines or []
        for il in inlines:
            text = " ".join(
                s.text for s in (il.spans or []) if getattr(s, "text", "")
            ).strip()
            if not text:
                continue
            vl = getattr(il, "visual_layout", None)
            if vl is None:
                if len(inlines) != 1:
                    continue
                vl = bvl
            style = vl.style or bvl.style
            size = float(getattr(style, "font_size_pt", 0.0) or 0.0) if style else 0.0
            r = vl.bounding_box
            page = vl.page_or_screen_index
            pages.setdefault(page, []).append(
                Line(idx, text, r.x0, r.y0, r.x1, r.y1, size, page, b)
            )
            block_lines.setdefault(b, []).append(idx)
            styles[idx] = style
            idx += 1
    return pages, block_lines, styles


def _entry_layout(e: Entry, styles: Dict[int, Optional[StyleDescriptor]]) -> VisualLayout:
    lines = [l for l in e.lines if l.page == e.lines[0].page]
    return VisualLayout(
        bounding_box=NormalizedRect(
            min(l.x0 for l in lines), min(l.y0 for l in lines),
            max(l.x1 for l in lines), max(l.y1 for l in lines),
        ),
        page_or_screen_index=lines[0].page,
        style=styles.get(e.rows[0].lines[0].idx),
    )


def _materialise(
    toc: TocRead,
    blocks: List[Tuple[ParagraphBlock, ContainerUnit]],
    block_lines: Dict[int, List[int]],
    styles: Dict[int, Optional[StyleDescriptor]],
) -> None:
    content_blocks = {
        l.block for e in toc.entries
        for l in e.lines + [x for r in e.description_rows for x in r.all_lines]
    }
    # A block is folded into the contents only when all of it was read as
    # contents — a block that also holds the first lines of the book proper
    # (TeX Live guide: the list ends mid-page) stays live.
    folded = {b for b in content_blocks
              if all(i in toc.consumed for i in block_lines.get(b, []))}
    if toc.heading is not None and all(
        i in toc.consumed for i in block_lines.get(toc.heading.block, [])
    ):
        folded.add(toc.heading.block)

    first = min(content_blocks | ({toc.heading.block} if toc.heading else set()))
    anchor, parent = blocks[first]
    conf = _CONF_HEADING if toc.heading is not None else _CONF_SHAPE

    container = ContainerUnit(
        id=derive_composite_id("toc-container", *(blocks[b][0].id for b in content_blocks)),
        title=toc.heading.text if toc.heading is not None else _DEFAULT_TITLE,
        level=parent.level + 1,
        semantic_type="toc",
        visual_layout=VisualLayout(
            bounding_box=NormalizedRect(0.0, 0.0, 1.0, 1.0),
            page_or_screen_index=toc.pages[0],
        ),
        classification_confidence=conf,
        extraction_confidence=0.9,
        confidence_score=min(0.9, conf),
        provenance_info=anchor.provenance_info,
    )
    for k, e in enumerate(toc.entries):
        number, title = e.number_and_title()
        sources = sorted({blocks[l.block][0].id for l in e.lines})
        entry = TocEntryBlock(
            # The source blocks stay in the tree, tombstoned (RFC 0001 §2.4),
            # so an entry never reuses one of their ids: two live-looking
            # nodes under one id read to the pipeline's guard as an
            # un-tombstoning.
            id=derive_composite_id("toc-entry", *sources, f"#{k}", e.text),
            entry_text=title,
            chapter_number=number,
            page_label=e.page_label,
            level=e.level,
            visual_layout=_entry_layout(e, styles),
            parent_container_id=container.id,
            provenance_info=anchor.provenance_info,
            extraction_confidence=0.9,
            classification_confidence=conf,
            confidence_score=min(0.9, conf),
        )
        if e.description:
            entry.metadata = {"toc_description": e.description}
        container.children.append(entry)

    at = next(i for i, c in enumerate(parent.children) if c is anchor)
    parent.children.insert(at, container)
    for b in sorted(folded):
        block = blocks[b][0]
        block.is_tombstoned = True
        if not block.metadata:
            block.metadata = {}
        block.metadata["tombstone_reason"] = "merged_into_toc"

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
from src.analyzers.printed import measure_line, settle_page
from src.analyzers.source_io import resolve_source_path
from src.analyzers.toc.layout import Entry, Line, TocRead, read_toc
from src.analyzers.toc.rules import is_number_token
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
    UnknownBlock,
    VisualLayout,
)

# A contents list found under its own heading is surer than one recognised
# by its shape alone.
_CONF_HEADING = 0.9
_CONF_SHAPE = 0.8
_DEFAULT_TITLE = "Оглавление"

# Text a contents line can be read from: what the adapter emits, not yet
# classified (RFC 0008 §5.2), and prose. Exact types: a title page or a
# caption is not a contents line, however it subclasses.
TEXT_BLOCKS = (UnknownBlock, ParagraphBlock)


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
            container, entries = _materialise(toc, blocks, block_lines, styles)
            _mark_print(doc, toc, container, entries)


def _collect(container: ContainerUnit, out: List[Tuple[ParagraphBlock, ContainerUnit]]) -> None:
    for child in container.children:
        if isinstance(child, ContainerUnit):
            if child.semantic_type != "toc":
                _collect(child, out)
        elif type(child) in TEXT_BLOCKS and not child.is_tombstoned:
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
) -> Tuple[ContainerUnit, List[Tuple[TocEntryBlock, Entry]]]:
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
    entries: List[Tuple[TocEntryBlock, Entry]] = []
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
        entries.append((entry, e))

    at = next(i for i, c in enumerate(parent.children) if c is anchor)
    parent.children.insert(at, container)
    for b in sorted(folded):
        block = blocks[b][0]
        block.is_tombstoned = True
        if not block.metadata:
            block.metadata = {}
        block.metadata["tombstone_reason"] = "merged_into_toc"
    return container, entries


def _parts(e: Entry) -> List[Tuple[str, Line]]:
    """An entry's printed lines, each with what it prints: its number set
    apart, its title (a line of it), its page reference, a row of its
    description."""
    out: List[Tuple[str, Line]] = []
    for r, row in enumerate(e.rows):
        for k, line in enumerate(row.lines):
            numbered = r == 0 and k == 0 and len(row.lines) > 1 and is_number_token(line.text)
            out.append(("number" if numbered else "title", line))
        if row.page_line is not None:
            out.append(("page", row.page_line))
    out += [("description", line) for row in e.description_rows for line in row.all_lines]
    return out


def _mark_print(
    doc: KnowledgeDocument,
    toc: TocRead,
    container: ContainerUnit,
    entries: List[Tuple[TocEntryBlock, Entry]],
) -> None:
    """Record how the contents were printed, line by line, for a page
    rebuilt where it was printed (RFC 0021 §3): each entry's lines
    (metadata["printed_lines"]) and the heading's (container
    metadata["printed_title"]), as src/analyzers/printed.py reads them off
    the source page's pixels - its ink box and baseline (page-normalised),
    the skew it was scanned at, size, face, weight, slant, colour,
    underline. Visual facts of the page,
    beside the entries' text, not in it. Nothing where the source cannot
    be opened."""
    path = resolve_source_path(doc)
    if not path:
        return
    try:
        import numpy as np
        import pymupdf
        source = pymupdf.open(path)
    except Exception:
        return
    try:
        measured: List[Tuple[Any, Dict[str, Any]]] = []
        words: Dict[int, List[Any]] = {}

        def measure(owner: Any, part: str, line: Line) -> None:
            if line.page >= source.page_count:
                return
            page = source[line.page]
            pw, ph = page.rect.width, page.rect.height
            rect = pymupdf.Rect(line.x0 * pw, line.y0 * ph, line.x1 * pw, line.y1 * ph)
            if line.page not in words:
                words[line.page] = page.get_text("words")
            own = [w for w in words[line.page]
                   if rect.x0 <= (w[0] + w[2]) / 2 <= rect.x1 and rect.y0 <= (w[1] + w[3]) / 2 <= rect.y1]
            m = measure_line(np, pymupdf, page, rect, line.text, own)
            if m is not None:
                m.update({"part": part, "text": line.text, "page": line.page, "pw": pw, "ph": ph})
                measured.append((owner, m))

        for entry, e in entries:
            for part, line in _parts(e):
                measure(entry, part, line)
        if toc.heading is not None:
            measure(container, "heading", toc.heading)
        for page_index in sorted({m["page"] for _, m in measured}):
            settle_page([m for _, m in measured if m["page"] == page_index])

        for owner, m in measured:
            pw, ph = m["pw"], m["ph"]
            x0, y0, x1, y1 = m["box"]
            line = {
                "part": m["part"], "text": m["text"], "page": m["page"],
                "box": [x0 / pw, y0 / ph, x1 / pw, y1 / ph], "baseline": m["baseline"] / ph,
                "skew": m["skew"],
                "words": [[a / pw, b / pw, t] for a, b, t in m["words"]],
                "size": m["size"], "face": m["face"], "bold": m["bold"], "italic": m["italic"],
                "fakebold": m["fakebold"], "rgb": m["rgb"],
                "underline": [m["underline"][0] / ph, m["underline"][1]] if m["underline"] else None,
            }
            md = dict(owner.metadata or {})
            if owner is container:
                md["printed_title"] = line
            else:
                md.setdefault("printed_lines", []).append(line)
            owner.metadata = md
    finally:
        source.close()

"""diagram: The analyzer itself: orchestration and KRM writes."""

from src.analyzers.access import page_of
from typing import Any, Dict, List, Optional, Tuple
from src.analyzers.base import AnalyzerManifest, BaseAnalyzer, KRMPermission
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.identity import derive_composite_id
from src.krm.models import (
    CodeBlock,
    ContainerUnit,
    DiagramBlock,
    FormulaBlock,
    KnowledgeDocument,
    ParagraphBlock,
    UnknownBlock,
    VisualLayout,
    NormalizedRect,
)

from src.analyzers.diagram.signals import FIGURE_ZOOM, INK_LEVEL, LEFT_PAD, MASK_PAD, MAX_LABEL_WIDTH, MAX_LABEL_WORDS, MIN_LABELS, NOTE_SIZE, PAD, RIGHT_PAD, _RE_FIGURE_CAPTION, _RE_SUBLABEL, log
from src.analyzers.diagram.rules import Box, _bbox_of, _runs_on, _size_of, _text_of, figure_area
from src.analyzers.printed import _runs_of
from src.analyzers.source_io import resolve_source_path

class DiagramDetectorAnalyzer(BaseAnalyzer):
    def __init__(self) -> None:
        super().__init__(
            AnalyzerManifest(
                name="DiagramDetectorAnalyzer",
                version="1.0.0",
                description="Clusters short labels on scanned pages into DiagramBlocks",
                krm_permissions={
                    KRMPermission.READ,
                    KRMPermission.INSERT,
                    KRMPermission.TOMBSTONE,
                },
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
        # Collect leaf paragraph blocks with their parent container, by page
        # - and every block of a page, for what of it is not a figure's.
        by_page: Dict[int, List[Tuple[ParagraphBlock, ContainerUnit]]] = {}
        self._blocks: Dict[int, List[Tuple[Any, ContainerUnit]]] = {}

        def walk(container: ContainerUnit) -> None:
            for child in container.children:
                if getattr(child, "is_tombstoned", False):
                    continue
                if isinstance(child, ContainerUnit):
                    walk(child)
                    continue
                pg = page_of(child)
                if pg is None or _bbox_of(child) is None:
                    continue
                self._blocks.setdefault(pg, []).append((child, container))
                if isinstance(child, (ParagraphBlock, UnknownBlock)) and not isinstance(child, DiagramBlock):
                    by_page.setdefault(pg, []).append((child, container))

        for c in doc.root_containers:
            walk(c)

        # A figure is drawn from its own ink where its source can be read.
        self._source = None
        path = resolve_source_path(doc)
        if path:
            try:
                import pymupdf
                self._source = pymupdf.open(path)
            except Exception:
                self._source = None
        count = 0
        try:
            for pg, items in by_page.items():
                count += self._detect_on_page(pg, items)
        finally:
            if self._source is not None:
                self._source.close()
        if count:
            log.info("DiagramDetectorAnalyzer: %d diagram(s) detected", count)

    def _detect_on_page(
        self, page: int, items: List[Tuple[ParagraphBlock, ContainerUnit]]
    ) -> int:
        if len(items) < MIN_LABELS:
            return 0

        caption_text = ""
        caption_box: Optional[Tuple[float, float, float, float]] = None
        labels: List[Tuple[ParagraphBlock, ContainerUnit, str, Tuple[float, float, float, float]]] = []
        # neither labels nor body text: labels OCR ran together, wires it
        # read as letters - the figure's where they stand among its labels
        drawn: List[Tuple[ParagraphBlock, ContainerUnit, str, Tuple[float, float, float, float]]] = []
        prose: List[Tuple[float, float, float, float]] = []
        caption_size = 0.0
        # A real caption is short ("Figure 2-11 Data-related addressing modes"),
        # not an in-text reference ("Figure 2-5 shows how a program's code …").
        for block, _parent in items:
            txt = _text_of(block)
            if txt and _RE_FIGURE_CAPTION.match(txt) and len(txt.split()) <= 10:
                caption_text, caption_box, caption_size = txt, _bbox_of(block), _size_of(block)
                break
        for block, parent in items:
            txt = _text_of(block)
            if not txt:
                continue
            bb = _bbox_of(block)
            if not bb or txt == caption_text:
                # the caption is a block of its own, set as it printed
                continue
            width = bb[2] - bb[0]
            is_sublabel = bool(_RE_SUBLABEL.match(txt))
            # A schematic label is a short AND narrow text block (or an (a)-(g)
            # sub-caption). Other blocks are body text where they run on.
            is_label = (len(txt.split()) <= MAX_LABEL_WORDS and width <= MAX_LABEL_WIDTH) or is_sublabel
            if is_label:
                labels.append((block, parent, txt, bb))
            elif _runs_on(block, txt) and not 0 < _size_of(block) < NOTE_SIZE * caption_size:
                prose.append(bb)
            else:
                drawn.append((block, parent, txt, bb))

        # A diagram region needs a real Figure caption and a cluster of narrow labels.
        if not caption_text or len(labels) < MIN_LABELS:
            return 0
        # Its labels stand by its caption: over it up to the body text over
        # it, or under it down to the body text under it - not every short
        # line of the page. Taken from the whole page, a book's worked
        # examples ("or \"377\" in octal.", "010 001 001") went into the
        # figure over them and out of the text.
        band = None
        if caption_box is not None:
            labels, band = _by_caption(labels, prose, caption_box)
            if len(labels) < MIN_LABELS:
                return 0

        # Region = bbox of all clustered labels, padded (extra on the right for
        # arrows/boxes that extend beyond the text labels).
        x0 = min(b[3][0] for b in labels)
        y0 = min(b[3][1] for b in labels)
        x1 = max(b[3][2] for b in labels)
        y1 = max(b[3][3] for b in labels)
        region = NormalizedRect(
            max(0.0, x0 - LEFT_PAD), max(0.0, y0 - PAD),
            min(1.0, x1 + RIGHT_PAD), min(1.0, y1 + PAD),
        )
        if band is not None:
            # The figure stands in the band between its caption and the text
            # across from it (figure_area): what else OCR read in it - its
            # wires read as letters, labels it ran together - is the
            # figure's too, and the figure is drawn from its own ink, what
            # is not its - its caption, a running head - left out.
            area = figure_area([l[3] for l in labels], prose, band)

            def inside(bb: Box) -> bool:
                return area[0] <= (bb[0] + bb[2]) / 2 <= area[2] and area[1] <= (bb[1] + bb[3]) / 2 <= area[3]

            labels += [d for d in drawn if inside(d[3])]
            # and a listing or a formula OCR made of its marks ("R -J" of
            # Zaks' vertical "REGISTER 0")
            labels += [(b, parent, "", _bbox_of(b)) for b, parent in self._blocks.get(page, [])
                       if isinstance(b, (CodeBlock, FormulaBlock)) and inside(_bbox_of(b))]
            ink = None
            if self._source is not None and page < self._source.page_count:
                import numpy as np
                import pymupdf
                taken = {id(l[0]) for l in labels}
                masks = [_bbox_of(b) for b, _ in self._blocks.get(page, []) if id(b) not in taken]
                ink = figure_ink(np, pymupdf, self._source[page], area, [m for m in masks if m])
            if ink is not None:
                region = NormalizedRect(*ink["box"])
        else:
            # what else OCR read among the labels is the figure's too - not a
            # text column's running by it
            labels += [d for d in drawn if x0 <= (d[3][0] + d[3][2]) / 2 <= x1 and y0 <= (d[3][1] + d[3][3]) / 2 <= y1
                       and not _in_column(d[3], prose, y0, y1)]
            ink = None

        diagram = DiagramBlock(
            # Built from the labels it absorbs, so its identity is theirs
            # (RFC 0009 §5.2) — the uuid4 default made two runs disagree.
            id=derive_composite_id("diagram", *(b.id for b, _p, _t, _bb in labels)),
            caption_text=caption_text,
            labels=[{"text": t, "x0": bb[0], "y0": bb[1], "x1": bb[2], "y1": bb[3]}
                    for _b, _p, t, bb in labels if t],
            visual_layout=VisualLayout(bounding_box=region, page_or_screen_index=page),
            extraction_confidence=0.85,
            classification_confidence=0.80,
            confidence_score=0.80,
        )
        if ink is not None:
            diagram.metadata["printed_ink"] = ink

        # Insert the diagram at the position of the first label, tombstone the rest.
        first_parent = labels[0][1]
        first_block = labels[0][0]
        try:
            idx = first_parent.children.index(first_block)
        except ValueError:
            idx = 0
        first_parent.children.insert(idx, diagram)

        for block, parent, _txt, _bb in labels:
            block.is_tombstoned = True
            if not block.metadata:
                block.metadata = {}
            block.metadata["tombstone_reason"] = f"absorbed_into_diagram:{diagram.id}"

        return 1


def _by_caption(labels: List[Any], prose: List[Tuple[float, float, float, float]],
                caption: Tuple[float, float, float, float]) -> Tuple[List[Any], Tuple[float, float]]:
    """The labels a figure's caption has by it: those over the caption and
    under the body text nearest over it, or else those under the caption
    and over the body text nearest under it - the side with more - and
    that side's band (top, bottom).

    The body text that bounds the figure runs across from its caption. A
    column of text running down beside the figure - the Intel 3000
    manual's, by its block diagram - bounds nothing, and the short lines
    standing in it, its headings ("ACCUMULATOR AND D-BUS"), are its own."""
    across = [b for b in prose if b[0] < caption[2] and caption[0] < b[2]]
    top = max((b[3] for b in across if b[3] <= caption[1]), default=0.0)
    bottom = min((b[1] for b in across if b[1] >= caption[3]), default=1.0)
    over = [l for l in labels if l[3][1] >= top and l[3][3] <= caption[3]
            and not _in_column(l[3], prose, top, caption[1])]
    under = [l for l in labels if l[3][1] >= caption[1] and l[3][3] <= bottom
             and not _in_column(l[3], prose, caption[3], bottom)]
    return (over, (top, caption[1])) if len(over) >= len(under) else (under, (caption[3], bottom))


def _in_column(box: Tuple[float, float, float, float], prose: List[Tuple[float, float, float, float]],
               top: float, bottom: float) -> bool:
    """Whether a box stands in a column of body text: text of its column
    over it and under it, both between top and bottom."""
    middle = (box[0] + box[2]) / 2
    height = box[3] - box[1]
    column = [b for b in prose if b[0] <= middle <= b[2] and b[3] > top and b[1] < bottom]
    return (any(b[3] <= box[1] + height for b in column)
            and any(b[1] >= box[3] - height for b in column))


def figure_ink(np, pymupdf, page: Any, area: Box, masks: List[Box]) -> Optional[Dict[str, Any]]:
    """A figure's own ink, read off its page (a pymupdf page) in its area,
    masks - the boxes of what on the page is not the figure's - left out:
    "box" (page-normalised, the ink's own), "shape" (rows, columns), "runs"
    ([row, first column, end column] each), "page_pt". None where there is
    none."""
    pw, ph = page.rect.width, page.rect.height
    clip = pymupdf.Rect(area[0] * pw, area[1] * ph, area[2] * pw, area[3] * ph) & page.rect
    if clip.is_empty:
        return None
    pix = page.get_pixmap(matrix=pymupdf.Matrix(FIGURE_ZOOM, FIGURE_ZOOM), clip=clip)
    grey = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3].mean(axis=2)
    ink = grey < INK_LEVEL
    for m in masks:
        r0 = int(((m[1] - MASK_PAD) * ph - clip.y0) * FIGURE_ZOOM)
        r1 = int(((m[3] + MASK_PAD) * ph - clip.y0) * FIGURE_ZOOM) + 1
        c0 = int(((m[0] - MASK_PAD) * pw - clip.x0) * FIGURE_ZOOM)
        c1 = int(((m[2] + MASK_PAD) * pw - clip.x0) * FIGURE_ZOOM) + 1
        ink[max(0, r0):max(0, r1), max(0, c0):max(0, c1)] = False
    rows, cols = np.flatnonzero(ink.any(axis=1)), np.flatnonzero(ink.any(axis=0))
    if not len(rows):
        return None
    ink = ink[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1]
    x0, y0 = clip.x0 + cols[0] / FIGURE_ZOOM, clip.y0 + rows[0] / FIGURE_ZOOM
    x1, y1 = clip.x0 + (cols[-1] + 1) / FIGURE_ZOOM, clip.y0 + (rows[-1] + 1) / FIGURE_ZOOM
    return {"box": [x0 / pw, y0 / ph, x1 / pw, y1 / ph], "shape": list(ink.shape),
            "runs": _runs_of(np, ink), "page_pt": [pw, ph]}

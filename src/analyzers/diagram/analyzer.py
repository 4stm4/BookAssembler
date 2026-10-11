"""diagram: The analyzer itself: orchestration and KRM writes.

On a scanned page read line by line a figure is found by the page's own
ink (ink.py): its drawn strokes, the labels standing by them
(_set_figure), drawn as printed from the ink itself. What OCR read in it
goes into the figure, line by line - a block wholly so is tombstoned,
another loses those lines: OCR sets a logic diagram's "Y6" on one line
with the row of the table beside it. Elsewhere a figure is told by its
caption and the short labels by it (_detect_on_page).
"""

from dataclasses import dataclass
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
    TableBlock,
    UnknownBlock,
    VisualLayout,
    NormalizedRect,
)

from src.analyzers.diagram.ink import PageInk, drawn, is_figure, letters, printed_ink, read_page, strokes_ink, with_marks
from src.analyzers.diagram.signals import FIGURE_ZOOM, GAP, INK_LEVEL, LEFT_PAD, MASK_PAD, MAX_LABEL_WIDTH, MAX_LABEL_WORDS, MIN_LABELS, NOTE_LINES, NOTE_SIZE, PAD, REACH, RIGHT_PAD, TOUCH, _RE_FIGURE_CAPTION, _RE_SUBLABEL, log
from src.analyzers.diagram.rules import Box, _bbox_of, _runs_on, _size_of, _text_of, between, drawings, figure_area, holds, is_caption, is_small, meets, near, over
from src.analyzers.heading.rules import _word_char_ratio, body_size
from src.analyzers.heading.signals import MIN_WORD_CHAR_RATIO
from src.analyzers.source_io import resolve_source_path


@dataclass(eq=False)
class _Line:
    """A line of a page's text where it printed: its block and the block's
    container, the line itself (None: a block whose lines have no place of
    their own, taken whole), its text and box; whether its block is a
    figure's caption, or runs on as body text; and whether the line is the
    page's text - a caption, or words set no smaller than the page's body
    - no label of a drawing it stands by."""
    block: Any
    parent: ContainerUnit
    inline: Any
    text: str
    box: Box
    caption: bool
    runs_on: bool
    page_text: bool = False

    @property
    def fixed(self) -> bool:
        """The page's wherever it stands: in a drawing's area it is text
        the drawing stands about."""
        return self.caption or (self.runs_on and self.page_text)

class DiagramDetectorAnalyzer(BaseAnalyzer):
    def __init__(self) -> None:
        super().__init__(
            AnalyzerManifest(
                name="DiagramDetectorAnalyzer",
                version="1.0.0",
                description="Finds the figures drawn on scanned pages, with the labels OCR read in them",
                krm_permissions={
                    KRMPermission.READ,
                    KRMPermission.INSERT,
                    KRMPermission.TOMBSTONE,
                    KRMPermission.MUTATE_ATTRIBUTES,
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
            for pg in sorted(self._blocks):
                found = self._by_ink(pg)
                count += self._detect_on_page(pg, by_page.get(pg, [])) if found is None else found
        finally:
            if self._source is not None:
                self._source.close()
        if count:
            log.info("DiagramDetectorAnalyzer: %d diagram(s) detected", count)

    def _by_ink(self, page: int) -> Optional[int]:
        """The figures of a scanned page found by its own ink, set in the
        document: how many - None where the page is no scan read line by
        line (PrintedLinesAnalyzer), or its source cannot be read."""
        blocks = self._blocks.get(page, [])
        texts = [b for b, _ in blocks if _is_text(b)]
        sizes = sorted(l.get("size") or 0.0 for b in texts for l in (b.metadata or {}).get("printed_lines") or [])
        if self._source is None or page >= self._source.page_count or not sizes:
            return None
        try:
            import cv2
            import numpy as np
            import pymupdf
        except ImportError:
            return None
        em = body_size(texts) or sizes[len(sizes) // 2]
        if not em:
            return None
        ink = read_page(np, cv2, pymupdf, self._source[page], em)
        lines = _page_lines(np, ink, page, blocks)

        # the page's text a drawing stands clear of: its running text for a
        # stroke to be a mark on, every line of it for two drawings to
        # stand either side of - and what else of the page is no text
        running = [_bbox_of(b) for b in texts if any(l.fixed for l in lines if l.block is b)]
        others = [_bbox_of(b) for b, _ in blocks if not _is_text(b) and not isinstance(b, (CodeBlock, FormulaBlock))]
        tables = [_bbox_of(b) for b, _ in blocks if isinstance(b, TableBlock)]
        seeds = drawn(np, ink, running + others)
        parts = drawings([tuple(ink.boxes[k]) for k in seeds], [l.box for l in lines if l.page_text] + others,
                         ink.ems(GAP))
        found = 0
        for strokes in sorted(([seeds[k] for k in part] for part in parts), key=lambda st: ink.box(st)[1]):
            box = ink.box(strokes)
            # a register set as a table of its bits (RegisterAnalyzer) is drawn already
            if any(holds(box, t) or holds(t, box) for t in tables):
                continue
            if is_figure(np, cv2, ink, strokes) and self._set_figure(np, page, ink, box, lines):
                found += 1
        return found

    def _set_figure(self, np, page: int, ink: PageInk, strokes: Box, lines: List[_Line]) -> bool:
        """Set the figure whose drawn strokes stand in a box of a page: the
        lines of the page's text that are its own go into it - those in
        its area, those between it and its caption (a note set under
        Zaks' "Shift and Rotate", over its caption), those touching its
        strokes (TOUCH), and those no text of the page (_Line.page_text)
        within REACH of it as it stands with the ones it has - with the
        marks by it no line accounts for (ink.with_marks), and it is
        drawn from its own ink, the page's text left out. lines loses the
        ones it takes."""
        touch, reach = ink.ems(TOUCH), ink.ems(REACH)
        area = strokes
        own: List[_Line] = []
        made = [(b, parent) for b, parent in self._blocks.get(page, []) if not _is_text(b) and not b.is_tombstoned]
        caption = _caption_by(strokes, lines)
        while True:
            before = area
            gap = between(area, _bbox_of(caption)) if caption is not None else None
            for line in lines:
                noted = gap is not None and holds(gap, line.box)
                if line.caption or (line.fixed and not noted) or any(line is o for o in own):
                    continue
                if (noted or holds(area, line.box) or near(line.box, strokes, touch)
                        or (not line.page_text and near(line.box, area, reach))):
                    own.append(line)
                    area = over([area, line.box])
            # and a listing or a formula OCR made of its marks ("R -J" of
            # Zaks' vertical "REGISTER 0")
            marks = [(b, parent) for b, parent in made
                     if isinstance(b, (CodeBlock, FormulaBlock)) and holds(area, _bbox_of(b))]
            taken = {id(b) for b, _ in marks}
            masks = [l.box for l in lines if not any(l is o for o in own)]
            masks += [_bbox_of(b) for b, _ in made if id(b) not in taken]
            area = with_marks(ink, area, masks, touch)
            if area == before:
                break
        printed = strokes_ink(np, ink, area, masks)
        if printed is None:
            return False

        box = tuple(printed["box"])
        parent, at = self._place(page, box, {id(l.block) for l in own} | taken)
        parts = sorted({l.block.id if l.inline is None else f"{l.block.id}/{_line_number(l)}" for l in own}
                       | {b.id for b, _ in marks})
        diagram = DiagramBlock(
            # Built from the lines it takes, so its identity is theirs
            # (RFC 0009 §5.2) - a drawing with no text in it, its place's.
            id=derive_composite_id("diagram", *(parts or [parent.id, str(page)] + [f"{v:.3f}" for v in box])),
            caption_text=_text_of(caption) if caption is not None else "",
            labels=[{"text": l.text, "x0": l.box[0], "y0": l.box[1], "x1": l.box[2], "y1": l.box[3]}
                    for l in own if l.text],
            visual_layout=VisualLayout(bounding_box=NormalizedRect(*box), page_or_screen_index=page),
            parent_container_id=parent.id,
            extraction_confidence=0.85,
            classification_confidence=0.80,
            confidence_score=0.80,
        )
        diagram.metadata["printed_ink"] = printed
        parent.children.insert(at, diagram)

        reason = f"absorbed_into_diagram:{diagram.id}"
        for block, _parent in marks:
            block.is_tombstoned = True
            block.metadata = {**(block.metadata or {}), "tombstone_reason": reason}
        for block in {id(l.block): l.block for l in own}.values():
            _take_lines(block, [l for l in own if l.block is block], reason)
        lines[:] = [l for l in lines if not any(l is o for o in own)]
        return True

    def _place(self, page: int, box: Box, own: set) -> Tuple[ContainerUnit, int]:
        """Where in the document a figure standing in a box of a page goes
        (a container, a place among its children): after the last block of
        the page standing over it - the page is in reading order
        (PageOrderAnalyzer) - before the page's first where none does. own
        are the blocks it takes (their ids)."""
        blocks = [(b, parent) for b, parent in self._blocks.get(page, [])
                  if not b.is_tombstoned and id(b) not in own]
        middle = (box[1] + box[3]) / 2
        above = [(b, parent) for b, parent in blocks
                 if _bbox_of(b)[0] < box[2] and box[0] < _bbox_of(b)[2] and _bbox_of(b)[3] <= middle]
        if above:
            block, parent = above[-1]
            return parent, parent.children.index(block) + 1
        block, parent = blocks[0] if blocks else self._blocks[page][0]
        return parent, parent.children.index(block)

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
    return printed_ink(np, ink, clip.x0, clip.y0, (pw, ph))


def _is_text(block: Any) -> bool:
    """Whether a block is text as OCR read it - nothing made of it yet."""
    return isinstance(block, (ParagraphBlock, UnknownBlock)) and not isinstance(block, DiagramBlock)


def _page_lines(np, ink: PageInk, page: int, blocks: List[Tuple[Any, ContainerUnit]]) -> List[_Line]:
    """The lines of a page's text, in the document's order, each told the
    page's text or not (_Line.page_text): a caption's, or words
    (MIN_WORD_CHAR_RATIO) set no smaller than the page's body (is_small) -
    its size the page's em, its letters' ink as tall as its running
    text's."""
    lines: List[_Line] = []
    for block, parent in blocks:
        if not _is_text(block):
            continue
        text = _text_of(block)
        caption, runs_on = is_caption(text), _runs_on(block, text)
        placed = [(il, " ".join(getattr(sp, "text", "") for sp in getattr(il, "spans", []) or []).strip(), _bbox_of(il))
                  for il in block.inlines or [] if _bbox_of(il) and page_of(il) == page]
        for inline, line_text, box in placed or [(None, text, _bbox_of(block))]:
            lines.append(_Line(block, parent, inline, line_text, box, caption, runs_on))
    tall = [letters(np, ink, l.box) for l in lines]
    running = sorted(letters(np, ink, l.box, share=75) for l in lines if l.runs_on)
    body_tall = running[len(running) // 2] if running else 0.0
    for line, height in zip(lines, tall):
        size = next((pl.get("size") or 0.0 for pl in (line.block.metadata or {}).get("printed_lines") or []
                     if holds(line.box, tuple(pl["box"]))), 0.0)
        reads = _word_char_ratio(line.text) >= MIN_WORD_CHAR_RATIO
        line.page_text = line.caption or (reads and not is_small(size, ink.em, height, body_tall, line.text))
    return lines


def _line_number(line: _Line) -> int:
    return next(k for k, il in enumerate(line.block.inlines) if il is line.inline)


def _caption_by(box: Box, lines: List[_Line]) -> Optional[Any]:
    """The caption a figure standing in a box has by it (its block): the
    page's nearest over or under it, across from it, no more of the page's
    running text between them than a note's (NOTE_LINES). None where it
    has none."""
    stretches = []
    for block in {id(l.block): l.block for l in lines if l.caption}.values():
        place = _bbox_of(block)
        if place[0] < box[2] and box[0] < place[2] and not meets(place, box):
            stretches.append((between(box, place), block))
    if not stretches:
        return None
    gap, nearest = min(stretches, key=lambda found: found[0][3] - found[0][1])
    running = [l for l in lines if l.fixed and not l.caption and meets(l.box, gap)]
    return nearest if len(running) <= NOTE_LINES else None


def _take_lines(block: Any, taken: List[_Line], reason: str) -> None:
    """Take a figure's lines out of a block: tombstone it where it is left
    with none, else leave it the rest - its box theirs, its print's lines
    without the ones gone."""
    gone = {id(l.inline) for l in taken}
    rest = [il for il in block.inlines or [] if id(il) not in gone]
    boxes = [_bbox_of(il) for il in rest if _bbox_of(il)]
    if any(l.inline is None for l in taken) or not boxes:
        block.is_tombstoned = True
        block.metadata = {**(block.metadata or {}), "tombstone_reason": reason}
        return
    block.inlines = rest
    block.visual_layout.bounding_box = NormalizedRect(*over(boxes))
    printed = (block.metadata or {}).get("printed_lines")
    if printed:
        block.metadata = {**block.metadata, "printed_lines": [
            pl for pl in printed if not any(holds(l.box, tuple(pl["box"])) for l in taken)]}

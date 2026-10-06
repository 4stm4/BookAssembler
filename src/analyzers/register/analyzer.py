"""register: The analyzer itself: orchestration and KRM writes.

Each register drawn on a page (rules.register_frames) becomes a table of
its bits, a cell to each, framed as printed, in place of the text it was
read as: the bits as one word, the ticks as stray letters ("1 l l Ll rT L
L"), sometimes on one line with a label beside the frame ("Cycles: 3
11100101"). What OCR read inside the frame or among its ticks goes into
the table - a block wholly so is tombstoned, another loses those lines.
Early, before anything judges the page's text by its size or weight.
"""

from dataclasses import replace
from typing import Any, Dict, List, Optional

from src.analyzers.base import AnalyzerManifest, BaseAnalyzer, KRMPermission
from src.analyzers.register.rules import ZOOM, Register, _DARK_LEVEL, bits_of, register_frames
from src.analyzers.source_io import resolve_source_path
from src.analyzers.table.boxes import BoxCell, BoxGrid, _ink_size, _table_from_box_grid
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.identity import derive_composite_id
from src.krm.models import ContainerUnit, KnowledgeDocument, NormalizedRect, ParagraphBlock, UnknownBlock

# How far past its frame, up and down, a register's ticks' stray letters
# can be boxed (pt).
_ZONE_PT = 3.0


class RegisterAnalyzer(BaseAnalyzer):
    def __init__(self) -> None:
        super().__init__(
            AnalyzerManifest(
                name="RegisterAnalyzer",
                version="1.0.0",
                description="Sets each register drawn as a framed row of bits as a table of its bits",
                krm_permissions={KRMPermission.READ, KRMPermission.INSERT, KRMPermission.TOMBSTONE,
                                 KRMPermission.MUTATE_ATTRIBUTES},
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
            for root in doc.root_containers:
                self._process(root, source, np, pymupdf)
        finally:
            source.close()

    def _process(self, container: ContainerUnit, source, np, pymupdf) -> None:
        for child in container.children:
            if isinstance(child, ContainerUnit):
                self._process(child, source, np, pymupdf)
        pages = sorted({c.visual_layout.page_or_screen_index for c in _text(container)})
        for page_index in pages:
            if page_index is None or page_index >= source.page_count:
                continue
            page = source[page_index]
            pix = page.get_pixmap(matrix=pymupdf.Matrix(ZOOM, ZOOM))
            rgb = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3]
            dark = rgb.max(axis=2) < _DARK_LEVEL
            words = page.get_text("words")
            for register in register_frames(np, dark):
                self._set(container, page_index, page, register, words, np, dark)

    def _set(self, container: ContainerUnit, page_index: int, page, register: Register, words, np, dark) -> None:
        bits = bits_of(words, register)
        if bits is None:
            return
        pw, ph = page.rect.width, page.rect.height
        zone = (register.x0 / pw, (register.y0 - _ZONE_PT) / ph, register.x1 / pw, (register.y1 + _ZONE_PT) / ph)
        texts = {id(c) for c in _text(container)}
        touched = []
        for idx, block in enumerate(container.children):
            if id(block) not in texts or block.visual_layout.page_or_screen_index != page_index:
                continue
            inside = [il for il in block.inlines or [] if _within(il, zone)]
            if inside:
                touched.append((idx, block, inside))
        if not touched:
            return
        cells = []
        y0, y1 = bits[1], bits[3]
        last = len(register.cuts) - 2
        for k, (a, b) in enumerate(zip(register.cuts, register.cuts[1:])):
            cell = BoxCell(0, k, 1, 1, (a, register.y0, b, register.y1), None,
                           (True, k == last, True, k == 0))
            cell.words = [(a, y0, b, y1, bits[4].strip()[k])]
            # its digit, inside the ticks
            cell.size = _ink_size(np, dark, cell, ZOOM, (register.tick + 0.5) * ZOOM)
            cells.append(cell)
        table = _table_from_box_grid(BoxGrid(register.cuts, [register.y0, register.y1], cells), page_index, pw, ph)
        table.id = derive_composite_id("register", *[b.id for _, b, _ in touched])
        table.parent_container_id = container.id
        table.provenance_info = touched[0][1].provenance_info
        table.metadata["register"] = True
        for _, block, inside in touched:
            gone = {id(il) for il in inside}
            rest = [il for il in block.inlines if id(il) not in gone]
            if not rest:
                block.is_tombstoned = True
                block.metadata = {**(block.metadata or {}), "tombstone_reason": "merged_into_table"}
                continue
            block.inlines = rest
            boxes = [il.visual_layout.bounding_box for il in rest if getattr(il, "visual_layout", None)]
            if boxes:
                block.visual_layout.bounding_box = NormalizedRect(
                    min(b.x0 for b in boxes), min(b.y0 for b in boxes),
                    max(b.x1 for b in boxes), max(b.y1 for b in boxes))
            # its size its own lines', not the stray letters' (OCR sized a
            # tick read as "dn" at 22pt among its 10)
            sizes = [il.visual_layout.style.font_size_pt for il in rest
                     if getattr(il, "visual_layout", None) and il.visual_layout.style and il.visual_layout.style.font_size_pt]
            if sizes and block.visual_layout.style is not None:
                block.visual_layout.style = replace(block.visual_layout.style, font_size_pt=max(sizes))
        container.children.insert(touched[0][0], table)


def _text(container: ContainerUnit) -> List[Any]:
    return [c for c in container.children
            if type(c) in (UnknownBlock, ParagraphBlock) and not c.is_tombstoned and c.visual_layout is not None]


def _within(inline: Any, zone) -> bool:
    vl = getattr(inline, "visual_layout", None)
    b = vl.bounding_box if vl is not None else None
    if b is None:
        return False
    x, y = (b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2
    return zone[0] <= x <= zone[2] and zone[1] <= y <= zone[3]

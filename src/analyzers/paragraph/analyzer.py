"""paragraph: The analyzer itself: orchestration and KRM writes.

OCR cuts a paragraph into blocks where its lines stand a little further
apart, or where a bold word thickens one: the paragraph fixture's one
paragraph came out three. The rest of a paragraph - in its column,
unindented, a line under its last full line (rules.continues) - is merged
into it, its lines and their print (metadata["printed_lines"]) after the
paragraph's own, and tombstoned (RFC 0001 §2.4).

A paragraph a column's or a page's end cuts stays two blocks, each where
it printed; the one going on is marked so (metadata["continues"], the id
of the one before - rules.continues_across), for a translation to take
the sentence whole.

A line of a paragraph OCR misread whole - every word of it drawn from its
print (printed._mark_misread): a formula's line over its explanation,
"(SP-2) <- IXL" read "(SP—2) — IXz" - is no text of it: its lines at the
paragraph's head or foot go to a formula of their own, set as printed.
"""

from typing import Any, Dict, List, Optional

from src.analyzers.base import AnalyzerManifest, BaseAnalyzer, KRMPermission
from src.analyzers.paragraph.rules import continues, continues_across
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.identity import derive_composite_id
from src.krm.models import ContainerUnit, FormulaBlock, KnowledgeDocument, NormalizedRect, ParagraphBlock, VisualLayout


class ParagraphAnalyzer(BaseAnalyzer):
    def __init__(self) -> None:
        super().__init__(
            AnalyzerManifest(
                name="ParagraphAnalyzer",
                version="1.0.0",
                description="Joins the pieces of a paragraph OCR cut apart, marks one a column or page cut",
                krm_permissions={KRMPermission.READ, KRMPermission.MUTATE_ATTRIBUTES, KRMPermission.TOMBSTONE,
                                 KRMPermission.INSERT},
                rg_permissions=set(),
                kg_permissions=set(),
                # Paragraphs are final only once nothing else can claim them.
                depends_on=["UnknownResolverAnalyzer"],
            )
        )

    def run(
        self,
        doc: KnowledgeDocument,
        rg: ReadingGraph,
        kg: KnowledgeGraph,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        for root in doc.root_containers:
            _join(root)
            _split_misread(root)
        flow: List[ParagraphBlock] = []
        for root in doc.root_containers:
            _flow(root, flow)
        for prev, nxt in zip(flow, flow[1:]):
            if continues_across(prev, nxt):
                nxt.metadata = {**(nxt.metadata or {}), "continues": prev.id}


def _join(container: ContainerUnit) -> None:
    """Merge into each paragraph the paragraphs that continue it."""
    prev: Optional[ParagraphBlock] = None
    for child in container.children:
        if isinstance(child, ContainerUnit):
            _join(child)
            prev = None
            continue
        if getattr(child, "is_tombstoned", False):
            continue
        if type(child) is not ParagraphBlock:
            prev = None
            continue
        if prev is not None and continues(prev, child):
            a, b = prev.visual_layout.bounding_box, child.visual_layout.bounding_box
            prev.inlines = list(prev.inlines or []) + list(child.inlines or [])
            prev.visual_layout.bounding_box = NormalizedRect(
                min(a.x0, b.x0), min(a.y0, b.y0), max(a.x1, b.x1), max(a.y1, b.y1))
            printed = list((prev.metadata or {}).get("printed_lines") or []) + \
                list((child.metadata or {}).get("printed_lines") or [])
            if printed:
                prev.metadata = {**(prev.metadata or {}), "printed_lines": printed}
            child.is_tombstoned = True
            child.metadata = {**(child.metadata or {}), "tombstone_reason": "merged_into_paragraph"}
            continue
        prev = child


def _flow(node: Any, out: List[Any]) -> None:
    """The document's live paragraphs in its order - a heading between two
    breaks no sentence a column cut."""
    if isinstance(node, ContainerUnit):
        for child in node.children:
            _flow(child, out)
    elif type(node) is ParagraphBlock and not node.is_tombstoned:
        out.append(node)


def _misread(line: Dict[str, Any]) -> bool:
    words = line.get("words") or []
    return bool(words) and all(len(w) > 4 and w[4].get("ink") for w in words)


def _split_misread(container: ContainerUnit) -> None:
    """Move the lines OCR misread whole at a paragraph's head or foot to a
    formula of their own, beside it."""
    for child in container.children:
        if isinstance(child, ContainerUnit):
            _split_misread(child)
    out: List[Any] = []
    for child in container.children:
        if type(child) is not ParagraphBlock or child.is_tombstoned:
            out.append(child)
            continue
        printed = list((child.metadata or {}).get("printed_lines") or [])
        lines = sorted(child.inlines or [], key=lambda il: il.visual_layout.bounding_box.y0
                       if getattr(il, "visual_layout", None) and il.visual_layout.bounding_box else 0.0)
        bad = []
        for il in lines:
            text = " ".join(getattr(s, "text", "") for s in getattr(il, "spans", []) or []).strip()
            bad.append(any(_misread(pl) and pl.get("text") == text for pl in printed))
        head = 0
        while head < len(lines) and bad[head]:
            head += 1
        foot = len(lines)
        while foot > head and bad[foot - 1]:
            foot -= 1
        # a line on the row of a misread one is the same printed line, OCR
        # cut apart - signetics8080's "T - (I" and "K) - 1 + CI.", a sign
        # it did not read between them
        while head and head < foot and _same_row(lines[head - 1], lines[head]):
            head += 1
        while foot < len(lines) and foot > head and _same_row(lines[foot - 1], lines[foot]):
            foot -= 1
        if head == foot or (head == 0 and foot == len(lines)):
            out.append(child)
            continue
        before = [_formula(child, lines[:head], printed, "head")] if head else []
        after = [_formula(child, lines[foot:], printed, "foot")] if foot < len(lines) else []
        kept = lines[head:foot]
        moved = {id(il) for il in lines[:head] + lines[foot:]}
        child.inlines = [il for il in child.inlines if id(il) not in moved]
        texts = {" ".join(getattr(s, "text", "") for s in il.spans).strip() for il in kept}
        child.metadata = {**child.metadata, "printed_lines": [pl for pl in printed if pl.get("text") in texts]}
        boxes = [il.visual_layout.bounding_box for il in kept]
        child.visual_layout.bounding_box = NormalizedRect(
            min(b.x0 for b in boxes), min(b.y0 for b in boxes), max(b.x1 for b in boxes), max(b.y1 for b in boxes))
        out.extend(before + [child] + after)
    container.children = out


def _same_row(a: Any, b: Any) -> bool:
    """Whether two lines stand on one printed row: each over half the
    other's height."""
    p, q = a.visual_layout.bounding_box, b.visual_layout.bounding_box
    return min(p.y1, q.y1) - max(p.y0, q.y0) > 0.5 * min(p.y1 - p.y0, q.y1 - q.y0)


def _formula(paragraph: ParagraphBlock, lines: List[Any], printed: List[Dict[str, Any]], where: str) -> FormulaBlock:
    texts = [" ".join(getattr(s, "text", "") for s in il.spans).strip() for il in lines]
    boxes = [il.visual_layout.bounding_box for il in lines]
    formula = FormulaBlock(
        id=derive_composite_id("formula", paragraph.id, where),
        latex_expression=" ".join(texts),
        parent_container_id=paragraph.parent_container_id,
        provenance_info=paragraph.provenance_info,
        visual_layout=VisualLayout(
            bounding_box=NormalizedRect(min(b.x0 for b in boxes), min(b.y0 for b in boxes),
                                        max(b.x1 for b in boxes), max(b.y1 for b in boxes)),
            page_or_screen_index=paragraph.visual_layout.page_or_screen_index,
        ),
        extraction_confidence=paragraph.extraction_confidence,
        classification_confidence=0.6,
        confidence_score=min(paragraph.extraction_confidence, 0.6),
    )
    formula.metadata.update({"needs_vision_ocr": True, "detector_signal": "misread_line",
                             "printed_lines": [pl for pl in printed if pl.get("text") in texts]})
    return formula

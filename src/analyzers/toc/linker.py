"""toc: linking contents entries to the headings they name.

Needs the heading tree, so it runs after HeadingAnalyzer — detection
(analyzer.py) runs before it, on the flat block list.

Also resolves where each entry points in the file. The printed page number
is not a page index: front matter shifts it (the Z80 manual's page "1" is
the file's 15th page), and 1970s manuals number pages per chapter ("2-15").
The folios printed on the pages map one onto the other (folios.py). Where a
book prints none that can be read, the shift is measured on the entries
that did link to a heading; with nothing to go on, the target stays
unknown rather than guessed.
"""

import re
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from src.analyzers.access import block_text
from src.analyzers.base import AnalyzerManifest, BaseAnalyzer, KRMPermission
from src.analyzers.toc.folios import EDGE_BOTTOM, EDGE_TOP, PageMap, folio_candidates
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import (
    ContainerUnit,
    EphemeraBlock,
    KnowledgeDocument,
    ParagraphBlock,
    TocEntryBlock,
)

_NUM_RE = re.compile(
    r"^\s*(?:(?:chapter|appendix|part|section|глава|часть|раздел|приложение)\s+)?"
    r"([\dA-ZА-Я]{1,4}(?:\.\d+)*)\.?\s+",
    re.IGNORECASE,
)
_ARABIC_RE = re.compile(r"^\d{1,4}$")
_CHAPTER_PAGE_RE = re.compile(r"^(\d{1,3})-(\d{1,4})$")


def _norm(text: str) -> str:
    return re.sub(r"[\W_]+", " ", (text or "").lower()).strip()


def _number(text: str) -> Optional[str]:
    m = _NUM_RE.match((text or "") + " ")
    return m.group(1).upper() if m else None


def _page(node: Any) -> Optional[int]:
    vl = getattr(node, "visual_layout", None)
    return getattr(vl, "page_or_screen_index", None) if vl else None


class TocLinkAnalyzer(BaseAnalyzer):
    def __init__(self) -> None:
        super().__init__(
            AnalyzerManifest(
                name="TocLinkAnalyzer",
                version="1.0.0",
                description="Links contents entries to their headings and resolves target pages",
                krm_permissions={KRMPermission.READ, KRMPermission.MUTATE_ATTRIBUTES},
                rg_permissions=set(),
                kg_permissions=set(),
                depends_on=["HeadingAnalyzer", "TocAnalyzer"],
            )
        )

    def run(
        self,
        doc: KnowledgeDocument,
        rg: ReadingGraph,
        kg: KnowledgeGraph,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        headings: List[ContainerUnit] = []
        tocs: List[ContainerUnit] = []

        def walk(nodes: List[Any]) -> None:
            for n in nodes:
                if isinstance(n, ContainerUnit):
                    if n.semantic_type == "toc":
                        tocs.append(n)
                    elif n.title:
                        headings.append(n)
                    walk(n.children)

        walk(doc.root_containers)
        if not tocs:
            return
        folios = _page_map(doc.root_containers)
        for toc in tocs:
            entries = [e for e in toc.children if isinstance(e, TocEntryBlock)]
            after = _page(toc)
            # A heading before the contents (the title page) is not what an
            # entry points to.
            pool = [h for h in headings
                    if after is None or _page(h) is None or _page(h) > after]
            _link(entries, pool)
            _resolve_pages(entries, {h.id: h for h in pool}, folios)


def _page_map(containers: List[ContainerUnit]) -> PageMap:
    """The folio of every page: short lines in the page's top and bottom
    bands — running heads and page numbers, EphemeraBlock or not. Judged
    line by line: on a scanned page the folio can share a block with the
    labels of a diagram above it (MCS-40, chapter 3)."""
    found: List[Tuple[int, str]] = []

    def consider(vl: Any, text: str) -> None:
        bb = getattr(vl, "bounding_box", None) if vl else None
        if bb is None or EDGE_TOP <= bb.y0 and bb.y1 <= EDGE_BOTTOM:
            return
        for label in folio_candidates(text):
            found.append((vl.page_or_screen_index, label))

    def walk(nodes: List[Any]) -> None:
        for n in nodes:
            if isinstance(n, ContainerUnit):
                walk(n.children)
                continue
            if getattr(n, "is_tombstoned", False):
                continue
            if isinstance(n, EphemeraBlock):
                consider(n.visual_layout, n.repeated_text)
            elif type(n) is ParagraphBlock:
                lines = [il for il in (n.inlines or []) if getattr(il, "visual_layout", None)]
                if lines:
                    for il in lines:
                        consider(il.visual_layout,
                                 " ".join(s.text for s in il.spans if getattr(s, "text", "")))
                else:
                    consider(n.visual_layout, block_text(n))

    walk(containers)
    return PageMap(found)


def _link(entries: List[TocEntryBlock], headings: List[ContainerUnit]) -> None:
    by_title: Dict[str, ContainerUnit] = {}
    by_number: Dict[str, List[ContainerUnit]] = {}
    for h in headings:
        full = _norm(h.title)
        by_title.setdefault(full, h)
        num = _number(h.title)
        if num:
            by_number.setdefault(num, []).append(h)
            by_title.setdefault(_norm(_NUM_RE.sub("", h.title + " ", count=1)), h)
    for e in entries:
        if e.anchor_id:
            continue
        num = (e.chapter_number or "").strip().rstrip(".").upper() or None
        cands = by_number.get(num, []) if num else []
        if len(cands) == 1:
            e.anchor_id = cands[0].id
            continue
        for key in (_norm(f"{e.chapter_number or ''} {e.entry_text}"), _norm(e.entry_text)):
            if key and key in by_title:
                e.anchor_id = by_title[key].id
                break


def _resolve_pages(entries: List[TocEntryBlock], headings: Dict[str, ContainerUnit],
                   folios: Optional[PageMap] = None) -> None:
    # The book's own folios first: they are what the printed label means.
    if folios:
        for e in entries:
            if e.page_label:
                e.target_page = folios.resolve(e.page_label)
    shift: Counter = Counter()
    chapter_shift: Dict[str, Counter] = {}
    for e in entries:
        if e.target_page is not None:
            continue
        target = _page(headings[e.anchor_id]) if e.anchor_id in headings else None
        if target is None or not e.page_label:
            continue
        e.target_page = target
        if _ARABIC_RE.match(e.page_label):
            shift[target - int(e.page_label)] += 1
        elif (m := _CHAPTER_PAGE_RE.match(e.page_label)):
            chapter_shift.setdefault(m.group(1), Counter())[target - int(m.group(2))] += 1
    for e in entries:
        if e.target_page is not None or not e.page_label:
            continue
        if _ARABIC_RE.match(e.page_label) and shift:
            e.target_page = int(e.page_label) + shift.most_common(1)[0][0]
        elif (m := _CHAPTER_PAGE_RE.match(e.page_label)) and m.group(1) in chapter_shift:
            e.target_page = int(m.group(2)) + chapter_shift[m.group(1)].most_common(1)[0][0]

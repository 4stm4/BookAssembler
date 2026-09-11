"""toc: linking contents entries to the headings they name.

Needs the heading tree, so it runs after HeadingAnalyzer — detection
(analyzer.py) runs before it, on the flat block list.

Also resolves where each entry points in the file. The printed page number
is not a page index: front matter shifts it (the Z80 manual's page "1" is
the file's 15th page), and 1970s manuals number pages per chapter ("2-15").
The shift is measured on the entries that did link to a heading and applied
to the ones that did not; with nothing to measure against, the target stays
unknown rather than guessed.
"""

import re
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from src.analyzers.base import AnalyzerManifest, BaseAnalyzer, KRMPermission
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import ContainerUnit, KnowledgeDocument, TocEntryBlock

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
        for toc in tocs:
            entries = [e for e in toc.children if isinstance(e, TocEntryBlock)]
            after = _page(toc)
            # A heading before the contents (the title page) is not what an
            # entry points to.
            pool = [h for h in headings
                    if after is None or _page(h) is None or _page(h) > after]
            _link(entries, pool)
            _resolve_pages(entries, {h.id: h for h in pool})


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


def _resolve_pages(entries: List[TocEntryBlock], headings: Dict[str, ContainerUnit]) -> None:
    shift: Counter = Counter()
    chapter_shift: Dict[str, Counter] = {}
    for e in entries:
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

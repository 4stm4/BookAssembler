"""
TitlePageAnalyzer — detects title pages and blank pages.

Title page detection:
1. Collect ALL nodes (ParagraphBlock + ContainerUnit headings) from first MAX_SCAN_PAGES
2. Score each page by signals: ALL CAPS, publisher/copyright/ISBN patterns
3. Pages above threshold → replace all their blocks with one TitlePageBlock

Blank page detection:
- ParagraphBlocks with text ≤ 2 chars (e.g. "-", "") → BlankPageBlock
"""

import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from src.analyzers.base import AnalyzerManifest, BaseAnalyzer, KRMPermission
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import (
    BlankPageBlock,
    ContainerUnit,
    KnowledgeDocument,
    ParagraphBlock,
    TitlePageBlock,
    TextLineInline,
    StyledTextSpan,
)

log = logging.getLogger(__name__)

MAX_SCAN_PAGES = 12
MIN_SCORE = 3

_RE_COPYRIGHT = re.compile(r"(?:©|\bcopyright\b|\bcopr\b)", re.IGNORECASE)
_RE_PUBLISHER = re.compile(
    r"\b(?:press|publisher|inc\.|hall|wiley|springer|mcgraw|elsevier|"
    r"academic|prentice|addison|cambridge|oxford|o'reilly)\b",
    re.IGNORECASE,
)
_RE_ISBN = re.compile(r"\bISBN\b", re.IGNORECASE)
_RE_EDITION = re.compile(r"\b\d+(?:st|nd|rd|th)\s+edition\b", re.IGNORECASE)
_RE_YEAR = re.compile(r"\b(19|20)\d{2}\b")


def _get_text(block: Any) -> str:
    if isinstance(block, ParagraphBlock):
        parts = []
        for inline in (block.inlines or []):
            for span in getattr(inline, "spans", []):
                if hasattr(span, "text"):
                    parts.append(span.text)
        return " ".join(parts).strip()
    if isinstance(block, ContainerUnit):
        return (block.title or "").strip()
    return ""


def _page_of(block: Any) -> Optional[int]:
    vl = getattr(block, "visual_layout", None)
    if vl is None:
        return None
    return getattr(vl, "page_or_screen_index", None)



def _is_mostly_upper(text: str) -> bool:
    alpha = [c for c in text if c.isalpha()]
    if len(alpha) < 3:
        return False
    return sum(1 for c in alpha if c.isupper()) / len(alpha) > 0.7


def _score_page_blocks(texts: List[str]) -> int:
    score = 0
    for t in texts:
        if _is_mostly_upper(t) and len(t) > 5:
            score += 2
        if _RE_COPYRIGHT.search(t):
            score += 3
        if _RE_PUBLISHER.search(t):
            score += 2
        if _RE_ISBN.search(t):
            score += 3
        if _RE_EDITION.search(t):
            score += 2
        if _RE_YEAR.search(t) and len(t) < 60:
            score += 1
    if len(texts) >= 3 and all(len(t) < 80 for t in texts):
        score += 1
    return score


def _extract_metadata(texts: List[str]) -> Dict[str, Any]:
    title_parts: List[str] = []
    authors: List[str] = []
    publisher = ""
    edition = ""
    page_role = "title"

    for t in texts:
        if _RE_COPYRIGHT.search(t) or _RE_ISBN.search(t):
            page_role = "copyright"
        if _RE_PUBLISHER.search(t):
            publisher = t.strip()
        m = _RE_EDITION.search(t)
        if m:
            edition = m.group(0)
        if _is_mostly_upper(t) and len(t) > 5 and not _RE_COPYRIGHT.search(t):
            title_parts.append(t.strip())

    for t in texts:
        words = t.strip().split()
        if 2 <= len(words) <= 6 and all(w[0].isupper() for w in words if w[0].isalpha()):
            if not _RE_PUBLISHER.search(t) and not _RE_COPYRIGHT.search(t) and not _RE_ISBN.search(t):
                if not any(kw in t.lower() for kw in ("edition", "copyright", "press", "inc", "limited", "ltd")):
                    if not _is_mostly_upper(t) or len(words) <= 4:
                        authors.append(t.strip())

    return {
        "book_title": " ".join(title_parts),
        "authors": authors[:5],
        "publisher": publisher,
        "edition": edition,
        "page_role": page_role,
    }


_NodeLoc = Tuple[Any, ContainerUnit, int]


class TitlePageAnalyzer(BaseAnalyzer):
    def __init__(self) -> None:
        super().__init__(
            AnalyzerManifest(
                name="TitlePageAnalyzer",
                version="1.1.0",
                description="Detects title pages, blank pages",
                krm_permissions={KRMPermission.READ, KRMPermission.TRANSFORM_NODE, KRMPermission.INSERT},
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
        self._detect_blank_pages(doc)
        self._detect_title_pages(doc)

    def _detect_blank_pages(self, doc: KnowledgeDocument) -> None:
        count = 0
        for container in doc.root_containers:
            count += self._replace_blanks(container)
        if count:
            log.info("TitlePageAnalyzer: %d blank pages detected", count)

    def _replace_blanks(self, container: ContainerUnit) -> int:
        count = 0
        for i, child in enumerate(container.children):
            if isinstance(child, ParagraphBlock) and not isinstance(child, TitlePageBlock):
                text = _get_text(child).strip()
                if len(text) <= 2:
                    page = _page_of(child)
                    if page == 0:
                        # First page with no extractable text = scanned cover image.
                        cover = TitlePageBlock()
                        cover.id = child.id
                        cover.visual_layout = child.visual_layout
                        cover.inlines = child.inlines
                        cover.page_role = "cover"
                        cover.extraction_confidence = 1.0
                        cover.classification_confidence = 1.0
                        container.children[i] = cover
                    else:
                        bp = BlankPageBlock()
                        bp.id = child.id
                        bp.visual_layout = child.visual_layout
                        bp.extraction_confidence = 1.0
                        bp.classification_confidence = 1.0
                        container.children[i] = bp
                    count += 1
            elif isinstance(child, ContainerUnit):
                count += self._replace_blanks(child)
        return count

    def _detect_title_pages(self, doc: KnowledgeDocument) -> None:
        all_locs: List[_NodeLoc] = []
        for container in doc.root_containers:
            self._collect_all(container, all_locs)

        page_groups: Dict[int, List[_NodeLoc]] = {}
        for loc in all_locs:
            page = _page_of(loc[0])
            if page is not None and page < MAX_SCAN_PAGES:
                page_groups.setdefault(page, []).append(loc)

        title_page_count = 0
        for page in sorted(page_groups.keys()):
            locs = page_groups[page]
            texts = [_get_text(loc[0]) for loc in locs if _get_text(loc[0])]
            score = _score_page_blocks(texts)
            log.info("TitlePageAnalyzer: page %d — %d nodes, score=%d", page, len(locs), score)
            if score < MIN_SCORE:
                continue

            meta = _extract_metadata(texts)
            tp = TitlePageBlock(
                book_title=meta["book_title"],
                authors=meta["authors"],
                publisher=meta["publisher"],
                edition=meta["edition"],
                page_role=meta["page_role"],
            )
            first_vl = next((_page_of(l[0]) for l in locs if _page_of(l[0]) is not None), None)
            if first_vl is not None:
                from src.krm.models import VisualLayout, NormalizedRect
                tp.visual_layout = VisualLayout(bounding_box=NormalizedRect(0.0, 0.0, 1.0, 1.0), page_or_screen_index=first_vl)
            tp.extraction_confidence = 0.90
            tp.classification_confidence = 0.90
            full_text = "\n".join(texts)
            tp.inlines = [TextLineInline(spans=[StyledTextSpan(text=full_text)])]

            first_parent: Optional[ContainerUnit] = None
            first_index = 999999
            removed_ids: Set[str] = set()

            for node, parent, idx in sorted(locs, key=lambda x: -x[2]):
                if isinstance(node, ContainerUnit):
                    continue
                nid = getattr(node, 'id', '')
                if nid in removed_ids:
                    continue
                removed_ids.add(nid)
                try:
                    parent.children.remove(node)
                except ValueError:
                    pass
                if first_parent is None or idx < first_index:
                    first_parent = parent
                    first_index = idx

            if first_parent is not None:
                insert_at = min(first_index, len(first_parent.children))
                first_parent.children.insert(insert_at, tp)
                title_page_count += 1

        log.info("TitlePageAnalyzer: %d title pages created", title_page_count)

    def _collect_all(
        self, container: ContainerUnit, result: List[_NodeLoc]
    ) -> None:
        for idx, child in enumerate(container.children):
            if isinstance(child, ParagraphBlock) and not isinstance(child, TitlePageBlock):
                result.append((child, container, idx))
            elif isinstance(child, BlankPageBlock):
                result.append((child, container, idx))
            elif isinstance(child, ContainerUnit):
                pg = _page_of(child)
                if pg is not None and pg < MAX_SCAN_PAGES:
                    result.append((child, container, idx))
                self._collect_all(child, result)

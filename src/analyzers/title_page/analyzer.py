"""title_page: The analyzer itself: orchestration and KRM writes."""

from src.analyzers.access import page_of
from typing import Any, Dict, List, Optional, Set, Tuple
from src.analyzers.base import AnalyzerManifest, BaseAnalyzer, KRMPermission
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.geometry import union_bbox
from src.krm.identity import derive_composite_id
from src.krm.models import (
    BlankPageBlock,
    ContainerUnit,
    KnowledgeDocument,
    ParagraphBlock,
    TitlePageBlock,
    TextLineInline,
    StyledTextSpan,
)

from src.analyzers.title_page.signals import MAX_SCAN_PAGES, MAX_TITLE_BLOCK_LEN, MIN_SCORE, TITLE_MAX_PAGES, _NodeLoc, _RE_STRONG, log
from src.analyzers.title_page.rules import _extract_metadata, _get_text, _score_page_blocks

class TitlePageAnalyzer(BaseAnalyzer):
    def __init__(self) -> None:
        super().__init__(
            AnalyzerManifest(
                name="TitlePageAnalyzer",
                version="1.2.0",
                description="Detects title pages, blank pages",
                krm_permissions={KRMPermission.READ, KRMPermission.TRANSFORM_NODE, KRMPermission.INSERT, KRMPermission.TOMBSTONE},
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
                # A page that carries an image and no text layer is unread, not
                # empty. Relabelling it BlankPageBlock discards the needs_ocr
                # flag and states as fact that the page has no content.
                if (child.metadata or {}).get("needs_ocr"):
                    continue
                text = _get_text(child).strip()
                if len(text) <= 2:
                    page = page_of(child)
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
            page = page_of(loc[0])
            # Only the front matter can hold title/copyright pages.
            if page is not None and page < TITLE_MAX_PAGES:
                page_groups.setdefault(page, []).append(loc)

        already_titled: Set[int] = set()
        for container in doc.root_containers:
            for child in container.children:
                if isinstance(child, TitlePageBlock) and not child.is_tombstoned:
                    vl = getattr(child, "visual_layout", None)
                    if vl and hasattr(vl, "page_or_screen_index"):
                        already_titled.add(vl.page_or_screen_index)

        title_page_count = 0
        for page in sorted(page_groups.keys()):
            if page in already_titled:
                continue
            locs = page_groups[page]
            texts = [_get_text(loc[0]) for loc in locs if _get_text(loc[0])]
            score = _score_page_blocks(texts)
            log.info("TitlePageAnalyzer: page %d — %d nodes, score=%d", page, len(locs), score)
            if score < MIN_SCORE:
                continue
            # A title page has no running paragraphs (only short centered lines).
            if any(len(t) > MAX_TITLE_BLOCK_LEN for t in texts):
                continue
            # Beyond the very first page, require a strong front-matter signal so
            # ALL-CAPS section headings (CONTENTS, SECTION 1) are not caught.
            if page > 0 and not any(_RE_STRONG.search(t) for t in texts):
                continue

            meta = _extract_metadata(texts)
            tp = TitlePageBlock(
                # Aggregates the front-matter blocks it absorbs, so its identity
                # is derived from theirs (RFC 0009 §5.2).
                id=derive_composite_id(
                    "title-page", *[l[0].id for l in locs]
                ),
                book_title=meta["book_title"],
                authors=meta["authors"],
                publisher=meta["publisher"],
                edition=meta["edition"],
                page_role=meta["page_role"],
            )
            first_vl = next((page_of(l[0]) for l in locs if page_of(l[0]) is not None), None)
            if first_vl is not None:
                from src.krm.models import VisualLayout
                # RFC 0021 §5.4 forbids zeroing coordinates: the title page
                # covers the region its sources covered, not the whole sheet.
                region = union_bbox([l[0] for l in locs])
                if region is not None:
                    tp.visual_layout = VisualLayout(
                        bounding_box=region, page_or_screen_index=first_vl,
                    )
            tp.extraction_confidence = 0.90
            tp.classification_confidence = 0.90
            # One inline per source line, each keeping that line's own bbox and
            # StyleDescriptor. Joining them into a single span would discard the
            # geometry of every source node, which RFC 0021 §5.4 requires to stay
            # available and §3 needs to place a title page positionally.
            tp.inlines = []
            for node, _parent, _idx in locs:
                text = _get_text(node)
                if not text.strip():
                    continue
                line = TextLineInline(spans=[StyledTextSpan(text=text)])
                line.visual_layout = getattr(node, "visual_layout", None)
                tp.inlines.append(line)
            if not tp.inlines:
                tp.inlines = [
                    TextLineInline(spans=[StyledTextSpan(text="\n".join(texts))])
                ]

            first_parent: Optional[ContainerUnit] = None
            first_index = 999999
            tombstoned_ids: Set[str] = set()

            # RFC 0001 §2.4 / 0005 §2: no physical deletion. Nodes merged into the
            # title page are tombstoned in place; exporters and Reading Graph skip them.
            for node, parent, idx in sorted(locs, key=lambda x: -x[2]):
                if isinstance(node, ContainerUnit):
                    continue
                nid = getattr(node, 'id', '')
                if nid in tombstoned_ids:
                    continue
                tombstoned_ids.add(nid)
                node.is_tombstoned = True
                if not node.metadata:
                    node.metadata = {}
                node.metadata["tombstone_reason"] = f"merged_into_title_page:{tp.id}"
                try:
                    child_idx = parent.children.index(node)
                except ValueError:
                    child_idx = idx
                if first_parent is None or child_idx < first_index:
                    first_parent = parent
                    first_index = child_idx

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
                pg = page_of(child)
                if pg is not None and pg < MAX_SCAN_PAGES:
                    result.append((child, container, idx))
                self._collect_all(child, result)

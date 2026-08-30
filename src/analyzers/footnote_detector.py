"""
FootnoteDetectorAnalyzer — promote small-font page-bottom paragraphs
that start with a footnote marker to FootnoteBlock
(KRM_ENTITIES_MAP P1.5).

Signals (paragraph must satisfy all three that apply):
  1. Leading marker: superscript digit (¹²³…), plain digit followed by
     a separator ("1.", "1)"), or a symbol ('*', '†', '‡').
  2. Small font: font_size_pt below body-text mode by ≥ 15 %.
  3. Low y-position: bounding_box.y0 in the bottom 30 % of the page
     (allowing books that print footnotes tighter).

Signals 2 and 3 are best-effort — when the source lacks style/bbox, we
fall back to marker-only. Identity of the source ParagraphBlock is
preserved (RFC 0001 §2.3).
"""

import re
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from src.analyzers.base import (
    AnalyzerManifest,
    BaseAnalyzer,
    KGPermission,
    KRMPermission,
)
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import (
    ContainerUnit,
    FootnoteBlock,
    KnowledgeDocument,
    ParagraphBlock,
)


_SUPERSCRIPT_DIGITS = "⁰¹²³⁴⁵⁶⁷⁸⁹"
_SUPER_MAP = {c: i for i, c in enumerate(_SUPERSCRIPT_DIGITS)}

_MARKER_RE = re.compile(
    r"""^\s*
    (?:
        (?P<super>[""" + _SUPERSCRIPT_DIGITS + r"""]+)
      | (?P<digit>\d{1,3})[.)]
      | (?P<sym>[*†‡§¶])
    )
    \s+
    """,
    re.VERBOSE,
)


def _first_text(block: ParagraphBlock) -> str:
    for inline in block.inlines or []:
        for span in getattr(inline, "spans", []) or []:
            txt = getattr(span, "text", "")
            if txt:
                return str(txt)
    return ""


def _full_text(block: ParagraphBlock) -> str:
    parts: List[str] = []
    for inline in block.inlines or []:
        for span in getattr(inline, "spans", []) or []:
            txt = getattr(span, "text", "")
            if txt:
                parts.append(txt)
    return "".join(parts)


def _font_size(block: ParagraphBlock) -> Optional[float]:
    vl = getattr(block, "visual_layout", None)
    st = getattr(vl, "style", None) if vl else None
    return float(getattr(st, "font_size_pt", 0)) or None if st else None


def _bbox_bottom_y(block: ParagraphBlock) -> Optional[float]:
    vl = getattr(block, "visual_layout", None)
    bb = getattr(vl, "bounding_box", None) if vl else None
    return bb.y0 if bb else None


def _parse_marker(text: str) -> Optional[Tuple[str, Optional[int], str]]:
    m = _MARKER_RE.match(text)
    if not m:
        return None
    if m.group("super"):
        marker = m.group("super")
        number = sum(_SUPER_MAP[c] * (10 ** i)
                     for i, c in enumerate(reversed(marker)))
    elif m.group("digit"):
        marker = text[m.start(): m.end()].strip()
        try:
            number = int(m.group("digit"))
        except ValueError:
            number = None
    else:
        marker = m.group("sym")
        number = None
    return marker, number, text[m.end():]


class FootnoteDetectorAnalyzer(BaseAnalyzer):
    def __init__(self) -> None:
        super().__init__(
            AnalyzerManifest(
                name="FootnoteDetectorAnalyzer",
                version="1.0.0",
                description="Promote small-font page-bottom marker paragraphs to FootnoteBlock",
                krm_permissions={
                    KRMPermission.READ,
                    KRMPermission.TRANSFORM_NODE,
                    KRMPermission.INSERT,
                    KRMPermission.MUTATE_ATTRIBUTES,
                },
                rg_permissions=set(),
                kg_permissions={KGPermission.READ},
                depends_on=["NormalizationAnalyzer", "HeadingAnalyzer"],
            )
        )

    def run(
        self,
        doc: KnowledgeDocument,
        rg: ReadingGraph,
        kg: KnowledgeGraph,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        body_size = self._body_font_size(doc)
        small_threshold = body_size * 0.85 if body_size else None
        for root in doc.root_containers:
            self._process(root, small_threshold)

    def _body_font_size(self, doc: KnowledgeDocument) -> Optional[float]:
        sizes: List[float] = []

        def walk(nodes: List[Any]) -> None:
            for n in nodes:
                if isinstance(n, ContainerUnit):
                    walk(n.children)
                elif isinstance(n, ParagraphBlock) and not n.is_tombstoned:
                    s = _font_size(n)
                    if s:
                        sizes.append(round(s, 1))

        walk(list(doc.root_containers))
        if not sizes:
            return None
        return Counter(sizes).most_common(1)[0][0]

    def _process(self, container: ContainerUnit, small_threshold: Optional[float]) -> None:
        for child in container.children:
            if isinstance(child, ContainerUnit):
                self._process(child, small_threshold)

        new_children: List[Any] = []
        for child in container.children:
            if not isinstance(child, ParagraphBlock) or child.is_tombstoned:
                new_children.append(child)
                continue
            if type(child) is not ParagraphBlock:
                new_children.append(child)
                continue

            text = _first_text(child)
            parsed = _parse_marker(text) if text else None
            if not parsed:
                new_children.append(child)
                continue

            marker, number, remainder = parsed

            fs = _font_size(child)
            y0 = _bbox_bottom_y(child)
            font_role = (child.metadata or {}).get("font_role")
            font_is_footnote = font_role == "footnote"

            if not font_is_footnote:
                if fs is not None and small_threshold is not None and fs >= small_threshold:
                    new_children.append(child)
                    continue
            if y0 is not None and y0 < 0.70 and not font_is_footnote:
                # Not near the bottom → probably not a footnote (e.g. numbered
                # step in body text). Leave it as ParagraphBlock.
                new_children.append(child)
                continue

            body_text = (remainder + _full_text(child)[len(text):]).strip()
            if not body_text:
                body_text = remainder.strip()
            cls_conf = 0.85 if font_is_footnote else 0.75
            footnote = FootnoteBlock(
                marker=marker,
                footnote_number=number,
                text=body_text,
                visual_layout=child.visual_layout,
                extraction_confidence=child.extraction_confidence,
                classification_confidence=cls_conf,
                confidence_score=min(child.extraction_confidence, cls_conf),
            )
            footnote.id = child.id  # RFC 0001 §2.3
            new_children.append(footnote)

        container.children = new_children

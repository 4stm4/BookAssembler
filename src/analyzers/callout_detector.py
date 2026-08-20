"""
CalloutDetectorAnalyzer — promote ParagraphBlocks that start with a
"Note:"/"Warning:"/"Tip:"/«Внимание»/⚠/ℹ prefix to CalloutBlock so the
assembler can render them inside a framed admonition environment
(KRM_ENTITIES_MAP P1.4).

The whole prefix ("Note:", "Warning —", "⚠ Внимание.") is stripped into
CalloutBlock.label; the trailing text becomes the first paragraph of
content. Identity of the source block is preserved (RFC 0001 §2.3).
"""

import re
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
    CalloutBlock,
    ContainerUnit,
    KnowledgeDocument,
    ParagraphBlock,
    StyledTextSpan,
    TextLineInline,
)


# Ordering matters: 'important' before 'note' so 'Important' isn't eaten
# by the shorter alternative.
_LABEL_MAP: List[Tuple[str, str, str]] = [
    # (regex-alternation, kind, severity)
    (r"caution|осторожно", "caution", "critical"),
    (r"warning|внимание|предупреждение", "warning", "warning"),
    (r"danger|опасно", "warning", "critical"),
    (r"important|важно", "important", "warning"),
    (r"tip|подсказка|совет", "tip", "info"),
    (r"note|заметка|замечание|примечание", "note", "info"),
    (r"info|информация", "note", "info"),
]

_ICON_MAP: List[Tuple[str, str, str]] = [
    ("⚠", "warning", "warning"),
    ("❗", "important", "warning"),
    ("‼", "warning", "critical"),
    ("ℹ", "note", "info"),
    ("💡", "tip", "info"),
    ("📝", "note", "info"),
]


def _first_text(block: ParagraphBlock) -> str:
    for inline in block.inlines or []:
        for span in getattr(inline, "spans", []) or []:
            txt = getattr(span, "text", "")
            if txt:
                return str(txt)
    return ""


def _classify(text: str) -> Optional[Tuple[str, str, str, str]]:
    """Return (kind, severity, label, remainder) or None."""
    stripped = text.lstrip()

    for icon, kind, severity in _ICON_MAP:
        if stripped.startswith(icon):
            rest = stripped[len(icon):].lstrip(" .!:—-")
            label, remainder = _split_word_label(rest)
            return kind, severity, (icon + (" " + label if label else "")).strip(), remainder

    for pattern, kind, severity in _LABEL_MAP:
        m = re.match(rf"^\s*(?P<label>{pattern})\s*[!:.—–\-]\s*(?P<rest>.*)$",
                     text, re.IGNORECASE)
        if m:
            return kind, severity, m.group("label"), m.group("rest")

    return None


def _split_word_label(text: str) -> Tuple[str, str]:
    """If text starts with a callout keyword, return (label, rest); else ('', text)."""
    for pattern, _, _ in _LABEL_MAP:
        m = re.match(rf"^(?P<label>{pattern})\s*[!:.—–\-]\s*(?P<rest>.*)$",
                     text, re.IGNORECASE)
        if m:
            return m.group("label"), m.group("rest")
    return "", text


def _replace_first_text(block: ParagraphBlock, new_text: str) -> None:
    for inline in block.inlines or []:
        for span in getattr(inline, "spans", []) or []:
            if getattr(span, "text", ""):
                span.text = new_text
                return
    block.inlines = [TextLineInline(spans=[StyledTextSpan(text=new_text)])]


class CalloutDetectorAnalyzer(BaseAnalyzer):
    def __init__(self) -> None:
        super().__init__(
            AnalyzerManifest(
                name="CalloutDetectorAnalyzer",
                version="1.0.0",
                description="Promote 'Note:'/'Warning:'/… paragraphs to CalloutBlock",
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
        for root in doc.root_containers:
            self._process(root)

    def _process(self, container: ContainerUnit) -> None:
        for child in container.children:
            if isinstance(child, ContainerUnit):
                self._process(child)

        new_children: List[Any] = []
        for child in container.children:
            if not isinstance(child, ParagraphBlock) or child.is_tombstoned:
                new_children.append(child)
                continue
            # Do not re-wrap already-typed subclasses (TitlePageBlock etc.)
            if type(child) is not ParagraphBlock:
                new_children.append(child)
                continue

            text = _first_text(child)
            classified = _classify(text) if text else None
            if not classified:
                new_children.append(child)
                continue

            kind, severity, label, remainder = classified
            _replace_first_text(child, remainder.strip())
            callout = CalloutBlock(
                kind=kind,
                severity=severity,
                label=label.strip(),
                content=[child],
                visual_layout=child.visual_layout,
                extraction_confidence=child.extraction_confidence,
                classification_confidence=0.85,
                confidence_score=min(child.extraction_confidence, 0.85),
            )
            callout.id = child.id  # RFC 0001 §2.3
            new_children.append(callout)

        container.children = new_children

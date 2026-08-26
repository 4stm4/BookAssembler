"""
TheoremDetectorAnalyzer — detect theorem-like environments and their proofs.

Detects prefixed paragraphs:
  Theorem/Lemma/Corollary/Proposition + optional number + optional name
  Proof/Доказательство prefix
  Example/Пример prefix
  Remark/Замечание prefix

Each detected block becomes a SemanticUnit decorator (TheoremSpec, ProofSpec,
ExampleSpec, RemarkSpec) attached to the containing paragraph via
target_block_id. The structural block remains a ParagraphBlock — the decorator
adds semantic meaning (RFC 0002 semantic layer).
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
    ContainerUnit,
    ExampleSpec,
    KnowledgeDocument,
    ParagraphBlock,
    ProofSpec,
    RemarkSpec,
    TheoremSpec,
)

_THEOREM_TYPES = {
    "theorem": "theorem", "теорема": "theorem",
    "lemma": "lemma", "лемма": "lemma",
    "corollary": "corollary", "следствие": "corollary",
    "proposition": "proposition", "утверждение": "proposition",
}

_PROOF_KEYWORDS = {"proof", "доказательство"}

_EXAMPLE_KEYWORDS = {"example", "пример"}

_REMARK_KEYWORDS = {"remark", "замечание", "observation", "наблюдение"}

_THEOREM_RE = re.compile(
    r"^\s*(?P<keyword>" + "|".join(_THEOREM_TYPES.keys()) + r")"
    r"(?:\s+(?P<number>\d+(?:\.\d+)*))?\.?"
    r"(?:\s*\((?P<name>[^)]+)\))?"
    r"\s*[.:—–\-]?\s*(?P<rest>.*)$",
    re.IGNORECASE,
)

_PROOF_RE = re.compile(
    r"^\s*(?P<keyword>" + "|".join(_PROOF_KEYWORDS) + r")"
    r"(?:\s*[.:—–\-])?\s*(?P<rest>.*)$",
    re.IGNORECASE,
)

_EXAMPLE_RE = re.compile(
    r"^\s*(?P<keyword>" + "|".join(_EXAMPLE_KEYWORDS) + r")"
    r"(?:\s+(?P<number>\d+(?:\.\d+)*))?\.?"
    r"(?:\s*\((?P<name>[^)]+)\))?"
    r"\s*[.:—–\-]?\s*(?P<rest>.*)$",
    re.IGNORECASE,
)

_REMARK_RE = re.compile(
    r"^\s*(?P<keyword>" + "|".join(_REMARK_KEYWORDS) + r")"
    r"(?:\s+(?P<number>\d+(?:\.\d+)*))?\.?"
    r"(?:\s*\((?P<name>[^)]+)\))?"
    r"\s*[.:—–\-]?\s*(?P<rest>.*)$",
    re.IGNORECASE,
)

_PROOF_END_MARKERS = {"□", "∎", "qed", "q.e.d.", "ч.т.д.", "чтд"}


def _first_text(block: ParagraphBlock) -> str:
    for inline in block.inlines or []:
        for span in getattr(inline, "spans", []) or []:
            txt = getattr(span, "text", "")
            if txt:
                return str(txt)
    return ""


class TheoremDetectorAnalyzer(BaseAnalyzer):
    def __init__(self) -> None:
        super().__init__(
            AnalyzerManifest(
                name="TheoremDetectorAnalyzer",
                version="1.0.0",
                description="Detect theorem/proof/example/remark environments and attach SemanticUnit decorators",
                krm_permissions={
                    KRMPermission.READ,
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
            self._process(root, doc)

    def _process(self, container: ContainerUnit, doc: KnowledgeDocument) -> None:
        for child in container.children:
            if isinstance(child, ContainerUnit):
                self._process(child, doc)

        last_theorem_id = ""
        for child in container.children:
            if not isinstance(child, ParagraphBlock) or child.is_tombstoned:
                continue
            if type(child) is not ParagraphBlock:
                continue

            text = _first_text(child)
            if not text:
                continue

            m = _THEOREM_RE.match(text)
            if m:
                kw = m.group("keyword").lower()
                stype = _THEOREM_TYPES.get(kw, "theorem")
                spec = TheoremSpec(
                    target_block_id=child.id,
                    statement_type=stype,
                    name=m.group("name") or "",
                    number=m.group("number") or "",
                )
                child.metadata = child.metadata or {}
                child.metadata["semantic_decorator"] = "theorem"
                child.metadata["statement_type"] = stype
                if m.group("number"):
                    child.metadata["theorem_number"] = m.group("number")
                if m.group("name"):
                    child.metadata["theorem_name"] = m.group("name")
                doc.semantic_units.append(spec)
                last_theorem_id = child.id
                continue

            m = _PROOF_RE.match(text)
            if m:
                spec = ProofSpec(
                    target_block_id=child.id,
                    proved_statement_id=last_theorem_id,
                )
                child.metadata = child.metadata or {}
                child.metadata["semantic_decorator"] = "proof"
                doc.semantic_units.append(spec)
                continue

            m = _EXAMPLE_RE.match(text)
            if m:
                spec = ExampleSpec(
                    target_block_id=child.id,
                    name=m.group("name") or "",
                    number=m.group("number") or "",
                )
                child.metadata = child.metadata or {}
                child.metadata["semantic_decorator"] = "example"
                doc.semantic_units.append(spec)
                continue

            m = _REMARK_RE.match(text)
            if m:
                spec = RemarkSpec(
                    target_block_id=child.id,
                    name=m.group("name") or "",
                    number=m.group("number") or "",
                )
                child.metadata = child.metadata or {}
                child.metadata["semantic_decorator"] = "remark"
                doc.semantic_units.append(spec)
                continue

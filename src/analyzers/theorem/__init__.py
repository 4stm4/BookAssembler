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

from src.analyzers.theorem.analyzer import TheoremDetectorAnalyzer

__all__ = [
    "TheoremDetectorAnalyzer",
]

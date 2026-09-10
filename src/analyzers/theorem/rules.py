"""theorem: Pure decision logic — no KRM writes, no I/O."""

from src.analyzers.theorem.signals import _EXAMPLE_KEYWORDS, _EXAMPLE_RE, _PROOF_END_MARKERS, _PROOF_KEYWORDS, _PROOF_RE, _REMARK_KEYWORDS, _REMARK_RE, _THEOREM_RE, _THEOREM_TYPES
import re
from src.krm.models import (
    ContainerUnit,
    ExampleSpec,
    KnowledgeDocument,
    ParagraphBlock,
    ProofSpec,
    RemarkSpec,
    TheoremSpec,
)


"""algorithm: Pure decision logic — no KRM writes, no I/O."""

from src.analyzers.algorithm.signals import _ALGO_PREFIX_RE, _PSEUDO_KEYWORDS
import re
from src.krm.models import (
    AlgorithmBlock,
    ContainerUnit,
    KnowledgeDocument,
    ParagraphBlock,
)


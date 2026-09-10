"""citation: Pure decision logic — no KRM writes, no I/O."""

from src.analyzers.citation.signals import _CITE_RE
import re
from src.krm.models import (
    BibEntryBlock,
    ContainerUnit,
    KnowledgeDocument,
    ParagraphBlock,
)


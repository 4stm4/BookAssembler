"""index: Pure decision logic — no KRM writes, no I/O."""

from src.analyzers.index.signals import _INDEX_ENTRY_RE, _INDEX_TITLE_RE
import re
from typing import Any, Dict, List, Optional
from src.krm.models import (
    ContainerUnit,
    IndexEntryBlock,
    KnowledgeDocument,
    ParagraphBlock,
)

def _parse_page_refs(raw: str) -> List[str]:
    return [r.strip() for r in raw.split(",") if r.strip()]

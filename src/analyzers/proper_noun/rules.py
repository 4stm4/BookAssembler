"""proper_noun: Pure decision logic — no KRM writes, no I/O."""

from src.analyzers.proper_noun.signals import _DATE_RE, _ORG_RE, _PATTERNS, _PERSON_RE, _PRODUCT_RE, _VERSION_RE
import re
from typing import Any, Dict, List, Optional, Set, Tuple
from src.graph.knowledge_graph import (
    EntityType,
    KGEntityNode,
    KnowledgeGraph,
    RelationType,
)
from src.krm.models import (
    ContainerUnit,
    KnowledgeDocument,
    ParagraphBlock,
)


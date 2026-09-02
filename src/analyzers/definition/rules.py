"""definition: Pure decision logic — no KRM writes, no I/O."""

from src.analyzers.definition.signals import _DEFINITION_PATTERN_RE, _DEFINITION_PREFIX_RE
import re
from typing import Any, Dict, List, Optional
from src.krm.models import (
    ContainerUnit,
    DefinitionSpec,
    KnowledgeDocument,
    ParagraphBlock,
    StyledTextSpan,
)


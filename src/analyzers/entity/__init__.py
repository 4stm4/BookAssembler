"""entity."""

from src.analyzers.entity.signals import _HEX_RE, _INSTRUCTION_RE, _PATTERNS, _REGISTER_RE
from src.analyzers.entity.rules import _collect_spans
from src.analyzers.entity.analyzer import EntityExtractorAnalyzer

__all__ = [
    "EntityExtractorAnalyzer",
    "_HEX_RE",
    "_INSTRUCTION_RE",
    "_PATTERNS",
    "_REGISTER_RE",
    "_collect_spans",
]

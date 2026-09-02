"""
DefinitionDetectorAnalyzer — detect formal definitions in text.

Detection heuristics:
  1. Prefix "Definition N." / "Определение N."
  2. Pattern "X — это" / "X is defined as" / "X means"
  3. Italic/bold leading term followed by "—" or ":" definition

Attaches a DefinitionSpec (SemanticUnit) to the paragraph via target_block_id.
Populates DefinitionSpec.term and .definition_text from the detected content.
"""

from src.analyzers.definition.signals import _DEFINITION_PATTERN_RE, _DEFINITION_PREFIX_RE
from src.analyzers.definition.rules import _has_styled_lead
from src.analyzers.definition.analyzer import DefinitionDetectorAnalyzer

__all__ = [
    "DefinitionDetectorAnalyzer",
    "_DEFINITION_PATTERN_RE",
    "_DEFINITION_PREFIX_RE",
    "_has_styled_lead",
]

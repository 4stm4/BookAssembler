"""
DefinitionDetectorAnalyzer — detect formal definitions in text.

Detection heuristics:
  1. Prefix "Definition N." / "Определение N."
  2. Pattern "X — это" / "X is defined as" / "X means"
  3. Italic/bold leading term followed by "—" or ":" definition

Attaches a DefinitionSpec (SemanticUnit) to the paragraph via target_block_id.
Populates DefinitionSpec.term and .definition_text from the detected content.
"""

from src.analyzers.definition.analyzer import DefinitionDetectorAnalyzer

__all__ = [
    "DefinitionDetectorAnalyzer",
]

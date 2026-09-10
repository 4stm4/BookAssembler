"""
CitationLinkerAnalyzer — link inline citations [N] to BibEntryBlock entities
and create AUTHORED_BY edges from Person entities to bibliography entries.

Phase 1: scan paragraphs for [N] citation markers, find matching BibEntryBlock
         by cite_key, create CITES edge paragraph→bib_entity.
Phase 2: scan BibEntryBlock.authors, find matching PERSON entities in KG,
         create AUTHORED_BY edge person_entity→bib_entity.
"""

from src.analyzers.citation.analyzer import CitationLinkerAnalyzer

__all__ = [
    "CitationLinkerAnalyzer",
]

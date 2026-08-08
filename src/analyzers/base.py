"""
Analyzer API and permissions base definitions for Knowledge Assembly Engine (KAE).

This module defines permission enums, analyzer manifests, security exception types,
and the abstract BaseAnalyzer class according to RFC 0005 (docs/architecture/0005-analyzer-api.md).

Guarantees:
- Strict typing (100% mypy --strict compatible)
- Standard library dependencies only (dataclasses, enum, typing, abc, set)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Set

from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import KnowledgeDocument


class KRMPermission(Enum):
    """
    Permissions required to access or mutate Knowledge Representation Model (KRM) nodes.
    """
    READ = auto()               # Reading KRM node structure and properties
    MUTATE_ATTRIBUTES = auto()  # Modifying text content, styles, and metadata
    TRANSFORM_NODE = auto()     # Replacing node class type
    INSERT = auto()             # Creating and inserting new nodes into hierarchy
    TOMBSTONE = auto()          # Marking node as tombstoned (is_tombstoned = True)


class RGPermission(Enum):
    """
    Permissions required to access or mutate Reading Graph (RG) trajectories.
    """
    READ = auto()               # Reading trajectories and step sequences
    MUTATE_EDGES = auto()       # Adding, modifying, or removing reading step edges


class KGPermission(Enum):
    """
    Permissions required to access or mutate Knowledge Graph (KG) entities and edges.
    """
    READ = auto()               # Reading entities and semantic edge relations
    MUTATE_ENTITIES = auto()    # Adding and updating external domain entities
    MUTATE_EDGES = auto()       # Adding and updating semantic relation edges


class SecurityViolationError(Exception):
    """
    Raised when an analyzer attempts an operation not authorized by its manifest permissions.
    """
    pass


@dataclass(frozen=True)
class AnalyzerManifest:
    """
    Declarative specification of an analyzer's identity, permissions, and dependencies.
    """
    name: str
    version: str
    description: str
    krm_permissions: Set[KRMPermission] = field(default_factory=set)
    rg_permissions: Set[RGPermission] = field(default_factory=set)
    kg_permissions: Set[KGPermission] = field(default_factory=set)
    depends_on: List[str] = field(default_factory=list)


class BaseAnalyzer(ABC):
    """
    Abstract base class for all pipeline analyzers.
    Analyzers process and enrich KRM documents, Reading Graphs, and Knowledge Graphs
    strictly within their declared manifest permissions.
    """

    def __init__(self, manifest: AnalyzerManifest) -> None:
        self._manifest = manifest

    @property
    def manifest(self) -> AnalyzerManifest:
        """
        Returns the analyzer's declared manifest.
        """
        return self._manifest

    @abstractmethod
    def run(
        self,
        doc: KnowledgeDocument,
        rg: ReadingGraph,
        kg: KnowledgeGraph,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Executes the analyzer transformation on the document, reading graph, and knowledge graph.
        """
        pass

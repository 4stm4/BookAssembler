"""
Reading Graph (RG) implementation for Knowledge Assembly Engine (KAE).

This module defines reading flow tracks, edge connections, and the DAG container
for representing reading trajectories according to RFC 0004 (docs/architecture/0004-reading-graph.md).

Guarantees:
- Strict typing (100% mypy --strict compatible)
- Complete isolation from KRM internal structures (references by node ID strings)
- Strict DAG invariant enforcement via CyclicReadingPathError
- Standard library dependencies only (dataclasses, enum, typing)
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Set


class ReadingTrack(str, Enum):
    """
    Parallel reading tracks supported in the Reading Graph.
    """
    MAIN_FLOW = "main_flow"
    SIDEBAR_FLOW = "sidebar_flow"
    FOOTNOTE_FLOW = "footnote_flow"
    CAPTION_FLOW = "caption_flow"
    CODE_EXPLANATION = "code_expl"


@dataclass
class ReadingEdge:
    """
    Directed step in a reading trajectory connecting two KRM node IDs.
    """
    source_id: str
    target_id: str
    track: ReadingTrack = ReadingTrack.MAIN_FLOW
    confidence: float = 1.0
    provenance_analyzer: str = ""


class CyclicReadingPathError(Exception):
    """
    Raised when adding an edge to the Reading Graph creates a cycle on a reading track.
    """
    pass


class ReadingGraph:
    """
    Container managing reading order trajectories as Directed Acyclic Graphs (DAGs).
    Maintains multiple parallel reading tracks (Main Flow, Sidebars, Footnotes, etc.).
    """

    def __init__(self) -> None:
        self._edges: List[ReadingEdge] = []
        self._adjacency_out: Dict[str, List[ReadingEdge]] = {}
        self._adjacency_in: Dict[str, List[ReadingEdge]] = {}

    def _has_path(self, start_id: str, target_id: str, track: ReadingTrack) -> bool:
        """
        Checks via BFS whether a path exists from start_id to target_id on the given track.
        """
        if start_id == target_id:
            return True

        visited: Set[str] = {start_id}
        queue: List[str] = [start_id]

        while queue:
            curr = queue.pop(0)
            for edge in self._adjacency_out.get(curr, []):
                if edge.track == track:
                    nxt = edge.target_id
                    if nxt == target_id:
                        return True
                    if nxt not in visited:
                        visited.add(nxt)
                        queue.append(nxt)

        return False

    def add_step(
        self,
        source_id: str,
        target_id: str,
        track: ReadingTrack = ReadingTrack.MAIN_FLOW,
        confidence: float = 1.0,
        analyzer_name: str = "",
    ) -> None:
        """
        Adds a reading step between two KRM nodes on a specified track.
        Enforces DAG acyclicity on the track; raises CyclicReadingPathError if a cycle is introduced.
        """
        if self._has_path(start_id=target_id, target_id=source_id, track=track):
            raise CyclicReadingPathError(
                f"Cannot add reading step from '{source_id}' to '{target_id}' "
                f"on track '{track.value}': creates a cycle in ReadingGraph."
            )

        edge = ReadingEdge(
            source_id=source_id,
            target_id=target_id,
            track=track,
            confidence=confidence,
            provenance_analyzer=analyzer_name,
        )

        self._edges.append(edge)
        self._adjacency_out.setdefault(source_id, []).append(edge)
        self._adjacency_in.setdefault(target_id, []).append(edge)

    def get_outgoing_edges(
        self, node_id: str, track: Optional[ReadingTrack] = None
    ) -> List[ReadingEdge]:
        """
        Retrieves outgoing reading edges from a node, optionally filtered by track.
        """
        edges = self._adjacency_out.get(node_id, [])
        if track is None:
            return list(edges)
        return [e for e in edges if e.track == track]

    def get_incoming_edges(
        self, node_id: str, track: Optional[ReadingTrack] = None
    ) -> List[ReadingEdge]:
        """
        Retrieves incoming reading edges to a node, optionally filtered by track.
        """
        edges = self._adjacency_in.get(node_id, [])
        if track is None:
            return list(edges)
        return [e for e in edges if e.track == track]

    def get_sequence(
        self, root_id: str, track: ReadingTrack = ReadingTrack.MAIN_FLOW
    ) -> List[str]:
        """
        Traverses the Reading Graph along the specified track starting from root_id.
        Returns the ordered list of node IDs forming the linear reading trajectory.
        At branch points, selects the outgoing edge with the highest confidence.
        """
        sequence: List[str] = [root_id]
        current_id = root_id
        visited: Set[str] = {root_id}

        while True:
            outgoing = [
                e for e in self._adjacency_out.get(current_id, [])
                if e.track == track and e.target_id not in visited
            ]
            if not outgoing:
                break

            best_edge = max(outgoing, key=lambda e: e.confidence)
            current_id = best_edge.target_id
            visited.add(current_id)
            sequence.append(current_id)

        return sequence

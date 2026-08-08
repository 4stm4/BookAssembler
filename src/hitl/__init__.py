"""
Human-in-the-Loop & Interactive Ground Truth Engine for Knowledge Assembly Engine (KAE).

Provides CorrectionStatus, HITLTaskItem, and HITLManager according to RFC 0016.
"""

from src.hitl.manager import (
    CorrectionStatus,
    HITLManager,
    HITLTaskItem,
)

__all__ = [
    "CorrectionStatus",
    "HITLManager",
    "HITLTaskItem",
]

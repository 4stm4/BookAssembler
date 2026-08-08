"""
Job & Resource Management Engine for Knowledge Assembly Engine (KAE).

Provides JobStatus, ResourceLimits, JobRecord, JobManager, and ResourceManager
according to RFC 0019.
"""

from src.jobs.manager import (
    JobManager,
    JobRecord,
    JobStatus,
    ResourceManager,
    ResourceLimits,
)
from src.jobs.pyjobkit_bridge import KAEGenericExecutor, PyJobKitBridge

__all__ = [
    "JobManager",
    "JobRecord",
    "JobStatus",
    "ResourceManager",
    "ResourceLimits",
    "PyJobKitBridge",
    "KAEGenericExecutor",
]

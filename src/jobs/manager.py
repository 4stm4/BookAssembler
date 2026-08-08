"""
Job & Resource Management Engine for Knowledge Assembly Engine (KAE).

Implements JobStatus, ResourceLimits, JobRecord, JobManager, and ResourceManager
according to RFC 0019.

Guarantees:
- Strict typing (100% mypy --strict compatible)
- Standard library dependencies only (dataclasses, enum, typing, datetime, uuid)
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, Optional
from uuid import uuid4


class JobStatus(Enum):
    """
    Lifecycle status states for execution jobs in Knowledge Assembly Engine.
    """
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING_FOR_HUMAN = "WAITING_FOR_HUMAN"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


@dataclass
class ResourceLimits:
    """
    Budgeting constraints for memory, compute cores, GPU, and execution timeout.
    """
    max_ram_mb: int = 8192
    max_cpu_cores: int = 4
    max_gpu_vram_mb: int = 0
    timeout_seconds: int = 3600


@dataclass
class JobRecord:
    """
    Audit and tracking record for a processing job.
    """
    source_uri: str
    job_id: str = field(default_factory=lambda: str(uuid4()))
    status: JobStatus = JobStatus.QUEUED
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    error_message: Optional[str] = None
    artifacts_manifest: Dict[str, str] = field(default_factory=dict)


class JobManager:
    """
    Manager for job lifecycle, state transitions, and execution tracking.
    """

    def __init__(self) -> None:
        self._jobs: Dict[str, JobRecord] = {}

    def create_job(self, source_uri: str) -> JobRecord:
        """
        Creates and queues a new processing job.
        """
        job = JobRecord(
            source_uri=source_uri,
            status=JobStatus.QUEUED,
        )
        self._jobs[job.job_id] = job
        return job

    def update_status(
        self,
        job_id: str,
        new_status: JobStatus,
        error: Optional[str] = None,
    ) -> None:
        """
        Updates job status, refreshes timestamp, and records optional error message.
        """
        job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(f"Job with ID '{job_id}' not found")

        job.status = new_status
        job.updated_at = datetime.now(timezone.utc).isoformat()
        if error is not None:
            job.error_message = error

    def get_job(self, job_id: str) -> Optional[JobRecord]:
        """
        Retrieves a JobRecord by job_id.
        """
        return self._jobs.get(job_id)


class ResourceManager:
    """
    Manager for verifying platform resource availability against requested budgeting limits.
    """

    def __init__(self, available_limits: Optional[ResourceLimits] = None) -> None:
        self.available_limits = available_limits or ResourceLimits(
            max_ram_mb=16384,
            max_cpu_cores=8,
            max_gpu_vram_mb=8192,
            timeout_seconds=7200,
        )

    def check_availability(self, required: ResourceLimits) -> bool:
        """
        Checks whether required resource limits fit within available system constraints.
        """
        if required.max_ram_mb > self.available_limits.max_ram_mb:
            return False
        if required.max_cpu_cores > self.available_limits.max_cpu_cores:
            return False
        if required.max_gpu_vram_mb > self.available_limits.max_gpu_vram_mb:
            return False
        if required.timeout_seconds > self.available_limits.timeout_seconds:
            return False

        return True

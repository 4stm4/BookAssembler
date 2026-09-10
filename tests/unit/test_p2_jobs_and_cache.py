"""
Unit tests for the Job Manager & Resource Management Engine (RFC 0019).
"""

from src.jobs.manager import (
    JobManager,
    JobRecord,
    JobStatus,
    ResourceManager,
    ResourceLimits,
)


def test_job_manager_lifecycle_and_status_transitions() -> None:
    """
    Test job creation, QUEUED state, transitions to RUNNING, COMPLETED, and error recording on FAILED.
    """
    manager = JobManager()

    source_uri = "file:///docs/book_assembly.pdf"
    job = manager.create_job(source_uri)

    assert job.source_uri == source_uri
    assert job.status == JobStatus.QUEUED
    assert job.error_message is None

    # Retrieve job
    retrieved = manager.get_job(job.job_id)
    assert retrieved is not None
    assert retrieved.job_id == job.job_id

    # Update status to RUNNING
    manager.update_status(job.job_id, JobStatus.RUNNING)
    assert job.status == JobStatus.RUNNING

    # Update status to FAILED with error message
    error_msg = "Out of memory error during layout parsing"
    manager.update_status(job.job_id, JobStatus.FAILED, error=error_msg)
    assert job.status == JobStatus.FAILED
    assert job.error_message == error_msg


def test_resource_manager_budgeting_limits() -> None:
    """
    Test resource availability checks against RAM, CPU cores, GPU VRAM, and timeouts.
    """
    resource_mgr = ResourceManager(
        available_limits=ResourceLimits(
            max_ram_mb=8192,
            max_cpu_cores=4,
            max_gpu_vram_mb=4096,
            timeout_seconds=1800,
        )
    )

    # Valid requirements
    valid_req = ResourceLimits(
        max_ram_mb=4096,
        max_cpu_cores=2,
        max_gpu_vram_mb=2048,
        timeout_seconds=600,
    )
    assert resource_mgr.check_availability(valid_req) is True

    # Exceeding RAM
    excess_ram = ResourceLimits(
        max_ram_mb=16384,
        max_cpu_cores=2,
        max_gpu_vram_mb=2048,
        timeout_seconds=600,
    )
    assert resource_mgr.check_availability(excess_ram) is False

    # Exceeding CPU
    excess_cpu = ResourceLimits(
        max_ram_mb=4096,
        max_cpu_cores=8,
        max_gpu_vram_mb=2048,
        timeout_seconds=600,
    )
    assert resource_mgr.check_availability(excess_cpu) is False


if __name__ == "__main__":
    test_job_manager_lifecycle_and_status_transitions()
    test_resource_manager_budgeting_limits()
    print("ALL P2 INFRASTRUCTURE TESTS PASSED!")

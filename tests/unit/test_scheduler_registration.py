"""Unit tests for scheduler data-driven job registration."""

from __future__ import annotations

from core.scheduler.daemon import JobConfig, SchedulerDaemon


def test_all_default_jobs_registered():
    """Scheduler should register exactly 16 default jobs."""
    daemon = SchedulerDaemon("test-empire")
    assert len(daemon._jobs) == 16


def test_every_job_has_a_handler():
    """Every registered job must have a callable handler."""
    daemon = SchedulerDaemon("test-empire")
    for name, job in daemon._jobs.items():
        assert callable(job.handler), f"Job '{name}' handler is not callable"


def test_job_type_equals_name():
    """job_type property should always return the job name."""
    daemon = SchedulerDaemon("test-empire")
    for name, job in daemon._jobs.items():
        assert job.job_type == job.name == name


def test_handler_naming_convention():
    """Each job's handler should be _run_{name} method on the daemon."""
    daemon = SchedulerDaemon("test-empire")
    for name, job in daemon._jobs.items():
        expected_method = f"_run_{name}"
        assert hasattr(daemon, expected_method), f"Missing handler method: {expected_method}"
        assert job.handler == getattr(daemon, expected_method)


def test_priorities_are_valid():
    """All job priorities should be between 1 and 10."""
    daemon = SchedulerDaemon("test-empire")
    for name, job in daemon._jobs.items():
        assert 1 <= job.priority <= 10, f"Job '{name}' priority {job.priority} out of range"


def test_intervals_are_positive():
    """All job intervals should be positive."""
    daemon = SchedulerDaemon("test-empire")
    for name, job in daemon._jobs.items():
        assert job.interval_seconds > 0, f"Job '{name}' has non-positive interval"


def test_health_check_is_highest_priority():
    """health_check should be priority 1 (highest)."""
    daemon = SchedulerDaemon("test-empire")
    assert daemon._jobs["health_check"].priority == 1


def test_jobs_start_enabled():
    """All default jobs should start enabled."""
    daemon = SchedulerDaemon("test-empire")
    for name, job in daemon._jobs.items():
        assert job.enabled, f"Job '{name}' started disabled"


def test_jobconfig_defaults():
    """JobConfig should have sensible defaults."""
    job = JobConfig(name="test", interval_seconds=60, handler=lambda: {})
    assert job.enabled is True
    assert job.priority == 5
    assert job.run_count == 0
    assert job.error_count == 0
    assert job.consecutive_errors == 0
    assert job.job_type == "test"

"""Scheduler management routes."""

from __future__ import annotations

import logging
from flask import Blueprint, render_template, jsonify, request, current_app

logger = logging.getLogger(__name__)
scheduler_bp = Blueprint("scheduler", __name__)


@scheduler_bp.route("/")
def scheduler_overview():
    """Scheduler overview page."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    try:
        from core.scheduler.daemon import SchedulerDaemon
        daemon = SchedulerDaemon(empire_id)
        status = daemon.get_status()
        jobs = daemon.get_next_runs()
        return render_template("scheduler/overview.html", status=status.__dict__, jobs=[
            {"name": j.job_name, "interval": j.interval_seconds, "next_run": j.next_run,
             "last_run": j.last_run, "status": j.status}
            for j in jobs
        ])
    except Exception as e:
        return render_template("scheduler/overview.html", status={}, jobs=[], error=str(e))


@scheduler_bp.route("/jobs")
def list_jobs():
    """List all scheduler jobs."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    from core.scheduler.jobs import JOB_REGISTRY, get_all_jobs
    jobs = get_all_jobs(empire_id)
    return jsonify([
        {"name": j.name, "description": j.description, "interval": j.interval_seconds,
         "priority": j.priority, "enabled": j.enabled}
        for j in jobs
    ])


@scheduler_bp.route("/jobs/<job_name>/run", methods=["POST"])
def force_run_job(job_name: str):
    """Force-run a specific job."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    from core.scheduler.daemon import SchedulerDaemon
    daemon = SchedulerDaemon(empire_id)
    app_daemon = current_app.config.get("_SCHEDULER_DAEMON")
    result = daemon.force_run(job_name)
    return jsonify(result)


@scheduler_bp.route("/jobs/<job_name>/pause", methods=["POST"])
def pause_job(job_name: str):
    """Pause a job."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    from core.scheduler.daemon import SchedulerDaemon
    daemon = SchedulerDaemon(empire_id)
    app_daemon = current_app.config.get("_SCHEDULER_DAEMON")
    success = daemon.pause_job(job_name)
    return jsonify({"success": success})


@scheduler_bp.route("/jobs/<job_name>/resume", methods=["POST"])
def resume_job(job_name: str):
    """Resume a paused job."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    from core.scheduler.daemon import SchedulerDaemon
    daemon = SchedulerDaemon(empire_id)
    success = daemon.resume_job(job_name)
    return jsonify({"success": success})


@scheduler_bp.route("/start", methods=["POST"])
def start_scheduler():
    """Start the scheduler daemon."""
    daemon = current_app.config.get("_SCHEDULER_DAEMON")
    if daemon:
        daemon.start()
        return jsonify({"status": "started"})

    empire_id = current_app.config.get("EMPIRE_ID", "")
    from core.scheduler.daemon import SchedulerDaemon
    daemon = SchedulerDaemon(empire_id, tick_interval=300)
    daemon.start()
    current_app.config["_SCHEDULER_DAEMON"] = daemon
    return jsonify({"status": "started"})


@scheduler_bp.route("/tick", methods=["POST"])
def manual_tick():
    """Execute a single scheduler tick."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    from core.scheduler.daemon import SchedulerDaemon
    daemon = SchedulerDaemon(empire_id)
    executed = daemon.tick()
    app_daemon = current_app.config.get("_SCHEDULER_DAEMON")
    return jsonify({"jobs_executed": executed})

"""Gunicorn configuration for Empire AI."""

import multiprocessing
import os

# Server
bind = f"0.0.0.0:{os.environ.get('PORT', '5000')}"

# Workers — default to 1 because each worker spawns its own SchedulerDaemon
# thread. Running 4 workers meant 4x everything (Flask + SQLAlchemy + scheduler
# + 40-conn DB pool), which OOM-killed workers every ~6 min on Railway. The
# scheduler is embedded per-worker until a separate service can be set up.
# Threads=4 handles I/O-bound LLM concurrency fine for a low-traffic empire.
# Override with WEB_CONCURRENCY if you know what you're doing.
workers = int(os.environ.get("WEB_CONCURRENCY", "1"))
threads = int(os.environ.get("WEB_THREADS", "4"))
timeout = 300  # 5 min — long enough for directives, short enough to catch hangs
worker_class = "gthread"  # Threaded workers — better for I/O-bound LLM calls

# Logging
accesslog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info")

# Graceful restart
graceful_timeout = 30

# Don't preload — the scheduler thread lives inside create_app() and threads
# don't survive os.fork(), so preload would kill the scheduler.
preload_app = False

# Worker lifecycle — recycle after N requests to mitigate any leaks we haven't
# tracked down yet. Lower than default because of known session-leak hot spots.
max_requests = int(os.environ.get("MAX_REQUESTS", "300"))
max_requests_jitter = 50

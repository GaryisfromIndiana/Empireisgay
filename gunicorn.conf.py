"""Gunicorn configuration for Empire AI."""

import os

# Server
bind = f"0.0.0.0:{os.environ.get('PORT', '5000')}"

# Workers — each gets its own scheduler daemon thread (lightweight)
workers = int(os.environ.get("WEB_CONCURRENCY", 6))
threads = 4
timeout = 600

# Logging
accesslog = "-"
loglevel = "info"

# Graceful restart
graceful_timeout = 30

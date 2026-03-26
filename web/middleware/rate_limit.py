"""Rate limiting middleware for Flask API."""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from functools import wraps
from typing import Callable, Optional

from flask import request, jsonify

logger = logging.getLogger(__name__)


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting."""
    requests_per_minute: int = 60
    requests_per_hour: int = 1000
    burst_limit: int = 10
    enabled: bool = True


class RateLimiter:
    """In-memory rate limiter tracking per-client request timestamps."""

    def __init__(self, config: RateLimitConfig | None = None):
        self.config = config or RateLimitConfig()
        self._minute_log: dict[str, list[float]] = defaultdict(list)
        self._hour_log: dict[str, list[float]] = defaultdict(list)

    def _get_client_id(self) -> str:
        api_key = request.headers.get("X-API-Key", "")
        if api_key:
            return f"key:{api_key[:16]}"
        return f"ip:{request.remote_addr or 'unknown'}"

    def _clean_old_entries(self, client_id: str) -> None:
        now = time.time()
        self._minute_log[client_id] = [
            t for t in self._minute_log[client_id] if t > now - 60
        ]
        self._hour_log[client_id] = [
            t for t in self._hour_log[client_id] if t > now - 3600
        ]

    def check_rate_limit(self) -> tuple[bool, dict]:
        if not self.config.enabled:
            return True, {"enabled": False}

        client_id = self._get_client_id()
        self._clean_old_entries(client_id)

        rpm = len(self._minute_log[client_id])
        rph = len(self._hour_log[client_id])

        info = {
            "client_id": client_id[:32],
            "requests_minute": rpm,
            "requests_hour": rph,
            "limit_minute": self.config.requests_per_minute,
            "limit_hour": self.config.requests_per_hour,
        }

        if rpm >= self.config.requests_per_minute:
            return False, {**info, "blocked": True, "reason": "minute_limit", "retry_after": 60}

        if rph >= self.config.requests_per_hour:
            return False, {**info, "blocked": True, "reason": "hour_limit", "retry_after": 3600}

        now = time.time()
        self._minute_log[client_id].append(now)
        self._hour_log[client_id].append(now)

        info["allowed"] = True
        info["remaining_minute"] = self.config.requests_per_minute - rpm - 1
        info["remaining_hour"] = self.config.requests_per_hour - rph - 1
        return True, info


_rate_limiter: RateLimiter | None = None


def get_rate_limiter() -> RateLimiter:
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter()
    return _rate_limiter


def rate_limit(
    requests_per_minute: int | None = None,
    requests_per_hour: int | None = None,
):
    """Decorator to rate-limit a Flask route.

    Usage:
        @app.route("/api/expensive")
        @rate_limit(requests_per_minute=10)
        def expensive_endpoint():
            ...
    """
    def decorator(f: Callable):
        # Use the global singleton — override its config temporarily for the check
        @wraps(f)
        def decorated_function(*args, **kwargs):
            limiter = get_rate_limiter()

            # Temporarily adjust limits if custom values provided
            orig_rpm = limiter.config.requests_per_minute
            orig_rph = limiter.config.requests_per_hour
            if requests_per_minute:
                limiter.config.requests_per_minute = requests_per_minute
            if requests_per_hour:
                limiter.config.requests_per_hour = requests_per_hour

            allowed, info = limiter.check_rate_limit()

            # Restore original config
            limiter.config.requests_per_minute = orig_rpm
            limiter.config.requests_per_hour = orig_rph

            if not allowed:
                retry_after = info.get("retry_after", 60)
                response = jsonify({
                    "error": "Rate limit exceeded",
                    "reason": info.get("reason", "unknown"),
                    "retry_after_seconds": retry_after,
                })
                response.status_code = 429
                response.headers["Retry-After"] = str(retry_after)
                return response

            result = f(*args, **kwargs)
            if hasattr(result, "headers"):
                result.headers["X-RateLimit-Remaining-Minute"] = str(
                    info.get("remaining_minute", 0)
                )
                result.headers["X-RateLimit-Remaining-Hour"] = str(
                    info.get("remaining_hour", 0)
                )
            return result

        return decorated_function
    return decorator

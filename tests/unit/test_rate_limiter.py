"""Unit tests for LLM rate limiter enforcement."""

from __future__ import annotations

import time

from llm.base import RateLimiter


def test_rate_limiter_allows_requests_under_limit() -> None:
    limiter = RateLimiter(requests_per_minute=10, tokens_per_minute=10000)
    
    for _ in range(9):
        assert limiter.can_proceed(estimated_tokens=500)
        limiter.record_request(tokens_used=500)
    
    assert limiter.can_proceed(estimated_tokens=500)


def test_rate_limiter_blocks_requests_at_rpm_limit() -> None:
    limiter = RateLimiter(requests_per_minute=5, tokens_per_minute=100000)
    
    for _ in range(5):
        limiter.record_request(tokens_used=100)
    
    assert not limiter.can_proceed(estimated_tokens=100)


def test_rate_limiter_blocks_requests_at_tpm_limit() -> None:
    limiter = RateLimiter(requests_per_minute=100, tokens_per_minute=5000)
    
    limiter.record_request(tokens_used=4800)
    assert not limiter.can_proceed(estimated_tokens=300)


def test_rate_limiter_allows_after_time_window_expires() -> None:
    limiter = RateLimiter(requests_per_minute=2, tokens_per_minute=1000)
    
    limiter.record_request(tokens_used=500)
    limiter.record_request(tokens_used=500)
    assert not limiter.can_proceed(estimated_tokens=100)
    
    # Manually expire old requests by manipulating timestamps
    limiter._request_timestamps = [time.time() - 61.0, time.time() - 61.0]
    limiter._token_counts = [(time.time() - 61.0, 500), (time.time() - 61.0, 500)]
    
    assert limiter.can_proceed(estimated_tokens=100)


def test_rate_limiter_calculates_wait_time() -> None:
    limiter = RateLimiter(requests_per_minute=10, tokens_per_minute=10000)
    
    for _ in range(10):
        limiter.record_request(tokens_used=100)
    
    wait = limiter.wait_time()
    assert 0 < wait <= 60.0

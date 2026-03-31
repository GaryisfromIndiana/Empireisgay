"""Pytest safety defaults for fast, deterministic unit tests."""

from __future__ import annotations

import signal
from collections.abc import Generator

import pytest


DEFAULT_TEST_TIMEOUT_SECONDS = 8


def _handle_timeout(signum, frame) -> None:  # type: ignore[no-untyped-def]
    raise TimeoutError(
        f"Test exceeded {DEFAULT_TEST_TIMEOUT_SECONDS}s timeout. "
        "Mark with @pytest.mark.no_timeout if long runtime is expected."
    )


@pytest.fixture(autouse=True)
def per_test_timeout(request: pytest.FixtureRequest) -> Generator[None, None, None]:
    """Fail fast on hanging tests unless explicitly opted out."""
    if request.node.get_closest_marker("no_timeout"):
        yield
        return

    previous_handler = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, _handle_timeout)
    signal.alarm(DEFAULT_TEST_TIMEOUT_SECONDS)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous_handler)

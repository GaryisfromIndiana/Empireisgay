"""Unit tests for DB engine session initialization behavior."""

from __future__ import annotations

import queue
import threading

import db.engine as eng


def _reset_engine_singletons() -> None:
    """Reset global engine/session singletons for deterministic tests."""
    if eng._scoped_session is not None:
        eng._scoped_session.remove()
        eng._scoped_session = None

    if eng._engine is not None:
        eng._engine.dispose()

    eng._engine = None
    eng._session_factory = None


def test_first_call_get_session_does_not_deadlock() -> None:
    _reset_engine_singletons()
    error_queue: queue.Queue[Exception] = queue.Queue()

    def _target() -> None:
        try:
            session = eng.get_session()
            session.close()
        except Exception as exc:  # pragma: no cover - assertion handles this
            error_queue.put(exc)

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join(timeout=2.0)

    assert not thread.is_alive(), "get_session deadlocked on first call"
    assert error_queue.empty(), f"unexpected get_session error: {list(error_queue.queue)}"


def test_session_stats_track_open_and_close() -> None:
    baseline = eng.get_session_stats()
    session = eng.get_session()
    mid = eng.get_session_stats()
    session.close()
    end = eng.get_session_stats()

    assert mid["opened_total"] == baseline["opened_total"] + 1
    assert end["closed_total"] >= baseline["closed_total"] + 1
    assert end["active"] <= mid["active"]

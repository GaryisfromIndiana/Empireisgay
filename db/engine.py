"""SQLAlchemy engine setup, session management, and connection pooling."""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, scoped_session, sessionmaker
from sqlalchemy.pool import NullPool, StaticPool

logger = logging.getLogger(__name__)

_engine: Engine | None = None
_session_factory: sessionmaker | None = None
_scoped_session: scoped_session | None = None
_lock = threading.Lock()
_stats_lock = threading.Lock()
_sqlite_write_lock = threading.RLock()
_session_stats = {"opened_total": 0, "closed_total": 0, "active": 0}


def _record_session_open() -> None:
    with _stats_lock:
        _session_stats["opened_total"] += 1
        _session_stats["active"] += 1


def _record_session_close() -> None:
    with _stats_lock:
        _session_stats["closed_total"] += 1
        _session_stats["active"] = max(0, _session_stats["active"] - 1)


class TrackedSession(Session):
    """Session subclass that tracks open/close and auto-closes leaked sessions.

    Safety net: if a session is not closed within MAX_SESSION_AGE_SECONDS,
    it gets force-closed on the next operation to prevent pool exhaustion.
    """

    MAX_SESSION_AGE_SECONDS = 60  # Sessions older than this are leaked

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._close_recorded = False
        self._created_at = time.monotonic()
        self._sqlite_write_lock_held = False
        _record_session_open()

    def _is_sqlite_bound(self) -> bool:
        bind = self.get_bind()
        return bind is not None and str(bind.url).startswith("sqlite")

    def _acquire_sqlite_write_lock(self) -> None:
        if self._is_sqlite_bound() and not self._sqlite_write_lock_held:
            _sqlite_write_lock.acquire()
            self._sqlite_write_lock_held = True

    def _release_sqlite_write_lock(self) -> None:
        if self._sqlite_write_lock_held:
            self._sqlite_write_lock_held = False
            _sqlite_write_lock.release()

    def close(self) -> None:
        self._release_sqlite_write_lock()
        if not self._close_recorded:
            _record_session_close()
            self._close_recorded = True
        super().close()

    def _check_age(self) -> None:
        """Force-close if session has been open too long (leaked)."""
        age = time.monotonic() - self._created_at
        if age > self.MAX_SESSION_AGE_SECONDS and not self._close_recorded:
            logger.warning(
                "Force-closing leaked session (age=%.0fs). "
                "This indicates a missing session.close() call.",
                age,
            )
            self.close()

    def execute(self, *args, **kwargs):
        self._check_age()
        return super().execute(*args, **kwargs)

    def flush(self, objects=None) -> None:
        self._acquire_sqlite_write_lock()
        try:
            super().flush(objects=objects)
        except Exception:
            self._release_sqlite_write_lock()
            raise

    def commit(self) -> None:
        self._acquire_sqlite_write_lock()
        try:
            super().commit()
        finally:
            self._release_sqlite_write_lock()

    def rollback(self) -> None:
        try:
            super().rollback()
        finally:
            self._release_sqlite_write_lock()

    def __del__(self):
        """Last resort: close on garbage collection if still open."""
        if not self._close_recorded:
            try:
                _record_session_close()
                self._close_recorded = True
                super().close()
            except Exception:
                pass


def get_session_stats() -> dict[str, int]:
    """Get debug stats for SQLAlchemy session lifecycle."""
    with _stats_lock:
        return dict(_session_stats)


def _configure_sqlite(dbapi_conn: Any, connection_record: Any) -> None:
    """Configure SQLite pragmas for performance and reliability."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA cache_size=-64000")  # 64MB cache
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA temp_store=MEMORY")
    cursor.execute("PRAGMA mmap_size=268435456")  # 256MB mmap
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()


def get_engine(db_url: str | None = None, echo: bool = False) -> Engine:
    """Get or create the SQLAlchemy engine singleton.

    Args:
        db_url: Database URL. If None, uses settings.
        echo: Whether to echo SQL statements.

    Returns:
        SQLAlchemy Engine instance.
    """
    global _engine

    if _engine is not None:
        return _engine

    with _lock:
        if _engine is not None:
            return _engine

        if db_url is None:
            from config.settings import get_settings
            settings = get_settings()
            db_url = settings.db_url
            echo = settings.db_echo

        is_sqlite = db_url.startswith("sqlite")

        if is_sqlite:
            # Ensure directory exists for file-based SQLite
            if ":///" in db_url and ":memory:" not in db_url:
                db_path = db_url.split("///", 1)[1]
                Path(db_path).parent.mkdir(parents=True, exist_ok=True)

            engine = create_engine(
                db_url,
                echo=echo,
                connect_args={"check_same_thread": False},
                poolclass=StaticPool if ":memory:" in db_url else NullPool,
            )
            event.listen(engine, "connect", _configure_sqlite)
        else:
            engine = create_engine(
                db_url,
                echo=echo,
                # Single gunicorn worker × 4 gthread threads → 4 concurrent ops.
                # Previous 15+25=40 conns per worker contributed to memory
                # pressure on Railway and easily exceeded PG plan limits.
                pool_size=int(os.environ.get("DB_POOL_SIZE", "5")),
                max_overflow=int(os.environ.get("DB_MAX_OVERFLOW", "10")),
                pool_pre_ping=True,
                pool_recycle=300,
                pool_timeout=20,
                query_cache_size=500,
            )

        _engine = engine
        logger.info("Database engine created: %s", db_url.split("?")[0])
        return engine


def get_session_factory(engine: Engine | None = None) -> sessionmaker:
    """Get or create the session factory.

    Args:
        engine: SQLAlchemy engine. If None, uses default.

    Returns:
        Session factory.
    """
    global _session_factory

    if _session_factory is not None:
        return _session_factory

    if engine is None:
        # Resolve engine before acquiring _lock to avoid lock re-entry deadlocks.
        engine = get_engine()

    with _lock:
        if _session_factory is not None:
            return _session_factory

        _session_factory = sessionmaker(
            bind=engine,
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
            class_=TrackedSession,
        )
        return _session_factory


def get_scoped_session(engine: Engine | None = None) -> scoped_session:
    """Get a thread-local scoped session.

    Args:
        engine: SQLAlchemy engine.

    Returns:
        Scoped session instance.
    """
    global _scoped_session

    if _scoped_session is not None:
        return _scoped_session

    factory = get_session_factory(engine)

    with _lock:
        if _scoped_session is not None:
            return _scoped_session

        _scoped_session = scoped_session(factory)
        return _scoped_session


def get_session(engine: Engine | None = None) -> Session:
    """Get a new database session.

    Args:
        engine: SQLAlchemy engine.

    Returns:
        New Session instance.

    Note:
        Callers MUST close the session when done (use try/finally or session_scope).
        If a session is not closed within 60 seconds, TrackedSession will
        force-close it as a safety net, but this indicates a bug.
    """
    from sqlalchemy.exc import TimeoutError as SATimeoutError

    factory = get_session_factory(engine)
    try:
        return factory()
    except SATimeoutError:
        # Pool exhausted — force-close any leaked sessions and retry once
        logger.warning("Connection pool exhausted — forcing cleanup of leaked sessions")
        _force_cleanup_leaked_sessions()
        try:
            return factory()
        except SATimeoutError:
            logger.error("Connection pool still exhausted after cleanup")
            raise


def _force_cleanup_leaked_sessions() -> None:
    """Emergency cleanup: dispose all pool connections and reset.

    This is a last resort when the pool is exhausted due to leaked sessions.
    """
    global _engine
    if _engine is not None:
        try:
            _engine.pool.dispose()
            logger.warning("Disposed connection pool to recover from exhaustion")
        except Exception as e:
            logger.error("Pool dispose failed: %s", e)


@contextmanager
def session_scope(engine: Engine | None = None) -> Generator[Session, None, None]:
    """Provide a transactional scope around a series of operations.

    Usage:
        with session_scope() as session:
            session.add(obj)
            # auto-commits on success, rollbacks on exception

    Args:
        engine: SQLAlchemy engine.

    Yields:
        Session instance.
    """
    session = get_session(engine)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def read_session(engine: Engine | None = None) -> Generator[Session, None, None]:
    """Provide a read-only session scope.

    Args:
        engine: SQLAlchemy engine.

    Yields:
        Session instance (read-only).
    """
    session = get_session(engine)
    try:
        yield session
    finally:
        session.close()


@contextmanager
def repo_scope(repo_class):
    """Context manager that creates a repository with its own session and auto-closes.

    Usage:
        with repo_scope(DirectiveRepository) as repo:
            repo.get_active(empire_id)
    """
    session = get_session()
    try:
        yield repo_class(session)
    finally:
        session.close()


def init_db(engine: Engine | None = None) -> None:
    """Initialize the database by creating all tables and seed the default empire.

    Args:
        engine: SQLAlchemy engine. If None, uses default.
    """
    from db.models import Base

    if engine is None:
        engine = get_engine()

    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created successfully")

    # Run lightweight migrations for constraint updates
    _run_constraint_migrations(engine)

    # Ensure the default empire record exists (required for FK constraints on budget_logs etc.)
    _ensure_default_empire(engine)


def _run_constraint_migrations(engine: Engine) -> None:
    """Update check constraints that may have changed since last deploy."""
    try:
        is_postgres = "postgresql" in str(engine.url)
        if not is_postgres:
            return  # SQLite recreates constraints on create_all

        with engine.connect() as conn:
            # Update directive source constraint to allow god_panel and scheduler
            try:
                conn.execute(text("ALTER TABLE directives DROP CONSTRAINT IF EXISTS ck_directive_source"))
                conn.execute(text(
                    "ALTER TABLE directives ADD CONSTRAINT ck_directive_source "
                    "CHECK (source IN ('human', 'evolution', 'autonomous', 'god_panel', 'scheduler'))"
                ))
                conn.commit()
                logger.info("Updated ck_directive_source constraint")
            except Exception as e:
                logger.debug("Constraint migration skipped: %s", e)
    except Exception as e:
        logger.debug("Constraint migrations skipped: %s", e)


def _ensure_default_empire(engine: Engine) -> None:
    """Create the default empire row if it doesn't exist."""
    try:
        from sqlalchemy.orm import Session as SASession

        from config.settings import get_settings
        from db.models import Empire

        settings = get_settings()
        empire_id = settings.empire_id
        if not empire_id:
            return

        with SASession(engine) as session:
            existing = session.get(Empire, empire_id)
            if existing:
                return

            empire = Empire(
                id=empire_id,
                name=settings.empire_name,
                description=settings.empire_description,
                domain="ai_research",
                status="active",
            )
            session.add(empire)
            session.commit()
            logger.info("Created default empire: %s (%s)", empire_id, settings.empire_name)

    except Exception as e:
        logger.warning("Could not seed default empire: %s", e)


def drop_db(engine: Engine | None = None) -> None:
    """Drop all database tables. USE WITH CAUTION.

    Args:
        engine: SQLAlchemy engine.
    """
    from db.models import Base

    if engine is None:
        engine = get_engine()

    Base.metadata.drop_all(bind=engine)
    logger.warning("All database tables dropped")


def reset_db(engine: Engine | None = None) -> None:
    """Drop and recreate all tables. USE WITH CAUTION.

    Args:
        engine: SQLAlchemy engine.
    """
    drop_db(engine)
    init_db(engine)
    logger.warning("Database reset complete")


def get_table_names(engine: Engine | None = None) -> list[str]:
    """Get list of all table names in the database.

    Args:
        engine: SQLAlchemy engine.

    Returns:
        List of table names.
    """
    if engine is None:
        engine = get_engine()
    inspector = inspect(engine)
    return inspector.get_table_names()


def check_connection(engine: Engine | None = None) -> bool:
    """Check if the database connection is healthy.

    Args:
        engine: SQLAlchemy engine.

    Returns:
        True if connection is healthy.
    """
    if engine is None:
        engine = get_engine()
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.error("Database connection check failed: %s", e)
        return False


def get_db_stats(engine: Engine | None = None) -> dict:
    """Get database statistics.

    Args:
        engine: SQLAlchemy engine.

    Returns:
        Dictionary with database stats.
    """
    if engine is None:
        engine = get_engine()

    stats = {
        "url": str(engine.url).split("?")[0],
        "pool_size": engine.pool.size() if hasattr(engine.pool, "size") else "N/A",
        "checked_in": engine.pool.checkedin() if hasattr(engine.pool, "checkedin") else "N/A",
        "checked_out": engine.pool.checkedout() if hasattr(engine.pool, "checkedout") else "N/A",
        "tables": get_table_names(engine),
    }

    # Get row counts for each table
    try:
        with engine.connect() as conn:
            for table in stats["tables"]:
                if not table.isidentifier():
                    continue
                result = conn.execute(text(f'SELECT COUNT(*) FROM "{table}"'))
                stats[f"rows_{table}"] = result.scalar()
    except Exception as e:
        logger.warning("Could not get row counts: %s", e)

    return stats


class DatabaseManager:
    """High-level database management interface.

    Provides a convenient API for database operations including
    initialization, health checks, and statistics.
    """

    def __init__(self, db_url: str | None = None, echo: bool = False):
        self.engine = get_engine(db_url, echo)
        self._session_factory = get_session_factory(self.engine)

    def init(self) -> None:
        """Initialize database tables."""
        init_db(self.engine)

    def reset(self) -> None:
        """Reset database (drop and recreate all tables)."""
        reset_db(self.engine)

    def check_health(self) -> bool:
        """Check database connection health."""
        return check_connection(self.engine)

    def get_stats(self) -> dict:
        """Get database statistics."""
        return get_db_stats(self.engine)

    def get_session(self) -> Session:
        """Get a new session."""
        return self._session_factory()

    @contextmanager
    def session(self) -> Generator[Session, None, None]:
        """Get a transactional session scope."""
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @contextmanager
    def read_session(self) -> Generator[Session, None, None]:
        """Get a read-only session."""
        session = self._session_factory()
        try:
            yield session
        finally:
            session.close()

    def execute_raw(self, sql: str, params: dict | None = None) -> Any:
        """Execute raw SQL. Use sparingly.

        Args:
            sql: SQL statement.
            params: Query parameters.

        Returns:
            Query result.
        """
        with self.engine.connect() as conn:
            result = conn.execute(text(sql), params or {})
            conn.commit()
            return result

    def table_exists(self, table_name: str) -> bool:
        """Check if a table exists.

        Args:
            table_name: Name of the table.

        Returns:
            True if table exists.
        """
        return table_name in get_table_names(self.engine)

    def get_table_row_count(self, table_name: str) -> int:
        """Get row count for a table.

        Args:
            table_name: Name of the table.

        Returns:
            Number of rows.
        """
        with self.engine.connect() as conn:
            result = conn.execute(text(f'SELECT COUNT(*) FROM "{table_name}"'))
            return result.scalar() or 0

    def vacuum(self) -> None:
        """Run VACUUM on SQLite database to reclaim space."""
        with self.engine.connect() as conn:
            conn.execute(text("VACUUM"))
            conn.commit()
        logger.info("Database vacuumed")

    def get_db_size_bytes(self) -> int | None:
        """Get database file size in bytes (SQLite only).

        Returns:
            File size in bytes, or None if not applicable.
        """
        url = str(self.engine.url)
        if "sqlite" not in url or ":memory:" in url:
            return None
        db_path = url.split("///", 1)[1] if "///" in url else None
        if db_path:
            path = Path(db_path)
            if path.exists():
                return path.stat().st_size
        return None

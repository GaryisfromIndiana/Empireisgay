"""Database migration runner with version tracking.

Handles schema creation, evolution, and version management for the Empire database.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import text, inspect
from sqlalchemy.engine import Engine

from db.engine import get_engine, session_scope
from db.models import Base

logger = logging.getLogger(__name__)


class MigrationVersion:
    """Represents a single migration version."""

    def __init__(
        self,
        version: int,
        name: str,
        description: str = "",
        sql_up: str = "",
        sql_down: str = "",
        applied_at: Optional[datetime] = None,
    ):
        self.version = version
        self.name = name
        self.description = description
        self.sql_up = sql_up
        self.sql_down = sql_down
        self.applied_at = applied_at

    @property
    def checksum(self) -> str:
        return hashlib.md5(self.sql_up.encode()).hexdigest()[:12]

    def __repr__(self) -> str:
        status = "applied" if self.applied_at else "pending"
        return f"<Migration(v{self.version}: {self.name} [{status}])>"


class MigrationRunner:
    """Manages database schema migrations with version tracking.

    Creates a _schema_versions table to track which migrations have been applied.
    Supports forward migrations and rollbacks.
    """

    VERSION_TABLE = "_schema_versions"

    def __init__(self, engine: Engine | None = None):
        self.engine = engine or get_engine()
        self._migrations: list[MigrationVersion] = []
        self._ensure_version_table()
        self._register_builtin_migrations()

    def _ensure_version_table(self) -> None:
        """Create the version tracking table if it doesn't exist."""
        with self.engine.connect() as conn:
            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS {self.VERSION_TABLE} (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    checksum TEXT DEFAULT '',
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    rolled_back_at TIMESTAMP,
                    is_current BOOLEAN DEFAULT TRUE
                )
            """))
            conn.commit()

    def _register_builtin_migrations(self) -> None:
        """Register the built-in migration chain."""
        self.register(MigrationVersion(
            version=1,
            name="initial_schema",
            description="Create all initial tables via SQLAlchemy models",
            sql_up="-- Handled by SQLAlchemy Base.metadata.create_all()",
            sql_down="-- Handled by SQLAlchemy Base.metadata.drop_all()",
        ))

        self.register(MigrationVersion(
            version=2,
            name="add_performance_indexes",
            description="Add additional performance indexes for common queries",
            sql_up="""
                CREATE INDEX IF NOT EXISTS ix_tasks_cost ON tasks(cost_usd);
                CREATE INDEX IF NOT EXISTS ix_tasks_quality ON tasks(quality_score);
                CREATE INDEX IF NOT EXISTS ix_budget_logs_cost ON budget_logs(cost_usd);
                CREATE INDEX IF NOT EXISTS ix_memory_created ON memory_entries(created_at);
                CREATE INDEX IF NOT EXISTS ix_knowledge_created ON knowledge_entities(created_at);
            """,
            sql_down="""
                DROP INDEX IF EXISTS ix_tasks_cost;
                DROP INDEX IF EXISTS ix_tasks_quality;
                DROP INDEX IF EXISTS ix_budget_logs_cost;
                DROP INDEX IF EXISTS ix_memory_created;
                DROP INDEX IF EXISTS ix_knowledge_created;
            """,
        ))

        # FTS is SQLite-only; Postgres uses built-in full-text search
        is_sqlite = str(self.engine.url).startswith("sqlite")
        if is_sqlite:
            self.register(MigrationVersion(
                version=3,
                name="add_full_text_search",
                description="Add FTS5 virtual tables (SQLite only)",
                sql_up="""
                    CREATE VIRTUAL TABLE IF NOT EXISTS fts_knowledge_entities
                        USING fts5(name, description, content=knowledge_entities, content_rowid=rowid);
                    CREATE VIRTUAL TABLE IF NOT EXISTS fts_memory_entries
                        USING fts5(title, content, summary, content=memory_entries, content_rowid=rowid);
                    CREATE VIRTUAL TABLE IF NOT EXISTS fts_tasks
                        USING fts5(title, description, content=tasks, content_rowid=rowid);
                """,
                sql_down="""
                    DROP TABLE IF EXISTS fts_knowledge_entities;
                    DROP TABLE IF EXISTS fts_memory_entries;
                    DROP TABLE IF EXISTS fts_tasks;
                """,
            ))
        else:
            self.register(MigrationVersion(
                version=3,
                name="add_full_text_search",
                description="Skip — Postgres uses built-in ILIKE",
                sql_up="SELECT 1",
                sql_down="SELECT 1",
            ))

        self.register(MigrationVersion(
            version=4,
            name="add_audit_log",
            description="Add audit log table for tracking system changes",
            sql_up="""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id TEXT PRIMARY KEY,
                    empire_id TEXT NOT NULL,
                    actor_type TEXT NOT NULL DEFAULT 'system',
                    actor_id TEXT,
                    action TEXT NOT NULL,
                    resource_type TEXT NOT NULL,
                    resource_id TEXT,
                    details_json TEXT DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS ix_audit_empire ON audit_log(empire_id);
                CREATE INDEX IF NOT EXISTS ix_audit_action ON audit_log(action);
                CREATE INDEX IF NOT EXISTS ix_audit_resource ON audit_log(resource_type, resource_id);
                CREATE INDEX IF NOT EXISTS ix_audit_created ON audit_log(created_at);
            """,
            sql_down="DROP TABLE IF EXISTS audit_log;",
        ))

        self.register(MigrationVersion(
            version=5,
            name="add_task_dependencies",
            description="Add task dependency tracking table",
            sql_up="""
                CREATE TABLE IF NOT EXISTS task_dependencies (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    depends_on_task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    dependency_type TEXT DEFAULT 'hard',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(task_id, depends_on_task_id)
                );
                CREATE INDEX IF NOT EXISTS ix_task_deps_task ON task_dependencies(task_id);
                CREATE INDEX IF NOT EXISTS ix_task_deps_dep ON task_dependencies(depends_on_task_id);
            """,
            sql_down="DROP TABLE IF EXISTS task_dependencies;",
        ))

        self.register(MigrationVersion(
            version=6,
            name="add_performance_indexes_v2",
            description="Additional performance indexes for hot query paths",
            sql_up="""
                CREATE INDEX IF NOT EXISTS ix_directives_completed_at ON directives(completed_at);
                CREATE INDEX IF NOT EXISTS ix_tasks_quality_score ON tasks(quality_score);
                CREATE INDEX IF NOT EXISTS ix_memory_effective_importance ON memory_entries(effective_importance);
                CREATE INDEX IF NOT EXISTS ix_knowledge_entity_type ON knowledge_entities(entity_type, empire_id);
                CREATE INDEX IF NOT EXISTS ix_budget_logs_created_at ON budget_logs(created_at);
                CREATE INDEX IF NOT EXISTS ix_lieutenants_last_active ON lieutenants(last_active_at);
            """,
            sql_down="""
                DROP INDEX IF EXISTS ix_directives_completed_at;
                DROP INDEX IF EXISTS ix_tasks_quality_score;
                DROP INDEX IF EXISTS ix_memory_effective_importance;
                DROP INDEX IF EXISTS ix_knowledge_entity_type;
                DROP INDEX IF EXISTS ix_budget_logs_created_at;
                DROP INDEX IF EXISTS ix_lieutenants_last_active;
            """,
        ))

    def register(self, migration: MigrationVersion) -> None:
        """Register a migration version.

        Args:
            migration: The migration to register.
        """
        existing = [m for m in self._migrations if m.version == migration.version]
        if existing:
            logger.warning("Migration v%d already registered, skipping", migration.version)
            return
        self._migrations.append(migration)
        self._migrations.sort(key=lambda m: m.version)

    def get_current_version(self) -> int:
        """Get the current schema version.

        Returns:
            Current version number, or 0 if no migrations applied.
        """
        with self.engine.connect() as conn:
            result = conn.execute(text(
                f"SELECT MAX(version) FROM {self.VERSION_TABLE} WHERE is_current = TRUE"
            ))
            row = result.fetchone()
            return row[0] if row and row[0] is not None else 0

    def get_applied_versions(self) -> list[int]:
        """Get list of applied migration versions.

        Returns:
            List of applied version numbers.
        """
        with self.engine.connect() as conn:
            result = conn.execute(text(
                f"SELECT version FROM {self.VERSION_TABLE} WHERE is_current = TRUE ORDER BY version"
            ))
            return [row[0] for row in result.fetchall()]

    def get_pending_migrations(self) -> list[MigrationVersion]:
        """Get migrations that haven't been applied yet.

        Returns:
            List of pending migrations.
        """
        applied = set(self.get_applied_versions())
        return [m for m in self._migrations if m.version not in applied]

    def migrate(self, target_version: int | None = None) -> list[MigrationVersion]:
        """Run all pending migrations up to the target version.

        Args:
            target_version: Target version. If None, runs all pending migrations.

        Returns:
            List of applied migrations.
        """
        pending = self.get_pending_migrations()
        if target_version is not None:
            pending = [m for m in pending if m.version <= target_version]

        if not pending:
            logger.info("No pending migrations")
            return []

        applied = []
        for migration in pending:
            try:
                self._apply_migration(migration)
                applied.append(migration)
                logger.info("Applied migration v%d: %s", migration.version, migration.name)
            except Exception as e:
                logger.error("Failed to apply migration v%d: %s", migration.version, e)
                raise

        return applied

    def _apply_migration(self, migration: MigrationVersion) -> None:
        """Apply a single migration.

        Args:
            migration: The migration to apply.
        """
        with self.engine.connect() as conn:
            # Special handling for v1 (SQLAlchemy create_all)
            if migration.version == 1:
                Base.metadata.create_all(bind=self.engine)
            else:
                # Execute SQL statements
                for statement in migration.sql_up.strip().split(";"):
                    statement = statement.strip()
                    # Skip empty statements and SQL comments
                    if statement and not statement.startswith("--"):
                        conn.execute(text(statement))

            # Record the migration
            conn.execute(text(f"""
                INSERT INTO {self.VERSION_TABLE} (version, name, description, checksum, is_current)
                VALUES (:version, :name, :description, :checksum, TRUE)
            """), {
                "version": migration.version,
                "name": migration.name,
                "description": migration.description,
                "checksum": migration.checksum,
            })
            conn.commit()

        migration.applied_at = datetime.now(timezone.utc)

    def rollback(self, target_version: int = 0) -> list[MigrationVersion]:
        """Rollback migrations down to target version.

        Args:
            target_version: Target version to rollback to (exclusive).

        Returns:
            List of rolled-back migrations.
        """
        applied = self.get_applied_versions()
        to_rollback = [
            m for m in reversed(self._migrations)
            if m.version in applied and m.version > target_version
        ]

        rolled_back = []
        for migration in to_rollback:
            try:
                self._rollback_migration(migration)
                rolled_back.append(migration)
                logger.info("Rolled back migration v%d: %s", migration.version, migration.name)
            except Exception as e:
                logger.error("Failed to rollback migration v%d: %s", migration.version, e)
                raise

        return rolled_back

    def _rollback_migration(self, migration: MigrationVersion) -> None:
        """Rollback a single migration.

        Args:
            migration: The migration to rollback.
        """
        with self.engine.connect() as conn:
            if migration.version == 1:
                Base.metadata.drop_all(bind=self.engine)
            else:
                for statement in migration.sql_down.strip().split(";"):
                    statement = statement.strip()
                    if statement:
                        conn.execute(text(statement))

            conn.execute(text(f"""
                UPDATE {self.VERSION_TABLE}
                SET is_current = FALSE, rolled_back_at = CURRENT_TIMESTAMP
                WHERE version = :version
            """), {"version": migration.version})
            conn.commit()

    def get_status(self) -> dict:
        """Get migration status summary.

        Returns:
            Dict with current version, applied count, pending count, details.
        """
        current = self.get_current_version()
        applied = self.get_applied_versions()
        pending = self.get_pending_migrations()

        return {
            "current_version": current,
            "latest_available": self._migrations[-1].version if self._migrations else 0,
            "applied_count": len(applied),
            "pending_count": len(pending),
            "applied_versions": applied,
            "pending_versions": [m.version for m in pending],
            "migrations": [
                {
                    "version": m.version,
                    "name": m.name,
                    "description": m.description,
                    "status": "applied" if m.version in applied else "pending",
                }
                for m in self._migrations
            ],
        }

    def verify_integrity(self) -> dict:
        """Verify schema integrity by checking all expected tables exist.

        Returns:
            Dict with verification results.
        """
        inspector = inspect(self.engine)
        existing_tables = set(inspector.get_table_names())

        expected_tables = set(Base.metadata.tables.keys())
        missing = expected_tables - existing_tables
        extra = existing_tables - expected_tables - {self.VERSION_TABLE}

        return {
            "valid": len(missing) == 0,
            "expected_tables": sorted(expected_tables),
            "existing_tables": sorted(existing_tables),
            "missing_tables": sorted(missing),
            "extra_tables": sorted(extra),
        }


def run(target_version: int | None = None) -> None:
    """Run migrations (entry point for empire-migrate command).

    Args:
        target_version: Optional target version.
    """
    runner = MigrationRunner()

    status = runner.get_status()
    logger.info("Current schema version: %d", status["current_version"])
    logger.info("Pending migrations: %d", status["pending_count"])

    if status["pending_count"] > 0:
        applied = runner.migrate(target_version)
        logger.info("Applied %d migration(s)", len(applied))
        for m in applied:
            logger.info("  v%d: %s", m.version, m.name)
    else:
        logger.info("Schema is up to date")

    integrity = runner.verify_integrity()
    if not integrity["valid"]:
        logger.warning("Schema integrity check failed! Missing tables: %s", integrity["missing_tables"])
    else:
        logger.info("Schema integrity verified: %d tables", len(integrity["expected_tables"]))


def main() -> None:
    """CLI entry point for migrations."""
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if len(sys.argv) > 1 and sys.argv[1] == "rollback":
        target = int(sys.argv[2]) if len(sys.argv) > 2 else 0
        runner = MigrationRunner()
        rolled_back = runner.rollback(target)
        print(f"Rolled back {len(rolled_back)} migration(s)")
    elif len(sys.argv) > 1 and sys.argv[1] == "status":
        runner = MigrationRunner()
        status = runner.get_status()
        print(json.dumps(status, indent=2))
    else:
        run()


if __name__ == "__main__":
    main()

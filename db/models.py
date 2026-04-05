"""SQLAlchemy ORM models for the Empire system.

All database tables are defined here using SQLAlchemy 2.0 Mapped Column style.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    JSON,
    UniqueConstraint,
    CheckConstraint,
    func,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _generate_id() -> str:
    return uuid.uuid4().hex[:16]


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


# ═══════════════════════════════════════════════════════════════════════════
# Empire
# ═══════════════════════════════════════════════════════════════════════════

class Empire(Base):
    """An autonomous empire — the top-level organizational unit."""

    __tablename__ = "empires"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_generate_id)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    domain: Mapped[str] = mapped_column(String(64), default="general")
    status: Mapped[str] = mapped_column(String(32), default="active")  # active, paused, archived
    config_json: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)

    total_tasks_completed: Mapped[int] = mapped_column(Integer, default=0)
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    total_knowledge_entries: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    # Relationships
    lieutenants: Mapped[list[Lieutenant]] = relationship("Lieutenant", back_populates="empire", cascade="all, delete-orphan")
    directives: Mapped[list[Directive]] = relationship("Directive", back_populates="empire", cascade="all, delete-orphan")
    war_rooms: Mapped[list[WarRoom]] = relationship("WarRoom", back_populates="empire", cascade="all, delete-orphan")
    knowledge_entities: Mapped[list[KnowledgeEntity]] = relationship("KnowledgeEntity", back_populates="empire", cascade="all, delete-orphan")
    memory_entries: Mapped[list[MemoryEntry]] = relationship("MemoryEntry", back_populates="empire", cascade="all, delete-orphan")
    evolution_proposals: Mapped[list[EvolutionProposal]] = relationship("EvolutionProposal", back_populates="empire", cascade="all, delete-orphan")
    evolution_cycles: Mapped[list[EvolutionCycle]] = relationship("EvolutionCycle", back_populates="empire", cascade="all, delete-orphan")
    budget_logs: Mapped[list[BudgetLog]] = relationship("BudgetLog", back_populates="empire", cascade="all, delete-orphan")
    health_checks: Mapped[list[HealthCheck]] = relationship("HealthCheck", back_populates="empire", cascade="all, delete-orphan")
    scheduler_jobs: Mapped[list[SchedulerJob]] = relationship("SchedulerJob", back_populates="empire", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_empires_status", "status"),
        Index("ix_empires_domain", "domain"),
        CheckConstraint("status IN ('active', 'paused', 'archived')", name="ck_empire_status"),
    )

    def __repr__(self) -> str:
        return f"<Empire(id={self.id!r}, name={self.name!r}, status={self.status!r})>"


# ═══════════════════════════════════════════════════════════════════════════
# Lieutenant
# ═══════════════════════════════════════════════════════════════════════════

class Lieutenant(Base):
    """A specialized AI agent that runs the ACE engine with a unique persona."""

    __tablename__ = "lieutenants"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_generate_id)
    empire_id: Mapped[str] = mapped_column(String(32), ForeignKey("empires.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    domain: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active")  # active, inactive, suspended, retired

    # Persona configuration
    persona_json: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    specializations_json: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    preferred_models_json: Mapped[Optional[list]] = mapped_column(JSON, default=list)

    # Performance metrics
    performance_score: Mapped[float] = mapped_column(Float, default=0.5)
    tasks_completed: Mapped[int] = mapped_column(Integer, default=0)
    tasks_failed: Mapped[int] = mapped_column(Integer, default=0)
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    avg_quality_score: Mapped[float] = mapped_column(Float, default=0.0)
    avg_execution_time: Mapped[float] = mapped_column(Float, default=0.0)
    knowledge_entries: Mapped[int] = mapped_column(Integer, default=0)

    # Activity tracking
    current_task_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    last_active_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_learning_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_evolution_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    # Relationships
    empire: Mapped[Empire] = relationship("Empire", back_populates="lieutenants")
    tasks: Mapped[list[Task]] = relationship("Task", back_populates="lieutenant", cascade="all, delete-orphan")
    memory_entries: Mapped[list[MemoryEntry]] = relationship("MemoryEntry", back_populates="lieutenant", cascade="all, delete-orphan")
    evolution_proposals: Mapped[list[EvolutionProposal]] = relationship("EvolutionProposal", back_populates="lieutenant", cascade="all, delete-orphan")
    budget_logs: Mapped[list[BudgetLog]] = relationship("BudgetLog", back_populates="lieutenant", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_lieutenants_empire_id", "empire_id"),
        Index("ix_lieutenants_status", "status"),
        Index("ix_lieutenants_domain", "domain"),
        Index("ix_lieutenants_performance", "performance_score"),
        UniqueConstraint("empire_id", "name", name="uq_lieutenant_name_per_empire"),
        CheckConstraint("status IN ('active', 'inactive', 'suspended', 'retired')", name="ck_lieutenant_status"),
        CheckConstraint("performance_score >= 0.0 AND performance_score <= 1.0", name="ck_lieutenant_perf"),
    )

    @property
    def success_rate(self) -> float:
        total = self.tasks_completed + self.tasks_failed
        return self.tasks_completed / total if total > 0 else 0.0

    def __repr__(self) -> str:
        return f"<Lieutenant(id={self.id!r}, name={self.name!r}, domain={self.domain!r}, status={self.status!r})>"


# ═══════════════════════════════════════════════════════════════════════════
# Directive
# ═══════════════════════════════════════════════════════════════════════════

class Directive(Base):
    """A high-level directive that flows through the full pipeline."""

    __tablename__ = "directives"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_generate_id)
    empire_id: Mapped[str] = mapped_column(String(32), ForeignKey("empires.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="pending")
    priority: Mapped[int] = mapped_column(Integer, default=5)  # 1 = highest, 10 = lowest
    source: Mapped[str] = mapped_column(String(32), default="human")  # human, evolution, autonomous

    # Assignment
    assigned_lieutenants_json: Mapped[Optional[list]] = mapped_column(JSON, default=list)

    # Wave execution
    wave_count: Mapped[int] = mapped_column(Integer, default=0)
    current_wave: Mapped[int] = mapped_column(Integer, default=0)
    wave_plan_json: Mapped[Optional[list]] = mapped_column(JSON, default=list)

    # Results
    results_json: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    quality_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)

    # Pipeline tracking
    pipeline_stage: Mapped[str] = mapped_column(String(32), default="intake")
    pipeline_log_json: Mapped[Optional[list]] = mapped_column(JSON, default=list)

    # Timestamps
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    # Relationships
    empire: Mapped[Empire] = relationship("Empire", back_populates="directives")
    tasks: Mapped[list[Task]] = relationship("Task", back_populates="directive", cascade="all, delete-orphan")
    war_rooms: Mapped[list[WarRoom]] = relationship("WarRoom", back_populates="directive", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_directives_empire_id", "empire_id"),
        Index("ix_directives_status", "status"),
        Index("ix_directives_priority", "priority"),
        Index("ix_directives_source", "source"),
        Index("ix_directives_created_at", "created_at"),
        CheckConstraint(
            "status IN ('pending', 'planning', 'executing', 'reviewing', 'completed', 'failed', 'cancelled', 'paused')",
            name="ck_directive_status",
        ),
        CheckConstraint("priority >= 1 AND priority <= 10", name="ck_directive_priority"),
        CheckConstraint("source IN ('human', 'evolution', 'autonomous', 'god_panel', 'scheduler')", name="ck_directive_source"),
    )

    @property
    def duration_seconds(self) -> float | None:
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None

    @property
    def is_active(self) -> bool:
        return self.status in ("planning", "executing", "reviewing")

    def __repr__(self) -> str:
        return f"<Directive(id={self.id!r}, title={self.title!r}, status={self.status!r})>"


# ═══════════════════════════════════════════════════════════════════════════
# Task
# ═══════════════════════════════════════════════════════════════════════════

class Task(Base):
    """A single task within a directive, executed by a lieutenant."""

    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_generate_id)
    directive_id: Mapped[Optional[str]] = mapped_column(String(32), ForeignKey("directives.id", ondelete="CASCADE"), nullable=True)
    lieutenant_id: Mapped[Optional[str]] = mapped_column(String(32), ForeignKey("lieutenants.id", ondelete="SET NULL"), nullable=True)
    parent_task_id: Mapped[Optional[str]] = mapped_column(String(32), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)

    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="pending")
    task_type: Mapped[str] = mapped_column(String(64), default="general")
    wave_number: Mapped[int] = mapped_column(Integer, default=0)
    priority: Mapped[int] = mapped_column(Integer, default=5)

    # Input/Output
    input_json: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    output_json: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    artifacts_json: Mapped[Optional[list]] = mapped_column(JSON, default=list)

    # LLM tracking
    model_used: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    provider: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    tokens_input: Mapped[int] = mapped_column(Integer, default=0)
    tokens_output: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)

    # Quality
    quality_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    quality_details_json: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)

    # Retry tracking
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=5)
    error_log_json: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Pipeline metadata
    pipeline_stage: Mapped[str] = mapped_column(String(32), default="pending")
    planning_output_json: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    execution_output_json: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    critic_output_json: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)

    # Timing
    execution_time_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    # Relationships
    directive: Mapped[Optional[Directive]] = relationship("Directive", back_populates="tasks")
    lieutenant: Mapped[Optional[Lieutenant]] = relationship("Lieutenant", back_populates="tasks")
    parent_task: Mapped[Optional[Task]] = relationship("Task", remote_side=[id], backref="subtasks")

    __table_args__ = (
        Index("ix_tasks_directive_id", "directive_id"),
        Index("ix_tasks_lieutenant_id", "lieutenant_id"),
        Index("ix_tasks_status", "status"),
        Index("ix_tasks_task_type", "task_type"),
        Index("ix_tasks_wave_number", "wave_number"),
        Index("ix_tasks_created_at", "created_at"),
        Index("ix_tasks_directive_wave", "directive_id", "wave_number"),
        CheckConstraint(
            "status IN ('pending', 'planning', 'executing', 'reviewing', 'completed', 'failed', 'cancelled', 'retrying')",
            name="ck_task_status",
        ),
    )

    @property
    def is_failed(self) -> bool:
        return self.status == "failed"

    @property
    def can_retry(self) -> bool:
        return self.retry_count < self.max_retries and self.status == "failed"

    def __repr__(self) -> str:
        return f"<Task(id={self.id!r}, title={self.title!r}, status={self.status!r}, wave={self.wave_number})>"


# ═══════════════════════════════════════════════════════════════════════════
# War Room
# ═══════════════════════════════════════════════════════════════════════════

class WarRoom(Base):
    """A War Room session where lieutenants debate and plan."""

    __tablename__ = "war_rooms"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_generate_id)
    directive_id: Mapped[Optional[str]] = mapped_column(String(32), ForeignKey("directives.id", ondelete="CASCADE"), nullable=True)
    empire_id: Mapped[str] = mapped_column(String(32), ForeignKey("empires.id", ondelete="CASCADE"), nullable=False)

    title: Mapped[str] = mapped_column(String(256), default="")
    status: Mapped[str] = mapped_column(String(32), default="created")
    session_type: Mapped[str] = mapped_column(String(32), default="planning")  # planning, review, retrospective, debate

    # Participants
    participants_json: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    moderator_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    # Debate
    debate_topic: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    debate_rounds_json: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    debate_round_count: Mapped[int] = mapped_column(Integer, default=0)
    consensus_reached: Mapped[bool] = mapped_column(Boolean, default=False)
    consensus_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Synthesis
    synthesis_json: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    synthesis_model: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Action items
    action_items_json: Mapped[Optional[list]] = mapped_column(JSON, default=list)

    # Retrospective
    retrospective_json: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)

    # Transcript
    transcript_json: Mapped[Optional[list]] = mapped_column(JSON, default=list)

    # Cost
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    # Relationships
    directive: Mapped[Optional[Directive]] = relationship("Directive", back_populates="war_rooms")
    empire: Mapped[Empire] = relationship("Empire", back_populates="war_rooms")

    __table_args__ = (
        Index("ix_war_rooms_empire_id", "empire_id"),
        Index("ix_war_rooms_directive_id", "directive_id"),
        Index("ix_war_rooms_status", "status"),
        CheckConstraint(
            "status IN ('created', 'debating', 'planning', 'reviewing', 'retrospective', 'closed')",
            name="ck_warroom_status",
        ),
    )

    def __repr__(self) -> str:
        return f"<WarRoom(id={self.id!r}, status={self.status!r}, participants={len(self.participants_json or [])})>"


# ═══════════════════════════════════════════════════════════════════════════
# Knowledge Graph
# ═══════════════════════════════════════════════════════════════════════════

class KnowledgeEntity(Base):
    """An entity in the knowledge graph."""

    __tablename__ = "knowledge_entities"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_generate_id)
    empire_id: Mapped[str] = mapped_column(String(32), ForeignKey("empires.id", ondelete="CASCADE"), nullable=False)

    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    attributes_json: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)

    confidence: Mapped[float] = mapped_column(Float, default=0.8)
    importance_score: Mapped[float] = mapped_column(Float, default=0.5)
    access_count: Mapped[int] = mapped_column(Integer, default=0)

    source_task_id: Mapped[Optional[str]] = mapped_column(String(32), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)
    source_type: Mapped[str] = mapped_column(String(32), default="extraction")  # extraction, manual, import, bridge

    # Deferred: a 1536-float JSON array (~25KB/row). Loading it for every
    # SELECT * was a significant chunk of the OOM problem. Callers that need
    # it (vector search, PageRank seeding) must opt-in with .undefer().
    embedding_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True, deferred=True)
    tags_json: Mapped[Optional[list]] = mapped_column(JSON, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    # Relationships
    empire: Mapped[Empire] = relationship("Empire", back_populates="knowledge_entities")
    source_task: Mapped[Optional[Task]] = relationship("Task", foreign_keys=[source_task_id])
    outgoing_relations: Mapped[list[KnowledgeRelation]] = relationship(
        "KnowledgeRelation",
        foreign_keys="KnowledgeRelation.source_entity_id",
        back_populates="source_entity",
        cascade="all, delete-orphan",
    )
    incoming_relations: Mapped[list[KnowledgeRelation]] = relationship(
        "KnowledgeRelation",
        foreign_keys="KnowledgeRelation.target_entity_id",
        back_populates="target_entity",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_knowledge_entities_empire_id", "empire_id"),
        Index("ix_knowledge_entities_type", "entity_type"),
        Index("ix_knowledge_entities_name", "name"),
        Index("ix_knowledge_entities_confidence", "confidence"),
        Index("ix_knowledge_entities_importance", "importance_score"),
        Index("ix_knowledge_entities_empire_type", "empire_id", "entity_type"),
        UniqueConstraint("empire_id", "name", "entity_type", name="uq_entity_name_type_per_empire"),
        CheckConstraint("confidence >= 0.0 AND confidence <= 1.0", name="ck_entity_confidence"),
    )

    @property
    def connection_count(self) -> int:
        return len(self.outgoing_relations or []) + len(self.incoming_relations or [])

    def __repr__(self) -> str:
        return f"<KnowledgeEntity(id={self.id!r}, name={self.name!r}, type={self.entity_type!r})>"


class KnowledgeRelation(Base):
    """A directed relation between two knowledge entities."""

    __tablename__ = "knowledge_relations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_generate_id)
    source_entity_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("knowledge_entities.id", ondelete="CASCADE"), nullable=False
    )
    target_entity_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("knowledge_entities.id", ondelete="CASCADE"), nullable=False
    )

    relation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    confidence: Mapped[float] = mapped_column(Float, default=0.8)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)

    source_task_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    # Relationships
    source_entity: Mapped[KnowledgeEntity] = relationship(
        "KnowledgeEntity", foreign_keys=[source_entity_id], back_populates="outgoing_relations"
    )
    target_entity: Mapped[KnowledgeEntity] = relationship(
        "KnowledgeEntity", foreign_keys=[target_entity_id], back_populates="incoming_relations"
    )

    __table_args__ = (
        Index("ix_knowledge_relations_source", "source_entity_id"),
        Index("ix_knowledge_relations_target", "target_entity_id"),
        Index("ix_knowledge_relations_type", "relation_type"),
        Index("ix_knowledge_relations_pair", "source_entity_id", "target_entity_id"),
        CheckConstraint("confidence >= 0.0 AND confidence <= 1.0", name="ck_relation_confidence"),
    )

    def __repr__(self) -> str:
        return f"<KnowledgeRelation(source={self.source_entity_id!r}, target={self.target_entity_id!r}, type={self.relation_type!r})>"


class KnowledgeFact(Base):
    """An atomic, verifiable claim attached to a knowledge entity.

    Each fact is a single claim (e.g. "DeepSeek-V3.2 has 685B parameters")
    with evidence, source attribution, verification status, and bi-temporal
    validity. Smart deduplication prevents accumulation — similar facts
    (>75% text overlap) are updated, not duplicated.
    """

    __tablename__ = "knowledge_facts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_generate_id)
    empire_id: Mapped[str] = mapped_column(String(32), ForeignKey("empires.id", ondelete="CASCADE"), nullable=False)
    entity_id: Mapped[Optional[str]] = mapped_column(
        String(32), ForeignKey("knowledge_entities.id", ondelete="SET NULL"), nullable=True
    )

    # The claim itself
    claim: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[str] = mapped_column(Text, default="")  # Quote from source that supports the claim
    category: Mapped[str] = mapped_column(String(64), default="general")  # metric, release, capability, pricing, etc.

    # Source attribution
    source_url: Mapped[str] = mapped_column(Text, default="")
    source_tool: Mapped[str] = mapped_column(String(64), default="")  # e.g. mcp_huggingface_hub_repo_details, tavily_search
    source_name: Mapped[str] = mapped_column(String(128), default="")  # e.g. "HuggingFace", "GitHub", "arXiv"

    # Verification
    verification_status: Mapped[str] = mapped_column(
        String(16), default="unverified"
    )  # unverified, supported, contradicted, unverifiable
    verification_source: Mapped[str] = mapped_column(String(128), default="")  # tool/source used for verification
    verification_detail: Mapped[str] = mapped_column(Text, default="")  # explanation of verification result

    # Confidence & quality
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    access_count: Mapped[int] = mapped_column(Integer, default=0)

    # Bi-temporal validity
    valid_from: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Deduplication
    claim_hash: Mapped[str] = mapped_column(String(32), default="")  # MD5 of normalized claim for fast dedup

    # Provenance
    source_task_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    lieutenant_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    # Relationships
    empire: Mapped[Empire] = relationship("Empire")
    entity: Mapped[Optional[KnowledgeEntity]] = relationship("KnowledgeEntity")

    __table_args__ = (
        Index("ix_knowledge_facts_empire_id", "empire_id"),
        Index("ix_knowledge_facts_entity_id", "entity_id"),
        Index("ix_knowledge_facts_verification", "verification_status"),
        Index("ix_knowledge_facts_empire_entity", "empire_id", "entity_id"),
        Index("ix_knowledge_facts_claim_hash", "claim_hash"),
        Index("ix_knowledge_facts_confidence", "confidence"),
        Index("ix_knowledge_facts_source_name", "source_name"),
        CheckConstraint("confidence >= 0.0 AND confidence <= 1.0", name="ck_fact_confidence"),
        CheckConstraint(
            "verification_status IN ('unverified', 'supported', 'contradicted', 'unverifiable')",
            name="ck_fact_verification_status",
        ),
    )

    def __repr__(self) -> str:
        return f"<KnowledgeFact(id={self.id!r}, claim={self.claim[:50]!r}, status={self.verification_status!r})>"


class SourceReliability(Base):
    """Tracks per-source reliability as an exponential moving average.

    Updated when facts from a source get verified (boost) or contradicted
    (penalize). Feeds into tool selection so lieutenants prefer proven sources.
    """

    __tablename__ = "source_reliability"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_generate_id)
    empire_id: Mapped[str] = mapped_column(String(32), ForeignKey("empires.id", ondelete="CASCADE"), nullable=False)
    source_name: Mapped[str] = mapped_column(String(128), nullable=False)  # e.g. "HuggingFace", "GitHub", "arXiv"

    # EMA scores
    reliability_score: Mapped[float] = mapped_column(Float, default=0.7)  # Current EMA (0.0-1.0)
    total_checks: Mapped[int] = mapped_column(Integer, default=0)
    supported_count: Mapped[int] = mapped_column(Integer, default=0)
    contradicted_count: Mapped[int] = mapped_column(Integer, default=0)
    unverifiable_count: Mapped[int] = mapped_column(Integer, default=0)

    # Metadata
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        UniqueConstraint("empire_id", "source_name", name="uq_source_reliability_empire_source"),
        Index("ix_source_reliability_empire", "empire_id"),
        CheckConstraint("reliability_score >= 0.0 AND reliability_score <= 1.0", name="ck_source_reliability"),
    )

    def __repr__(self) -> str:
        return f"<SourceReliability(source={self.source_name!r}, score={self.reliability_score:.2f})>"


# ═══════════════════════════════════════════════════════════════════════════
# Memory
# ═══════════════════════════════════════════════════════════════════════════

class MemoryEntry(Base):
    """A single memory entry in the 4-tier memory system."""

    __tablename__ = "memory_entries"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_generate_id)
    empire_id: Mapped[str] = mapped_column(String(32), ForeignKey("empires.id", ondelete="CASCADE"), nullable=False)
    lieutenant_id: Mapped[Optional[str]] = mapped_column(
        String(32), ForeignKey("lieutenants.id", ondelete="CASCADE"), nullable=True
    )

    memory_type: Mapped[str] = mapped_column(String(32), nullable=False)  # semantic, experiential, design, episodic
    category: Mapped[str] = mapped_column(String(64), default="general")
    title: Mapped[str] = mapped_column(String(256), default="")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    tags_json: Mapped[Optional[list]] = mapped_column(JSON, default=list)

    importance_score: Mapped[float] = mapped_column(Float, default=0.5)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.8)
    relevance_score: Mapped[float] = mapped_column(Float, default=0.5)

    access_count: Mapped[int] = mapped_column(Integer, default=0)
    decay_factor: Mapped[float] = mapped_column(Float, default=1.0)  # 1.0 = no decay, 0.0 = fully decayed
    effective_importance: Mapped[float] = mapped_column(Float, default=0.5)  # importance * decay

    # Deferred — same reasoning as KnowledgeEntity.embedding_json.
    embedding_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True, deferred=True)

    source_task_id: Mapped[Optional[str]] = mapped_column(String(32), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)
    source_type: Mapped[str] = mapped_column(String(32), default="task")  # task, reflection, import, manual, promotion

    # Promotion tracking
    promoted_from_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    promoted_to_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    last_accessed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    empire: Mapped[Empire] = relationship("Empire", back_populates="memory_entries")
    lieutenant: Mapped[Optional[Lieutenant]] = relationship("Lieutenant", back_populates="memory_entries")
    source_task: Mapped[Optional[Task]] = relationship("Task", foreign_keys=[source_task_id])

    __table_args__ = (
        Index("ix_memory_empire_id", "empire_id"),
        Index("ix_memory_lieutenant_id", "lieutenant_id"),
        Index("ix_memory_type", "memory_type"),
        Index("ix_memory_category", "category"),
        Index("ix_memory_importance", "effective_importance"),
        Index("ix_memory_decay", "decay_factor"),
        Index("ix_memory_empire_type", "empire_id", "memory_type"),
        Index("ix_memory_lieutenant_type", "lieutenant_id", "memory_type"),
        Index("ix_memory_expires", "expires_at"),
        CheckConstraint(
            "memory_type IN ('semantic', 'experiential', 'design', 'episodic')",
            name="ck_memory_type",
        ),
        CheckConstraint("importance_score >= 0.0 AND importance_score <= 1.0", name="ck_memory_importance"),
        CheckConstraint("decay_factor >= 0.0 AND decay_factor <= 1.0", name="ck_memory_decay"),
    )

    def apply_decay(self, rate: float = 0.01) -> None:
        """Apply time-based decay to this memory entry."""
        self.decay_factor = max(0.0, self.decay_factor - rate)
        self.effective_importance = self.importance_score * self.decay_factor

    def refresh(self) -> None:
        """Refresh memory on access (slow decay reset)."""
        self.access_count += 1
        self.last_accessed_at = _utcnow()
        self.decay_factor = min(1.0, self.decay_factor + 0.1)
        self.effective_importance = self.importance_score * self.decay_factor

    def __repr__(self) -> str:
        return f"<MemoryEntry(id={self.id!r}, type={self.memory_type!r}, importance={self.effective_importance:.2f})>"


# ═══════════════════════════════════════════════════════════════════════════
# Evolution
# ═══════════════════════════════════════════════════════════════════════════

class EvolutionProposal(Base):
    """A self-improvement proposal from a lieutenant."""

    __tablename__ = "evolution_proposals"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_generate_id)
    empire_id: Mapped[str] = mapped_column(String(32), ForeignKey("empires.id", ondelete="CASCADE"), nullable=False)
    lieutenant_id: Mapped[Optional[str]] = mapped_column(
        String(32), ForeignKey("lieutenants.id", ondelete="SET NULL"), nullable=True
    )
    cycle_id: Mapped[Optional[str]] = mapped_column(
        String(32), ForeignKey("evolution_cycles.id", ondelete="SET NULL"), nullable=True
    )

    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    proposal_type: Mapped[str] = mapped_column(String(32), default="optimization")
    rationale: Mapped[str] = mapped_column(Text, default="")

    # Changes
    code_diff: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    changes_json: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    affected_components_json: Mapped[Optional[list]] = mapped_column(JSON, default=list)

    # Review
    review_status: Mapped[str] = mapped_column(String(32), default="pending")
    review_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewer_model: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    review_scores_json: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)

    # Scoring
    confidence_score: Mapped[float] = mapped_column(Float, default=0.5)
    impact_score: Mapped[float] = mapped_column(Float, default=0.5)
    risk_score: Mapped[float] = mapped_column(Float, default=0.5)
    feasibility_score: Mapped[float] = mapped_column(Float, default=0.5)

    # Application
    applied: Mapped[bool] = mapped_column(Boolean, default=False)
    applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    application_result_json: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    rolled_back: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    # Relationships
    empire: Mapped[Empire] = relationship("Empire", back_populates="evolution_proposals")
    lieutenant: Mapped[Optional[Lieutenant]] = relationship("Lieutenant", back_populates="evolution_proposals")
    cycle: Mapped[Optional[EvolutionCycle]] = relationship("EvolutionCycle", back_populates="proposals")

    __table_args__ = (
        Index("ix_evolution_proposals_empire_id", "empire_id"),
        Index("ix_evolution_proposals_lieutenant_id", "lieutenant_id"),
        Index("ix_evolution_proposals_cycle_id", "cycle_id"),
        Index("ix_evolution_proposals_status", "review_status"),
        Index("ix_evolution_proposals_type", "proposal_type"),
        CheckConstraint(
            "review_status IN ('pending', 'approved', 'rejected', 'revision_needed', 'deferred')",
            name="ck_proposal_review_status",
        ),
        CheckConstraint(
            "proposal_type IN ('optimization', 'bug_fix', 'new_capability', 'refactor', 'knowledge_update', 'process_improvement')",
            name="ck_proposal_type",
        ),
    )

    def __repr__(self) -> str:
        return f"<EvolutionProposal(id={self.id!r}, title={self.title!r}, status={self.review_status!r})>"


class EvolutionCycle(Base):
    """A single evolution cycle — collect, review, apply, learn."""

    __tablename__ = "evolution_cycles"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_generate_id)
    empire_id: Mapped[str] = mapped_column(String(32), ForeignKey("empires.id", ondelete="CASCADE"), nullable=False)

    status: Mapped[str] = mapped_column(String(32), default="collecting")
    cycle_number: Mapped[int] = mapped_column(Integer, default=1)

    proposals_count: Mapped[int] = mapped_column(Integer, default=0)
    approved_count: Mapped[int] = mapped_column(Integer, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0)
    applied_count: Mapped[int] = mapped_column(Integer, default=0)
    rolled_back_count: Mapped[int] = mapped_column(Integer, default=0)

    learnings_json: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    metrics_json: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)

    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=_utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # Relationships
    empire: Mapped[Empire] = relationship("Empire", back_populates="evolution_cycles")
    proposals: Mapped[list[EvolutionProposal]] = relationship("EvolutionProposal", back_populates="cycle", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_evolution_cycles_empire_id", "empire_id"),
        Index("ix_evolution_cycles_status", "status"),
        CheckConstraint(
            "status IN ('collecting', 'reviewing', 'executing', 'learning', 'completed', 'failed')",
            name="ck_cycle_status",
        ),
    )

    @property
    def approval_rate(self) -> float:
        if self.proposals_count == 0:
            return 0.0
        return self.approved_count / self.proposals_count

    def __repr__(self) -> str:
        return f"<EvolutionCycle(id={self.id!r}, cycle={self.cycle_number}, status={self.status!r})>"


# ═══════════════════════════════════════════════════════════════════════════
# Budget & Cost Tracking
# ═══════════════════════════════════════════════════════════════════════════

class BudgetLog(Base):
    """A single cost event for budget tracking."""

    __tablename__ = "budget_logs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_generate_id)
    empire_id: Mapped[str] = mapped_column(String(32), ForeignKey("empires.id", ondelete="CASCADE"), nullable=False)

    model_used: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    tokens_input: Mapped[int] = mapped_column(Integer, default=0)
    tokens_output: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False)

    task_id: Mapped[Optional[str]] = mapped_column(String(32), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)
    lieutenant_id: Mapped[Optional[str]] = mapped_column(
        String(32), ForeignKey("lieutenants.id", ondelete="SET NULL"), nullable=True
    )
    directive_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    purpose: Mapped[str] = mapped_column(String(64), default="task_execution")
    purpose_detail: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)

    # Daily/monthly aggregation helpers
    cost_date: Mapped[str] = mapped_column(String(10), nullable=False)  # YYYY-MM-DD
    cost_month: Mapped[str] = mapped_column(String(7), nullable=False)  # YYYY-MM

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # Relationships
    empire: Mapped[Empire] = relationship("Empire", back_populates="budget_logs")
    task: Mapped[Optional[Task]] = relationship("Task", foreign_keys=[task_id])
    lieutenant: Mapped[Optional[Lieutenant]] = relationship("Lieutenant", back_populates="budget_logs")

    __table_args__ = (
        Index("ix_budget_logs_empire_id", "empire_id"),
        Index("ix_budget_logs_date", "cost_date"),
        Index("ix_budget_logs_month", "cost_month"),
        Index("ix_budget_logs_model", "model_used"),
        Index("ix_budget_logs_provider", "provider"),
        Index("ix_budget_logs_purpose", "purpose"),
        Index("ix_budget_logs_lieutenant", "lieutenant_id"),
        Index("ix_budget_logs_empire_date", "empire_id", "cost_date"),
        Index("ix_budget_logs_empire_month", "empire_id", "cost_month"),
    )

    def __repr__(self) -> str:
        return f"<BudgetLog(model={self.model_used!r}, cost=${self.cost_usd:.4f}, purpose={self.purpose!r})>"


# ═══════════════════════════════════════════════════════════════════════════
# Health Checks
# ═══════════════════════════════════════════════════════════════════════════

class HealthCheck(Base):
    """A health check record."""

    __tablename__ = "health_checks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_generate_id)
    empire_id: Mapped[str] = mapped_column(String(32), ForeignKey("empires.id", ondelete="CASCADE"), nullable=False)

    check_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)  # healthy, degraded, unhealthy
    message: Mapped[str] = mapped_column(String(256), default="")
    details_json: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)

    response_time_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # Relationships
    empire: Mapped[Empire] = relationship("Empire", back_populates="health_checks")

    __table_args__ = (
        Index("ix_health_checks_empire_id", "empire_id"),
        Index("ix_health_checks_type", "check_type"),
        Index("ix_health_checks_status", "status"),
        Index("ix_health_checks_created_at", "created_at"),
        CheckConstraint("status IN ('healthy', 'unhealthy', 'unknown')", name="ck_health_status"),
    )

    def __repr__(self) -> str:
        return f"<HealthCheck(type={self.check_type!r}, status={self.status!r})>"


# ═══════════════════════════════════════════════════════════════════════════
# Scheduler
# ═══════════════════════════════════════════════════════════════════════════

class SchedulerJob(Base):
    """A registered scheduler job."""

    __tablename__ = "scheduler_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_generate_id)
    empire_id: Mapped[str] = mapped_column(String(32), ForeignKey("empires.id", ondelete="CASCADE"), nullable=False)

    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(String(256), default="")
    status: Mapped[str] = mapped_column(String(32), default="active")  # active, paused, disabled, error
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # Scheduling
    interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    cron_expression: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=5)

    # Execution tracking
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    run_count: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    consecutive_errors: Mapped[int] = mapped_column(Integer, default=0)

    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_duration_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    avg_duration_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    config_json: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    # Relationships
    empire: Mapped[Empire] = relationship("Empire", back_populates="scheduler_jobs")

    __table_args__ = (
        Index("ix_scheduler_jobs_empire_id", "empire_id"),
        Index("ix_scheduler_jobs_type", "job_type"),
        Index("ix_scheduler_jobs_status", "status"),
        Index("ix_scheduler_jobs_next_run", "next_run_at"),
        UniqueConstraint("empire_id", "job_type", name="uq_job_type_per_empire"),
        CheckConstraint("status IN ('active', 'paused', 'disabled', 'error')", name="ck_job_status"),
    )

    @property
    def success_rate(self) -> float:
        if self.run_count == 0:
            return 0.0
        return self.success_count / self.run_count

    def __repr__(self) -> str:
        return f"<SchedulerJob(type={self.job_type!r}, status={self.status!r}, runs={self.run_count})>"


# ═══════════════════════════════════════════════════════════════════════════
# Cross-Empire Sync
# ═══════════════════════════════════════════════════════════════════════════

class CrossEmpireSync(Base):
    """A cross-empire synchronization record."""

    __tablename__ = "cross_empire_syncs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_generate_id)
    source_empire_id: Mapped[str] = mapped_column(String(32), nullable=False)
    target_empire_id: Mapped[str] = mapped_column(String(32), nullable=False)

    sync_type: Mapped[str] = mapped_column(String(32), nullable=False)  # knowledge, memory, lieutenant, full
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending, in_progress, completed, failed

    # Payload
    payload_json: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    entities_synced: Mapped[int] = mapped_column(Integer, default=0)
    relations_synced: Mapped[int] = mapped_column(Integer, default=0)
    conflicts_found: Mapped[int] = mapped_column(Integer, default=0)
    conflicts_resolved: Mapped[int] = mapped_column(Integer, default=0)

    # Results
    result_json: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_cross_sync_source", "source_empire_id"),
        Index("ix_cross_sync_target", "target_empire_id"),
        Index("ix_cross_sync_status", "status"),
        Index("ix_cross_sync_type", "sync_type"),
        CheckConstraint("status IN ('pending', 'in_progress', 'completed', 'failed')", name="ck_sync_status"),
        CheckConstraint("sync_type IN ('knowledge', 'memory', 'lieutenant', 'full')", name="ck_sync_type"),
    )

    @property
    def duration_seconds(self) -> float | None:
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None

    def __repr__(self) -> str:
        return f"<CrossEmpireSync(source={self.source_empire_id!r}, target={self.target_empire_id!r}, type={self.sync_type!r})>"


class GodPanelCommand(Base):
    """A God Panel command with its execution state."""

    __tablename__ = "god_panel_commands"

    id: Mapped[str] = mapped_column(String(12), primary_key=True)
    empire_id: Mapped[str] = mapped_column(String(32), ForeignKey("empires.id", ondelete="CASCADE"), nullable=False)
    command: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    topic: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="accepted")
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    result_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_gpc_empire_id", "empire_id"),
        Index("ix_gpc_status", "status"),
        Index("ix_gpc_started_at", "started_at"),
        CheckConstraint(
            "status IN ('accepted', 'running', 'researching', 'completed', 'failed')",
            name="ck_gpc_status",
        ),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "command": self.command,
            "action": self.action,
            "topic": self.topic,
            "status": self.status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "result": self.result_json,
            "error": self.error,
            "cost": self.cost_usd,
        }

    def __repr__(self) -> str:
        return f"<GodPanelCommand(id={self.id!r}, action={self.action!r}, status={self.status!r})>"

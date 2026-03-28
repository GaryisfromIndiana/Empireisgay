"""Application settings using Pydantic."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMModelConfig:
    """Configuration for a single LLM model."""

    def __init__(
        self,
        model_id: str,
        provider: str,
        cost_per_1k_input: float,
        cost_per_1k_output: float,
        max_tokens: int,
        tier: int,
        capabilities: list[str] | None = None,
    ):
        self.model_id = model_id
        self.provider = provider
        self.cost_per_1k_input = cost_per_1k_input
        self.cost_per_1k_output = cost_per_1k_output
        self.max_tokens = max_tokens
        self.tier = tier
        self.capabilities = capabilities or []

    @property
    def cost_per_1k_total(self) -> float:
        return self.cost_per_1k_input + self.cost_per_1k_output

    def __repr__(self) -> str:
        return f"LLMModelConfig(model_id={self.model_id!r}, provider={self.provider!r}, tier={self.tier})"


# ── Model catalog ──────────────────────────────────────────────────────────

MODEL_CATALOG: dict[str, LLMModelConfig] = {
    # Anthropic
    "claude-opus-4": LLMModelConfig(
        model_id="claude-opus-4-20250514",
        provider="anthropic",
        cost_per_1k_input=0.015,
        cost_per_1k_output=0.075,
        max_tokens=32_000,
        tier=1,
        capabilities=["reasoning", "code", "analysis", "creative", "vision"],
    ),
    "claude-sonnet-4": LLMModelConfig(
        model_id="claude-sonnet-4-20250514",
        provider="anthropic",
        cost_per_1k_input=0.003,
        cost_per_1k_output=0.015,
        max_tokens=16_000,
        tier=2,
        capabilities=["reasoning", "code", "analysis", "creative", "vision"],
    ),
    "claude-haiku-4.5": LLMModelConfig(
        model_id="claude-haiku-4-5-20251001",
        provider="anthropic",
        cost_per_1k_input=0.001,
        cost_per_1k_output=0.005,
        max_tokens=8_192,
        tier=3,
        capabilities=["reasoning", "code", "analysis"],
    ),
    # OpenAI
    "gpt-4o": LLMModelConfig(
        model_id="gpt-4o",
        provider="openai",
        cost_per_1k_input=0.005,
        cost_per_1k_output=0.015,
        max_tokens=16_384,
        tier=2,
        capabilities=["reasoning", "code", "analysis", "creative", "vision"],
    ),
    "gpt-4o-mini": LLMModelConfig(
        model_id="gpt-4o-mini",
        provider="openai",
        cost_per_1k_input=0.00015,
        cost_per_1k_output=0.0006,
        max_tokens=16_384,
        tier=4,
        capabilities=["reasoning", "code", "analysis"],
    ),
    "o3-mini": LLMModelConfig(
        model_id="o3-mini",
        provider="openai",
        cost_per_1k_input=0.0011,
        cost_per_1k_output=0.0044,
        max_tokens=100_000,
        tier=3,
        capabilities=["reasoning", "code", "analysis", "math"],
    ),
}

# ── Tier descriptions ──────────────────────────────────────────────────────

TIER_DESCRIPTIONS = {
    1: "Premium — complex reasoning, multi-step analysis, code generation",
    2: "Standard — general analysis, moderate complexity tasks",
    3: "Economy — research, summarization, simple analysis",
    4: "Flash — classification, extraction, simple routing",
}


class SchedulerSettings(BaseSettings):
    """Scheduler-specific settings."""

    tick_interval_seconds: int = Field(default=60, ge=5, le=3600)
    learning_cycle_hours: int = Field(default=6, ge=1, le=24)
    evolution_cycle_hours: int = Field(default=12, ge=1, le=48)
    health_check_interval_minutes: int = Field(default=5, ge=1, le=60)
    knowledge_maintenance_hours: int = Field(default=4, ge=1, le=24)
    max_concurrent_jobs: int = Field(default=5, ge=1, le=20)
    job_timeout_seconds: int = Field(default=300, ge=30, le=3600)


class BudgetSettings(BaseSettings):
    """Budget control settings."""

    daily_limit_usd: float = Field(default=50.0, ge=0.0)
    monthly_limit_usd: float = Field(default=500.0, ge=0.0)
    per_task_limit_usd: float = Field(default=5.0, ge=0.0)
    per_directive_limit_usd: float = Field(default=25.0, ge=0.0)
    alert_threshold_percent: float = Field(default=80.0, ge=0.0, le=100.0)
    hard_stop_on_limit: bool = True


class RetrySettings(BaseSettings):
    """Ralph Wiggum retry loop settings."""

    max_retries: int = Field(default=5, ge=1, le=10)
    escalate_model_after: int = Field(default=2, ge=1, le=5)
    inject_error_context: bool = True
    inject_sibling_context: bool = True
    backoff_base_seconds: float = Field(default=2.0, ge=0.5, le=30.0)
    backoff_multiplier: float = Field(default=1.5, ge=1.0, le=5.0)
    backoff_max_seconds: float = Field(default=60.0, ge=5.0, le=300.0)


class QualitySettings(BaseSettings):
    """Quality gate settings."""

    min_confidence_score: float = Field(default=0.5, ge=0.0, le=1.0)
    min_completeness_score: float = Field(default=0.6, ge=0.0, le=1.0)
    min_coherence_score: float = Field(default=0.65, ge=0.0, le=1.0)
    require_source_citations: bool = True
    max_hallucination_score: float = Field(default=0.3, ge=0.0, le=1.0)
    auto_reject_below: float = Field(default=0.4, ge=0.0, le=1.0)
    require_critic_approval: bool = True


class ACESettings(BaseSettings):
    """ACE engine settings."""

    default_planning_model: str = "claude-haiku-4.5"  # Planning is simple — use Haiku
    default_execution_model: str = "claude-sonnet-4"  # Execution needs quality — use Sonnet
    default_critic_model: str = "claude-haiku-4.5"    # Critic is simple evaluation — use Haiku
    escalation_model: str = "claude-opus-4"  # Escalate to Opus when Sonnet fails quality
    escalate_after_failures: int = Field(default=2, ge=1, le=5)  # Escalate after N critic failures
    max_pipeline_iterations: int = Field(default=1, ge=1, le=10)
    enable_parallel_execution: bool = True
    max_parallel_tasks: int = Field(default=5, ge=1, le=20)
    task_timeout_seconds: int = Field(default=600, ge=30, le=3600)


class WarRoomSettings(BaseSettings):
    """War Room settings."""

    max_debate_rounds: int = Field(default=3, ge=1, le=10)
    max_participants: int = Field(default=8, ge=2, le=20)
    synthesis_model: str = "claude-sonnet-4"
    require_consensus: bool = False
    consensus_threshold: float = Field(default=0.7, ge=0.5, le=1.0)
    enable_retrospectives: bool = True
    retrospective_model: str = "claude-sonnet-4"


class KnowledgeSettings(BaseSettings):
    """Knowledge system settings."""

    max_entities_per_extraction: int = Field(default=50, ge=1, le=200)
    entity_confidence_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    graph_max_depth: int = Field(default=5, ge=1, le=20)
    enable_cross_empire_bridge: bool = True
    bridge_sync_interval_minutes: int = Field(default=30, ge=5, le=360)
    embedding_model: str = "gpt-4o-mini"
    similarity_threshold: float = Field(default=0.75, ge=0.0, le=1.0)


class QdrantSettings(BaseSettings):
    """Qdrant vector database settings.

    Set EMPIRE_QDRANT__URL to enable Qdrant.
    Falls back to in-memory Python cosine similarity when not configured.
    """

    url: str = ""  # e.g. "http://localhost:6333" or Qdrant Cloud URL
    api_key: str = ""  # For Qdrant Cloud
    collection_prefix: str = "empire"  # Collections: empire_memories, empire_entities
    embedding_dimension: int = 1536  # text-embedding-3-small
    on_disk: bool = True  # Store on disk for persistence
    batch_upsert_size: int = 100
    search_limit_default: int = 20
    hnsw_ef: int = 128  # Higher = more accurate but slower
    hnsw_m: int = 16  # Higher = more memory, better recall


class MCPSettings(BaseSettings):
    """MCP (Model Context Protocol) server settings.

    Configure external MCP servers that lieutenants can use as tools.
    Servers are defined as a dict of name -> config.

    Example env var:
        EMPIRE_MCP__SERVERS='{"filesystem": {"command": ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/data"]}}'
    """

    servers: dict = Field(default_factory=dict)
    enabled: bool = True
    auto_connect_on_start: bool = True
    default_timeout: float = Field(default=30.0, ge=5.0, le=300.0)
    max_tool_result_chars: int = Field(default=8000, ge=500, le=50000)


class EvolutionSettings(BaseSettings):
    """Evolution system settings."""

    proposal_model: str = "claude-sonnet-4"
    review_model: str = "claude-opus-4"
    auto_reject_confidence_below: float = Field(default=0.5, ge=0.0, le=1.0)
    max_proposals_per_cycle: int = Field(default=10, ge=1, le=50)
    require_review_approval: bool = True
    enable_auto_apply: bool = False
    cooldown_hours: int = Field(default=2, ge=0, le=24)


class Settings(BaseSettings):
    """Main application settings."""

    model_config = SettingsConfigDict(
        env_prefix="EMPIRE_",
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    # ── Core ───────────────────────────────────────────────────────────
    app_name: str = "Empire"
    debug: bool = False
    log_level: str = "INFO"
    base_dir: Path = Field(default_factory=lambda: Path(__file__).resolve().parent.parent)
    data_dir: Optional[Path] = None

    # ── Database ───────────────────────────────────────────────────────
    db_url: str = "sqlite:///empire.db"
    db_echo: bool = False
    db_pool_size: int = Field(default=5, ge=1, le=50)

    # ── API Keys ───────────────────────────────────────────────────────
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    google_api_key: str = ""
    xai_api_key: str = ""
    tavily_api_key: str = ""

    # ── Flask ──────────────────────────────────────────────────────────
    flask_secret_key: str = "change-me-to-random-string"
    flask_debug: bool = False
    flask_host: str = "0.0.0.0"
    flask_port: int = Field(default=5000, ge=1024, le=65535)

    # ── Authentication ──────────────────────────────────────────────
    auth_username: str = "admin"
    auth_password: str = ""  # Set EMPIRE_AUTH_PASSWORD to enable auth
    api_key: str = ""  # Set EMPIRE_API_KEY for API access

    # ── Empire identity ────────────────────────────────────────────────
    empire_id: str = "empire-alpha"
    empire_name: str = "Alpha Empire"
    empire_description: str = "Primary autonomous empire"

    # ── Sub-settings ───────────────────────────────────────────────────
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)
    budget: BudgetSettings = Field(default_factory=BudgetSettings)
    retry: RetrySettings = Field(default_factory=RetrySettings)
    quality: QualitySettings = Field(default_factory=QualitySettings)
    ace: ACESettings = Field(default_factory=ACESettings)
    warroom: WarRoomSettings = Field(default_factory=WarRoomSettings)
    knowledge: KnowledgeSettings = Field(default_factory=KnowledgeSettings)
    evolution: EvolutionSettings = Field(default_factory=EvolutionSettings)
    qdrant: QdrantSettings = Field(default_factory=QdrantSettings)
    mcp: MCPSettings = Field(default_factory=MCPSettings)

    @field_validator("data_dir", mode="before")
    @classmethod
    def set_data_dir(cls, v: Optional[Path], info) -> Path:
        if v is not None:
            return Path(v)
        base = info.data.get("base_dir", Path(__file__).resolve().parent.parent)
        return Path(base) / "data"

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in valid:
            raise ValueError(f"Invalid log level: {v}. Must be one of {valid}")
        return upper

    def get_model_config(self, model_key: str) -> LLMModelConfig:
        """Get model configuration by key."""
        if model_key not in MODEL_CATALOG:
            raise ValueError(f"Unknown model: {model_key}. Available: {list(MODEL_CATALOG.keys())}")
        return MODEL_CATALOG[model_key]

    def get_api_key(self, provider: str) -> str:
        """Get API key for a provider."""
        keys = {
            "anthropic": self.anthropic_api_key,
            "openai": self.openai_api_key,
            "google": self.google_api_key,
            "xai": self.xai_api_key,
        }
        key = keys.get(provider, "")
        if not key:
            raise ValueError(f"No API key configured for provider: {provider}")
        return key

    def get_models_for_tier(self, tier: int) -> list[LLMModelConfig]:
        """Get all models for a given tier."""
        return [m for m in MODEL_CATALOG.values() if m.tier == tier]

    def get_cheapest_model(self, capabilities: list[str] | None = None) -> LLMModelConfig:
        """Get the cheapest model optionally filtered by required capabilities."""
        candidates = list(MODEL_CATALOG.values())
        if capabilities:
            candidates = [
                m for m in candidates
                if all(c in m.capabilities for c in capabilities)
            ]
        if not candidates:
            raise ValueError(f"No model found with capabilities: {capabilities}")
        return min(candidates, key=lambda m: m.cost_per_1k_total)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get cached application settings singleton."""
    return Settings()

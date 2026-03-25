"""Entity type schemas — enforce what attributes are valid for each entity type.

Every entity in the knowledge graph has a type, and each type has a schema
defining required/optional fields with validation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class FieldDef:
    """Definition of a single field in an entity schema."""
    name: str
    field_type: str = "string"  # string, number, date, list, boolean, url
    required: bool = False
    description: str = ""
    default: Any = None
    examples: list[str] = field(default_factory=list)


@dataclass
class EntitySchema:
    """Schema for an entity type."""
    entity_type: str
    display_name: str
    description: str
    fields: list[FieldDef] = field(default_factory=list)
    parent_type: str = ""  # Inheritance

    @property
    def required_fields(self) -> list[str]:
        return [f.name for f in self.fields if f.required]

    @property
    def all_field_names(self) -> list[str]:
        return [f.name for f in self.fields]

    def validate(self, attributes: dict) -> tuple[bool, list[str]]:
        """Validate attributes against this schema.

        Returns:
            (valid, list of issues)
        """
        issues = []
        for f in self.fields:
            if f.required and f.name not in attributes:
                issues.append(f"Missing required field: {f.name}")
            if f.name in attributes:
                val = attributes[f.name]
                if f.field_type == "number" and val is not None:
                    try:
                        float(val)
                    except (TypeError, ValueError):
                        issues.append(f"Field {f.name} should be a number, got: {type(val).__name__}")
                if f.field_type == "list" and not isinstance(val, list):
                    issues.append(f"Field {f.name} should be a list")
                if f.field_type == "boolean" and not isinstance(val, bool):
                    issues.append(f"Field {f.name} should be boolean")
        return len(issues) == 0, issues

    def apply_defaults(self, attributes: dict) -> dict:
        """Apply default values for missing optional fields."""
        result = dict(attributes)
        for f in self.fields:
            if f.name not in result and f.default is not None:
                result[f.name] = f.default
        return result


# ═══════════════════════════════════════════════════════════════════════════
# Entity type schemas — 22 types for AI research domain
# ═══════════════════════════════════════════════════════════════════════════

ENTITY_SCHEMAS: dict[str, EntitySchema] = {}


def _register(schema: EntitySchema) -> None:
    ENTITY_SCHEMAS[schema.entity_type] = schema


# ── AI Models ──────────────────────────────────────────────────────────

_register(EntitySchema(
    entity_type="ai_model",
    display_name="AI Model",
    description="A specific AI/ML model (e.g., GPT-4, Claude 3, Llama 3)",
    fields=[
        FieldDef("provider", "string", required=True, description="Company that created the model"),
        FieldDef("model_family", "string", description="Model family (e.g., GPT, Claude, Llama)"),
        FieldDef("release_date", "date", description="Release date"),
        FieldDef("parameter_count", "string", description="Parameter count (e.g., '70B', '1.8T')"),
        FieldDef("context_window", "number", description="Max context window in tokens"),
        FieldDef("modalities", "list", default=[], description="Input/output modalities (text, image, audio, video)"),
        FieldDef("open_weight", "boolean", default=False, description="Whether weights are publicly available"),
        FieldDef("pricing_input", "number", description="Cost per 1K input tokens (USD)"),
        FieldDef("pricing_output", "number", description="Cost per 1K output tokens (USD)"),
        FieldDef("benchmark_scores", "list", default=[], description="Notable benchmark results"),
        FieldDef("capabilities", "list", default=[], description="Key capabilities"),
        FieldDef("limitations", "list", default=[], description="Known limitations"),
    ],
))

_register(EntitySchema(
    entity_type="model_family",
    display_name="Model Family",
    description="A family of related models (e.g., the GPT series, Claude series)",
    fields=[
        FieldDef("provider", "string", required=True),
        FieldDef("models", "list", default=[], description="List of model names in this family"),
        FieldDef("first_release", "date"),
        FieldDef("latest_release", "date"),
        FieldDef("architecture", "string", description="Base architecture"),
    ],
))

# ── Organizations ──────────────────────────────────────────────────────

_register(EntitySchema(
    entity_type="company",
    display_name="Company",
    description="An AI company or research lab",
    fields=[
        FieldDef("founded", "date"),
        FieldDef("headquarters", "string"),
        FieldDef("ceo", "string"),
        FieldDef("funding_total", "string", description="Total funding raised"),
        FieldDef("valuation", "string"),
        FieldDef("employee_count", "number"),
        FieldDef("products", "list", default=[], description="Key products"),
        FieldDef("focus_areas", "list", default=[], description="Research/product focus"),
        FieldDef("competitors", "list", default=[]),
        FieldDef("website", "url"),
    ],
))

_register(EntitySchema(
    entity_type="research_lab",
    display_name="Research Lab",
    description="An academic or corporate research lab",
    fields=[
        FieldDef("parent_org", "string", description="Parent organization"),
        FieldDef("director", "string"),
        FieldDef("focus_areas", "list", default=[]),
        FieldDef("notable_papers", "list", default=[]),
        FieldDef("location", "string"),
    ],
))

# ── Research ───────────────────────────────────────────────────────────

_register(EntitySchema(
    entity_type="paper",
    display_name="Research Paper",
    description="An academic paper or preprint",
    fields=[
        FieldDef("title", "string", required=True),
        FieldDef("authors", "list", default=[]),
        FieldDef("published_date", "date"),
        FieldDef("venue", "string", description="Conference or journal"),
        FieldDef("arxiv_id", "string"),
        FieldDef("abstract", "string"),
        FieldDef("key_contribution", "string"),
        FieldDef("citations", "number"),
        FieldDef("url", "url"),
        FieldDef("topics", "list", default=[]),
    ],
))

_register(EntitySchema(
    entity_type="technique",
    display_name="AI Technique",
    description="A training or inference technique (e.g., RLHF, DPO, LoRA)",
    fields=[
        FieldDef("category", "string", description="Training, inference, fine-tuning, etc."),
        FieldDef("introduced_by", "string"),
        FieldDef("introduced_date", "date"),
        FieldDef("paper_url", "url"),
        FieldDef("use_cases", "list", default=[]),
        FieldDef("advantages", "list", default=[]),
        FieldDef("limitations", "list", default=[]),
        FieldDef("superseded_by", "string"),
    ],
))

_register(EntitySchema(
    entity_type="architecture",
    display_name="Model Architecture",
    description="A neural network architecture (e.g., Transformer, Mamba, SSM)",
    fields=[
        FieldDef("introduced_by", "string"),
        FieldDef("introduced_date", "date"),
        FieldDef("paper_title", "string"),
        FieldDef("key_innovation", "string"),
        FieldDef("models_using_it", "list", default=[]),
        FieldDef("advantages", "list", default=[]),
    ],
))

# ── Concepts ───────────────────────────────────────────────────────────

_register(EntitySchema(
    entity_type="concept",
    display_name="AI Concept",
    description="A theoretical concept (e.g., scaling laws, emergent abilities, alignment)",
    fields=[
        FieldDef("domain", "string"),
        FieldDef("definition", "string"),
        FieldDef("related_concepts", "list", default=[]),
        FieldDef("key_papers", "list", default=[]),
        FieldDef("importance", "string", description="Why this matters"),
    ],
))

_register(EntitySchema(
    entity_type="benchmark",
    display_name="Benchmark",
    description="An AI evaluation benchmark (e.g., MMLU, HumanEval, SWE-bench)",
    fields=[
        FieldDef("measures", "string", description="What it evaluates"),
        FieldDef("created_by", "string"),
        FieldDef("created_date", "date"),
        FieldDef("top_scores", "list", default=[], description="Best known scores"),
        FieldDef("url", "url"),
        FieldDef("criticisms", "list", default=[]),
    ],
))

_register(EntitySchema(
    entity_type="dataset",
    display_name="Dataset",
    description="A training or evaluation dataset",
    fields=[
        FieldDef("size", "string"),
        FieldDef("created_by", "string"),
        FieldDef("domain", "string"),
        FieldDef("license", "string"),
        FieldDef("url", "url"),
        FieldDef("used_by", "list", default=[]),
    ],
))

# ── Products & Tools ───────────────────────────────────────────────────

_register(EntitySchema(
    entity_type="product",
    display_name="AI Product",
    description="A commercial AI product or service (e.g., ChatGPT, Claude, Copilot)",
    fields=[
        FieldDef("company", "string", required=True),
        FieldDef("launched", "date"),
        FieldDef("pricing", "string"),
        FieldDef("model_used", "string"),
        FieldDef("target_audience", "string"),
        FieldDef("features", "list", default=[]),
        FieldDef("competitors", "list", default=[]),
        FieldDef("url", "url"),
    ],
))

_register(EntitySchema(
    entity_type="framework",
    display_name="AI Framework/Library",
    description="A software framework or library (e.g., LangChain, PyTorch, vLLM)",
    fields=[
        FieldDef("category", "string", description="Agent, training, inference, etc."),
        FieldDef("created_by", "string"),
        FieldDef("language", "string"),
        FieldDef("github_url", "url"),
        FieldDef("stars", "number"),
        FieldDef("license", "string"),
        FieldDef("features", "list", default=[]),
        FieldDef("alternatives", "list", default=[]),
    ],
))

_register(EntitySchema(
    entity_type="api",
    display_name="AI API",
    description="An AI API endpoint or service",
    fields=[
        FieldDef("provider", "string", required=True),
        FieldDef("models_available", "list", default=[]),
        FieldDef("pricing_model", "string"),
        FieldDef("rate_limits", "string"),
        FieldDef("features", "list", default=[]),
        FieldDef("docs_url", "url"),
    ],
))

# ── Infrastructure ─────────────────────────────────────────────────────

_register(EntitySchema(
    entity_type="hardware",
    display_name="AI Hardware",
    description="Hardware for AI training/inference (e.g., H100, TPU v5, Groq LPU)",
    fields=[
        FieldDef("manufacturer", "string", required=True),
        FieldDef("release_date", "date"),
        FieldDef("memory", "string"),
        FieldDef("performance", "string"),
        FieldDef("price", "string"),
        FieldDef("used_by", "list", default=[]),
    ],
))

_register(EntitySchema(
    entity_type="cloud_provider",
    display_name="Cloud/Inference Provider",
    description="Cloud or inference hosting provider (e.g., Together AI, Fireworks, Groq)",
    fields=[
        FieldDef("models_hosted", "list", default=[]),
        FieldDef("pricing", "string"),
        FieldDef("unique_features", "list", default=[]),
        FieldDef("url", "url"),
    ],
))

# ── Events & Industry ──────────────────────────────────────────────────

_register(EntitySchema(
    entity_type="event",
    display_name="AI Event",
    description="A conference, launch event, or industry milestone",
    fields=[
        FieldDef("event_type", "string", description="Conference, launch, acquisition, etc."),
        FieldDef("date", "date", required=True),
        FieldDef("location", "string"),
        FieldDef("organizer", "string"),
        FieldDef("key_announcements", "list", default=[]),
        FieldDef("significance", "string"),
    ],
))

_register(EntitySchema(
    entity_type="funding_round",
    display_name="Funding Round",
    description="An investment or funding event",
    fields=[
        FieldDef("company", "string", required=True),
        FieldDef("amount", "string", required=True),
        FieldDef("round_type", "string", description="Seed, Series A, etc."),
        FieldDef("date", "date"),
        FieldDef("investors", "list", default=[]),
        FieldDef("valuation", "string"),
    ],
))

_register(EntitySchema(
    entity_type="regulation",
    display_name="AI Regulation/Policy",
    description="A law, regulation, or policy affecting AI",
    fields=[
        FieldDef("jurisdiction", "string", required=True),
        FieldDef("status", "string", description="Proposed, enacted, etc."),
        FieldDef("effective_date", "date"),
        FieldDef("scope", "string"),
        FieldDef("key_provisions", "list", default=[]),
        FieldDef("affected_entities", "list", default=[]),
    ],
))

# ── People ─────────────────────────────────────────────────────────────

_register(EntitySchema(
    entity_type="person",
    display_name="Person",
    description="A notable person in AI",
    fields=[
        FieldDef("role", "string"),
        FieldDef("organization", "string"),
        FieldDef("known_for", "list", default=[]),
        FieldDef("twitter", "string"),
        FieldDef("website", "url"),
    ],
))

# ── Metrics & Trends ───────────────────────────────────────────────────

_register(EntitySchema(
    entity_type="metric",
    display_name="AI Metric/Statistic",
    description="A quantitative metric or statistic about AI",
    fields=[
        FieldDef("value", "string", required=True),
        FieldDef("unit", "string"),
        FieldDef("measured_date", "date"),
        FieldDef("source", "string"),
        FieldDef("context", "string"),
        FieldDef("trend", "string", description="Increasing, decreasing, stable"),
    ],
))

_register(EntitySchema(
    entity_type="trend",
    display_name="AI Trend",
    description="An observed trend in AI development",
    fields=[
        FieldDef("domain", "string"),
        FieldDef("direction", "string", description="Growing, declining, emerging, etc."),
        FieldDef("evidence", "list", default=[]),
        FieldDef("timeframe", "string"),
        FieldDef("implications", "list", default=[]),
    ],
))

_register(EntitySchema(
    entity_type="process",
    display_name="Process/Workflow",
    description="An AI development or deployment process",
    fields=[
        FieldDef("steps", "list", default=[]),
        FieldDef("tools_used", "list", default=[]),
        FieldDef("best_practices", "list", default=[]),
        FieldDef("common_pitfalls", "list", default=[]),
    ],
))


# ═══════════════════════════════════════════════════════════════════════════
# Schema utilities
# ═══════════════════════════════════════════════════════════════════════════

def get_schema(entity_type: str) -> EntitySchema | None:
    """Get schema for an entity type."""
    return ENTITY_SCHEMAS.get(entity_type)


def list_schemas() -> list[dict]:
    """List all available schemas."""
    return [
        {
            "type": s.entity_type,
            "display_name": s.display_name,
            "description": s.description,
            "required_fields": s.required_fields,
            "total_fields": len(s.fields),
        }
        for s in ENTITY_SCHEMAS.values()
    ]


def validate_entity(entity_type: str, attributes: dict) -> tuple[bool, list[str]]:
    """Validate entity attributes against its schema."""
    schema = ENTITY_SCHEMAS.get(entity_type)
    if not schema:
        return True, []  # No schema = no validation
    return schema.validate(attributes)


def enrich_entity(entity_type: str, attributes: dict) -> dict:
    """Apply schema defaults to entity attributes."""
    schema = ENTITY_SCHEMAS.get(entity_type)
    if not schema:
        return attributes
    return schema.apply_defaults(attributes)


def map_generic_type(generic_type: str) -> str:
    """Map a generic entity type to a specific schema type.

    E.g., "technology" → "framework", "organization" → "company"
    """
    mapping = {
        "technology": "framework",
        "organization": "company",
        "location": "event",  # Usually locations are mentioned in event context
        "market": "trend",
    }
    if generic_type in ENTITY_SCHEMAS:
        return generic_type
    return mapping.get(generic_type, generic_type)

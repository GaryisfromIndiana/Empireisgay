"""Entity Quality Score — 8-dimension quality rating for every piece of knowledge."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class EntityQualityScore:
    """8-dimension quality score for a knowledge entity."""
    entity_id: str = ""
    entity_name: str = ""

    # The 8 dimensions (all 0.0 - 1.0)
    source_reliability: float = 0.5    # How trustworthy is the source?
    recency: float = 0.5              # How recent is this information?
    corroboration: float = 0.5        # How many sources confirm this?
    completeness: float = 0.5         # How complete are the attributes?
    consistency: float = 0.5          # Does it align with related entities?
    citation_quality: float = 0.5     # How well-cited is the source?
    extraction_confidence: float = 0.5 # How confident was the extraction?
    update_frequency: float = 0.5     # How often is this entity reinforced?

    # Composite
    overall: float = 0.5

    def compute_overall(self) -> float:
        """Compute weighted overall score."""
        weights = {
            "source_reliability": 0.20,
            "recency": 0.15,
            "corroboration": 0.15,
            "completeness": 0.10,
            "consistency": 0.10,
            "citation_quality": 0.10,
            "extraction_confidence": 0.10,
            "update_frequency": 0.10,
        }
        score = (
            self.source_reliability * weights["source_reliability"] +
            self.recency * weights["recency"] +
            self.corroboration * weights["corroboration"] +
            self.completeness * weights["completeness"] +
            self.consistency * weights["consistency"] +
            self.citation_quality * weights["citation_quality"] +
            self.extraction_confidence * weights["extraction_confidence"] +
            self.update_frequency * weights["update_frequency"]
        )
        self.overall = round(score, 3)
        return self.overall

    def to_dict(self) -> dict:
        return {
            "source_reliability": self.source_reliability,
            "recency": self.recency,
            "corroboration": self.corroboration,
            "completeness": self.completeness,
            "consistency": self.consistency,
            "citation_quality": self.citation_quality,
            "extraction_confidence": self.extraction_confidence,
            "update_frequency": self.update_frequency,
            "overall": self.overall,
        }


class EntityQualityScorer:
    """Scores entities across 8 quality dimensions."""

    def __init__(self, empire_id: str = ""):
        self.empire_id = empire_id

    def score_entity(self, entity_id: str) -> EntityQualityScore:
        """Compute quality score for a single entity."""
        try:
            from db.engine import get_session
            from db.repositories.knowledge import KnowledgeRepository
            session = get_session()
            repo = KnowledgeRepository(session)

            entity = repo.get(entity_id)
            if not entity:
                return EntityQualityScore(entity_id=entity_id)

            attrs = entity.attributes_json or {}
            tags = entity.tags_json or []
            now = datetime.now(timezone.utc)

            qs = EntityQualityScore(entity_id=entity_id, entity_name=entity.name)

            # 1. Source reliability
            source_domain = ""
            for tag in tags:
                if "." in tag:
                    source_domain = tag
                    break
            if source_domain:
                from core.search.credibility import CredibilityScorer
                scorer = CredibilityScorer()
                cred = scorer.score(f"https://{source_domain}")
                qs.source_reliability = cred.score
            else:
                qs.source_reliability = 0.5

            # 2. Recency
            last_seen = attrs.get("last_seen", "")
            if last_seen:
                try:
                    seen_dt = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
                    age_days = (now - seen_dt).total_seconds() / 86400
                    if age_days < 1:
                        qs.recency = 1.0
                    elif age_days < 7:
                        qs.recency = 0.8
                    elif age_days < 30:
                        qs.recency = 0.6
                    elif age_days < 90:
                        qs.recency = 0.4
                    else:
                        qs.recency = 0.2
                except Exception:
                    qs.recency = 0.3
            elif entity.updated_at:
                age_days = (now - entity.updated_at).total_seconds() / 86400
                qs.recency = max(0.1, 1.0 - age_days / 90)
            else:
                qs.recency = 0.3

            # 3. Corroboration (how many times updated/seen)
            update_count = attrs.get("update_count", 0)
            if update_count >= 5:
                qs.corroboration = 1.0
            elif update_count >= 3:
                qs.corroboration = 0.8
            elif update_count >= 1:
                qs.corroboration = 0.6
            else:
                qs.corroboration = 0.3

            # 4. Completeness (how many schema fields are filled)
            from core.knowledge.schemas import get_schema
            schema = get_schema(entity.entity_type)
            if schema:
                total_fields = len(schema.fields)
                filled = sum(1 for f in schema.fields if f.name in attrs and attrs[f.name])
                qs.completeness = filled / max(total_fields, 1)
            else:
                # No schema — check how many attrs exist
                qs.completeness = min(1.0, len(attrs) / 5)

            # 5. Consistency (does it have contradicting info?)
            qs.consistency = 0.7  # Default — would need deeper analysis

            # 6. Citation quality
            has_url = bool(attrs.get("url") or attrs.get("source_url") or attrs.get("paper_url"))
            has_source = bool(attrs.get("source") or attrs.get("introduced_by") or attrs.get("created_by"))
            qs.citation_quality = 0.3
            if has_url:
                qs.citation_quality += 0.4
            if has_source:
                qs.citation_quality += 0.3

            # 7. Extraction confidence
            qs.extraction_confidence = entity.confidence

            # 8. Update frequency
            if entity.access_count >= 10:
                qs.update_frequency = 1.0
            elif entity.access_count >= 5:
                qs.update_frequency = 0.7
            elif entity.access_count >= 1:
                qs.update_frequency = 0.4
            else:
                qs.update_frequency = 0.2

            qs.compute_overall()

            # Store the quality score in entity attributes
            try:
                enriched = dict(attrs)
                enriched["quality_score"] = qs.to_dict()
                repo.update(entity_id, attributes_json=enriched)
                repo.commit()
            except Exception:
                pass

            return qs

        except Exception as e:
            logger.warning("Quality scoring failed for %s: %s", entity_id, e)
            return EntityQualityScore(entity_id=entity_id)

    def score_all(self, limit: int = 100) -> list[EntityQualityScore]:
        """Score all entities in the knowledge graph."""
        try:
            from db.engine import get_session
            from db.repositories.knowledge import KnowledgeRepository
            session = get_session()
            repo = KnowledgeRepository(session)

            entities = repo.get_by_empire(self.empire_id, limit=limit)
            scores = []
            for entity in entities:
                score = self.score_entity(entity.id)
                scores.append(score)

            scores.sort(key=lambda s: s.overall, reverse=True)
            return scores

        except Exception as e:
            logger.error("Batch scoring failed: %s", e)
            return []

    def get_low_quality(self, threshold: float = 0.4, limit: int = 20) -> list[EntityQualityScore]:
        """Find entities with low quality scores."""
        all_scores = self.score_all(limit=200)
        return [s for s in all_scores if s.overall < threshold][:limit]

    def get_quality_stats(self) -> dict:
        """Get aggregate quality statistics."""
        scores = self.score_all(limit=500)
        if not scores:
            return {"total": 0}

        return {
            "total": len(scores),
            "avg_overall": sum(s.overall for s in scores) / len(scores),
            "avg_source_reliability": sum(s.source_reliability for s in scores) / len(scores),
            "avg_recency": sum(s.recency for s in scores) / len(scores),
            "avg_corroboration": sum(s.corroboration for s in scores) / len(scores),
            "avg_completeness": sum(s.completeness for s in scores) / len(scores),
            "high_quality": sum(1 for s in scores if s.overall >= 0.7),
            "medium_quality": sum(1 for s in scores if 0.4 <= s.overall < 0.7),
            "low_quality": sum(1 for s in scores if s.overall < 0.4),
        }

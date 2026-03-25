"""Evolution cycle manager — orchestrates self-improvement cycles."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CycleResult:
    """Result of a full evolution cycle."""
    cycle_id: str = ""
    proposals_collected: int = 0
    reviewed: int = 0
    approved: int = 0
    rejected: int = 0
    applied: int = 0
    learnings: list[str] = field(default_factory=list)
    total_cost: float = 0.0
    duration_seconds: float = 0.0


@dataclass
class CycleStats:
    """Statistics about evolution cycles."""
    total_cycles: int = 0
    approval_rate: float = 0.0
    application_rate: float = 0.0
    avg_proposals: float = 0.0
    total_cost: float = 0.0


class EvolutionCycleManager:
    """Orchestrates the self-improvement cycle.

    The evolution cycle: collect → review → execute → learn → repeat.
    Lieutenants propose improvements, an expert model reviews them,
    approved proposals are executed, and outcomes feed back as learnings.
    """

    def __init__(self, empire_id: str = ""):
        self.empire_id = empire_id
        self._repo = None

    def _get_repo(self):
        """Get a fresh repository with its own session."""
        from db.engine import get_session
        from db.repositories.evolution import EvolutionRepository
        return EvolutionRepository(get_session())

    def should_run_cycle(self) -> bool:
        """Check if a new cycle should be started."""
        repo = self._get_repo()
        try:
            from config.settings import get_settings
            cooldown = get_settings().evolution.cooldown_hours
        except Exception:
            cooldown = 2
        return repo.should_run_cycle(self.empire_id, cooldown)

    def run_full_cycle(self) -> CycleResult:
        """Run a complete evolution cycle.

        1. Collect proposals from lieutenants
        2. Review proposals with expert model
        3. Execute approved proposals
        4. Extract learnings and feed back to memory

        Returns:
            CycleResult.
        """
        start_time = time.time()
        result = CycleResult()

        repo = self._get_repo()
        cycle = repo.create_cycle(self.empire_id)
        result.cycle_id = cycle.id

        logger.info("Starting evolution cycle %d for empire %s", cycle.cycle_number, self.empire_id)

        # 1. Collect proposals
        proposals = self._collect_proposals()
        result.proposals_collected = len(proposals)
        repo.update_cycle(cycle.id, status="reviewing", proposals_count=len(proposals))
        repo.commit()

        # 2. Review proposals
        reviewed = self._review_proposals(proposals)
        approved = [r for r in reviewed if r.get("recommendation") == "approve"]
        rejected = [r for r in reviewed if r.get("recommendation") == "reject"]
        result.reviewed = len(reviewed)
        result.approved = len(approved)
        result.rejected = len(rejected)

        repo.update_cycle(cycle.id, status="executing", approved_count=len(approved), rejected_count=len(rejected))
        repo.commit()

        # 3. Execute approved proposals
        executed = self._execute_approved(approved)
        result.applied = len(executed)
        repo.update_cycle(cycle.id, applied_count=len(executed))
        repo.commit()

        # 4. Extract learnings
        learnings = self._extract_learnings(proposals, reviewed, executed)
        result.learnings = learnings
        self._feed_back_to_memory(learnings)

        # Complete cycle
        result.duration_seconds = time.time() - start_time
        repo.complete_cycle(cycle.id, learnings=learnings, summary=f"Cycle {cycle.cycle_number}: {result.applied}/{result.proposals_collected} proposals applied")
        repo.commit()

        logger.info(
            "Evolution cycle %d complete: %d proposals, %d approved, %d applied",
            cycle.cycle_number, result.proposals_collected, result.approved, result.applied,
        )

        return result

    def _collect_proposals(self) -> list[dict]:
        """Collect improvement proposals from all lieutenants."""
        from core.lieutenant.manager import LieutenantManager

        lt_manager = LieutenantManager(self.empire_id)
        active_lts = lt_manager.list_lieutenants(status="active")

        proposals = []
        for lt_info in active_lts[:10]:
            lt = lt_manager.get_lieutenant(lt_info["id"])
            if lt:
                try:
                    proposal = lt.propose_upgrade()
                    if proposal.get("description"):
                        proposals.append(proposal)

                        # Save to DB
                        repo = self._get_repo()
                        repo.create(
                            empire_id=self.empire_id,
                            lieutenant_id=lt.id,
                            title=proposal.get("title", "Untitled"),
                            description=proposal.get("description", ""),
                            proposal_type="optimization",
                            confidence_score=proposal.get("confidence", 0.5),
                        )
                        repo.commit()
                except Exception as e:
                    logger.warning("Failed to collect proposal from %s: %s", lt.name, e)

        return proposals

    def _review_proposals(self, proposals: list[dict]) -> list[dict]:
        """Review proposals using an expert model."""
        from llm.base import LLMRequest, LLMMessage
        from llm.router import ModelRouter, TaskMetadata
        import json

        router = ModelRouter()
        reviews = []

        for proposal in proposals:
            prompt = f"""Review this system improvement proposal:

Title: {proposal.get('title', '')}
Description: {proposal.get('description', '')[:3000]}
Proposed by: {proposal.get('lieutenant_id', 'unknown')}
Confidence: {proposal.get('confidence', 0)}

Evaluate:
1. Quality and clarity of the proposal
2. Feasibility of implementation
3. Risk assessment
4. Expected impact

Respond as JSON:
{{
    "recommendation": "approve|reject|revise",
    "quality_score": 0.0-1.0,
    "risk_level": "low|medium|high",
    "notes": "...",
    "confidence": 0.0-1.0
}}
"""
            try:
                request = LLMRequest(
                    messages=[LLMMessage.user(prompt)],
                    system_prompt="You are an expert system reviewer. Be rigorous but fair.",
                    temperature=0.2,
                    max_tokens=1000,
                )
                response = router.execute(request, TaskMetadata(task_type="analysis", complexity="complex"))

                try:
                    review = json.loads(response.content)
                except json.JSONDecodeError:
                    from llm.schemas import _find_json_object
                    json_str = _find_json_object(response.content)
                    review = json.loads(json_str) if json_str else {"recommendation": "reject"}

                review["proposal"] = proposal
                reviews.append(review)

                # Update proposal in DB
                repo = self._get_repo()
                pending = repo.get_pending(self.empire_id, limit=1)
                if pending:
                    if review.get("recommendation") == "approve":
                        repo.approve_proposal(pending[0].id, notes=review.get("notes", ""), reviewer_model=response.model)
                    else:
                        repo.reject_proposal(pending[0].id, notes=review.get("notes", ""), reviewer_model=response.model)
                    repo.commit()

            except Exception as e:
                logger.warning("Failed to review proposal: %s", e)
                reviews.append({"recommendation": "reject", "proposal": proposal, "error": str(e)})

        return reviews

    def _execute_approved(self, approved: list[dict]) -> list[dict]:
        """Execute approved proposals."""
        executed = []
        for review in approved:
            proposal = review.get("proposal", {})
            try:
                # For now, store the execution record
                executed.append({
                    "title": proposal.get("title", ""),
                    "status": "applied",
                    "notes": review.get("notes", ""),
                })
            except Exception as e:
                logger.warning("Failed to execute proposal: %s", e)

        return executed

    def _extract_learnings(
        self,
        proposals: list[dict],
        reviews: list[dict],
        executed: list[dict],
    ) -> list[str]:
        """Extract learnings from the cycle."""
        learnings = []

        approved_rate = len([r for r in reviews if r.get("recommendation") == "approve"]) / max(len(reviews), 1)
        learnings.append(f"Cycle approval rate: {approved_rate:.0%}")

        for review in reviews:
            if review.get("notes"):
                learnings.append(f"Review insight: {review['notes'][:200]}")

        return learnings

    def _feed_back_to_memory(self, learnings: list[str]) -> None:
        """Store learnings in lieutenant memory."""
        from core.memory.manager import MemoryManager
        mm = MemoryManager(self.empire_id)
        for learning in learnings[:10]:
            mm.store(
                content=f"[Evolution] {learning}",
                memory_type="experiential",
                category="evolution",
                importance=0.7,
                tags=["evolution", "learning"],
                source_type="evolution",
            )

    def get_cycle_history(self, limit: int = 10) -> list[dict]:
        """Get recent cycle history."""
        repo = self._get_repo()
        cycles = repo.get_cycle_history(self.empire_id, limit)
        return [
            {
                "id": c.id,
                "cycle_number": c.cycle_number,
                "status": c.status,
                "proposals": c.proposals_count,
                "approved": c.approved_count,
                "applied": c.applied_count,
                "approval_rate": c.approval_rate,
                "cost": c.total_cost_usd,
                "completed_at": c.completed_at.isoformat() if c.completed_at else None,
            }
            for c in cycles
        ]

    def get_stats(self) -> CycleStats:
        """Get evolution statistics."""
        repo = self._get_repo()
        raw = repo.get_cycle_stats(self.empire_id)
        return CycleStats(
            total_cycles=raw.get("total_cycles", 0),
            approval_rate=raw.get("avg_approval_rate", 0),
            avg_proposals=raw.get("avg_proposals_per_cycle", 0),
            total_cost=raw.get("total_cost", 0),
        )

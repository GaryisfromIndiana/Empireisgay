"""Evolution executor — applies approved proposals and tracks outcomes."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """Result of applying a proposal."""
    proposal_id: str = ""
    proposal_title: str = ""
    status: str = "pending"  # pending, applied, failed, rolled_back
    changes_applied: list[dict] = field(default_factory=list)
    verification: dict = field(default_factory=dict)
    rollback_available: bool = True
    error: str = ""
    cost_usd: float = 0.0


@dataclass
class KnowledgeUpdateResult:
    """Result of applying a knowledge update proposal."""
    entities_added: int = 0
    entities_updated: int = 0
    relations_added: int = 0
    memories_stored: int = 0


@dataclass
class ProcessChangeResult:
    """Result of applying a process change."""
    settings_changed: list[str] = field(default_factory=list)
    parameters_updated: dict = field(default_factory=dict)
    applied: bool = False


@dataclass
class VerificationResult:
    """Result of verifying an applied proposal."""
    verified: bool = False
    checks_passed: int = 0
    checks_failed: int = 0
    issues: list[str] = field(default_factory=list)


@dataclass
class RollbackResult:
    """Result of rolling back a proposal."""
    rolled_back: bool = False
    changes_reverted: list[str] = field(default_factory=list)
    error: str = ""


class EvolutionExecutor:
    """Applies approved proposals and tracks outcomes.

    Handles knowledge updates, process changes, and configuration
    modifications. Supports rollback for failed applications.
    Feeds outcomes back into lieutenant memory as pre-digested rules.
    """

    def __init__(self, empire_id: str = ""):
        self.empire_id = empire_id
        self._applied: dict[str, dict] = {}  # proposal_id → state before change
        self._repo = None

    def _get_repo(self):
        """Get a fresh repository with its own session."""
        from db.engine import get_session
        from db.repositories.evolution import EvolutionRepository
        return EvolutionRepository(get_session())

    def execute_proposal(self, proposal: dict) -> ExecutionResult:
        """Apply a single approved proposal.

        Args:
            proposal: Proposal dict.

        Returns:
            ExecutionResult.
        """
        proposal_type = proposal.get("proposal_type", "optimization")
        result = ExecutionResult(
            proposal_id=proposal.get("id", ""),
            proposal_title=proposal.get("title", ""),
        )

        try:
            if proposal_type == "knowledge_update":
                kr = self.apply_knowledge_update(proposal)
                result.changes_applied = [{"type": "knowledge", "entities": kr.entities_added, "memories": kr.memories_stored}]
                result.status = "applied"

            elif proposal_type == "process_improvement":
                pr = self.apply_process_change(proposal)
                result.changes_applied = [{"type": "process", "settings": pr.settings_changed}]
                result.status = "applied" if pr.applied else "failed"

            else:
                # General proposals — store as learnings
                self._apply_as_learning(proposal)
                result.changes_applied = [{"type": "learning", "stored": True}]
                result.status = "applied"

            # Save state for rollback
            self._applied[result.proposal_id] = {
                "proposal": proposal,
                "changes": result.changes_applied,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            # Record in DB
            self._record_execution(result)

            # Feed back to memory
            self.feed_back_to_memory([result])

            logger.info("Applied proposal: %s", result.proposal_title)

        except Exception as e:
            result.status = "failed"
            result.error = str(e)
            logger.error("Failed to apply proposal %s: %s", result.proposal_title, e)

        return result

    def batch_execute(self, proposals: list[dict]) -> list[ExecutionResult]:
        """Execute multiple approved proposals.

        Args:
            proposals: List of proposal dicts.

        Returns:
            List of execution results.
        """
        results = []
        for proposal in proposals:
            result = self.execute_proposal(proposal)
            results.append(result)
            # Stop on failure if proposal has high risk
            if result.status == "failed" and proposal.get("risk_level") == "high":
                logger.warning("Stopping batch execution after high-risk failure")
                break
        return results

    def apply_knowledge_update(self, proposal: dict) -> KnowledgeUpdateResult:
        """Apply a knowledge update proposal.

        Adds new entities, relations, and memories based on the proposal.
        """
        result = KnowledgeUpdateResult()
        description = proposal.get("description", "")

        # Extract entities from proposal description
        try:
            from core.knowledge.entities import EntityExtractor
            extractor = EntityExtractor()
            extraction = extractor.extract_from_text(
                description,
                context=f"Evolution proposal: {proposal.get('title', '')}",
                max_entities=10,
            )

            if extraction.entities:
                from core.knowledge.graph import KnowledgeGraph
                graph = KnowledgeGraph(self.empire_id)
                for entity in extraction.entities:
                    graph.add_entity(
                        name=entity.get("name", ""),
                        entity_type=entity.get("entity_type", "concept"),
                        description=entity.get("description", ""),
                        confidence=entity.get("confidence", 0.7),
                    )
                    result.entities_added += 1

                for relation in extraction.relations:
                    graph.add_relation(
                        source_name=relation.get("source", ""),
                        target_name=relation.get("target", ""),
                        relation_type=relation.get("type", "related_to"),
                    )
                    result.relations_added += 1
        except Exception as e:
            logger.warning("Knowledge extraction from proposal failed: %s", e)

        # Store as semantic memory
        from core.memory.manager import MemoryManager
        mm = MemoryManager(self.empire_id)
        lieutenant_id = proposal.get("lieutenant_id", "")

        mm.store(
            content=f"[Knowledge Update] {proposal.get('title', '')}: {description[:1000]}",
            memory_type="semantic",
            lieutenant_id=lieutenant_id,
            title=f"Knowledge: {proposal.get('title', '')}",
            category="evolution_knowledge",
            importance=0.75,
            tags=["evolution", "knowledge_update"],
            source_type="evolution",
        )
        result.memories_stored += 1

        return result

    def apply_process_change(self, proposal: dict) -> ProcessChangeResult:
        """Apply a process change proposal.

        Updates system parameters or configurations.
        """
        result = ProcessChangeResult()

        # Process changes are stored as design memories
        # (actual config changes would need manual approval in production)
        from core.memory.manager import MemoryManager
        mm = MemoryManager(self.empire_id)

        mm.store(
            content=f"[Process Change] {proposal.get('title', '')}: {proposal.get('description', '')[:1000]}",
            memory_type="design",
            title=f"Process: {proposal.get('title', '')}",
            category="process_change",
            importance=0.8,
            tags=["evolution", "process_change"],
            source_type="evolution",
        )

        result.applied = True
        result.settings_changed = ["memory_stored"]
        return result

    def _apply_as_learning(self, proposal: dict) -> None:
        """Store a general proposal as a learning in memory."""
        from core.memory.manager import MemoryManager
        mm = MemoryManager(self.empire_id)
        lieutenant_id = proposal.get("lieutenant_id", "")

        # Store as experiential learning
        mm.store(
            content=(
                f"[Evolution Applied] {proposal.get('title', '')}\n"
                f"Type: {proposal.get('proposal_type', '')}\n"
                f"Rationale: {proposal.get('rationale', '')[:500]}\n"
                f"Description: {proposal.get('description', '')[:500]}"
            ),
            memory_type="experiential",
            lieutenant_id=lieutenant_id,
            title=f"Evolution: {proposal.get('title', '')}",
            category="evolution",
            importance=0.7,
            tags=["evolution", "applied", proposal.get("proposal_type", "")],
            source_type="evolution",
        )

    def rollback(self, proposal_id: str) -> RollbackResult:
        """Rollback a previously applied proposal.

        Args:
            proposal_id: ID of the proposal to rollback.

        Returns:
            RollbackResult.
        """
        state = self._applied.get(proposal_id)
        if not state:
            return RollbackResult(rolled_back=False, error="No rollback state found for this proposal")

        try:
            # Mark as rolled back in DB
            repo = self._get_repo()
            repo.mark_rolled_back(proposal_id)
            repo.commit()

            # Store rollback event in memory
            from core.memory.manager import MemoryManager
            mm = MemoryManager(self.empire_id)
            mm.store(
                content=f"[Rollback] Proposal '{state['proposal'].get('title', '')}' was rolled back",
                memory_type="experiential",
                category="evolution_rollback",
                importance=0.8,
                tags=["evolution", "rollback"],
                source_type="evolution",
            )

            del self._applied[proposal_id]

            return RollbackResult(
                rolled_back=True,
                changes_reverted=[str(c) for c in state.get("changes", [])],
            )

        except Exception as e:
            return RollbackResult(rolled_back=False, error=str(e))

    def verify_application(self, proposal_id: str) -> VerificationResult:
        """Verify that a proposal was applied correctly.

        Args:
            proposal_id: Proposal to verify.

        Returns:
            VerificationResult.
        """
        state = self._applied.get(proposal_id)
        if not state:
            return VerificationResult(verified=False, issues=["Proposal not found in applied state"])

        checks_passed = 0
        checks_failed = 0
        issues = []

        # Check that the changes were recorded
        changes = state.get("changes", [])
        if changes:
            checks_passed += 1
        else:
            checks_failed += 1
            issues.append("No changes recorded")

        # Check that memory was stored
        from core.memory.manager import MemoryManager
        mm = MemoryManager(self.empire_id)
        related = mm.recall(query=state["proposal"].get("title", ""), memory_types=["experiential", "semantic"], limit=1)
        if related:
            checks_passed += 1
        else:
            checks_failed += 1
            issues.append("No related memory found")

        return VerificationResult(
            verified=checks_failed == 0,
            checks_passed=checks_passed,
            checks_failed=checks_failed,
            issues=issues,
        )

    def record_outcome(self, proposal_id: str, outcome: dict) -> None:
        """Record the outcome of an applied proposal.

        Args:
            proposal_id: Proposal ID.
            outcome: Outcome data.
        """
        try:
            repo = self._get_repo()
            repo.update(proposal_id, application_result_json=outcome)
            repo.commit()
        except Exception as e:
            logger.warning("Failed to record outcome: %s", e)

    def feed_back_to_memory(self, results: list[ExecutionResult]) -> int:
        """Feed execution results back as pre-digested rules.

        Applied proposals become experiential rules that lieutenants
        can reference in future tasks.

        Args:
            results: Execution results.

        Returns:
            Number of memories stored.
        """
        from core.memory.manager import MemoryManager
        mm = MemoryManager(self.empire_id)
        stored = 0

        for result in results:
            if result.status == "applied":
                mm.store(
                    content=(
                        f"[Pre-digested Rule] Applied evolution: {result.proposal_title}\n"
                        f"Changes: {json.dumps(result.changes_applied, default=str)[:500]}\n"
                        f"This improvement was reviewed and approved. Apply this pattern in future work."
                    ),
                    memory_type="experiential",
                    category="evolution_rule",
                    importance=0.8,
                    tags=["evolution", "rule", "pre-digested"],
                    source_type="evolution",
                )
                stored += 1

            elif result.status == "failed":
                mm.store(
                    content=(
                        f"[Failed Evolution] Proposal '{result.proposal_title}' failed to apply.\n"
                        f"Error: {result.error}\n"
                        f"Avoid similar proposals or address the root cause first."
                    ),
                    memory_type="experiential",
                    category="evolution_failure",
                    importance=0.7,
                    tags=["evolution", "failure"],
                    source_type="evolution",
                )
                stored += 1

        return stored

    def get_execution_history(self) -> list[dict]:
        """Get history of applied proposals."""
        return [
            {
                "proposal_id": pid,
                "proposal_title": state["proposal"].get("title", ""),
                "changes": state.get("changes", []),
                "timestamp": state.get("timestamp", ""),
            }
            for pid, state in self._applied.items()
        ]

    def _record_execution(self, result: ExecutionResult) -> None:
        """Record execution result in DB."""
        try:
            repo = self._get_repo()
            if result.proposal_id:
                if result.status == "applied":
                    repo.mark_applied(result.proposal_id, {"changes": result.changes_applied})
                repo.commit()
        except Exception as e:
            logger.warning("Failed to record execution: %s", e)

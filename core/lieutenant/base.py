"""Base lieutenant class — a specialized AI agent powered by ACE."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from core.ace.engine import ACEEngine, ACEContext, TaskInput, TaskResult
from core.memory.manager import MemoryManager
from core.lieutenant.persona import PersonaConfig

logger = logging.getLogger(__name__)


@dataclass
class PerformanceStats:
    """Performance statistics for a lieutenant."""
    tasks_completed: int = 0
    tasks_failed: int = 0
    success_rate: float = 0.0
    avg_quality: float = 0.0
    avg_cost_per_task: float = 0.0
    total_cost: float = 0.0
    avg_execution_time: float = 0.0
    specialization_scores: dict[str, float] = field(default_factory=dict)


@dataclass
class KnowledgeGap:
    """An identified gap in the lieutenant's knowledge."""
    topic: str
    importance: float = 0.5
    suggested_research: list[str] = field(default_factory=list)


@dataclass
class DebateContribution:
    """A lieutenant's contribution to a war room debate."""
    lieutenant_id: str = ""
    lieutenant_name: str = ""
    position: str = ""
    arguments: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    confidence: float = 0.7
    counterpoints: list[str] = field(default_factory=list)


class Lieutenant:
    """A specialized AI agent with persona, domain expertise, and ACE engine.

    Each lieutenant runs the same ACE pipeline but with a unique persona
    that shapes its approach, analysis style, and domain focus.
    """

    def __init__(
        self,
        lieutenant_id: str,
        name: str,
        empire_id: str,
        persona: PersonaConfig,
        domain: str = "",
        ace_engine: ACEEngine | None = None,
    ):
        self.id = lieutenant_id
        self.name = name
        self.empire_id = empire_id
        self.persona = persona
        self.domain = domain or persona.domain
        self.ace = ace_engine or ACEEngine(
            empire_id=empire_id,
            lieutenant_id=lieutenant_id,
        )
        self.memory = MemoryManager(empire_id)

        # Internal tracking
        self._tasks_completed = 0
        self._tasks_failed = 0
        self._total_cost = 0.0
        self._quality_scores: list[float] = []
        self._execution_times: list[float] = []

    def execute_task(self, task: TaskInput) -> TaskResult:
        """Execute a task using the ACE pipeline with persona context.

        Args:
            task: Task to execute.

        Returns:
            TaskResult.
        """
        context = self._build_context(task)

        logger.info("[%s] Executing task: %s", self.name, task.title)
        start = time.time()
        result = self.ace.execute_task(task, context)
        duration = time.time() - start

        # Track metrics
        if result.success:
            self._tasks_completed += 1
        else:
            self._tasks_failed += 1

        self._total_cost += result.cost_usd
        if result.quality_score > 0:
            self._quality_scores.append(result.quality_score)
        self._execution_times.append(duration)

        # Store task outcome in memory (best-effort — don't crash directive on DB error)
        try:
            self.memory.store_task_outcome(
                task_id=task.id,
                task_title=task.title,
                outcome=result.content[:1000],
                success=result.success,
                lieutenant_id=self.id,
            )
        except Exception as e:
            logger.warning("[%s] Failed to store task outcome: %s", self.name, e)

        # Extract entities for knowledge graph (best-effort)
        try:
            self._extract_knowledge(result)
        except Exception as e:
            logger.warning("[%s] Failed to extract knowledge: %s", self.name, e)

        # Memory feedback: boost memories that contributed to good outcomes
        try:
            self._feedback_memories(task, result)
        except Exception as e:
            logger.debug("[%s] Memory feedback failed: %s", self.name, e)

        # Update lieutenant DB record (performance, cost, last_active)
        try:
            from db.engine import session_scope
            from db.models import Lieutenant as LtModel
            from datetime import datetime, timezone as tz

            with session_scope() as session:
                db_lt = session.get(LtModel, self.id)
                if db_lt:
                    if result.success:
                        db_lt.tasks_completed += 1
                    else:
                        db_lt.tasks_failed += 1
                    db_lt.total_cost_usd += result.cost_usd
                    db_lt.last_active_at = datetime.now(tz.utc)

                    # Rolling average quality
                    total = db_lt.tasks_completed + db_lt.tasks_failed
                    if result.quality_score > 0 and total > 0:
                        db_lt.avg_quality_score = (
                            (db_lt.avg_quality_score * (total - 1) + result.quality_score) / total
                        )

                    # Recalculate performance score
                    success_rate = db_lt.tasks_completed / total if total > 0 else 0.5
                    quality_factor = db_lt.avg_quality_score if db_lt.avg_quality_score > 0 else 0.5
                    db_lt.performance_score = min(1.0, success_rate * 0.4 + quality_factor * 0.6)

                    db_lt.avg_execution_time = (
                        (db_lt.avg_execution_time * (total - 1) + duration) / total
                    ) if total > 0 else duration
        except Exception as e:
            logger.debug("[%s] Failed to update DB record: %s", self.name, e)

        logger.info(
            "[%s] Task %s: %s (quality=%.2f, cost=$%.4f)",
            self.name, task.title,
            "SUCCESS" if result.success else "FAILED",
            result.quality_score, result.cost_usd,
        )

        return result

    def execute_batch(self, tasks: list[TaskInput]) -> list[TaskResult]:
        """Execute multiple tasks."""
        return [self.execute_task(task) for task in tasks]

    def research(self, topic: str, depth: str = "standard") -> TaskResult:
        """Conduct autonomous research on a topic.

        Args:
            topic: Research topic.
            depth: Research depth (shallow, standard, deep).

        Returns:
            TaskResult with research findings.
        """
        task = TaskInput(
            title=f"Research: {topic}",
            description=f"Conduct {depth} research on: {topic}. "
                        f"Focus on {self.domain} perspectives. "
                        f"Identify key facts, trends, and knowledge gaps.",
            task_type="research",
            max_tokens=6000 if depth == "deep" else 4000,
        )
        return self.execute_task(task)

    def analyze(self, data: str, framework: str = "") -> TaskResult:
        """Conduct domain-specific analysis.

        Args:
            data: Data to analyze.
            framework: Analysis framework to use.

        Returns:
            TaskResult with analysis.
        """
        task = TaskInput(
            title="Analysis",
            description=f"Analyze the following from a {self.domain} perspective:\n\n{data[:4000]}",
            task_type="analysis",
            input_data={"framework": framework} if framework else {},
            max_tokens=5000,
        )
        return self.execute_task(task)

    def propose_upgrade(self, system_context: str = "") -> dict:
        """Propose a system improvement based on domain knowledge.

        Args:
            system_context: Current system context.

        Returns:
            Proposal dict.
        """
        task = TaskInput(
            title="Evolution Proposal",
            description=(
                f"Based on your expertise in {self.domain}, "
                f"propose a specific improvement to the system.\n\n"
                f"System context: {system_context[:2000]}\n\n"
                f"Consider your recent learnings and identify one concrete "
                f"improvement that would make the system better."
            ),
            task_type="analysis",
            max_tokens=3000,
        )
        result = self.execute_task(task)
        return {
            "title": f"Proposal from {self.name}",
            "description": result.content,
            "lieutenant_id": self.id,
            "confidence": result.quality_score,
        }

    def reflect(self, task_results: list[TaskResult]) -> list[str]:
        """Extract learnings from completed work.

        Args:
            task_results: Recent task results.

        Returns:
            List of learnings.
        """
        from core.memory.experiential import ExperientialMemory
        exp_mem = ExperientialMemory(self.memory, self.id)

        all_learnings = []
        for result in task_results:
            learnings = exp_mem.extract_learnings(result.to_dict())
            for learning in learnings:
                exp_mem.store_lesson(learning)
                all_learnings.append(learning.content)

        return all_learnings

    def assess_knowledge_gaps(self) -> list[KnowledgeGap]:
        """Identify what this lieutenant doesn't know.

        Returns:
            List of knowledge gaps.
        """
        from core.knowledge.maintenance import KnowledgeMaintainer
        maintainer = KnowledgeMaintainer(self.empire_id)
        gaps = maintainer.suggest_gaps(self.domain)

        return [
            KnowledgeGap(
                topic=g.topic,
                importance=g.importance,
                suggested_research=g.suggested_queries,
            )
            for g in gaps
        ]

    def run_learning_cycle(self) -> dict:
        """Run an autonomous learning cycle.

        1. Assess knowledge gaps
        2. Research the most important gaps
        3. Store findings in memory and knowledge graph

        Returns:
            Cycle results.
        """
        logger.info("[%s] Starting learning cycle", self.name)

        # 1. Assess gaps
        gaps = self.assess_knowledge_gaps()
        if not gaps:
            logger.info("[%s] No knowledge gaps identified", self.name)
            return {"gaps_found": 0, "researched": 0}

        # 2. Research top gaps
        researched = 0
        for gap in gaps[:3]:  # Top 3 gaps
            result = self.research(gap.topic)
            if result.success:
                researched += 1

        logger.info("[%s] Learning cycle complete: %d gaps, %d researched", self.name, len(gaps), researched)
        return {"gaps_found": len(gaps), "researched": researched}

    def participate_in_debate(self, topic: str, position: str = "") -> DebateContribution:
        """Participate in a war room debate.

        Args:
            topic: Debate topic.
            position: Optional pre-assigned position.

        Returns:
            DebateContribution.
        """
        task = TaskInput(
            title=f"Debate: {topic}",
            description=(
                f"Topic: {topic}\n"
                f"{'Position: ' + position if position else 'Take the position most aligned with your expertise.'}\n\n"
                f"Provide:\n"
                f"1. Your position on this topic\n"
                f"2. Key arguments supporting your position\n"
                f"3. Evidence or reasoning\n"
                f"4. Potential counterarguments and your rebuttals\n"
                f"5. Your confidence level (0-1)"
            ),
            task_type="analysis",
            max_tokens=3000,
        )
        result = self.execute_task(task)

        return DebateContribution(
            lieutenant_id=self.id,
            lieutenant_name=self.name,
            position=position or "See arguments",
            arguments=[result.content[:2000]],
            confidence=result.quality_score,
        )

    def get_performance_stats(self) -> PerformanceStats:
        """Get current performance statistics."""
        total = self._tasks_completed + self._tasks_failed
        return PerformanceStats(
            tasks_completed=self._tasks_completed,
            tasks_failed=self._tasks_failed,
            success_rate=self._tasks_completed / total if total > 0 else 0.0,
            avg_quality=sum(self._quality_scores) / len(self._quality_scores) if self._quality_scores else 0.0,
            avg_cost_per_task=self._total_cost / total if total > 0 else 0.0,
            total_cost=self._total_cost,
            avg_execution_time=sum(self._execution_times) / len(self._execution_times) if self._execution_times else 0.0,
        )

    def _build_context(self, task: TaskInput) -> ACEContext:
        """Build ACE context with persona, task-relevant memories, and knowledge graph."""
        task_query = f"{task.title} {task.description[:200]}"

        # Get task-relevant memories using context window builder
        memory_context = ""
        try:
            memory_context = self.memory.get_context_window(
                query=task_query,
                lieutenant_id=self.id,
                token_budget=3000,
                include_types=["semantic", "experiential", "design", "episodic"],
            )
        except Exception as e:
            logger.debug("[%s] Memory context build failed: %s", self.name, e)

        # Get relevant knowledge graph entities (lightweight — no neighbor traversal)
        knowledge_context = ""
        try:
            from core.knowledge.graph import KnowledgeGraph
            graph = KnowledgeGraph(self.empire_id)
            entities = graph.find_entities(query=task_query[:100], limit=5)
            if entities:
                kg_parts = [
                    f"- {e.name} ({e.entity_type}): {e.description[:150]}"
                    for e in entities
                ]
                knowledge_context = "## Known Entities\n" + "\n".join(kg_parts)
        except Exception:
            pass

        # Build the full context
        context_parts = [self.persona.build_system_prompt()]
        context_parts.append(f"\nDomain: {self.domain}")

        if memory_context:
            context_parts.append(f"\n{memory_context}")
        if knowledge_context:
            context_parts.append(f"\n{knowledge_context}")

        context = ACEContext(
            persona_prompt="\n".join(context_parts),
            domain_context=f"Domain: {self.domain}",
            metadata={"task_query": task_query[:200]},
        )

        return context

    def _feedback_memories(self, task: TaskInput, result: TaskResult) -> None:
        """Update memory importance based on task outcome.

        If a task succeeds with high quality, boost the memories that were
        used in its context. If it fails, slightly reduce them.
        This creates a reinforcement loop — useful memories get stronger.
        """
        task_query = f"{task.title} {task.description[:200]}"

        # Find memories that were likely used in this task's context
        related = self.memory.recall(
            query=task_query,
            memory_types=["semantic", "experiential"],
            lieutenant_id=self.id,
            limit=5,
        )

        if not related:
            return

        from db.engine import session_scope
        from db.models import MemoryEntry

        boost = 0.0
        if result.success and result.quality_score >= 0.7:
            boost = 0.05  # Good outcome → boost memories
        elif result.success and result.quality_score >= 0.5:
            boost = 0.02  # OK outcome → slight boost
        elif not result.success:
            boost = -0.03  # Failed → slight reduction

        if boost == 0.0:
            return

        try:
            with session_scope() as session:
                for mem in related:
                    mem_id = mem.get("id")
                    if mem_id:
                        db_mem = session.get(MemoryEntry, mem_id)
                        if db_mem:
                            new_importance = max(0.1, min(1.0, db_mem.importance_score + boost))
                            db_mem.importance_score = new_importance
                            db_mem.effective_importance = new_importance * db_mem.decay_factor

            logger.debug(
                "[%s] Memory feedback: %+.2f to %d memories (quality=%.2f)",
                self.name, boost, len(related), result.quality_score,
            )
        except Exception:
            pass  # Best-effort

    def _extract_knowledge(self, result: TaskResult) -> None:
        """Extract entities from task results into knowledge graph."""
        if not result.success or not result.content:
            return
        # Skip extraction for very short content (not worth the LLM call)
        if len(result.content) < 200:
            return

        try:
            from core.knowledge.entities import EntityExtractor
            extractor = EntityExtractor()
            extraction = extractor.extract_from_text(
                result.content[:4000],
                context=f"Domain: {self.domain}",
                max_entities=10,
            )

            if extraction.entities:
                from core.knowledge.graph import KnowledgeGraph
                from core.knowledge.resolution import EntityResolver
                from core.knowledge.schemas import map_generic_type

                graph = KnowledgeGraph(self.empire_id)
                resolver = EntityResolver(self.empire_id)

                # Add all entities with resolution and schema mapping
                added_names = set()
                for entity in extraction.entities:
                    name = entity.get("name", "").strip()
                    if not name:
                        continue

                    # Map generic type to schema type
                    raw_type = entity.get("entity_type", "concept")
                    mapped_type = map_generic_type(raw_type)

                    # Resolve against existing entities (fuzzy dedup)
                    resolution = resolver.resolve(name, mapped_type)
                    if resolution.resolved and resolution.match and resolution.match.match_stage <= 2:
                        # Exact or normalized match — update existing
                        name = resolution.match.existing_name  # Use canonical name

                    graph.add_entity(
                        name=name,
                        entity_type=mapped_type,
                        description=entity.get("description", ""),
                        confidence=entity.get("confidence", 0.7),
                        source_task_id=result.task_id,
                    )
                    added_names.add(name.lower())

                # Only create relations where both entities exist
                for relation in extraction.relations:
                    source = relation.get("source", "").strip()
                    target = relation.get("target", "").strip()
                    if source.lower() in added_names and target.lower() in added_names:
                        graph.add_relation(
                            source_name=source,
                            target_name=target,
                            relation_type=relation.get("type", "related_to"),
                        )
        except Exception as e:
            logger.debug("Knowledge extraction failed: %s", e)

    def serialize(self) -> dict:
        """Export lieutenant state for persistence or sharing."""
        return {
            "id": self.id,
            "name": self.name,
            "empire_id": self.empire_id,
            "domain": self.domain,
            "persona": self.persona.to_dict(),
            "stats": self.get_performance_stats().__dict__,
        }

    @classmethod
    def deserialize(cls, data: dict, ace_engine: ACEEngine | None = None) -> Lieutenant:
        """Restore from serialized state."""
        persona = PersonaConfig.from_dict(data.get("persona", {}))
        return cls(
            lieutenant_id=data.get("id", ""),
            name=data.get("name", ""),
            empire_id=data.get("empire_id", ""),
            persona=persona,
            domain=data.get("domain", ""),
            ace_engine=ace_engine,
        )

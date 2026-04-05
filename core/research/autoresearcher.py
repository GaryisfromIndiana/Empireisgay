"""AutoResearcher — the main orchestrator for autonomous research cycles.

Pipeline:
  1. Detect knowledge gaps per lieutenant domain
  2. Generate targeted research questions (LLM)
  3. Execute multi-step research (search -> scrape -> extract -> verify)
  4. Synthesize findings into structured knowledge (LLM)
  5. Store in memory + knowledge graph
  6. Record what worked for next cycle

This replaces/upgrades the simple AutonomousResearchJob and
IntelligenceSweep with a true closed-loop system.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ResearchFinding:
    """A single finding from a research step."""

    title: str = ""
    content: str = ""
    source_url: str = ""
    source_name: str = ""
    confidence: float = 0.5
    importance: float = 0.5
    entity_type: str = ""
    entities_extracted: list[dict] = field(default_factory=list)
    is_novel: bool = True
    question_id: str = ""


@dataclass
class ResearchStepResult:
    """Result from executing a single research question."""

    question_id: str = ""
    question_text: str = ""
    domain: str = ""
    lieutenant_id: str = ""
    findings: list[ResearchFinding] = field(default_factory=list)
    sources_searched: int = 0
    pages_scraped: int = 0
    entities_extracted: int = 0
    memories_stored: int = 0
    novel_findings: int = 0
    cost_usd: float = 0.0
    duration_seconds: float = 0.0
    strategy_used: str = ""
    success: bool = False
    error: str = ""


@dataclass
class ResearchCycleResult:
    """Result of a full AutoResearch cycle."""

    cycle_id: str = ""
    gaps_detected: int = 0
    questions_generated: int = 0
    questions_researched: int = 0
    total_findings: int = 0
    novel_findings: int = 0
    entities_extracted: int = 0
    memories_stored: int = 0
    synthesis_reports: int = 0
    total_cost_usd: float = 0.0
    duration_seconds: float = 0.0
    step_results: list[ResearchStepResult] = field(default_factory=list)
    domains_covered: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "cycle_id": self.cycle_id,
            "gaps_detected": self.gaps_detected,
            "questions_generated": self.questions_generated,
            "questions_researched": self.questions_researched,
            "total_findings": self.total_findings,
            "novel_findings": self.novel_findings,
            "entities_extracted": self.entities_extracted,
            "memories_stored": self.memories_stored,
            "synthesis_reports": self.synthesis_reports,
            "total_cost_usd": self.total_cost_usd,
            "duration_seconds": self.duration_seconds,
            "domains_covered": self.domains_covered,
            "errors": self.errors[:10],
        }


# ---------------------------------------------------------------------------
# AutoResearcher
# ---------------------------------------------------------------------------

class AutoResearcher:
    """Closed-loop autonomous research engine.

    Ties together gap detection, question generation, multi-step research,
    entity extraction, synthesis, and strategy learning.
    """

    # Guard-rails
    MAX_QUESTIONS_PER_CYCLE = 6
    MAX_QUESTIONS_PER_DOMAIN = 2
    MAX_SCRAPES_PER_QUESTION = 3
    MAX_COST_PER_CYCLE_USD = 0.50
    MIN_FINDING_CONFIDENCE = 0.3

    def __init__(self, empire_id: str):
        self.empire_id = empire_id

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_cycle(
        self,
        domains: list[str] | None = None,
        max_questions: int | None = None,
    ) -> ResearchCycleResult:
        """Run a full autonomous research cycle.

        Args:
            domains: Restrict to specific domains (default: all active).
            max_questions: Override MAX_QUESTIONS_PER_CYCLE.

        Returns:
            ResearchCycleResult with everything that happened.
        """
        from utils.crypto import generate_id

        start = time.time()
        cap = min(max_questions or self.MAX_QUESTIONS_PER_CYCLE, self.MAX_QUESTIONS_PER_CYCLE)
        result = ResearchCycleResult(cycle_id=generate_id("research"))

        try:
            if not self._check_budget():
                result.errors.append("Budget limit reached — skipping research cycle")
                result.duration_seconds = time.time() - start
                return result

            # Step 1: Detect gaps across lieutenant domains
            gaps_by_domain = self._detect_gaps(domains)
            result.gaps_detected = sum(len(g) for g in gaps_by_domain.values())
            result.domains_covered = list(gaps_by_domain.keys())

            if result.gaps_detected == 0:
                logger.info("No knowledge gaps detected — nothing to research")
                result.duration_seconds = time.time() - start
                return result

            # Step 2: Generate research questions from gaps
            from core.research.questions import ResearchQuestionGenerator
            qgen = ResearchQuestionGenerator(self.empire_id)
            questions = qgen.generate_from_gaps(
                gaps_by_domain,
                max_per_domain=self.MAX_QUESTIONS_PER_DOMAIN,
                max_total=cap,
            )
            result.questions_generated = len(questions)

            if not questions:
                logger.info("No research questions generated")
                result.duration_seconds = time.time() - start
                return result

            # Step 3: Execute research for each question
            for question in questions:
                if result.total_cost_usd >= self.MAX_COST_PER_CYCLE_USD:
                    logger.info("Cost cap reached ($%.3f) — stopping research", result.total_cost_usd)
                    break

                step = self._execute_research(question)
                result.step_results.append(step)
                result.questions_researched += 1
                result.total_cost_usd += step.cost_usd

                if step.success:
                    result.total_findings += len(step.findings)
                    result.novel_findings += step.novel_findings
                    result.entities_extracted += step.entities_extracted
                    result.memories_stored += step.memories_stored
                else:
                    result.errors.append(step.error)

            # Step 4: Synthesize findings into per-domain research reports
            if result.novel_findings > 0:
                reports, synthesis_cost = self._synthesize(result)
                result.synthesis_reports = reports
                result.total_cost_usd += synthesis_cost

            # Step 5: Update strategy tracker
            self._update_strategies(result)

            # Step 6: Emit events
            self._emit_events(result)

        except Exception as exc:
            result.errors.append(str(exc))
            logger.error("AutoResearch cycle failed: %s", exc)

        result.duration_seconds = time.time() - start
        logger.info(
            "AutoResearch cycle %s complete: %d questions -> %d findings (%d novel), "
            "%d entities, $%.4f in %.1fs",
            result.cycle_id, result.questions_researched, result.total_findings,
            result.novel_findings, result.entities_extracted, result.total_cost_usd,
            result.duration_seconds,
        )
        return result

    # ------------------------------------------------------------------
    # Step 1: Gap detection
    # ------------------------------------------------------------------

    def _detect_gaps(self, domains: list[str] | None = None) -> dict[str, list]:
        """Detect knowledge gaps per domain."""
        from core.knowledge.maintenance import KnowledgeMaintainer
        from db.engine import get_engine, read_session
        from db.repositories.lieutenant import LieutenantRepository

        maintainer = KnowledgeMaintainer(self.empire_id)

        with read_session(get_engine()) as session:
            repo = LieutenantRepository(session)
            active = repo.get_active(self.empire_id)
            if domains:
                active = [lt for lt in active if lt.domain in domains]
            domain_list = [(lt.domain, lt.id) for lt in active if lt.domain]

        gaps_by_domain: dict[str, list] = {}
        for domain, _lt_id in domain_list:
            try:
                gaps = maintainer.suggest_gaps(domain=domain)
                if gaps:
                    gaps_by_domain[domain] = gaps
                    logger.debug("Domain '%s': %d gaps found", domain, len(gaps))
            except Exception as exc:
                logger.warning("Gap detection failed for domain '%s': %s", domain, exc)

        return gaps_by_domain

    # ------------------------------------------------------------------
    # Step 3: Execute research per question
    # ------------------------------------------------------------------

    def _execute_research(self, question: Any) -> ResearchStepResult:
        """Execute a multi-step research pipeline for one question.

        Creates a Task row linked to the assigned lieutenant, so autonomous
        research shows up in the task/cost tracking system instead of running
        as a ghost pipeline.

        Task lifecycle is guaranteed: the finally block ensures every task
        row ends in 'completed' or 'failed', never stuck in 'executing'.
        """
        from core.research.questions import ResearchQuestion

        q: ResearchQuestion = question
        start = time.time()
        step = ResearchStepResult(
            question_id=q.question_id,
            question_text=q.question,
            domain=q.domain,
            lieutenant_id=q.lieutenant_id,
            strategy_used=q.strategy,
        )

        # Create Task row so this research is visible in the task system
        task_id = self._create_task(q)
        task_finalized = False

        try:
            # A. Search
            findings = self._search_phase(q)
            step.sources_searched = len(findings)

            # B. Scrape top results for deeper content
            scraped = self._scrape_phase(findings)
            step.pages_scraped = len(scraped)
            findings.extend(scraped)

            # C. Novelty filter
            novel = self._novelty_filter(findings)
            step.novel_findings = len(novel)

            # D. Extract entities from novel findings
            entities, extraction_cost, extraction_tokens, model_used = self._extract_entities(novel, q.domain)
            step.entities_extracted = len(entities)
            step.cost_usd += extraction_cost

            # E. Store findings in memory and knowledge graph
            stored = self._store_findings(novel, entities, q, source_task_id=task_id)
            step.memories_stored = stored

            step.findings = novel
            step.success = True

            # Mark task complete and update lieutenant + empire stats
            step.duration_seconds = time.time() - start
            self._complete_task(
                task_id=task_id,
                step=step,
                quality_score=self._estimate_step_quality(step),
                tokens=extraction_tokens,
                model_used=model_used,
            )
            task_finalized = True

        except Exception as exc:
            step.error = str(exc)
            logger.error("Research step failed for '%s': %s", q.question[:60], exc)
            self._fail_task(task_id, str(exc))
            task_finalized = True

        finally:
            # Catch-all: if neither complete nor fail ran (e.g., _complete_task
            # itself threw), fail the task so it never stays stuck in 'executing'.
            if not task_finalized:
                self._fail_task(task_id, f"Task finalization failed after {time.time() - start:.1f}s")

        step.duration_seconds = time.time() - start
        return step

    def _create_task(self, q: Any) -> str | None:
        """Create a Task row for this research question. Returns task_id or None."""
        try:
            from db.engine import repo_scope
            from db.repositories.task import TaskRepository

            with repo_scope(TaskRepository) as repo:
                task = repo.create(
                    lieutenant_id=q.lieutenant_id or None,
                    title=f"Research: {q.question[:180]}",
                    description=q.question,
                    task_type="research",
                    status="executing",
                    started_at=datetime.now(timezone.utc),
                    pipeline_stage="executing",
                    input_json={
                        "question_id": q.question_id,
                        "domain": q.domain,
                        "strategy": q.strategy,
                        "search_queries": q.search_queries[:3],
                    },
                )
                repo.commit()
                return task.id
        except Exception as e:
            logger.error("Failed to create research task: %s", e)
            return None

    def _complete_task(
        self,
        task_id: str | None,
        step: ResearchStepResult,
        quality_score: float,
        tokens: int,
        model_used: str,
    ) -> None:
        """Mark task complete and cascade stats to lieutenant and empire."""
        if not task_id:
            return
        try:
            from db.engine import repo_scope
            from db.repositories.task import TaskRepository
            from db.repositories.lieutenant import LieutenantRepository
            from db.repositories.empire import EmpireRepository

            with repo_scope(TaskRepository) as repo:
                repo.complete_task(
                    task_id=task_id,
                    output={
                        "findings_count": len(step.findings),
                        "novel_findings": step.novel_findings,
                        "entities_extracted": step.entities_extracted,
                        "memories_stored": step.memories_stored,
                        "sources_searched": step.sources_searched,
                        "pages_scraped": step.pages_scraped,
                        "finding_titles": [f.title[:120] for f in step.findings[:10]],
                    },
                    quality_score=quality_score,
                    tokens_output=tokens,
                    cost_usd=step.cost_usd,
                    model_used=model_used or None,
                )
                repo.commit()

            # Update lieutenant performance
            if step.lieutenant_id:
                with repo_scope(LieutenantRepository) as lt_repo:
                    lt_repo.update_performance(
                        lieutenant_id=step.lieutenant_id,
                        task_succeeded=True,
                        quality_score=quality_score,
                        cost_usd=step.cost_usd,
                        execution_time=step.duration_seconds,
                    )
                    lt_repo.commit()

            # Update empire aggregate stats
            with repo_scope(EmpireRepository) as e_repo:
                e_repo.increment_stats(
                    empire_id=self.empire_id,
                    tasks_completed=1,
                    cost_usd=step.cost_usd,
                    knowledge_entries=step.entities_extracted,
                )
                e_repo.commit()
        except Exception as e:
            logger.error("Failed to complete task %s: %s", task_id, e)

    def _fail_task(self, task_id: str | None, error: str) -> None:
        """Mark task as failed and update lieutenant failure count."""
        if not task_id:
            return
        try:
            from db.engine import repo_scope
            from db.repositories.task import TaskRepository
            from db.repositories.lieutenant import LieutenantRepository

            with repo_scope(TaskRepository) as repo:
                task = repo.fail_task(task_id, error, increment_retry=False)
                repo.commit()

            if task and task.lieutenant_id:
                with repo_scope(LieutenantRepository) as lt_repo:
                    lt_repo.update_performance(
                        lieutenant_id=task.lieutenant_id,
                        task_succeeded=False,
                    )
                    lt_repo.commit()
        except Exception as e:
            logger.error("Failed to record task failure for %s: %s", task_id, e)

    def _estimate_step_quality(self, step: ResearchStepResult) -> float:
        """Heuristic quality score for a research step.

        Real critic evaluation doesn't happen here (autoresearcher bypasses ACE),
        so we score on outcome density: novel findings + entities extracted per source.
        """
        if step.sources_searched == 0:
            return 0.0
        novelty_ratio = step.novel_findings / max(step.sources_searched, 1)
        entity_density = min(1.0, step.entities_extracted / 10.0)
        storage_success = 1.0 if step.memories_stored > 0 else 0.0
        return round(0.4 * novelty_ratio + 0.4 * entity_density + 0.2 * storage_success, 3)

    def _search_phase(self, question: Any) -> list[ResearchFinding]:
        """Search the web using the question's search queries."""
        from core.search.web import WebSearcher
        from core.research.questions import ResearchQuestion

        q: ResearchQuestion = question
        searcher = WebSearcher(self.empire_id)
        findings: list[ResearchFinding] = []

        for query in q.search_queries[:3]:
            try:
                results = searcher.search(query, max_results=5)
                for r in results.results:
                    findings.append(ResearchFinding(
                        title=r.title,
                        content=r.snippet,
                        source_url=r.url,
                        source_name=r.source,
                        confidence=self._estimate_confidence(r.source),
                        importance=q.importance,
                        question_id=q.question_id,
                    ))
            except Exception as exc:
                logger.warning("Search failed for '%s': %s", query[:60], exc)

        return findings

    def _scrape_phase(self, findings: list[ResearchFinding]) -> list[ResearchFinding]:
        """Scrape the top search results for deeper content."""
        from core.search.scraper import WebScraper

        scraper = WebScraper(self.empire_id)
        scraped: list[ResearchFinding] = []

        ranked = sorted(findings, key=lambda f: f.confidence, reverse=True)

        for finding in ranked[:self.MAX_SCRAPES_PER_QUESTION]:
            if not finding.source_url:
                continue
            try:
                result = scraper.scrape_and_store(finding.source_url)
                if result.get("success") and result.get("content"):
                    scraped.append(ResearchFinding(
                        title=result.get("title", finding.title),
                        content=result["content"][:3000],
                        source_url=finding.source_url,
                        source_name=finding.source_name,
                        confidence=finding.confidence + 0.1,
                        importance=finding.importance,
                        question_id=finding.question_id,
                    ))
            except Exception as exc:
                logger.warning("Scrape failed for %s: %s", finding.source_url, exc)

        return scraped

    def _novelty_filter(self, findings: list[ResearchFinding]) -> list[ResearchFinding]:
        """Filter out findings that duplicate existing knowledge."""
        from core.search.sweep import IntelligenceSweep

        sweep = IntelligenceSweep(self.empire_id)
        novel: list[ResearchFinding] = []

        seen_titles: set[str] = set()
        for finding in findings:
            if finding.confidence < self.MIN_FINDING_CONFIDENCE:
                continue

            title_key = finding.title.lower().strip()[:60]
            if title_key in seen_titles:
                continue
            seen_titles.add(title_key)

            from core.search.sweep import Discovery
            disc = Discovery(
                title=finding.title,
                content=finding.content[:500],
                source_url=finding.source_url,
            )
            if sweep._is_novel(disc):
                finding.is_novel = True
                novel.append(finding)

        return novel

    def _extract_entities(
        self, findings: list[ResearchFinding], domain: str
    ) -> tuple[list[dict], float, int, str]:
        """Use LLM to extract knowledge entities from research findings.

        Returns (entities, cost_usd, tokens_output, model_used).
        """
        if not findings:
            return [], 0.0, 0, ""

        from llm.router import ModelRouter, TaskMetadata
        from llm.base import LLMRequest, LLMMessage

        context = "\n\n".join(
            f"### {f.title}\n{f.content[:800]}\n(Source: {f.source_name})"
            for f in findings[:5]
        )

        prompt = f"""Extract knowledge entities from the following research findings about {domain}.

{context}

Return valid JSON only. Format:
[
  {{
    "name": "<entity name>",
    "entity_type": "<person|company|ai_model|paper|framework|technique|concept|event>",
    "description": "<1-2 sentence description>",
    "tags": ["<tag1>", "<tag2>"],
    "confidence": <0.0-1.0>
  }}
]

Rules:
1. Extract 3-8 distinct, meaningful entities.
2. Do NOT extract generic concepts — only specific, named things.
3. Be accurate about entity types.
4. Set confidence based on how well-sourced the information is.
"""

        router = ModelRouter(self.empire_id)
        metadata = TaskMetadata(
            task_type="extraction",
            complexity="moderate",
            required_capabilities=["reasoning"],
            estimated_tokens=1500,
            priority=4,
        )

        request = LLMRequest(
            messages=[LLMMessage.user(prompt)],
            system_prompt="You are a knowledge extraction specialist. Extract structured entities from research text. Respond with valid JSON only.",
            temperature=0.2,
            max_tokens=1500,
        )

        # Don't silently swallow LLM failures — previously this returned
        # ([],0.0,0,"") on any exception which marked tasks success=True with
        # cost=$0, quality=0, model=None. Let the outer _execute_research
        # handler route real failures through _fail_task with a proper error.
        response = router.execute(request, metadata)
        return (
            self._parse_entities(response.content),
            float(response.cost_usd or 0.0),
            int(response.total_tokens or 0),
            response.model or "",
        )

    def _parse_entities(self, raw: str) -> list[dict]:
        """Parse entity extraction JSON response."""
        import json
        from utils.text import extract_json_block

        text = extract_json_block(raw) if "```" in raw else raw

        try:
            data = json.loads(text)
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            start = raw.find("[")
            end = raw.rfind("]") + 1
            if start >= 0 and end > start:
                try:
                    return json.loads(raw[start:end])
                except json.JSONDecodeError:
                    pass

        logger.debug("Could not parse entity extraction response")
        return []

    def _store_findings(
        self,
        findings: list[ResearchFinding],
        entities: list[dict],
        question: Any,
        source_task_id: str | None = None,
    ) -> int:
        """Store novel findings in memory and knowledge graph."""
        from core.research.questions import ResearchQuestion

        q: ResearchQuestion = question
        stored = 0

        # Use BiTemporalMemory for auto-supersession — new findings replace
        # outdated ones instead of piling up and decaying to zero.
        from core.memory.bitemporal import BiTemporalMemory
        bt = BiTemporalMemory(self.empire_id)

        for finding in findings[:8]:
            try:
                bt.store_smart(
                    content=(
                        f"{finding.title}\n\n{finding.content[:1500]}\n\n"
                        f"Source: {finding.source_name} ({finding.source_url})"
                    ),
                    title=f"Research: {finding.title[:80]}",
                    category="auto_research",
                    importance=finding.importance,
                    tags=["auto_research", q.domain, q.strategy],
                    lieutenant_id=q.lieutenant_id or "",
                )
                stored += 1
            except Exception as exc:
                logger.error("Failed to store finding '%s': %s", finding.title[:60], exc)

        from core.knowledge.graph import KnowledgeGraph
        graph = KnowledgeGraph(self.empire_id)

        for entity in entities:
            try:
                graph.add_entity(
                    name=entity.get("name", "")[:100],
                    entity_type=entity.get("entity_type", "concept"),
                    description=entity.get("description", "")[:500],
                    confidence=entity.get("confidence", 0.6),
                    tags=entity.get("tags", []) + ["auto_research", q.domain],
                    source_task_id=source_task_id or "",
                    source_type="web_research",
                )
                stored += 1
            except Exception as exc:
                logger.error("Failed to store entity '%s': %s", entity.get("name"), exc)

        return stored

    # ------------------------------------------------------------------
    # Step 4: Synthesis
    # ------------------------------------------------------------------

    def _synthesize(self, result: ResearchCycleResult) -> tuple[int, float]:
        """Produce per-domain synthesis reports from research findings.

        Returns (reports_created, total_cost_usd).
        """
        from llm.router import ModelRouter, TaskMetadata
        from llm.base import LLMRequest, LLMMessage
        from core.memory.manager import MemoryManager

        router = ModelRouter(self.empire_id)
        mm = MemoryManager(self.empire_id)
        reports_created = 0
        total_cost = 0.0

        domain_findings: dict[str, list[ResearchFinding]] = {}
        for step in result.step_results:
            if step.success and step.findings:
                domain_findings.setdefault(step.domain, []).extend(step.findings)

        for domain, findings in domain_findings.items():
            if len(findings) < 2:
                continue

            context = "\n\n".join(
                f"- **{f.title}** ({f.source_name}): {f.content[:400]}"
                for f in findings[:10]
            )

            prompt = f"""Synthesize these research findings about {domain} into a concise intelligence briefing.

{context}

Write a 3-5 paragraph synthesis that:
1. Identifies the key themes and developments.
2. Notes any connections between findings.
3. Highlights what's most significant or surprising.
4. Suggests what to research next.

Write in a professional intelligence-briefing style. Be specific — cite sources by name.
"""

            metadata = TaskMetadata(
                task_type="synthesis",
                complexity="moderate",
                required_capabilities=["reasoning", "writing"],
                estimated_tokens=1500,
                priority=4,
            )

            request = LLMRequest(
                messages=[LLMMessage.user(prompt)],
                system_prompt=(
                    "You are an AI research analyst producing intelligence briefings. "
                    "Synthesize research findings into clear, actionable summaries."
                ),
                temperature=0.3,
                max_tokens=1500,
            )

            try:
                response = router.execute(request, metadata)
                total_cost += float(response.cost_usd or 0.0)

                mm.store(
                    content=response.content,
                    memory_type="semantic",
                    title=f"Research Synthesis: {domain} — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
                    category="synthesis",
                    importance=0.85,
                    tags=["synthesis", "auto_research", domain],
                    source_type="autonomous",
                )
                reports_created += 1
                logger.info("Created synthesis report for domain '%s' ($%.4f)", domain, response.cost_usd or 0)

            except Exception as exc:
                logger.error("Synthesis failed for domain '%s': %s", domain, exc)

        return reports_created, total_cost

    # ------------------------------------------------------------------
    # Step 5: Strategy learning
    # ------------------------------------------------------------------

    def _update_strategies(self, result: ResearchCycleResult) -> None:
        """Update the strategy tracker with results from this cycle."""
        from core.research.strategy import StrategyTracker

        tracker = StrategyTracker(self.empire_id)

        for step in result.step_results:
            efficiency = step.novel_findings / max(1, step.sources_searched)
            tracker.record_outcome(
                strategy=step.strategy_used,
                domain=step.domain,
                efficiency=efficiency,
                findings=step.novel_findings,
                cost_usd=step.cost_usd,
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _check_budget(self) -> bool:
        """Check if we have budget headroom for a research cycle.

        Fails closed — if the check itself throws, assume over budget.
        """
        try:
            from core.routing.budget import BudgetManager
            bm = BudgetManager(self.empire_id)
            return not bm.is_over_budget()
        except Exception as e:
            logger.error("Budget check failed — halting research as precaution: %s", e)
            return False

    def _estimate_confidence(self, source: str) -> float:
        """Estimate confidence based on the source domain."""
        try:
            from core.search.credibility import CredibilityScorer
            scorer = CredibilityScorer()
            result = scorer.score(source)
            return result.score  # Extract float from CredibilityScore object
        except Exception:
            return 0.5

    def _emit_events(self, result: ResearchCycleResult) -> None:
        """Publish events for the research cycle."""
        from utils.events import emit

        emit(
            "research.cycle_completed",
            source="autoresearcher",
            data=result.to_dict(),
            empire_id=self.empire_id,
        )

        if result.novel_findings > 0:
            emit(
                "research.findings_stored",
                source="autoresearcher",
                data={
                    "cycle_id": result.cycle_id,
                    "novel_findings": result.novel_findings,
                    "entities_extracted": result.entities_extracted,
                    "domains": result.domains_covered,
                },
                empire_id=self.empire_id,
            )

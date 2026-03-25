"""War Room sessions — orchestrates multi-lieutenant planning and debate."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class SessionState(str, Enum):
    CREATED = "created"
    DEBATING = "debating"
    PLANNING = "planning"
    REVIEWING = "reviewing"
    RETROSPECTIVE = "retrospective"
    CLOSED = "closed"


@dataclass
class Message:
    """A message in the war room."""
    speaker_id: str
    speaker_name: str
    content: str
    message_type: str = "statement"  # statement, question, proposal, rebuttal, synthesis
    timestamp: str = ""
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


@dataclass
class ActionItem:
    """An action item from the war room."""
    description: str
    assigned_to: str = ""
    priority: str = "medium"  # low, medium, high, critical
    deadline: str = ""
    status: str = "pending"  # pending, in_progress, completed


@dataclass
class SessionSummary:
    """Summary of a war room session."""
    session_id: str = ""
    status: str = ""
    decisions: list[str] = field(default_factory=list)
    action_items: list[ActionItem] = field(default_factory=list)
    key_insights: list[str] = field(default_factory=list)
    dissenting_views: list[str] = field(default_factory=list)
    participants: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    total_cost: float = 0.0


class WarRoomSession:
    """Orchestrates multi-lieutenant planning and debate sessions.

    The War Room is where lieutenants come together to debate approaches,
    plan directive execution, review results, and run retrospectives.
    A Chief of Staff (the synthesis model) moderates and combines outputs.
    """

    def __init__(
        self,
        session_id: str = "",
        empire_id: str = "",
        directive_id: str = "",
        session_type: str = "planning",
    ):
        self.session_id = session_id
        self.empire_id = empire_id
        self.directive_id = directive_id
        self.session_type = session_type
        self.state = SessionState.CREATED
        self.participants: list[dict] = []  # {id, name, domain}
        self.transcript: list[Message] = []
        self.action_items: list[ActionItem] = []
        self.decisions: list[str] = []
        self.synthesis: dict = {}
        self._start_time = time.time()
        self._total_cost = 0.0
        self._repo = None

    def _get_repo(self):
        if self._repo is None:
            from db.engine import get_session
            session = get_session()
            self._repo = session
        return self._repo

    def add_participant(self, lieutenant_id: str, name: str = "", domain: str = "") -> None:
        """Add a lieutenant participant."""
        self.participants.append({
            "id": lieutenant_id,
            "name": name,
            "domain": domain,
        })
        self._add_message(
            speaker_id="system",
            speaker_name="War Room",
            content=f"{name or lieutenant_id} has joined the session.",
            msg_type="system",
        )

    def remove_participant(self, lieutenant_id: str) -> None:
        """Remove a participant."""
        self.participants = [p for p in self.participants if p["id"] != lieutenant_id]

    def start_debate(self, topic: str, context: str = "") -> dict:
        """Start a debate on a topic.

        Args:
            topic: Debate topic.
            context: Additional context.

        Returns:
            Debate result dict.
        """
        self.state = SessionState.DEBATING
        self._add_message("system", "War Room", f"Debate started: {topic}", "system")

        # Collect positions from each participant
        contributions = []
        from core.lieutenant.manager import LieutenantManager
        manager = LieutenantManager(self.empire_id)

        for participant in self.participants:
            lt = manager.get_lieutenant(participant["id"])
            if lt:
                contribution = lt.participate_in_debate(topic)
                contributions.append({
                    "lieutenant_id": participant["id"],
                    "name": participant.get("name", ""),
                    "position": contribution.position,
                    "arguments": contribution.arguments,
                    "confidence": contribution.confidence,
                })
                self._add_message(
                    participant["id"],
                    participant.get("name", ""),
                    f"Position: {contribution.position}\nArguments: {'; '.join(contribution.arguments[:3])}",
                    "statement",
                )

        # Synthesize
        synthesis = self._synthesize_debate(topic, contributions)
        self.synthesis = synthesis
        self.decisions.extend(synthesis.get("decisions", []))

        return {
            "topic": topic,
            "contributions": contributions,
            "synthesis": synthesis,
            "participant_count": len(contributions),
        }

    def run_planning_phase(self, directive_title: str, directive_description: str) -> dict:
        """Run the planning phase — lieutenants propose plans, Chief of Staff synthesizes.

        Args:
            directive_title: Directive title.
            directive_description: Directive description.

        Returns:
            Planning result with unified plan.
        """
        self.state = SessionState.PLANNING
        self._add_message("system", "War Room", f"Planning phase: {directive_title}", "system")

        plans = []
        from llm.base import LLMRequest, LLMMessage
        from llm.router import ModelRouter, TaskMetadata
        from db.engine import get_session
        from db.repositories.lieutenant import LieutenantRepository

        router = ModelRouter()
        session_db = get_session()
        lt_repo = LieutenantRepository(session_db)

        for participant in self.participants:
            db_lt = lt_repo.get(participant["id"])
            if not db_lt:
                continue

            persona = db_lt.persona_json or {}
            system_prompt = persona.get("system_prompt_template", f"You are {db_lt.name}, an expert in {db_lt.domain}.")

            prompt = (
                f"Create a plan for this directive from your {db_lt.domain} perspective:\n\n"
                f"Directive: {directive_title}\n{directive_description}\n\n"
                f"Propose specific tasks with their order and who should handle them. Be concise."
            )

            try:
                request = LLMRequest(
                    messages=[LLMMessage.user(prompt)],
                    system_prompt=system_prompt,
                    temperature=0.4,
                    max_tokens=1500,
                )
                response = router.execute(request, TaskMetadata(task_type="planning", complexity="moderate"))

                plans.append({
                    "lieutenant_id": participant["id"],
                    "name": participant.get("name", db_lt.name),
                    "domain": participant.get("domain", db_lt.domain),
                    "plan": response.content,
                    "quality": 0.7,
                })
                self._add_message(
                    participant["id"],
                    participant.get("name", db_lt.name),
                    response.content[:500],
                    "proposal",
                )
                self._total_cost += response.cost_usd
            except Exception as e:
                logger.warning("Planning failed for %s: %s", db_lt.name, e)
                plans.append({
                    "lieutenant_id": participant["id"],
                    "name": db_lt.name,
                    "domain": db_lt.domain,
                    "plan": f"Planning error: {e}",
                    "quality": 0.0,
                })

        # Synthesize plans
        unified = self._synthesize_plans(directive_title, plans)
        self.synthesis = unified

        return {
            "individual_plans": plans,
            "unified_plan": unified,
            "participant_count": len(plans),
        }

    def run_retrospective(self, results: dict) -> dict:
        """Run a retrospective on completed work.

        Args:
            results: Results of the completed directive.

        Returns:
            Retrospective findings.
        """
        self.state = SessionState.RETROSPECTIVE

        from llm.base import LLMRequest, LLMMessage
        from llm.router import ModelRouter, TaskMetadata
        import json

        router = ModelRouter()
        results_str = json.dumps(results, indent=2, default=str)[:6000]

        prompt = f"""Run a retrospective on this completed directive.

Results:
{results_str}

Analyze:
1. What went well
2. What went wrong
3. Lessons learned
4. Specific improvements for next time
5. Action items

Respond as JSON:
{{
    "what_went_well": ["..."],
    "what_went_wrong": ["..."],
    "lessons_learned": ["..."],
    "improvements": ["..."],
    "action_items": [{{"description": "...", "priority": "high", "assigned_to": ""}}]
}}
"""
        try:
            request = LLMRequest(
                messages=[LLMMessage.user(prompt)],
                system_prompt="You are a retrospective facilitator. Be specific and actionable.",
                temperature=0.3,
                max_tokens=2000,
            )
            response = router.execute(request, TaskMetadata(task_type="analysis"))
            self._total_cost += response.cost_usd

            try:
                data = json.loads(response.content)
            except json.JSONDecodeError:
                from llm.schemas import _find_json_object
                json_str = _find_json_object(response.content)
                data = json.loads(json_str) if json_str else {}

            # Create action items
            for item in data.get("action_items", []):
                self.action_items.append(ActionItem(
                    description=item.get("description", ""),
                    priority=item.get("priority", "medium"),
                    assigned_to=item.get("assigned_to", ""),
                ))

            return data

        except Exception as e:
            logger.error("Retrospective failed: %s", e)
            return {"error": str(e)}

    def get_session_transcript(self) -> list[dict]:
        """Get the full session transcript."""
        return [
            {
                "speaker_id": m.speaker_id,
                "speaker_name": m.speaker_name,
                "content": m.content,
                "type": m.message_type,
                "timestamp": m.timestamp,
            }
            for m in self.transcript
        ]

    def get_action_items(self) -> list[dict]:
        """Get all action items from the session."""
        return [
            {
                "description": ai.description,
                "assigned_to": ai.assigned_to,
                "priority": ai.priority,
                "status": ai.status,
            }
            for ai in self.action_items
        ]

    def close_session(self) -> SessionSummary:
        """Close the session and produce a summary."""
        self.state = SessionState.CLOSED
        duration = time.time() - self._start_time

        summary = SessionSummary(
            session_id=self.session_id,
            status="closed",
            decisions=self.decisions,
            action_items=self.action_items,
            key_insights=self.synthesis.get("key_insights", []),
            dissenting_views=self.synthesis.get("dissenting_views", []),
            participants=[p.get("name", p["id"]) for p in self.participants],
            duration_seconds=duration,
            total_cost=self._total_cost,
        )

        # Persist to database
        self._persist_session(summary)

        return summary

    def _add_message(self, speaker_id: str, speaker_name: str, content: str, msg_type: str) -> None:
        """Add a message to the transcript."""
        self.transcript.append(Message(
            speaker_id=speaker_id,
            speaker_name=speaker_name,
            content=content,
            message_type=msg_type,
        ))

    def _synthesize_debate(self, topic: str, contributions: list[dict]) -> dict:
        """Synthesize debate contributions using the Chief of Staff model."""
        from llm.base import LLMRequest, LLMMessage
        from llm.router import ModelRouter, TaskMetadata
        import json

        router = ModelRouter()
        contrib_text = "\n\n".join(
            f"**{c.get('name', 'Unknown')}** ({c.get('domain', '')}):\n"
            f"Position: {c.get('position', '')}\n"
            f"Arguments: {'; '.join(str(a) for a in c.get('arguments', []))}\n"
            f"Confidence: {c.get('confidence', 0)}"
            for c in contributions
        )

        prompt = f"""As Chief of Staff, synthesize this debate.

Topic: {topic}

Contributions:
{contrib_text}

Provide:
1. Summary of the debate
2. Key decisions/consensus points
3. Dissenting views that merit consideration
4. Recommended path forward
5. Action items

Respond as JSON:
{{
    "summary": "...",
    "decisions": ["..."],
    "dissenting_views": ["..."],
    "recommended_action": "...",
    "key_insights": ["..."]
}}
"""
        try:
            request = LLMRequest(
                messages=[LLMMessage.user(prompt)],
                system_prompt="You are the Chief of Staff. Synthesize fairly, capturing all perspectives.",
                temperature=0.3,
                max_tokens=2000,
            )
            response = router.execute(request, TaskMetadata(task_type="analysis"))
            self._total_cost += response.cost_usd

            from llm.schemas import _find_json_object, _extract_json_block
            raw = response.content
            # Try direct parse, then markdown block, then find object
            for attempt_str in [raw, _extract_json_block(raw), _find_json_object(raw)]:
                if attempt_str:
                    try:
                        return json.loads(attempt_str)
                    except (json.JSONDecodeError, TypeError):
                        continue
            return {"summary": raw, "waves": []}

        except Exception as e:
            return {"summary": f"Synthesis failed: {e}", "decisions": [], "dissenting_views": []}

    def _synthesize_plans(self, directive_title: str, plans: list[dict]) -> dict:
        """Synthesize individual plans into a unified plan."""
        from llm.base import LLMRequest, LLMMessage
        from llm.router import ModelRouter, TaskMetadata
        import json

        router = ModelRouter()
        plans_text = "\n\n---\n\n".join(
            f"**{p.get('name', 'Unknown')}** ({p.get('domain', '')}):\n{p.get('plan', '')[:1500]}"
            for p in plans
        )

        prompt = f"""Synthesize these plans into a unified execution plan for: {directive_title}

Individual Plans:
{plans_text}

Create a unified plan with:
1. Ordered waves of execution
2. Task assignments to lieutenants
3. Dependencies between tasks
4. Key milestones

Respond as JSON:
{{
    "summary": "...",
    "waves": [
        {{
            "wave_number": 1,
            "tasks": [{{"title": "...", "assigned_to": "...", "description": "..."}}],
            "dependencies": []
        }}
    ],
    "milestones": ["..."],
    "estimated_total_tasks": 0,
    "key_risks": ["..."]
}}
"""
        try:
            request = LLMRequest(
                messages=[LLMMessage.user(prompt)],
                temperature=0.3,
                max_tokens=3000,
            )
            response = router.execute(request, TaskMetadata(task_type="planning"))
            self._total_cost += response.cost_usd

            from llm.schemas import _find_json_object, _extract_json_block
            raw = response.content
            # Try direct parse, then markdown block, then find object
            for attempt_str in [raw, _extract_json_block(raw), _find_json_object(raw)]:
                if attempt_str:
                    try:
                        return json.loads(attempt_str)
                    except (json.JSONDecodeError, TypeError):
                        continue
            return {"summary": raw, "waves": []}

        except Exception as e:
            return {"summary": f"Plan synthesis failed: {e}"}

    def _persist_session(self, summary: SessionSummary) -> None:
        """Save session to database."""
        try:
            from db.engine import session_scope
            from db.models import WarRoom

            with session_scope() as session:
                war_room = WarRoom(
                    id=self.session_id or None,
                    directive_id=self.directive_id or None,
                    empire_id=self.empire_id,
                    status="closed",
                    session_type=self.session_type,
                    participants_json=[p["id"] for p in self.participants],
                    debate_rounds_json=[],
                    synthesis_json=self.synthesis,
                    action_items_json=[ai.__dict__ for ai in self.action_items],
                    transcript_json=[m.__dict__ for m in self.transcript[-50:]],  # Last 50 messages
                    total_cost_usd=self._total_cost,
                    completed_at=datetime.now(timezone.utc),
                )
                session.add(war_room)
        except Exception as e:
            logger.warning("Failed to persist war room session: %s", e)

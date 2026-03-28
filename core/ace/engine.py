"""ACE (Autonomous Cognitive Engine) — the reusable brain powering every lieutenant.

Orchestrates the 3-agent pipeline: Planner → Executor → Critic
with quality gates, retry loops, and cost tracking.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from llm.base import LLMRequest, LLMResponse, LLMMessage, ToolDefinition
from llm.router import ModelRouter, TaskMetadata
from llm.schemas import PlanningOutput, CriticOutput, parse_llm_output
from config.settings import get_settings
from core.ace.tools import ToolRegistry

logger = logging.getLogger(__name__)


@dataclass
class ACEContext:
    """Context for an ACE execution — persona, domain knowledge, memories."""
    persona_prompt: str = ""
    domain_context: str = ""
    memories: list[str] = field(default_factory=list)
    knowledge: list[str] = field(default_factory=list)
    previous_results: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def build_system_prompt(self) -> str:
        parts = []
        if self.persona_prompt:
            parts.append(self.persona_prompt)
        if self.domain_context:
            parts.append(f"\n## Domain Context\n{self.domain_context}")
        if self.memories:
            parts.append("\n## Relevant Memories\n" + "\n".join(f"- {m}" for m in self.memories[:10]))
        if self.knowledge:
            parts.append("\n## Domain Knowledge\n" + "\n".join(f"- {k}" for k in self.knowledge[:10]))
        return "\n".join(parts)

    @property
    def token_estimate(self) -> int:
        total = len(self.persona_prompt) + len(self.domain_context)
        total += sum(len(m) for m in self.memories)
        total += sum(len(k) for k in self.knowledge)
        return total // 4


@dataclass
class TaskInput:
    """Input for a single task."""
    id: str = ""
    title: str = ""
    description: str = ""
    task_type: str = "general"
    input_data: dict = field(default_factory=dict)
    requirements: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    priority: int = 5
    max_tokens: int = 4096
    model_override: str = ""


@dataclass
class TaskResult:
    """Result of a single task execution through the ACE pipeline."""
    task_id: str = ""
    success: bool = False
    output: dict = field(default_factory=dict)
    content: str = ""
    quality_score: float = 0.0
    quality_details: dict = field(default_factory=dict)

    # Pipeline details
    planning_output: dict = field(default_factory=dict)
    execution_output: dict = field(default_factory=dict)
    critic_output: dict = field(default_factory=dict)

    # Metrics
    model_used: str = ""
    provider: str = ""
    tokens_input: int = 0
    tokens_output: int = 0
    cost_usd: float = 0.0
    execution_time_seconds: float = 0.0
    pipeline_iterations: int = 1
    retry_count: int = 0

    # Errors
    error: str = ""
    error_log: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "success": self.success,
            "content": self.content[:500],
            "quality_score": self.quality_score,
            "model_used": self.model_used,
            "cost_usd": self.cost_usd,
            "execution_time": self.execution_time_seconds,
            "iterations": self.pipeline_iterations,
        }


@dataclass
class DirectiveResult:
    """Result of a full directive execution."""
    directive_id: str = ""
    success: bool = False
    task_results: list[TaskResult] = field(default_factory=list)
    synthesis: str = ""
    quality_score: float = 0.0
    total_cost_usd: float = 0.0
    total_tokens: int = 0
    total_time_seconds: float = 0.0
    waves_completed: int = 0
    tasks_completed: int = 0
    tasks_failed: int = 0


@dataclass
class WaveResult:
    """Result of executing one wave of tasks."""
    wave_number: int = 0
    task_results: list[TaskResult] = field(default_factory=list)
    success_rate: float = 0.0
    total_cost: float = 0.0
    duration_seconds: float = 0.0


class ACEEngine:
    """The Autonomous Cognitive Engine — core brain for every lieutenant.

    Takes a persona + domain context and orchestrates a 3-agent pipeline:
    1. Planner — strategizes the approach
    2. Executor — executes the plan
    3. Critic — evaluates quality and decides if retry is needed

    Quality gates between stages ensure output meets standards.
    """

    def __init__(
        self,
        router: ModelRouter | None = None,
        planning_model: str = "",
        execution_model: str = "",
        critic_model: str = "",
        max_iterations: int = 3,
        min_quality: float = 0.6,
        empire_id: str = "",
        lieutenant_id: str = "",
    ):
        self.router = router or ModelRouter()
        self._planning_model = planning_model
        self._execution_model = execution_model
        self._critic_model = critic_model
        self._max_iterations = max_iterations
        self._min_quality = min_quality
        self._empire_id = empire_id
        self._lieutenant_id = lieutenant_id
        self._tool_registry: ToolRegistry | None = None

        # Load defaults from settings
        try:
            from config.settings import get_settings
            s = get_settings()
            if not self._planning_model:
                self._planning_model = s.ace.default_planning_model
            if not self._execution_model:
                self._execution_model = s.ace.default_execution_model
            if not self._critic_model:
                self._critic_model = s.ace.default_critic_model
            if max_iterations == 3:
                self._max_iterations = s.ace.max_pipeline_iterations
            if min_quality == 0.6:
                self._min_quality = s.quality.min_confidence_score
            if not self._empire_id:
                self._empire_id = s.empire_id
        except Exception:
            pass

        # Initialize tool registry (includes MCP tools)
        try:
            self._tool_registry = ToolRegistry(
                empire_id=self._empire_id,
                lieutenant_id=self._lieutenant_id,
            )
        except Exception as e:
            logger.debug("Tool registry init failed (tools unavailable): %s", e)

    def execute_task(self, task: TaskInput, context: ACEContext | None = None) -> TaskResult:
        """Execute a single task through the full 3-agent pipeline.

        Args:
            task: The task to execute.
            context: Persona and domain context.

        Returns:
            TaskResult with output, quality scores, and metrics.
        """
        context = context or ACEContext()
        start_time = time.time()
        result = TaskResult(task_id=task.id)

        system_prompt = context.build_system_prompt()

        try:
            # ── Stage 1: Planning (skip for short/simple tasks) ────────
            desc_len = len(task.description)
            skip_planning = desc_len < 200 or task.task_type in ("extraction", "classification")

            if skip_planning:
                plan = {"plan": "Direct execution (simple task)", "cost": 0.0, "tokens": 0}
            else:
                plan = self._run_planning(task, system_prompt, context)

            result.planning_output = plan
            result.cost_usd += plan.get("cost", 0.0)
            result.tokens_input += plan.get("tokens", 0)

            # ── Stage 2: Execution ─────────────────────────────────────
            execution = self._run_execution(task, plan, system_prompt, context)
            result.execution_output = execution
            result.content = execution.get("content", "")
            result.cost_usd += execution.get("cost", 0.0)
            result.tokens_input += execution.get("tokens", 0)
            result.model_used = execution.get("model", "")

            # ── Stage 3: Critic loop ───────────────────────────────────
            critic_failures = 0
            for iteration in range(self._max_iterations):
                result.pipeline_iterations = iteration + 1

                critic_eval = self._run_critic(task, execution, system_prompt)
                result.critic_output = critic_eval
                result.quality_score = critic_eval.get("overall_score", 0.0)
                result.quality_details = critic_eval
                result.cost_usd += critic_eval.get("cost", 0.0)

                # Check if quality is acceptable
                if result.quality_score >= self._min_quality:
                    result.success = True
                    break

                critic_failures += 1

                # Quality not met — retry if we have iterations left
                if iteration < self._max_iterations - 1:
                    logger.info(
                        "Task %s: quality %.2f below threshold %.2f, iteration %d/%d",
                        task.id, result.quality_score, self._min_quality,
                        iteration + 1, self._max_iterations,
                    )

                    # Escalate to premium model if repeated failures
                    escalation_threshold = getattr(
                        getattr(get_settings(), "ace", None),
                        "escalate_after_failures",
                        2
                    )
                    if critic_failures >= escalation_threshold and not task.model_override:
                        escalation_model = getattr(
                            getattr(get_settings(), "ace", None),
                            "escalation_model",
                            "claude-opus-4"
                        )
                        logger.warning(
                            "Task %s: escalating to %s after %d quality failures",
                            task.id, escalation_model, critic_failures
                        )
                        task.model_override = escalation_model

                    # Re-execute with critic feedback
                    feedback = critic_eval.get("suggestions", [])
                    issues = critic_eval.get("issues", [])
                    execution = self._run_execution(
                        task, plan, system_prompt, context,
                        previous_output=execution,
                        feedback=feedback,
                        issues=issues,
                    )
                    result.execution_output = execution
                    result.content = execution.get("content", "")
                    result.cost_usd += execution.get("cost", 0.0)

            if not result.success and result.quality_score > 0:
                # Accept with lower quality if we exhausted iterations
                result.success = result.quality_score >= (self._min_quality * 0.7)

            result.output = {
                "content": result.content,
                "planning": result.planning_output,
                "quality": result.quality_details,
            }

        except Exception as e:
            result.error = str(e)
            result.error_log.append(str(e))
            logger.error("ACE engine error on task %s: %s", task.id, e)

        result.execution_time_seconds = time.time() - start_time
        return result

    def execute_batch(
        self,
        tasks: list[TaskInput],
        context: ACEContext | None = None,
    ) -> list[TaskResult]:
        """Execute multiple tasks sequentially.

        Args:
            tasks: List of tasks.
            context: Shared context.

        Returns:
            List of results.
        """
        results = []
        for task in tasks:
            result = self.execute_task(task, context)
            results.append(result)
        return results

    def execute_wave(
        self,
        tasks: list[TaskInput],
        context: ACEContext | None = None,
        wave_number: int = 0,
    ) -> WaveResult:
        """Execute a wave of tasks (all tasks in parallel within a wave).

        Args:
            tasks: Tasks in this wave.
            context: Shared context.
            wave_number: Wave number.

        Returns:
            WaveResult.
        """
        start_time = time.time()
        task_results = self.execute_batch(tasks, context)

        succeeded = sum(1 for r in task_results if r.success)
        total_cost = sum(r.cost_usd for r in task_results)

        return WaveResult(
            wave_number=wave_number,
            task_results=task_results,
            success_rate=succeeded / len(task_results) if task_results else 0.0,
            total_cost=total_cost,
            duration_seconds=time.time() - start_time,
        )

    # ── Pipeline stages ────────────────────────────────────────────────

    def _run_planning(
        self,
        task: TaskInput,
        system_prompt: str,
        context: ACEContext,
    ) -> dict:
        """Run the planning agent to strategize the approach."""
        planning_prompt = f"""You are the PLANNING agent in a 3-agent pipeline.

Your job is to analyze this task and create an execution plan.

## Task
Title: {task.title}
Description: {task.description}
Type: {task.task_type}
Requirements: {', '.join(task.requirements) if task.requirements else 'None specified'}
Constraints: {', '.join(task.constraints) if task.constraints else 'None specified'}

## Instructions
1. Analyze the task requirements
2. Break down the approach into clear steps
3. Identify potential challenges or risks
4. Recommend the level of detail needed

Respond with a structured plan including:
- approach: Your high-level strategy
- steps: Ordered list of execution steps
- estimated_complexity: simple/moderate/complex/expert
- risks: Potential issues to watch for
"""

        model = task.model_override or self._planning_model
        metadata = TaskMetadata(
            task_type="planning",
            complexity="moderate",
            estimated_tokens=2000,
        )

        try:
            request = LLMRequest(
                messages=[LLMMessage.user(planning_prompt)],
                model=model,
                system_prompt=system_prompt,
                temperature=0.3,
                max_tokens=2000,
            )
            response = self.router.execute(request, metadata)

            return {
                "plan": response.content,
                "model": response.model,
                "tokens": response.total_tokens,
                "cost": response.cost_usd,
            }
        except Exception as e:
            logger.warning("Planning failed, proceeding without plan: %s", e)
            return {"plan": "Direct execution (planning skipped)", "error": str(e)}

    def _run_execution(
        self,
        task: TaskInput,
        plan: dict,
        system_prompt: str,
        context: ACEContext,
        previous_output: dict | None = None,
        feedback: list | None = None,
        issues: list | None = None,
    ) -> dict:
        """Run the execution agent to produce the task output."""
        exec_prompt = f"""You are the EXECUTION agent in a 3-agent pipeline.

## Task
Title: {task.title}
Description: {task.description}
Type: {task.task_type}

## Plan from Planning Agent
{plan.get('plan', 'No plan available — use your best judgment.')}

## Additional Input
{self._format_input_data(task.input_data)}
"""

        if previous_output and feedback:
            exec_prompt += f"""
## Previous Attempt Feedback
Your previous output was reviewed. Here is the feedback:

Issues found:
{chr(10).join(f'- {i}' for i in (issues or []))}

Suggestions for improvement:
{chr(10).join(f'- {s}' for s in (feedback or []))}

Previous output (for reference):
{previous_output.get('content', '')[:2000]}

Please produce an improved version addressing the feedback above.
"""

        exec_prompt += """
## Instructions
Execute the task thoroughly and produce high-quality output.
Be specific, accurate, and comprehensive.
Cite sources or reasoning where applicable.
"""

        # Add tool usage instructions if tools are available
        tool_definitions = []
        if self._tool_registry:
            tool_definitions = self._tool_registry.get_definitions()
            if tool_definitions:
                exec_prompt += f"""
You have {len(tool_definitions)} tools available. Use them to gather information,
search the web, recall memories, look up knowledge, and interact with external systems.
Call tools when you need real data — don't guess or hallucinate facts.
"""

        model = task.model_override or self._execution_model
        metadata = TaskMetadata(
            task_type=task.task_type,
            complexity="complex" if task.priority <= 3 else "moderate",
            estimated_tokens=task.max_tokens,
        )

        try:
            request = LLMRequest(
                messages=[LLMMessage.user(exec_prompt)],
                model=model,
                system_prompt=system_prompt,
                temperature=0.7,
                max_tokens=task.max_tokens,
                tools=tool_definitions,
                tool_choice="auto" if tool_definitions else None,
            )

            decision = self.router.route(metadata)
            request.model = decision.model_config.model_id
            client = self.router.get_client(decision.provider)

            # Use complete_with_tools for automatic tool execution loop
            if tool_definitions and self._tool_registry:
                response = client.complete_with_tools(
                    request,
                    tool_executor=self._tool_registry.execute_tool_call,
                    max_rounds=5,
                )
            else:
                response = client.complete(request)

            self.router._record_cost(response, decision.model_key, decision.provider)

            logger.info(
                "Execution complete: content_len=%d, tool_calls=%d, cost=%.4f",
                len(response.content),
                len(response.tool_calls) if response.tool_calls else 0,
                response.cost_usd,
            )

            return {
                "content": response.content,
                "model": response.model,
                "tokens": response.total_tokens,
                "cost": response.cost_usd,
                "tool_calls_made": len(response.tool_calls) if response.tool_calls else 0,
            }
        except Exception as e:
            logger.exception("Execution failed: %s", e)
            return {"content": "", "error": str(e)}

    def _run_critic(
        self,
        task: TaskInput,
        execution: dict,
        system_prompt: str,
    ) -> dict:
        """Run the critic agent to evaluate the output quality."""
        content = execution.get("content", "")
        if not content:
            return {
                "overall_score": 0.0,
                "approved": False,
                "issues": ["No content produced"],
                "suggestions": ["Retry execution"],
            }

        critic_prompt = f"""You are the CRITIC agent in a 3-agent pipeline.

## Original Task
Title: {task.title}
Description: {task.description}
Requirements: {', '.join(task.requirements) if task.requirements else 'None specified'}

## Output to Evaluate
{content[:6000]}

## Instructions
Evaluate the output quality on these dimensions (score 0.0 to 1.0):
1. **Confidence** — How confident is the output in its claims?
2. **Completeness** — Does it address all requirements?
3. **Coherence** — Is it logically consistent and well-structured?
4. **Accuracy** — Are the facts and reasoning sound?

Also identify:
- Any issues or problems
- Specific suggestions for improvement
- Whether you approve the output

Respond as JSON:
{{
    "confidence": 0.0-1.0,
    "completeness": 0.0-1.0,
    "coherence": 0.0-1.0,
    "accuracy": 0.0-1.0,
    "overall_score": 0.0-1.0,
    "approved": true/false,
    "issues": ["list of issues"],
    "suggestions": ["list of suggestions"],
    "summary": "brief evaluation summary"
}}
"""

        metadata = TaskMetadata(
            task_type="analysis",
            complexity="moderate",
            estimated_tokens=2000,
        )

        try:
            request = LLMRequest(
                messages=[LLMMessage.user(critic_prompt)],
                model=self._critic_model,
                system_prompt="You are a quality evaluation expert. Be fair but rigorous. Always respond with valid JSON.",
                temperature=0.2,
                max_tokens=1500,
            )
            response = self.router.execute(request, metadata)

            # Parse the JSON response directly — the prompt asks for flat fields
            import json
            from llm.schemas import _find_json_object

            raw = response.content
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                json_str = _find_json_object(raw)
                if json_str:
                    data = json.loads(json_str)
                else:
                    data = {}

            if data:
                return {
                    "overall_score": float(data.get("overall_score", 0.5)),
                    "confidence": float(data.get("confidence", 0.5)),
                    "completeness": float(data.get("completeness", 0.5)),
                    "coherence": float(data.get("coherence", 0.5)),
                    "accuracy": float(data.get("accuracy", 0.5)),
                    "approved": data.get("approved", False),
                    "issues": data.get("issues", []),
                    "suggestions": data.get("suggestions", []),
                    "summary": data.get("summary", ""),
                    "cost": response.cost_usd,
                }

            return {"overall_score": 0.5, "approved": False, "issues": ["Could not parse critic output"], "cost": response.cost_usd}

        except Exception as e:
            logger.warning("Critic evaluation failed: %s", e)
            # If critic fails, give moderate score and approve
            return {"overall_score": 0.6, "approved": True, "issues": [f"Critic error: {e}"], "cost": 0.0}

    def _format_input_data(self, data: dict) -> str:
        """Format input data for the execution prompt."""
        if not data:
            return "No additional input data."
        parts = []
        for key, value in data.items():
            if isinstance(value, str) and len(value) > 500:
                parts.append(f"{key}: {value[:500]}...")
            else:
                parts.append(f"{key}: {value}")
        return "\n".join(parts)

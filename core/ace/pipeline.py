"""The 3-agent pipeline with configurable stages and hooks."""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class StageType(str, Enum):
    PLANNING = "planning"
    EXECUTION = "execution"
    CRITIC = "critic"
    CUSTOM = "custom"


@dataclass
class PipelineContext:
    """Shared context flowing between pipeline stages."""
    task_id: str = ""
    task_title: str = ""
    task_description: str = ""
    task_type: str = "general"
    system_prompt: str = ""

    # Input data
    input_data: dict = field(default_factory=dict)
    requirements: list[str] = field(default_factory=list)

    # Stage outputs (accumulated as pipeline progresses)
    planning_output: Optional[dict] = None
    execution_output: Optional[dict] = None
    critic_output: Optional[dict] = None
    custom_outputs: dict = field(default_factory=dict)

    # Iteration tracking
    iteration: int = 0
    max_iterations: int = 3
    previous_outputs: list[dict] = field(default_factory=list)
    feedback: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)

    # Metrics
    total_tokens: int = 0
    total_cost: float = 0.0
    stage_metrics: dict = field(default_factory=dict)

    def add_stage_output(self, stage_type: StageType, output: dict) -> None:
        if stage_type == StageType.PLANNING:
            self.planning_output = output
        elif stage_type == StageType.EXECUTION:
            self.execution_output = output
        elif stage_type == StageType.CRITIC:
            self.critic_output = output
        else:
            self.custom_outputs[stage_type.value] = output

    def add_metrics(self, stage_name: str, tokens: int = 0, cost: float = 0.0, duration: float = 0.0) -> None:
        self.total_tokens += tokens
        self.total_cost += cost
        self.stage_metrics[stage_name] = {
            "tokens": tokens,
            "cost": cost,
            "duration_seconds": duration,
        }


@dataclass
class StageResult:
    """Result from a single pipeline stage."""
    stage_name: str
    stage_type: StageType
    success: bool = True
    output: dict = field(default_factory=dict)
    content: str = ""
    tokens_used: int = 0
    cost_usd: float = 0.0
    duration_seconds: float = 0.0
    error: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class PipelineResult:
    """Aggregated result from the full pipeline."""
    success: bool = False
    content: str = ""
    quality_score: float = 0.0
    approved: bool = False
    stage_results: list[StageResult] = field(default_factory=list)
    iterations: int = 1
    total_tokens: int = 0
    total_cost: float = 0.0
    total_duration: float = 0.0
    errors: list[str] = field(default_factory=list)


class PipelineStage(ABC):
    """Abstract base class for pipeline stages."""

    stage_type: StageType = StageType.CUSTOM
    stage_name: str = "custom"

    @abstractmethod
    def execute(self, context: PipelineContext) -> StageResult:
        """Execute this pipeline stage.

        Args:
            context: Pipeline context with accumulated data.

        Returns:
            Stage result.
        """
        ...

    def should_skip(self, context: PipelineContext) -> bool:
        """Check if this stage should be skipped.

        Args:
            context: Pipeline context.

        Returns:
            True if stage should be skipped.
        """
        return False


class PlanningStage(PipelineStage):
    """Planning stage — breaks task into steps and strategizes approach."""

    stage_type = StageType.PLANNING
    stage_name = "planning"

    def __init__(self, engine: Any = None):
        self._engine = engine

    def execute(self, context: PipelineContext) -> StageResult:
        start = time.time()
        try:
            if self._engine:
                from core.ace.engine import TaskInput
                task = TaskInput(
                    id=context.task_id,
                    title=context.task_title,
                    description=context.task_description,
                    task_type=context.task_type,
                )
                plan = self._engine._run_planning(task, context.system_prompt, None)
            else:
                plan = {"plan": f"Direct execution for: {context.task_title}"}

            context.add_stage_output(StageType.PLANNING, plan)

            return StageResult(
                stage_name=self.stage_name,
                stage_type=self.stage_type,
                success=True,
                output=plan,
                content=plan.get("plan", ""),
                tokens_used=plan.get("tokens", 0),
                cost_usd=plan.get("cost", 0.0),
                duration_seconds=time.time() - start,
            )
        except Exception as e:
            return StageResult(
                stage_name=self.stage_name,
                stage_type=self.stage_type,
                success=False,
                error=str(e),
                duration_seconds=time.time() - start,
            )


class ExecutionStage(PipelineStage):
    """Execution stage — produces the task output."""

    stage_type = StageType.EXECUTION
    stage_name = "execution"

    def __init__(self, engine: Any = None):
        self._engine = engine

    def execute(self, context: PipelineContext) -> StageResult:
        start = time.time()
        try:
            if self._engine:
                from core.ace.engine import TaskInput
                task = TaskInput(
                    id=context.task_id,
                    title=context.task_title,
                    description=context.task_description,
                    task_type=context.task_type,
                    input_data=context.input_data,
                    requirements=context.requirements,
                )
                execution = self._engine._run_execution(
                    task,
                    context.planning_output or {},
                    context.system_prompt,
                    None,
                    previous_output=context.execution_output if context.iteration > 0 else None,
                    feedback=context.feedback,
                    issues=context.issues,
                )
            else:
                execution = {"content": "No execution engine available"}

            context.add_stage_output(StageType.EXECUTION, execution)

            return StageResult(
                stage_name=self.stage_name,
                stage_type=self.stage_type,
                success=True,
                output=execution,
                content=execution.get("content", ""),
                tokens_used=execution.get("tokens", 0),
                cost_usd=execution.get("cost", 0.0),
                duration_seconds=time.time() - start,
            )
        except Exception as e:
            return StageResult(
                stage_name=self.stage_name,
                stage_type=self.stage_type,
                success=False,
                error=str(e),
                duration_seconds=time.time() - start,
            )


class CriticStage(PipelineStage):
    """Critic stage — evaluates quality and decides if retry is needed."""

    stage_type = StageType.CRITIC
    stage_name = "critic"

    def __init__(self, engine: Any = None, min_quality: float = 0.6):
        self._engine = engine
        self._min_quality = min_quality

    def execute(self, context: PipelineContext) -> StageResult:
        start = time.time()
        try:
            if self._engine:
                from core.ace.engine import TaskInput
                task = TaskInput(
                    id=context.task_id,
                    title=context.task_title,
                    description=context.task_description,
                    requirements=context.requirements,
                )
                critic = self._engine._run_critic(
                    task,
                    context.execution_output or {},
                )
            else:
                critic = {"overall_score": 0.5, "approved": False}

            context.add_stage_output(StageType.CRITIC, critic)

            return StageResult(
                stage_name=self.stage_name,
                stage_type=self.stage_type,
                success=True,
                output=critic,
                content=critic.get("summary", ""),
                duration_seconds=time.time() - start,
                metadata={
                    "quality_score": critic.get("overall_score", 0.0),
                    "approved": critic.get("approved", False),
                },
            )
        except Exception as e:
            return StageResult(
                stage_name=self.stage_name,
                stage_type=self.stage_type,
                success=False,
                error=str(e),
                duration_seconds=time.time() - start,
            )


# ── Hook types ─────────────────────────────────────────────────────────

PipelineHook = Callable[[PipelineContext, StageResult], None]


@dataclass
class PipelineConfig:
    """Configuration for the pipeline."""
    planning_model: str = ""
    execution_model: str = ""
    critic_model: str = ""
    max_iterations: int = 3
    min_quality: float = 0.6
    skip_planning: bool = False
    skip_critic: bool = False
    before_stage_hooks: dict[str, list[PipelineHook]] = field(default_factory=dict)
    after_stage_hooks: dict[str, list[PipelineHook]] = field(default_factory=dict)
    on_error_hooks: list[PipelineHook] = field(default_factory=list)


class Pipeline:
    """Configurable 3-agent pipeline with hooks and iteration support.

    Stages:
    1. Planning — strategize the approach
    2. Execution — produce the output
    3. Critic — evaluate quality
    4. (Repeat 2-3 if quality insufficient)
    """

    def __init__(
        self,
        stages: list[PipelineStage] | None = None,
        config: PipelineConfig | None = None,
    ):
        self.config = config or PipelineConfig()
        self._stages = stages or []

    def add_stage(self, stage: PipelineStage) -> None:
        self._stages.append(stage)

    def run(self, context: PipelineContext) -> PipelineResult:
        """Run the full pipeline.

        Args:
            context: Pipeline context.

        Returns:
            Pipeline result.
        """
        start_time = time.time()
        result = PipelineResult()

        for stage in self._stages:
            if stage.should_skip(context):
                continue

            # Before hooks
            hooks = self.config.before_stage_hooks.get(stage.stage_name, [])
            for hook in hooks:
                try:
                    hook(context, StageResult(stage_name=stage.stage_name, stage_type=stage.stage_type))
                except Exception as e:
                    logger.warning("Before hook error: %s", e)

            # Execute stage
            stage_result = stage.execute(context)
            result.stage_results.append(stage_result)
            context.add_metrics(
                stage.stage_name,
                tokens=stage_result.tokens_used,
                cost=stage_result.cost_usd,
                duration=stage_result.duration_seconds,
            )

            # After hooks
            hooks = self.config.after_stage_hooks.get(stage.stage_name, [])
            for hook in hooks:
                try:
                    hook(context, stage_result)
                except Exception as e:
                    logger.warning("After hook error: %s", e)

            if not stage_result.success:
                result.errors.append(f"{stage.stage_name}: {stage_result.error}")
                for hook in self.config.on_error_hooks:
                    try:
                        hook(context, stage_result)
                    except Exception:
                        pass

            # Handle critic iteration
            if stage.stage_type == StageType.CRITIC and stage_result.success:
                quality = stage_result.metadata.get("quality_score", 0.0)
                approved = stage_result.metadata.get("approved", False)
                result.quality_score = quality

                if quality >= self.config.min_quality or approved:
                    result.success = True
                    result.approved = True
                    result.content = context.execution_output.get("content", "") if context.execution_output else ""
                    break

        result.total_tokens = context.total_tokens
        result.total_cost = context.total_cost
        result.total_duration = time.time() - start_time
        result.iterations = context.iteration + 1

        if not result.content and context.execution_output:
            result.content = context.execution_output.get("content", "")

        return result

    @classmethod
    def create_default(cls, engine: Any = None, config: PipelineConfig | None = None) -> Pipeline:
        """Create a default 3-agent pipeline.

        Args:
            engine: ACE engine for stage execution.
            config: Pipeline configuration.

        Returns:
            Configured Pipeline.
        """
        config = config or PipelineConfig()
        pipeline = cls(config=config)
        pipeline.add_stage(PlanningStage(engine))
        pipeline.add_stage(ExecutionStage(engine))
        pipeline.add_stage(CriticStage(engine, min_quality=config.min_quality))
        return pipeline

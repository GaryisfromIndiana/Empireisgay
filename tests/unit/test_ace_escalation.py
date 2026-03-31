"""Unit tests for ACE model escalation logic."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from core.ace.engine import ACEEngine, ACEContext, TaskInput


def test_ace_escalates_to_opus_after_repeated_quality_failures() -> None:
    """Verify that ACE escalates from Sonnet to Opus after N critic failures."""
    
    # Force max_iterations to be exactly 4 (not pulled from config)
    from config.settings import get_settings
    original_max = get_settings().ace.max_pipeline_iterations
    get_settings().ace.max_pipeline_iterations = 4
    
    try:
        engine = ACEEngine(max_iterations=4, min_quality=0.8)
        task = TaskInput(
            title="Test escalation task",
            description="A task that will fail quality checks repeatedly",
        )
        
        # Mock the pipeline stages
        with patch.object(engine, "_run_planning") as mock_plan, \
             patch.object(engine, "_run_execution") as mock_exec, \
             patch.object(engine, "_run_critic") as mock_critic:
            
            # Planning returns success
            mock_plan.return_value = {"plan": "test plan", "cost": 0.01, "tokens": 100}
            
            # Execution returns low-quality output
            def execution_side_effect(*args, **kwargs):
                return {
                    "content": "Low quality output",
                    "model": kwargs.get("model", "claude-sonnet-4"),
                    "tokens": 200,
                    "cost": 0.03,
                }
            mock_exec.side_effect = execution_side_effect
            
            # Critic always fails (quality below threshold)
            mock_critic.return_value = {
                "overall_score": 0.5,
                "approved": False,
                "issues": ["Quality insufficient"],
                "suggestions": ["Add more detail"],
                "cost": 0.005,
            }
            
            result = engine.execute_task(task)
            
            # After 2 failures (escalate_after_failures=2), task.model_override should be set to opus
            # Total exec calls: initial + 3 retries = 4
            assert mock_exec.call_count == 4
            assert task.model_override == "claude-opus-4"
    finally:
        get_settings().ace.max_pipeline_iterations = original_max


def test_ace_does_not_escalate_if_quality_passes() -> None:
    """Verify ACE does not escalate when quality passes on first try."""
    
    engine = ACEEngine(max_iterations=3, min_quality=0.7)
    task = TaskInput(title="Test", description="High quality task")
    
    with patch.object(engine, "_run_planning") as mock_plan, \
         patch.object(engine, "_run_execution") as mock_exec, \
         patch.object(engine, "_run_critic") as mock_critic:
        
        mock_plan.return_value = {"plan": "test", "cost": 0.01, "tokens": 100}
        mock_exec.return_value = {"content": "Great output", "model": "claude-sonnet-4", "tokens": 300, "cost": 0.03}
        mock_critic.return_value = {"overall_score": 0.85, "approved": True, "cost": 0.005}
        
        result = engine.execute_task(task)
        
        assert result.success
        # model_override defaults to empty string, not None
        assert task.model_override == ""
        assert mock_exec.call_count == 1

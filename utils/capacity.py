"""Capacity planning and budget recommendation utilities."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CapacityEstimate:
    """Capacity estimate for task throughput."""
    target_tasks_per_hour: int
    estimated_cost_per_task: float
    recommended_daily_budget: float
    recommended_monthly_budget: float
    recommended_max_parallel: int
    notes: list[str]


def estimate_capacity(
    tasks_per_hour: int,
    avg_cost_per_task: float = 0.034,
    safety_margin: float = 1.3,
) -> CapacityEstimate:
    """Calculate recommended budget settings for target throughput.
    
    Args:
        tasks_per_hour: Target sustained throughput.
        avg_cost_per_task: Average cost per task (default: $0.034 for Sonnet).
        safety_margin: Budget multiplier for burst capacity (default: 1.3x).
    
    Returns:
        CapacityEstimate with recommendations.
    """
    tasks_per_day = tasks_per_hour * 24
    daily_cost = tasks_per_day * avg_cost_per_task
    recommended_daily = daily_cost * safety_margin
    
    tasks_per_month = tasks_per_day * 30
    monthly_cost = tasks_per_month * avg_cost_per_task
    recommended_monthly = monthly_cost * safety_margin
    
    # Parallel workers: aim for ~3-5 minute task completion at target rate
    tasks_per_5min = tasks_per_hour / 12
    recommended_parallel = max(3, min(20, int(tasks_per_5min * 1.5)))
    
    notes = []
    if tasks_per_hour > 50:
        notes.append("High throughput: ensure Postgres is configured (not SQLite)")
    if tasks_per_hour > 100:
        notes.append("Very high throughput: consider task queue (Celery/RQ) for horizontal scaling")
    if recommended_daily > 100:
        notes.append(f"Daily budget ${recommended_daily:.0f} requires approval for production use")
    
    return CapacityEstimate(
        target_tasks_per_hour=tasks_per_hour,
        estimated_cost_per_task=avg_cost_per_task,
        recommended_daily_budget=recommended_daily,
        recommended_monthly_budget=recommended_monthly,
        recommended_max_parallel=recommended_parallel,
        notes=notes,
    )


def print_capacity_report(tasks_per_hour: int) -> None:
    """Print a capacity planning report for target throughput."""
    estimate = estimate_capacity(tasks_per_hour)
    
    print(f"=== Capacity Plan for {tasks_per_hour} tasks/hour ===\n")
    print(f"Cost per task: ${estimate.estimated_cost_per_task:.4f}")
    print(f"Daily throughput: {tasks_per_hour * 24:,} tasks")
    print(f"Monthly throughput: {tasks_per_hour * 24 * 30:,} tasks")
    print()
    print("Recommended settings:")
    print(f"  EMPIRE_BUDGET__DAILY_LIMIT_USD={estimate.recommended_daily_budget:.2f}")
    print(f"  EMPIRE_BUDGET__MONTHLY_LIMIT_USD={estimate.recommended_monthly_budget:.2f}")
    print(f"  EMPIRE_ACE__MAX_PARALLEL_TASKS={estimate.recommended_max_parallel}")
    print()
    
    if estimate.notes:
        print("Notes:")
        for note in estimate.notes:
            print(f"  - {note}")


if __name__ == "__main__":
    import sys
    target = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    print_capacity_report(target)

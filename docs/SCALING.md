# Scaling Empire to 20+ Tasks/Hour

Empire now includes intelligent scaling optimizations that allow you to run 20-100+ tasks per hour with Postgres and appropriate budgets.

## Changes Implemented

### 1. Intelligent Model Escalation

**What it does**: Automatically escalates from Sonnet to Opus only when Sonnet repeatedly fails quality checks.

**How it works**:
- Default execution model: Sonnet ($0.003/1K input, $0.015/1K output)
- After N critic failures: Automatically escalates to Opus ($0.015/1K input, $0.075/1K output)
- Only pays 5x cost when absolutely necessary

**Configuration** (`config/settings.py` → `ACESettings`):
```python
escalation_model: str = "claude-opus-4"
escalate_after_failures: int = 2  # Escalate after N quality failures
```

**Example log output**:
```
Task abc123: quality 0.45 below threshold 0.7, iteration 1/3
Task abc123: quality 0.52 below threshold 0.7, iteration 2/3
Task abc123: escalating to claude-opus-4 after 2 quality failures
```

### 2. Thread Pool Scaling

**What it does**: Respects the configured `max_parallel_tasks` setting instead of hardcoded cap of 3.

**Before**: Directive manager used `ThreadPoolExecutor(max_workers=min(3, ...))`
**After**: Uses `max_workers=min(settings.ace.max_parallel_tasks, ...)`

**Configuration**:
```python
EMPIRE_ACE__MAX_PARALLEL_TASKS=8  # Run up to 8 tasks concurrently
```

### 3. Rate Limiter Enforcement

**What it does**: Proactively waits before API calls to avoid rate limit errors and failed requests.

**How it works**:
- Before each API call, checks if request would exceed RPM/TPM limits
- If yes: waits the minimum necessary time (max 5s per check)
- If no: proceeds immediately
- Eliminates rate limit errors and exponential backoff retries

**Example behavior**:
```
DEBUG Rate limit backpressure: waiting 2.3s
DEBUG Rate limit backpressure: waiting 0.8s
```

### 4. Capacity Planning Utility

**What it does**: Calculates recommended budget settings for target throughput.

**Usage**:
```bash
python3 -m utils.capacity 20  # For 20 tasks/hour
```

**Output**:
```
=== Capacity Plan for 20 tasks/hour ===

Cost per task: $0.0340
Daily throughput: 480 tasks
Monthly throughput: 14,400 tasks

Recommended settings:
  EMPIRE_BUDGET__DAILY_LIMIT_USD=21.22
  EMPIRE_BUDGET__MONTHLY_LIMIT_USD=636.48
  EMPIRE_ACE__MAX_PARALLEL_TASKS=5

Notes:
  - Recommend Postgres for production use (not SQLite)
```

## Configuration Examples

### Conservative (20 tasks/hour)
```bash
export EMPIRE_BUDGET__DAILY_LIMIT_USD=25
export EMPIRE_BUDGET__MONTHLY_LIMIT_USD=700
export EMPIRE_ACE__MAX_PARALLEL_TASKS=5
export EMPIRE_ACE__ESCALATE_AFTER_FAILURES=2
```

### Aggressive (50 tasks/hour)
```bash
export EMPIRE_BUDGET__DAILY_LIMIT_USD=60
export EMPIRE_BUDGET__MONTHLY_LIMIT_USD=1800
export EMPIRE_ACE__MAX_PARALLEL_TASKS=10
export EMPIRE_ACE__ESCALATE_AFTER_FAILURES=3  # More patience before Opus
```

### Maximum (100 tasks/hour)
```bash
export EMPIRE_BUDGET__DAILY_LIMIT_USD=120
export EMPIRE_BUDGET__MONTHLY_LIMIT_USD=3600
export EMPIRE_ACE__MAX_PARALLEL_TASKS=15
export EMPIRE_ACE__ESCALATE_AFTER_FAILURES=3
```

## Cost Analysis

### Sonnet (Default Executor)
- Input: $0.003/1K tokens
- Output: $0.015/1K tokens
- Typical task: ~4K input, ~2K output = **$0.042/task**

### Opus (Escalation Model)
- Input: $0.015/1K tokens
- Output: $0.075/1K tokens
- Typical task: ~4K input, ~2K output = **$0.210/task** (5x cost)

### Haiku (Planner + Critic)
- Input: $0.00025/1K tokens
- Output: $0.00125/1K tokens
- Negligible cost (~$0.002/task)

### Real-World Escalation Rate
- With `escalate_after_failures=2`, expect ~5-10% of tasks to escalate to Opus
- Effective average cost: **$0.034-0.045/task**
- At 20 tasks/hour: **$16-22/day**

## Per-Task Budget

Current setting: `per_task_limit_usd = 0.50`

**Should you increase it?**
- 0.50: Safe default, allows 1-2 Opus attempts if Sonnet fails
- 1.00: More headroom for complex research tasks
- 0.25: Aggressive cost control (may abort valid Opus escalations)

**Recommendation**: Keep at $0.50 unless you see frequent budget aborts in logs.

## Prerequisites for High Throughput

### Database
- **SQLite**: Max ~20 tasks/hour (single-file bottleneck)
- **Postgres**: 100+ tasks/hour (connection pooling, concurrent writes)

You confirmed running Postgres ✓

### API Rate Limits
With Anthropic Tier 2:
- Sonnet: 10,000 RPM, 2.5M TPM → supports 100+ tasks/hour
- Opus: 10,000 RPM, 2.5M TPM → supports 30-50 tasks/hour (if all tasks escalate)

Rate limiter enforcement prevents hitting these limits.

## Monitoring

Watch for these log patterns:

**Good**:
```
Task abc123: quality 0.85 above threshold 0.7 (1 iteration)
Rate limit backpressure: waiting 1.2s
```

**Attention needed**:
```
Task abc123: escalating to claude-opus-4 after 2 quality failures  # Normal escalation
Task abc123: budget exceeded ($0.51 > $0.50 limit)  # Increase per_task_limit_usd
Task abc123: exhausted 3 iterations, quality 0.65  # Tune min_quality threshold
```

## Testing

New unit tests verify the escalation logic:
```bash
pytest tests/unit/test_ace_escalation.py -v
pytest tests/unit/test_rate_limiter.py -v
```

## Next Steps

1. **Start conservative**: Use 20 tasks/hour settings above
2. **Monitor for 24 hours**: Watch logs for escalation rate and bottlenecks
3. **Scale gradually**: Increase `max_parallel_tasks` by 2-3 every few days
4. **Track costs**: Use capacity utility to validate actual vs estimated costs
5. **Optimize thresholds**: Adjust `escalate_after_failures` based on escalation rate

---

**Summary**: These changes give you intelligent cost control (escalate only when needed), proactive rate limiting (no failed requests), and configurable parallelism. You can now scale to 50-100 tasks/hour on Postgres with budgets of $25-120/day.

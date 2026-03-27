"""Budget management — tracks and enforces spending limits."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class BudgetCheck:
    """Result of a budget check."""
    allowed: bool = True
    remaining_daily: float = 0.0
    remaining_monthly: float = 0.0
    warning: str = ""
    reason: str = ""


@dataclass
class BudgetAlert:
    """A budget alert."""
    alert_type: str = "warning"  # warning, critical, exceeded
    message: str = ""
    severity: str = "medium"
    threshold_percent: float = 0.0
    current_percent: float = 0.0


@dataclass
class BudgetForecast:
    """Budget forecast based on current spending."""
    projected_daily: float = 0.0
    projected_monthly: float = 0.0
    will_exceed_daily: bool = False
    will_exceed_monthly: bool = False
    days_until_daily_limit: float = 0.0
    days_until_monthly_limit: float = 0.0


@dataclass
class BudgetReport:
    """Comprehensive budget report."""
    period: str = ""
    total_spend: float = 0.0
    daily_spend: float = 0.0
    monthly_spend: float = 0.0
    daily_remaining: float = 0.0
    monthly_remaining: float = 0.0
    by_model: dict[str, float] = field(default_factory=dict)
    by_purpose: dict[str, float] = field(default_factory=dict)
    daily_trend: list[dict] = field(default_factory=list)
    alerts: list[BudgetAlert] = field(default_factory=list)


class BudgetManager:
    """Tracks and enforces spending limits across the empire.

    Monitors daily, monthly, and per-task costs. Generates alerts
    at configurable thresholds and provides cost optimization suggestions.
    """

    def __init__(self, empire_id: str = ""):
        self.empire_id = empire_id
        self._settings = None

    def _get_settings(self):
        if self._settings is None:
            try:
                from config.settings import get_settings
                self._settings = get_settings().budget
            except Exception:
                from config.settings import BudgetSettings
                self._settings = BudgetSettings()
        return self._settings

    def record_spend(
        self,
        cost_usd: float,
        model: str,
        provider: str,
        task_id: str = "",
        lieutenant_id: str = "",
        purpose: str = "task_execution",
        tokens_input: int = 0,
        tokens_output: int = 0,
    ) -> None:
        """Record a spending event.

        Args:
            cost_usd: Cost in USD.
            model: Model used.
            provider: Provider name.
            task_id: Related task ID.
            lieutenant_id: Related lieutenant ID.
            purpose: Purpose of the spend.
            tokens_input: Input tokens used.
            tokens_output: Output tokens used.
        """
        try:
            from db.engine import session_scope
            from db.models import BudgetLog

            now = datetime.now(timezone.utc)

            with session_scope() as session:
                log = BudgetLog(
                    empire_id=self.empire_id,
                    model_used=model,
                    provider=provider,
                    tokens_input=tokens_input,
                    tokens_output=tokens_output,
                    cost_usd=cost_usd,
                    task_id=task_id or None,
                    lieutenant_id=lieutenant_id or None,
                    purpose=purpose,
                    cost_date=now.strftime("%Y-%m-%d"),
                    cost_month=now.strftime("%Y-%m"),
                )
                session.add(log)
        except Exception as e:
            logger.warning("Failed to record spend: %s", e)

    def check_budget(self, estimated_cost: float = 0.0) -> BudgetCheck:
        """Check if a spend is within budget.

        Args:
            estimated_cost: Estimated cost of the operation.

        Returns:
            BudgetCheck result.
        """
        settings = self._get_settings()
        daily = self.get_daily_spend()
        monthly = self.get_monthly_spend()

        daily_remaining = settings.daily_limit_usd - daily
        monthly_remaining = settings.monthly_limit_usd - monthly

        if estimated_cost > daily_remaining:
            return BudgetCheck(
                allowed=not settings.hard_stop_on_limit,
                remaining_daily=daily_remaining,
                remaining_monthly=monthly_remaining,
                warning="Daily budget exceeded" if daily_remaining <= 0 else "Would exceed daily budget",
                reason="daily_limit",
            )

        if estimated_cost > monthly_remaining:
            return BudgetCheck(
                allowed=not settings.hard_stop_on_limit,
                remaining_daily=daily_remaining,
                remaining_monthly=monthly_remaining,
                warning="Monthly budget exceeded" if monthly_remaining <= 0 else "Would exceed monthly budget",
                reason="monthly_limit",
            )

        if estimated_cost > settings.per_task_limit_usd:
            return BudgetCheck(
                allowed=False,
                remaining_daily=daily_remaining,
                remaining_monthly=monthly_remaining,
                warning=f"Exceeds per-task limit (${settings.per_task_limit_usd})",
                reason="per_task_limit",
            )

        warning = ""
        daily_pct = (daily + estimated_cost) / settings.daily_limit_usd * 100 if settings.daily_limit_usd > 0 else 0
        if daily_pct >= settings.alert_threshold_percent:
            warning = f"Daily spend at {daily_pct:.0f}% of limit"

        return BudgetCheck(
            allowed=True,
            remaining_daily=daily_remaining,
            remaining_monthly=monthly_remaining,
            warning=warning,
        )

    def get_daily_spend(self) -> float:
        """Get total spend for today."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self._get_spend_for_date(today)

    def get_monthly_spend(self) -> float:
        """Get total spend for this month."""
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        return self._get_spend_for_month(month)

    def get_remaining_daily(self) -> float:
        """Get remaining daily budget."""
        return self._get_settings().daily_limit_usd - self.get_daily_spend()

    def get_remaining_monthly(self) -> float:
        """Get remaining monthly budget."""
        return self._get_settings().monthly_limit_usd - self.get_monthly_spend()

    def is_over_budget(self) -> bool:
        """Check if currently over budget."""
        return self.get_remaining_daily() <= 0 or self.get_remaining_monthly() <= 0

    def get_spend_by_model(self, days: int = 30) -> dict[str, float]:
        """Get spend breakdown by model."""
        try:
            from db.engine import get_session
            from db.repositories.task import TaskRepository
            session = get_session()
            repo = TaskRepository(session)
            stats = repo.get_cost_aggregation(days=days)
            return {k: v.get("total_cost", 0) for k, v in stats.get("by_model", {}).items()}
        except Exception:
            return {}

    def get_budget_alerts(self) -> list[BudgetAlert]:
        """Get current budget alerts."""
        settings = self._get_settings()
        alerts = []

        daily = self.get_daily_spend()
        monthly = self.get_monthly_spend()

        daily_pct = daily / settings.daily_limit_usd * 100 if settings.daily_limit_usd > 0 else 0
        monthly_pct = monthly / settings.monthly_limit_usd * 100 if settings.monthly_limit_usd > 0 else 0

        if daily_pct >= 100:
            alerts.append(BudgetAlert(
                alert_type="exceeded",
                message=f"Daily budget exceeded: ${daily:.2f} / ${settings.daily_limit_usd:.2f}",
                severity="critical",
                threshold_percent=100,
                current_percent=daily_pct,
            ))
        elif daily_pct >= settings.alert_threshold_percent:
            alerts.append(BudgetAlert(
                alert_type="warning",
                message=f"Daily budget at {daily_pct:.0f}%: ${daily:.2f} / ${settings.daily_limit_usd:.2f}",
                severity="high",
                threshold_percent=settings.alert_threshold_percent,
                current_percent=daily_pct,
            ))

        if monthly_pct >= 100:
            alerts.append(BudgetAlert(
                alert_type="exceeded",
                message=f"Monthly budget exceeded: ${monthly:.2f} / ${settings.monthly_limit_usd:.2f}",
                severity="critical",
                threshold_percent=100,
                current_percent=monthly_pct,
            ))
        elif monthly_pct >= settings.alert_threshold_percent:
            alerts.append(BudgetAlert(
                alert_type="warning",
                message=f"Monthly budget at {monthly_pct:.0f}%",
                severity="high",
                threshold_percent=settings.alert_threshold_percent,
                current_percent=monthly_pct,
            ))

        return alerts

    def get_budget_forecast(self, days: int = 7) -> BudgetForecast:
        """Forecast budget based on recent spending patterns.

        Args:
            days: Number of days to look ahead.

        Returns:
            BudgetForecast.
        """
        settings = self._get_settings()
        daily = self.get_daily_spend()

        # Simple projection based on today's rate
        projected_daily = daily  # Today's pace
        projected_monthly = daily * 30  # Extrapolate to month

        daily_remaining = settings.daily_limit_usd - daily
        monthly_remaining = settings.monthly_limit_usd - self.get_monthly_spend()

        days_until_daily = daily_remaining / max(daily / max(1, 1), 0.001) if daily > 0 else float("inf")
        days_until_monthly = monthly_remaining / max(daily, 0.001) if daily > 0 else float("inf")

        return BudgetForecast(
            projected_daily=projected_daily,
            projected_monthly=projected_monthly,
            will_exceed_daily=daily >= settings.daily_limit_usd,
            will_exceed_monthly=projected_monthly >= settings.monthly_limit_usd,
            days_until_daily_limit=min(days_until_daily, 999),
            days_until_monthly_limit=min(days_until_monthly, 999),
        )

    def get_budget_report(self, days: int = 30) -> BudgetReport:
        """Generate comprehensive budget report."""
        settings = self._get_settings()
        daily = self.get_daily_spend()
        monthly = self.get_monthly_spend()

        return BudgetReport(
            period=f"Last {days} days",
            total_spend=monthly,
            daily_spend=daily,
            monthly_spend=monthly,
            daily_remaining=settings.daily_limit_usd - daily,
            monthly_remaining=settings.monthly_limit_usd - monthly,
            by_model=self.get_spend_by_model(days),
            alerts=self.get_budget_alerts(),
        )

    def _get_spend_for_date(self, date_str: str) -> float:
        """Get total spend for a specific date."""
        try:
            from db.engine import get_session
            from sqlalchemy import select, func
            from db.models import BudgetLog

            session = get_session()
            try:
                result = session.execute(
                    select(func.coalesce(func.sum(BudgetLog.cost_usd), 0.0))
                    .where(BudgetLog.empire_id == self.empire_id)
                    .where(BudgetLog.cost_date == date_str)
                ).scalar()
                return float(result or 0.0)
            finally:
                session.close()
        except Exception:
            return 0.0

    def _get_spend_for_month(self, month_str: str) -> float:
        """Get total spend for a specific month."""
        try:
            from db.engine import get_session
            from sqlalchemy import select, func
            from db.models import BudgetLog

            session = get_session()
            try:
                result = session.execute(
                    select(func.coalesce(func.sum(BudgetLog.cost_usd), 0.0))
                    .where(BudgetLog.empire_id == self.empire_id)
                    .where(BudgetLog.cost_month == month_str)
                ).scalar()
                return float(result or 0.0)
            finally:
                session.close()
        except Exception:
            return 0.0

"""Budget dashboard routes."""

from __future__ import annotations

import logging
from flask import Blueprint, render_template, jsonify, request, current_app

logger = logging.getLogger(__name__)
budget_bp = Blueprint("budget", __name__)


@budget_bp.route("/")
def budget_overview():
    """Budget overview page."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    try:
        from core.routing.budget import BudgetManager
        bm = BudgetManager(empire_id)
        report = bm.get_budget_report(days=30)
        forecast = bm.get_budget_forecast()
        alerts = bm.get_budget_alerts()

        return render_template("budget/overview.html",
            report={
                "daily_spend": report.daily_spend,
                "monthly_spend": report.monthly_spend,
                "daily_remaining": report.daily_remaining,
                "monthly_remaining": report.monthly_remaining,
                "by_model": report.by_model,
            },
            forecast={
                "projected_daily": forecast.projected_daily,
                "projected_monthly": forecast.projected_monthly,
                "will_exceed_daily": forecast.will_exceed_daily,
                "will_exceed_monthly": forecast.will_exceed_monthly,
                "days_until_daily": forecast.days_until_daily_limit,
                "days_until_monthly": forecast.days_until_monthly_limit,
            },
            alerts=[{"message": a.message, "severity": a.severity, "type": a.alert_type} for a in alerts],
        )
    except Exception as e:
        return render_template("budget/overview.html", report={}, forecast={}, alerts=[], error=str(e))


@budget_bp.route("/daily")
def daily_spend():
    """Get daily spend data."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    try:
        from db.engine import get_session
        from db.repositories.empire import EmpireRepository
        session = get_session()
        try:
            repo = EmpireRepository(session)
            daily = repo.get_daily_spend(empire_id, days=30)
            return jsonify(daily)
        finally:
            session.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@budget_bp.route("/by-model")
def spend_by_model():
    """Get spend breakdown by model."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    from core.routing.budget import BudgetManager
    bm = BudgetManager(empire_id)
    return jsonify(bm.get_spend_by_model(days=30))


@budget_bp.route("/forecast")
def budget_forecast():
    """Get budget forecast."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    from core.routing.budget import BudgetManager
    bm = BudgetManager(empire_id)
    f = bm.get_budget_forecast()
    return jsonify({
        "projected_daily": f.projected_daily,
        "projected_monthly": f.projected_monthly,
        "will_exceed_daily": f.will_exceed_daily,
        "will_exceed_monthly": f.will_exceed_monthly,
    })


@budget_bp.route("/optimize")
def cost_optimization():
    """Get cost optimization suggestions."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    try:
        from core.routing.pricing import PricingEngine
        engine = PricingEngine()
        comparisons = engine.compare_models(task_type="general", complexity="moderate")
        return jsonify({
            "model_comparison": comparisons,
            "suggestion": "Use cheaper models for simple tasks, premium models only for complex analysis",
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

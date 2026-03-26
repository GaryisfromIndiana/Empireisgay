"""Flask application factory and main entry point."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from flask import Flask

logger = logging.getLogger(__name__)


def create_app(config: dict | None = None) -> Flask:
    """Create and configure the Flask application.

    Args:
        config: Optional configuration overrides.

    Returns:
        Configured Flask application.
    """
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).parent / "templates"),
        static_folder=str(Path(__file__).parent / "static"),
    )

    # Load settings
    from config.settings import get_settings
    settings = get_settings()

    app.config["SECRET_KEY"] = settings.flask_secret_key
    app.config["DEBUG"] = settings.flask_debug
    app.config["EMPIRE_ID"] = settings.empire_id
    app.config["EMPIRE_NAME"] = settings.empire_name

    if config:
        app.config.update(config)

    # Initialize database
    with app.app_context():
        from db.engine import init_db
        init_db()

    # Register blueprints
    from web.routes.dashboard import dashboard_bp
    from web.routes.lieutenants import lieutenants_bp
    from web.routes.directives import directives_bp
    from web.routes.knowledge import knowledge_bp
    from web.routes.warrooms import warrooms_bp
    from web.routes.evolution import evolution_bp
    from web.routes.settings import settings_bp
    from web.routes.api import api_bp
    from web.routes.memory import memory_bp
    from web.routes.scheduler import scheduler_bp
    from web.routes.budget import budget_bp
    from web.routes.replication import replication_bp
    from web.routes.god_panel import god_panel_bp

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(lieutenants_bp, url_prefix="/lieutenants")
    app.register_blueprint(directives_bp, url_prefix="/directives")
    app.register_blueprint(knowledge_bp, url_prefix="/knowledge")
    app.register_blueprint(warrooms_bp, url_prefix="/warrooms")
    app.register_blueprint(evolution_bp, url_prefix="/evolution")
    app.register_blueprint(settings_bp, url_prefix="/settings")
    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(memory_bp, url_prefix="/memory")
    app.register_blueprint(scheduler_bp, url_prefix="/scheduler")
    app.register_blueprint(budget_bp, url_prefix="/budget")
    app.register_blueprint(replication_bp, url_prefix="/network")
    app.register_blueprint(god_panel_bp, url_prefix="/god")

    # ── Authentication ──────────────────────────────────────────────
    from web.middleware.auth import require_login, require_api_auth, _is_auth_enabled, _check_password, _get_auth_config

    @app.route("/login", methods=["GET", "POST"])
    def login():
        from flask import render_template, session as flask_session
        if request.method == "POST":
            username = request.form.get("username", "")
            password = request.form.get("password", "")
            auth_user, _, _ = _get_auth_config()
            if username == auth_user and _check_password(password):
                flask_session["authenticated"] = True
                return redirect("/")
            return render_template("login.html", error="Invalid credentials")
        return render_template("login.html")

    @app.route("/logout")
    def logout():
        from flask import session as flask_session
        flask_session.clear()
        return redirect("/login")

    # Protect all web routes
    @app.before_request
    def check_auth():
        if not _is_auth_enabled():
            return None
        # Allow login/logout/health/static
        exempt = ["/login", "/logout", "/static", "/api/health"]
        for path in exempt:
            if request.path.startswith(path):
                return None
        # API routes use API key auth
        if request.path.startswith("/api/"):
            api_key = request.headers.get("X-API-Key", "")
            if api_key:
                from web.middleware.auth import _check_api_key
                if _check_api_key(api_key):
                    return None
                return jsonify({"error": "Invalid API key"}), 401
            if not session.get("authenticated"):
                return jsonify({"error": "Unauthorized"}), 401
            return None
        # Web routes use session auth
        if not session.get("authenticated"):
            return redirect("/login")
        return None

    # Context processors
    @app.context_processor
    def inject_globals():
        return {
            "empire_name": app.config.get("EMPIRE_NAME", "Empire"),
            "empire_id": app.config.get("EMPIRE_ID", ""),
            "auth_enabled": _is_auth_enabled(),
        }

    # Error handlers
    @app.errorhandler(404)
    def not_found(e):
        return {"error": "Not found"}, 404

    @app.errorhandler(500)
    def server_error(e):
        logger.error("Server error: %s", e)
        return {"error": "Internal server error"}, 500

    # Start scheduler daemon — every worker gets a daemon object,
    # but only auto-starts on Postgres. Multiple start() calls are safe
    # because SchedulerDaemon.start() is a no-op if already running.
    import os
    is_worker = os.environ.get("WERKZEUG_RUN_MAIN") == "true" or not app.config.get("DEBUG")
    if is_worker:
        try:
            from core.scheduler.daemon import SchedulerDaemon
            empire_id = app.config.get("EMPIRE_ID", "")
            daemon = SchedulerDaemon(empire_id, tick_interval=300)  # 5 min ticks
            app.config["_SCHEDULER_DAEMON"] = daemon

            if "postgresql" in settings.db_url:
                daemon.start()
                logger.info("Scheduler daemon STARTED (Postgres — 5 min ticks)")
            else:
                logger.info("Scheduler daemon ready (SQLite — use /scheduler/start)")
        except Exception as e:
            logger.warning("Could not create scheduler: %s", e)

    logger.info("Empire web app created: %s", settings.empire_name)
    return app


def main():
    """Run the Flask development server."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    from config.settings import get_settings
    settings = get_settings()

    app = create_app()
    app.run(
        host=settings.flask_host,
        port=settings.flask_port,
        debug=settings.flask_debug,
    )


if __name__ == "__main__":
    main()

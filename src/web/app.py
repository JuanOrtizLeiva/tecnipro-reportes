"""Servidor web Flask para el dashboard de Tecnipro."""

import logging
import secrets
from datetime import timedelta

from flask import Flask, session, request, abort
from flask_cors import CORS

from config import settings
from src.web.auth import login_manager

logger = logging.getLogger(__name__)


def create_app():
    """Factory para crear la aplicación Flask."""
    app = Flask(
        __name__,
        template_folder=str(settings.TEMPLATES_PATH),
    )

    # Secret key para sesiones
    app.secret_key = settings.SECRET_KEY

    # Configuración de sesión
    app.config["REMEMBER_COOKIE_DURATION"] = timedelta(
        hours=settings.SESSION_LIFETIME_HOURS
    )
    app.config["REMEMBER_COOKIE_HTTPONLY"] = True
    app.config["REMEMBER_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(
        hours=settings.SESSION_LIFETIME_HOURS
    )

    # CORS: solo localhost por defecto
    CORS(app, origins=["http://localhost:*", "http://127.0.0.1:*"])

    # Flask-Login
    login_manager.init_app(app)

    # ── CSRF Protection ──────────────────────────────────────
    # Rutas exentas: login (genera sesión), health, status checks
    CSRF_EXEMPT = {"/login", "/forgot-password", "/reset-password", "/api/health"}

    @app.before_request
    def csrf_protect():
        if request.method in ("GET", "HEAD", "OPTIONS"):
            # Generar token si no existe en sesión
            if "_csrf_token" not in session:
                session["_csrf_token"] = secrets.token_hex(32)
            return
        # POST/PUT/DELETE: validar token (excepto rutas exentas)
        if request.path in CSRF_EXEMPT:
            return
        # API JSON usa header X-CSRFToken; formularios HTML usan campo oculto
        token = (
            request.headers.get("X-CSRFToken")
            or (request.form.get("csrf_token") if request.form else None)
        )
        if not token or token != session.get("_csrf_token"):
            logger.warning("CSRF token inválido en %s desde %s", request.path, request.remote_addr)
            abort(403)

    @app.context_processor
    def inject_csrf():
        """Inyectar csrf_token en todos los templates."""
        if "_csrf_token" not in session:
            session["_csrf_token"] = secrets.token_hex(32)
        return {"csrf_token": session["_csrf_token"]}

    # Security headers
    @app.after_request
    def add_security_headers(response):
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    # Registrar rutas
    from src.web.routes import register_routes
    register_routes(app)

    return app


# Expuesto para gunicorn: gunicorn src.web.app:app
app = create_app()

if __name__ == "__main__":
    app.run(
        host=settings.WEB_HOST,
        port=settings.WEB_PORT,
        debug=False,
    )

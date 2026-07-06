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
    # Límite de subida de archivos (panel Compras Ágiles: activos hasta ~20 MB)
    app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024

    # CORS: localhost + dominios Tecnipro (para caso de profundización en Moodle)
    CORS(app, origins=[
        "http://localhost:*",
        "http://127.0.0.1:*",
        "https://reportes.tecnipro.cl",
        "https://tecnipro.cl",
        "https://www.tecnipro.cl",
        "https://*.tecnipro.cl",
        "https://virtual.institutotecnipro.cl",
        "https://*.institutotecnipro.cl",
    ])

    # Flask-Login
    login_manager.init_app(app)

    # ── CSRF Protection ──────────────────────────────────────
    # Rutas exentas de CSRF:
    #   - Formularios de auth (generan sesión nueva)
    #   - Rutas /api/* (protegidas por @login_required + JSON, no formularios HTML)
    CSRF_EXEMPT = {"/login", "/forgot-password", "/reset-password", "/api/health"}

    @app.before_request
    def csrf_protect():
        if request.method in ("GET", "HEAD", "OPTIONS"):
            # Generar token si no existe en sesión
            if "_csrf_token" not in session:
                session["_csrf_token"] = secrets.token_hex(32)
            return
        # POST/PUT/DELETE: validar token (excepto rutas exentas)
        if request.path in CSRF_EXEMPT or request.path.startswith("/api/"):
            return
        # Formularios HTML usan campo oculto csrf_token
        token = (
            request.headers.get("X-CSRFToken")
            or (request.form.get("csrf_token") if request.form else None)
        )
        if not token or token != session.get("_csrf_token"):
            logger.warning("CSRF token inválido en %s desde %s", request.path, request.remote_addr)
            abort(403)

    @app.context_processor
    def inject_csrf():
        """Inyectar csrf_token y config en todos los templates."""
        if "_csrf_token" not in session:
            session["_csrf_token"] = secrets.token_hex(32)
        return {"csrf_token": session["_csrf_token"], "config": settings}

    # Security headers
    @app.after_request
    def add_security_headers(response):
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    # Inicializar PostgreSQL (si configurado)
    if settings.USE_PG:
        try:
            from src.database import init_db
            init_db()
        except Exception as e:
            logger.warning("PostgreSQL no disponible: %s (dashboard usará JSON)", e)

    # Registrar rutas
    from src.web.routes import register_routes
    register_routes(app)

    from src.web.routes_sii_monitor import register_sii_monitor_routes
    register_sii_monitor_routes(app)

    from src.web.routes_evalpro import register_evalpro_routes
    register_evalpro_routes(app)

    from src.web.routes_envios import register_envios_routes
    register_envios_routes(app)

    from src.web.routes_evaluar_caso import register_evaluar_caso_routes
    register_evaluar_caso_routes(app)

    from src.web.routes_fundacion import register_routes as register_fundacion_routes
    register_fundacion_routes(app)

    from src.web.routes_compras_agiles import register_routes as register_compras_agiles_routes
    register_compras_agiles_routes(app)

    from src.web.routes_certificados import register_certificados_routes
    register_certificados_routes(app)

    return app


# Expuesto para gunicorn: gunicorn src.web.app:app
app = create_app()

if __name__ == "__main__":
    app.run(
        host=settings.WEB_HOST,
        port=settings.WEB_PORT,
        debug=False,
    )

"""Servidor web Flask para el dashboard de Tecnipro."""

import logging

from flask import Flask
from flask_cors import CORS

from config import settings

logger = logging.getLogger(__name__)


def create_app():
    """Factory para crear la aplicación Flask."""
    app = Flask(
        __name__,
        template_folder=str(settings.TEMPLATES_PATH),
    )

    # CORS: solo localhost por defecto
    CORS(app, origins=["http://localhost:*", "http://127.0.0.1:*"])

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

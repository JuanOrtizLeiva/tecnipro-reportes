"""Rutas del servidor web del dashboard."""

import json
import logging
import time
from collections import defaultdict
from pathlib import Path

from flask import jsonify, render_template, request

from config import settings

logger = logging.getLogger(__name__)

# Rate limiting para envío de correo: máximo 10 por minuto
_email_timestamps = defaultdict(list)
RATE_LIMIT_MAX = 10
RATE_LIMIT_WINDOW = 60  # segundos


def _check_rate_limit(ip):
    """Retorna True si el IP excedió el límite de envíos."""
    now = time.time()
    # Limpiar timestamps viejos
    _email_timestamps[ip] = [
        t for t in _email_timestamps[ip] if now - t < RATE_LIMIT_WINDOW
    ]
    if len(_email_timestamps[ip]) >= RATE_LIMIT_MAX:
        return True
    _email_timestamps[ip].append(now)
    return False


def register_routes(app):
    """Registra todas las rutas en la app Flask."""

    @app.route("/")
    def index():
        """Sirve el dashboard HTML."""
        return render_template("dashboard.html")

    @app.route("/api/datos")
    def api_datos():
        """Retorna datos_procesados.json."""
        json_path = settings.JSON_DATOS_PATH
        if not json_path.exists():
            return jsonify({
                "error": "No se encontró datos_procesados.json. "
                         "Ejecute el pipeline primero: python -m src.main"
            }), 404

        with open(json_path, "r", encoding="utf-8") as f:
            datos = json.load(f)

        return jsonify(datos)

    @app.route("/api/health")
    def api_health():
        """Health check."""
        json_path = settings.JSON_DATOS_PATH
        fecha_datos = None
        if json_path.exists():
            with open(json_path, "r", encoding="utf-8") as f:
                datos = json.load(f)
            fecha_datos = datos.get("metadata", {}).get("fecha_procesamiento")

        return jsonify({
            "status": "ok",
            "fecha_datos": fecha_datos,
        })

    @app.route("/api/enviar-correo", methods=["POST"])
    def api_enviar_correo():
        """Envía correo a participantes seleccionados."""
        # Rate limiting
        client_ip = request.remote_addr or "unknown"
        if _check_rate_limit(client_ip):
            return jsonify({
                "error": "Demasiados envíos. Máximo 10 por minuto."
            }), 429

        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error": "Body JSON requerido"}), 400

        destinatarios = data.get("destinatarios", [])
        asunto = data.get("asunto", "").strip()
        cuerpo = data.get("cuerpo", "").strip()
        cc = data.get("cc", [])

        if not destinatarios:
            return jsonify({"error": "Se requiere al menos un destinatario"}), 400
        if not asunto:
            return jsonify({"error": "Se requiere asunto"}), 400
        if not cuerpo:
            return jsonify({"error": "Se requiere cuerpo del mensaje"}), 400

        # Convertir cuerpo texto plano a HTML básico
        cuerpo_html = cuerpo.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        cuerpo_html = "<p>" + cuerpo_html.replace("\n\n", "</p><p>").replace("\n", "<br>") + "</p>"

        from src.reports.email_sender import enviar_correo

        email_str = ", ".join(destinatarios)
        cc_str = ", ".join(cc) if cc else settings.EMAIL_CC

        resultado = enviar_correo(
            destinatario=email_str,
            asunto=asunto,
            cuerpo_html=cuerpo_html,
            cc=cc_str,
            dry_run=False,
        )

        if resultado["status"] == "OK":
            logger.info("Correo enviado desde dashboard a %s", destinatarios)
            return jsonify({
                "status": "ok",
                "enviados": len(destinatarios),
            })
        else:
            logger.error("Error enviando correo desde dashboard: %s", resultado["detalle"])
            return jsonify({
                "error": resultado["detalle"],
            }), 500

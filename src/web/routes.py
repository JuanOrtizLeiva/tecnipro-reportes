"""Rutas del servidor web del dashboard."""

import json
import logging
import time
from collections import defaultdict
from pathlib import Path

from flask import jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user

from config import settings
from src.web.auth import check_login_rate_limit, verify_password

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

    # ── Login / Logout ────────────────────────────────────

    @app.route("/login", methods=["GET", "POST"])
    def login():
        """Página de login."""
        # Si ya está logueado, redirigir al dashboard
        if current_user.is_authenticated:
            return redirect(url_for("index"))

        if request.method == "GET":
            return render_template("login.html")

        # POST: verificar credenciales
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        # Rate limiting
        client_ip = request.remote_addr or "unknown"
        if check_login_rate_limit(client_ip):
            return render_template(
                "login.html",
                error="Demasiados intentos. Espere 15 minutos.",
                email=email,
            ), 429

        if not email or not password:
            return render_template(
                "login.html",
                error="Ingrese correo y contraseña.",
                email=email,
            )

        user = verify_password(email, password)
        if user is None:
            return render_template(
                "login.html",
                error="Credenciales inválidas.",
                email=email,
            )

        login_user(user, remember=True)
        session.permanent = True
        logger.info("Login exitoso: %s (%s)", user.email, user.rol)
        return redirect(url_for("index"))

    @app.route("/logout")
    def logout():
        """Destruye sesión y redirige al login."""
        if current_user.is_authenticated:
            logger.info("Logout: %s", current_user.email)
        logout_user()
        session.clear()
        return redirect(url_for("login"))

    # ── Dashboard ─────────────────────────────────────────

    @app.route("/")
    @login_required
    def index():
        """Sirve el dashboard HTML."""
        return render_template("dashboard.html")

    # ── API: info del usuario ─────────────────────────────

    @app.route("/api/me")
    @login_required
    def api_me():
        """Retorna información del usuario actual."""
        return jsonify(current_user.to_dict())

    # ── API: datos ────────────────────────────────────────

    @app.route("/api/datos")
    @login_required
    def api_datos():
        """Retorna datos_procesados.json, filtrado por rol."""
        json_path = settings.JSON_DATOS_PATH
        if not json_path.exists():
            return jsonify({
                "error": "No se encontró datos_procesados.json. "
                         "Ejecute el pipeline primero: python -m src.main"
            }), 404

        with open(json_path, "r", encoding="utf-8") as f:
            datos = json.load(f)

        # Admin (or unauthenticated when LOGIN_DISABLED) ve todo
        if not current_user.is_authenticated or current_user.rol == "admin":
            return jsonify(datos)

        # Comprador: filtrar solo sus cursos
        cursos_filtrados = [
            c for c in datos.get("cursos", [])
            if int(c.get("id_moodle", 0)) in current_user.cursos
        ]
        datos_filtrados = {
            "metadata": dict(datos.get("metadata", {})),
            "cursos": cursos_filtrados,
        }
        # Recalcular metadata
        datos_filtrados["metadata"]["total_cursos"] = len(cursos_filtrados)
        datos_filtrados["metadata"]["total_estudiantes"] = sum(
            len(c.get("estudiantes", [])) for c in cursos_filtrados
        )
        return jsonify(datos_filtrados)

    # ── API: health (pública) ─────────────────────────────

    @app.route("/api/health")
    def api_health():
        """Health check — público, no requiere autenticación."""
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

    # ── API: enviar correo (solo admin) ───────────────────

    @app.route("/api/enviar-correo", methods=["POST"])
    @login_required
    def api_enviar_correo():
        """Envía correo a participantes seleccionados. Solo admin."""
        # Solo admin puede enviar correos
        if current_user.is_authenticated and current_user.rol != "admin":
            return jsonify({"error": "No autorizado"}), 403

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

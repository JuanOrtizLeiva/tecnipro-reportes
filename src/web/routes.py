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

        login_user(user, remember=False)  # No usar remember_me cookie
        session.permanent = True  # Sesión permanente por SESSION_LIFETIME_HOURS
        logger.info("Login exitoso: %s (%s)", user.email, user.rol)
        return redirect(url_for("index"))

    @app.route("/logout")
    def logout():
        """Destruye sesión y redirige al login."""
        if current_user.is_authenticated:
            logger.info("Logout: %s", current_user.email)

        # Cerrar sesión de Flask-Login
        logout_user()

        # Limpiar sesión de Flask
        session.clear()

        # Crear respuesta y eliminar cookies explícitamente
        response = redirect(url_for("login"))
        response.delete_cookie("session")
        response.delete_cookie("remember_token")

        # También eliminar la cookie de sesión de Flask (por si tiene otro nombre)
        response.set_cookie("session", "", expires=0)

        return response

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

    # ── API: refresh datos (solo admin) ──────────────────

    @app.route("/api/refresh", methods=["POST"])
    @login_required
    def api_refresh():
        """Ejecuta el pipeline para refrescar datos desde Moodle API. Solo admin."""
        # Solo admin puede refrescar datos
        if current_user.is_authenticated and current_user.rol != "admin":
            return jsonify({"error": "No autorizado"}), 403

        # Importar y ejecutar pipeline en el mismo thread
        # (En producción con Gunicorn esto no bloqueará otras requests)
        try:
            from src.main import run_pipeline
            logger.info("Iniciando refresh manual de datos por %s", current_user.email)

            # Ejecutar pipeline
            datos_json = run_pipeline()

            logger.info("Refresh completado exitosamente")
            return jsonify({
                "status": "ok",
                "message": "Datos actualizados exitosamente",
                "cursos": datos_json["metadata"]["total_cursos"],
                "estudiantes": datos_json["metadata"]["total_estudiantes"],
                "fecha": datos_json["metadata"]["fecha_procesamiento"]
            })

        except Exception as e:
            logger.error("Error ejecutando pipeline desde API: %s", e, exc_info=True)
            return jsonify({
                "error": f"Error al actualizar datos: {str(e)}"
            }), 500

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

    # ── API: descargar Excel ──────────────────────────────

    @app.route("/api/descargar-excel")
    @login_required
    def api_descargar_excel():
        """Genera y descarga un archivo Excel con los datos visibles."""
        from datetime import datetime
        from io import BytesIO
        from flask import send_file
        from openpyxl import Workbook
        from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

        # Cargar datos
        json_path = settings.JSON_DATOS_PATH
        if not json_path.exists():
            return jsonify({"error": "No hay datos disponibles"}), 404

        with open(json_path, "r", encoding="utf-8") as f:
            datos = json.load(f)

        # Filtrar por rol
        cursos = datos.get("cursos", [])
        if current_user.is_authenticated and current_user.rol == "comprador":
            cursos = [c for c in cursos if int(c.get("id_moodle", 0)) in current_user.cursos]

        # Filtrar por parámetro de query (cursos visibles)
        cursos_param = request.args.get("cursos", "")
        if cursos_param:
            ids_visibles = set(cursos_param.split(","))
            cursos = [c for c in cursos if c.get("id_moodle") in ids_visibles]

        if not cursos:
            return jsonify({"error": "No hay cursos para descargar"}), 404

        # Crear workbook
        wb = Workbook()
        wb.remove(wb.active)  # Remover hoja por defecto

        # Estilos
        header_fill = PatternFill(start_color="2563EB", end_color="2563EB", fill_type="solid")
        header_font = Font(bold=True, color="FFFFFF", size=11)
        title_font = Font(bold=True, size=13)
        subtitle_font = Font(size=11, italic=True)
        border = Border(
            left=Side(style='thin'),
            right=Side(style='thin'),
            top=Side(style='thin'),
            bottom=Side(style='thin')
        )

        # Helper para sanear nombres de hoja (Excel no permite / \ ? * [ ] :)
        def sanitizar_nombre_hoja(nombre):
            nombre = nombre.replace('/', ' ').replace('\\', ' ')
            nombre = nombre.replace('?', '').replace('*', '')
            nombre = nombre.replace('[', '(').replace(']', ')')
            nombre = nombre.replace(':', '-')
            return nombre[:31]  # Límite de Excel

        # Crear hoja índice
        ws_index = wb.create_sheet(title="Índice", index=0)
        ws_index['A1'] = "Instituto de Capacitaciones Tecnipro"
        ws_index['A1'].font = Font(bold=True, size=16)
        ws_index['A2'] = "Reporte de Capacitación"
        ws_index['A2'].font = title_font
        ws_index['A3'] = f"Fecha: {datetime.now().strftime('%d/%m/%Y')}"
        ws_index['A3'].font = subtitle_font

        # Headers de tabla índice
        index_headers = ["N°", "ID Curso", "Nombre del Curso", "Participantes", "Progreso Promedio", "Aprobados", "Estado"]
        for col_idx, header in enumerate(index_headers, start=1):
            cell = ws_index.cell(row=5, column=col_idx, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal='center')
            cell.border = border

        # Crear hojas de cursos y llenar índice
        for idx, curso in enumerate(cursos, start=1):
            # Nombre de hoja: usar nombre corto o nombre completo (sanitizado)
            nombre_base = curso.get("nombre_corto") or curso.get("nombre") or curso.get("id_moodle", "Curso")
            nombre_hoja = sanitizar_nombre_hoja(nombre_base)
            ws = wb.create_sheet(title=nombre_hoja)

            # Fila en índice (5 es header, 6 es primera fila de datos)
            row_index = idx + 5
            stats = curso.get("estadisticas", {})

            # Llenar fila de índice
            ws_index.cell(row=row_index, column=1, value=idx).border = border
            ws_index.cell(row=row_index, column=2, value=curso.get("id_moodle", "")).border = border

            # Nombre con hyperlink a la hoja del curso
            cell_nombre = ws_index.cell(row=row_index, column=3, value=curso.get("nombre", "Sin nombre"))
            cell_nombre.hyperlink = f"#{nombre_hoja}!A1"
            cell_nombre.font = Font(color="0563C1", underline="single")
            cell_nombre.border = border

            ws_index.cell(row=row_index, column=4, value=stats.get("total_estudiantes", 0)).border = border
            ws_index.cell(row=row_index, column=5, value=f"{stats.get('promedio_progreso', 0):.1f}%").border = border
            ws_index.cell(row=row_index, column=6, value=stats.get("aprobados", 0)).border = border

            estado_curso = "Activo" if curso.get("dias_restantes", 0) >= 0 else "Vencido"
            ws_index.cell(row=row_index, column=7, value=estado_curso).border = border

            # Header del curso (filas 1-3)
            ws.merge_cells('A1:J1')
            ws['A1'] = curso.get("nombre", "Sin nombre")
            ws['A1'].font = title_font
            ws['A1'].alignment = Alignment(horizontal='center')

            # Link de retorno al índice (fila 2)
            ws.merge_cells('A2:J2')
            ws['A2'] = "← Volver al Índice"
            ws['A2'].hyperlink = "#Índice!A1"
            ws['A2'].font = Font(color="0563C1", underline="single", size=10)
            ws['A2'].alignment = Alignment(horizontal='center')

            # Info del curso (fila 3)
            ws.merge_cells('A3:J3')
            info_curso = f"ID Moodle: {curso.get('id_moodle', '—')} | ID SENCE: {curso.get('id_sence', '—')} | {curso.get('fecha_inicio', '—')} a {curso.get('fecha_fin', '—')}"
            ws['A3'] = info_curso
            ws['A3'].alignment = Alignment(horizontal='center')
            ws['A3'].font = subtitle_font

            # Headers de columnas (fila 5)
            headers = [
                "Nombre", "RUT", "Correo", "Progreso (%)", "Calificación",
                "Estado", "Riesgo", "Conexiones SENCE", "DJ", "Días sin acceso"
            ]
            for col_idx, header in enumerate(headers, start=1):
                cell = ws.cell(row=5, column=col_idx, value=header)
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = Alignment(horizontal='center')
                cell.border = border

            # Datos de estudiantes
            estudiantes = curso.get("estudiantes", [])
            for row_idx, est in enumerate(estudiantes, start=6):
                sence = est.get("sence") or {}
                estado_texto = {"A": "Aprobado", "R": "Reprobado", "P": "En proceso"}.get(est.get("estado", ""), "—")

                valores = [
                    est.get("nombre", ""),
                    est.get("id", ""),
                    est.get("email", ""),
                    est.get("progreso", 0),
                    est.get("calificacion", 0),
                    estado_texto,
                    est.get("riesgo", "").capitalize() or "—",
                    sence.get("n_ingresos", 0) if sence else 0,
                    sence.get("declaracion_jurada", "—") if sence else "—",
                    est.get("dias_sin_ingreso", 0)
                ]

                for col_idx, valor in enumerate(valores, start=1):
                    cell = ws.cell(row=row_idx, column=col_idx, value=valor)
                    cell.border = border
                    if col_idx in (4, 5):  # Progreso y Calificación
                        cell.alignment = Alignment(horizontal='center')

            # Fila de resumen
            stats = curso.get("estadisticas", {})
            row_resumen = len(estudiantes) + 7
            ws.merge_cells(f'A{row_resumen}:B{row_resumen}')
            ws[f'A{row_resumen}'] = "RESUMEN"
            ws[f'A{row_resumen}'].font = Font(bold=True)

            ws[f'C{row_resumen}'] = f"Total: {stats.get('total_estudiantes', 0)}"
            ws[f'D{row_resumen}'] = f"Promedio: {stats.get('promedio_progreso', 0):.1f}%"
            ws[f'E{row_resumen}'] = f"Promedio: {stats.get('promedio_calificacion', 0):.1f}"
            ws[f'F{row_resumen}'] = f"A:{stats.get('aprobados', 0)} R:{stats.get('reprobados', 0)} P:{stats.get('en_proceso', 0)}"
            ws[f'G{row_resumen}'] = f"Alto:{stats.get('riesgo_alto', 0)} Medio:{stats.get('riesgo_medio', 0)}"
            ws[f'H{row_resumen}'] = f"Conectados: {stats.get('conectados_sence', 0)}"

            # Ajustar anchos de columna
            ws.column_dimensions['A'].width = 35
            ws.column_dimensions['B'].width = 14
            ws.column_dimensions['C'].width = 30
            ws.column_dimensions['D'].width = 12
            ws.column_dimensions['E'].width = 12
            ws.column_dimensions['F'].width = 12
            ws.column_dimensions['G'].width = 10
            ws.column_dimensions['H'].width = 16
            ws.column_dimensions['I'].width = 8
            ws.column_dimensions['J'].width = 15

        # Ajustar anchos de columna de la hoja índice
        ws_index.column_dimensions['A'].width = 5   # N°
        ws_index.column_dimensions['B'].width = 10  # ID Curso
        ws_index.column_dimensions['C'].width = 50  # Nombre (con hyperlink)
        ws_index.column_dimensions['D'].width = 14  # Participantes
        ws_index.column_dimensions['E'].width = 18  # Progreso Promedio
        ws_index.column_dimensions['F'].width = 12  # Aprobados
        ws_index.column_dimensions['G'].width = 12  # Estado

        # Guardar en memoria (fix para gunicorn: crear nuevo BytesIO con datos completos)
        temp_output = BytesIO()
        wb.save(temp_output)
        temp_output.seek(0)

        # Crear nuevo BytesIO con los datos completos (evita problemas de ZipFile cerrado)
        excel_data = temp_output.getvalue()
        output = BytesIO(excel_data)
        output.seek(0)

        # Nombre del archivo
        fecha_str = datetime.now().strftime("%Y%m%d")
        filename = f"Reporte_Tecnipro_{fecha_str}.xlsx"

        logger.info("Generando Excel: %s cursos para %s", len(cursos), current_user.email)

        return send_file(
            output,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name=filename
        )

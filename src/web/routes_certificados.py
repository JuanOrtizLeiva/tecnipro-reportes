"""Rutas del módulo de Certificados de Participación.

- UI de emisión (wizard) para la coordinadora académica (permiso
  "certificados"; los admin lo tienen automáticamente).
- API de cursos con elegibilidad calculada en el servidor (nota mínima 4,0;
  en sincrónicos además asistencia >= mínimo del curso).
- Emisión por lotes en subproceso desacoplado (sobrevive caídas de la
  sesión del navegador) con reanudación.
- Endpoint PÚBLICO de validación por código QR (consumido por la página
  www.tecnipro.cl/validar).
"""

import json
import logging
import os
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

from flask import abort, jsonify, render_template, request, send_file
from flask_login import current_user, login_required

from config import settings
from src.certificados import registry
from src.certificados.generator import rut_formateado, fecha_larga
from src.reports.pdf_generator import _cargar_coordinadores_por_curso

logger = logging.getLogger(__name__)

NOTA_CORTE = 4.0
ASIST_MIN_DEFAULT = 75.0


def _requiere_permiso():
    if not current_user.tiene_permiso("certificados"):
        abort(403)


def _norm_rut(rut):
    return str(rut or "").strip().lower().replace(".", "").replace(" ", "")


def _cargar_datos_cursos():
    """Carga datos_procesados.json y enriquece sincrónicos (degradante)."""
    path = settings.JSON_DATOS_PATH
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        datos = json.load(f)
    try:
        from src.web.sincronico_queries import enriquecer_sincronicos
        enriquecer_sincronicos(datos.get("cursos", []))
    except Exception as e:
        logger.warning("Certificados: sin enriquecimiento sincrónico: %s", e)
        for c in datos.get("cursos", []):
            c.setdefault("es_sincronico", False)
    return datos


def _evaluar_alumno(es_sincronico, est):
    """Evalúa elegibilidad de un alumno. Retorna (elegible, motivos, asistencia_pct).

    Criterios: calificación >= 4,0; en sincrónicos además asistencia >= mínimo
    del curso. La coordinadora puede forzar la inclusión con un motivo que
    queda registrado en el folio.
    """
    motivos = []
    cal = est.get("calificacion")
    if cal is None:
        motivos.append("Sin calificación registrada")
    elif float(cal) < NOTA_CORTE:
        motivos.append(f"Calificación {str(cal).replace('.', ',')} inferior a 4,0")

    asistencia_pct = None
    if es_sincronico:
        bloque = est.get("asistencia") or {}
        asistencia_pct = bloque.get("pct")
        minimo = bloque.get("minimo") or ASIST_MIN_DEFAULT
        if asistencia_pct is None:
            motivos.append("Sin asistencia registrada")
        elif float(asistencia_pct) < float(minimo):
            motivos.append(
                f"Asistencia {str(asistencia_pct).replace('.', ',')}% inferior al "
                f"mínimo {str(minimo).replace('.', ',')}%"
            )
    return (len(motivos) == 0, motivos, asistencia_pct)


def _mascara_rut(rut):
    """RUT parcialmente enmascarado para la página pública: 13.05•.••7-6."""
    formateado = rut_formateado(rut)
    cuerpo, _, dv = formateado.rpartition("-")
    if not cuerpo:
        return "••••••"
    digitos = [i for i, ch in enumerate(cuerpo) if ch.isdigit()]
    ocultar = set(digitos[3:-1])  # deja visibles los 3 primeros y el último
    enmascarado = "".join(
        "•" if i in ocultar else ch for i, ch in enumerate(cuerpo)
    )
    return f"{enmascarado}-{dv}"


def _lanzar_proceso_lote(lote_id, emitido_por):
    """Lanza scripts/emitir_certificados.py desacoplado del servidor web."""
    project_root = Path(__file__).parent.parent.parent
    script = project_root / "scripts" / "emitir_certificados.py"
    log_dir = settings.CERTIFICADOS_PATH / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = open(str(log_dir / f"lote_{lote_id}.log"), "a", encoding="utf-8")
    log_file.write(f"\n──── Lanzado {datetime.now():%Y-%m-%d %H:%M:%S} por {emitido_por} ────\n")
    log_file.flush()

    child_env = os.environ.copy()
    child_env["PYTHONPATH"] = str(project_root)
    process = subprocess.Popen(
        [sys.executable, str(script), lote_id],
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        cwd=str(project_root),
        env=child_env,
    )
    logger.info("Emisión de lote %s lanzada (PID %d) por %s",
                lote_id, process.pid, emitido_por)

    def _reap(proc, fh):
        try:
            proc.wait()
        finally:
            try:
                fh.close()
            except Exception:
                pass

    threading.Thread(target=_reap, args=(process, log_file), daemon=True).start()
    return process.pid


def register_certificados_routes(app):

    # ── UI ─────────────────────────────────────────────────

    @app.route("/certificados")
    @login_required
    def certificados_ui():
        _requiere_permiso()
        return render_template("certificados.html")

    # ── API: cursos con elegibilidad ───────────────────────

    @app.route("/api/certificados/cursos")
    @login_required
    def api_cert_cursos():
        _requiere_permiso()
        datos = _cargar_datos_cursos()
        if datos is None:
            return jsonify({"error": "No hay datos procesados. Ejecute una actualización."}), 404

        coordinadores = _cargar_coordinadores_por_curso()
        cursos = []
        for c in datos.get("cursos", []):
            curso_id = str(c.get("id_moodle", ""))
            if not curso_id:
                continue
            es_sinc = bool(c.get("es_sincronico"))
            alumnos = []
            for est in c.get("estudiantes", []):
                elegible, motivos, asistencia_pct = _evaluar_alumno(es_sinc, est)
                alumnos.append({
                    "nombre": est.get("nombre", ""),
                    "rut": est.get("rut", ""),
                    "email": est.get("email", ""),
                    "calificacion": est.get("calificacion"),
                    "progreso": est.get("progreso"),
                    "asistencia_pct": asistencia_pct,
                    "asistencia_min": (est.get("asistencia") or {}).get("minimo") if es_sinc else None,
                    "elegible": elegible,
                    "motivos": motivos,
                })
            cursos.append({
                "id": curso_id,
                "nombre": c.get("nombre", ""),
                "categoria": c.get("categoria", ""),
                "modalidad": "sincronico" if es_sinc else "asincronico",
                "fecha_inicio": c.get("fecha_inicio", ""),
                "fecha_fin": c.get("fecha_fin", ""),
                "estado": c.get("estado", ""),
                "horas": registry.get_horas_curso(curso_id),
                "coordinadores": [
                    {"email": e, "nombre": n, "empresa": emp}
                    for (e, n, emp) in coordinadores.get(curso_id, [])
                ],
                "alumnos": alumnos,
            })
        cursos.sort(key=lambda x: (x["estado"] != "active", x["nombre"]))
        return jsonify({
            "cursos": cursos,
            "copia": settings.CERT_COPIA,
            "fecha_datos": datos.get("metadata", {}).get("fecha_procesamiento", ""),
        })

    # ── API: emitir lote ───────────────────────────────────

    @app.route("/api/certificados/emitir", methods=["POST"])
    @login_required
    def api_cert_emitir():
        _requiere_permiso()
        body = request.get_json(silent=True) or {}
        seleccion = body.get("cursos") or []
        if not seleccion:
            return jsonify({"error": "No se seleccionaron cursos"}), 400

        datos = _cargar_datos_cursos()
        if datos is None:
            return jsonify({"error": "No hay datos procesados"}), 404
        cursos_srv = {str(c.get("id_moodle")): c for c in datos.get("cursos", [])}

        a_emitir = []
        for sel in seleccion:
            curso_id = str(sel.get("curso_id", ""))
            curso = cursos_srv.get(curso_id)
            if curso is None:
                return jsonify({"error": f"Curso {curso_id} no existe en los datos"}), 400

            # Validar fechas y horas confirmadas por la coordinadora
            try:
                fi = datetime.strptime(str(sel.get("fecha_inicio", ""))[:10], "%Y-%m-%d").date()
                ft = datetime.strptime(str(sel.get("fecha_termino", ""))[:10], "%Y-%m-%d").date()
            except ValueError:
                return jsonify({"error": f"Fechas inválidas en curso {curso_id}"}), 400
            if ft < fi:
                return jsonify({"error": f"El término es anterior al inicio en curso {curso_id}"}), 400
            try:
                horas = float(sel.get("horas") or 0)
            except (TypeError, ValueError):
                horas = 0
            if horas <= 0 or horas > 2000:
                return jsonify({"error": f"Horas inválidas en curso {curso_id}"}), 400

            es_sinc = bool(curso.get("es_sincronico"))
            estudiantes = {_norm_rut(e.get("rut")): e for e in curso.get("estudiantes", [])}

            incluidos = [a for a in (sel.get("alumnos") or []) if a.get("incluir")]
            if not incluidos:
                return jsonify({"error": f"Curso {curso_id} sin alumnos seleccionados"}), 400

            for al in incluidos:
                est = estudiantes.get(_norm_rut(al.get("rut")))
                if est is None:
                    return jsonify({
                        "error": f"Alumno con RUT {al.get('rut')} no está en el curso {curso_id}"
                    }), 400
                elegible, motivos, asistencia_pct = _evaluar_alumno(es_sinc, est)
                motivo_manual = (al.get("motivo_manual") or "").strip()
                if not elegible and not motivo_manual:
                    return jsonify({
                        "error": f"{est.get('nombre')} no cumple los criterios "
                                 f"({'; '.join(motivos)}). Para incluirlo debes indicar un motivo.",
                    }), 400
                a_emitir.append({
                    "curso_id": curso_id,
                    "curso_nombre": curso.get("nombre", ""),
                    "modalidad": "sincronico" if es_sinc else "asincronico",
                    "alumno_nombre": est.get("nombre", ""),
                    "alumno_rut": est.get("rut", ""),
                    "alumno_email": est.get("email", ""),
                    "fecha_inicio": fi.isoformat(),
                    "fecha_termino": ft.isoformat(),
                    "horas": horas,
                    "asistencia_pct": asistencia_pct,
                    "calificacion": est.get("calificacion"),
                    "incluido_manual": not elegible,
                    "motivo_manual": motivo_manual if not elegible else "",
                })

            registry.set_horas_curso(curso_id, horas)

        lote_id = registry.crear_lote(current_user.email, a_emitir)
        try:
            _lanzar_proceso_lote(lote_id, current_user.email)
        except Exception as e:
            logger.error("No se pudo lanzar el proceso del lote %s: %s", lote_id, e)
            return jsonify({
                "lote_id": lote_id,
                "error": "El lote quedó creado pero no se pudo iniciar el proceso. "
                         "Usa 'Reanudar' para intentarlo de nuevo.",
            }), 500
        return jsonify({"lote_id": lote_id, "total": len(a_emitir)})

    # ── API: estado y reanudación de lotes ─────────────────

    @app.route("/api/certificados/lote/<lote_id>")
    @login_required
    def api_cert_lote(lote_id):
        _requiere_permiso()
        lote = registry.obtener_lote(lote_id)
        if lote is None:
            return jsonify({"error": "Lote no existe"}), 404
        from src.certificados.emitter import lote_en_proceso
        certs = registry.certificados_de_lote(lote_id)
        return jsonify({
            "lote": lote,
            "en_proceso": lote_en_proceso(lote_id),
            "certificados": [
                {k: c[k] for k in (
                    "folio_num", "folio", "codigo", "curso_id", "curso_nombre",
                    "alumno_nombre", "alumno_rut", "alumno_email", "estado",
                    "error", "incluido_manual", "motivo_manual", "anulado",
                )} for c in certs
            ],
        })

    @app.route("/api/certificados/lotes")
    @login_required
    def api_cert_lotes():
        _requiere_permiso()
        from src.certificados.emitter import lote_en_proceso
        registry.init_db()
        lotes = registry.lotes_recientes(15)
        for l in lotes:
            l["en_proceso"] = lote_en_proceso(l["id"])
        return jsonify({"lotes": lotes})

    @app.route("/api/certificados/lote/<lote_id>/reanudar", methods=["POST"])
    @login_required
    def api_cert_reanudar(lote_id):
        _requiere_permiso()
        lote = registry.obtener_lote(lote_id)
        if lote is None:
            return jsonify({"error": "Lote no existe"}), 404
        from src.certificados.emitter import lote_en_proceso
        if lote_en_proceso(lote_id):
            return jsonify({"error": "El lote ya está en proceso"}), 409
        _lanzar_proceso_lote(lote_id, current_user.email)
        return jsonify({"status": "relanzado", "lote_id": lote_id})

    # ── API: registro, descarga y anulación ────────────────

    @app.route("/api/certificados/registro")
    @login_required
    def api_cert_registro():
        _requiere_permiso()
        registry.init_db()
        q = request.args.get("q", "").strip() or None
        curso_id = request.args.get("curso_id", "").strip() or None
        return jsonify({"certificados": registry.listar_registro(q=q, curso_id=curso_id)})

    @app.route("/certificados/archivo/<int:folio_num>")
    @login_required
    def cert_archivo(folio_num):
        _requiere_permiso()
        cert = registry.obtener_certificado(folio_num)
        if cert is None or not cert.get("archivo"):
            abort(404)
        archivo = Path(cert["archivo"])
        if not archivo.exists():
            abort(404)
        return send_file(str(archivo), as_attachment=True,
                         download_name=archivo.name, mimetype="application/pdf")

    @app.route("/api/certificados/anular/<int:folio_num>", methods=["POST"])
    @login_required
    def api_cert_anular(folio_num):
        _requiere_permiso()
        cert = registry.obtener_certificado(folio_num)
        if cert is None:
            return jsonify({"error": "Folio no existe"}), 404
        motivo = ((request.get_json(silent=True) or {}).get("motivo") or "").strip()
        if not motivo:
            return jsonify({"error": "Debes indicar un motivo de anulación"}), 400
        registry.anular(folio_num, motivo, current_user.email)
        return jsonify({"status": "anulado", "folio": cert["folio"]})

    # ── API PÚBLICA: validación de certificados ────────────

    @app.route("/api/certificados/validar/<codigo>")
    def api_cert_validar(codigo):
        """Validación pública por código QR — sin autenticación.

        La consume la página www.tecnipro.cl/validar. Solo expone datos
        no sensibles (RUT enmascarado).
        """
        registry.init_db()
        cert = registry.buscar_por_codigo(codigo)
        if cert is None:
            return jsonify({"valido": False})
        if cert.get("anulado"):
            return jsonify({
                "valido": False,
                "anulado": True,
                "mensaje": "Este certificado fue anulado por el Instituto.",
            })
        return jsonify({
            "valido": True,
            "certificado": {
                "folio": cert["folio"],
                "nombre": cert["alumno_nombre"],
                "rut": _mascara_rut(cert["alumno_rut"]),
                "curso": cert["curso_nombre"],
                "modalidad": "Sincrónico (en vivo)" if cert["modalidad"] == "sincronico"
                             else "Asincrónico (e-learning)",
                "fecha_inicio": fecha_larga(cert["fecha_inicio"]),
                "fecha_termino": fecha_larga(cert["fecha_termino"]),
                "horas": int(cert["horas"]) if float(cert["horas"]).is_integer()
                         else cert["horas"],
                "fecha_emision": fecha_larga(cert["creado_en"][:10]),
                "institucion": "Instituto de Capacitación TECNIPRO",
            },
        })

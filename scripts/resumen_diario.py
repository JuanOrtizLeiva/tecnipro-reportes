#!/usr/bin/env python3
"""Resumen diario consolidado para el equipo (jortizleiva + ygonzalez).

Reemplaza los múltiples correos individuales que el pipeline diario enviaba a
estos dos usuarios (estado del pipeline, una alerta SENCE por curso, un
recordatorio DJ por acción SENCE) por **un solo correo** con:

- Cuerpo HTML redactado en lenguaje simple (sin tecnicismos), ordenado con lo
  accionable arriba y el estado del sistema al final, con enlaces útiles (ficha
  del curso en Moodle, dashboard, portal SENCE) y diseñado para leerse de un
  vistazo (una columna, 600px, tarjetas por curso, semáforo de color).
- Un Excel adjunto (``resumen_diario_YYYYMMDD.xlsx``) con una hoja por tema, con
  el detalle completo (RUT, todas las columnas) para descargar y analizar.

Temas consolidados:
  1. Participantes por revisar — cobertura SENCE, 0 conexiones y con notas
     (reutiliza la lógica de ``alerta_sence_sin_conexion_con_notas`` con su
     filtro anti-falsos-positivos).
  2. Declaraciones Juradas por firmar — DJ sin firmar en acciones ya terminadas.
  3. Estado del sistema — descarga SENCE + actualización del dashboard (al final,
     en lenguaje simple).

Se envía SIEMPRE (una vez al día): los días sin novedades llega un resumen corto
que confirma que el sistema corrió. Se engancha al final de
``run_daily_production.sh`` (rama de éxito). El watchdog independiente sigue como
red de seguridad para el caso de que el pipeline no corra.

Uso:
    python scripts/resumen_diario.py [--dry-run] [--to correo1,correo2]
"""

import argparse
import json
import logging
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from sqlalchemy import desc, func

from config import settings
from src.database import init_db, get_session
from src.models import Curso, Estudiante, Inscripcion, PipelineRun, SnapshotDiario
from src.reports.email_sender import enviar_correo

# Reutiliza los detectores puros del control de anomalías SENCE (misma fuente de
# verdad, incluido el filtro que descarta cursos con scraping SENCE fallido).
from scripts.alerta_sence_sin_conexion_con_notas import (
    _cursos_afectados,
    _filtrar_sence_no_confiable,
    _fmt_nota,
    _fmt_pct,
    _pares,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("resumen_diario")

DESTINATARIOS = "jortizleiva@duocapital.cl,ygonzalez@duocapital.cl"
FIRMADA = ("Emitida", "Firmada", "Descargada")

# Enlaces accionables (dominios propios/conocidos, texto descriptivo)
MOODLE_COURSE_URL = "https://virtual.institutotecnipro.cl/course/view.php?id={}"
DASHBOARD_URL = "https://reportes.tecnipro.cl"
SENCE_PORTAL_URL = "https://lce.sence.cl/CertificadoAsistencia/"

# Paleta (semáforo). Se evita negro/blanco puros por compatibilidad dark mode.
COLOR_OK = "#16a34a"       # verde
COLOR_WARN = "#d97706"     # ámbar
COLOR_ERROR = "#dc2626"    # rojo
COLOR_HEADER = "#334155"   # encabezado neutro
COLOR_TEXT = "#1f2937"     # casi negro
COLOR_MUTE = "#6b7280"     # gris texto secundario
COLOR_BORDE = "#e5e7eb"    # gris borde
COLOR_BG = "#f4f5f7"       # fondo página
COLOR_CARD = "#ffffff"     # tarjeta

FONT = "Arial,Helvetica,sans-serif"

_DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
_MESES = ["", "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
          "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def _fecha_humana(dt):
    """'Domingo 19 de julio de 2026 · 09:14 h'."""
    return (f"{_DIAS[dt.weekday()]} {dt.day} de {_MESES[dt.month]} de {dt.year}"
            f" · {dt.strftime('%H:%M')} h")


def _fecha_corta(iso):
    try:
        return date.fromisoformat(iso).strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return iso or "—"


# ══════════════════════════════════════════════════════════════════════════
# Recolectores (una función por tema, sin efectos secundarios)
# ══════════════════════════════════════════════════════════════════════════

def recolectar_estado_sistema(s):
    """Estado de la descarga SENCE, la actualización del dashboard y la frescura.

    Devuelve un dict con banderas y textos en lenguaje simple listos para render.
    """
    out = Path(settings.OUTPUT_PATH)
    reps = sorted(out.glob("scraper_report_*.json"),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    scr = {}
    if reps:
        try:
            scr = json.loads(reps[0].read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("No se pudo leer scraper report: %s", e)

    solicitados = list(scr.get("ids_solicitados", []))
    ok = list(scr.get("descargados_ok", []))
    fallidos = list(scr.get("fallidos", []))
    errores = list(scr.get("errores", []))
    scraping_ok = bool(ok) and len(ok) == len(solicitados) and not errores

    # Último pipeline_run de hoy en PostgreSQL (fuente de verdad del dashboard)
    hoy = date.today()
    ini = datetime(hoy.year, hoy.month, hoy.day, tzinfo=timezone.utc)
    pg_ok = False
    pg_cursos = 0
    pg_error = ""
    try:
        ult = (s.query(PipelineRun)
                .filter(PipelineRun.started_at >= ini)
                .order_by(desc(PipelineRun.started_at))
                .first())
        if ult is not None:
            pg_cursos = ult.total_cursos or 0
            if ult.status == "ok" and pg_cursos > 0:
                pg_ok = True
            else:
                pg_error = (ult.error_message or "")[:300]
    except Exception as e:  # noqa: BLE001 - robustez del resumen
        pg_error = f"Error consultando la actualización: {e}"

    # Frescura del dashboard
    try:
        ult_snap = s.query(func.max(SnapshotDiario.fecha)).scalar()
    except Exception:  # noqa: BLE001
        ult_snap = None
    dias_snap = (hoy - ult_snap).days if ult_snap else None

    if scraping_ok and pg_ok:
        severidad = "ok"
    elif pg_ok:
        severidad = "warn"      # dashboard actualizado pero descarga SENCE parcial
    else:
        severidad = "error"

    # Textos en lenguaje simple (compartidos por el HTML y el Excel)
    descarga_txt = f"{len(ok)} de {len(solicitados)} cursos"
    if pg_ok:
        actualizacion_txt = f"Completada — {pg_cursos} cursos"
    elif pg_cursos:
        actualizacion_txt = f"Con problemas — {pg_cursos} cursos"
    else:
        actualizacion_txt = "No se registró actualización hoy"
    if ult_snap is None:
        frescura_txt = "Sin datos"
    elif dias_snap == 0:
        frescura_txt = "Hoy"
    elif dias_snap == 1:
        frescura_txt = "Ayer"
    else:
        frescura_txt = f"{dias_snap} días atrás ({ult_snap.isoformat()})"

    return {
        "severidad": severidad,
        "solicitados": len(solicitados),
        "descargados_ok": len(ok),
        "fallidos": fallidos,
        "errores": errores,
        "scraping_ok": scraping_ok,
        "pg_ok": pg_ok,
        "pg_cursos": pg_cursos,
        "pg_error": pg_error,
        "ultimo_snapshot": ult_snap.isoformat() if ult_snap else None,
        "dias_snapshot": dias_snap,
        "descarga_txt": descarga_txt,
        "actualizacion_txt": actualizacion_txt,
        "frescura_txt": frescura_txt,
    }


def recolectar_sence_anomalias(s):
    """Participantes con cobertura SENCE, 0 conexiones y con notas.

    Devuelve (resumen_por_curso, filas_detalle, omitidos) donde omitidos son los
    cursos excluidos por scraping SENCE fallido (datos no confiables).
    """
    por_curso = _cursos_afectados(s)
    por_curso, omitidos = _filtrar_sence_no_confiable(s, por_curso)

    resumen = []
    filas = []
    for curso_id, afectados in sorted(por_curso.items()):
        curso = s.get(Curso, curso_id)
        if curso is None:
            continue
        pares = _pares(s, afectados)
        resumen.append({"curso": curso, "n": len(pares)})
        for est, i in pares:
            filas.append({
                "Curso": curso.nombre,
                "ID Moodle": curso.id_moodle,
                "Ficha Moodle": MOODLE_COURSE_URL.format(curso.id_moodle),
                "SENCE": i.id_sence or "",
                "Participante": est.nombre if est else "?",
                "RUT": est.rut if est else "?",
                "Conexiones SENCE": i.sence_n_ingresos or 0,
                "Nota": _fmt_nota(i.calificacion),
                "Eval. rendidas": i.evaluaciones_rendidas or 0,
                "Avance": _fmt_pct(i.progreso),
            })
    return resumen, filas, omitidos


def recolectar_dj_pendientes(s, hoy):
    """DJ sin firmar en acciones SENCE ya terminadas (vista diaria sin estado).

    La firma se habilita al día siguiente del término SENCE. Devuelve
    (resumen_por_accion, filas_detalle).
    """
    insc = s.query(Inscripcion).filter(Inscripcion.id_sence != "").all()
    por_sence = defaultdict(list)
    for i in insc:
        por_sence[i.id_sence.strip()].append(i)

    resumen = []
    filas = []
    for id_sence, lst in sorted(por_sence.items()):
        curso = s.get(Curso, lst[0].curso_id)
        if curso is None:
            continue
        ft = (curso.fecha_termino_sence or "").strip()
        try:
            fterm = date.fromisoformat(ft)
        except ValueError:
            continue  # sin término válido: no se sabe si aplica firmar
        if hoy <= fterm:
            continue  # aún no habilitada la firma

        pendientes = [i for i in lst if (i.sence_dj or "").strip() not in FIRMADA]
        if not pendientes:
            continue

        empresa = (curso.comprador.empresa if curso.comprador else "") or ""
        resumen.append({
            "curso": curso, "id_sence": id_sence, "empresa": empresa,
            "fterm": fterm, "n": len(pendientes),
        })
        pares = []
        for i in pendientes:
            est = s.get(Estudiante, i.estudiante_id)
            pares.append((
                est.nombre if est else "?",
                est.rut if est else "?",
                (i.sence_dj or "").strip() or "Pendiente de emitir",
            ))
        pares.sort(key=lambda p: p[0].lower())
        for nombre, rut, estado_dj in pares:
            filas.append({
                "Curso": curso.nombre,
                "ID Moodle": curso.id_moodle,
                "Ficha Moodle": MOODLE_COURSE_URL.format(curso.id_moodle),
                "SENCE": id_sence,
                "Empresa": empresa,
                "Término SENCE": fterm.isoformat(),
                "Participante": nombre,
                "RUT": rut,
                "Estado DJ": estado_dj,
            })
    return resumen, filas


# ══════════════════════════════════════════════════════════════════════════
# Render HTML (una columna, 600px, tarjetas por curso, semáforo de color)
# ══════════════════════════════════════════════════════════════════════════

def _link(url, texto, color=COLOR_TEXT, bold=False):
    peso = "font-weight:700;" if bold else ""
    return (f'<a href="{url}" target="_blank" '
            f'style="color:{color};{peso}text-decoration:underline">{texto}</a>')


def _boton(href, texto, color=COLOR_HEADER):
    """Botón 'a prueba de balas' (HTML/tabla, visible sin imágenes)."""
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'style="margin:6px 0"><tr>'
        f'<td align="center" bgcolor="{color}" style="border-radius:6px">'
        f'<a href="{href}" target="_blank" '
        f'style="display:inline-block;padding:12px 24px;font-family:{FONT};'
        f'font-size:15px;font-weight:700;color:#ffffff;text-decoration:none;'
        f'border-radius:6px">{texto}</a>'
        f'</td></tr></table>')


def _tile(label, valor, color):
    return (
        f'<td class="tile" width="33%" align="center" valign="top" '
        f'style="padding:14px 6px;border:1px solid {COLOR_BORDE};border-radius:8px;'
        f'background:{COLOR_CARD}">'
        f'<div style="font-family:{FONT};font-size:26px;font-weight:800;'
        f'color:{color};line-height:1">{valor}</div>'
        f'<div style="font-family:{FONT};font-size:12px;color:{COLOR_MUTE};'
        f'margin-top:5px">{label}</div></td>')


def _banner(sev):
    cfg = {
        "ok": (COLOR_OK, "✅", "Todo en orden",
               "El sistema se actualizó correctamente esta mañana."),
        "warn": (COLOR_WARN, "⚠️", "Atención",
                 "La descarga de datos de SENCE quedó incompleta hoy; algunos "
                 "cursos pueden estar parciales."),
        "error": (COLOR_ERROR, "🔴", "Requiere revisión",
                  "No se pudo actualizar la información hoy."),
    }[sev]
    color, icono, titulo, txt = cfg
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'border="0" style="margin:2px 0 16px"><tr>'
        f'<td style="background:{color};padding:14px 16px;border-radius:8px;'
        f'font-family:{FONT}">'
        f'<div style="font-size:17px;font-weight:800;color:#ffffff">{icono} {titulo}</div>'
        f'<div style="font-size:14px;color:#ffffff;opacity:.95;margin-top:3px">{txt}</div>'
        f'</td></tr></table>')


def _seccion(titulo, color, intro_html, cuerpo_html):
    """Tarjeta de sección con encabezado de color."""
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'border="0" style="margin:0 0 16px"><tr><td '
        f'style="border:1px solid {COLOR_BORDE};border-radius:8px;background:{COLOR_CARD}">'
        f'<div style="background:{color};color:#ffffff;padding:11px 16px;'
        f'border-radius:8px 8px 0 0;font-family:{FONT};font-size:15px;'
        f'font-weight:800">{titulo}</div>'
        f'<div style="padding:14px 16px;font-family:{FONT};color:{COLOR_TEXT};'
        f'font-size:14px;line-height:1.5">{intro_html}{cuerpo_html}</div>'
        f'</td></tr></table>')


def _curso_card(id_moodle, nombre, meta_txt, items_html, color):
    encabezado = (_link(MOODLE_COURSE_URL.format(id_moodle), nombre, color=color, bold=True)
                  if id_moodle else f'<span style="font-weight:700;color:{color}">{nombre}</span>')
    meta = (f'<div style="font-size:12px;color:{COLOR_MUTE};margin:3px 0 7px">{meta_txt}</div>'
            if meta_txt else '')
    return (
        f'<div style="border:1px solid {COLOR_BORDE};border-left:4px solid {color};'
        f'border-radius:6px;padding:11px 13px;margin:9px 0;background:#fbfbfc">'
        f'<div style="font-size:14px">{encabezado}</div>{meta}'
        f'<div style="font-size:13px;color:{COLOR_TEXT}">{items_html}</div></div>')


def construir_html(fecha_str, estado, sence, dj):
    _resumen_sence, filas_sence, omitidos = sence
    _resumen_dj, filas_dj = dj
    n_sence = len(filas_sence)
    n_dj = len(filas_dj)
    sev = estado["severidad"]

    # ── Cifras clave (accionables) ───────────────────────────────────
    tiles = (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="8" '
        'border="0" style="margin:2px 0 6px"><tr>'
        + _tile("Participantes por revisar", n_sence, COLOR_ERROR if n_sence else COLOR_OK)
        + _tile("Declaraciones Juradas por firmar", n_dj, COLOR_WARN if n_dj else COLOR_OK)
        + _tile("Cursos al día", estado["pg_cursos"], COLOR_HEADER)
        + '</tr></table>')

    # ── Sección 1 (ACCIÓN): Participantes por revisar ────────────────
    if filas_sence:
        grupos = {}
        for f in filas_sence:
            grupos.setdefault((f["Curso"], f["ID Moodle"]), []).append(f)
        cards = ""
        for (nombre, idm), fs in grupos.items():
            items = "".join(
                f'&bull; <strong>{f["Participante"]}</strong> — nota {f["Nota"]} · '
                f'{f["Conexiones SENCE"]} conexiones SENCE · {f["Avance"]} de avance<br>'
                for f in fs)
            cards += _curso_card(idm, nombre, f'{len(fs)} participante(s)',
                                 items, COLOR_ERROR)
        intro = ('<p style="margin:0 0 6px">Estos participantes tienen <strong>nota '
                 'registrada pero 0 conexiones a SENCE</strong>. Como el ingreso a la '
                 'plataforma exige acreditarse con SENCE, conviene revisar cada caso.</p>')
        sec_sence = _seccion("Participantes por revisar (SENCE)", COLOR_ERROR, intro, cards)
    else:
        nota = ""
        if omitidos:
            nota = (f'<br><span style="color:{COLOR_MUTE};font-size:13px">'
                    f'{len(omitidos)} curso(s) quedaron fuera de este control porque su '
                    f'descarga de SENCE falló hoy (se revisarán cuando los datos estén al día).</span>')
        sec_sence = _seccion("Participantes por revisar (SENCE)", COLOR_OK,
                             f'✅ Ningún caso por revisar hoy.{nota}', "")

    # ── Sección 2 (ACCIÓN): Declaraciones Juradas por firmar ─────────
    if filas_dj:
        grupos = {}
        for f in filas_dj:
            grupos.setdefault(
                (f["Curso"], f["ID Moodle"], f["SENCE"], f["Término SENCE"]), []).append(f)
        cards = ""
        for (nombre, idm, id_sence, term), fs in grupos.items():
            empresa = fs[0].get("Empresa", "")
            items = "".join(
                f'&bull; {f["Participante"]} '
                f'<span style="color:{COLOR_MUTE};font-size:12px">({f["Estado DJ"]})</span><br>'
                for f in fs)
            meta = f'Terminó el {_fecha_corta(term)} · {len(fs)} por firmar'
            if empresa:
                meta += f' · {empresa}'
            cards += _curso_card(idm, nombre, meta, items, COLOR_WARN)
        intro = ('<p style="margin:0 0 6px">Estos cursos ya terminaron y tienen '
                 '<strong>Declaraciones Juradas (DJ) pendientes de firma</strong> en el '
                 'portal SENCE. Se firman al día siguiente del término.</p>'
                 f'<p style="margin:0 0 4px">{_link(SENCE_PORTAL_URL, "Ir al portal SENCE para firmar &rarr;", color=COLOR_WARN, bold=True)}</p>')
        sec_dj = _seccion("Declaraciones Juradas por firmar", COLOR_WARN, intro, cards)
    else:
        sec_dj = _seccion("Declaraciones Juradas por firmar", COLOR_OK,
                          "✅ No hay Declaraciones Juradas pendientes.", "")

    # ── Sección 3 (INFO): Estado del sistema (lenguaje simple) ───────
    li = [
        f'Descarga de conexiones SENCE: <strong>{estado["descarga_txt"]}</strong>',
        f'Actualización del dashboard: <strong>{estado["actualizacion_txt"]}</strong>',
        f'Información al día: <strong>{estado["frescura_txt"]}</strong>',
    ]
    if estado["fallidos"]:
        li.append('<span style="color:' + COLOR_ERROR + '">Cursos que no se pudieron '
                  'descargar hoy: <strong>' + ", ".join(estado["fallidos"]) + '</strong></span>')
    if estado["pg_error"]:
        li.append(f'<span style="color:{COLOR_ERROR}">Detalle del problema: {estado["pg_error"]}</span>')
    cuerpo_estado = ('<ul style="margin:0;padding-left:18px">'
                     + "".join(f'<li style="margin:3px 0">{x}</li>' for x in li) + '</ul>')
    sec_estado = _seccion("Estado del sistema", COLOR_HEADER, "", cuerpo_estado)

    # ── Preheader (texto de vista previa) ────────────────────────────
    resumen_pre = {"ok": "Todo en orden.", "warn": "Descarga SENCE incompleta hoy.",
                   "error": "Requiere revisión."}[sev]
    ph_partes = []
    if n_sence:
        ph_partes.append(f"{n_sence} por revisar")
    if n_dj:
        ph_partes.append(f"{n_dj} DJ por firmar")
    preheader = resumen_pre + (" " + ", ".join(ph_partes) + "." if ph_partes
                               else " Sin tareas pendientes.")

    # ── Documento ────────────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<meta name="supported-color-schemes" content="light dark">
<style>
  @media only screen and (max-width:600px) {{
    .contenedor {{ width:100% !important; }}
    .tile {{ display:block !important; width:100% !important; margin-bottom:8px !important; }}
  }}
</style>
</head>
<body style="margin:0;padding:0;background:{COLOR_BG};color:{COLOR_TEXT}">
  <div style="display:none;max-height:0;overflow:hidden;opacity:0;color:{COLOR_BG}">{preheader}</div>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:{COLOR_BG}">
    <tr><td align="center" style="padding:18px 12px">
      <table role="presentation" class="contenedor" width="600" cellpadding="0" cellspacing="0" border="0" style="width:600px;max-width:600px">
        <tr><td style="background:{COLOR_HEADER};padding:18px 20px;border-radius:8px">
          <div style="font-family:{FONT};font-size:20px;font-weight:800;color:#ffffff">Resumen diario · Tecnipro</div>
          <div style="font-family:{FONT};font-size:13px;color:#ffffff;opacity:.85;margin-top:3px">{fecha_str}</div>
        </td></tr>
        <tr><td style="height:14px;line-height:14px">&nbsp;</td></tr>
        <tr><td>{_banner(sev)}</td></tr>
        <tr><td>{tiles}</td></tr>
        <tr><td align="center" style="padding:2px 0 14px">{_boton(DASHBOARD_URL, "Abrir el dashboard")}</td></tr>
        <tr><td>{sec_sence}</td></tr>
        <tr><td>{sec_dj}</td></tr>
        <tr><td>{sec_estado}</td></tr>
        <tr><td style="padding:6px 4px 0;font-family:{FONT};font-size:12px;color:{COLOR_MUTE};line-height:1.5">
          El detalle completo (con RUT y todas las columnas) está en el Excel adjunto, con una hoja por tema.<br>
          Correo automático diario · {_link(DASHBOARD_URL, "reportes.tecnipro.cl", color=COLOR_MUTE)}
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""
    return html


# ══════════════════════════════════════════════════════════════════════════
# Excel adjunto (detalle completo, una hoja por tema)
# ══════════════════════════════════════════════════════════════════════════

def construir_excel(path, fecha_str, estado, filas_sence, filas_dj):
    """Escribe un .xlsx con una hoja por tema. Devuelve la ruta."""
    resumen_rows = [
        {"Tema": "Fecha", "Valor": fecha_str},
        {"Tema": "Participantes por revisar (SENCE)", "Valor": f"{len(filas_sence)}"},
        {"Tema": "Declaraciones Juradas por firmar", "Valor": f"{len(filas_dj)}"},
        {"Tema": "Descarga de conexiones SENCE", "Valor": estado["descarga_txt"]},
        {"Tema": "Actualización del dashboard", "Valor": estado["actualizacion_txt"]},
        {"Tema": "Información al día", "Valor": estado["frescura_txt"]},
    ]

    estado_rows = [
        {"Indicador": "Descarga de conexiones SENCE", "Valor": estado["descarga_txt"]},
        {"Indicador": "Cursos que no se pudieron descargar",
         "Valor": ", ".join(estado["fallidos"]) or "—"},
        {"Indicador": "Problemas de descarga", "Valor": " | ".join(estado["errores"]) or "—"},
        {"Indicador": "Actualización del dashboard", "Valor": estado["actualizacion_txt"]},
        {"Indicador": "Detalle del problema (si hubo)", "Valor": estado["pg_error"] or "—"},
        {"Indicador": "Información al día", "Valor": estado["frescura_txt"]},
    ]

    cols_sence = ["Curso", "ID Moodle", "Ficha Moodle", "SENCE", "Participante", "RUT",
                  "Conexiones SENCE", "Nota", "Eval. rendidas", "Avance"]
    cols_dj = ["Curso", "ID Moodle", "Ficha Moodle", "SENCE", "Empresa", "Término SENCE",
               "Participante", "RUT", "Estado DJ"]

    def _df(filas, cols):
        return pd.DataFrame(filas, columns=cols) if filas else pd.DataFrame(columns=cols)

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame(resumen_rows).to_excel(writer, sheet_name="Resumen", index=False)
        _df(filas_sence, cols_sence).to_excel(
            writer, sheet_name="Participantes por revisar", index=False)
        _df(filas_dj, cols_dj).to_excel(writer, sheet_name="DJ por firmar", index=False)
        pd.DataFrame(estado_rows).to_excel(writer, sheet_name="Estado del sistema", index=False)

        # Autoancho básico por hoja
        for ws in writer.book.worksheets:
            for col in ws.columns:
                largo = max((len(str(c.value)) for c in col if c.value is not None), default=10)
                ws.column_dimensions[col[0].column_letter].width = min(max(largo + 2, 12), 60)

    return path


# ══════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════

def main(dry_run=False, to=None):
    destinatarios = to or DESTINATARIOS
    if not init_db():
        logger.error("Base de datos no disponible")
        sys.exit(1)

    s = get_session()
    try:
        hoy = date.today()
        ahora = datetime.now()
        fecha_str = _fecha_humana(ahora)

        estado = recolectar_estado_sistema(s)
        sence = recolectar_sence_anomalias(s)
        dj = recolectar_dj_pendientes(s, hoy)

        _resumen_sence, filas_sence, omitidos = sence
        _resumen_dj, filas_dj = dj

        logger.info("Estado=%s | Por revisar (SENCE)=%d (omitidos=%d) | DJ por firmar=%d",
                    estado["severidad"], len(filas_sence), len(omitidos), len(filas_dj))

        # ── Excel adjunto ────────────────────────────────────────────
        out = Path(settings.OUTPUT_PATH)
        out.mkdir(parents=True, exist_ok=True)
        xlsx_path = out / f"resumen_diario_{hoy.strftime('%Y%m%d')}.xlsx"
        construir_excel(xlsx_path, fecha_str, estado, filas_sence, filas_dj)
        logger.info("Excel generado: %s", xlsx_path)

        # ── HTML + asunto ────────────────────────────────────────────
        html = construir_html(fecha_str, estado, sence, dj)
        icono = {"ok": "✅", "warn": "⚠️", "error": "🔴"}[estado["severidad"]]
        partes = []
        if not estado["scraping_ok"]:
            partes.append(f'SENCE {estado["descargados_ok"]}/{estado["solicitados"]}')
        if filas_sence:
            partes.append(f"{len(filas_sence)} por revisar")
        if filas_dj:
            partes.append(f"{len(filas_dj)} DJ por firmar")
        cola = (" — " + " · ".join(partes)) if partes else " — sin novedades"
        asunto = f"{icono} Resumen diario Tecnipro {hoy.strftime('%d/%m')}{cola}"

        if dry_run:
            logger.info("[DRY-RUN] Para: %s", destinatarios)
            logger.info("[DRY-RUN] Asunto: %s", asunto)
            logger.info("[DRY-RUN] Adjunto: %s", xlsx_path)
            logger.info("[DRY-RUN] Por revisar: %d fila(s); DJ: %d fila(s)",
                        len(filas_sence), len(filas_dj))
            preview = out / f"resumen_diario_{hoy.strftime('%Y%m%d')}_preview.html"
            preview.write_text(html, encoding="utf-8")
            logger.info("[DRY-RUN] Vista previa HTML: %s", preview)
            return

        res = enviar_correo(destinatarios, asunto, html, adjunto_path=xlsx_path)
        if res["status"] == "OK":
            logger.info("Resumen diario enviado a %s", destinatarios)
        else:
            logger.error("Fallo al enviar resumen diario: %s", res.get("detalle"))
            sys.exit(1)
    except Exception as e:  # noqa: BLE001
        logger.error("Error generando resumen diario: %s", e, exc_info=True)
        sys.exit(1)
    finally:
        s.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(
        description="Resumen diario consolidado (un solo correo por secciones + Excel).")
    p.add_argument("--dry-run", action="store_true",
                   help="No envía; genera el Excel y una vista previa HTML.")
    p.add_argument("--to", default=None,
                   help="Override de destinatario(s) (coma-separados). Para pruebas. "
                        "Por defecto: jortizleiva + ygonzalez.")
    args = p.parse_args()
    main(dry_run=args.dry_run, to=args.to)

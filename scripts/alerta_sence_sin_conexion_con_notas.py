#!/usr/bin/env python3
"""Alerta: participantes con cobertura SENCE, 0 conexiones pero con notas.

Lógica de negocio
-----------------
En un curso con cobertura SENCE el participante ingresa a la plataforma a
través de SENCE, y cada ingreso queda registrado (N_Ingresos → `sence_n_ingresos`).
La asistencia (esas conexiones) es además requisito para aprobar. Por lo tanto,
un participante con **0 conexiones** no debería poder tener **notas**: sin
conexión no hay forma de haber ingresado a rendir evaluaciones.

Cuando aparece esa combinación —cobertura SENCE + estado ``SIN_CONEXION`` + con
notas— es señal de un desajuste (datos SENCE desincronizados, o acceso fuera de
la vía SENCE) que la coordinación debe revisar. Este control detecta la
condición y, por cada curso afectado, envía un correo a la coordinadora con el
ID del curso en el asunto, el enlace al curso en Moodle y el listado de los
participantes en esa condición.

Corre a diario (tras el pipeline). Reenvía mientras la condición persista.

Uso:
    python alerta_sence_sin_conexion_con_notas.py [--dry-run]
"""

import argparse
import logging
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import or_

from config import settings
from src.database import init_db, get_session
from src.models import Curso, Inscripcion, Estudiante
from src.reports.email_sender import enviar_correo

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("alerta_sence_notas")

DESTINATARIO = "ygonzalez@duocapital.cl"
CC = "jortizleiva@duocapital.cl"
# Mismo enlace que usan los cursos en el dashboard (templates/dashboard.html).
MOODLE_COURSE_URL = "https://virtual.institutotecnipro.cl/course/view.php?id={}"

# Un CSV de conectividad SENCE se considera confiable si se descargó dentro de
# esta ventana. El pipeline diario mueve los CSV a backup y re-descarga: si la
# descarga falla, el CSV queda ausente (o viejo) y el curso muestra 0 conexiones
# falsas → NO se debe alertar. Ventana amplia (> 1 ciclo diario) para no
# suprimir corridas legítimas del mismo día.
SENCE_FRESCURA_HORAS = 26


def _sence_confiable(id_sence):
    """True si la conectividad SENCE de ese ID se descargó con éxito y reciente.

    Señal directa de que el scraping funcionó para ese curso: el archivo
    ``data/sence/<id_sence>.csv`` existe y su mtime está dentro de la ventana de
    frescura. Si el scraping falló, el archivo no existe (fue movido a backup y
    no se re-creó) → los 0 ingresos en la BD no son datos reales, son datos
    faltantes, y la alerta debe omitir ese curso.
    """
    if not id_sence:
        return False
    ruta = settings.SENCE_CSV_PATH / f"{id_sence}.csv"
    try:
        mtime = datetime.fromtimestamp(ruta.stat().st_mtime)
    except OSError:
        return False
    return (datetime.now() - mtime) <= timedelta(hours=SENCE_FRESCURA_HORAS)


def _filtrar_sence_no_confiable(s, por_curso):
    """Separa cursos con datos SENCE confiables de los que fallaron el scraping.

    Devuelve ``(confiables, omitidos)`` donde ``confiables`` es el dict filtrado
    y ``omitidos`` es una lista de tuplas ``(id_moodle, id_sence, n_afectados)``
    para registrar en el log qué cursos se excluyeron por scraping fallido.
    """
    confiables = {}
    omitidos = []
    for curso_id, afectados in por_curso.items():
        curso = s.get(Curso, curso_id)
        # Todas las inscripciones del grupo comparten el ID SENCE del curso.
        id_sence = (curso.id_sence if curso else "") or (
            afectados[0].id_sence if afectados else "")
        if _sence_confiable(id_sence):
            confiables[curso_id] = afectados
        else:
            id_moodle = curso.id_moodle if curso else curso_id
            omitidos.append((id_moodle, id_sence, len(afectados)))
    return confiables, omitidos


def _cursos_afectados(s):
    """Devuelve {curso_id: [Inscripcion, ...]} para la condición anómala.

    Cobertura SENCE (id_sence poblado) + estado ``SIN_CONEXION`` (0 ingresos) +
    con notas (calificación > 0 o al menos una evaluación rendida).
    """
    q = (
        s.query(Inscripcion)
        .filter(Inscripcion.id_sence != "")
        .filter(Inscripcion.sence_estado == "SIN_CONEXION")
        .filter(or_(Inscripcion.calificacion > 0,
                    Inscripcion.evaluaciones_rendidas > 0))
    )
    por_curso = defaultdict(list)
    for i in q.all():
        por_curso[i.curso_id].append(i)
    return por_curso


def _pares(s, afectados):
    """Lista ordenada por nombre de tuplas (Estudiante, Inscripcion)."""
    pares = []
    for i in afectados:
        est = s.get(Estudiante, i.estudiante_id)
        pares.append((est, i))
    pares.sort(key=lambda p: (p[0].nombre if p[0] else "").lower())
    return pares


def _fmt_nota(v):
    return f"{v:.1f}" if v is not None else "—"


def _fmt_pct(v):
    return f"{v:.1f}%" if v is not None else "—"


def _correo_curso(curso, pares):
    """Construye (asunto, html) para un curso afectado."""
    id_moodle = curso.id_moodle
    enlace = MOODLE_COURSE_URL.format(id_moodle)
    n = len(pares)

    filas = ""
    for est, i in pares:
        nombre = est.nombre if est else "?"
        rut = est.rut if est else "?"
        filas += (
            "<tr>"
            f"<td style='padding:6px 10px;border:1px solid #ddd'>{nombre}</td>"
            f"<td style='padding:6px 10px;border:1px solid #ddd'>{rut}</td>"
            f"<td style='padding:6px 10px;border:1px solid #ddd'>{i.id_sence or '—'}</td>"
            f"<td style='padding:6px 10px;border:1px solid #ddd;text-align:center'>{i.sence_n_ingresos or 0}</td>"
            f"<td style='padding:6px 10px;border:1px solid #ddd;text-align:center'>{_fmt_nota(i.calificacion)}</td>"
            f"<td style='padding:6px 10px;border:1px solid #ddd;text-align:center'>{i.evaluaciones_rendidas or 0}</td>"
            f"<td style='padding:6px 10px;border:1px solid #ddd;text-align:center'>{_fmt_pct(i.progreso)}</td>"
            "</tr>"
        )

    asunto = (f"⚠️ Alerta SENCE — Curso {id_moodle}: cobertura sin conexión "
              f"pero con notas")
    html = f"""<html><body style="font-family:Arial,sans-serif;color:#222">
<p>Hola Yessenia,</p>
<p>En el curso <strong>{curso.nombre}</strong> (ID Moodle
<strong>{id_moodle}</strong>) se detectaron <strong>{n}</strong> participante(s)
con <strong>cobertura SENCE</strong> que registran <strong>0 conexiones</strong>
a la plataforma SENCE pero <strong>tienen notas</strong>.</p>
<p>Esto no debería ocurrir: sin conexiones no hay forma de haber ingresado a la
plataforma a rendir evaluaciones, y la asistencia es requisito para aprobar.
Conviene revisar estos casos.</p>
<p>Enlace al curso en Moodle:<br>
<a href="{enlace}">{enlace}</a></p>
<table style="border-collapse:collapse;border:1px solid #ddd">
  <thead><tr style="background:#f3f4f6">
    <th style="padding:6px 10px;border:1px solid #ddd;text-align:left">Participante</th>
    <th style="padding:6px 10px;border:1px solid #ddd;text-align:left">RUT</th>
    <th style="padding:6px 10px;border:1px solid #ddd;text-align:left">Código SENCE</th>
    <th style="padding:6px 10px;border:1px solid #ddd">N° ingresos</th>
    <th style="padding:6px 10px;border:1px solid #ddd">Nota</th>
    <th style="padding:6px 10px;border:1px solid #ddd">Eval. rendidas</th>
    <th style="padding:6px 10px;border:1px solid #ddd">Progreso</th>
  </tr></thead>
  <tbody>{filas}</tbody>
</table>
<p style="color:#666;font-size:13px">Este aviso se envía a diario mientras la
condición persista para el curso.</p>
</body></html>"""
    return asunto, html


def main(dry_run=False):
    if not init_db():
        logger.error("Base de datos no disponible")
        sys.exit(1)

    s = get_session()
    enviados = fallidos = afectados_total = 0

    try:
        por_curso = _cursos_afectados(s)

        if not por_curso:
            logger.info("Sin anomalías: ningún participante con cobertura SENCE, "
                        "sin conexión y con notas.")
            return

        # ── Filtro anti-falsos-positivos por scraping SENCE fallido ──────
        # Si la descarga de conectividad de un curso falló, todos sus alumnos
        # quedan con 0 ingresos (SIN_CONEXION) → alarmas falsas. Se omiten los
        # cursos sin datos SENCE frescos y confiables.
        por_curso, omitidos = _filtrar_sence_no_confiable(s, por_curso)
        for id_moodle, id_sence, n in sorted(omitidos):
            logger.warning(
                "Curso %s (SENCE %s): sin datos SENCE frescos (scraping fallido) "
                "→ alerta OMITIDA para %d caso(s) con 0 conexiones no confiables",
                id_moodle, id_sence or "—", n)

        if not por_curso:
            logger.info("Sin anomalías con datos SENCE confiables "
                        "(%d curso[s] omitido[s] por scraping fallido).",
                        len(omitidos))
            return

        for curso_id, afectados in sorted(por_curso.items()):
            curso = s.get(Curso, curso_id)
            if curso is None:
                continue
            pares = _pares(s, afectados)
            afectados_total += len(pares)
            asunto, html = _correo_curso(curso, pares)

            if dry_run:
                logger.info("[DRY-RUN] Para: %s | CC: %s | Asunto: %s",
                            DESTINATARIO, CC, asunto)
                logger.info("        Enlace: %s", MOODLE_COURSE_URL.format(curso.id_moodle))
                for est, i in pares:
                    logger.info("        - %-35s %-12s SENCE %s | nota=%s eval=%s prog=%s",
                                (est.nombre if est else "?")[:35],
                                (est.rut if est else "?"),
                                i.id_sence or "—", _fmt_nota(i.calificacion),
                                i.evaluaciones_rendidas or 0, _fmt_pct(i.progreso))
                continue

            res = enviar_correo(DESTINATARIO, asunto, html, cc=CC)
            if res["status"] == "OK":
                enviados += 1
                logger.info("Curso %s (%s): %d afectado(s) → correo enviado",
                            curso.id_moodle, curso.nombre, len(pares))
            else:
                fallidos += 1
                logger.error("Curso %s (%s): fallo al enviar — %s",
                             curso.id_moodle, curso.nombre, res.get("detalle"))

        if dry_run:
            logger.info("DRY-RUN: %d curso(s) afectado(s), %d participante(s). "
                        "Sin envíos.", len(por_curso), afectados_total)
        else:
            logger.info("Listo: %d correo(s) enviado(s), %d con error, sobre "
                        "%d curso(s) afectado(s), %d participante(s); "
                        "%d curso(s) omitido(s) por scraping SENCE fallido.",
                        enviados, fallidos, len(por_curso), afectados_total,
                        len(omitidos))
    except Exception as e:
        logger.error("Error: %s", e, exc_info=True)
        sys.exit(1)
    finally:
        s.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(
        description="Alerta de participantes con cobertura SENCE, sin conexión y con notas.")
    p.add_argument("--dry-run", action="store_true",
                   help="No envía correos; solo muestra qué haría.")
    args = p.parse_args()
    main(dry_run=args.dry_run)

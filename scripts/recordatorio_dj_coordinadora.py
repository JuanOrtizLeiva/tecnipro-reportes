#!/usr/bin/env python3
"""Recordatorio diario de DJ pendientes a la coordinadora, por acción SENCE.

Para cada IDSence cuyo curso ya terminó (desde el día SIGUIENTE al término,
que es cuando la coordinadora habilita la sección de firmas), envía un correo
diario a la coordinadora con las Declaraciones Juradas que faltan por firmar,
hasta que queden 0. Al llegar a 0 envía un último correo de cierre y deja de
enviar para ese IDSence.

Corre todos los días, incluido fin de semana.

Uso:
    python recordatorio_dj_coordinadora.py [--dry-run] [--fecha YYYY-MM-DD]
"""

import argparse
import logging
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.database import init_db, get_session, get_engine
from src.models import Curso, Inscripcion, Estudiante, SeguimientoDjSence
from src.reports.email_sender import enviar_correo

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("recordatorio_dj")

DESTINATARIO = "ygonzalez@duocapital.cl"
CC = "jortizleiva@duocapital.cl"
FIRMADA = ("Emitida", "Firmada", "Descargada")


def _fmt(d):
    return d.strftime("%d-%m-%Y") if d else "—"


def _correo_pendientes(curso, id_sence, empresa, fterm, pares):
    n = len(pares)
    filas = "".join(
        f"<tr><td style='padding:6px 10px;border:1px solid #ddd'>{nombre}</td>"
        f"<td style='padding:6px 10px;border:1px solid #ddd'>{rut}</td></tr>"
        for nombre, rut in pares
    )
    sub_empresa = f" — {empresa}" if empresa else ""
    asunto = f"DJ pendientes — {curso} (SENCE {id_sence}) — {n} sin firmar"
    html = f"""<html><body style="font-family:Arial,sans-serif;color:#222">
<p>Hola Yasna,</p>
<p>El curso <strong>{curso}</strong>{sub_empresa} (código SENCE
<strong>{id_sence}</strong>) terminó el <strong>{_fmt(fterm)}</strong>.
Quedan <strong>{n}</strong> Declaración(es) Jurada(s) sin firmar:</p>
<table style="border-collapse:collapse;border:1px solid #ddd">
  <thead><tr style="background:#f3f4f6">
    <th style="padding:6px 10px;border:1px solid #ddd;text-align:left">Participante</th>
    <th style="padding:6px 10px;border:1px solid #ddd;text-align:left">RUT</th>
  </tr></thead>
  <tbody>{filas}</tbody>
</table>
<p style="color:#666;font-size:13px">Este resumen se envía a diario hasta que
estén todas firmadas.</p>
</body></html>"""
    return asunto, html


def _correo_cierre(curso, id_sence, empresa):
    sub_empresa = f" — {empresa}" if empresa else ""
    asunto = f"✅ DJ completas — {curso} (SENCE {id_sence})"
    html = f"""<html><body style="font-family:Arial,sans-serif;color:#222">
<p>Hola Yasna,</p>
<p>Todas las Declaraciones Juradas del curso <strong>{curso}</strong>{sub_empresa}
(código SENCE <strong>{id_sence}</strong>) están <strong>firmadas</strong>.
No quedan pendientes. \U0001F389</p>
<p style="color:#666;font-size:13px">No se enviarán más recordatorios para este curso.</p>
</body></html>"""
    return asunto, html


def _enviar(asunto, html, dry_run):
    if dry_run:
        logger.info("[DRY-RUN] Para: %s | CC: %s | Asunto: %s", DESTINATARIO, CC, asunto)
        return {"status": "OK", "detalle": "dry-run"}
    return enviar_correo(DESTINATARIO, asunto, html, cc=CC)


def main(dry_run=False, fecha_override=None):
    if not init_db():
        logger.error("Base de datos no disponible")
        sys.exit(1)

    # Asegurar que la tabla de seguimiento existe (idempotente)
    SeguimientoDjSence.__table__.create(bind=get_engine(), checkfirst=True)

    s = get_session()
    hoy = fecha_override or date.today()
    enviados = cerrados_silencio = cerrados_correo = 0

    try:
        insc = s.query(Inscripcion).filter(Inscripcion.id_sence != "").all()
        por_sence = defaultdict(list)
        for i in insc:
            por_sence[i.id_sence.strip()].append(i)

        for id_sence, lst in sorted(por_sence.items()):
            curso = s.get(Curso, lst[0].curso_id)
            if curso is None:
                continue
            ft = (curso.fecha_termino_sence or "").strip()
            try:
                fterm = date.fromisoformat(ft)
            except ValueError:
                continue  # sin término válido: no se puede saber si terminó

            # Solo desde el día SIGUIENTE al término (la firma se habilita al día siguiente)
            if hoy <= fterm:
                continue

            seg = s.query(SeguimientoDjSence).filter_by(id_sence=id_sence).first()
            if seg and seg.estado == "cerrado":
                continue

            pendientes = [i for i in lst if (i.sence_dj or "").strip() not in FIRMADA]
            n_pend = len(pendientes)
            empresa = (curso.comprador.empresa if curso.comprador else "") or ""

            if seg is None:
                if n_pend == 0:
                    # Ya estaba todo firmado al entrar en alcance → cerrar en silencio
                    s.add(SeguimientoDjSence(
                        id_sence=id_sence, curso_id=curso.id, curso_nombre=curso.nombre,
                        fecha_termino=fterm, estado="cerrado", n_correos=0,
                        ultimo_pendientes=0, fecha_cierre=datetime.now(),
                    ))
                    logger.info("SENCE %s (%s): terminado y 100%% firmado al inicio "
                                "→ cerrado en silencio", id_sence, curso.nombre)
                    cerrados_silencio += 1
                    continue
                seg = SeguimientoDjSence(
                    id_sence=id_sence, curso_id=curso.id, curso_nombre=curso.nombre,
                    fecha_termino=fterm, estado="activo", n_correos=0,
                )
                s.add(seg)
                s.flush()

            # Anti-doble-envío el mismo día
            if seg.fecha_ultimo_correo and seg.fecha_ultimo_correo.date() == hoy:
                logger.info("SENCE %s: ya se envió hoy, skip", id_sence)
                continue

            if n_pend == 0:
                asunto, html = _correo_cierre(curso.nombre, id_sence, empresa)
                _enviar(asunto, html, dry_run)
                seg.estado = "cerrado"
                seg.fecha_cierre = datetime.now()
                seg.ultimo_pendientes = 0
                seg.n_correos = (seg.n_correos or 0) + 1
                seg.fecha_ultimo_correo = datetime.now()
                seg.fecha_primer_correo = seg.fecha_primer_correo or datetime.now()
                logger.info("SENCE %s (%s): 0 pendientes → correo de cierre",
                            id_sence, curso.nombre)
                cerrados_correo += 1
                enviados += 1
            else:
                pares = []
                for i in pendientes:
                    est = s.get(Estudiante, i.estudiante_id)
                    pares.append(((est.nombre if est else "?"), (est.rut if est else "?")))
                pares.sort()
                asunto, html = _correo_pendientes(curso.nombre, id_sence, empresa, fterm, pares)
                _enviar(asunto, html, dry_run)
                if dry_run:
                    for nombre, rut in pares:
                        logger.info("        - %-35s %s", nombre[:35], rut)
                seg.ultimo_pendientes = n_pend
                seg.n_correos = (seg.n_correos or 0) + 1
                seg.fecha_ultimo_correo = datetime.now()
                seg.fecha_primer_correo = seg.fecha_primer_correo or datetime.now()
                logger.info("SENCE %s (%s): %d pendientes → correo enviado",
                            id_sence, curso.nombre, n_pend)
                enviados += 1

        if dry_run:
            s.rollback()
            logger.info("DRY-RUN (fecha=%s): %d correo(s) simulado(s) "
                        "(%d de cierre), %d cerrado(s) en silencio. Sin cambios en BD.",
                        hoy, enviados, cerrados_correo, cerrados_silencio)
        else:
            s.commit()
            logger.info("Listo (fecha=%s): %d correo(s) enviado(s) "
                        "(%d de cierre), %d cerrado(s) en silencio.",
                        hoy, enviados, cerrados_correo, cerrados_silencio)
    except Exception as e:
        s.rollback()
        logger.error("Error: %s", e, exc_info=True)
        sys.exit(1)
    finally:
        s.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Recordatorio diario de DJ pendientes a la coordinadora.")
    p.add_argument("--dry-run", action="store_true",
                   help="No envía ni persiste; solo muestra qué haría.")
    p.add_argument("--fecha", help="Override de fecha (YYYY-MM-DD), solo para previsualizar.")
    args = p.parse_args()
    fecha = date.fromisoformat(args.fecha) if args.fecha else None
    main(dry_run=args.dry_run, fecha_override=fecha)

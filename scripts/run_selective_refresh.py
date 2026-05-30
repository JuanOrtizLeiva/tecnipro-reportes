#!/usr/bin/env python3
"""Actualización selectiva: SENCE IDs específicos + pipeline para cursos Moodle específicos.

Uso:
    python run_selective_refresh.py <email> <course_ids_json> <sence_ids_json> [job_id]

Ejemplo:
    python run_selective_refresh.py user@mail.com '[207]' '["6770574"]' abc12345
"""

import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings
from src.reports.email_sender import enviar_correo

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent


def _write_status(job_id, status, message="", **extra):
    """Escribe archivo de status para que el frontend pueda hacer polling."""
    if not job_id:
        return
    status_path = PROJECT_ROOT / "data" / "output" / f"refresh_status_{job_id}.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    data = {"status": status, "message": message}
    data.update(extra)
    status_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def main():
    usuario_email = sys.argv[1] if len(sys.argv) > 1 else settings.EMAIL_CC
    course_ids = json.loads(sys.argv[2]) if len(sys.argv) > 2 else []
    sence_ids = json.loads(sys.argv[3]) if len(sys.argv) > 3 else []
    job_id = sys.argv[4] if len(sys.argv) > 4 else None

    inicio = datetime.now()
    logger.info("=" * 60)
    logger.info("ACTUALIZACIÓN SELECTIVA EN SEGUNDO PLANO")
    logger.info("Iniciado por: %s", usuario_email)
    logger.info("Cursos Moodle: %s", course_ids)
    logger.info("IDs SENCE: %s", sence_ids)
    logger.info("Job ID: %s", job_id)
    logger.info("Inicio: %s", inicio.strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("=" * 60)

    errores = []
    resultado = {
        "scraper": {"status": "skipped", "descargados": 0, "fallidos": 0},
        "pipeline": {"status": "pending", "cursos": 0, "estudiantes": 0},
    }

    # ── Paso 1: Scraper SENCE (solo IDs seleccionados) ──────
    if sence_ids:
        _write_status(job_id, "running", f"Descargando SENCE: {', '.join(sence_ids)}...")
        try:
            logger.info("Paso 1/2: Scraper SENCE para IDs: %s", sence_ids)
            from src.scraper.sence_scraper import SenceScraper
            from src.scraper.orchestrator import ScraperOrchestrator

            # Clasificar cuáles necesitan DJ. En la actualización selectiva el
            # usuario pidió explícitamente estos IDs SENCE, así que se fuerza
            # el re-scraping de la DJ (no confiar en la caché de completitud).
            orch = ScraperOrchestrator(headless=True)
            ids_requieren_dj = orch._clasificar_cursos_dj(sence_ids, forzar_dj=True)

            scraper = SenceScraper(headless=True)
            try:
                asyncio.run(_run_scraper(scraper, sence_ids, ids_requieren_dj))
                resultado["scraper"]["status"] = "ok"
                resultado["scraper"]["descargados"] = len(sence_ids)
            except Exception as e:
                logger.error("Error en scraper SENCE: %s", e, exc_info=True)
                resultado["scraper"]["status"] = "error"
                errores.append(f"Scraper SENCE: {e}")
        except Exception as e:
            logger.error("Error inicializando scraper: %s", e, exc_info=True)
            resultado["scraper"]["status"] = "error"
            errores.append(f"Scraper init: {e}")
    else:
        logger.info("Paso 1/2: Sin IDs SENCE — omitiendo scraper")

    # ── Paso 2: Pipeline para cursos seleccionados ──────────
    _write_status(job_id, "running", "Ejecutando pipeline Moodle...")
    try:
        logger.info("Paso 2/2: Pipeline para cursos Moodle: %s", course_ids or "TODOS")
        from src.main import run_pipeline
        datos_json = run_pipeline(course_ids=course_ids or None)

        resultado["pipeline"]["status"] = "ok"
        resultado["pipeline"]["cursos"] = datos_json["metadata"]["total_cursos"]
        resultado["pipeline"]["estudiantes"] = datos_json["metadata"]["total_estudiantes"]

        logger.info(
            "Pipeline completado: %d cursos, %d estudiantes",
            resultado["pipeline"]["cursos"],
            resultado["pipeline"]["estudiantes"],
        )
    except Exception as e:
        logger.error("Error en pipeline: %s", e, exc_info=True)
        resultado["pipeline"]["status"] = "error"
        errores.append(f"Pipeline: {e}")

    # ── Paso 3: Notificación ────────────────────────────────
    fin = datetime.now()
    duracion = (fin - inicio).total_seconds() / 60

    exitoso = (
        resultado["scraper"]["status"] in ("ok", "skipped")
        and resultado["pipeline"]["status"] == "ok"
        and not errores
    )

    # Escribir status final para el frontend
    if exitoso:
        _write_status(
            job_id, "ok",
            f"Listo en {duracion:.1f} min — {resultado['pipeline']['cursos']} cursos, {resultado['pipeline']['estudiantes']} estudiantes",
        )
    else:
        _write_status(
            job_id, "error",
            "; ".join(errores) if errores else "Error desconocido",
        )

    color = "#16a34a" if exitoso else "#dc2626"
    icono = "✅" if exitoso else "⚠️"
    asunto = f"{icono} Actualización selectiva finalizada"

    sence_detalle = f"{resultado['scraper']['descargados']} descargados" if sence_ids else "omitido"

    mensaje_html = f"""
<html><body style="font-family: Arial, sans-serif;">
<div style="background-color: {color}; color: white; padding: 16px 20px;">
  <h2 style="margin: 0;">{icono} Actualización Selectiva Finalizada</h2>
</div>
<div style="padding: 20px; background: #f9fafb; border: 2px solid {color}; border-top: none;">
  <p><strong>Solicitado por:</strong> {usuario_email}</p>
  <p><strong>Cursos Moodle:</strong> {', '.join(str(c) for c in course_ids) if course_ids else 'Todos'}</p>
  <p><strong>IDs SENCE:</strong> {', '.join(sence_ids) if sence_ids else 'Ninguno'}</p>
  <p><strong>Duración:</strong> {duracion:.1f} minutos</p>
  <table style="width:100%;border-collapse:collapse;border:1px solid #ddd;background:white;margin:16px 0;">
    <thead><tr style="background-color:{color};color:white;">
      <th style="padding:8px;border:1px solid #ddd;text-align:left">Componente</th>
      <th style="padding:8px;border:1px solid #ddd;text-align:left">Estado</th>
      <th style="padding:8px;border:1px solid #ddd;text-align:left">Detalle</th>
    </tr></thead>
    <tbody>
      <tr><td style="padding:8px;border:1px solid #ddd"><strong>Scraper SENCE</strong></td>
          <td style="padding:8px;border:1px solid #ddd">{resultado['scraper']['status'].upper()}</td>
          <td style="padding:8px;border:1px solid #ddd">{sence_detalle}</td></tr>
      <tr><td style="padding:8px;border:1px solid #ddd"><strong>Pipeline</strong></td>
          <td style="padding:8px;border:1px solid #ddd">{resultado['pipeline']['status'].upper()}</td>
          <td style="padding:8px;border:1px solid #ddd">{resultado['pipeline']['cursos']} cursos, {resultado['pipeline']['estudiantes']} estudiantes</td></tr>
    </tbody>
  </table>
  {"".join(f'<p style="color:#dc2626">Error: {e}</p>' for e in errores)}
</div>
</body></html>
"""

    try:
        enviar_correo(
            destinatario=usuario_email,
            asunto=asunto,
            cuerpo_html=mensaje_html,
            cc="",
        )
        logger.info("Notificación enviada a %s", usuario_email)
    except Exception as e:
        logger.error("Error enviando correo: %s", e)

    sys.exit(0 if exitoso else 1)


async def _run_scraper(scraper, sence_ids, ids_requieren_dj):
    """Ejecuta el scraper con los IDs dados."""
    try:
        await scraper.start()
        await scraper.run(sence_ids, ids_requieren_dj=ids_requieren_dj)
    finally:
        await scraper.close()


if __name__ == "__main__":
    main()

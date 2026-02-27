"""Orquestador principal — ejecuta el pipeline completo de procesamiento.

Modos de ejecución:
    python -m src.main              → solo pipeline (comportamiento Fase 1)
    python -m src.main --scrape     → scraper SENCE + pipeline
    python -m src.main --scrape-only → solo scraper sin pipeline
    python -m src.main --visible    → (con --scrape) muestra el navegador
    python -m src.main --report     → pipeline + generar PDFs
    python -m src.main --report --email → pipeline + PDFs + enviar correos
    python -m src.main --report --email --dry-run → PDFs + sin enviar correos
    python -m src.main --report-only → solo generar PDFs (usa JSON existente)
    python -m src.main --scrape --report --email → flujo completo
    python -m src.main --web        → levantar servidor web (dashboard)
    python -m src.main --web --port 8080 → servidor web en puerto específico
    python -m src.main --report --web → pipeline + PDFs + dashboard
"""

import argparse
import asyncio
import logging
import sys

from config import settings

# Configurar logging antes de importar módulos que lo usen
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def run_pipeline(course_ids=None):
    """Ejecuta el pipeline completo: ingest → transform → output."""
    logger.info("=" * 60)
    logger.info("Iniciando procesamiento Tecnipro Reportes")
    logger.info("=" * 60)

    # ── Paso 1: Ingest ─────────────────────────────────────
    logger.info("─── PASO 1: Lectura de datos ───")

    from src.ingest.sence_reader import leer_sence
    from src.ingest.compradores_reader import leer_compradores

    # ── Lectura de datos Moodle (CSV o API) ────────────────────
    if settings.DATA_SOURCE == "api":
        logger.info("Modo API: leyendo desde Moodle API REST")
        from src.ingest.moodle_api_reader import leer_datos_moodle

        try:
            df_merged_base = leer_datos_moodle(course_ids=course_ids)
        except Exception as e:
            logger.error("Error leyendo Moodle API: %s", e)
            raise RuntimeError(f"No se puede continuar sin datos Moodle: {e}") from e
    else:
        logger.info("Modo CSV: leyendo desde Greporte.csv y Dreporte.csv")
        from src.ingest.dreporte_reader import leer_dreporte
        from src.ingest.greporte_reader import leer_greporte

        try:
            df_dreporte = leer_dreporte()
        except Exception as e:
            logger.error("Error leyendo Dreporte: %s", e)
            logger.error("No se puede continuar sin Dreporte")
            sys.exit(1)

        try:
            df_greporte = leer_greporte()
        except Exception as e:
            logger.error("Error leyendo Greporte: %s", e)
            logger.error("No se puede continuar sin Greporte")
            sys.exit(1)

        # Merge Greporte+Dreporte solo en modo CSV
        from src.transform.merger import merge_greporte_dreporte
        df_merged_base = merge_greporte_dreporte(df_greporte, df_dreporte)

    # Lectura de SENCE y compradores (común a ambos modos)
    try:
        df_sence = leer_sence()
    except Exception as e:
        logger.error("Error leyendo SENCE: %s", e)
        df_sence = None

    try:
        df_compradores = leer_compradores()
    except Exception as e:
        logger.error("Error leyendo compradores: %s", e)
        df_compradores = None

    # ── Paso 2: Transform ──────────────────────────────────
    logger.info("─── PASO 2: Cruce y transformación ───")

    from src.transform.merger import (
        merge_sence_into_dreporte,
        merge_compradores,
    )
    from src.transform.calculator import calcular_campos

    # 2a. Cruzar SENCE con df_merged_base
    if df_sence is not None and not df_sence.empty:
        df_merged = merge_sence_into_dreporte(df_merged_base, df_sence)
    else:
        df_merged = df_merged_base.copy()
        df_merged["N_Ingresos"] = 0
        df_merged["DJ"] = ""
        logger.warning("Sin datos SENCE — continuando sin cruce")

    # 2c. Cruzar con compradores
    if df_compradores is not None and not df_compradores.empty:
        df_merged = merge_compradores(df_merged, df_compradores)
    else:
        df_merged["comprador_nombre"] = ""
        df_merged["empresa"] = ""
        df_merged["email_comprador"] = ""

    # 2d. Calcular campos
    df_merged = calcular_campos(df_merged)

    logger.info("DataFrame final: %d filas, %d columnas", *df_merged.shape)

    # ── Paso 3: Output ─────────────────────────────────────
    logger.info("─── PASO 3: Generación de salidas ───")

    from src.output.json_exporter import exportar_json
    from src.output.sqlite_store import guardar_snapshot

    # 3a. Detectar fecha de última actualización SENCE (mtime del archivo más reciente)
    fecha_sence = None
    try:
        from pathlib import Path as _Path
        sence_folder = _Path(settings.SENCE_CSV_PATH)
        archivos_sence = list(sence_folder.glob("*.csv")) if sence_folder.exists() else []
        if archivos_sence:
            from datetime import datetime as _dt, timezone as _tz
            mtime = max(f.stat().st_mtime for f in archivos_sence)
            fecha_sence = _dt.fromtimestamp(mtime, tz=_tz.utc).isoformat(timespec="seconds")
            logger.info("Fecha última actualización SENCE: %s", fecha_sence)
    except Exception as e:
        logger.warning("No se pudo detectar fecha SENCE: %s", e)

    # 3b. Exportar JSON
    datos_json = exportar_json(df_merged, fecha_sence=fecha_sence)
    logger.info(
        "JSON: %d cursos, %d estudiantes",
        datos_json["metadata"]["total_cursos"],
        datos_json["metadata"]["total_estudiantes"],
    )

    # 3b. Guardar snapshot SQLite
    try:
        guardar_snapshot(datos_json)
    except Exception as e:
        logger.error("Error guardando snapshot SQLite: %s", e)

    logger.info("=" * 60)
    logger.info("Procesamiento completado exitosamente")
    logger.info("=" * 60)

    return datos_json


async def run_scraper(headless=True):
    """Ejecuta el scraper SENCE y retorna el reporte."""
    from src.scraper.orchestrator import ScraperOrchestrator

    orchestrator = ScraperOrchestrator(headless=headless)
    report = await orchestrator.run()
    return report


def run_reports(send_email=False, dry_run=False, json_path=None):
    """Ejecuta la generación de reportes PDF y envío de correos."""
    from src.reports.reports_orchestrator import ReportsOrchestrator

    orchestrator = ReportsOrchestrator(send_email=send_email, dry_run=dry_run)
    report = orchestrator.run(json_path=json_path)

    # Si hubo errores de validación, detener con código 1
    if report.get("errores_validacion"):
        logger.error("Proceso detenido por errores de validación")
        sys.exit(1)

    return report


def run_web(port=None, host=None):
    """Levanta el servidor web Flask con el dashboard."""
    from src.web.app import create_app

    _port = port or settings.WEB_PORT
    _host = host or settings.WEB_HOST

    app = create_app()

    logger.info("=" * 60)
    logger.info("Servidor web iniciando en http://%s:%s", _host, _port)
    logger.info("Dashboard: http://localhost:%s", _port)
    logger.info("Ctrl+C para detener")
    logger.info("=" * 60)

    app.run(host=_host, port=_port, debug=False)


def main():
    """Punto de entrada principal con soporte de argumentos."""
    parser = argparse.ArgumentParser(description="Tecnipro Reportes")
    parser.add_argument(
        "--scrape",
        action="store_true",
        help="Ejecutar scraper SENCE antes del pipeline",
    )
    parser.add_argument(
        "--scrape-only",
        action="store_true",
        help="Ejecutar solo el scraper SENCE (sin pipeline)",
    )
    parser.add_argument(
        "--visible",
        action="store_true",
        help="Mostrar el navegador durante el scraping (headless=False)",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Generar reportes PDF por comprador después del pipeline",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Solo generar reportes PDF (usa JSON existente, sin pipeline)",
    )
    parser.add_argument(
        "--email",
        action="store_true",
        help="Enviar reportes por correo (requiere --report o --report-only)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Modo prueba: genera PDFs pero NO envía correos",
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="Levantar servidor web con dashboard después del pipeline",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Puerto para el servidor web (default: 5000)",
    )
    args = parser.parse_args()

    # Log explícito del estado de flags de reporte
    if args.report or args.report_only:
        logger.info(
            "Flags: report=%s, report_only=%s, email=%s, dry_run=%s",
            args.report, args.report_only, args.email, args.dry_run,
        )

    headless = not args.visible

    # ── Modo scraper ────────────────────────────────────
    if args.scrape or args.scrape_only:
        logger.info("Modo scraper activado (headless=%s)", headless)
        report = asyncio.run(run_scraper(headless=headless))

        if args.scrape_only:
            # Solo scraper, no ejecutar pipeline
            ok = len(report.get("descargados_ok", []))
            fail = len(report.get("fallidos", []))
            logger.info("Scraper finalizado: %d OK, %d fallidos", ok, fail)
            return report

        # --scrape: continuar con pipeline si hubo descargas
        if report.get("pipeline_fase1") == "OK":
            logger.info("Pipeline Fase 1 ya ejecutado por el orquestador")
            # Si también pide reportes, ejecutarlos
            if args.report:
                run_reports(
                    send_email=args.email,
                    dry_run=args.dry_run,
                )
            if args.web:
                run_web(port=args.port)
            return report

    # ── Modo report-only (sin pipeline) ─────────────────
    if args.report_only:
        logger.info("Modo report-only: generando PDFs desde JSON existente")
        run_reports(
            send_email=args.email,
            dry_run=args.dry_run,
        )
        if args.web:
            run_web(port=args.port)
        return None

    # ── Modo solo web (sin pipeline) ──────────────────
    if args.web and not args.report:
        run_web(port=args.port)
        return None

    # ── Modo por defecto: pipeline ──────────────────────
    datos_json = run_pipeline()

    # ── Reportes si solicitados ─────────────────────────
    if args.report:
        run_reports(
            send_email=args.email,
            dry_run=args.dry_run,
        )

    # ── Servidor web si solicitado ─────────────────────
    if args.web:
        run_web(port=args.port)

    return datos_json


if __name__ == "__main__":
    main()

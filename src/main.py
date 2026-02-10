"""Orquestador principal — ejecuta el pipeline completo de procesamiento."""

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


def main():
    """Ejecuta el pipeline completo: ingest → transform → output."""
    logger.info("=" * 60)
    logger.info("Iniciando procesamiento Tecnipro Reportes")
    logger.info("=" * 60)

    # ── Paso 1: Ingest ─────────────────────────────────────
    logger.info("─── PASO 1: Lectura de datos ───")

    from src.ingest.sence_reader import leer_sence
    from src.ingest.dreporte_reader import leer_dreporte
    from src.ingest.greporte_reader import leer_greporte
    from src.ingest.compradores_reader import leer_compradores

    try:
        df_sence = leer_sence()
    except Exception as e:
        logger.error("Error leyendo SENCE: %s", e)
        df_sence = None

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

    try:
        df_compradores = leer_compradores()
    except Exception as e:
        logger.error("Error leyendo compradores: %s", e)
        df_compradores = None

    # ── Paso 2: Transform ──────────────────────────────────
    logger.info("─── PASO 2: Cruce y transformación ───")

    from src.transform.merger import (
        merge_sence_into_dreporte,
        merge_greporte_dreporte,
        merge_compradores,
    )
    from src.transform.calculator import calcular_campos
    import pandas as pd

    # 2a. Cruzar SENCE con Dreporte
    if df_sence is not None and not df_sence.empty:
        df_dreporte = merge_sence_into_dreporte(df_dreporte, df_sence)
    else:
        df_dreporte["N_Ingresos"] = 0
        df_dreporte["DJ"] = ""
        logger.warning("Sin datos SENCE — continuando sin cruce")

    # 2b. Cruzar Greporte con Dreporte
    df_merged = merge_greporte_dreporte(df_greporte, df_dreporte)

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

    # 3a. Exportar JSON
    datos_json = exportar_json(df_merged)
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


if __name__ == "__main__":
    main()

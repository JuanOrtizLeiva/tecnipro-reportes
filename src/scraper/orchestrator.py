"""Agente orquestador — coordina scraping, validación y pipeline Fase 1."""

import json
import logging
import os
from datetime import datetime
from pathlib import Path

import pandas as pd

from config import settings

logger = logging.getLogger(__name__)


class ScraperOrchestrator:
    """Orquesta el flujo completo: IDs → scraping → validación → pipeline."""

    def __init__(self, headless=True):
        self.headless = headless

    async def run(self):
        """Ejecuta el flujo completo y retorna un reporte detallado."""
        report = {
            "inicio": datetime.now().isoformat(),
            "ids_solicitados": [],
            "descargados_ok": [],
            "descargados_vacios": [],
            "fallidos": [],
            "errores": [],
            "pipeline_fase1": None,
            "fin": None,
        }

        # ── Paso 1: Obtener IDs SENCE del Dreporte ────────
        logger.info("═" * 60)
        logger.info("ORQUESTADOR: Obteniendo IDs SENCE del Dreporte")
        logger.info("═" * 60)

        try:
            sence_ids = self.get_sence_ids()
            report["ids_solicitados"] = sence_ids
            logger.info("IDs SENCE a descargar: %d → %s", len(sence_ids), sence_ids)
        except Exception as e:
            msg = f"Error obteniendo IDs SENCE: {e}"
            logger.error(msg)
            report["errores"].append(msg)
            report["fin"] = datetime.now().isoformat()
            self._save_report(report)
            return report

        if not sence_ids:
            logger.warning("No hay IDs SENCE para descargar")
            report["fin"] = datetime.now().isoformat()
            self._save_report(report)
            return report

        # ── Paso 2: Ejecutar scraper ──────────────────────
        logger.info("═" * 60)
        logger.info("ORQUESTADOR: Iniciando scraper SENCE")
        logger.info("═" * 60)

        from src.scraper.sence_scraper import SenceScraper

        scraper = SenceScraper(headless=self.headless)
        try:
            await scraper.start()
            scraping_result = await scraper.run(sence_ids)

            report["descargados_ok"] = scraping_result.get("descargados", [])
            report["fallidos"] = scraping_result.get("fallidos", [])
            report["errores"].extend(scraping_result.get("errores", []))
        except Exception as e:
            msg = f"Error en scraper: {e}"
            logger.error(msg)
            report["errores"].append(msg)
        finally:
            await scraper.close()

        # ── Paso 3: Verificar archivos descargados ────────
        logger.info("═" * 60)
        logger.info("ORQUESTADOR: Verificando archivos descargados")
        logger.info("═" * 60)

        self._verify_downloaded_files(report)

        # ── Paso 4: Ejecutar pipeline Fase 1 ──────────────
        logger.info("═" * 60)
        logger.info("ORQUESTADOR: Ejecutando pipeline Fase 1")
        logger.info("═" * 60)

        if report["descargados_ok"] or self._hay_sence_previos():
            try:
                from src.main import run_pipeline
                run_pipeline()
                report["pipeline_fase1"] = "OK"
                logger.info("Pipeline Fase 1 completado exitosamente")
            except Exception as e:
                msg = f"Pipeline Fase 1: {e}"
                report["pipeline_fase1"] = f"ERROR: {e}"
                report["errores"].append(msg)
                logger.error("Pipeline Fase 1 falló: %s", e)
        else:
            report["pipeline_fase1"] = "SKIPPED: sin archivos SENCE"
            logger.warning("Pipeline saltado: no hay archivos SENCE descargados")

        # ── Paso 5: Reporte final ─────────────────────────
        report["fin"] = datetime.now().isoformat()
        self._save_report(report)
        self._log_summary(report)

        return report

    def get_sence_ids(self):
        """Obtiene lista de IDs SENCE únicos del Dreporte.

        Returns
        -------
        list[str]
            IDs numéricos como strings.
        """
        dreporte_path = settings.DATA_INPUT_PATH
        dreporte_file = None
        for f in sorted(dreporte_path.iterdir()):
            if f.name.lower().startswith("d") and f.suffix.lower() == ".csv":
                dreporte_file = f
                break

        if dreporte_file is None:
            raise FileNotFoundError(
                f"No se encontró Dreporte.csv en {dreporte_path}"
            )

        df = pd.read_csv(dreporte_file, encoding="utf-8-sig", dtype=str)
        raw_ids = df["IDSence"].dropna().unique()

        ids = []
        for val in raw_ids:
            val = str(val).strip()
            # Convertir float-like strings: "6731347.0" → "6731347"
            try:
                num = int(float(val))
                ids.append(str(num))
            except (ValueError, TypeError):
                continue

        return sorted(set(ids))

    def _verify_downloaded_files(self, report):
        """Verifica que los archivos descargados existen y son legibles."""
        sence_dir = settings.SENCE_CSV_PATH

        verified_ok = []
        for sence_id in report["descargados_ok"]:
            filepath = sence_dir / f"{sence_id}.csv"

            if not filepath.exists():
                report["errores"].append(
                    f"{sence_id}: archivo no encontrado tras descarga"
                )
                continue

            size = filepath.stat().st_size
            if size == 0:
                report["descargados_vacios"].append(sence_id)
                logger.debug("SENCE %s: archivo vacío (0 bytes)", sence_id)
                continue

            # Verificar encoding
            contenido = None
            for enc in ("utf-8", "latin-1"):
                try:
                    contenido = filepath.read_text(encoding=enc)
                    break
                except (UnicodeDecodeError, ValueError):
                    continue

            if contenido is None:
                report["errores"].append(
                    f"{sence_id}: encoding no reconocido"
                )
                continue

            # Verificar si tiene "No hay datos"
            if "no hay datos" in contenido.lower():
                report["descargados_vacios"].append(sence_id)
                logger.debug("SENCE %s: sin datos disponibles", sence_id)
                continue

            verified_ok.append(sence_id)

        logger.info(
            "Verificación: %d OK, %d vacíos, %d errores",
            len(verified_ok),
            len(report["descargados_vacios"]),
            len([e for e in report["errores"] if any(
                sid in e for sid in report["descargados_ok"]
            )]),
        )

    def _hay_sence_previos(self):
        """Verifica si ya existen archivos SENCE de ejecuciones anteriores."""
        sence_dir = settings.SENCE_CSV_PATH
        if not sence_dir.exists():
            return False
        return any(sence_dir.glob("*.csv"))

    def _save_report(self, report):
        """Guarda el reporte JSON en data/output/."""
        output_dir = settings.OUTPUT_PATH
        output_dir.mkdir(parents=True, exist_ok=True)

        fecha = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = output_dir / f"scraper_report_{fecha}.json"

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)

        logger.info("Reporte guardado: %s", filepath)

    def _log_summary(self, report):
        """Imprime resumen final del proceso."""
        logger.info("═" * 60)
        logger.info("RESUMEN ORQUESTADOR")
        logger.info("═" * 60)
        logger.info("  Inicio:            %s", report["inicio"])
        logger.info("  Fin:               %s", report["fin"])
        logger.info("  IDs solicitados:   %d", len(report["ids_solicitados"]))
        logger.info("  Descargados OK:    %d", len(report["descargados_ok"]))
        logger.info("  Vacíos:            %d", len(report["descargados_vacios"]))
        logger.info("  Fallidos:          %d", len(report["fallidos"]))
        logger.info("  Errores:           %d", len(report["errores"]))
        logger.info("  Pipeline Fase 1:   %s", report["pipeline_fase1"])

        if report["errores"]:
            logger.warning("  Errores detallados:")
            for err in report["errores"]:
                logger.warning("    - %s", err)

        if report["fallidos"]:
            logger.warning("  IDs fallidos: %s", report["fallidos"])

        logger.info("═" * 60)

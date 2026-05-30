"""Agente orquestador — coordina scraping, validación y pipeline Fase 1."""

import json
import logging
import os
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from config import settings

logger = logging.getLogger(__name__)


class ScraperOrchestrator:
    """Orquesta el flujo completo: IDs → scraping → validación → pipeline."""

    def __init__(self, headless=True):
        self.headless = headless
        # {id_sence: nº de participantes según Moodle}; lo puebla get_sence_ids().
        # Punto de control para detectar DJ truncadas por paginación del portal.
        self._conteo_moodle = {}

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

        # ── Paso 1b: Clasificar cursos que necesitan DJ ───
        ids_requieren_dj = self._clasificar_cursos_dj(sence_ids)
        report["ids_requieren_dj"] = sorted(ids_requieren_dj)
        if ids_requieren_dj:
            logger.info(
                "Cursos terminados que requieren DJ: %d → %s",
                len(ids_requieren_dj), sorted(ids_requieren_dj),
            )
        else:
            logger.info("Ningún curso terminado — solo se descarga conectividad")

        # ── Paso 2: Ejecutar scraper ──────────────────────
        logger.info("═" * 60)
        logger.info("ORQUESTADOR: Iniciando scraper SENCE")
        logger.info("═" * 60)

        from src.scraper.sence_scraper import SenceScraper

        scraper = SenceScraper(headless=self.headless)
        try:
            await scraper.start()
            scraping_result = await scraper.run(sence_ids, ids_requieren_dj=ids_requieren_dj)

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
        """Obtiene lista de IDs SENCE únicos.

        Si DATA_SOURCE=api: Obtiene IDs desde Moodle API REST
        Si DATA_SOURCE=csv: Obtiene IDs desde Dreporte.csv

        Returns
        -------
        list[str]
            IDs numéricos como strings.
        """
        # Modo API: obtener IDs (y conteo de participantes) desde Moodle
        if settings.DATA_SOURCE == "api":
            logger.info("Modo API: obteniendo IDs SENCE desde Moodle API")
            try:
                from src.ingest.moodle_api_client import get_sence_participant_counts
                # Conteo por ID SENCE (no por curso): un curso Moodle puede
                # tener varios IDs SENCE. Se usa como punto de control de la DJ.
                self._conteo_moodle = get_sence_participant_counts()
                return sorted(self._conteo_moodle.keys())
            except Exception as e:
                logger.error("Error obteniendo IDs SENCE desde API: %s", e)
                raise RuntimeError(f"No se pueden obtener IDs SENCE desde API: {e}") from e

        # Modo CSV: obtener IDs desde Dreporte.csv
        logger.info("Modo CSV: obteniendo IDs SENCE desde Dreporte.csv")
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

        # Normalizar IDSence ("6731347.0" → "6731347") y contar RUTs únicos por
        # ID SENCE. El cruce es por ID SENCE, no por curso (un curso Moodle
        # puede tener más de un código SENCE).
        def _norm_id(val):
            try:
                return str(int(float(str(val).strip())))
            except (ValueError, TypeError):
                return None

        df = df.dropna(subset=["IDSence"]).copy()
        df["_id_sence"] = df["IDSence"].map(_norm_id)
        df = df[df["_id_sence"].notna()]

        conteo = df.groupby("_id_sence")["ID del Usuario"].nunique().to_dict()
        self._conteo_moodle = {str(k): int(v) for k, v in conteo.items()}

        return sorted(self._conteo_moodle.keys())

    def _clasificar_cursos_dj(self, sence_ids, forzar_dj=False):
        """Determina qué cursos SENCE necesitan scraping de DJ.

        Un curso necesita DJ si:
        - Tiene metadatos previos con fecha_termino_sence <= ayer
        - O si no tiene metadatos (primera vez, se verificará en el scraper)

        En la primera ejecución (sin metadatos), todos los cursos pasan por
        el scraper normalmente. El scraper captura los metadatos y en la
        siguiente ejecución se puede clasificar correctamente.

        Parameters
        ----------
        forzar_dj : bool
            Si es True, re-scrapea la DJ de todo curso terminado aunque su
            caché parezca completa. Se usa en la actualización selectiva,
            donde el usuario pide explícitamente refrescar esos IDs SENCE.

        Returns
        -------
        set[str]
            IDs SENCE de cursos que requieren scraping de DJ.
        """
        metadatos = self._cargar_metadatos_sence()
        if not metadatos:
            # Sin metadatos previos: no sabemos fechas, no scrapear DJ aún
            # (los metadatos se capturarán en esta ejecución)
            logger.info("Sin metadatos SENCE previos — DJ se activará en próxima ejecución")
            return set()

        ayer = date.today() - timedelta(days=1)
        ids_requieren_dj = set()

        for sence_id in sence_ids:
            meta = metadatos.get(sence_id, {})
            fecha_termino = meta.get("fecha_termino_sence")

            if not fecha_termino:
                # Sin fecha de término conocida, no sabemos si terminó
                continue

            try:
                dt_termino = date.fromisoformat(fecha_termino)
            except (ValueError, TypeError):
                continue

            if dt_termino <= ayer:
                # Curso terminado en SENCE → re-scrapear DJ si se fuerza o si
                # la caché no está completa (cobertura vs matrícula Moodle).
                if forzar_dj or not self._todas_dj_completas(sence_id):
                    ids_requieren_dj.add(sence_id)
                else:
                    logger.debug("SENCE %s: todas las DJ completas, skip", sence_id)

        return ids_requieren_dj

    def _cargar_metadatos_sence(self):
        """Lee metadatos_sence.json si existe."""
        ruta = settings.SENCE_METADATOS_PATH
        if not ruta.exists():
            return {}
        try:
            return json.loads(ruta.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Error leyendo metadatos SENCE: %s", e)
            return {}

    def _todas_dj_completas(self, sence_id):
        """Verifica si un curso SENCE ya tiene TODAS las DJ scrapeadas y no vacías.

        Lee el archivo _dj.csv (cache de DJ scrapeada). Para considerarse
        completo deben cumplirse DOS condiciones:

        1. Todas las filas presentes en _dj.csv tienen DJ no vacía.
        2. El nº de filas DJ cubre la matrícula real del ID SENCE según Moodle.
           Si hay menos filas DJ que participantes Moodle para ese ID SENCE,
           hubo truncamiento por paginación: el curso NO está completo y se
           debe re-scrapear. El cruce es por ID SENCE (no por curso Moodle).
        """
        dj_cache_path = settings.SENCE_CSV_PATH / f"{sence_id}_dj.csv"
        if not dj_cache_path.exists():
            return False

        try:
            contenido = None
            for enc in ("utf-8", "latin-1"):
                try:
                    contenido = dj_cache_path.read_text(encoding=enc)
                    break
                except (UnicodeDecodeError, ValueError):
                    continue

            if not contenido or "no hay datos" in contenido.lower():
                return False

            import csv
            reader = csv.reader(contenido.strip().splitlines())
            n_dj = 0
            for row in reader:
                if len(row) < 4:
                    continue
                # Ignorar filas sin RUT válido
                if not any(c.isdigit() for c in row[0]):
                    continue
                n_dj += 1
                # Columna DJ es la 4ta (índice 3)
                dj = row[3].strip()
                if not dj or dj.lower() == "pendiente de emitir":
                    return False  # Al menos un alumno sin DJ

            if n_dj == 0:
                return False

            # Punto de control: cobertura completa vs matrícula Moodle por ID SENCE.
            n_moodle = self._conteo_moodle.get(sence_id)
            if n_moodle is not None and n_dj < n_moodle:
                logger.warning(
                    "SENCE %s: DJ incompleta — %d filas en _dj.csv vs %d "
                    "participantes en Moodle (truncamiento de paginación). "
                    "Se forzará re-scraping.",
                    sence_id, n_dj, n_moodle,
                )
                return False

            return True  # Todas presentes tienen DJ y cobertura completa
        except Exception as e:
            logger.debug("Error verificando DJ completas para %s: %s", sence_id, e)
            return False

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

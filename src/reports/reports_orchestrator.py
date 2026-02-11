"""Orquestador de generación de reportes PDF y envío por correo."""

import json
import logging
from datetime import datetime
from pathlib import Path

from config import settings

logger = logging.getLogger(__name__)


class ReportsOrchestrator:
    """Coordina generación de PDFs y envío de correos."""

    def __init__(self, send_email=False, dry_run=False):
        self.send_email = bool(send_email)
        self.dry_run = bool(dry_run)
        logger.debug(
            "ReportsOrchestrator: send_email=%s, dry_run=%s",
            self.send_email, self.dry_run,
        )

    def run(self, json_path=None):
        """Ejecuta el flujo completo: generar PDFs y opcionalmente enviar correos.

        Parameters
        ----------
        json_path : Path | str | None
            Ruta al JSON de datos. Si es None, usa settings.JSON_DATOS_PATH.

        Returns
        -------
        dict
            Reporte de ejecución.
        """
        from src.reports.pdf_generator import (
            cargar_datos,
            agrupar_por_comprador,
            generar_pdf,
        )

        inicio = datetime.now()

        report = {
            "inicio": inicio.isoformat(),
            "fin": None,
            "pdfs_generados": [],
            "pdfs_fallidos": [],
            "correos_enviados": [],
            "correos_fallidos": [],
            "correos_sin_email": [],
            "modo_dry_run": self.dry_run,
        }

        # ── 1. Verificar JSON ────────────────────────────────
        logger.info("=" * 60)
        logger.info("REPORTES: Verificando datos de entrada")
        logger.info("=" * 60)

        try:
            datos = cargar_datos(json_path)
        except (FileNotFoundError, ValueError) as e:
            logger.error("Error cargando datos: %s", e)
            report["fin"] = datetime.now().isoformat()
            self._guardar_reporte(report)
            return report

        # ── 1b. Validar consistencia de emails en compradores ──
        from src.ingest.compradores_reader import validar_emails_compradores

        errores_email = validar_emails_compradores()
        if errores_email:
            logger.error("=" * 60)
            logger.error("VALIDACIÓN FALLIDA: emails inconsistentes en compradores")
            logger.error("=" * 60)
            for msg in errores_email:
                logger.error(msg)
            report["errores_validacion"] = errores_email
            report["fin"] = datetime.now().isoformat()
            self._guardar_reporte(report)
            return report

        grupos = agrupar_por_comprador(datos)

        # ── 2. Generar PDFs ──────────────────────────────────
        logger.info("=" * 60)
        logger.info("REPORTES: Generando PDFs (%d compradores)", len(grupos))
        logger.info("=" * 60)

        pdf_paths = {}  # clave (email) -> Path del PDF

        for clave, grupo in grupos.items():
            empresa = grupo["empresa"]
            total_est = sum(len(c.get("estudiantes", [])) for c in grupo["cursos"])

            try:
                ruta = generar_pdf(grupo)

                # Verificar que el PDF es válido
                if not ruta.exists():
                    raise RuntimeError(f"PDF no existe tras generación: {ruta}")
                if ruta.stat().st_size == 0:
                    raise RuntimeError(f"PDF vacío: {ruta}")
                if ruta.read_bytes()[:4] != b"%PDF":
                    raise RuntimeError(f"Archivo no es un PDF válido: {ruta}")

                pdf_paths[clave] = ruta
                report["pdfs_generados"].append({
                    "empresa": empresa,
                    "archivo": ruta.name,
                    "cursos": len(grupo["cursos"]),
                    "estudiantes": total_est,
                })
                logger.info(
                    "PDF OK: %s (%d cursos, %d estudiantes)",
                    empresa, len(grupo["cursos"]), total_est,
                )

            except Exception as e:
                logger.error("PDF FALLIDO: %s — %s", empresa, e)
                report["pdfs_fallidos"].append({
                    "empresa": empresa,
                    "error": str(e),
                })

        logger.info(
            "PDFs: %d generados, %d fallidos",
            len(report["pdfs_generados"]),
            len(report["pdfs_fallidos"]),
        )

        # ── 3. Enviar correos (si habilitado) ─────────────────
        if self.send_email:
            logger.info("=" * 60)
            logger.info("REPORTES: Enviando correos%s", " (DRY-RUN)" if self.dry_run else "")
            logger.info("=" * 60)

            self._enviar_correos(grupos, pdf_paths, datos, report)

        # ── 4. Guardar reporte ────────────────────────────────
        report["fin"] = datetime.now().isoformat()
        reporte_path = self._guardar_reporte(report)

        # ── 5. Resumen ───────────────────────────────────────
        logger.info("=" * 60)
        logger.info("RESUMEN REPORTES")
        logger.info("=" * 60)
        logger.info("  Inicio:            %s", report["inicio"])
        logger.info("  Fin:               %s", report["fin"])
        logger.info("  PDFs generados:    %d", len(report["pdfs_generados"]))
        logger.info("  PDFs fallidos:     %d", len(report["pdfs_fallidos"]))
        if self.send_email:
            logger.info("  Correos enviados:  %d", len(report["correos_enviados"]))
            logger.info("  Correos fallidos:  %d", len(report["correos_fallidos"]))
            logger.info("  Sin email:         %d", len(report["correos_sin_email"]))
            logger.info("  Modo dry-run:      %s", self.dry_run)
        logger.info("  Reporte:           %s", reporte_path)
        logger.info("=" * 60)

        return report

    def _enviar_correos(self, grupos, pdf_paths, datos, report):
        """Envía correos para cada comprador con PDF adjunto."""
        import time

        from src.reports.email_sender import (
            enviar_correo,
            generar_cuerpo_correo,
            DELAY_ENTRE_ENVIOS,
        )

        fecha_str = datetime.now().strftime("%d/%m/%Y")
        cc = settings.EMAIL_CC

        for idx, (clave, grupo) in enumerate(grupos.items()):
            empresa = grupo["empresa"]
            nombre = grupo["nombre"]
            email = grupo["email"]

            # Verificar que hay PDF generado
            if clave not in pdf_paths:
                logger.warning("Sin PDF para %s — no se envía correo", empresa)
                continue

            # Verificar email (soporta múltiples separados por coma)
            from src.reports.email_sender import _parsear_emails
            lista_emails = _parsear_emails(email)
            if not lista_emails:
                logger.warning("Sin email para %s — no se envía correo", empresa)
                report["correos_sin_email"].append(empresa)
                continue

            # Verificar datos del comprador
            if not nombre:
                nombre = empresa

            # Preparar resumen
            resumen = []
            for curso in grupo["cursos"]:
                stats = curso.get("estadisticas", {})
                resumen.append({
                    "nombre": curso.get("nombre", ""),
                    "total_estudiantes": stats.get("total_estudiantes", 0),
                    "aprobados": stats.get("aprobados", 0),
                    "en_proceso": stats.get("en_proceso", 0),
                })

            # Generar cuerpo
            cuerpo = generar_cuerpo_correo(nombre, empresa, resumen)
            asunto = f"Reporte de Capacitación - {empresa} - {fecha_str}"

            # Enviar
            resultado = enviar_correo(
                destinatario=email,
                asunto=asunto,
                cuerpo_html=cuerpo,
                adjunto_path=pdf_paths[clave],
                cc=cc,
                dry_run=self.dry_run,
            )

            if resultado["status"] in ("OK", "DRY-RUN"):
                report["correos_enviados"].append({
                    "empresa": empresa,
                    "email": email,
                    "status": resultado["status"],
                })
            else:
                report["correos_fallidos"].append({
                    "empresa": empresa,
                    "email": email,
                    "error": resultado["detalle"],
                })

            # Espera entre envíos
            if idx < len(grupos) - 1:
                time.sleep(DELAY_ENTRE_ENVIOS)

    def _guardar_reporte(self, report):
        """Guarda el reporte de ejecución como JSON."""
        output_dir = settings.OUTPUT_PATH
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        reporte_path = output_dir / f"reports_report_{timestamp}.json"

        with open(reporte_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)

        logger.info("Reporte guardado: %s", reporte_path)
        return reporte_path

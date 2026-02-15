#!/usr/bin/env python3
"""Script para ejecutar actualización completa en segundo plano.

Se ejecuta como proceso independiente, desvinculado del servidor web.
Al finalizar, envía correo de notificación con el resultado.
"""

import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path

# Agregar directorio raíz al path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings
from src.main import run_scraper, run_pipeline
from src.reports.email_sender import enviar_correo

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def main():
    """Ejecuta actualización completa y envía notificación."""
    # Obtener email del usuario que inició (pasado como argumento)
    usuario_email = sys.argv[1] if len(sys.argv) > 1 else settings.EMAIL_CC

    inicio = datetime.now()
    logger.info("=" * 60)
    logger.info("ACTUALIZACIÓN COMPLETA EN SEGUNDO PLANO")
    logger.info("Iniciado por: %s", usuario_email)
    logger.info("Inicio: %s", inicio.strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("=" * 60)

    errores = []
    resultado = {
        "scraper": {"status": "pending", "descargados": 0, "fallidos": 0},
        "pipeline": {"status": "pending", "cursos": 0, "estudiantes": 0},
    }

    # ── Paso 1: Scraper SENCE ──────────────────────────────────
    try:
        logger.info("Paso 1/2: Ejecutando scraper SENCE...")
        report = asyncio.run(run_scraper(headless=True))

        resultado["scraper"]["status"] = "ok"
        resultado["scraper"]["descargados"] = len(report.get("descargados_ok", []))
        resultado["scraper"]["fallidos"] = len(report.get("fallidos", []))

        logger.info(
            "Scraper SENCE completado: %d OK, %d fallidos",
            resultado["scraper"]["descargados"],
            resultado["scraper"]["fallidos"],
        )

        if report.get("errores"):
            errores.extend(report["errores"])

    except Exception as e:
        logger.error("Error en scraper SENCE: %s", e, exc_info=True)
        resultado["scraper"]["status"] = "error"
        errores.append(f"Scraper SENCE: {str(e)}")

    # ── Paso 2: Pipeline completo ──────────────────────────────
    try:
        logger.info("Paso 2/2: Ejecutando pipeline completo...")
        datos_json = run_pipeline()

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
        errores.append(f"Pipeline: {str(e)}")

    # ── Paso 3: Enviar correo de notificación ──────────────────
    fin = datetime.now()
    duracion = (fin - inicio).total_seconds() / 60  # minutos

    logger.info("=" * 60)
    logger.info("Fin: %s", fin.strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("Duración: %.1f minutos", duracion)
    logger.info("=" * 60)

    # Determinar si fue exitoso
    exitoso = (
        resultado["scraper"]["status"] in ["ok", "pending"]
        and resultado["pipeline"]["status"] == "ok"
        and not errores
    )

    # Construir email
    if exitoso:
        asunto = "✅ Actualización completa finalizada exitosamente"
        color = "#16a34a"  # verde
        icono = "✅"
    else:
        asunto = "⚠️ Actualización completa finalizada con errores"
        color = "#dc2626"  # rojo
        icono = "⚠️"

    # Tabla de resultados
    tabla_scraper = f"""
    <tr>
        <td style="padding: 8px; border: 1px solid #ddd;"><strong>Scraper SENCE</strong></td>
        <td style="padding: 8px; border: 1px solid #ddd;">{resultado['scraper']['status'].upper()}</td>
        <td style="padding: 8px; border: 1px solid #ddd;">{resultado['scraper']['descargados']} descargados, {resultado['scraper']['fallidos']} fallidos</td>
    </tr>
    """

    tabla_pipeline = f"""
    <tr>
        <td style="padding: 8px; border: 1px solid #ddd;"><strong>Pipeline</strong></td>
        <td style="padding: 8px; border: 1px solid #ddd;">{resultado['pipeline']['status'].upper()}</td>
        <td style="padding: 8px; border: 1px solid #ddd;">{resultado['pipeline']['cursos']} cursos, {resultado['pipeline']['estudiantes']} estudiantes</td>
    </tr>
    """

    # Tabla de errores (si hay)
    tabla_errores = ""
    if errores:
        filas_errores = "\n".join(
            f'<li style="margin-bottom: 8px; color: #dc2626;">{err}</li>'
            for err in errores
        )
        tabla_errores = f"""
        <div style="background: #fee2e2; padding: 12px; margin: 16px 0; border-left: 4px solid #dc2626;">
            <p style="margin: 0 0 8px 0; font-weight: bold; color: #dc2626;">Errores detectados:</p>
            <ul style="margin: 0; padding-left: 20px;">
                {filas_errores}
            </ul>
        </div>
        """

    mensaje_html = f"""
<html>
<body style="font-family: Arial, sans-serif;">
    <div style="background-color: {color}; color: white; padding: 16px 20px;">
        <h2 style="margin: 0;">{icono} Actualización Completa Finalizada</h2>
    </div>

    <div style="padding: 20px; background: #f9fafb; border: 2px solid {color}; border-top: none;">
        <p><strong>Sistema:</strong> Reportes de Alumnos y SENCE - Tecnipro</p>
        <p><strong>Solicitado por:</strong> {usuario_email}</p>
        <p><strong>Inicio:</strong> {inicio.strftime('%d/%m/%Y %H:%M:%S')}</p>
        <p><strong>Fin:</strong> {fin.strftime('%d/%m/%Y %H:%M:%S')}</p>
        <p><strong>Duración:</strong> {duracion:.1f} minutos</p>

        <div style="background: white; padding: 12px; margin: 16px 0; border-left: 4px solid {color};">
            <p style="margin: 0; font-weight: bold;">Resultados del proceso:</p>
        </div>

        <table style="width: 100%; border-collapse: collapse; border: 1px solid #ddd; background: white; margin: 16px 0;">
            <thead>
                <tr style="background-color: {color}; color: white;">
                    <th style="padding: 8px; border: 1px solid #ddd; text-align: left;">Componente</th>
                    <th style="padding: 8px; border: 1px solid #ddd; text-align: left;">Estado</th>
                    <th style="padding: 8px; border: 1px solid #ddd; text-align: left;">Detalle</th>
                </tr>
            </thead>
            <tbody>
                {tabla_scraper}
                {tabla_pipeline}
            </tbody>
        </table>

        {tabla_errores}

        <div style="background: white; padding: 16px; margin: 20px 0; border: 1px solid #ddd; border-radius: 4px;">
            <p style="font-weight: bold; margin: 0 0 8px 0; color: #333;">📊 Dashboard actualizado</p>
            <p style="margin: 0; font-size: 14px; color: #666;">
                Puede acceder al dashboard para ver los datos actualizados en:<br/>
                <a href="https://reportes.tecnipro.cl" style="color: {color}; text-decoration: none; font-weight: bold;">https://reportes.tecnipro.cl</a>
            </p>
        </div>
    </div>

    <p style="color: #666; font-size: 12px; margin-top: 16px;">
        Este es un mensaje automático del sistema reportes.tecnipro.cl
    </p>
</body>
</html>
"""

    # Enviar correo
    try:
        resultado_email = enviar_correo(
            destinatario=usuario_email,
            asunto=asunto,
            cuerpo_html=mensaje_html,
            cc=settings.EMAIL_CC,
        )

        if resultado_email["status"] == "OK":
            logger.info("Notificación enviada exitosamente a %s", usuario_email)
        else:
            logger.error("Error enviando notificación: %s", resultado_email["detalle"])

    except Exception as e:
        logger.error("Error enviando correo: %s", e, exc_info=True)

    # Retornar código de salida
    sys.exit(0 if exitoso else 1)


if __name__ == "__main__":
    main()

#!/bin/bash
# ============================================================
# Pipeline diario — Versión producción con logging completo
# Ejecutado por systemd timer (tecnipro-daily.timer)
# ============================================================

set -e

APP_DIR="/home/tecnipro/tecnipro-reportes"
LOG_DIR="/var/log/tecnipro"

cd "$APP_DIR"

# Activar entorno virtual
source venv/bin/activate

echo "============================================"
echo "Inicio pipeline: $(date)"
echo "============================================"

# Paso 1: Descargar archivos desde OneDrive/SharePoint
echo "[$(date)] Descargando archivos de OneDrive..."
python3 -c "
from src.ingest.onedrive_client import download_moodle_csvs
download_moodle_csvs()
" 2>&1 || {
    echo "[$(date)] WARN: Error descargando de OneDrive, usando archivos locales"
}

# Paso 2: Scraper SENCE + Pipeline + Reportes
# Envío de correos SOLO los lunes
DAY_OF_WEEK=$(date +%u)  # 1=Lunes, 7=Domingo

if [ "$DAY_OF_WEEK" -eq 1 ]; then
    echo "[$(date)] Ejecutando scraper + pipeline + reportes + EMAIL (LUNES)..."
    python3 -m src.main --scrape --report --email 2>&1
else
    echo "[$(date)] Ejecutando scraper + pipeline + reportes (SIN email - solo lunes)..."
    python3 -m src.main --scrape --report 2>&1
fi

EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo "[$(date)] Pipeline completado exitosamente"

    # Verificar si el scraping de SENCE fue exitoso
    echo "[$(date)] Verificando resultado del scraping SENCE..."
    python3 -c "
import json
from pathlib import Path
from src.reports.email_sender import enviar_correo
from datetime import datetime

# Buscar el reporte de scraper más reciente
output_dir = Path('data/output')
reportes_scraper = sorted(output_dir.glob('scraper_report_*.json'), key=lambda p: p.stat().st_mtime, reverse=True)

if not reportes_scraper:
    print('WARN: No se encontró reporte de scraper')
    exit(1)

# Leer último reporte de scraper
with open(reportes_scraper[0], 'r', encoding='utf-8') as f:
    reporte = json.load(f)

descargados = len(reporte.get('descargados_ok', []))
errores = len(reporte.get('errores', []))
fallidos = len(reporte.get('fallidos', []))
solicitados = len(reporte.get('ids_solicitados', []))

# Leer reporte de PDFs si existe
pdfs_generados = []
reportes_pdf = sorted(output_dir.glob('reports_report_*.json'), key=lambda p: p.stat().st_mtime, reverse=True)
if reportes_pdf:
    try:
        with open(reportes_pdf[0], 'r', encoding='utf-8') as f:
            reporte_pdf = json.load(f)
            pdfs_generados = reporte_pdf.get('pdfs_generados', [])
    except Exception:
        pass

# Determinar si el scraping fue exitoso
scraping_exitoso = descargados > 0 and descargados == solicitados

if scraping_exitoso:
    # EMAIL DE ÉXITO - Preparar tabla de PDFs generados
    pdfs_count = len(pdfs_generados)
    tabla_pdfs = ''
    if pdfs_generados:
        filas_tabla = ''
        for pdf in pdfs_generados:
            filas_tabla += f'''
            <tr>
                <td style=\"padding: 8px; border: 1px solid #ddd;\">{pdf['empresa']}</td>
                <td style=\"padding: 8px; border: 1px solid #ddd; font-family: monospace; font-size: 12px;\">{pdf['archivo']}</td>
                <td style=\"padding: 8px; border: 1px solid #ddd; text-align: center;\">{pdf['cursos']}</td>
                <td style=\"padding: 8px; border: 1px solid #ddd; text-align: center;\">{pdf['estudiantes']}</td>
            </tr>'''

        tabla_pdfs = f'''
        <div style=\"margin-top: 16px;\">
            <p style=\"font-weight: bold; margin-bottom: 8px;\">Reportes PDF generados ({pdfs_count}):</p>
            <table style=\"width: 100%; border-collapse: collapse; border: 1px solid #ddd; background: white;\">
                <thead>
                    <tr style=\"background-color: #16a34a; color: white;\">
                        <th style=\"padding: 8px; border: 1px solid #ddd; text-align: left;\">Empresa</th>
                        <th style=\"padding: 8px; border: 1px solid #ddd; text-align: left;\">Archivo</th>
                        <th style=\"padding: 8px; border: 1px solid #ddd; text-align: center;\">Cursos</th>
                        <th style=\"padding: 8px; border: 1px solid #ddd; text-align: center;\">Estudiantes</th>
                    </tr>
                </thead>
                <tbody>
                    {filas_tabla}
                </tbody>
            </table>
        </div>'''

    asunto = '✅ OK: Reportes Tecnipro actualizados correctamente'
    mensaje = f'''
<html>
<body style=\"font-family: Arial, sans-serif;\">
    <div style=\"background-color: #16a34a; color: white; padding: 16px 20px;\">
        <h2 style=\"margin: 0;\">✅ Reportes Actualizados Correctamente</h2>
    </div>

    <div style=\"padding: 20px; background: #f0fdf4; border: 2px solid #16a34a; border-top: none;\">
        <p><strong>Sistema:</strong> Reportes de Alumnos y SENCE - Tecnipro</p>
        <p><strong>Fecha y hora:</strong> {datetime.now().strftime('%d/%m/%Y %H:%M:%S')} (Chile)</p>
        <p><strong>Estado:</strong> ✅ Todo OK</p>

        <div style=\"background: white; padding: 12px; margin: 16px 0; border-left: 4px solid #16a34a;\">
            <p style=\"margin: 0; font-weight: bold;\">Resumen de la ejecución:</p>
        </div>

        <ul>
            <li>Archivos Moodle descargados desde OneDrive: ✅</li>
            <li>Datos SENCE actualizados: <strong>{descargados} de {solicitados} cursos</strong> ✅</li>
            <li>Datos de alumnos procesados: ✅</li>
        </ul>

        {tabla_pdfs}

        <p style=\"color: #16a34a; font-weight: bold; margin-top: 16px;\">
            ✓ Todos los procesos completados exitosamente
        </p>
    </div>

    <p style=\"color: #666; font-size: 12px; margin-top: 16px;\">
        Este es un mensaje automático del sistema reportes.tecnipro.cl
    </p>
</body>
</html>
'''
else:
    # EMAIL DE ALERTA - SCRAPING FALLÓ
    asunto = '⚠️ Reportes Tecnipro - ALERTA: Datos SENCE No Actualizados'
    mensaje = f'''
<html>
<body style=\"font-family: Arial, sans-serif;\">
    <div style=\"background-color: #dc3545; color: white; padding: 16px 20px;\">
        <h2 style=\"margin: 0;\">⚠️ ALERTA: Datos SENCE No Actualizados</h2>
    </div>

    <div style=\"padding: 20px; background: #fff3cd; border: 2px solid #ffc107;\">
        <p><strong>Sistema:</strong> Reportes de Alumnos y SENCE - Tecnipro</p>
        <p><strong>Fecha y hora:</strong> {datetime.now().strftime('%d/%m/%Y %H:%M:%S')} (Chile)</p>
        <p><strong>Estado:</strong> Pipeline ejecutado, pero el scraping de SENCE FALLÓ</p>

        <div style=\"background: white; padding: 12px; margin: 16px 0; border-left: 4px solid #dc3545;\">
            <p style=\"margin: 0; color: #dc3545; font-weight: bold;\">
                ⚠️ Los datos de SENCE NO se actualizaron. Los reportes contienen información desactualizada.
            </p>
        </div>

        <p><strong>Resumen del scraping:</strong></p>
        <ul>
            <li>Cursos solicitados: <strong>{solicitados}</strong></li>
            <li>Descargados exitosamente: <strong>{descargados}</strong></li>
            <li>Fallidos: <strong>{fallidos}</strong></li>
            <li>Errores: <strong>{errores}</strong></li>
        </ul>

        <p><strong>Acciones completadas:</strong></p>
        <ul>
            <li>Descarga de archivos Moodle desde OneDrive</li>
            <li>❌ Scraping de datos SENCE: <strong>FALLÓ</strong></li>
            <li>Procesamiento de datos de alumnos (con datos SENCE antiguos)</li>
            <li>Generación de reportes PDF (con datos SENCE antiguos)</li>
        </ul>

        <div style=\"background: white; padding: 12px; margin: 16px 0;\">
            <p style=\"margin: 0;\"><strong>Acción requerida:</strong> Verificar logs del servidor y volver a ejecutar el proceso manualmente.</p>
        </div>
    </div>

    <p style=\"color: #666; font-size: 12px; margin-top: 16px;\">
        Este es un mensaje automático del sistema reportes.tecnipro.cl
    </p>
</body>
</html>
'''

resultado = enviar_correo(
    destinatario='jortizleiva@duocapital.cl',
    asunto=asunto,
    cuerpo_html=mensaje
)

if resultado['status'] == 'OK':
    tipo = 'ÉXITO' if scraping_exitoso else 'ALERTA'
    print(f'Notificación enviada: {tipo}')
else:
    print(f'Error enviando notificación: {resultado[\"detalle\"]}')

exit(0 if scraping_exitoso else 1)
" 2>&1 || echo "[$(date)] WARN: No se pudo enviar notificación por correo"
else
    echo "[$(date)] Pipeline falló con código: $EXIT_CODE" >&2
fi

echo "============================================"
echo "Fin pipeline: $(date) (exit: $EXIT_CODE)"
echo "============================================"

# Limpiar logs antiguos (más de 30 días)
find "$LOG_DIR" -name "*.log" -mtime +30 -delete 2>/dev/null || true

exit $EXIT_CODE

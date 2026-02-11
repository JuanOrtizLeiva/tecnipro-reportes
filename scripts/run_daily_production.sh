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
reportes = sorted(output_dir.glob('scraper_report_*.json'), key=lambda p: p.stat().st_mtime, reverse=True)

if not reportes:
    print('WARN: No se encontró reporte de scraper')
    exit(1)

# Leer último reporte
with open(reportes[0], 'r', encoding='utf-8') as f:
    reporte = json.load(f)

descargados = len(reporte.get('descargados_ok', []))
errores = len(reporte.get('errores', []))
fallidos = len(reporte.get('fallidos', []))
solicitados = len(reporte.get('ids_solicitados', []))

# Determinar si el scraping fue exitoso
scraping_exitoso = descargados > 0 and descargados == solicitados

if scraping_exitoso:
    # EMAIL DE ÉXITO
    asunto = 'Reportes Tecnipro - Proceso Ejecutado Correctamente'
    mensaje = f'''
<html>
<body style=\"font-family: Arial, sans-serif;\">
    <h2 style=\"color: #16a34a;\">✅ Proceso de Reportes Ejecutado Exitosamente</h2>
    <p><strong>Sistema:</strong> Reportes de Alumnos y SENCE - Tecnipro</p>
    <p><strong>Fecha y hora:</strong> {datetime.now().strftime('%d/%m/%Y %H:%M:%S')} (Chile)</p>
    <p><strong>Estado:</strong> Completado sin errores</p>
    <p><strong>Acciones realizadas:</strong></p>
    <ul>
        <li>Descarga de archivos Moodle desde OneDrive</li>
        <li>Scraping de datos SENCE: <strong>{descargados}/{solicitados} cursos actualizados</strong></li>
        <li>Procesamiento de datos de alumnos</li>
        <li>Generación de reportes PDF</li>
    </ul>
    <hr>
    <p style=\"color: #666; font-size: 12px;\">
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
    print(f'Notificación enviada: {'ÉXITO' if scraping_exitoso else 'ALERTA'}')
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

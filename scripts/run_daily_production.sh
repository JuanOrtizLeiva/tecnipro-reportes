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

    # Enviar notificación de éxito por correo
    echo "[$(date)] Enviando notificación de éxito..."
    python3 -c "
from src.reports.email_sender import enviar_correo
from datetime import datetime

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
        <li>Scraping de datos SENCE</li>
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

resultado = enviar_correo(
    destinatario='jortizleiva@duocapital.cl',
    asunto=asunto,
    cuerpo_html=mensaje
)

if resultado['status'] == 'OK':
    print('Notificación enviada exitosamente')
else:
    print(f'Error enviando notificación: {resultado[\"detalle\"]}')
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

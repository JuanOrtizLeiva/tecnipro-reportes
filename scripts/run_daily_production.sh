#!/bin/bash
# ============================================================
# Pipeline diario — Versión producción con logging completo
# Ejecutado por systemd timer (tecnipro-daily.timer)
# ============================================================

set -e

APP_DIR="/home/ops/tecnipro-reportes"
LOG_DIR="/var/log/tecnipro"

cd "$APP_DIR"

# Activar entorno virtual
source venv/bin/activate

echo "============================================"
echo "Inicio pipeline: $(date)"
echo "============================================"

# Paso 0a: WATCHDOG — verificar staleness del último snapshot antes de ejecutar
echo "[$(date)] Watchdog: revisando último SnapshotDiario..."
WATCHDOG_WARN=$(python3 -c "
from datetime import date, timedelta
try:
    from src.database import init_db, get_session
    from src.models import SnapshotDiario
    from sqlalchemy import func
    if not init_db():
        print('')
    else:
        s = get_session()
        try:
            ult = s.query(func.max(SnapshotDiario.fecha)).scalar()
            if ult is None:
                print('Sin snapshots previos en PostgreSQL')
            elif ult < date.today() - timedelta(days=1):
                dias = (date.today() - ult).days
                print(f'Ultimo snapshot diario es del {ult} ({dias} dias atras)')
        finally:
            s.close()
except Exception as e:
    print(f'Watchdog no disponible: {e}')
" 2>/dev/null || true)

if [ -n "$WATCHDOG_WARN" ]; then
    echo "[$(date)] WATCHDOG WARN: $WATCHDOG_WARN"
fi
export WATCHDOG_WARN

# Paso 0: RESPALDO de archivos existentes
FECHA=$(date +%Y-%m-%d)
BACKUP_DIR="$APP_DIR/data/backup/$FECHA"

echo "[$(date)] Creando respaldo de archivos existentes..."
mkdir -p "$BACKUP_DIR/sence"

# Respaldar Greporte y Dreporte si existen
if [ -f "$APP_DIR/data/Greporte.csv" ]; then
    mv "$APP_DIR/data/Greporte.csv" "$BACKUP_DIR/"
    echo "[$(date)] Greporte.csv respaldado"
fi

if [ -f "$APP_DIR/data/Dreporte.csv" ]; then
    mv "$APP_DIR/data/Dreporte.csv" "$BACKUP_DIR/"
    echo "[$(date)] Dreporte.csv respaldado"
fi

# Respaldar archivos SENCE
ARCHIVOS_SENCE=$(find "$APP_DIR/data/sence" -maxdepth 1 -name "*.csv" 2>/dev/null | wc -l)
if [ "$ARCHIVOS_SENCE" -gt 0 ]; then
    mv "$APP_DIR/data/sence"/*.csv "$BACKUP_DIR/sence/" 2>/dev/null || true
    echo "[$(date)] $ARCHIVOS_SENCE archivos SENCE respaldados"
else
    echo "[$(date)] Sin archivos SENCE para respaldar"
fi

echo "[$(date)] Respaldo completado en: $BACKUP_DIR"

# Paso 1: Descargar archivos Moodle (solo si DATA_SOURCE=csv)
DATA_SOURCE=$(python3 -c "from config import settings; print(settings.DATA_SOURCE)" 2>/dev/null || echo "csv")

if [ "$DATA_SOURCE" = "api" ]; then
    echo "[$(date)] DATA_SOURCE=api → datos se obtienen directo de Moodle API (paso de descarga omitido)"
    FUENTE_DATOS="API Moodle"
else
    echo "[$(date)] DATA_SOURCE=csv → descargando CSVs..."
    FUENTE_DATOS="CSV (OneDrive)"
    python3 -c "
from src.ingest.email_reader import descargar_adjuntos_moodle
try:
    resultado = descargar_adjuntos_moodle()
    if resultado['status'] == 'OK':
        print(f'Email OK: {len(resultado[\"archivos_descargados\"])} archivos descargados')
    else:
        print(f'Email PARCIAL: {resultado.get(\"archivos_faltantes\", [])}')
        exit(1)
except Exception as e:
    print(f'Email FALLÓ: {e}')
    exit(1)
" 2>&1 || {
        echo "[$(date)] WARN: Email falló, intentando OneDrive como backup..."
        python3 -c "
from src.ingest.onedrive_client import download_moodle_csvs
download_moodle_csvs()
" 2>&1 || {
            echo "[$(date)] ERROR: OneDrive también falló, usando archivos locales"
        }
    }
fi

# Paso 2: Scraper SENCE + Pipeline + Reportes
# Desactivar set -e para capturar errores sin matar el script
set +e

# Paso 1.5: AUTO-REPARACIÓN del navegador Playwright
# Si Playwright se actualiza (requirements: playwright>=1.40), el build del
# navegador cambia y el binario anterior queda inválido → el scraper no puede
# lanzar el navegador y SENCE descarga 0 filas (incidente 13-jul-2026).
# El test de launch es instantáneo si el navegador está OK; solo reinstala
# cuando falta. `playwright install chromium` instala chromium + headless shell.
echo "[$(date)] Verificando navegador Playwright para scraper SENCE..."
if ! python3 -c "
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(headless=True); b.close()
" 2>/dev/null; then
    echo "[$(date)] WARN: navegador Playwright no disponible, reinstalando (playwright install chromium)..."
    python3 -m playwright install chromium 2>&1 || echo "[$(date)] ERROR: 'playwright install chromium' falló"
else
    echo "[$(date)] Navegador Playwright OK"
fi

# Envío de correos el primer día hábil de la semana (posterga si feriado)
echo "[$(date)] Verificando si hoy toca envío semanal (feriados Chile)..."
python3 scripts/es_dia_envio_semanal.py 2>&1
ES_DIA_ENVIO=$?

if [ "$ES_DIA_ENVIO" -eq 0 ]; then
    echo "[$(date)] Ejecutando scraper + pipeline + reportes PDF + EMAIL (primer día hábil de la semana)..."
    python3 -m src.main --scrape --report --email 2>&1
else
    echo "[$(date)] Ejecutando scraper + pipeline (SIN reportes PDF - no es día de envío semanal)..."
    python3 -m src.main --scrape 2>&1
fi

EXIT_CODE=$?

# Reactivar set -e
set -e

if [ $EXIT_CODE -eq 0 ]; then
    echo "[$(date)] Pipeline completado exitosamente"

    # Resumen diario consolidado: UN SOLO correo a jortizleiva + ygonzalez con
    # estado del sistema + anomalías SENCE + DJ pendientes, y Excel adjunto (una
    # hoja por tema). Reemplaza la antigua notificación de validación y el aviso
    # SENCE por-curso; el recordatorio DJ también se consolida aquí.
    echo "[$(date)] Generando y enviando resumen diario consolidado..."
    python3 scripts/resumen_diario.py 2>&1 \
        || echo "[$(date)] WARN: resumen diario falló (no crítico)"
else
    echo "[$(date)] Pipeline falló con código: $EXIT_CODE" >&2
    echo "[$(date)] Enviando alerta de error por correo..."
    python3 -c "
from src.reports.email_sender import enviar_correo
from datetime import datetime

asunto = '🔴 CRÍTICO: Pipeline Tecnipro falló completamente'
mensaje = '''
<html>
<body style=\"font-family: Arial, sans-serif;\">
    <div style=\"background-color: #dc3545; color: white; padding: 16px 20px;\">
        <h2 style=\"margin: 0;\">🔴 PIPELINE FALLÓ COMPLETAMENTE</h2>
    </div>

    <div style=\"padding: 20px; background: #f8d7da; border: 2px solid #dc3545; border-top: none;\">
        <p><strong>Sistema:</strong> Reportes de Alumnos y SENCE - Tecnipro</p>
        <p><strong>Fecha y hora:</strong> ''' + datetime.now().strftime('%d/%m/%Y %H:%M:%S') + ''' (Chile)</p>
        <p><strong>Estado:</strong> 🔴 Error crítico — el pipeline no pudo ejecutarse</p>
        <p><strong>Código de salida:</strong> $EXIT_CODE</p>

        <div style=\"background: white; padding: 12px; margin: 16px 0; border-left: 4px solid #dc3545;\">
            <p style=\"margin: 0; color: #dc3545; font-weight: bold;\">
                El pipeline no pudo completarse. No se generaron reportes ni se descargaron datos SENCE.
            </p>
        </div>

        <p><strong>Posibles causas:</strong></p>
        <ul>
            <li>Proxy Decodo sin tráfico disponible o apagado</li>
            <li>Moodle API inaccesible</li>
            <li>Clave Única bloqueando conexión</li>
            <li>Error interno del pipeline</li>
        </ul>

        <div style=\"background: white; padding: 12px; margin: 16px 0;\">
            <p style=\"margin: 0;\"><strong>Acción requerida:</strong> Revisar logs en el servidor:</p>
            <pre style=\"background: #f5f5f5; padding: 8px; margin: 8px 0; font-size: 12px;\">journalctl -u tecnipro-daily.service --no-pager | tail -50
tail -50 /var/log/tecnipro/daily.log</pre>
        </div>
    </div>

    <p style=\"color: #666; font-size: 12px; margin-top: 16px;\">
        Este es un mensaje automático del sistema reportes.tecnipro.cl
    </p>
</body>
</html>
'''

resultado = enviar_correo(
    destinatario='jortizleiva@duocapital.cl,ygonzalez@duocapital.cl',
    asunto=asunto,
    cuerpo_html=mensaje
)

if resultado['status'] == 'OK':
    print('Alerta de error enviada correctamente')
else:
    print(f'Error enviando alerta: {resultado[\"detalle\"]}')
" 2>&1 || echo "[$(date)] WARN: No se pudo enviar alerta de error por correo"
fi

echo "============================================"
echo "Fin pipeline: $(date) (exit: $EXIT_CODE)"
echo "============================================"

# Limpiar logs antiguos (más de 30 días)
find "$LOG_DIR" -name "*.log" -mtime +30 -delete 2>/dev/null || true

exit $EXIT_CODE

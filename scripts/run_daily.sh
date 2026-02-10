#!/usr/bin/env bash
# Script para ejecución diaria via cron
# Ejecuta scraper SENCE + pipeline de procesamiento
# Uso: crontab -e → 0 8 * * * /ruta/a/tecnipro-reportes/scripts/run_daily.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Activar virtualenv si existe
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
fi

# Instalar browsers de Playwright si es primera vez
python -m playwright install chromium --with-deps 2>/dev/null || true

# Ejecutar scraper + pipeline
echo "[$(date)] Iniciando ejecución diaria..."
python -m src.main --scrape 2>&1 | tee -a "$PROJECT_DIR/data/output/daily_log.txt"

echo "[$(date)] Ejecución completada."

#!/usr/bin/env bash
# Script para ejecución diaria via cron
# Uso: crontab -e → 0 8 * * * /ruta/a/tecnipro-reportes/scripts/run_daily.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Activar virtualenv si existe
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
fi

python -m src.main 2>&1 | tee -a "$PROJECT_DIR/data/output/run.log"

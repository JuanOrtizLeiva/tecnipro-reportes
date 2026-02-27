#!/bin/bash
# ============================================================
# DEPLOY — Actualizar código y reiniciar servicios
# Ejecutar como root: bash deploy/deploy.sh
# ============================================================

set -e

APP_DIR="/root/tecnipro-reportes"
cd "$APP_DIR"

echo "[$(date)] Actualizando código desde GitHub..."
git pull origin master

echo "[$(date)] Actualizando dependencias..."
./venv/bin/pip install -r requirements.txt --quiet

echo "[$(date)] Reiniciando servicio web..."
systemctl restart tecnipro-web

echo "[$(date)] Verificando estado..."
sleep 3
systemctl status tecnipro-web --no-pager

echo ""
# Smoke test
HTTP=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:5001/api/health)
if [ "$HTTP" = "200" ]; then
    echo "✓ Salud OK — /api/health → 200"
else
    echo "✗ ALERTA — /api/health devolvió $HTTP"
    exit 1
fi

echo ""
echo "Deploy completado: $(date)"

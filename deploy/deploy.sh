#!/bin/bash
# ============================================================
# DEPLOY — Actualizar código y reiniciar servicios
# Ejecutar como root: bash deploy/deploy.sh
# ============================================================

set -e

APP_DIR="/home/tecnipro/tecnipro-reportes"
cd "$APP_DIR"

echo "[$(date)] Actualizando código desde GitHub..."
sudo -u tecnipro git pull origin master

echo "[$(date)] Actualizando dependencias..."
sudo -u tecnipro ./venv/bin/pip install -r requirements.txt --quiet

echo "[$(date)] Reiniciando servicio web..."
systemctl restart tecnipro-web

echo "[$(date)] Verificando estado..."
sleep 2
systemctl status tecnipro-web --no-pager

echo ""
echo "Deploy completado: $(date)"

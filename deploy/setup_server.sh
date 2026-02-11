#!/bin/bash
# ============================================================
# SETUP INICIAL — Servidor DigitalOcean para Tecnipro Reportes
# Ejecutar como root: bash setup_server.sh
# ============================================================

set -e

echo "============================================"
echo "Instalando dependencias del sistema..."
echo "============================================"

apt update && apt upgrade -y

# Python 3.12+ y herramientas
apt install -y python3 python3-pip python3-venv python3-dev

# Dependencias para Playwright (Chromium headless)
apt install -y libnss3 libatk-bridge2.0-0 libdrm2 libxkbcommon0 \
    libgbm1 libpango-1.0-0 libcairo2 libasound2t64 libxshmfence1 \
    libx11-xcb1 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    fonts-liberation fonts-noto-color-emoji

# Dependencias para fpdf2
apt install -y libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 \
    libffi-dev shared-mime-info

# Nginx + Git
apt install -y nginx git

# Firewall
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

echo "============================================"
echo "Creando usuario de aplicación..."
echo "============================================"

useradd -m -s /bin/bash tecnipro || true
mkdir -p /home/tecnipro
chown tecnipro:tecnipro /home/tecnipro

echo "============================================"
echo "Clonando repositorio..."
echo "============================================"

cd /home/tecnipro
sudo -u tecnipro git clone https://github.com/JuanOrtizLeiva/tecnipro-reportes.git || true
cd tecnipro-reportes

echo "============================================"
echo "Configurando entorno virtual Python..."
echo "============================================"

sudo -u tecnipro python3 -m venv venv
sudo -u tecnipro ./venv/bin/pip install --upgrade pip
sudo -u tecnipro ./venv/bin/pip install -r requirements.txt

# Playwright: instalar Chromium
sudo -u tecnipro ./venv/bin/playwright install chromium
./venv/bin/playwright install-deps chromium

echo "============================================"
echo "Creando directorios..."
echo "============================================"

sudo -u tecnipro mkdir -p data/sence
sudo -u tecnipro mkdir -p data/config
sudo -u tecnipro mkdir -p data/output/reportes
sudo -u tecnipro mkdir -p data/output/screenshots
mkdir -p /var/log/tecnipro
chown tecnipro:tecnipro /var/log/tecnipro

echo "============================================"
echo "Instalando servicios systemd..."
echo "============================================"

cp deploy/tecnipro-web.service /etc/systemd/system/
cp deploy/tecnipro-daily.service /etc/systemd/system/
cp deploy/tecnipro-daily.timer /etc/systemd/system/

# Nginx
cp deploy/nginx.conf /etc/nginx/sites-available/tecnipro
ln -sf /etc/nginx/sites-available/tecnipro /etc/nginx/sites-enabled/tecnipro
rm -f /etc/nginx/sites-enabled/default

systemctl daemon-reload

echo "============================================"
echo " SETUP COMPLETO"
echo "============================================"
echo ""
echo "PASOS MANUALES RESTANTES:"
echo "1. Copiar .env:  cp deploy/.env.example .env"
echo "2. Editar .env:  nano .env  (agregar credenciales reales)"
echo "3. Copiar compradores: scp compradores_tecnipro.xlsx a data/config/"
echo "4. Copiar CSVs Moodle: scp Greporte.csv y Dreporte.csv a data/"
echo "5. Habilitar servicios:"
echo "   systemctl enable --now tecnipro-web"
echo "   systemctl enable --now tecnipro-daily.timer"
echo "6. Reiniciar Nginx:  systemctl restart nginx"
echo "7. Verificar:  systemctl status tecnipro-web"
echo ""

"""Configuración centralizada — lee variables desde .env."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Raíz del proyecto: dos niveles arriba de este archivo (config/settings.py)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Cargar .env desde la raíz del proyecto
load_dotenv(PROJECT_ROOT / ".env")

# ── Rutas ──────────────────────────────────────────────────
DATA_INPUT_PATH = Path(os.getenv("DATA_INPUT_PATH", "./data"))
SENCE_CSV_PATH = Path(os.getenv("SENCE_CSV_PATH", "./data/sence"))
SENCE_METADATOS_PATH = Path(os.getenv("SENCE_METADATOS_PATH", "./data/sence/metadatos_sence.json"))
COMPRADORES_PATH = Path(os.getenv("COMPRADORES_PATH", "./data/config/compradores_tecnipro.xlsx"))
OUTPUT_PATH = Path(os.getenv("OUTPUT_PATH", "./data/output"))
SQLITE_PATH = Path(os.getenv("SQLITE_PATH", "./data/output/historico.db"))

# Resolver rutas relativas respecto a la raíz del proyecto
if not DATA_INPUT_PATH.is_absolute():
    DATA_INPUT_PATH = PROJECT_ROOT / DATA_INPUT_PATH
if not SENCE_CSV_PATH.is_absolute():
    SENCE_CSV_PATH = PROJECT_ROOT / SENCE_CSV_PATH
if not COMPRADORES_PATH.is_absolute():
    COMPRADORES_PATH = PROJECT_ROOT / COMPRADORES_PATH
if not OUTPUT_PATH.is_absolute():
    OUTPUT_PATH = PROJECT_ROOT / OUTPUT_PATH
if not SQLITE_PATH.is_absolute():
    SQLITE_PATH = PROJECT_ROOT / SQLITE_PATH
if not SENCE_METADATOS_PATH.is_absolute():
    SENCE_METADATOS_PATH = PROJECT_ROOT / SENCE_METADATOS_PATH

# ── Scraper SENCE (Fase 2) ─────────────────────────────────
CLAVE_UNICA_RUT = os.getenv("CLAVE_UNICA_RUT", "")
CLAVE_UNICA_PASSWORD = os.getenv("CLAVE_UNICA_PASSWORD", "")
SCRAPER_HEADLESS = os.getenv("SCRAPER_HEADLESS", "true").lower() == "true"
SCRAPER_TIMEOUT = int(os.getenv("SCRAPER_TIMEOUT", "90000"))  # 90s (SENCE es muy lento)
PROXY_URL = os.getenv("PROXY_URL", None)  # Proxy residencial (opcional)
SCREENSHOTS_PATH = OUTPUT_PATH / "screenshots"

# ── Reportes PDF y Correo (Fase 3) ────────────────────────
REPORTS_PATH = OUTPUT_PATH / "reportes"
JSON_DATOS_PATH = OUTPUT_PATH / "datos_procesados.json"

# Azure AD — para envío de correo vía Microsoft Graph
AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID", "")
AZURE_TENANT_ID = os.getenv("AZURE_TENANT_ID", "")
AZURE_CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET", "")

# Correo
EMAIL_REMITENTE = os.getenv("EMAIL_REMITENTE", "jortizleiva@duocapital.cl")
EMAIL_CC = os.getenv("EMAIL_CC", "ygonzalez@duocapital.cl")
EMAIL_BCC = os.getenv("EMAIL_BCC", "")

# ── Email IMAP (Fase 5.1 - Email directo) ────────────────
EMAIL_MOODLE_USER = os.getenv("EMAIL_MOODLE_USER", "")
EMAIL_MOODLE_PASSWORD = os.getenv("EMAIL_MOODLE_PASSWORD", "")
EMAIL_MOODLE_FROM = os.getenv("EMAIL_MOODLE_FROM", "noreply@virtual.institutotecnipro.cl")
IMAP_SERVER = os.getenv("IMAP_SERVER", "imap.gmail.com")

# ── OneDrive / SharePoint (Fase 5 - Backup) ───────────────
ONEDRIVE_SITE_ID = os.getenv("ONEDRIVE_SITE_ID", "")
ONEDRIVE_MOODLE_FOLDER = os.getenv(
    "ONEDRIVE_MOODLE_FOLDER",
    "Instituto de Capacitacion Tecnipro/Cursos/Cursos en Proceso/"
    "Control Cursos Abiertos/Datos Moodle para control de cursos",
)
ONEDRIVE_COMPRADORES_FOLDER = os.getenv(
    "ONEDRIVE_COMPRADORES_FOLDER",
    "Instituto de Capacitacion Tecnipro/Cursos/Cursos en Proceso/"
    "Control Cursos Abiertos/Reporteria",
)

# ── Autenticación (Fase 4) ────────────────────────────────
SECRET_KEY = os.getenv("SECRET_KEY", "")
if not SECRET_KEY:
    import secrets as _secrets
    SECRET_KEY = _secrets.token_hex(32)
    import logging as _logging
    _logging.getLogger(__name__).warning(
        "SECRET_KEY no configurada — usando clave aleatoria temporal"
    )
SESSION_LIFETIME_HOURS = int(os.getenv("SESSION_LIFETIME_HOURS", "24"))
AUTH_SECRET_KEY = os.getenv("AUTH_SECRET_KEY", "")
if not AUTH_SECRET_KEY:
    import logging as _auth_log
    _auth_log.getLogger(__name__).error(
        "AUTH_SECRET_KEY no configurada — login centralizado no funcionará"
    )
SUPERADMIN_EMAILS = [
    e.strip().lower() for e in
    os.getenv("SUPERADMIN_EMAILS", "ygonzalez@duocapital.cl,jortizleiva@duocapital.cl").split(",")
    if e.strip()
]
USUARIOS_PATH = Path(os.getenv(
    "USUARIOS_PATH", "./data/config/usuarios.json"
))
if not USUARIOS_PATH.is_absolute():
    USUARIOS_PATH = PROJECT_ROOT / USUARIOS_PATH

# ── Dashboard Web (Fase 3.5) ──────────────────────────────
WEB_PORT = int(os.getenv("WEB_PORT", "5000"))
WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0")
TEMPLATES_PATH = PROJECT_ROOT / "templates"

# ── Catálogo de Cursos Aprobados ──────────────────────────
# Fuente de verdad: el MANIFEST.json del repo de cursos (mantenido por el
# flujo de aprobación) y las carpetas del aula con los HTML de cada clase.
# La sección /cursos-aprobados los parsea en vivo (cacheado por mtime).
CURSOS_APROBADOS_MANIFEST = Path(os.getenv(
    "CURSOS_APROBADOS_MANIFEST", "/home/ops/cursos/aprobados/MANIFEST.json"
))
# Raíz del repo del sitio (las rutas "aula/<Curso>" del MANIFEST cuelgan de aquí)
CURSOS_APROBADOS_AULA_ROOT = Path(os.getenv(
    "CURSOS_APROBADOS_AULA_ROOT", "/home/ops/cursos/aula"
))

# ── Moodle API (Fase 6) ───────────────────────────────────
MOODLE_URL = os.getenv("MOODLE_URL", "")
MOODLE_TOKEN = os.getenv("MOODLE_TOKEN", "")
MOODLE_TIMEOUT = int(os.getenv("MOODLE_TIMEOUT", "30"))
MOODLE_CATEGORY_IDS = [int(x.strip()) for x in os.getenv(
    "MOODLE_CATEGORY_IDS", "3,6,10,11,14,16,17,18,19,20,24,27,28,29"
).split(",")]

# Flag para elegir fuente de datos: "csv" o "api"
DATA_SOURCE = os.getenv("DATA_SOURCE", "csv").lower()


SII_CERT_PATH = os.getenv("SII_CERT_PATH", "/etc/ssl/private/tecnipro.pfx")
SII_CERT_PASSWORD = os.getenv("SII_CERT_PASSWORD", "")
SII_RUT_EMPRESA = os.getenv("SII_RUT_EMPRESA", "75620735-K")
SII_AMBIENTE = os.getenv("SII_AMBIENTE", "produccion")

# Año desde el cual se gestiona cobranza activa (facturas anteriores = solo histórico)
ANIO_CORTE_GESTION = int(os.getenv("ANIO_CORTE_GESTION", "2026"))

# ── EvalPro ───────────────────────────────────────────────
EVALPRO_ADMIN_EMAIL = os.getenv("EVALPRO_ADMIN_EMAIL", "jortizleiva@duocapital.cl")
EVALPRO_ADMIN_PASSWORD = os.getenv("EVALPRO_ADMIN_PASSWORD", "")

# ── Certificados de participación ──────────────────────────
CERTIFICADOS_PATH = PROJECT_ROOT / "data" / "certificados"
CERT_DB_PATH = CERTIFICADOS_PATH / "registro.db"
CERT_PLANTILLA_PATH = CERTIFICADOS_PATH / "plantilla" / "plantilla_certificado.docx"
CERT_EMITIDOS_PATH = CERTIFICADOS_PATH / "emitidos"
CERT_ZIPS_PATH = CERTIFICADOS_PATH / "zips"
# URL pública de validación (el QR del certificado apunta aquí + ?c=CODIGO)
CERT_URL_VALIDACION = os.getenv("CERT_URL_VALIDACION", "https://www.tecnipro.cl/validar/")
# Remitente de los correos de certificados (coordinadora académica)
CERT_REMITENTE = os.getenv("CERT_REMITENTE", "ygonzalez@duocapital.cl")
# Copia de resguardo de cada emisión
CERT_COPIA = os.getenv("CERT_COPIA", "ygonzalez@duocapital.cl")

# ── PostgreSQL (migración desde JSON/SQLite) ────────────────
REPORTES_DATABASE_URL = os.getenv("REPORTES_DATABASE_URL", "")
USE_PG = os.getenv("USE_PG", "false").lower() == "true"

# ── Logging ────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

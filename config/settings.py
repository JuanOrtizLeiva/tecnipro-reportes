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

# ── Logging ────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

"""Lee compradores desde JSON o Excel (fallback)."""

import json
import logging
from pathlib import Path

import pandas as pd

from config import settings

logger = logging.getLogger(__name__)

# Mapeo esperado de columnas del Excel → nombres internos
_COL_MAP = {
    "id curso moodle": "id_curso_moodle",
    "id sence": "id_sence_comprador",
    "nombre curso": "nombre_curso_comprador",
    "comprador (nombre)": "comprador_nombre",
    "comprador nombre": "comprador_nombre",
    "empresa": "empresa",
    "email comprador": "email_comprador",
}


def _leer_desde_json():
    """Lee coordinadores (usuarios con rol=comprador) desde usuarios.json.

    Returns
    -------
    pd.DataFrame | None
        DataFrame con coordinadores, o None si no existe o está vacío
    """
    json_path = settings.USUARIOS_PATH
    if not json_path.exists():
        return None

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        usuarios = data.get("usuarios", [])
        # Filtrar solo compradores (coordinadores)
        compradores = [u for u in usuarios if u.get("rol") == "comprador"]

        if not compradores:
            return None

        # Expandir usuarios con múltiples cursos en filas separadas
        filas = []
        for comprador in compradores:
            cursos = comprador.get("cursos", [])
            if not cursos:
                continue  # Ignorar compradores sin cursos asignados

            for curso_id in cursos:
                filas.append({
                    "id_curso_moodle": str(curso_id),
                    "comprador_nombre": comprador.get("nombre", ""),
                    "empresa": comprador.get("empresa", ""),
                    "email_comprador": comprador.get("email", ""),
                })

        if not filas:
            return None

        df = pd.DataFrame(filas)

        # Normalizar id_curso_moodle
        df["id_curso_moodle"] = df["id_curso_moodle"].astype(str).str.strip().str.lower()

        logger.info("Coordinadores cargados desde usuarios.json: %d registros (%d usuarios)", len(df), len(compradores))
        return df

    except Exception as e:
        logger.warning("Error leyendo coordinadores desde usuarios.json: %s", e)
        return None


def leer_compradores(path=None):
    """Lee coordinadores desde JSON (preferencia) o Excel (fallback).

    Intenta leer desde coordinadores.json primero. Si no existe o está vacío,
    fallback al Excel de compradores.

    Parameters
    ----------
    path : Path | str | None
        Ruta al archivo .xlsx (fallback).  Si es ``None`` usa ``settings.COMPRADORES_PATH``.

    Returns
    -------
    pd.DataFrame
        Con columnas: id_curso_moodle, comprador_nombre, empresa, email_comprador
    """
    # Intentar leer desde JSON primero
    df_json = _leer_desde_json()
    if df_json is not None and len(df_json) > 0:
        return df_json

    # Fallback al Excel
    logger.info("JSON no disponible o vacío, usando Excel como fallback")

    if path is None:
        path = settings.COMPRADORES_PATH

    path = Path(path)

    if not path.exists():
        logger.warning("Archivo de compradores no encontrado: %s", path)
        return pd.DataFrame(
            columns=["id_curso_moodle", "comprador_nombre", "empresa", "email_comprador"]
        )

    logger.info("Leyendo compradores desde %s", path)

    df = pd.read_excel(path, sheet_name="Compradores", dtype=str, engine="openpyxl")
    logger.info("Compradores: %d filas leídas", len(df))

    # Normalizar nombres de columnas para mapear
    col_rename = {}
    for col in df.columns:
        key = col.strip().lower()
        if key in _COL_MAP:
            col_rename[col] = _COL_MAP[key]

    df = df.rename(columns=col_rename)

    # Asegurar columnas requeridas existan
    for col in ["id_curso_moodle", "comprador_nombre", "empresa", "email_comprador"]:
        if col not in df.columns:
            df[col] = ""

    # Normalizar id_curso_moodle: strip + minúscula (para cruce)
    df["id_curso_moodle"] = (
        df["id_curso_moodle"].astype(str).str.strip().str.lower()
    )
    # Limpiar nulos
    df.loc[df["id_curso_moodle"].isin(["nan", "", "none"]), "id_curso_moodle"] = ""

    # Seleccionar solo columnas necesarias
    df = df[["id_curso_moodle", "comprador_nombre", "empresa", "email_comprador"]].copy()
    df = df[df["id_curso_moodle"] != ""].copy()

    # Deduplicar por id_curso_moodle (mantener primera fila con datos de comprador)
    df = df.drop_duplicates(subset=["id_curso_moodle"], keep="first")

    logger.info("Compradores válidos: %d", len(df))
    return df


def validar_emails_compradores(path=None):
    """Valida que cada ID Curso Moodle tenga emails consistentes.

    Lee el Excel SIN deduplicar para detectar filas con emails distintos
    para el mismo curso.

    Parameters
    ----------
    path : Path | str | None

    Returns
    -------
    list[str]
        Lista de mensajes de error.  Vacía si todo está OK.
    """
    if path is None:
        path = settings.COMPRADORES_PATH

    path = Path(path)
    if not path.exists():
        logger.debug("Archivo compradores no encontrado para validación: %s", path)
        return []

    df = pd.read_excel(path, sheet_name="Compradores", dtype=str, engine="openpyxl")

    # Normalizar nombres de columnas
    col_rename = {}
    for col in df.columns:
        key = col.strip().lower()
        if key in _COL_MAP:
            col_rename[col] = _COL_MAP[key]
    df = df.rename(columns=col_rename)

    for col in ["id_curso_moodle", "email_comprador"]:
        if col not in df.columns:
            df[col] = ""

    df["id_curso_moodle"] = df["id_curso_moodle"].astype(str).str.strip().str.lower()
    df.loc[df["id_curso_moodle"].isin(["nan", "", "none"]), "id_curso_moodle"] = ""
    df = df[df["id_curso_moodle"] != ""].copy()

    df["email_comprador"] = df["email_comprador"].fillna("").astype(str).str.strip()

    # Buscar nombre del curso para mensajes de error
    col_nombre = "nombre_curso_comprador" if "nombre_curso_comprador" in df.columns else None

    errores = []
    for id_moodle, grupo in df.groupby("id_curso_moodle"):
        emails = set(
            e for e in grupo["email_comprador"].unique()
            if e and e.lower() not in ("nan", "none", "")
        )
        if len(emails) > 1:
            nombre = ""
            if col_nombre and col_nombre in grupo.columns:
                nombre = grupo[col_nombre].dropna().iloc[0] if not grupo[col_nombre].dropna().empty else ""
            emails_sorted = sorted(emails)
            emails_str = " vs ".join(emails_sorted)
            errores.append({
                "curso": nombre or "Desconocido",
                "id_moodle": str(id_moodle),
                "emails": emails_sorted,
                "mensaje": (
                    f"ERROR: El curso {nombre!r} (ID Moodle: {id_moodle}) tiene "
                    f"emails de comprador inconsistentes: {emails_str}. "
                    f"Corrija el archivo compradores_tecnipro.xlsx antes de continuar."
                ),
            })

    return errores

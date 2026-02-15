"""Lee TODOS los CSV de SENCE de una carpeta."""

import logging
from pathlib import Path

import pandas as pd

from config import settings

logger = logging.getLogger(__name__)

SENCE_COLUMNS = ["RUT", "Nombre", "N_Ingresos", "DJ", "Accion"]


def leer_sence(carpeta=None):
    """Lee todos los CSV de asistencia SENCE y retorna un DataFrame consolidado.

    Cada archivo se llama ``<id_sence>.csv``.  El nombre del archivo (sin
    extensión) se usa como ID SENCE del curso.

    Parameters
    ----------
    carpeta : Path | str | None
        Carpeta con los CSV.  Si es ``None`` usa ``settings.SENCE_CSV_PATH``.

    Returns
    -------
    pd.DataFrame
        Columnas: LLave, IDUser, IDSence, N_Ingresos, DJ
    """
    if carpeta is None:
        carpeta = settings.SENCE_CSV_PATH

    carpeta = Path(carpeta)
    if not carpeta.exists():
        logger.warning("Carpeta SENCE no encontrada: %s", carpeta)
        return _df_vacio()

    archivos = sorted(carpeta.glob("*.csv"))
    if not archivos:
        logger.warning("Sin archivos CSV en %s", carpeta)
        return _df_vacio()

    logger.info("SENCE: %d archivos encontrados en %s", len(archivos), carpeta)

    frames = []
    for archivo in archivos:
        df = _leer_archivo_sence(archivo)
        if df is not None and len(df) > 0:
            frames.append(df)

    if not frames:
        logger.warning("Ningún archivo SENCE tenía datos válidos")
        return _df_vacio()

    resultado = pd.concat(frames, ignore_index=True)

    # Filtrar llaves vacías
    resultado = resultado[resultado["LLave"].str.strip() != ""].copy()

    logger.info("SENCE consolidado: %d registros", len(resultado))
    return resultado


def _leer_archivo_sence(archivo):
    """Lee un CSV individual de SENCE con fallback de encoding.

    SENCE "Descargar Conectividad" a veces devuelve archivos Excel (.xlsx)
    disfrazados con extensión .csv.  Se detecta por los bytes mágicos ``PK``
    (cabecera ZIP) y se lee con ``pd.read_excel`` en esos casos.
    """
    id_sence = archivo.stem  # nombre sin extensión = ID SENCE

    # ── Detectar si es Excel disfrazado de CSV ──────────────
    es_excel = False
    try:
        cabecera = archivo.read_bytes()[:4]
        if cabecera[:2] == b"PK":
            es_excel = True
    except Exception:
        pass

    if es_excel:
        return _leer_excel_sence(archivo, id_sence)

    # ── Lectura normal como CSV ─────────────────────────────
    # Intentar leer con utf-8 primero, luego latin-1
    contenido = None
    for enc in ("utf-8", "latin-1"):
        try:
            contenido = archivo.read_text(encoding=enc)
            break
        except (UnicodeDecodeError, ValueError):
            continue

    if contenido is None:
        logger.warning("No se pudo leer %s con ningún encoding", archivo.name)
        return None

    # Verificar si está vacío o tiene mensaje "No hay datos"
    lineas = [l for l in contenido.strip().splitlines() if l.strip()]
    if not lineas:
        logger.debug("Archivo SENCE vacío: %s", archivo.name)
        return None

    # Detectar mensaje "No hay datos disponibles"
    if len(lineas) == 1 and "no hay datos" in lineas[0].lower():
        logger.debug("Archivo SENCE sin datos: %s", archivo.name)
        return None

    # Leer como CSV sin encabezados
    try:
        df = pd.read_csv(
            archivo,
            header=None,
            names=SENCE_COLUMNS,
            encoding=_detectar_encoding(archivo),
            dtype=str,
        )
    except Exception as e:
        logger.warning("Error leyendo SENCE %s: %s", archivo.name, e)
        return None

    # Filtrar filas que no tienen RUT válido (contiene al menos un dígito y guión)
    df = df[df["RUT"].str.contains(r"\d", na=False)].copy()

    if df.empty:
        return None

    # Limpiar RUT: quitar puntos, trim, minúscula
    df["IDUser"] = df["RUT"].str.replace(".", "", regex=False).str.strip().str.lower()

    # ID SENCE del archivo
    df["IDSence"] = id_sence

    # Llave de cruce
    df["LLave"] = df["IDUser"] + id_sence

    # N_Ingresos a entero
    df["N_Ingresos"] = pd.to_numeric(df["N_Ingresos"], errors="coerce").fillna(0).astype(int)

    # DJ: "Pendiente de Emitir" → vacío
    df.loc[df["DJ"].str.strip().str.lower() == "pendiente de emitir", "DJ"] = ""

    # Seleccionar columnas finales
    df = df[["LLave", "IDUser", "IDSence", "N_Ingresos", "DJ"]].copy()

    logger.debug("SENCE %s: %d registros", archivo.name, len(df))
    return df


def _leer_excel_sence(archivo, id_sence):
    """Lee un archivo Excel de conectividad SENCE (.xlsx disfrazado de .csv).

    El Excel tiene una fila por sesión de conectividad con columnas como:
    "Rut Participante", "Nombre Participante", "Fecha Inicio Conectividad", etc.

    Se agrupa por RUT para contar sesiones (N_Ingresos).
    """
    try:
        df = pd.read_excel(archivo, header=0, dtype=str)
    except Exception as e:
        logger.warning("Error leyendo Excel SENCE %s: %s", archivo.name, e)
        return None

    if df.empty:
        logger.debug("Excel SENCE vacío: %s", archivo.name)
        return None

    # Buscar columnas específicas por nombre parcial
    col_rut = _buscar_columna(df, "rut participante")
    col_nombre = _buscar_columna(df, "nombre participante")

    if col_rut is None:
        logger.warning(
            "Excel SENCE %s: no se encontró 'Rut Participante' en %s",
            archivo.name, list(df.columns),
        )
        return None

    # Extraer solo las columnas necesarias
    rut_series = df[col_rut].astype(str).str.strip()
    nombre_series = df[col_nombre].astype(str).str.strip() if col_nombre else pd.Series("", index=df.index)

    # Buscar columna de fecha de inicio de conectividad
    col_fecha = _buscar_columna(df, "fecha inicio conectividad")

    # Filtrar filas sin RUT válido
    mask = rut_series.str.contains(r"\d", na=False)

    # NUEVO: Filtrar también filas sin fecha válida de conectividad
    if col_fecha is not None:
        mask = mask & df[col_fecha].notna()
        logger.debug("Filtrando filas con fecha de conectividad válida")

    rut_series = rut_series[mask]
    nombre_series = nombre_series[mask]

    if rut_series.empty:
        return None

    # Limpiar RUT
    id_user = rut_series.str.replace(".", "", regex=False).str.strip().str.lower()

    # Agrupar por RUT: contar sesiones (solo las que tienen fecha válida), tomar primer nombre
    agrupado = pd.DataFrame({"IDUser": id_user, "Nombre": nombre_series})
    conteo = agrupado.groupby("IDUser").agg(
        Nombre=("Nombre", "first"),
        N_Ingresos=("IDUser", "size"),
    ).reset_index()

    conteo["IDSence"] = id_sence
    conteo["LLave"] = conteo["IDUser"] + id_sence
    conteo["DJ"] = ""

    conteo = conteo[["LLave", "IDUser", "IDSence", "N_Ingresos", "DJ"]].copy()

    logger.debug("Excel SENCE %s: %d participantes (%d sesiones)", archivo.name, len(conteo), len(rut_series))
    return conteo


def _buscar_columna(df, patron):
    """Busca una columna cuyo nombre contenga el patrón (case-insensitive)."""
    for col in df.columns:
        if patron in str(col).lower():
            return col
    return None


def _detectar_encoding(archivo):
    """Intenta utf-8; si falla retorna latin-1."""
    try:
        archivo.read_text(encoding="utf-8")
        return "utf-8"
    except (UnicodeDecodeError, ValueError):
        return "latin-1"


def _df_vacio():
    """Retorna un DataFrame vacío con las columnas esperadas."""
    return pd.DataFrame(columns=["LLave", "IDUser", "IDSence", "N_Ingresos", "DJ"])

"""Lee Dreporte.csv (participantes y progreso)."""

import logging

import pandas as pd

from config import settings

logger = logging.getLogger(__name__)


def leer_dreporte(path=None):
    """Lee el archivo Dreporte.csv y retorna un DataFrame filtrado.

    Parameters
    ----------
    path : Path | str | None
        Ruta al CSV.  Si es ``None`` se busca un archivo que empiece con "D"
        dentro de ``settings.DATA_INPUT_PATH``.

    Returns
    -------
    pd.DataFrame
    """
    if path is None:
        path = _buscar_archivo("D")

    logger.info("Leyendo Dreporte desde %s", path)

    df = pd.read_csv(path, encoding="utf-8-sig", dtype=str)
    logger.info("Dreporte: %d filas leídas", len(df))

    # ── Filtros ────────────────────────────────────────────
    # Excluir suspendidos
    df = df[df["Estado"].str.strip().str.lower() != "suspendido"].copy()

    # Solo estudiantes
    df = df[df["Rol"].str.strip().str.lower() == "estudiante"].copy()

    # Excluir sin nombre
    df = df[df["Nombre completo Participante"].notna()].copy()
    df = df[df["Nombre completo Participante"].str.strip() != ""].copy()

    logger.info("Dreporte tras filtros: %d filas", len(df))

    # ── Normalización ──────────────────────────────────────
    # Nombre corto del curso: strip + minúscula (viene como int-like)
    df["Nombre corto del curso con enlace"] = (
        df["Nombre corto del curso con enlace"].astype(str).str.strip().str.lower()
    )

    # ID del Usuario: strip + minúscula
    df["ID del Usuario"] = (
        df["ID del Usuario"].astype(str).str.strip().str.lower()
    )

    # IDSence: strip (mantener como string)
    df["IDSence"] = df["IDSence"].astype(str).str.strip()
    # Limpiar valores nulos representados como "nan"
    df.loc[df["IDSence"].isin(["nan", "", "None"]), "IDSence"] = ""

    # Progreso: "100,0%" → 100.0
    df["Progreso del estudiante"] = (
        df["Progreso del estudiante"]
        .astype(str)
        .str.replace("%", "", regex=False)
        .str.replace(",", ".", regex=False)
        .str.strip()
    )
    df["Progreso del estudiante"] = pd.to_numeric(
        df["Progreso del estudiante"], errors="coerce"
    ).fillna(0.0)

    # Calificación: "7,00" → 7.0
    df["Calificación"] = (
        df["Calificación"]
        .astype(str)
        .str.replace(",", ".", regex=False)
        .str.strip()
    )
    df["Calificación"] = pd.to_numeric(df["Calificación"], errors="coerce")

    # Nombre participante: Title Case + strip
    df["Nombre completo Participante"] = (
        df["Nombre completo Participante"].str.strip().str.title()
    )

    # Email: minúscula + strip
    df["Dirección de correo"] = (
        df["Dirección de correo"].astype(str).str.strip().str.lower()
    )

    # Construir llave para cruce con SENCE
    df["LLave"] = df["ID del Usuario"] + df["IDSence"]
    # Si IDSence está vacío la llave no sirve
    df.loc[df["IDSence"] == "", "LLave"] = ""

    return df


def _buscar_archivo(prefijo):
    """Busca el primer CSV cuyo nombre empiece con *prefijo* en DATA_INPUT_PATH."""
    carpeta = settings.DATA_INPUT_PATH
    for f in sorted(carpeta.iterdir()):
        if f.name.lower().startswith(prefijo.lower()) and f.suffix.lower() == ".csv":
            return f
    raise FileNotFoundError(
        f"No se encontró CSV con prefijo '{prefijo}' en {carpeta}"
    )

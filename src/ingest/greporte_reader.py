"""Lee Greporte.csv (listado de cursos Moodle)."""

import logging

import pandas as pd

from config import settings

logger = logging.getLogger(__name__)


def leer_greporte(path=None):
    """Lee el archivo Greporte.csv y retorna un DataFrame filtrado.

    Parameters
    ----------
    path : Path | str | None
        Ruta al CSV.  Si es ``None`` se busca un archivo que empiece con "G"
        dentro de ``settings.DATA_INPUT_PATH``.

    Returns
    -------
    pd.DataFrame
    """
    if path is None:
        path = _buscar_archivo("G")

    logger.info("Leyendo Greporte desde %s", path)

    df = pd.read_csv(path, encoding="utf-8-sig", dtype=str)
    logger.info("Greporte: %d filas leídas", len(df))

    # Filtrar "Restauración del curso iniciada"
    mask = df["Nombre completo del curso"].str.contains(
        "Restauración del curso iniciada", na=False
    )
    df = df[~mask].copy()
    logger.info("Greporte tras filtro restauración: %d filas", len(df))

    # Normalizar nombre corto: strip + minúscula
    df["Nombre corto del curso"] = (
        df["Nombre corto del curso"].astype(str).str.strip().str.lower()
    )

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

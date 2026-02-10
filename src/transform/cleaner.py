"""Limpieza y normalización de datos — incluye parser de fechas en español."""

import logging
import re
from datetime import datetime

logger = logging.getLogger(__name__)

MESES_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}

# Patrón: "miércoles, 5 de noviembre de 2025, 00:00"
_RE_FECHA = re.compile(
    r",\s*(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})"
)

# Patrón hora opcional al final: ", 23:59"
_RE_HORA = re.compile(r",\s*(\d{1,2}):(\d{2})\s*$")


def parse_fecha_espanol(texto):
    """Parsea una fecha en formato largo español a ``datetime``.

    Formatos soportados:
    - ``"miércoles, 5 de noviembre de 2025, 00:00"``
    - ``"5 de noviembre de 2025"``
    - ``"Nunca"`` / vacío → ``None``

    Returns
    -------
    datetime | None
    """
    if not texto or not isinstance(texto, str):
        return None

    texto = texto.strip()
    if texto.lower() in ("nunca", "nan", "", "none", "nat"):
        return None

    # Intentar patrón principal
    m = _RE_FECHA.search(texto)
    if m:
        dia = int(m.group(1))
        mes_nombre = m.group(2).lower()
        anio = int(m.group(3))
        mes = MESES_ES.get(mes_nombre)
        if mes is None:
            logger.warning("Mes desconocido: '%s' en '%s'", mes_nombre, texto)
            return None

        hora, minuto = 0, 0
        mh = _RE_HORA.search(texto)
        if mh:
            hora = int(mh.group(1))
            minuto = int(mh.group(2))

        try:
            return datetime(anio, mes, dia, hora, minuto)
        except ValueError as e:
            logger.warning("Fecha inválida '%s': %s", texto, e)
            return None

    # Fallback: intentar con dateutil
    try:
        from dateutil import parser as du_parser
        return du_parser.parse(texto, dayfirst=True)
    except Exception:
        logger.warning("No se pudo parsear fecha: '%s'", texto)
        return None


def clean_rut(rut):
    """Limpia un RUT: quita puntos, trim, minúscula.

    ``"15.083.435-K"`` → ``"15083435-k"``
    """
    if not rut or not isinstance(rut, str):
        return ""
    return rut.replace(".", "").strip().lower()

"""
Parser de CSV del Registro de Ventas del SII (Servicio de Impuestos Internos de Chile).

Maneja:
  - Separador: punto y coma (;)
  - Encoding: UTF-8 con fallback a Latin-1
  - Formatos de fecha:
      DD-MM-YYYY           (e.g. "03-01-2023")
      DD/MM/YYYY           (e.g. "01/02/2022")
      DD-MM-YYYY HH:MM     (e.g. "03-01-2023 16:41")
      DD/MM/YYYY HH:MM:SS  (e.g. "01/02/2022 18:40:03")
  - Tipos de documento relevantes: 33, 34 (facturas), 61 (notas de crédito)
  - Nombre de archivo: "MM YYYY.csv" o "MM_YYYY.csv" → extrae periodo_tributario
  - Corte temporal: facturas < 2026 entran como "Pagada" (histórico)

Uso:
    resultado = parsear_archivo(path_csv)
    # resultado.documentos  → lista de dicts listos para insertar_documento()
    # resultado.errores     → lista de strings con filas problemáticas
    # resultado.periodo     → "2023-01"
    # resultado.duplicados  → int (filas omitidas por UNIQUE en la BD)
"""

import csv
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from config import settings

logger = logging.getLogger(__name__)

# ── Constantes ────────────────────────────────────────────────────────────────

TIPOS_RELEVANTES = frozenset({33, 34, 61})

NOMBRE_TIPO = {
    33: "Factura Electronica",
    34: "Factura Exenta",
    61: "Nota de Credito",
}

# Separador de columnas del CSV del SII
CSV_DELIMITER = ";"

# Patrón para extraer mes y año del nombre del archivo
# Soporta: "01 2023.csv", "01_2023.csv", "012023.csv"
_PATRON_NOMBRE = re.compile(r"(\d{2})[\s_]?(\d{4})\.csv$", re.IGNORECASE)

# Patrones de fecha para parseo manual (strptime es lento × millones de filas)
_FMTS_FECHA = [
    "%d/%m/%Y %H:%M:%S",  # "01/02/2022 18:40:03"
    "%d/%m/%Y %H:%M",     # "01/02/2022 18:40"  (poco frecuente)
    "%d-%m-%Y %H:%M:%S",  # "03-01-2023 16:41:05" (poco frecuente)
    "%d-%m-%Y %H:%M",     # "03-01-2023 16:41"
    "%d/%m/%Y",           # "01/02/2022"
    "%d-%m-%Y",           # "03-01-2023"
]


# ── Mapeo de columnas CSV ─────────────────────────────────────────────────────

# Nombre exacto de columna en el CSV → nombre interno
_COL_MAP = {
    "Tipo Doc":                   "tipo_doc",
    "Tipo Venta":                 "tipo_venta",
    "Rut cliente":                "rut_cliente",
    "Razon Social":               "razon_social",
    "Folio":                      "folio",
    "Fecha Docto":                "fecha_docto",
    "Fecha Recepcion":            "fecha_recepcion",
    "Fecha Acuse Recibo":         "fecha_acuse_recibo",
    "Monto Exento":               "monto_exento",
    "Monto Neto":                 "monto_neto",
    "Monto IVA":                  "monto_iva",
    "Monto total":                "monto_total",
    "Tipo Docto. Referencia":     "tipo_doc_referencia",
    "Folio Docto. Referencia":    "folio_referencia",
}


# ── Resultado del parseo ──────────────────────────────────────────────────────

@dataclass
class ResultadoParseo:
    """Resultado de parsear un archivo CSV del SII."""
    periodo: str                        # "YYYY-MM"
    archivo_origen: str                 # nombre del archivo (sin ruta)
    documentos: list[dict] = field(default_factory=list)
    errores: list[str] = field(default_factory=list)
    filas_omitidas: int = 0             # tipo_doc no relevante
    total_filas: int = 0

    @property
    def facturas(self) -> list[dict]:
        return [d for d in self.documentos if d["tipo_doc"] in (33, 34)]

    @property
    def notas_credito(self) -> list[dict]:
        return [d for d in self.documentos if d["tipo_doc"] == 61]

    @property
    def monto_total_facturas(self) -> int:
        return sum(d["monto_total"] for d in self.facturas)


# ── Funciones auxiliares ──────────────────────────────────────────────────────

def _extraer_periodo(nombre_archivo: str) -> str:
    """
    Extrae el periodo tributario del nombre del archivo.

    "01 2023.csv"  → "2023-01"
    "12_2024.csv"  → "2024-12"
    """
    m = _PATRON_NOMBRE.search(nombre_archivo)
    if m:
        mes, anio = m.group(1), m.group(2)
        return f"{anio}-{mes}"
    raise ValueError(f"No se pudo extraer periodo del nombre de archivo: {nombre_archivo!r}")


def _parsear_fecha(valor: str) -> Optional[str]:
    """
    Convierte una cadena de fecha/datetime del SII a formato ISO 8601.

    Retorna None si el valor está vacío o no reconocido.
    Retorna "YYYY-MM-DD" para fechas solas.
    Retorna "YYYY-MM-DDTHH:MM:SS" para fechas con hora.
    """
    if not valor or not valor.strip():
        return None
    valor = valor.strip()
    for fmt in _FMTS_FECHA:
        try:
            dt = datetime.strptime(valor, fmt)
            if "%H" in fmt:
                return dt.strftime("%Y-%m-%dT%H:%M:%S")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    logger.debug("Formato de fecha no reconocido: %r", valor)
    return None


def _parsear_monto(valor: str) -> int:
    """
    Convierte un monto del CSV a entero (pesos chilenos, sin decimales).

    Maneja: "", "0", "1234567", "-1234"
    Los montos vacíos o inválidos se tratan como 0.
    """
    if not valor or not valor.strip():
        return 0
    try:
        return int(valor.strip())
    except ValueError:
        # Caso inesperado: loguear pero no fallar
        logger.debug("Monto no parseable: %r → 0", valor)
        return 0


def _parsear_folio(valor: str) -> Optional[int]:
    """Convierte el folio a entero. Retorna None si está vacío."""
    if not valor or not valor.strip():
        return None
    try:
        return int(valor.strip())
    except ValueError:
        return None


def _estado_inicial(fecha_docto_iso: str, anio_corte: int) -> tuple[str, int]:
    """
    Determina el estado inicial y el saldo_pendiente de un documento al importarlo.

    Retorna (estado, saldo_pendiente).
    - Documentos históricos (< anio_corte): estado="Pagada", saldo=0
    - Documentos activos (>= anio_corte): estado="Pendiente", saldo=monto_total
      (el saldo real se calcula después de insertar; aquí devolvemos un marker)
    """
    try:
        anio = int(fecha_docto_iso[:4])
    except (ValueError, TypeError, IndexError):
        return "Pendiente", 0  # No se pudo determinar → tratar como activo

    if anio < anio_corte:
        return "Pagada", 0
    return "Pendiente", -1   # -1 = "usar monto_total" (se reemplaza en el llamador)


def _detectar_encoding(ruta: Path) -> str:
    """Detecta encoding UTF-8 o Latin-1 leyendo los primeros bytes."""
    with open(ruta, "rb") as f:
        raw = f.read(4096)
    try:
        raw.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        return "latin-1"


# ── Parser principal ──────────────────────────────────────────────────────────

def parsear_archivo(ruta: Path) -> ResultadoParseo:
    """
    Parsea un archivo CSV del Registro de Ventas del SII.

    Args:
        ruta: Path al archivo CSV.

    Returns:
        ResultadoParseo con todos los documentos y metadatos.

    Raises:
        ValueError: Si el nombre del archivo no tiene formato válido.
        FileNotFoundError: Si el archivo no existe.
    """
    ruta = Path(ruta)
    if not ruta.exists():
        raise FileNotFoundError(f"Archivo no encontrado: {ruta}")

    nombre_archivo = ruta.name
    periodo = _extraer_periodo(nombre_archivo)
    anio_corte = settings.ANIO_CORTE_GESTION
    ahora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    resultado = ResultadoParseo(periodo=periodo, archivo_origen=nombre_archivo)
    encoding = _detectar_encoding(ruta)
    logger.info("Parseando %s (encoding=%s, periodo=%s)", nombre_archivo, encoding, periodo)

    with open(ruta, encoding=encoding, errors="replace") as f:
        reader = csv.DictReader(f, delimiter=CSV_DELIMITER)

        # Verificar que el CSV tiene las columnas mínimas esperadas
        if reader.fieldnames is None:
            resultado.errores.append("El archivo CSV está vacío o no tiene encabezados")
            return resultado

        columnas_csv = set(reader.fieldnames)
        columnas_requeridas = {"Tipo Doc", "Folio", "Fecha Docto", "Monto total", "Rut cliente"}
        faltantes = columnas_requeridas - columnas_csv
        if faltantes:
            resultado.errores.append(
                f"Columnas requeridas no encontradas: {', '.join(sorted(faltantes))}"
            )
            return resultado

        for nro_fila, fila in enumerate(reader, start=2):  # start=2: fila 1 es header
            resultado.total_filas += 1

            # ── Tipo de documento ─────────────────────────────
            tipo_doc_raw = fila.get("Tipo Doc", "").strip()
            try:
                tipo_doc = int(tipo_doc_raw)
            except ValueError:
                resultado.errores.append(
                    f"Fila {nro_fila}: Tipo Doc inválido: {tipo_doc_raw!r}"
                )
                continue

            if tipo_doc not in TIPOS_RELEVANTES:
                resultado.filas_omitidas += 1
                continue

            # ── Folio ─────────────────────────────────────────
            folio = _parsear_folio(fila.get("Folio", ""))
            if folio is None:
                resultado.errores.append(f"Fila {nro_fila}: Folio vacío o inválido")
                continue

            # ── Fechas ────────────────────────────────────────
            fecha_docto = _parsear_fecha(fila.get("Fecha Docto", ""))
            if fecha_docto is None:
                resultado.errores.append(
                    f"Fila {nro_fila} (folio {folio}): Fecha Docto vacía o inválida"
                )
                continue

            fecha_recepcion = _parsear_fecha(fila.get("Fecha Recepcion", ""))
            fecha_acuse = _parsear_fecha(fila.get("Fecha Acuse Recibo", ""))

            # ── Montos (siempre INTEGER) ───────────────────────
            monto_exento = _parsear_monto(fila.get("Monto Exento", ""))
            monto_neto   = _parsear_monto(fila.get("Monto Neto", ""))
            monto_iva    = _parsear_monto(fila.get("Monto IVA", ""))
            monto_total  = _parsear_monto(fila.get("Monto total", ""))

            if monto_total == 0 and tipo_doc in (33, 34):
                resultado.errores.append(
                    f"Fila {nro_fila} (folio {folio}): monto_total es 0 en una factura"
                )
                # No cancelamos la importación, pero advertimos

            # ── Referencia (para Notas de Crédito) ───────────
            tipo_doc_ref = _parsear_folio(fila.get("Tipo Docto. Referencia", ""))
            folio_ref    = _parsear_folio(fila.get("Folio Docto. Referencia", ""))

            # ── RUT y Razón Social ────────────────────────────
            rut_cliente  = fila.get("Rut cliente", "").strip()
            razon_social = fila.get("Razon Social", "").strip()

            # ── Estado inicial según corte temporal ───────────
            estado, saldo = _estado_inicial(fecha_docto, anio_corte)
            if saldo == -1:
                # Documento activo: saldo inicial = monto total
                # Las NC se aplican después en credit_note_engine
                saldo = monto_total

            # ── Las NC históricas no necesitan saldo ──────────
            if tipo_doc == 61 and estado == "Pagada":
                saldo = 0

            doc = {
                "tipo_doc":           tipo_doc,
                "tipo_doc_nombre":    NOMBRE_TIPO[tipo_doc],
                "tipo_venta":         fila.get("Tipo Venta", "").strip() or None,
                "rut_cliente":        rut_cliente,
                "razon_social":       razon_social,
                "folio":              folio,
                "fecha_docto":        fecha_docto,
                "fecha_recepcion":    fecha_recepcion,
                "fecha_acuse_recibo": fecha_acuse,
                "monto_exento":       monto_exento,
                "monto_neto":         monto_neto,
                "monto_iva":          monto_iva,
                "monto_total":        monto_total,
                "folio_referencia":   folio_ref,
                "tipo_doc_referencia": tipo_doc_ref,
                "periodo_tributario": periodo,
                "archivo_origen":     nombre_archivo,
                "fecha_importacion":  ahora,
                "estado":             estado,
                "saldo_pendiente":    saldo,
            }
            resultado.documentos.append(doc)

    logger.info(
        "Parseo completado: %d documentos (%d facturas, %d NC), "
        "%d omitidos, %d errores",
        len(resultado.documentos),
        len(resultado.facturas),
        len(resultado.notas_credito),
        resultado.filas_omitidas,
        len(resultado.errores),
    )
    return resultado


def parsear_multiples_archivos(rutas: list[Path]) -> list[ResultadoParseo]:
    """
    Parsea varios archivos CSV del SII, ordenados por período.

    Útil para importación masiva de todo el histórico.
    """
    resultados = []
    for ruta in sorted(rutas, key=lambda p: _extraer_periodo_seguro(p.name)):
        try:
            resultados.append(parsear_archivo(ruta))
        except (ValueError, FileNotFoundError) as exc:
            logger.error("Error parseando %s: %s", ruta.name, exc)
            r = ResultadoParseo(periodo="desconocido", archivo_origen=ruta.name)
            r.errores.append(str(exc))
            resultados.append(r)
    return resultados


def _extraer_periodo_seguro(nombre: str) -> str:
    """Versión sin raise para usar como key de sort."""
    try:
        return _extraer_periodo(nombre)
    except ValueError:
        return "9999-99"  # Al final del sort

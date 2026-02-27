"""
Modelos de datos para el módulo de cobranzas.

Gestiona la base de datos SQLite con todas las tablas del sistema:
  - documentos_sii: facturas y notas de crédito del SII
  - clientes: catálogo de clientes reales (no OTICs)
  - pagos: ingresos bancarios
  - pago_detalle: distribución de pagos entre facturas
  - log_auditoria: trazabilidad de todas las acciones
"""

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from config import settings

logger = logging.getLogger(__name__)

DB_PATH: Path = settings.COBRANZAS_DB_PATH

# DDL de la base de datos — se ejecuta una sola vez en init_db()
_SCHEMA = """
-- ─── Documentos SII ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS documentos_sii (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo_doc            INTEGER  NOT NULL,          -- 33, 34, 61
    tipo_doc_nombre     TEXT     NOT NULL,
    tipo_venta          TEXT,
    rut_cliente         TEXT     NOT NULL,          -- RUT de la OTIC receptor
    razon_social        TEXT     NOT NULL,
    folio               INTEGER  NOT NULL,
    fecha_docto         DATE     NOT NULL,
    fecha_recepcion     DATETIME,
    fecha_acuse_recibo  DATETIME,
    monto_exento        INTEGER  NOT NULL DEFAULT 0,
    monto_neto          INTEGER  NOT NULL DEFAULT 0,
    monto_iva           INTEGER  NOT NULL DEFAULT 0,
    monto_total         INTEGER  NOT NULL DEFAULT 0,
    folio_referencia    INTEGER,                    -- NC: folio de la factura que modifica
    tipo_doc_referencia INTEGER,                    -- NC: tipo del doc de referencia
    periodo_tributario  TEXT     NOT NULL,          -- "YYYY-MM" extraído del nombre de archivo
    archivo_origen      TEXT     NOT NULL,
    fecha_importacion   DATETIME NOT NULL,
    -- Campos de gestión activa (solo 2026+)
    cliente_id          INTEGER  REFERENCES clientes(id) ON DELETE SET NULL,
    curso               TEXT,
    estado              TEXT     NOT NULL DEFAULT 'Pendiente',
    saldo_pendiente     INTEGER  NOT NULL DEFAULT 0,
    UNIQUE(tipo_doc, folio)
);

CREATE INDEX IF NOT EXISTS idx_docs_estado      ON documentos_sii(estado);
CREATE INDEX IF NOT EXISTS idx_docs_periodo     ON documentos_sii(periodo_tributario);
CREATE INDEX IF NOT EXISTS idx_docs_rut         ON documentos_sii(rut_cliente);
CREATE INDEX IF NOT EXISTS idx_docs_cliente     ON documentos_sii(cliente_id);
CREATE INDEX IF NOT EXISTS idx_docs_fecha       ON documentos_sii(fecha_docto);

-- ─── Clientes ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS clientes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre          TEXT NOT NULL UNIQUE,           -- Título: "Empresa Ejemplo Spa"
    nombre_busqueda TEXT NOT NULL UNIQUE,           -- MAYÚSCULAS sin tildes para dedup
    rut             TEXT,
    contacto        TEXT,
    email           TEXT,
    telefono        TEXT,
    fecha_creacion  DATETIME NOT NULL,
    creado_por      TEXT     NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_clientes_busqueda ON clientes(nombre_busqueda);

-- ─── Pagos ───────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS pagos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha_pago      DATE     NOT NULL,
    monto_total     INTEGER  NOT NULL,
    observacion     TEXT,
    fecha_registro  DATETIME NOT NULL,
    registrado_por  TEXT     NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pagos_fecha ON pagos(fecha_pago);

-- ─── Pago Detalle (distribución muchos-a-muchos) ─────────────────────────────
CREATE TABLE IF NOT EXISTS pago_detalle (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    pago_id          INTEGER NOT NULL REFERENCES pagos(id)          ON DELETE CASCADE,
    documento_id     INTEGER NOT NULL REFERENCES documentos_sii(id) ON DELETE RESTRICT,
    monto_aplicado   INTEGER NOT NULL,
    fecha_aplicacion DATETIME NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pd_pago      ON pago_detalle(pago_id);
CREATE INDEX IF NOT EXISTS idx_pd_documento ON pago_detalle(documento_id);

-- ─── Log de Auditoría ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS log_auditoria (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha   DATETIME NOT NULL,
    usuario TEXT     NOT NULL,
    accion  TEXT     NOT NULL,   -- "importar_csv", "registrar_pago", etc.
    detalle TEXT,
    ip      TEXT
);

CREATE INDEX IF NOT EXISTS idx_log_fecha   ON log_auditoria(fecha);
CREATE INDEX IF NOT EXISTS idx_log_accion  ON log_auditoria(accion);
"""


def init_db() -> None:
    """Crea la BD y todas las tablas si no existen. Idempotente."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(_SCHEMA)
        # Habilitar claves foráneas en esta conexión de inicialización
        conn.execute("PRAGMA foreign_keys = ON")
        conn.commit()
    logger.info("Base de datos de cobranzas inicializada: %s", DB_PATH)


@contextmanager
def get_db():
    """
    Context manager que entrega una conexión SQLite configurada.

    Uso:
        with get_db() as conn:
            rows = conn.execute("SELECT ...").fetchall()
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row          # Filas accesibles por nombre de columna
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")  # WAL: mejor concurrencia con Flask
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Tipos de documento ────────────────────────────────────────────────────────

TIPOS_DOC = {
    33: "Factura Electronica",
    34: "Factura Exenta",
    61: "Nota de Credito",
}

TIPOS_RELEVANTES = frozenset(TIPOS_DOC.keys())


# ── CRUD: documentos_sii ──────────────────────────────────────────────────────

def insertar_documento(conn: sqlite3.Connection, doc: dict) -> int | None:
    """
    Inserta un documento SII.

    Retorna el id del nuevo registro, o None si ya existía (UNIQUE constraint).
    Los montos se almacenan como INTEGER (pesos chilenos, sin decimales).
    """
    sql = """
        INSERT OR IGNORE INTO documentos_sii (
            tipo_doc, tipo_doc_nombre, tipo_venta,
            rut_cliente, razon_social, folio,
            fecha_docto, fecha_recepcion, fecha_acuse_recibo,
            monto_exento, monto_neto, monto_iva, monto_total,
            folio_referencia, tipo_doc_referencia,
            periodo_tributario, archivo_origen, fecha_importacion,
            estado, saldo_pendiente
        ) VALUES (
            :tipo_doc, :tipo_doc_nombre, :tipo_venta,
            :rut_cliente, :razon_social, :folio,
            :fecha_docto, :fecha_recepcion, :fecha_acuse_recibo,
            :monto_exento, :monto_neto, :monto_iva, :monto_total,
            :folio_referencia, :tipo_doc_referencia,
            :periodo_tributario, :archivo_origen, :fecha_importacion,
            :estado, :saldo_pendiente
        )
    """
    cursor = conn.execute(sql, doc)
    if cursor.lastrowid and cursor.rowcount > 0:
        return cursor.lastrowid
    return None


def buscar_factura_por_folio(
    conn: sqlite3.Connection, folio: int, tipo_doc: int | None = None
) -> sqlite3.Row | None:
    """Busca una factura por folio (y opcionalmente tipo_doc)."""
    if tipo_doc is not None:
        return conn.execute(
            "SELECT * FROM documentos_sii WHERE folio = ? AND tipo_doc = ?",
            (folio, tipo_doc),
        ).fetchone()
    return conn.execute(
        "SELECT * FROM documentos_sii WHERE folio = ? AND tipo_doc IN (33, 34)",
        (folio,),
    ).fetchone()


def recalcular_saldo(conn: sqlite3.Connection, documento_id: int) -> None:
    """
    Recalcula el saldo_pendiente y el estado de una factura ACTIVA (>= ANIO_CORTE_GESTION).

    saldo = monto_total - sum(pagos aplicados) - sum(NC que referencian esta factura)
    Estado resultante:
      - "Pagada"   si saldo == 0
      - "Parcial"  si 0 < saldo < monto_total y hay al menos un pago
      - "Pendiente" si no hay pagos y saldo == monto_total
      - "Anulada"  estado terminal, no se modifica aquí (lo gestiona credit_note_engine)

    Documentos históricos (< ANIO_CORTE_GESTION) y NC no se recalculan.
    """
    doc = conn.execute(
        "SELECT id, tipo_doc, monto_total, estado, fecha_docto FROM documentos_sii WHERE id = ?",
        (documento_id,),
    ).fetchone()
    if doc is None:
        return

    # Solo facturas activas reciben gestión de saldo
    if doc["tipo_doc"] == 61:
        return  # Las NC no tienen saldo propio
    if doc["estado"] == "Anulada":
        return  # Estado terminal: solo credit_note_engine lo puede cambiar

    # Documentos históricos: ya fueron marcados "Pagada" al importar, no tocar
    try:
        anio_doc = int(str(doc["fecha_docto"])[:4])
    except (ValueError, TypeError):
        anio_doc = 0
    if anio_doc < settings.ANIO_CORTE_GESTION:
        return

    total = doc["monto_total"]

    # Suma de pagos aplicados a esta factura
    pagos_sum = conn.execute(
        "SELECT COALESCE(SUM(monto_aplicado), 0) FROM pago_detalle WHERE documento_id = ?",
        (documento_id,),
    ).fetchone()[0]

    # Suma de NC que referencian esta factura (por folio Y tipo_doc para evitar colisiones)
    nc_sum = conn.execute(
        """SELECT COALESCE(SUM(nc.monto_total), 0)
           FROM documentos_sii nc
           JOIN documentos_sii fact
             ON nc.folio_referencia     = fact.folio
            AND nc.tipo_doc_referencia  = fact.tipo_doc
           WHERE nc.tipo_doc = 61
             AND fact.id     = ?""",
        (documento_id,),
    ).fetchone()[0]

    saldo = max(0, total - pagos_sum - nc_sum)

    if saldo == 0:
        nuevo_estado = "Pagada"
    elif pagos_sum > 0:
        nuevo_estado = "Parcial"
    else:
        nuevo_estado = "Pendiente"

    conn.execute(
        "UPDATE documentos_sii SET saldo_pendiente = ?, estado = ? WHERE id = ?",
        (saldo, nuevo_estado, documento_id),
    )


# ── CRUD: clientes ────────────────────────────────────────────────────────────

def normalizar_nombre_cliente(nombre: str) -> tuple[str, str]:
    """
    Normaliza un nombre de cliente.

    Retorna (nombre_titulo, nombre_busqueda):
      - nombre_titulo: "Hotel Diego De Almagro"  (para almacenar)
      - nombre_busqueda: "HOTEL DIEGO DE ALMAGRO" sin tildes (para comparar)
    """
    import unicodedata

    nombre = " ".join(nombre.split())  # Colapsar espacios
    nombre_titulo = nombre.title()

    # Quitar tildes para nombre_busqueda
    nfkd = unicodedata.normalize("NFKD", nombre_titulo.upper())
    nombre_busqueda = "".join(c for c in nfkd if not unicodedata.combining(c))

    return nombre_titulo, nombre_busqueda


def buscar_clientes_similares(
    conn: sqlite3.Connection, nombre: str, limite: int = 5
) -> list[sqlite3.Row]:
    """Busca clientes cuyo nombre_busqueda contenga las palabras del nombre dado."""
    _, nombre_busqueda = normalizar_nombre_cliente(nombre)
    # Búsqueda por LIKE para cada palabra significativa (más de 2 letras)
    palabras = [p for p in nombre_busqueda.split() if len(p) > 2]
    if not palabras:
        return []
    condiciones = " AND ".join(["nombre_busqueda LIKE ?"] * len(palabras))
    params = [f"%{p}%" for p in palabras]
    params.append(limite)
    return conn.execute(
        f"SELECT * FROM clientes WHERE {condiciones} LIMIT ?", params
    ).fetchall()


# ── CRUD: log_auditoria ───────────────────────────────────────────────────────

def registrar_auditoria(
    conn: sqlite3.Connection,
    usuario: str,
    accion: str,
    detalle: str = "",
    ip: str = "",
) -> None:
    """Registra una acción en el log de auditoría."""
    conn.execute(
        "INSERT INTO log_auditoria (fecha, usuario, accion, detalle, ip) VALUES (?, ?, ?, ?, ?)",
        (datetime.now(timezone.utc).isoformat(), usuario, accion, detalle, ip),
    )

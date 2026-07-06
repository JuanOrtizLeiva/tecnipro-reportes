"""Registro persistente de certificados de participación (SQLite + WAL).

Fuente de verdad de folios, códigos de validación y estados de envío.
Lo comparten la app web (gunicorn, varios workers) y el proceso de emisión
en segundo plano; SQLite en modo WAL soporta ese patrón con bajo volumen
de escrituras.

Estados de un certificado: pendiente → generado → enviado | error.
Estados de un lote: pendiente → procesando → completado |
completado_con_errores | error.
"""

import json
import logging
import secrets
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from config import settings

logger = logging.getLogger(__name__)

# Alfabeto sin caracteres ambiguos (sin I, O, 0, 1) para códigos legibles.
_ALFABETO_CODIGO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS lotes (
    id            TEXT PRIMARY KEY,
    creado_en     TEXT NOT NULL,
    creado_por    TEXT NOT NULL,
    estado        TEXT NOT NULL DEFAULT 'pendiente',
    total         INTEGER NOT NULL DEFAULT 0,
    procesados    INTEGER NOT NULL DEFAULT 0,
    errores       INTEGER NOT NULL DEFAULT 0,
    detalle       TEXT,
    actualizado_en TEXT
);

CREATE TABLE IF NOT EXISTS certificados (
    folio_num       INTEGER PRIMARY KEY AUTOINCREMENT,
    folio           TEXT UNIQUE,
    codigo          TEXT UNIQUE NOT NULL,
    lote_id         TEXT NOT NULL REFERENCES lotes(id),
    curso_id        TEXT NOT NULL,
    curso_nombre    TEXT NOT NULL,
    modalidad       TEXT NOT NULL,
    alumno_nombre   TEXT NOT NULL,
    alumno_rut      TEXT NOT NULL,
    alumno_email    TEXT,
    fecha_inicio    TEXT NOT NULL,
    fecha_termino   TEXT NOT NULL,
    horas           REAL NOT NULL,
    asistencia_pct  REAL,
    calificacion    REAL,
    incluido_manual INTEGER NOT NULL DEFAULT 0,
    motivo_manual   TEXT,
    archivo         TEXT,
    estado          TEXT NOT NULL DEFAULT 'pendiente',
    error           TEXT,
    emitido_por     TEXT NOT NULL,
    creado_en       TEXT NOT NULL,
    enviado_en      TEXT,
    anulado         INTEGER NOT NULL DEFAULT 0,
    anulado_motivo  TEXT,
    validaciones    INTEGER NOT NULL DEFAULT 0,
    ultima_validacion TEXT
);

CREATE INDEX IF NOT EXISTS idx_cert_lote  ON certificados(lote_id);
CREATE INDEX IF NOT EXISTS idx_cert_curso ON certificados(curso_id);
CREATE INDEX IF NOT EXISTS idx_cert_rut   ON certificados(alumno_rut);

CREATE TABLE IF NOT EXISTS config_cursos (
    curso_id       TEXT PRIMARY KEY,
    horas          REAL,
    actualizado_en TEXT
);
"""


def _ahora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _conn():
    settings.CERT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(settings.CERT_DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    with _conn() as conn:
        conn.executescript(_SCHEMA)


def generar_codigo():
    """Código de validación legible e imposible de adivinar: XXXX-XXXX-XXXX."""
    chars = [secrets.choice(_ALFABETO_CODIGO) for _ in range(12)]
    return "-".join("".join(chars[i:i + 4]) for i in range(0, 12, 4))


def _folio_desde_num(num, creado_en):
    anio = (creado_en or _ahora())[:4]
    return f"TP-{anio}-{num:06d}"


# ── Lotes ──────────────────────────────────────────────────


def crear_lote(creado_por, certificados):
    """Crea un lote y sus certificados en estado 'pendiente' (transaccional).

    Parameters
    ----------
    certificados : list[dict]
        Cada dict con: curso_id, curso_nombre, modalidad, alumno_nombre,
        alumno_rut, alumno_email, fecha_inicio, fecha_termino, horas,
        asistencia_pct, calificacion, incluido_manual, motivo_manual.

    Returns
    -------
    str — id del lote creado.
    """
    init_db()
    lote_id = uuid.uuid4().hex[:12]
    ahora = _ahora()
    with _conn() as conn:
        conn.execute(
            "INSERT INTO lotes (id, creado_en, creado_por, estado, total, actualizado_en) "
            "VALUES (?, ?, ?, 'pendiente', ?, ?)",
            (lote_id, ahora, creado_por, len(certificados), ahora),
        )
        for c in certificados:
            cur = conn.execute(
                "INSERT INTO certificados (codigo, lote_id, curso_id, curso_nombre, "
                "modalidad, alumno_nombre, alumno_rut, alumno_email, fecha_inicio, "
                "fecha_termino, horas, asistencia_pct, calificacion, incluido_manual, "
                "motivo_manual, emitido_por, creado_en) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    generar_codigo(), lote_id, str(c["curso_id"]), c["curso_nombre"],
                    c["modalidad"], c["alumno_nombre"], c["alumno_rut"],
                    c.get("alumno_email") or "", c["fecha_inicio"], c["fecha_termino"],
                    float(c["horas"]), c.get("asistencia_pct"), c.get("calificacion"),
                    1 if c.get("incluido_manual") else 0, c.get("motivo_manual") or "",
                    creado_por, ahora,
                ),
            )
            folio = _folio_desde_num(cur.lastrowid, ahora)
            conn.execute(
                "UPDATE certificados SET folio = ? WHERE folio_num = ?",
                (folio, cur.lastrowid),
            )
    logger.info("Lote %s creado por %s con %d certificados", lote_id, creado_por, len(certificados))
    return lote_id


def obtener_lote(lote_id):
    with _conn() as conn:
        row = conn.execute("SELECT * FROM lotes WHERE id = ?", (lote_id,)).fetchone()
        return dict(row) if row else None


def lotes_recientes(limit=20):
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM lotes ORDER BY creado_en DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def actualizar_lote(lote_id, estado=None, procesados=None, errores=None, detalle=None):
    sets, vals = ["actualizado_en = ?"], [_ahora()]
    if estado is not None:
        sets.append("estado = ?")
        vals.append(estado)
    if procesados is not None:
        sets.append("procesados = ?")
        vals.append(procesados)
    if errores is not None:
        sets.append("errores = ?")
        vals.append(errores)
    if detalle is not None:
        sets.append("detalle = ?")
        vals.append(json.dumps(detalle, ensure_ascii=False) if not isinstance(detalle, str) else detalle)
    vals.append(lote_id)
    with _conn() as conn:
        conn.execute(f"UPDATE lotes SET {', '.join(sets)} WHERE id = ?", vals)


# ── Certificados ───────────────────────────────────────────


def certificados_de_lote(lote_id):
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM certificados WHERE lote_id = ? ORDER BY curso_id, alumno_nombre",
            (lote_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def marcar_generado(folio_num, archivo):
    with _conn() as conn:
        conn.execute(
            "UPDATE certificados SET estado = 'generado', archivo = ?, error = NULL "
            "WHERE folio_num = ?",
            (str(archivo), folio_num),
        )


def marcar_enviado(folio_num):
    with _conn() as conn:
        conn.execute(
            "UPDATE certificados SET estado = 'enviado', enviado_en = ?, error = NULL "
            "WHERE folio_num = ?",
            (_ahora(), folio_num),
        )


def marcar_error(folio_num, error):
    with _conn() as conn:
        conn.execute(
            "UPDATE certificados SET estado = 'error', error = ? WHERE folio_num = ?",
            (str(error)[:500], folio_num),
        )


def anular(folio_num, motivo, quien):
    with _conn() as conn:
        conn.execute(
            "UPDATE certificados SET anulado = 1, anulado_motivo = ? WHERE folio_num = ?",
            (f"{motivo} ({quien}, {_ahora()})", folio_num),
        )


def obtener_certificado(folio_num):
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM certificados WHERE folio_num = ?", (folio_num,)
        ).fetchone()
        return dict(row) if row else None


def buscar_por_codigo(codigo):
    """Busca por código de validación (case-insensitive, con o sin guiones).

    Incrementa el contador de validaciones si existe.
    """
    limpio = "".join(ch for ch in (codigo or "").upper() if ch.isalnum())
    if len(limpio) != 12:
        return None
    normalizado = "-".join(limpio[i:i + 4] for i in range(0, 12, 4))
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM certificados WHERE codigo = ?", (normalizado,)
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE certificados SET validaciones = validaciones + 1, "
            "ultima_validacion = ? WHERE folio_num = ?",
            (_ahora(), row["folio_num"]),
        )
        return dict(row)


def listar_registro(q=None, curso_id=None, limit=500):
    """Listado del registro de emisiones para la UI (más recientes primero)."""
    sql = "SELECT * FROM certificados"
    conds, vals = [], []
    if q:
        conds.append("(alumno_nombre LIKE ? OR alumno_rut LIKE ? OR folio LIKE ? OR curso_nombre LIKE ?)")
        patron = f"%{q}%"
        vals += [patron, patron, patron, patron]
    if curso_id:
        conds.append("curso_id = ?")
        vals.append(str(curso_id))
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    sql += " ORDER BY folio_num DESC LIMIT ?"
    vals.append(limit)
    with _conn() as conn:
        return [dict(r) for r in conn.execute(sql, vals).fetchall()]


# ── Configuración de horas por curso ───────────────────────


def get_horas_curso(curso_id):
    init_db()
    with _conn() as conn:
        row = conn.execute(
            "SELECT horas FROM config_cursos WHERE curso_id = ?", (str(curso_id),)
        ).fetchone()
        return row["horas"] if row else None


def set_horas_curso(curso_id, horas):
    with _conn() as conn:
        conn.execute(
            "INSERT INTO config_cursos (curso_id, horas, actualizado_en) VALUES (?, ?, ?) "
            "ON CONFLICT(curso_id) DO UPDATE SET horas = excluded.horas, "
            "actualizado_en = excluded.actualizado_en",
            (str(curso_id), float(horas), _ahora()),
        )

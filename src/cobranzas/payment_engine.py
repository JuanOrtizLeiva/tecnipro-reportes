"""
Motor de Pagos — registro y distribución de ingresos entre facturas.

Flujo:
  1. Usuario ingresa: fecha_pago, monto_total, observacion.
  2. Distribuye el monto entre facturas pendientes/parciales (2026+).
  3. Validaciones:
       a. sum(distribuciones) == monto_total del pago (cuadre exacto).
       b. Cada distribución <= saldo_pendiente de la factura.
       c. Solo facturas 2026+ con estado Pendiente/Parcial reciben pagos.
       d. monto_total > 0.
  4. Se crean registros en `pagos` y `pago_detalle`.
  5. Se recalcula saldo_pendiente y estado de cada factura afectada.
  6. Se registra en log_auditoria.

Invariante financiero crítico:
  Para todo pago registrado: sum(pago_detalle.monto_aplicado) == pagos.monto_total
"""

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone

from config import settings
from src.cobranzas.models import recalcular_saldo, registrar_auditoria

logger = logging.getLogger(__name__)

ANIO_CORTE = settings.ANIO_CORTE_GESTION


# ── Tipos de datos ────────────────────────────────────────────────────────────

@dataclass
class DistribucionItem:
    """Un ítem de distribución de pago: asignar monto a una factura."""
    documento_id: int
    monto_aplicado: int


@dataclass
class ResultadoRegistro:
    """Resultado de intentar registrar un pago."""
    ok: bool
    pago_id: int | None = None
    errores: list[str] = field(default_factory=list)

    def agregar_error(self, msg: str) -> None:
        self.errores.append(msg)


# ── Validaciones ──────────────────────────────────────────────────────────────

def _validar_distribucion(
    conn: sqlite3.Connection,
    monto_total: int,
    distribuciones: list[DistribucionItem],
) -> list[str]:
    """
    Valida la distribución de un pago antes de registrarlo.

    Retorna lista de errores (vacía si todo es válido).
    """
    errores: list[str] = []

    if monto_total <= 0:
        errores.append(f"El monto del pago debe ser positivo, se recibió: {monto_total}")
        return errores  # No continuar

    if not distribuciones:
        errores.append("Debe distribuir el pago en al menos una factura")
        return errores

    suma_dist = sum(d.monto_aplicado for d in distribuciones)
    if suma_dist != monto_total:
        errores.append(
            f"La suma de la distribución (${suma_dist:,}) no coincide con "
            f"el monto total del pago (${monto_total:,}). "
            f"Diferencia: ${abs(monto_total - suma_dist):,}"
        )

    ids_vistos: set[int] = set()
    for dist in distribuciones:
        if dist.monto_aplicado <= 0:
            errores.append(
                f"El monto aplicado a factura id={dist.documento_id} debe ser "
                f"positivo, se recibió: {dist.monto_aplicado}"
            )
            continue

        if dist.documento_id in ids_vistos:
            errores.append(
                f"La factura id={dist.documento_id} aparece duplicada en la distribución"
            )
            continue
        ids_vistos.add(dist.documento_id)

        doc = conn.execute(
            "SELECT id, folio, tipo_doc, estado, saldo_pendiente, fecha_docto "
            "FROM documentos_sii WHERE id = ?",
            (dist.documento_id,),
        ).fetchone()

        if doc is None:
            errores.append(f"Factura id={dist.documento_id} no existe")
            continue

        # Solo facturas (no NC)
        if doc["tipo_doc"] == 61:
            errores.append(
                f"Folio {doc['folio']}: Las notas de crédito no reciben pagos"
            )
            continue

        # Solo documentos activos (2026+)
        try:
            anio_doc = int(str(doc["fecha_docto"])[:4])
        except (ValueError, TypeError):
            anio_doc = 0
        if anio_doc < ANIO_CORTE:
            errores.append(
                f"Folio {doc['folio']}: Las facturas históricas (anteriores a "
                f"{ANIO_CORTE}) no reciben pagos en el sistema"
            )
            continue

        # Solo estados cobrables
        if doc["estado"] not in ("Pendiente", "Parcial"):
            errores.append(
                f"Folio {doc['folio']}: Estado '{doc['estado']}' no permite "
                f"registrar pagos (debe ser Pendiente o Parcial)"
            )
            continue

        # No exceder el saldo pendiente
        if dist.monto_aplicado > doc["saldo_pendiente"]:
            errores.append(
                f"Folio {doc['folio']}: El monto aplicado (${dist.monto_aplicado:,}) "
                f"excede el saldo pendiente (${doc['saldo_pendiente']:,})"
            )

    return errores


# ── Registro de pago ──────────────────────────────────────────────────────────

def registrar_pago(
    conn: sqlite3.Connection,
    fecha_pago: str,          # "YYYY-MM-DD"
    monto_total: int,
    distribuciones: list[DistribucionItem],
    usuario: str,
    observacion: str = "",
    ip: str = "",
) -> ResultadoRegistro:
    """
    Registra un pago y su distribución entre facturas.

    Args:
        conn:           Conexión SQLite (debe estar dentro de una transacción).
        fecha_pago:     Fecha del pago/depósito ("YYYY-MM-DD").
        monto_total:    Monto total recibido en el banco (INTEGER, pesos).
        distribuciones: Lista de DistribucionItem con la distribución del pago.
        usuario:        Email/nombre del usuario que registra.
        observacion:    Texto libre (nro transferencia, banco, etc.).
        ip:             IP del usuario.

    Returns:
        ResultadoRegistro con ok=True y pago_id si todo es correcto,
        o ok=False con lista de errores si hay problemas de validación.
    """
    resultado = ResultadoRegistro(ok=False)

    # Sanitizar observación (strip, máximo 500 chars)
    observacion = observacion.strip()[:500] if observacion else ""

    # ── Validaciones ──────────────────────────────────────────
    errores = _validar_distribucion(conn, monto_total, distribuciones)
    if errores:
        for e in errores:
            resultado.agregar_error(e)
        return resultado

    ahora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    # ── Insertar pago ─────────────────────────────────────────
    cursor = conn.execute(
        """INSERT INTO pagos (fecha_pago, monto_total, observacion, fecha_registro, registrado_por)
           VALUES (?, ?, ?, ?, ?)""",
        (fecha_pago, monto_total, observacion, ahora, usuario),
    )
    pago_id = cursor.lastrowid

    # ── Insertar detalles de distribución ─────────────────────
    for dist in distribuciones:
        conn.execute(
            """INSERT INTO pago_detalle (pago_id, documento_id, monto_aplicado, fecha_aplicacion)
               VALUES (?, ?, ?, ?)""",
            (pago_id, dist.documento_id, dist.monto_aplicado, ahora),
        )

    # ── Recalcular saldo de cada factura afectada ─────────────
    for dist in distribuciones:
        recalcular_saldo(conn, dist.documento_id)

    # ── Auditoría ─────────────────────────────────────────────
    folios = []
    for dist in distribuciones:
        doc = conn.execute(
            "SELECT folio FROM documentos_sii WHERE id = ?", (dist.documento_id,)
        ).fetchone()
        if doc:
            folios.append(f"folio {doc['folio']} (${dist.monto_aplicado:,})")

    registrar_auditoria(
        conn, usuario, "registrar_pago",
        f"Pago id={pago_id} por ${monto_total:,} el {fecha_pago}. "
        f"Distribuido en: {', '.join(folios)}. Obs: {observacion[:100]}",
        ip,
    )

    resultado.ok = True
    resultado.pago_id = pago_id
    logger.info(
        "Pago id=%d registrado por %s: $%d en %d facturas",
        pago_id, usuario, monto_total, len(distribuciones),
    )
    return resultado


# ── Anulación de pago ─────────────────────────────────────────────────────────

def anular_pago(
    conn: sqlite3.Connection,
    pago_id: int,
    usuario: str,
    ip: str = "",
) -> dict:
    """
    Anula un pago: elimina su distribución y recalcula los saldos afectados.

    Esta operación es reversible en el sentido de que restaura el estado previo
    de las facturas. Sin embargo, el registro de auditoría queda permanente.

    Returns:
        {"ok": bool, "error": str | None, "facturas_afectadas": int}
    """
    pago = conn.execute("SELECT * FROM pagos WHERE id = ?", (pago_id,)).fetchone()
    if pago is None:
        return {"ok": False, "error": f"Pago id={pago_id} no encontrado"}

    # Obtener facturas afectadas antes de eliminar
    detalles = conn.execute(
        "SELECT documento_id, monto_aplicado FROM pago_detalle WHERE pago_id = ?",
        (pago_id,),
    ).fetchall()
    ids_afectados = [d["documento_id"] for d in detalles]

    # Auditoría antes de eliminar
    registrar_auditoria(
        conn, usuario, "anular_pago",
        f"Anulado pago id={pago_id} de ${pago['monto_total']:,} del {pago['fecha_pago']}. "
        f"Afectaba {len(ids_afectados)} facturas.",
        ip,
    )

    # Eliminar detalles y pago (cascade elimina pago_detalle)
    conn.execute("DELETE FROM pagos WHERE id = ?", (pago_id,))

    # Recalcular saldo de todas las facturas que estaban en este pago
    for doc_id in ids_afectados:
        recalcular_saldo(conn, doc_id)

    logger.info(
        "Pago id=%d anulado por %s. %d facturas recalculadas.",
        pago_id, usuario, len(ids_afectados),
    )
    return {"ok": True, "error": None, "facturas_afectadas": len(ids_afectados)}


# ── Consultas ─────────────────────────────────────────────────────────────────

def obtener_pago_con_detalle(conn: sqlite3.Connection, pago_id: int) -> dict | None:
    """
    Retorna un pago completo con el detalle de su distribución.

    Returns None si el pago no existe.
    """
    pago = conn.execute("SELECT * FROM pagos WHERE id = ?", (pago_id,)).fetchone()
    if pago is None:
        return None

    detalles = conn.execute(
        """SELECT pd.monto_aplicado, pd.fecha_aplicacion,
                  d.folio, d.razon_social, d.tipo_doc, d.fecha_docto,
                  d.monto_total, d.saldo_pendiente, d.estado,
                  c.nombre AS cliente_nombre
           FROM pago_detalle pd
           JOIN documentos_sii d ON pd.documento_id = d.id
           LEFT JOIN clientes c  ON d.cliente_id     = c.id
           WHERE pd.pago_id = ?
           ORDER BY d.folio""",
        (pago_id,),
    ).fetchall()

    return {
        "id":             pago["id"],
        "fecha_pago":     pago["fecha_pago"],
        "monto_total":    pago["monto_total"],
        "observacion":    pago["observacion"],
        "fecha_registro": pago["fecha_registro"],
        "registrado_por": pago["registrado_por"],
        "distribuciones": [dict(d) for d in detalles],
    }


def listar_pagos(
    conn: sqlite3.Connection,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """
    Lista pagos paginados, ordenados por fecha descendente.

    Returns:
        {"total": int, "pagos": list[dict]}
    """
    total = conn.execute("SELECT COUNT(*) FROM pagos").fetchone()[0]
    rows = conn.execute(
        """SELECT p.*,
                  COUNT(pd.id) AS num_facturas
           FROM pagos p
           LEFT JOIN pago_detalle pd ON p.id = pd.pago_id
           GROUP BY p.id
           ORDER BY p.fecha_pago DESC, p.id DESC
           LIMIT ? OFFSET ?""",
        (limit, offset),
    ).fetchall()
    return {
        "total": total,
        "pagos": [dict(r) for r in rows],
    }


def listar_pagos_por_factura(
    conn: sqlite3.Connection, documento_id: int
) -> list[dict]:
    """Lista todos los pagos aplicados a una factura específica."""
    rows = conn.execute(
        """SELECT pd.monto_aplicado, pd.fecha_aplicacion,
                  p.id AS pago_id, p.fecha_pago, p.observacion, p.registrado_por
           FROM pago_detalle pd
           JOIN pagos p ON pd.pago_id = p.id
           WHERE pd.documento_id = ?
           ORDER BY p.fecha_pago ASC""",
        (documento_id,),
    ).fetchall()
    return [dict(r) for r in rows]

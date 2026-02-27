"""
Motor de Notas de Crédito (NC) — asociación automática a facturas.

Lógica de negocio:
  - Una NC (tipo_doc=61) referencia una factura mediante folio_referencia + tipo_doc_referencia.
  - Al aplicar una NC sobre su factura, se reduce el saldo_pendiente de la factura.
  - Si saldo_pendiente queda en 0 → factura "Pagada".
  - Si saldo_pendiente queda negativo (NC > monto factura) → factura "Anulada", saldo=0.
  - Si la factura referenciada no existe en la BD → NC queda "sin asociar" para revisión.
  - Solo facturas 2026+ reciben actualización de saldo; facturas históricas quedan intactas.

Punto de entrada principal:
    aplicar_todas_ncs(conn) — llamar tras cualquier importación de CSV.
"""

import logging
import sqlite3

from config import settings
from src.cobranzas.models import recalcular_saldo, registrar_auditoria

logger = logging.getLogger(__name__)

ANIO_CORTE = settings.ANIO_CORTE_GESTION


# ── Búsqueda de factura referenciada ─────────────────────────────────────────

def _buscar_factura_ref(
    conn: sqlite3.Connection,
    folio_ref: int,
    tipo_doc_ref: int | None,
) -> sqlite3.Row | None:
    """
    Busca la factura (tipo 33 o 34) referenciada por una NC.

    Prioridad:
      1. Si tipo_doc_ref está disponible: buscar por (tipo_doc, folio) exacto.
      2. Si no: buscar cualquier factura con ese folio (tipo 33 o 34).
    """
    if tipo_doc_ref is not None and tipo_doc_ref in (33, 34):
        return conn.execute(
            "SELECT * FROM documentos_sii WHERE tipo_doc = ? AND folio = ?",
            (tipo_doc_ref, folio_ref),
        ).fetchone()
    # Fallback: buscar entre facturas
    return conn.execute(
        "SELECT * FROM documentos_sii WHERE folio = ? AND tipo_doc IN (33, 34)",
        (folio_ref,),
    ).fetchone()


# ── Aplicación individual ─────────────────────────────────────────────────────

def aplicar_nc(
    conn: sqlite3.Connection,
    nc_id: int,
    usuario: str = "sistema",
    ip: str = "",
) -> dict:
    """
    Aplica una Nota de Crédito a su factura referenciada.

    Returns:
        {
            "nc_folio": int,
            "nc_monto": int,
            "resultado": "aplicada" | "sin_referencia" | "factura_no_encontrada" |
                         "historica_ignorada" | "ya_anulada",
            "factura_folio": int | None,
            "factura_nuevo_estado": str | None,
        }
    """
    nc = conn.execute(
        "SELECT * FROM documentos_sii WHERE id = ? AND tipo_doc = 61",
        (nc_id,),
    ).fetchone()
    if nc is None:
        return {"resultado": "nc_no_encontrada", "nc_id": nc_id}

    resultado = {
        "nc_folio": nc["folio"],
        "nc_monto": nc["monto_total"],
        "factura_folio": None,
        "factura_nuevo_estado": None,
    }

    # NC sin referencia → no se puede aplicar automáticamente
    if not nc["folio_referencia"]:
        resultado["resultado"] = "sin_referencia"
        logger.warning(
            "NC folio=%d sin folio_referencia — revisión manual requerida", nc["folio"]
        )
        return resultado

    factura = _buscar_factura_ref(conn, nc["folio_referencia"], nc["tipo_doc_referencia"])
    if factura is None:
        resultado["resultado"] = "factura_no_encontrada"
        logger.warning(
            "NC folio=%d referencia factura folio=%d que no existe en la BD",
            nc["folio"], nc["folio_referencia"],
        )
        return resultado

    resultado["factura_folio"] = factura["folio"]

    # Solo actualizar facturas activas (2026+); históricas ya están marcadas "Pagada"
    try:
        anio_factura = int(str(factura["fecha_docto"])[:4])
    except (ValueError, TypeError):
        anio_factura = 0

    if anio_factura < ANIO_CORTE:
        resultado["resultado"] = "historica_ignorada"
        return resultado

    if factura["estado"] == "Anulada":
        resultado["resultado"] = "ya_anulada"
        resultado["factura_nuevo_estado"] = "Anulada"
        return resultado

    # Calcular saldo considerando TODOS los pagos y TODAS las NC de la factura
    pagos_sum = conn.execute(
        "SELECT COALESCE(SUM(monto_aplicado), 0) FROM pago_detalle WHERE documento_id = ?",
        (factura["id"],),
    ).fetchone()[0]

    nc_sum = conn.execute(
        """SELECT COALESCE(SUM(nc2.monto_total), 0)
           FROM documentos_sii nc2
           JOIN documentos_sii fact
             ON nc2.folio_referencia    = fact.folio
            AND nc2.tipo_doc_referencia = fact.tipo_doc
           WHERE nc2.tipo_doc = 61 AND fact.id = ?""",
        (factura["id"],),
    ).fetchone()[0]

    saldo_nuevo = factura["monto_total"] - pagos_sum - nc_sum

    if saldo_nuevo <= 0:
        nuevo_estado = "Anulada"
        saldo_final = 0
    elif pagos_sum > 0:
        nuevo_estado = "Parcial"
        saldo_final = saldo_nuevo
    else:
        nuevo_estado = "Pendiente"
        saldo_final = saldo_nuevo

    conn.execute(
        "UPDATE documentos_sii SET saldo_pendiente = ?, estado = ? WHERE id = ?",
        (saldo_final, nuevo_estado, factura["id"]),
    )

    resultado["resultado"] = "aplicada"
    resultado["factura_nuevo_estado"] = nuevo_estado

    registrar_auditoria(
        conn, usuario, "aplicar_nc",
        f"NC folio={nc['folio']} (${nc['monto_total']:,}) aplicada a factura folio={factura['folio']} → {nuevo_estado}",
        ip,
    )
    logger.info(
        "NC folio=%d ($%d) aplicada a factura folio=%d → %s (saldo=$%d)",
        nc["folio"], nc["monto_total"], factura["folio"], nuevo_estado, saldo_final,
    )
    return resultado


# ── Aplicación masiva ─────────────────────────────────────────────────────────

def aplicar_todas_ncs(
    conn: sqlite3.Connection,
    usuario: str = "sistema",
    ip: str = "",
) -> dict:
    """
    Aplica TODAS las notas de crédito de la BD a sus facturas referenciadas.

    Llama a `aplicar_nc` para cada NC que tenga folio_referencia.
    Es idempotente: las NCs ya aplicadas producen el mismo resultado final
    porque `recalcular_saldo` siempre suma todas las NC activas.

    Returns:
        {
            "aplicadas": int,
            "sin_referencia": int,
            "factura_no_encontrada": int,
            "historicas_ignoradas": int,
            "ya_anuladas": int,
            "detalles": list[dict],
        }
    }
    """
    ncs = conn.execute(
        "SELECT id FROM documentos_sii WHERE tipo_doc = 61 ORDER BY fecha_docto"
    ).fetchall()

    conteo = {
        "aplicadas": 0,
        "sin_referencia": 0,
        "factura_no_encontrada": 0,
        "historicas_ignoradas": 0,
        "ya_anuladas": 0,
        "detalles": [],
    }

    for row in ncs:
        res = aplicar_nc(conn, row["id"], usuario=usuario, ip=ip)
        estado = res.get("resultado", "desconocido")
        if estado == "aplicada":
            conteo["aplicadas"] += 1
        elif estado == "sin_referencia":
            conteo["sin_referencia"] += 1
        elif estado == "factura_no_encontrada":
            conteo["factura_no_encontrada"] += 1
            conteo["detalles"].append(res)
        elif estado == "historica_ignorada":
            conteo["historicas_ignoradas"] += 1
        elif estado == "ya_anulada":
            conteo["ya_anuladas"] += 1

    logger.info(
        "Aplicación masiva de NC: %d aplicadas, %d sin referencia, "
        "%d factura no encontrada, %d históricas ignoradas",
        conteo["aplicadas"], conteo["sin_referencia"],
        conteo["factura_no_encontrada"], conteo["historicas_ignoradas"],
    )
    return conteo


# ── Consulta: NCs sin asociar ─────────────────────────────────────────────────

def listar_ncs_sin_asociar(conn: sqlite3.Connection) -> list[dict]:
    """
    Lista las NC que no pudieron asociarse a ninguna factura.

    Una NC "sin asociar" es aquella con folio_referencia cuya factura no existe en la BD.
    Útil para mostrar al usuario qué NCs requieren revisión manual.
    """
    rows = conn.execute(
        """SELECT nc.*
           FROM documentos_sii nc
           WHERE nc.tipo_doc = 61
             AND nc.folio_referencia IS NOT NULL
             AND NOT EXISTS (
                 SELECT 1 FROM documentos_sii fact
                 WHERE fact.folio    = nc.folio_referencia
                   AND fact.tipo_doc IN (33, 34)
             )
           ORDER BY nc.fecha_docto DESC"""
    ).fetchall()
    return [dict(r) for r in rows]

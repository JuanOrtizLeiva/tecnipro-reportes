"""
Motor de Estadísticas — cálculos para el dashboard de cobranzas.

Separación temporal según CLAUDE-cobranzas.md:
  - "Históricas" (todos los años): facturación, tendencia, por OTIC.
  - "Cobranzas Activas" (solo 2026+): KPIs de cobro, estados, alertas.
  - "Por Cliente y Curso" (solo 2026+ con cliente asignado): análisis detallado.

Todos los montos retornados son INTEGER (pesos chilenos, sin decimales).
Todas las funciones reciben una conexión SQLite abierta.
Los dicts retornados son JSON-serializables (no contienen sqlite3.Row).

Uso típico desde una ruta Flask:
    with get_db() as conn:
        data = kpis_cobranza(conn)
    return jsonify(data)
"""

import logging
import sqlite3

from config import settings

logger = logging.getLogger(__name__)

ANIO_CORTE = settings.ANIO_CORTE_GESTION


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _rows_to_list(rows) -> list[dict]:
    return [dict(r) for r in rows]


def _safe_pct(numerador: int, denominador: int) -> float:
    """Porcentaje redondeado a 1 decimal. 0 si denominador == 0."""
    if not denominador:
        return 0.0
    return round(100 * numerador / denominador, 1)


# ─── 1. Resumen Histórico (todos los años) ────────────────────────────────────

def resumen_historico(conn: sqlite3.Connection) -> dict:
    """
    Facturación bruta por año y mes, para todos los años disponibles.

    Incluye facturas (tipo 33 y 34) y NC (tipo 61) para calcular neto.
    NO incluye saldos ni pagos (datos históricos se asumen cobrados).

    Returns:
        {
            "por_anio": [
                {
                    "anio": 2022,
                    "monto_bruto": 120000000,
                    "monto_nc": 5000000,
                    "monto_neto": 115000000,
                    "num_facturas": 45,
                    "num_nc": 3,
                }
            ],
            "por_mes": [
                {"periodo": "2022-02", "anio": 2022, "mes": 2,
                 "monto_bruto": 12000000, "monto_nc": 0, "num_facturas": 5}
            ],
            "total_historico": 573163497,
            "total_nc_historico": 12000000,
            "anios_disponibles": [2022, 2023, 2024, 2025, 2026],
        }
    """
    # Facturación bruta por año
    por_anio_fact = conn.execute(
        """SELECT
               CAST(strftime('%Y', fecha_docto) AS INTEGER) AS anio,
               COUNT(*)                                      AS num_facturas,
               COALESCE(SUM(monto_total), 0)                AS monto_bruto
           FROM documentos_sii
           WHERE tipo_doc IN (33, 34)
           GROUP BY anio
           ORDER BY anio"""
    ).fetchall()

    # NC por año
    por_anio_nc = conn.execute(
        """SELECT
               CAST(strftime('%Y', fecha_docto) AS INTEGER) AS anio,
               COUNT(*)                                      AS num_nc,
               COALESCE(SUM(monto_total), 0)                AS monto_nc
           FROM documentos_sii
           WHERE tipo_doc = 61
           GROUP BY anio
           ORDER BY anio"""
    ).fetchall()

    # Indexar NC por año
    nc_por_anio: dict[int, dict] = {
        r["anio"]: {"num_nc": r["num_nc"], "monto_nc": r["monto_nc"]}
        for r in por_anio_nc
    }

    por_anio = []
    for r in por_anio_fact:
        anio = r["anio"]
        nc = nc_por_anio.get(anio, {"num_nc": 0, "monto_nc": 0})
        por_anio.append({
            "anio":         anio,
            "monto_bruto":  r["monto_bruto"],
            "monto_nc":     nc["monto_nc"],
            "monto_neto":   r["monto_bruto"] - nc["monto_nc"],
            "num_facturas": r["num_facturas"],
            "num_nc":       nc["num_nc"],
        })

    # Facturación por mes (todos los años)
    por_mes_rows = conn.execute(
        """SELECT
               strftime('%Y-%m', fecha_docto)              AS periodo,
               CAST(strftime('%Y', fecha_docto) AS INTEGER) AS anio,
               CAST(strftime('%m', fecha_docto) AS INTEGER) AS mes,
               COUNT(*)                                      AS num_facturas,
               COALESCE(SUM(monto_total), 0)                AS monto_bruto
           FROM documentos_sii
           WHERE tipo_doc IN (33, 34)
           GROUP BY periodo
           ORDER BY periodo"""
    ).fetchall()

    por_mes = [dict(r) for r in por_mes_rows]

    total_hist = sum(a["monto_bruto"] for a in por_anio)
    total_nc   = sum(a["monto_nc"]    for a in por_anio)

    return {
        "por_anio":            por_anio,
        "por_mes":             por_mes,
        "total_historico":     total_hist,
        "total_nc_historico":  total_nc,
        "anios_disponibles":   [a["anio"] for a in por_anio],
    }


def facturacion_por_otic(
    conn: sqlite3.Connection,
    anio: int | None = None,
) -> list[dict]:
    """
    Facturación bruta por OTIC (razón social del receptor), ordenada de mayor a menor.

    Args:
        anio: Si se especifica, filtra por ese año. Si None, todos los años.

    Returns:
        [{"rut_cliente": ..., "razon_social": ..., "monto_total": ...,
          "num_facturas": ..., "monto_nc": ...}, ...]
    """
    where = "WHERE f.tipo_doc IN (33, 34)"
    params: list = []
    if anio is not None:
        where += " AND strftime('%Y', f.fecha_docto) = ?"
        params.append(str(anio))

    rows = conn.execute(
        f"""SELECT
               f.rut_cliente,
               f.razon_social,
               COUNT(f.id)                   AS num_facturas,
               COALESCE(SUM(f.monto_total), 0) AS monto_bruto
            FROM documentos_sii f
            {where}
            GROUP BY f.rut_cliente
            ORDER BY monto_bruto DESC""",
        params,
    ).fetchall()

    # Añadir NC por OTIC
    nc_where = "WHERE nc.tipo_doc = 61"
    nc_params: list = []
    if anio is not None:
        nc_where += " AND strftime('%Y', nc.fecha_docto) = ?"
        nc_params.append(str(anio))

    nc_rows = conn.execute(
        f"""SELECT rut_cliente, COALESCE(SUM(monto_total), 0) AS monto_nc
            FROM documentos_sii nc {nc_where} GROUP BY rut_cliente""",
        nc_params,
    ).fetchall()
    nc_map = {r["rut_cliente"]: r["monto_nc"] for r in nc_rows}

    result = []
    for r in rows:
        nc = nc_map.get(r["rut_cliente"], 0)
        result.append({
            "rut_cliente":   r["rut_cliente"],
            "razon_social":  r["razon_social"],
            "num_facturas":  r["num_facturas"],
            "monto_bruto":   r["monto_bruto"],
            "monto_nc":      nc,
            "monto_neto":    r["monto_bruto"] - nc,
        })
    return result


# ─── 2. KPIs de Cobranza Activa (solo 2026+) ──────────────────────────────────

def kpis_cobranza(conn: sqlite3.Connection) -> dict:
    """
    KPIs principales para el panel de cobranzas activas (facturas 2026+).

    Returns:
        {
            "total_facturado":   int,
            "total_cobrado":     int,
            "total_pendiente":   int,
            "pct_recuperacion":  float,   # %
            "num_facturas":      int,
            "num_pendientes":    int,
            "num_parciales":     int,
            "num_pagadas":       int,
            "num_anuladas":      int,
            "monto_nc_aplicado": int,
        }
    """
    anio_str = str(ANIO_CORTE)

    row = conn.execute(
        """SELECT
               COUNT(*)                                                    AS num_facturas,
               COALESCE(SUM(monto_total), 0)                              AS total_facturado,
               COALESCE(SUM(saldo_pendiente), 0)                          AS total_pendiente,
               COALESCE(SUM(CASE WHEN estado = 'Pendiente' THEN 1 ELSE 0 END), 0) AS num_pendientes,
               COALESCE(SUM(CASE WHEN estado = 'Parcial'   THEN 1 ELSE 0 END), 0) AS num_parciales,
               COALESCE(SUM(CASE WHEN estado = 'Pagada'    THEN 1 ELSE 0 END), 0) AS num_pagadas,
               COALESCE(SUM(CASE WHEN estado = 'Anulada'   THEN 1 ELSE 0 END), 0) AS num_anuladas
           FROM documentos_sii
           WHERE tipo_doc IN (33, 34)
             AND strftime('%Y', fecha_docto) >= ?""",
        (anio_str,),
    ).fetchone()

    total_facturado = row["total_facturado"]
    total_pendiente = row["total_pendiente"]
    total_cobrado   = total_facturado - total_pendiente

    # NC aplicadas en el período activo
    monto_nc = conn.execute(
        """SELECT COALESCE(SUM(monto_total), 0)
           FROM documentos_sii
           WHERE tipo_doc = 61
             AND strftime('%Y', fecha_docto) >= ?""",
        (anio_str,),
    ).fetchone()[0]

    # Días promedio de cobro (facturas ya pagadas)
    dias_prom = conn.execute(
        """SELECT COALESCE(AVG(dias_cobro), 0) AS dias_prom
           FROM (
               SELECT julianday(MAX(p.fecha_pago)) - julianday(d.fecha_docto) AS dias_cobro
               FROM documentos_sii d
               JOIN pago_detalle pd ON pd.documento_id = d.id
               JOIN pagos p         ON pd.pago_id      = p.id
               WHERE d.estado = 'Pagada'
                 AND d.tipo_doc IN (33, 34)
                 AND strftime('%Y', d.fecha_docto) >= ?
               GROUP BY d.id
           )""",
        (anio_str,),
    ).fetchone()[0]

    return {
        "total_facturado":   total_facturado,
        "total_cobrado":     total_cobrado,
        "total_pendiente":   total_pendiente,
        "pct_recuperacion":  _safe_pct(total_cobrado, total_facturado),
        "num_facturas":      row["num_facturas"],
        "num_pendientes":    row["num_pendientes"],
        "num_parciales":     row["num_parciales"],
        "num_pagadas":       row["num_pagadas"],
        "num_anuladas":      row["num_anuladas"],
        "monto_nc_aplicado": monto_nc,
        "dias_promedio_cobro": round(dias_prom, 1),
    }


def distribucion_estados(conn: sqlite3.Connection) -> list[dict]:
    """
    Distribución de facturas 2026+ por estado (para gráfico de torta/donut).

    Returns:
        [{"estado": "Pendiente", "cantidad": 5, "monto": 12000000}, ...]
    """
    anio_str = str(ANIO_CORTE)
    rows = conn.execute(
        """SELECT estado,
                  COUNT(*)                   AS cantidad,
                  COALESCE(SUM(monto_total), 0) AS monto
           FROM documentos_sii
           WHERE tipo_doc IN (33, 34)
             AND strftime('%Y', fecha_docto) >= ?
           GROUP BY estado
           ORDER BY CASE estado
               WHEN 'Pendiente' THEN 1
               WHEN 'Parcial'   THEN 2
               WHEN 'Pagada'    THEN 3
               WHEN 'Anulada'   THEN 4
               ELSE 5 END""",
        (anio_str,),
    ).fetchall()
    return _rows_to_list(rows)


def cobranza_mensual(conn: sqlite3.Connection) -> list[dict]:
    """
    Comparativo mensual: facturación emitida vs. monto cobrado (2026+).

    Returns:
        [{"periodo": "2026-01", "facturado": 15000000, "cobrado": 8000000,
          "pendiente": 7000000}, ...]
    """
    anio_str = str(ANIO_CORTE)

    # Facturado por mes
    fact_rows = conn.execute(
        """SELECT strftime('%Y-%m', fecha_docto)   AS periodo,
                  COALESCE(SUM(monto_total), 0)    AS facturado,
                  COALESCE(SUM(saldo_pendiente), 0) AS pendiente
           FROM documentos_sii
           WHERE tipo_doc IN (33, 34)
             AND strftime('%Y', fecha_docto) >= ?
           GROUP BY periodo
           ORDER BY periodo""",
        (anio_str,),
    ).fetchall()

    # Cobrado por mes de la FACTURA (no del pago) — permite comparar
    # "lo que se facturó en ese mes" vs "lo que se cobró de ese mes"
    cobrado_rows = conn.execute(
        """SELECT strftime('%Y-%m', d.fecha_docto) AS periodo,
                  COALESCE(SUM(pd.monto_aplicado), 0) AS cobrado
           FROM pago_detalle pd
           JOIN documentos_sii d ON pd.documento_id = d.id
           WHERE strftime('%Y', d.fecha_docto) >= ?
           GROUP BY periodo
           ORDER BY periodo""",
        (anio_str,),
    ).fetchall()
    cobrado_map = {r["periodo"]: r["cobrado"] for r in cobrado_rows}

    result = []
    for r in fact_rows:
        periodo = r["periodo"]
        result.append({
            "periodo":   periodo,
            "facturado": r["facturado"],
            "cobrado":   cobrado_map.get(periodo, 0),
            "pendiente": r["pendiente"],
        })
    return result


def top_otics_pendientes(conn: sqlite3.Connection, limite: int = 5) -> list[dict]:
    """
    Top N OTICs con mayor monto pendiente (facturas 2026+).

    Returns:
        [{"rut_cliente": ..., "razon_social": ..., "saldo_pendiente": ...,
          "num_facturas_pendientes": ...}, ...]
    """
    anio_str = str(ANIO_CORTE)
    rows = conn.execute(
        """SELECT rut_cliente, razon_social,
                  COUNT(*)                        AS num_facturas_pendientes,
                  COALESCE(SUM(saldo_pendiente), 0) AS saldo_total_pendiente
           FROM documentos_sii
           WHERE tipo_doc IN (33, 34)
             AND estado IN ('Pendiente', 'Parcial')
             AND strftime('%Y', fecha_docto) >= ?
           GROUP BY rut_cliente
           ORDER BY saldo_total_pendiente DESC
           LIMIT ?""",
        (anio_str, limite),
    ).fetchall()
    return _rows_to_list(rows)


# ─── 3. Alertas de vencimiento (2026+) ────────────────────────────────────────

def alertas_vencimiento(conn: sqlite3.Connection) -> dict:
    """
    Facturas 2026+ sin pago total clasificadas por antigüedad.

    Returns:
        {
            "mas_de_90_dias": [{"folio": ..., "razon_social": ..., "saldo_pendiente": ..., "dias": ...}],
            "entre_60_90":    [...],
            "entre_30_60":    [...],
            "menos_de_30":    [...],
            "total_critico":  int,   # Monto total > 90 días
        }
    """
    anio_str = str(ANIO_CORTE)
    rows = conn.execute(
        """SELECT
               d.id, d.folio, d.razon_social, d.fecha_docto,
               d.monto_total, d.saldo_pendiente, d.estado,
               c.nombre AS cliente_nombre,
               CAST(julianday('now') - julianday(d.fecha_docto) AS INTEGER) AS dias_transcurridos
           FROM documentos_sii d
           LEFT JOIN clientes c ON d.cliente_id = c.id
           WHERE d.tipo_doc IN (33, 34)
             AND d.estado IN ('Pendiente', 'Parcial')
             AND strftime('%Y', d.fecha_docto) >= ?
           ORDER BY dias_transcurridos DESC""",
        (anio_str,),
    ).fetchall()

    buckets: dict[str, list[dict]] = {
        "mas_de_90_dias": [],
        "entre_60_90":    [],
        "entre_30_60":    [],
        "menos_de_30":    [],
    }

    for r in rows:
        dias = r["dias_transcurridos"] or 0
        item = {
            "id":              r["id"],
            "folio":           r["folio"],
            "razon_social":    r["razon_social"],
            "cliente_nombre":  r["cliente_nombre"],
            "fecha_docto":     r["fecha_docto"],
            "monto_total":     r["monto_total"],
            "saldo_pendiente": r["saldo_pendiente"],
            "estado":          r["estado"],
            "dias":            dias,
        }
        if dias > 90:
            buckets["mas_de_90_dias"].append(item)
        elif dias > 60:
            buckets["entre_60_90"].append(item)
        elif dias > 30:
            buckets["entre_30_60"].append(item)
        else:
            buckets["menos_de_30"].append(item)

    total_critico = sum(
        item["saldo_pendiente"] for item in buckets["mas_de_90_dias"]
    )
    return {**buckets, "total_critico": total_critico}


# ─── 4. Análisis por Cliente y Curso (solo 2026+) ─────────────────────────────

def top_clientes(conn: sqlite3.Connection, limite: int = 10) -> list[dict]:
    """
    Top clientes reales por facturación (2026+).

    Solo incluye facturas con cliente asignado.

    Returns:
        [{"cliente_id": ..., "nombre": ..., "total_facturado": ...,
          "total_cobrado": ..., "total_pendiente": ..., "num_facturas": ...}, ...]
    """
    anio_str = str(ANIO_CORTE)
    rows = conn.execute(
        """SELECT
               c.id   AS cliente_id,
               c.nombre,
               COUNT(d.id)                              AS num_facturas,
               COALESCE(SUM(d.monto_total), 0)          AS total_facturado,
               COALESCE(SUM(d.saldo_pendiente), 0)      AS total_pendiente
           FROM clientes c
           JOIN documentos_sii d ON c.id = d.cliente_id
           WHERE d.tipo_doc IN (33, 34)
             AND strftime('%Y', d.fecha_docto) >= ?
           GROUP BY c.id
           ORDER BY total_facturado DESC
           LIMIT ?""",
        (anio_str, limite),
    ).fetchall()

    result = []
    for r in rows:
        total_facturado = r["total_facturado"]
        total_pendiente = r["total_pendiente"]
        result.append({
            "cliente_id":     r["cliente_id"],
            "nombre":         r["nombre"],
            "num_facturas":   r["num_facturas"],
            "total_facturado": total_facturado,
            "total_cobrado":   total_facturado - total_pendiente,
            "total_pendiente": total_pendiente,
            "pct_cobrado":    _safe_pct(total_facturado - total_pendiente, total_facturado),
        })
    return result


def top_cursos(conn: sqlite3.Connection, limite: int = 10) -> list[dict]:
    """
    Top cursos por facturación (2026+, solo facturas con curso asignado).

    Returns:
        [{"curso": ..., "total_facturado": ..., "num_facturas": ...,
          "num_clientes_distintos": ...}, ...]
    """
    anio_str = str(ANIO_CORTE)
    rows = conn.execute(
        """SELECT
               curso,
               COUNT(*)                              AS num_facturas,
               COALESCE(SUM(monto_total), 0)         AS total_facturado,
               COUNT(DISTINCT cliente_id)            AS num_clientes_distintos
           FROM documentos_sii
           WHERE tipo_doc IN (33, 34)
             AND curso IS NOT NULL
             AND curso != ''
             AND strftime('%Y', fecha_docto) >= ?
           GROUP BY curso
           ORDER BY total_facturado DESC
           LIMIT ?""",
        (anio_str, limite),
    ).fetchall()
    return _rows_to_list(rows)


def facturacion_por_cliente_detalle(
    conn: sqlite3.Connection,
    cliente_id: int,
) -> dict:
    """
    Detalle de facturación de un cliente específico (2026+).

    Returns:
        {
            "cliente": dict,
            "por_mes": [{"periodo": ..., "facturado": ..., "cobrado": ...}],
            "por_curso": [{"curso": ..., "facturado": ..., "cobrado": ...}],
            "facturas": [dict, ...],
        }
    """
    anio_str = str(ANIO_CORTE)

    cliente = conn.execute(
        "SELECT * FROM clientes WHERE id = ?", (cliente_id,)
    ).fetchone()
    if cliente is None:
        return {}

    por_mes = conn.execute(
        """SELECT
               strftime('%Y-%m', fecha_docto) AS periodo,
               COALESCE(SUM(monto_total), 0)   AS facturado,
               COALESCE(SUM(monto_total) - SUM(saldo_pendiente), 0) AS cobrado
           FROM documentos_sii
           WHERE cliente_id = ? AND tipo_doc IN (33, 34)
             AND strftime('%Y', fecha_docto) >= ?
           GROUP BY periodo ORDER BY periodo""",
        (cliente_id, anio_str),
    ).fetchall()

    por_curso = conn.execute(
        """SELECT
               COALESCE(curso, '(sin asignar)') AS curso,
               COALESCE(SUM(monto_total), 0)    AS facturado,
               COALESCE(SUM(monto_total) - SUM(saldo_pendiente), 0) AS cobrado,
               COUNT(*)                          AS num_facturas
           FROM documentos_sii
           WHERE cliente_id = ? AND tipo_doc IN (33, 34)
             AND strftime('%Y', fecha_docto) >= ?
           GROUP BY curso ORDER BY facturado DESC""",
        (cliente_id, anio_str),
    ).fetchall()

    facturas = conn.execute(
        """SELECT d.*, nc_agg.monto_nc
           FROM documentos_sii d
           LEFT JOIN (
               SELECT nc.folio_referencia, nc.tipo_doc_referencia,
                      COALESCE(SUM(nc.monto_total), 0) AS monto_nc
               FROM documentos_sii nc
               WHERE nc.tipo_doc = 61
               GROUP BY nc.folio_referencia, nc.tipo_doc_referencia
           ) nc_agg ON nc_agg.folio_referencia = d.folio
                   AND nc_agg.tipo_doc_referencia = d.tipo_doc
           WHERE d.cliente_id = ? AND d.tipo_doc IN (33, 34)
             AND strftime('%Y', d.fecha_docto) >= ?
           ORDER BY d.fecha_docto DESC""",
        (cliente_id, anio_str),
    ).fetchall()

    return {
        "cliente":   dict(cliente),
        "por_mes":   _rows_to_list(por_mes),
        "por_curso": _rows_to_list(por_curso),
        "facturas":  _rows_to_list(facturas),
    }


def resumen_dashboard(conn: sqlite3.Connection) -> dict:
    """
    Función consolidada que retorna todos los datos del dashboard en una sola llamada.

    Útil para cargar el dashboard con un solo request al backend.
    """
    return {
        "historico":          resumen_historico(conn),
        "por_otic_historico": facturacion_por_otic(conn),
        "kpis":               kpis_cobranza(conn),
        "estados":            distribucion_estados(conn),
        "cobranza_mensual":   cobranza_mensual(conn),
        "top_otics":          top_otics_pendientes(conn),
        "alertas":            alertas_vencimiento(conn),
        "top_clientes":       top_clientes(conn),
        "top_cursos":         top_cursos(conn),
    }

"""
Rutas Flask del módulo de Cobranzas — Acceso exclusivo a administradores.

HTML pages:
    GET  /cobranzas/             → Dashboard (3 pestañas)
    GET  /cobranzas/facturas     → Listado de facturas
    GET  /cobranzas/pagos        → Registro y listado de pagos
    GET  /cobranzas/clientes     → Catálogo de clientes
    GET  /cobranzas/importar     → Importación de CSV
    GET  /cobranzas/estadisticas → Estadísticas avanzadas

API JSON (CSRF-exempt al estar bajo /api/):
    GET  /api/cobranzas/stats/dashboard
    GET  /api/cobranzas/facturas
    GET  /api/cobranzas/facturas/<id>
    POST /api/cobranzas/facturas/<id>/asignar-cliente
    POST /api/cobranzas/facturas/<id>/asignar-curso
    POST /api/cobranzas/pagos
    DELETE /api/cobranzas/pagos/<id>
    GET  /api/cobranzas/clientes
    POST /api/cobranzas/clientes
    PUT  /api/cobranzas/clientes/<id>
    GET  /api/cobranzas/clientes/<id>
    POST /api/cobranzas/clientes/fusionar
    GET  /api/cobranzas/cursos
    POST /api/cobranzas/importar
    GET  /api/cobranzas/importar/historial
"""

import logging
from pathlib import Path

from flask import abort, jsonify, render_template, request
from flask_login import current_user, login_required

from config import settings
from src.cobranzas.client_manager import (
    actualizar_cliente,
    asignar_cliente_a_factura,
    asignar_curso_a_factura,
    buscar_clientes,
    crear_cliente,
    fusionar_clientes,
    listar_clientes,
    listar_cursos_usados,
    obtener_cliente,
)
from src.cobranzas.credit_note_engine import aplicar_todas_ncs
from src.cobranzas.csv_parser import parsear_archivo
from src.cobranzas.models import (
    get_db,
    init_db,
    insertar_documento,
    registrar_auditoria,
)
from src.cobranzas.payment_engine import (
    DistribucionItem,
    anular_pago,
    listar_pagos,
    listar_pagos_por_factura,
    obtener_pago_con_detalle,
    registrar_pago,
)
from src.cobranzas.stats_engine import (
    alertas_vencimiento,
    cobranza_mensual,
    distribucion_estados,
    facturacion_por_otic,
    kpis_cobranza,
    resumen_historico,
    top_clientes,
    top_cursos,
    top_otics_pendientes,
)

logger = logging.getLogger(__name__)

ANIO_CORTE = settings.ANIO_CORTE_GESTION


# ── Helpers ───────────────────────────────────────────────────────────────────

def _admin_required():
    """Aborta con 403 si el usuario no es administrador."""
    if not current_user.is_authenticated or current_user.rol != "admin":
        abort(403)


def _json_error(msg: str, code: int = 400):
    return jsonify({"ok": False, "error": msg}), code


def _json_ok(data: dict | None = None, **kwargs):
    payload = {"ok": True}
    if data:
        payload.update(data)
    payload.update(kwargs)
    return jsonify(payload)


def _get_ip() -> str:
    return request.headers.get("X-Forwarded-For", request.remote_addr or "")


def _usuario() -> str:
    return current_user.email if current_user.is_authenticated else "desconocido"


# ── Registro de rutas ─────────────────────────────────────────────────────────

def register_cobranzas_routes(app):
    """Registra todas las rutas del módulo de cobranzas en la app Flask."""

    # Inicializar BD al arrancar
    init_db()

    # ════════════════════════════════════════════════════════════
    # HTML — Vistas renderizadas en servidor
    # ════════════════════════════════════════════════════════════

    @app.route("/cobranzas/")
    @app.route("/cobranzas")
    @login_required
    def cobranzas_dashboard():
        _admin_required()
        return render_template("cobranzas/dashboard.html", anio_corte=ANIO_CORTE)

    @app.route("/cobranzas/facturas")
    @login_required
    def cobranzas_facturas():
        _admin_required()
        return render_template("cobranzas/facturas.html", anio_corte=ANIO_CORTE)

    @app.route("/cobranzas/pagos")
    @login_required
    def cobranzas_pagos():
        _admin_required()
        return render_template("cobranzas/pagos.html", anio_corte=ANIO_CORTE)

    @app.route("/cobranzas/clientes")
    @login_required
    def cobranzas_clientes():
        _admin_required()
        return render_template("cobranzas/clientes.html", anio_corte=ANIO_CORTE)

    @app.route("/cobranzas/importar")
    @login_required
    def cobranzas_importar():
        _admin_required()
        return render_template("cobranzas/importar.html", anio_corte=ANIO_CORTE)

    @app.route("/cobranzas/estadisticas")
    @login_required
    def cobranzas_estadisticas():
        _admin_required()
        return render_template("cobranzas/estadisticas.html", anio_corte=ANIO_CORTE)

    # ════════════════════════════════════════════════════════════
    # API — Estadísticas / Dashboard
    # ════════════════════════════════════════════════════════════

    @app.route("/api/cobranzas/stats/dashboard")
    @login_required
    def api_cobranzas_stats_dashboard():
        _admin_required()
        try:
            with get_db() as conn:
                data = {
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
            return jsonify(data)
        except Exception as exc:
            logger.exception("Error obteniendo stats dashboard")
            return _json_error(str(exc), 500)

    @app.route("/api/cobranzas/stats/historico")
    @login_required
    def api_cobranzas_stats_historico():
        _admin_required()
        anio = request.args.get("anio", type=int)
        try:
            with get_db() as conn:
                return jsonify({
                    "historico": resumen_historico(conn),
                    "por_otic":  facturacion_por_otic(conn, anio=anio),
                })
        except Exception as exc:
            return _json_error(str(exc), 500)

    # ════════════════════════════════════════════════════════════
    # API — Facturas
    # ════════════════════════════════════════════════════════════

    @app.route("/api/cobranzas/facturas")
    @login_required
    def api_cobranzas_facturas_list():
        _admin_required()
        try:
            page     = max(1, request.args.get("page", 1, type=int))
            per_page = min(200, max(10, request.args.get("per_page", 50, type=int)))
            estado   = request.args.get("estado", "").strip()
            otic     = request.args.get("otic", "").strip()
            periodo  = request.args.get("periodo", "").strip()
            q        = request.args.get("q", "").strip()
            solo_activas = request.args.get("solo_activas", "false").lower() == "true"
            tipo_doc = request.args.get("tipo_doc", "").strip()

            conditions = ["d.tipo_doc IN (33, 34)"]
            params: list = []

            if solo_activas:
                conditions.append(f"strftime('%Y', d.fecha_docto) >= '{ANIO_CORTE}'")
            if estado:
                conditions.append("d.estado = ?")
                params.append(estado)
            if otic:
                conditions.append("d.rut_cliente = ?")
                params.append(otic)
            if periodo:
                conditions.append("d.periodo_tributario = ?")
                params.append(periodo)
            if tipo_doc:
                conditions.append("d.tipo_doc = ?")
                params.append(int(tipo_doc))
            if q:
                conditions.append(
                    "(d.folio LIKE ? OR d.razon_social LIKE ? OR c.nombre LIKE ?)"
                )
                like = f"%{q}%"
                params += [like, like, like]

            where = "WHERE " + " AND ".join(conditions) if conditions else ""

            sql_base = f"""
                FROM documentos_sii d
                LEFT JOIN clientes c ON d.cliente_id = c.id
                LEFT JOIN (
                    SELECT folio_referencia, tipo_doc_referencia,
                           SUM(monto_total) AS monto_nc
                    FROM documentos_sii WHERE tipo_doc = 61
                    GROUP BY folio_referencia, tipo_doc_referencia
                ) nc ON nc.folio_referencia = d.folio
                     AND nc.tipo_doc_referencia = d.tipo_doc
                LEFT JOIN (
                    SELECT documento_id, SUM(monto_aplicado) AS total_pagado
                    FROM pago_detalle GROUP BY documento_id
                ) pg ON pg.documento_id = d.id
                {where}
            """

            with get_db() as conn:
                total = conn.execute(
                    f"SELECT COUNT(*) {sql_base}", params
                ).fetchone()[0]

                rows = conn.execute(
                    f"""SELECT d.id, d.tipo_doc, d.tipo_doc_nombre, d.folio,
                               d.rut_cliente, d.razon_social, d.fecha_docto,
                               d.monto_total, d.monto_exento, d.monto_neto, d.monto_iva,
                               d.estado, d.saldo_pendiente, d.periodo_tributario,
                               d.cliente_id, d.curso, d.archivo_origen,
                               c.nombre AS cliente_nombre,
                               COALESCE(nc.monto_nc, 0)       AS monto_nc,
                               COALESCE(pg.total_pagado, 0)   AS total_pagado
                        {sql_base}
                        ORDER BY d.fecha_docto DESC, d.folio DESC
                        LIMIT ? OFFSET ?""",
                    params + [per_page, (page - 1) * per_page],
                ).fetchall()

            return jsonify({
                "total":    total,
                "page":     page,
                "per_page": per_page,
                "pages":    (total + per_page - 1) // per_page,
                "facturas": [dict(r) for r in rows],
            })
        except Exception as exc:
            logger.exception("Error listando facturas")
            return _json_error(str(exc), 500)

    @app.route("/api/cobranzas/facturas/<int:doc_id>")
    @login_required
    def api_cobranzas_factura_detalle(doc_id):
        _admin_required()
        try:
            with get_db() as conn:
                doc = conn.execute(
                    """SELECT d.*, c.nombre AS cliente_nombre
                       FROM documentos_sii d
                       LEFT JOIN clientes c ON d.cliente_id = c.id
                       WHERE d.id = ?""",
                    (doc_id,),
                ).fetchone()
                if doc is None:
                    return _json_error("Factura no encontrada", 404)

                # Notas de crédito que la referencian
                ncs = conn.execute(
                    """SELECT folio, fecha_docto, monto_total, razon_social
                       FROM documentos_sii
                       WHERE tipo_doc = 61
                         AND folio_referencia = ?
                         AND tipo_doc_referencia = ?
                       ORDER BY fecha_docto""",
                    (doc["folio"], doc["tipo_doc"]),
                ).fetchall()

                # Historial de pagos
                pagos = listar_pagos_por_factura(conn, doc_id)

            return jsonify({
                "factura": dict(doc),
                "notas_credito": [dict(nc) for nc in ncs],
                "pagos": pagos,
            })
        except Exception as exc:
            logger.exception("Error obteniendo detalle factura %d", doc_id)
            return _json_error(str(exc), 500)

    @app.route("/api/cobranzas/facturas/<int:doc_id>/asignar-cliente", methods=["POST"])
    @login_required
    def api_asignar_cliente(doc_id):
        _admin_required()
        data = request.get_json(silent=True) or {}
        cliente_id = data.get("cliente_id")
        if not cliente_id:
            return _json_error("cliente_id es requerido")
        try:
            with get_db() as conn:
                res = asignar_cliente_a_factura(
                    conn, doc_id, int(cliente_id), _usuario(), _get_ip()
                )
            if not res["ok"]:
                return _json_error(res["error"])
            return _json_ok(**res)
        except Exception as exc:
            return _json_error(str(exc), 500)

    @app.route("/api/cobranzas/facturas/<int:doc_id>/asignar-curso", methods=["POST"])
    @login_required
    def api_asignar_curso(doc_id):
        _admin_required()
        data = request.get_json(silent=True) or {}
        curso = data.get("curso", "")
        try:
            with get_db() as conn:
                res = asignar_curso_a_factura(
                    conn, doc_id, curso, _usuario(), _get_ip()
                )
            if not res["ok"]:
                return _json_error(res["error"])
            return _json_ok()
        except Exception as exc:
            return _json_error(str(exc), 500)

    # ════════════════════════════════════════════════════════════
    # API — Pagos
    # ════════════════════════════════════════════════════════════

    @app.route("/api/cobranzas/pagos", methods=["GET"])
    @login_required
    def api_cobranzas_pagos_list():
        _admin_required()
        page     = max(1, request.args.get("page", 1, type=int))
        per_page = min(100, max(10, request.args.get("per_page", 20, type=int)))
        try:
            with get_db() as conn:
                result = listar_pagos(conn, limit=per_page, offset=(page - 1) * per_page)
            return jsonify(result)
        except Exception as exc:
            return _json_error(str(exc), 500)

    @app.route("/api/cobranzas/pagos", methods=["POST"])
    @login_required
    def api_cobranzas_pagos_registrar():
        _admin_required()
        data = request.get_json(silent=True) or {}

        fecha_pago   = data.get("fecha_pago", "").strip()
        observacion  = data.get("observacion", "")
        try:
            monto_total = int(data.get("monto_total", 0))
        except (ValueError, TypeError):
            return _json_error("monto_total debe ser un entero")

        raw_dists = data.get("distribuciones", [])
        if not isinstance(raw_dists, list):
            return _json_error("distribuciones debe ser una lista")

        try:
            distribuciones = [
                DistribucionItem(
                    documento_id=int(d["documento_id"]),
                    monto_aplicado=int(d["monto_aplicado"]),
                )
                for d in raw_dists
            ]
        except (KeyError, ValueError, TypeError) as exc:
            return _json_error(f"Error en distribuciones: {exc}")

        if not fecha_pago:
            return _json_error("fecha_pago es requerida (YYYY-MM-DD)")

        try:
            with get_db() as conn:
                res = registrar_pago(
                    conn,
                    fecha_pago=fecha_pago,
                    monto_total=monto_total,
                    distribuciones=distribuciones,
                    usuario=_usuario(),
                    observacion=observacion,
                    ip=_get_ip(),
                )
            if not res.ok:
                return jsonify({"ok": False, "errores": res.errores}), 400
            return _json_ok(pago_id=res.pago_id), 201
        except Exception as exc:
            logger.exception("Error registrando pago")
            return _json_error(str(exc), 500)

    @app.route("/api/cobranzas/pagos/<int:pago_id>", methods=["GET"])
    @login_required
    def api_cobranzas_pago_detalle(pago_id):
        _admin_required()
        try:
            with get_db() as conn:
                pago = obtener_pago_con_detalle(conn, pago_id)
            if pago is None:
                return _json_error("Pago no encontrado", 404)
            return jsonify(pago)
        except Exception as exc:
            return _json_error(str(exc), 500)

    @app.route("/api/cobranzas/pagos/<int:pago_id>", methods=["DELETE"])
    @login_required
    def api_cobranzas_pago_anular(pago_id):
        _admin_required()
        try:
            with get_db() as conn:
                res = anular_pago(conn, pago_id, _usuario(), _get_ip())
            if not res["ok"]:
                return _json_error(res["error"])
            return _json_ok(**res)
        except Exception as exc:
            return _json_error(str(exc), 500)

    # ════════════════════════════════════════════════════════════
    # API — Clientes
    # ════════════════════════════════════════════════════════════

    @app.route("/api/cobranzas/clientes", methods=["GET"])
    @login_required
    def api_cobranzas_clientes_list():
        _admin_required()
        q        = request.args.get("q", "").strip()
        page     = max(1, request.args.get("page", 1, type=int))
        per_page = min(200, max(10, request.args.get("per_page", 50, type=int)))
        try:
            with get_db() as conn:
                if q:
                    clientes = buscar_clientes(conn, q, limite=20)
                    return jsonify({"clientes": clientes, "total": len(clientes)})
                result = listar_clientes(conn, limit=per_page, offset=(page - 1) * per_page)
            return jsonify(result)
        except Exception as exc:
            return _json_error(str(exc), 500)

    @app.route("/api/cobranzas/clientes", methods=["POST"])
    @login_required
    def api_cobranzas_clientes_crear():
        _admin_required()
        data = request.get_json(silent=True) or {}
        nombre   = data.get("nombre", "").strip()
        forzar   = bool(data.get("forzar", False))
        rut      = data.get("rut", "")
        contacto = data.get("contacto", "")
        email    = data.get("email", "")
        telefono = data.get("telefono", "")

        if not nombre:
            return _json_error("El nombre es requerido")
        try:
            with get_db() as conn:
                res = crear_cliente(
                    conn, nombre, _usuario(),
                    rut=rut, contacto=contacto, email=email, telefono=telefono,
                    ip=_get_ip(), forzar=forzar,
                )
            if not res["ok"]:
                return jsonify(res), 409 if res.get("sugerencias") else 400
            return jsonify(res), 201
        except Exception as exc:
            return _json_error(str(exc), 500)

    @app.route("/api/cobranzas/clientes/<int:cliente_id>", methods=["GET"])
    @login_required
    def api_cobranzas_cliente_detalle(cliente_id):
        _admin_required()
        try:
            with get_db() as conn:
                cliente = obtener_cliente(conn, cliente_id)
            if cliente is None:
                return _json_error("Cliente no encontrado", 404)
            return jsonify(cliente)
        except Exception as exc:
            return _json_error(str(exc), 500)

    @app.route("/api/cobranzas/clientes/<int:cliente_id>", methods=["PUT"])
    @login_required
    def api_cobranzas_clientes_actualizar(cliente_id):
        _admin_required()
        data = request.get_json(silent=True) or {}
        try:
            with get_db() as conn:
                res = actualizar_cliente(
                    conn, cliente_id, _usuario(),
                    nombre   = data.get("nombre"),
                    rut      = data.get("rut"),
                    contacto = data.get("contacto"),
                    email    = data.get("email"),
                    telefono = data.get("telefono"),
                    ip       = _get_ip(),
                )
            if not res["ok"]:
                return _json_error(res["error"])
            return _json_ok()
        except Exception as exc:
            return _json_error(str(exc), 500)

    @app.route("/api/cobranzas/clientes/fusionar", methods=["POST"])
    @login_required
    def api_cobranzas_clientes_fusionar():
        _admin_required()
        data = request.get_json(silent=True) or {}
        try:
            id_origen  = int(data["id_origen"])
            id_destino = int(data["id_destino"])
        except (KeyError, ValueError, TypeError):
            return _json_error("id_origen e id_destino son requeridos (enteros)")
        try:
            with get_db() as conn:
                res = fusionar_clientes(conn, id_origen, id_destino, _usuario(), _get_ip())
            if not res["ok"]:
                return _json_error(res["error"])
            return _json_ok(**res)
        except Exception as exc:
            return _json_error(str(exc), 500)

    # ════════════════════════════════════════════════════════════
    # API — Cursos (autocompletado)
    # ════════════════════════════════════════════════════════════

    @app.route("/api/cobranzas/cursos")
    @login_required
    def api_cobranzas_cursos():
        _admin_required()
        try:
            with get_db() as conn:
                cursos = listar_cursos_usados(conn)
            return jsonify({"cursos": cursos})
        except Exception as exc:
            return _json_error(str(exc), 500)

    # ════════════════════════════════════════════════════════════
    # API — OTICs (para filtros)
    # ════════════════════════════════════════════════════════════

    @app.route("/api/cobranzas/otics")
    @login_required
    def api_cobranzas_otics():
        _admin_required()
        try:
            with get_db() as conn:
                rows = conn.execute(
                    """SELECT DISTINCT rut_cliente, razon_social
                       FROM documentos_sii WHERE tipo_doc IN (33,34)
                       ORDER BY razon_social"""
                ).fetchall()
            return jsonify({"otics": [dict(r) for r in rows]})
        except Exception as exc:
            return _json_error(str(exc), 500)

    # ════════════════════════════════════════════════════════════
    # API — Importación de CSV
    # ════════════════════════════════════════════════════════════

    @app.route("/api/cobranzas/importar", methods=["POST"])
    @login_required
    def api_cobranzas_importar():
        _admin_required()
        archivos = request.files.getlist("archivos")
        if not archivos or all(f.filename == "" for f in archivos):
            return _json_error("No se enviaron archivos")

        destino = settings.SII_CSV_PATH
        destino.mkdir(parents=True, exist_ok=True)

        resumen_global = {
            "archivos_procesados": 0,
            "documentos_insertados": 0,
            "duplicados": 0,
            "errores_parseo": [],
            "ncs_aplicadas": 0,
            "detalles": [],
        }

        archivos_guardados: list[Path] = []

        for f in archivos:
            if not f.filename:
                continue
            nombre = Path(f.filename).name  # Evitar path traversal
            ruta_guardado = destino / nombre
            f.save(str(ruta_guardado))
            archivos_guardados.append(ruta_guardado)

        try:
            with get_db() as conn:
                for ruta in archivos_guardados:
                    try:
                        resultado = parsear_archivo(ruta)
                    except Exception as exc:
                        resumen_global["errores_parseo"].append(
                            f"{ruta.name}: {exc}"
                        )
                        continue

                    insertados = duplicados = 0
                    for doc in resultado.documentos:
                        if insertar_documento(conn, doc):
                            insertados += 1
                        else:
                            duplicados += 1

                    resumen_global["archivos_procesados"] += 1
                    resumen_global["documentos_insertados"] += insertados
                    resumen_global["duplicados"] += duplicados
                    resumen_global["errores_parseo"].extend(resultado.errores)

                    resumen_global["detalles"].append({
                        "archivo":   ruta.name,
                        "periodo":   resultado.periodo,
                        "facturas":  len(resultado.facturas),
                        "ncs":       len(resultado.notas_credito),
                        "insertados": insertados,
                        "duplicados": duplicados,
                        "errores":   resultado.errores,
                    })

                # Aplicar NCs tras todos los inserts
                res_nc = aplicar_todas_ncs(conn, usuario=_usuario(), ip=_get_ip())
                resumen_global["ncs_aplicadas"] = res_nc["aplicadas"]

                # Auditoría
                registrar_auditoria(
                    conn, _usuario(), "importar_csv",
                    f"Importados {resumen_global['documentos_insertados']} documentos "
                    f"de {resumen_global['archivos_procesados']} archivos. "
                    f"{resumen_global['duplicados']} duplicados omitidos.",
                    _get_ip(),
                )

        except Exception as exc:
            logger.exception("Error durante importación")
            return _json_error(str(exc), 500)

        return jsonify({"ok": True, **resumen_global}), 201

    @app.route("/api/cobranzas/importar/historial")
    @login_required
    def api_cobranzas_importar_historial():
        _admin_required()
        try:
            with get_db() as conn:
                rows = conn.execute(
                    """SELECT fecha, usuario, detalle, ip
                       FROM log_auditoria
                       WHERE accion = 'importar_csv'
                       ORDER BY fecha DESC LIMIT 50"""
                ).fetchall()
            return jsonify({"historial": [dict(r) for r in rows]})
        except Exception as exc:
            return _json_error(str(exc), 500)

    @app.route("/api/cobranzas/importar/periodos")
    @login_required
    def api_cobranzas_periodos():
        """Lista de periodos ya importados en la BD."""
        _admin_required()
        try:
            with get_db() as conn:
                rows = conn.execute(
                    """SELECT periodo_tributario,
                              COUNT(*)                              AS num_docs,
                              SUM(CASE WHEN tipo_doc IN (33,34) THEN 1 ELSE 0 END) AS num_facturas,
                              SUM(CASE WHEN tipo_doc = 61 THEN 1 ELSE 0 END)       AS num_ncs
                       FROM documentos_sii
                       GROUP BY periodo_tributario
                       ORDER BY periodo_tributario DESC"""
                ).fetchall()
            return jsonify({"periodos": [dict(r) for r in rows]})
        except Exception as exc:
            return _json_error(str(exc), 500)

    logger.info("Rutas de cobranzas registradas correctamente")

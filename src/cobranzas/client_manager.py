"""
Gestor de Clientes — catálogo maestro con normalización y deduplicación.

Reglas de negocio:
  - Los clientes son las empresas REALES (no las OTICs intermediarias del SII).
  - Normalización obligatoria: "HOTEL DIEGO DE ALMAGRO" → "Hotel Diego De Almagro"
  - Deduplicación: antes de crear, buscar si ya existe uno similar por nombre_busqueda.
  - Autocompletado fuzzy: buscar coincidencias parciales por palabras del nombre.
  - Merge de duplicados: unificar dos registros en uno conservando el destino.
  - Solo facturas 2026+ pueden tener cliente asignado (ver ANIO_CORTE_GESTION).
"""

import logging
import sqlite3
import unicodedata
from datetime import datetime, timezone

from config import settings
from src.cobranzas.models import registrar_auditoria

logger = logging.getLogger(__name__)

ANIO_CORTE = settings.ANIO_CORTE_GESTION


# ── Normalización ─────────────────────────────────────────────────────────────

def normalizar_nombre(nombre: str) -> tuple[str, str]:
    """
    Normaliza un nombre de cliente.

    Returns:
        (nombre_titulo, nombre_busqueda):
          - nombre_titulo:   "Hotel Diego De Almagro"  (almacenado en BD)
          - nombre_busqueda: "HOTEL DIEGO DE ALMAGRO"  sin tildes (para comparar)

    Ejemplos:
      "HOTEL DIEGO DE ALMAGRO"   → ("Hotel Diego De Almagro",   "HOTEL DIEGO DE ALMAGRO")
      "  empresa  ejemplo spa  " → ("Empresa Ejemplo Spa",      "EMPRESA EJEMPLO SPA")
      "Constructora Ñañez"       → ("Constructora Ñañez",       "CONSTRUCTORA NANEZ")
    """
    nombre = " ".join(nombre.split())   # Colapsar espacios múltiples
    nombre_titulo = nombre.title()

    # Normalización NFKD: descompone caracteres con acento
    nfkd = unicodedata.normalize("NFKD", nombre_titulo.upper())
    # Quitar combinaciones diacríticas (tildes, diéresis, etc.) pero conservar Ñ → N
    nombre_busqueda = "".join(c for c in nfkd if not unicodedata.combining(c))

    return nombre_titulo, nombre_busqueda


# ── Creación de clientes ──────────────────────────────────────────────────────

def crear_cliente(
    conn: sqlite3.Connection,
    nombre: str,
    usuario: str,
    rut: str = "",
    contacto: str = "",
    email: str = "",
    telefono: str = "",
    ip: str = "",
    forzar: bool = False,
) -> dict:
    """
    Crea un nuevo cliente en el catálogo.

    Antes de crear, verifica si ya existe uno similar (por nombre_busqueda).
    Si encuentra similares y forzar=False, retorna sugerencias sin crear.

    Args:
        nombre:   Nombre del cliente (se normaliza automáticamente).
        usuario:  Email del usuario que crea el registro.
        rut:      RUT del cliente (opcional, sin validación de DV aquí).
        contacto: Nombre de contacto (opcional).
        email:    Email de contacto (opcional).
        telefono: Teléfono (opcional).
        ip:       IP del usuario.
        forzar:   Si True, crea aunque existan similares.

    Returns:
        {
            "ok": bool,
            "cliente_id": int | None,
            "cliente": dict | None,
            "sugerencias": list[dict],    # Solo si ok=False por duplicados
            "error": str | None,
        }
    """
    if not nombre or not nombre.strip():
        return {"ok": False, "cliente_id": None, "cliente": None,
                "sugerencias": [], "error": "El nombre del cliente es requerido"}

    nombre_titulo, nombre_busqueda = normalizar_nombre(nombre)

    # Verificar si ya existe exactamente igual
    existente = conn.execute(
        "SELECT * FROM clientes WHERE nombre_busqueda = ?", (nombre_busqueda,)
    ).fetchone()
    if existente:
        return {
            "ok": False, "cliente_id": existente["id"],
            "cliente": dict(existente),
            "sugerencias": [], "error": "Ya existe un cliente con ese nombre",
        }

    # Buscar similares si no se fuerza la creación
    if not forzar:
        similares = buscar_clientes_similares(conn, nombre_busqueda, limite=4)
        if similares:
            return {
                "ok": False, "cliente_id": None, "cliente": None,
                "sugerencias": similares,
                "error": (
                    f"Se encontraron clientes similares. "
                    f"¿Quisiste decir '{similares[0]['nombre']}'? "
                    f"Usa forzar=True para crear de todas formas."
                ),
            }

    ahora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    # Sanitizar campos opcionales
    rut      = rut.strip()[:20]      if rut      else None
    contacto = contacto.strip()[:200] if contacto else None
    email    = email.strip()[:200]    if email    else None
    telefono = telefono.strip()[:50]  if telefono else None

    try:
        cursor = conn.execute(
            """INSERT INTO clientes
               (nombre, nombre_busqueda, rut, contacto, email, telefono,
                fecha_creacion, creado_por)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (nombre_titulo, nombre_busqueda, rut, contacto, email, telefono,
             ahora, usuario),
        )
        cliente_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        return {
            "ok": False, "cliente_id": None, "cliente": None,
            "sugerencias": [], "error": "Conflicto al insertar: nombre ya registrado",
        }

    registrar_auditoria(
        conn, usuario, "crear_cliente",
        f"Cliente creado: '{nombre_titulo}' (id={cliente_id})", ip,
    )
    logger.info("Cliente creado: '%s' (id=%d) por %s", nombre_titulo, cliente_id, usuario)

    cliente = conn.execute(
        "SELECT * FROM clientes WHERE id = ?", (cliente_id,)
    ).fetchone()
    return {
        "ok": True, "cliente_id": cliente_id,
        "cliente": dict(cliente), "sugerencias": [], "error": None,
    }


def actualizar_cliente(
    conn: sqlite3.Connection,
    cliente_id: int,
    usuario: str,
    nombre: str | None = None,
    rut: str | None = None,
    contacto: str | None = None,
    email: str | None = None,
    telefono: str | None = None,
    ip: str = "",
) -> dict:
    """
    Actualiza los datos de un cliente existente.

    Solo actualiza los campos que se pasen (no None).
    Si se cambia el nombre, renormaliza nombre_busqueda.
    """
    cliente = conn.execute(
        "SELECT * FROM clientes WHERE id = ?", (cliente_id,)
    ).fetchone()
    if cliente is None:
        return {"ok": False, "error": f"Cliente id={cliente_id} no encontrado"}

    sets: list[str] = []
    params: list = []

    if nombre is not None:
        nombre_titulo, nombre_busqueda = normalizar_nombre(nombre)
        # Verificar que el nuevo nombre no colisione con otro cliente
        colision = conn.execute(
            "SELECT id FROM clientes WHERE nombre_busqueda = ? AND id != ?",
            (nombre_busqueda, cliente_id),
        ).fetchone()
        if colision:
            return {"ok": False, "error": f"Ya existe otro cliente con un nombre similar"}
        sets.extend(["nombre = ?", "nombre_busqueda = ?"])
        params.extend([nombre_titulo, nombre_busqueda])

    for campo, valor in [("rut", rut), ("contacto", contacto),
                         ("email", email), ("telefono", telefono)]:
        if valor is not None:
            sets.append(f"{campo} = ?")
            params.append(valor.strip()[:200] if valor else None)

    if not sets:
        return {"ok": False, "error": "No se especificaron campos a actualizar"}

    params.append(cliente_id)
    conn.execute(
        f"UPDATE clientes SET {', '.join(sets)} WHERE id = ?", params
    )

    registrar_auditoria(
        conn, usuario, "actualizar_cliente",
        f"Cliente id={cliente_id} actualizado. Campos: {', '.join(s.split(' = ')[0] for s in sets)}",
        ip,
    )
    return {"ok": True, "error": None}


# ── Búsqueda y autocompletado ─────────────────────────────────────────────────

def buscar_clientes(
    conn: sqlite3.Connection,
    query: str,
    limite: int = 10,
) -> list[dict]:
    """
    Busca clientes por coincidencia parcial del nombre (autocompletado).

    Divide el query en palabras y busca clientes cuyo nombre_busqueda
    contenga TODAS las palabras (AND). Devuelve resultado ordenado por nombre.
    """
    if not query or not query.strip():
        # Sin query: devolver todos los clientes (paginado)
        rows = conn.execute(
            "SELECT * FROM clientes ORDER BY nombre LIMIT ?", (limite,)
        ).fetchall()
        return [dict(r) for r in rows]

    _, nombre_busqueda_query = normalizar_nombre(query)
    palabras = [p for p in nombre_busqueda_query.split() if len(p) >= 2]

    if not palabras:
        return []

    condiciones = " AND ".join(["nombre_busqueda LIKE ?" for _ in palabras])
    params = [f"%{p}%" for p in palabras]
    params.append(limite)

    rows = conn.execute(
        f"SELECT * FROM clientes WHERE {condiciones} ORDER BY nombre LIMIT ?",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def buscar_clientes_similares(
    conn: sqlite3.Connection,
    nombre_busqueda: str,
    limite: int = 4,
) -> list[dict]:
    """
    Busca clientes similares a partir del nombre_busqueda ya normalizado.

    Usa las palabras significativas (> 2 letras) para hacer AND de LIKEs.
    """
    palabras = [p for p in nombre_busqueda.split() if len(p) > 2]
    if not palabras:
        return []

    condiciones = " AND ".join(["nombre_busqueda LIKE ?" for _ in palabras])
    params = [f"%{p}%" for p in palabras]
    params.append(limite)

    rows = conn.execute(
        f"SELECT * FROM clientes WHERE {condiciones} ORDER BY nombre LIMIT ?",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def obtener_cliente(conn: sqlite3.Connection, cliente_id: int) -> dict | None:
    """Obtiene un cliente por id con sus estadísticas de facturación."""
    cliente = conn.execute(
        "SELECT * FROM clientes WHERE id = ?", (cliente_id,)
    ).fetchone()
    if cliente is None:
        return None

    stats = conn.execute(
        """SELECT
               COUNT(*)                                        AS total_facturas,
               COALESCE(SUM(monto_total), 0)                  AS total_facturado,
               COALESCE(SUM(CASE WHEN estado='Pagada'  THEN monto_total ELSE 0 END), 0) AS total_pagado,
               COALESCE(SUM(saldo_pendiente), 0)              AS total_pendiente
           FROM documentos_sii
           WHERE cliente_id = ? AND tipo_doc IN (33, 34)""",
        (cliente_id,),
    ).fetchone()

    cursos = conn.execute(
        """SELECT DISTINCT curso FROM documentos_sii
           WHERE cliente_id = ? AND curso IS NOT NULL
           ORDER BY curso""",
        (cliente_id,),
    ).fetchall()

    return {
        **dict(cliente),
        "total_facturas":   stats["total_facturas"],
        "total_facturado":  stats["total_facturado"],
        "total_pagado":     stats["total_pagado"],
        "total_pendiente":  stats["total_pendiente"],
        "cursos":           [r["curso"] for r in cursos],
    }


# ── Asignación a facturas ─────────────────────────────────────────────────────

def asignar_cliente_a_factura(
    conn: sqlite3.Connection,
    documento_id: int,
    cliente_id: int,
    usuario: str,
    ip: str = "",
) -> dict:
    """
    Asigna un cliente real a una factura 2026+.

    Solo facturas con fecha_docto >= ANIO_CORTE pueden recibir cliente.
    """
    doc = conn.execute(
        "SELECT id, folio, tipo_doc, fecha_docto, cliente_id FROM documentos_sii WHERE id = ?",
        (documento_id,),
    ).fetchone()
    if doc is None:
        return {"ok": False, "error": f"Factura id={documento_id} no encontrada"}

    if doc["tipo_doc"] == 61:
        return {"ok": False, "error": "Las notas de crédito no tienen cliente asignado"}

    try:
        anio_doc = int(str(doc["fecha_docto"])[:4])
    except (ValueError, TypeError):
        anio_doc = 0
    if anio_doc < ANIO_CORTE:
        return {
            "ok": False,
            "error": f"Las facturas anteriores a {ANIO_CORTE} no admiten asignación de cliente",
        }

    cliente = conn.execute(
        "SELECT id, nombre FROM clientes WHERE id = ?", (cliente_id,)
    ).fetchone()
    if cliente is None:
        return {"ok": False, "error": f"Cliente id={cliente_id} no encontrado"}

    cliente_anterior = doc["cliente_id"]
    conn.execute(
        "UPDATE documentos_sii SET cliente_id = ? WHERE id = ?",
        (cliente_id, documento_id),
    )

    registrar_auditoria(
        conn, usuario, "asignar_cliente",
        f"Factura folio={doc['folio']}: cliente "
        f"{'cambiado de id=' + str(cliente_anterior) + ' a' if cliente_anterior else 'asignado'} "
        f"'{cliente['nombre']}' (id={cliente_id})",
        ip,
    )
    return {"ok": True, "error": None, "cliente_nombre": cliente["nombre"]}


def asignar_curso_a_factura(
    conn: sqlite3.Connection,
    documento_id: int,
    curso: str,
    usuario: str,
    ip: str = "",
) -> dict:
    """
    Asigna un nombre de curso a una factura 2026+.

    El curso se guarda como texto libre (sanitizado).
    """
    doc = conn.execute(
        "SELECT id, folio, tipo_doc, fecha_docto FROM documentos_sii WHERE id = ?",
        (documento_id,),
    ).fetchone()
    if doc is None:
        return {"ok": False, "error": f"Factura id={documento_id} no encontrada"}

    if doc["tipo_doc"] == 61:
        return {"ok": False, "error": "Las notas de crédito no tienen curso asignado"}

    try:
        anio_doc = int(str(doc["fecha_docto"])[:4])
    except (ValueError, TypeError):
        anio_doc = 0
    if anio_doc < ANIO_CORTE:
        return {
            "ok": False,
            "error": f"Las facturas anteriores a {ANIO_CORTE} no admiten asignación de curso",
        }

    # Sanitizar: strip, máximo 300 chars, permitir None si viene vacío
    curso_limpio = curso.strip()[:300] if curso and curso.strip() else None

    conn.execute(
        "UPDATE documentos_sii SET curso = ? WHERE id = ?",
        (curso_limpio, documento_id),
    )

    registrar_auditoria(
        conn, usuario, "asignar_curso",
        f"Factura folio={doc['folio']}: curso asignado = '{curso_limpio}'", ip,
    )
    return {"ok": True, "error": None}


def listar_cursos_usados(conn: sqlite3.Connection) -> list[str]:
    """Devuelve todos los nombres de curso distintos usados en facturas 2026+."""
    rows = conn.execute(
        """SELECT DISTINCT curso FROM documentos_sii
           WHERE curso IS NOT NULL AND curso != ''
             AND tipo_doc IN (33, 34)
             AND strftime('%Y', fecha_docto) >= ?
           ORDER BY curso""",
        (str(ANIO_CORTE),),
    ).fetchall()
    return [r["curso"] for r in rows]


# ── Fusión de duplicados ──────────────────────────────────────────────────────

def fusionar_clientes(
    conn: sqlite3.Connection,
    id_origen: int,
    id_destino: int,
    usuario: str,
    ip: str = "",
) -> dict:
    """
    Fusiona dos clientes duplicados en uno solo.

    Reasigna todas las facturas del cliente id_origen al id_destino,
    luego elimina el cliente id_origen.

    El id_destino queda como el cliente "sobreviviente".

    Returns:
        {"ok": bool, "facturas_reasignadas": int, "error": str | None}
    """
    if id_origen == id_destino:
        return {"ok": False, "error": "Origen y destino son el mismo cliente", "facturas_reasignadas": 0}

    for cid in (id_origen, id_destino):
        if conn.execute("SELECT 1 FROM clientes WHERE id = ?", (cid,)).fetchone() is None:
            return {"ok": False, "error": f"Cliente id={cid} no encontrado", "facturas_reasignadas": 0}

    origen  = conn.execute("SELECT nombre FROM clientes WHERE id = ?", (id_origen,)).fetchone()
    destino = conn.execute("SELECT nombre FROM clientes WHERE id = ?", (id_destino,)).fetchone()

    # Reasignar facturas
    cursor = conn.execute(
        "UPDATE documentos_sii SET cliente_id = ? WHERE cliente_id = ?",
        (id_destino, id_origen),
    )
    facturas_reasignadas = cursor.rowcount

    # Eliminar cliente origen
    conn.execute("DELETE FROM clientes WHERE id = ?", (id_origen,))

    registrar_auditoria(
        conn, usuario, "fusionar_clientes",
        f"Fusionado '{origen['nombre']}' (id={id_origen}) → '{destino['nombre']}' (id={id_destino}). "
        f"{facturas_reasignadas} facturas reasignadas.",
        ip,
    )
    logger.info(
        "Clientes fusionados: id=%d → id=%d (%d facturas reasignadas)",
        id_origen, id_destino, facturas_reasignadas,
    )
    return {"ok": True, "error": None, "facturas_reasignadas": facturas_reasignadas}


# ── Listado de clientes ───────────────────────────────────────────────────────

def listar_clientes(
    conn: sqlite3.Connection,
    limit: int = 100,
    offset: int = 0,
    order_by: str = "nombre",
) -> dict:
    """
    Lista todos los clientes con sus estadísticas básicas.

    Returns:
        {"total": int, "clientes": list[dict]}
    """
    columnas_validas = {"nombre", "total_facturado", "total_pendiente", "fecha_creacion"}
    if order_by not in columnas_validas:
        order_by = "nombre"

    total = conn.execute("SELECT COUNT(*) FROM clientes").fetchone()[0]

    sql_order = order_by if order_by == "nombre" else f"{order_by} DESC"

    rows = conn.execute(
        f"""SELECT c.*,
                   COUNT(d.id)                                         AS total_facturas,
                   COALESCE(SUM(d.monto_total), 0)                     AS total_facturado,
                   COALESCE(SUM(d.saldo_pendiente), 0)                 AS total_pendiente
            FROM clientes c
            LEFT JOIN documentos_sii d ON c.id = d.cliente_id AND d.tipo_doc IN (33, 34)
            GROUP BY c.id
            ORDER BY {sql_order}
            LIMIT ? OFFSET ?""",
        (limit, offset),
    ).fetchall()
    return {
        "total": total,
        "clientes": [dict(r) for r in rows],
    }

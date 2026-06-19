"""
sincronico_queries.py — Datos de la pestaña "Cursos Sincrónicos" del dashboard.

Combina, SOLO para cursos sincrónicos, dos fuentes distintas:
  - NOTA / estado académico  → base `tecnipro_reportes` (Moodle, ya procesada
    por el pipeline; misma fuente que el dashboard asincrónico).
  - % ASISTENCIA por alumno   → base `erp_empresas`, schema `cursos_sincronico`
    (capturada por la app "Cursos Sincrónicos" desde Teams vía Graph + matcher).

Un curso es SINCRÓNICO sí y solo sí existe en `cursos_sincronico.cursos`
(por `moodle_course_id`). Cualquier curso que no esté ahí es asincrónico y
NO es tocado por este módulo: la lógica es 100% aditiva y aislada.

Las dos fuentes se cruzan por RUT (normalizado). La lista base de alumnos de
cada curso es la inscripción del sistema sincrónico (para que el % de
asistencia cuadre exactamente con dicho sistema); la nota se agrega con un
LEFT JOIN lógico por RUT.
"""

import logging
import os

import psycopg2
from psycopg2.extras import RealDictCursor
from sqlalchemy import bindparam, text

from src.database import get_engine, init_db

logger = logging.getLogger(__name__)

# Corte de aprobación de nota (escala chilena), idéntico a calculator.py.
NOTA_CORTE = 4.0

# Mínimo de asistencia por defecto cuando el curso no lo tiene configurado.
ASIST_MIN_DEFAULT = 75.0

# Conexión a erp_empresas (mismas credenciales que el resto de módulos ERP).
# erp_admin es dueño del schema cursos_sincronico → lectura completa sin grants.
ERP_PG_DSN = {
    "host": os.environ.get("ERP_PG_HOST", "localhost"),
    "dbname": os.environ.get("ERP_PG_DATABASE", "erp_empresas"),
    "user": os.environ.get("ERP_PG_USER", "erp_admin"),
    "password": os.environ.get("ERP_PG_PASSWORD", ""),
}

# Query canónica de asistencia (idéntica a la del sistema sincrónico):
# denominador uniforme = total de sesiones del curso; pct a 1 decimal;
# NULL si el curso aún no tiene sesiones.
_ASISTENCIA_SQL = """
WITH curso AS (
    SELECT id, asistencia_minima
    FROM cursos_sincronico.cursos
    WHERE moodle_course_id = %(moodle_course_id)s
),
ses AS (
    SELECT id FROM cursos_sincronico.sesiones
    WHERE curso_id = (SELECT id FROM curso)
),
total AS (SELECT count(*) AS n FROM ses)
SELECT
    e.moodle_user_id, e.rut, e.email, e.nombre, e.apellido,
    t.n AS total_sesiones,
    count(a.id) FILTER (WHERE a.presente OR a.justificado) AS sesiones_asistidas,
    CASE WHEN t.n > 0
         THEN round(count(a.id) FILTER (WHERE a.presente OR a.justificado)::numeric / t.n * 100, 1)
         ELSE NULL END AS pct_asistencia,
    (SELECT asistencia_minima FROM curso) AS asistencia_minima
FROM cursos_sincronico.inscripciones i
JOIN cursos_sincronico.estudiantes e ON e.id = i.estudiante_id
CROSS JOIN total t
LEFT JOIN cursos_sincronico.asistencia a
       ON a.estudiante_id = e.id AND a.sesion_id IN (SELECT id FROM ses)
WHERE i.curso_id = (SELECT id FROM curso) AND i.activo = TRUE
GROUP BY e.moodle_user_id, e.rut, e.email, e.nombre, e.apellido, t.n
ORDER BY pct_asistencia DESC NULLS LAST
"""

# Query agregada para enriquecer el dashboard: trae por (curso, rut) la
# asistencia de TODOS los cursos sincrónicos en una sola pasada (evita N+1).
# `realizadas` = sesiones cuya fecha ya pasó (las filas de sesiones se crean
# retroactivamente, no existen sesiones futuras en la tabla).
_ASISTENCIA_DASHBOARD_SQL = """
WITH ses_agg AS (
    SELECT curso_id,
           count(*) AS total_sesiones,
           count(*) FILTER (WHERE fecha_inicio <= now()) AS realizadas
    FROM cursos_sincronico.sesiones
    GROUP BY curso_id
)
SELECT c.moodle_course_id, e.rut,
       COALESCE(sa.total_sesiones, 0) AS total_sesiones,
       COALESCE(sa.realizadas, 0)     AS realizadas,
       c.sesiones_planificadas, c.asistencia_minima,
       count(a.id) FILTER (WHERE a.presente OR a.justificado) AS asistidas
FROM cursos_sincronico.cursos c
JOIN cursos_sincronico.inscripciones i ON i.curso_id = c.id AND i.activo = TRUE
JOIN cursos_sincronico.estudiantes e   ON e.id = i.estudiante_id
LEFT JOIN ses_agg sa ON sa.curso_id = c.id
LEFT JOIN cursos_sincronico.asistencia a
       ON a.estudiante_id = e.id
      AND a.sesion_id IN (SELECT id FROM cursos_sincronico.sesiones s WHERE s.curso_id = c.id)
WHERE c.moodle_course_id = ANY(%(ids)s)
GROUP BY c.moodle_course_id, e.rut, sa.total_sesiones, sa.realizadas,
         c.sesiones_planificadas, c.asistencia_minima
"""


def _norm_rut(rut):
    """Normaliza RUT para cruzar entre bases: minúsculas, sin puntos ni espacios."""
    if not rut:
        return ""
    return str(rut).strip().lower().replace(".", "").replace(" ", "")


def _erp_conn():
    return psycopg2.connect(**ERP_PG_DSN)


# ── Lógica para enriquecer el dashboard (progreso=asistencia, riesgo, estado) ──

def _riesgo_sincronico(asistidas, realizadas, faltan, total_planificadas,
                       minimo, curso_terminado):
    """Riesgo por asistencia proyectada: alto/medio/bajo/None.

    - alto:  aun asistiendo a TODO lo que falta ya no alcanza el mínimo.
    - medio: va bajo el mínimo respecto a las clases ya realizadas, pero recuperable.
    - bajo:  va cumpliendo.
    - None:  curso terminado o sin sesiones (igual que un asincrónico vencido).
    """
    if curso_terminado:
        return None
    if total_planificadas <= 0 or realizadas <= 0:
        return None
    pct_maximo = (asistidas + faltan) / total_planificadas * 100
    pct_realizadas = asistidas / realizadas * 100
    if pct_maximo < minimo:
        return "alto"
    if pct_realizadas < minimo:
        return "medio"
    return "bajo"


def _estado_sincronico(calificacion, pct_final, minimo, curso_terminado):
    """Estado A/R/P: aprueba = nota >= 4,0 Y asistencia >= mínimo. En curso → P."""
    if not curso_terminado:
        return "P"
    aprueba_nota = calificacion is not None and calificacion >= NOTA_CORTE
    aprueba_asist = pct_final is not None and pct_final >= minimo
    return "A" if (aprueba_nota and aprueba_asist) else "R"


def _datos_sincronicos_erp(conn, moodle_ids):
    """Una conexión a erp_empresas → (set de ids sincrónicos, dict de asistencia).

    Returns
    -------
    (set[str], dict[(id_moodle:str, rut_norm:str)] -> dict)
        El set son los moodle_course_id que existen en cursos_sincronico.cursos.
        El dict trae por alumno: pct, asistidas, realizadas, faltan,
        total_planificadas, total_sesiones, minimo, curso_terminado.
    """
    ids = [int(m) for m in moodle_ids if str(m).strip().isdigit()]
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute(
        "SELECT moodle_course_id FROM cursos_sincronico.cursos "
        "WHERE moodle_course_id = ANY(%(ids)s)",
        {"ids": ids},
    )
    ids_sinc = {str(r["moodle_course_id"]) for r in cur.fetchall()}

    asistencia = {}
    cur.execute(_ASISTENCIA_DASHBOARD_SQL, {"ids": ids})
    for r in cur.fetchall():
        total_ses = int(r["total_sesiones"] or 0)
        realizadas = int(r["realizadas"] or 0)
        planif = int(r["sesiones_planificadas"] or 0)
        total_plan = max(planif, total_ses)
        faltan = max(0, total_plan - realizadas)
        minimo = (float(r["asistencia_minima"])
                  if r["asistencia_minima"] is not None else ASIST_MIN_DEFAULT)
        curso_terminado = (faltan == 0 and realizadas > 0)
        asistidas = int(r["asistidas"] or 0)
        pct = round(asistidas / total_ses * 100, 1) if total_ses > 0 else None
        key = (str(r["moodle_course_id"]), _norm_rut(r["rut"]))
        asistencia[key] = {
            "pct": pct,
            "asistidas": asistidas,
            "realizadas": realizadas,
            "faltan": faltan,
            "total_planificadas": total_plan,
            "total_sesiones": total_ses,
            "minimo": minimo,
            "curso_terminado": curso_terminado,
        }
    cur.close()
    return ids_sinc, asistencia


def _recomputar_estadisticas(curso):
    """Recalcula las estadísticas del curso tras enriquecer con asistencia."""
    estudiantes = curso.get("estudiantes", [])
    stats = curso.setdefault("estadisticas", {})
    progresos = [e["progreso"] for e in estudiantes if e.get("progreso") is not None]
    stats["promedio_progreso"] = round(sum(progresos) / len(progresos), 1) if progresos else 0.0
    stats["aprobados"] = sum(1 for e in estudiantes if e.get("estado") == "A")
    stats["reprobados"] = sum(1 for e in estudiantes if e.get("estado") == "R")
    stats["en_proceso"] = sum(1 for e in estudiantes if e.get("estado") == "P")
    stats["riesgo_alto"] = sum(1 for e in estudiantes if e.get("riesgo") == "alto")
    stats["riesgo_medio"] = sum(1 for e in estudiantes if e.get("riesgo") == "medio")
    stats["riesgo_bajo"] = sum(1 for e in estudiantes if e.get("riesgo") == "bajo")


def enriquecer_sincronicos(cursos_lista):
    """Marca cada curso con `es_sincronico` y, para los sincrónicos, reemplaza
    el progreso por la asistencia y recalcula estado/riesgo.

    Es degradante: si erp_empresas no responde, marca todo como asincrónico y
    deja el dashboard intacto (no lanza). Los cursos asincrónicos no se tocan.
    """
    if not cursos_lista:
        return

    moodle_ids = [c.get("id_moodle") for c in cursos_lista if c.get("id_moodle") is not None]
    try:
        conn = _erp_conn()
        try:
            ids_sinc, asistencia = _datos_sincronicos_erp(conn, moodle_ids)
        finally:
            conn.close()
    except Exception as e:
        logger.warning("Asistencia sincrónica no disponible (%s); dashboard sin cambios", e)
        for c in cursos_lista:
            c["es_sincronico"] = False
        return

    for curso in cursos_lista:
        mid = str(curso.get("id_moodle"))
        es_sinc = mid in ids_sinc
        curso["es_sincronico"] = es_sinc
        if not es_sinc:
            continue

        for est in curso.get("estudiantes", []):
            a = asistencia.get((mid, _norm_rut(est.get("rut"))))
            if not a:
                # Alumno en Moodle pero sin inscripción sincrónica (raro):
                # el progreso de Moodle no aplica a un curso sincrónico.
                est["progreso"] = None
                est["asistencia"] = None
                est["riesgo"] = ""
                est["estado"] = "P"
                continue
            # progreso = % de asistencia sobre el total de sesiones registradas
            # (cumplimiento actual). Hoy total_sesiones == realizadas porque las
            # sesiones se crean retroactivamente (no hay sesiones futuras en la BD).
            est["progreso"] = a["pct"]
            pct_total = (round(a["asistidas"] / a["total_planificadas"] * 100, 1)
                         if a["total_planificadas"] else None)
            est["asistencia"] = {
                "asistidas": a["asistidas"],
                "realizadas": a["realizadas"],
                "total_sesiones": a["total_sesiones"],
                "planificadas": a["total_planificadas"],
                "pct": a["pct"],            # sobre el total de sesiones registradas (cumplimiento)
                "pct_total": pct_total,     # sobre el total programado (avance)
                "minimo": a["minimo"],
            }
            est["riesgo"] = _riesgo_sincronico(
                a["asistidas"], a["realizadas"], a["faltan"],
                a["total_planificadas"], a["minimo"], a["curso_terminado"],
            ) or ""
            est["estado"] = _estado_sincronico(
                est.get("calificacion"), a["pct"], a["minimo"], a["curso_terminado"],
            )

        _recomputar_estadisticas(curso)


def listar_cursos_sincronicos():
    """Lista los cursos sincrónicos (los que existen en cursos_sincronico.cursos).

    Returns
    -------
    list[dict] con keys: moodle_course_id (int), nombre (str),
        asistencia_minima (float|None).
    """
    conn = _erp_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT moodle_course_id, nombre, asistencia_minima "
            "FROM cursos_sincronico.cursos "
            "WHERE moodle_course_id IS NOT NULL "
            "ORDER BY moodle_course_id"
        )
        rows = cur.fetchall()
        cur.close()
        return [
            {
                "moodle_course_id": int(r["moodle_course_id"]),
                "nombre": r["nombre"] or "",
                "asistencia_minima": (
                    float(r["asistencia_minima"])
                    if r["asistencia_minima"] is not None else None
                ),
            }
            for r in rows
        ]
    finally:
        conn.close()


def _asistencia_por_curso(conn, moodle_course_id):
    """Ejecuta la query canónica de asistencia para un curso sincrónico."""
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(_ASISTENCIA_SQL, {"moodle_course_id": moodle_course_id})
    rows = cur.fetchall()
    cur.close()
    return rows


def _notas_por_curso(moodle_course_ids):
    """Trae notas/estado académico desde tecnipro_reportes para varios cursos.

    Returns
    -------
    dict[(id_moodle:str, rut_norm:str)] -> dict con calificacion, estado,
        progreso, evaluaciones, nombre, email.
    """
    if not moodle_course_ids:
        return {}

    engine = get_engine()
    if engine is None:
        if not init_db():
            logger.warning("No hay conexión a tecnipro_reportes para notas")
            return {}
        engine = get_engine()

    ids_str = [str(c) for c in moodle_course_ids]
    notas = {}
    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT c.id_moodle, e.rut, e.nombre, e.email,
                       i.calificacion, i.estado, i.progreso,
                       i.evaluaciones_rendidas, i.total_evaluaciones
                FROM inscripciones i
                JOIN cursos c ON c.id = i.curso_id
                JOIN estudiantes e ON e.id = i.estudiante_id
                WHERE c.id_moodle IN :ids
            """).bindparams(bindparam("ids", expanding=True)),
            {"ids": ids_str},
        ).fetchall()

    for r in rows:
        key = (str(r.id_moodle), _norm_rut(r.rut))
        notas[key] = {
            "nombre": r.nombre or "",
            "email": r.email or "",
            "calificacion": float(r.calificacion) if r.calificacion is not None else None,
            "estado": r.estado or None,
            "progreso": float(r.progreso) if r.progreso is not None else None,
            "evaluaciones_rendidas": r.evaluaciones_rendidas or 0,
            "total_evaluaciones": r.total_evaluaciones or 0,
        }
    return notas


def _combinar_alumno(asist, nota):
    """Combina la fila de asistencia (sincrónico) con la nota Moodle (si existe)."""
    pct = asist.get("pct_asistencia")
    pct = float(pct) if pct is not None else None
    minimo = asist.get("asistencia_minima")
    minimo = float(minimo) if minimo is not None else None

    # Estado de asistencia
    if pct is None:
        asistencia_estado = "sin_sesiones"   # curso aún sin sesiones
        aprueba_asistencia = None
    elif minimo is None:
        asistencia_estado = "sin_umbral"     # curso sin asistencia_minima definida
        aprueba_asistencia = None
    elif pct >= minimo:
        asistencia_estado = "aprobada"
        aprueba_asistencia = True
    else:
        asistencia_estado = "reprobada"
        aprueba_asistencia = False

    # Dimensión nota (usa el estado académico oficial del dashboard A/R/P)
    estado_nota = nota.get("estado") if nota else None
    calificacion = nota.get("calificacion") if nota else None
    aprueba_nota = estado_nota == "A"

    # Estado final combinado (Aprobado = nota aprobada Y asistencia aprobada)
    if nota is None:
        estado_final = "sin_nota"
    elif aprueba_asistencia is None:
        # Asistencia no evaluable aún → reflejar solo la dimensión académica
        estado_final = {
            "A": "aprobado_nota",
            "R": "reprobado_nota",
        }.get(estado_nota, "en_proceso")
    elif aprueba_nota and aprueba_asistencia:
        estado_final = "aprobado"
    elif estado_nota == "R" or aprueba_asistencia is False:
        estado_final = "reprobado"
    else:
        estado_final = "en_proceso"

    return {
        "rut": asist.get("rut") or "",
        "moodle_user_id": asist.get("moodle_user_id"),
        "nombre": (nota.get("nombre") if nota else None)
                  or " ".join(filter(None, [asist.get("nombre"), asist.get("apellido")])).strip(),
        "email": (nota.get("email") if nota else None) or asist.get("email") or "",
        "calificacion": calificacion,
        "estado_nota": estado_nota,
        "total_sesiones": int(asist.get("total_sesiones") or 0),
        "sesiones_asistidas": int(asist.get("sesiones_asistidas") or 0),
        "pct_asistencia": pct,
        "asistencia_minima": minimo,
        "asistencia_estado": asistencia_estado,
        "aprueba_asistencia": aprueba_asistencia,
        "estado_final": estado_final,
    }


def get_dashboard_sincronico(cursos_usuario=None):
    """Construye los datos de la pestaña "Cursos Sincrónicos".

    Parameters
    ----------
    cursos_usuario : list[int] | None
        IDs de cursos Moodle que el usuario puede ver. None = admin (ve todos).

    Returns
    -------
    dict con keys: metadata, cursos. Cada curso trae resumen + alumnos.
    """
    sincronicos = listar_cursos_sincronicos()

    # Filtro de visibilidad por usuario (mismo criterio que el dashboard).
    if cursos_usuario is not None:
        permitidos = {int(c) for c in cursos_usuario}
        sincronicos = [c for c in sincronicos if c["moodle_course_id"] in permitidos]

    if not sincronicos:
        return {"metadata": {"total_cursos": 0}, "cursos": []}

    ids = [c["moodle_course_id"] for c in sincronicos]
    notas = _notas_por_curso(ids)

    cursos_out = []
    conn = _erp_conn()
    try:
        for curso in sincronicos:
            mid = curso["moodle_course_id"]
            filas = _asistencia_por_curso(conn, mid)

            alumnos = []
            for asist in filas:
                nota = notas.get((str(mid), _norm_rut(asist.get("rut"))))
                alumnos.append(_combinar_alumno(asist, nota))

            # Orden: por % asistencia desc, luego nombre
            alumnos.sort(
                key=lambda a: (
                    a["pct_asistencia"] is not None,
                    a["pct_asistencia"] or 0,
                ),
                reverse=True,
            )

            total_sesiones = max((a["total_sesiones"] for a in alumnos), default=0)
            pcts = [a["pct_asistencia"] for a in alumnos if a["pct_asistencia"] is not None]
            resumen = {
                "total_alumnos": len(alumnos),
                "total_sesiones": total_sesiones,
                "asistencia_minima": curso["asistencia_minima"],
                "promedio_asistencia": round(sum(pcts) / len(pcts), 1) if pcts else None,
                "aprueban_asistencia": sum(1 for a in alumnos if a["aprueba_asistencia"] is True),
                "reprueban_asistencia": sum(1 for a in alumnos if a["aprueba_asistencia"] is False),
                "aprobados_final": sum(1 for a in alumnos if a["estado_final"] == "aprobado"),
                "reprobados_final": sum(1 for a in alumnos if a["estado_final"] == "reprobado"),
                "sin_nota": sum(1 for a in alumnos if a["estado_final"] == "sin_nota"),
            }

            cursos_out.append({
                "moodle_course_id": mid,
                "nombre": curso["nombre"],
                "asistencia_minima": curso["asistencia_minima"],
                "total_sesiones": total_sesiones,
                "resumen": resumen,
                "alumnos": alumnos,
            })
    finally:
        conn.close()

    # Orden de cursos por nombre
    cursos_out.sort(key=lambda c: c["nombre"].lower())

    return {
        "metadata": {
            "total_cursos": len(cursos_out),
            "total_alumnos": sum(len(c["alumnos"]) for c in cursos_out),
        },
        "cursos": cursos_out,
    }

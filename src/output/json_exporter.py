"""Genera JSON consolidado para el dashboard."""

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from config import settings

logger = logging.getLogger(__name__)


def exportar_json(df, output_path=None, fecha_sence=None):
    """Genera el JSON consolidado a partir del DataFrame procesado.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame con todos los campos calculados.
    output_path : Path | str | None
        Ruta del archivo de salida.  Si es ``None`` se usa
        ``settings.OUTPUT_PATH / "datos_procesados.json"``.

    Returns
    -------
    dict
        Estructura del JSON generado.
    """
    if output_path is None:
        output_path = settings.OUTPUT_PATH / "datos_procesados.json"

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    estructura = _construir_estructura(df, fecha_sence=fecha_sence)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(estructura, f, ensure_ascii=False, indent=2, default=str)

    logger.info("JSON exportado a %s", output_path)
    return estructura


def _cargar_metadatos_sence():
    """Carga metadatos_sence.json si existe."""
    ruta = settings.SENCE_METADATOS_PATH
    if not ruta.exists():
        return {}
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Error leyendo metadatos SENCE: %s", e)
        return {}


def _construir_estructura(df, fecha_sence=None):
    """Construye el dict con la estructura esperada por el dashboard."""
    metadatos_sence = _cargar_metadatos_sence()
    cursos_dict = {}
    # Safety net: rastrear estudiantes ya agregados por (curso, rut)
    _seen_students = set()

    for _, row in df.iterrows():
        nombre_corto = str(row.get("nombre_corto", "")).strip()
        if not nombre_corto or nombre_corto in ("nan", ""):
            continue

        if nombre_corto not in cursos_dict:
            cursos_dict[nombre_corto] = {
                "id_moodle": nombre_corto,
                "id_sence": _safe_str(row.get("IDSence", "")),
                "nombre": _safe_str(row.get("nombre_curso", "")),
                "nombre_corto": nombre_corto,
                "categoria": _safe_str(row.get("categoria", "")),
                "modalidad": _safe_str(row.get("Modalidad", "")),  # NUEVO
                "fecha_inicio": _format_date(row.get("fecha_inicio_dt")),
                "fecha_fin": _format_date(row.get("fecha_fin_dt")),
                "estado": _safe_str(row.get("estado_curso", "active")),
                "dias_restantes": _safe_int(row.get("dias_para_termino")),
                "comprador": {
                    "nombre": _safe_str(row.get("comprador_nombre", "")),
                    "empresa": _safe_str(row.get("empresa", "")),
                    "email": _safe_str(row.get("email_comprador", "")),
                },
                "estudiantes": [],
            }
            # Agregar metadatos SENCE si existen para este curso
            id_sence_curso = _safe_str(row.get("IDSence", ""))
            meta_sence = metadatos_sence.get(id_sence_curso, {})
            if meta_sence:
                cursos_dict[nombre_corto]["fecha_termino_sence"] = meta_sence.get("fecha_termino_sence")
                cursos_dict[nombre_corto]["fecha_inicio_sence"] = meta_sence.get("fecha_inicio_sence")
                cursos_dict[nombre_corto]["estado_dj_otec"] = meta_sence.get("estado_dj_otec", "")
                cursos_dict[nombre_corto]["estado_curso_sence"] = meta_sence.get("estado_curso_sence", "")

        # Solo agregar estudiantes con nombre (y no duplicados)
        nombre_participante = _safe_str(row.get("Nombre completo Participante", ""))
        rut_estudiante = _safe_str(row.get("ID del Usuario", ""))
        student_key = (nombre_corto, rut_estudiante)

        if nombre_participante and student_key not in _seen_students:
            _seen_students.add(student_key)
            id_sence_est = _safe_str(row.get("IDSence", ""))
            estudiante = {
                "id": _safe_str(row.get("ID del Usuario", "")),
                "rut": _safe_str(row.get("ID del Usuario", "")),
                "nombre": nombre_participante,
                "email": _safe_str(row.get("Dirección de correo", "")),
                "progreso": _safe_float(row.get("Progreso del estudiante")),
                "calificacion": _safe_float(row.get("Calificación")),
                "evaluaciones_rendidas": _safe_int(row.get("Evaluaciones Rendidas", 0)),  # NUEVO
                "total_evaluaciones": _safe_int(row.get("Total Evaluaciones", 0)),  # NUEVO
                "promedio_evaluadas": _safe_float(row.get("Promedio Evaluadas")),  # NUEVO
                "resumen_evaluaciones": _safe_str(row.get("Resumen Evaluaciones", "0/0")),  # NUEVO
                "ultimo_acceso": _format_date(row.get("ultimo_acceso_dt")),
                "dias_sin_ingreso": _safe_int(row.get("dias_sin_ingreso")),
                "dias_sin_acceso": _safe_int(row.get("dias_sin_ingreso")),
                "estado": _safe_str(row.get("estado_participante", "")),
                "riesgo": _safe_str(row.get("riesgo", "")),
                "sence": {
                    "id_sence": id_sence_est,
                    "n_ingresos": _safe_int(row.get("N_Ingresos", 0)),
                    "estado": _safe_str(row.get("estado_sence", "NO_APLICA")),
                    "declaracion_jurada": _safe_str(row.get("DJ", "")),
                    "estado_dj": _safe_str(row.get("DJ", "")),
                },
            }
            cursos_dict[nombre_corto]["estudiantes"].append(estudiante)

    # Calcular estadísticas por curso
    cursos_lista = []
    total_estudiantes = 0
    for curso in cursos_dict.values():
        ests = curso["estudiantes"]
        n = len(ests)
        total_estudiantes += n

        # Actualizar id_sence del curso: tomar el primer no vacío de los estudiantes
        if not curso["id_sence"]:
            for e in ests:
                if e["sence"]["id_sence"]:
                    curso["id_sence"] = e["sence"]["id_sence"]
                    break

        progresos = [e["progreso"] for e in ests if e["progreso"] is not None]
        califs = [e["calificacion"] for e in ests if e["calificacion"] is not None]
        proms_eval = [
            e["promedio_evaluadas"] for e in ests if e["promedio_evaluadas"] is not None
        ]

        # Avance temporal (% del tiempo transcurrido del curso)
        avance_temporal = None
        if curso.get("fecha_inicio") and curso.get("fecha_fin"):
            try:
                inicio = date.fromisoformat(curso["fecha_inicio"])
                fin = date.fromisoformat(curso["fecha_fin"])
                total_dias = (fin - inicio).days
                if total_dias > 0:
                    avance_temporal = round(
                        max(0, min(100, ((date.today() - inicio).days / total_dias) * 100))
                    )
            except (ValueError, TypeError):
                pass

        # Estadísticas SENCE detalladas
        con_sence = [e for e in ests if e["sence"]["id_sence"]]
        sin_sence = [e for e in ests if not e["sence"]["id_sence"]]
        con_sence_conect = [
            e for e in con_sence if (e["sence"]["n_ingresos"] or 0) > 0
        ]
        con_sence_en_plat = sum(
            1 for e in con_sence
            if (not e["sence"]["n_ingresos"] or e["sence"]["n_ingresos"] == 0)
            and (e["ultimo_acceso"] or (e["progreso"] or 0) > 0)
        )
        sin_sence_conect = sum(
            1 for e in sin_sence
            if e["ultimo_acceso"] or (e["progreso"] or 0) > 0
        )

        # IDs SENCE únicos del curso
        ids_sence = sorted(
            {e["sence"]["id_sence"] for e in ests if e["sence"]["id_sence"]}
        )

        # Enriquecer con metadatos SENCE (buscar por todos los IDs del curso)
        if metadatos_sence and not curso.get("fecha_termino_sence"):
            for sid in ids_sence:
                meta = metadatos_sence.get(sid, {})
                if meta.get("fecha_termino_sence"):
                    curso["fecha_termino_sence"] = meta.get("fecha_termino_sence")
                    curso["fecha_inicio_sence"] = meta.get("fecha_inicio_sence")
                    curso["estado_dj_otec"] = meta.get("estado_dj_otec", "")
                    curso["estado_curso_sence"] = meta.get("estado_curso_sence", "")
                    break

        curso["estadisticas"] = {
            "total_estudiantes": n,
            "promedio_progreso": round(sum(progresos) / len(progresos), 1) if progresos else 0.0,
            "promedio_calificacion": round(sum(califs) / len(califs), 1) if califs else 0.0,
            "promedio_evaluadas": round(sum(proms_eval) / len(proms_eval), 1) if proms_eval else 0.0,
            "aprobados": sum(1 for e in ests if e["estado"] == "A"),
            "reprobados": sum(1 for e in ests if e["estado"] == "R"),
            "en_proceso": sum(1 for e in ests if e["estado"] == "P"),
            "riesgo_alto": sum(1 for e in ests if e["riesgo"] == "alto"),
            "riesgo_medio": sum(1 for e in ests if e["riesgo"] == "medio"),
            "riesgo_bajo": sum(1 for e in ests if e["riesgo"] == "bajo"),
            "conectados_sence": sum(
                1 for e in ests if e["sence"]["estado"] == "CONECTADO"
            ),
            "avance_temporal": avance_temporal,
            "con_sence": len(con_sence),
            "sin_sence": len(sin_sence),
            "con_sence_conectados": len(con_sence_conect),
            "con_sence_faltantes": len(con_sence) - len(con_sence_conect),
            "con_sence_en_plat_no_sence": con_sence_en_plat,
            "sin_sence_conectados_plat": sin_sence_conect,
            "sin_sence_sin_conectar": len(sin_sence) - sin_sence_conect,
            "pct_con_sence": round((len(con_sence_conect) / len(con_sence)) * 100) if con_sence else 0,
            "pct_sin_sence": round((sin_sence_conect / len(sin_sence)) * 100) if sin_sence else 0,
            "ids_sence": ids_sence,
            "total_dj_emitidas": sum(
                1 for e in ests
                if e["sence"]["id_sence"] and e["sence"]["estado_dj"] in ("Emitida", "Firmada", "Descargada")
            ),
            "total_dj_pendientes": sum(
                1 for e in ests
                if e["sence"]["id_sence"]
                and e["sence"]["estado_dj"] not in ("Emitida", "Firmada", "Descargada")
                and _sence_curso_terminado(curso.get("fecha_termino_sence"))
            ),
            "total_evaluaciones": max((e["total_evaluaciones"] or 0) for e in ests) if ests else 0,
            "distribucion_evaluaciones": _calcular_distribucion_evaluaciones(ests),
        }
        cursos_lista.append(curso)

    # Totales globales pre-calculados
    total_aprobados = sum(c["estadisticas"]["aprobados"] for c in cursos_lista)
    total_reprobados = sum(c["estadisticas"]["reprobados"] for c in cursos_lista)
    total_en_proceso = sum(c["estadisticas"]["en_proceso"] for c in cursos_lista)
    total_riesgo_alto = sum(c["estadisticas"]["riesgo_alto"] for c in cursos_lista)
    total_riesgo_medio = sum(c["estadisticas"]["riesgo_medio"] for c in cursos_lista)
    total_riesgo_bajo = sum(c["estadisticas"]["riesgo_bajo"] for c in cursos_lista)
    total_inactivos_7d = sum(
        sum(1 for e in c["estudiantes"] if (e.get("dias_sin_ingreso") or 0) > 7)
        for c in cursos_lista
    )
    total_conectados_sence = sum(c["estadisticas"]["conectados_sence"] for c in cursos_lista)
    total_dj_emitidas = sum(c["estadisticas"].get("total_dj_emitidas", 0) for c in cursos_lista)
    total_dj_pendientes = sum(c["estadisticas"].get("total_dj_pendientes", 0) for c in cursos_lista)
    categorias = sorted({c["categoria"] for c in cursos_lista if c.get("categoria")})

    # Cierres próximos (cursos que cierran en los próximos 15 días)
    hoy = date.today()
    limite = hoy.toordinal() + 15
    cierres_proximos = []
    for c in cursos_lista:
        if not c.get("fecha_fin"):
            continue
        try:
            fecha_fin = date.fromisoformat(c["fecha_fin"])
        except (ValueError, TypeError):
            continue
        dias = (fecha_fin - hoy).days
        if 0 <= dias <= 15:
            cierres_proximos.append({
                "id_moodle": c["id_moodle"],
                "nombre": c["nombre"],
                "fecha_fin": c["fecha_fin"],
                "dias": dias,
            })
    cierres_proximos.sort(key=lambda x: x["dias"])

    fecha_moodle = datetime.now(timezone.utc).isoformat(timespec="seconds")
    estructura = {
        "metadata": {
            "fecha_procesamiento": fecha_moodle,
            "fecha_moodle": fecha_moodle,
            "fecha_sence": fecha_sence,
            "total_cursos": len(cursos_lista),
            "total_estudiantes": total_estudiantes,
            "total_aprobados": total_aprobados,
            "total_reprobados": total_reprobados,
            "total_en_proceso": total_en_proceso,
            "total_riesgo_alto": total_riesgo_alto,
            "total_riesgo_medio": total_riesgo_medio,
            "total_riesgo_bajo": total_riesgo_bajo,
            "total_inactivos_7d": total_inactivos_7d,
            "total_conectados_sence": total_conectados_sence,
            "total_dj_emitidas": total_dj_emitidas,
            "total_dj_pendientes": total_dj_pendientes,
            "categorias": categorias,
            "cierres_proximos": cierres_proximos,
            "version": "1.0",
        },
        "cursos": cursos_lista,
    }
    return estructura


def _calcular_distribucion_evaluaciones(estudiantes):
    """Calcula distribución de evaluaciones rendidas para un curso."""
    if not estudiantes:
        return {"total_evaluaciones": 0, "distribucion": []}
    total_evals = max((e.get("total_evaluaciones") or 0) for e in estudiantes)
    if total_evals == 0:
        return {"total_evaluaciones": 0, "distribucion": []}
    conteo = {i: 0 for i in range(total_evals + 1)}
    for e in estudiantes:
        rendidas = min(e.get("evaluaciones_rendidas") or 0, total_evals)
        conteo[rendidas] = conteo.get(rendidas, 0) + 1
    total = len(estudiantes)
    distribucion = [
        {
            "rendidas": i,
            "cantidad": conteo[i],
            "porcentaje": round((conteo[i] / total) * 100, 1) if total > 0 else 0.0,
        }
        for i in range(total_evals + 1)
    ]
    return {"total_evaluaciones": total_evals, "distribucion": distribucion}


def _sence_curso_terminado(fecha_termino_sence):
    """True si la fecha de término SENCE ya pasó (o es hoy)."""
    if not fecha_termino_sence:
        return False
    try:
        from datetime import date
        return date.fromisoformat(str(fecha_termino_sence)) <= date.today()
    except (ValueError, TypeError):
        return False


def _safe_str(val):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    s = str(val).strip()
    return "" if s in ("nan", "None", "NaT") else s


def _safe_float(val):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    try:
        return round(float(val), 1)
    except (ValueError, TypeError):
        return None


def _safe_int(val):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


def _format_date(dt):
    if dt is None or (isinstance(dt, float) and pd.isna(dt)) or pd.isna(dt):
        return None
    try:
        return dt.strftime("%Y-%m-%d")
    except (AttributeError, ValueError):
        return None

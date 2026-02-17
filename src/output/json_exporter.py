"""Genera JSON consolidado para el dashboard."""

import json
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

from config import settings

logger = logging.getLogger(__name__)


def exportar_json(df, output_path=None):
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

    estructura = _construir_estructura(df)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(estructura, f, ensure_ascii=False, indent=2, default=str)

    logger.info("JSON exportado a %s", output_path)
    return estructura


def _construir_estructura(df):
    """Construye el dict con la estructura esperada por el dashboard."""
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

        # Solo agregar estudiantes con nombre (y no duplicados)
        nombre_participante = _safe_str(row.get("Nombre completo Participante", ""))
        rut_estudiante = _safe_str(row.get("ID del Usuario", ""))
        student_key = (nombre_corto, rut_estudiante)

        if nombre_participante and student_key not in _seen_students:
            _seen_students.add(student_key)
            id_sence_est = _safe_str(row.get("IDSence", ""))
            estudiante = {
                "id": _safe_str(row.get("ID del Usuario", "")),
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
                "estado": _safe_str(row.get("estado_participante", "")),
                "riesgo": _safe_str(row.get("riesgo", "")),
                "sence": {
                    "id_sence": id_sence_est,
                    "n_ingresos": _safe_int(row.get("N_Ingresos", 0)),
                    "estado": _safe_str(row.get("estado_sence", "NO_APLICA")),
                    "declaracion_jurada": _safe_str(row.get("DJ", "")),
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

        curso["estadisticas"] = {
            "total_estudiantes": n,
            "promedio_progreso": round(sum(progresos) / len(progresos), 1) if progresos else 0.0,
            "promedio_calificacion": round(sum(califs) / len(califs), 1) if califs else 0.0,
            "aprobados": sum(1 for e in ests if e["estado"] == "A"),
            "reprobados": sum(1 for e in ests if e["estado"] == "R"),
            "en_proceso": sum(1 for e in ests if e["estado"] == "P"),
            "riesgo_alto": sum(1 for e in ests if e["riesgo"] == "alto"),
            "riesgo_medio": sum(1 for e in ests if e["riesgo"] == "medio"),
            "conectados_sence": sum(
                1 for e in ests if e["sence"]["estado"] == "CONECTADO"
            ),
        }
        cursos_lista.append(curso)

    estructura = {
        "metadata": {
            "fecha_procesamiento": datetime.now().isoformat(timespec="seconds"),
            "total_cursos": len(cursos_lista),
            "total_estudiantes": total_estudiantes,
            "version": "1.0",
        },
        "cursos": cursos_lista,
    }
    return estructura


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

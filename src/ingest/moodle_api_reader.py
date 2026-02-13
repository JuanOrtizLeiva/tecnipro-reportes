"""Lector de datos Moodle vía API REST.

Este módulo reemplaza la lectura de Greporte.csv + Dreporte.csv
consultando directamente la API REST de Moodle.
"""

import logging
from datetime import datetime

import pandas as pd

from config import settings
from src.ingest import moodle_api_client as api

logger = logging.getLogger(__name__)

# Mapeo de meses en español
_MESES_ES = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril",
    5: "mayo", 6: "junio", 7: "julio", 8: "agosto",
    9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre"
}

# Mapeo de días de la semana en español
_DIAS_SEMANA_ES = {
    0: "lunes", 1: "martes", 2: "miércoles", 3: "jueves",
    4: "viernes", 5: "sábado", 6: "domingo"
}


def leer_datos_moodle() -> pd.DataFrame:
    """Lee datos de cursos y estudiantes desde Moodle API REST.

    Retorna un DataFrame con las MISMAS columnas que el merge actual
    de Greporte + Dreporte, para mantener compatibilidad con el pipeline.

    Returns
    -------
    pd.DataFrame
        DataFrame con columnas compatibles con el pipeline existente.
        Incluye cursos, estudiantes, progreso, notas, etc.

    Raises
    ------
    RuntimeError
        Si hay error crítico en la lectura de datos
    """
    logger.info("Iniciando lectura desde Moodle API")

    # 1. Obtener datos maestros (categorías y cursos)
    try:
        categories = api.get_categories()
        logger.info("Categorías obtenidas: %d", len(categories))
    except Exception as e:
        logger.error("Error obteniendo categorías: %s", e)
        raise RuntimeError("No se pueden obtener categorías de Moodle") from e

    try:
        courses = api.get_courses(settings.MOODLE_CATEGORY_IDS)
        logger.info(
            "Cursos obtenidos: %d en categorías %s",
            len(courses), settings.MOODLE_CATEGORY_IDS
        )
    except Exception as e:
        logger.error("Error obteniendo cursos: %s", e)
        raise RuntimeError("No se pueden obtener cursos de Moodle") from e

    if not courses:
        logger.warning("No se encontraron cursos en las categorías especificadas")
        # Retornar DataFrame vacío con columnas esperadas
        return pd.DataFrame(columns=_get_column_names())

    # 2. Procesar cada curso
    filas = []
    total_estudiantes = 0

    for idx, curso in enumerate(courses, 1):
        curso_id = curso.get("id")
        curso_nombre = curso.get("fullname", "")
        logger.info(
            "[%d/%d] Procesando curso: %s (ID: %d)",
            idx, len(courses), curso_nombre, curso_id
        )

        try:
            # Obtener estudiantes del curso
            estudiantes = api.get_enrolled_users(curso_id)
            logger.debug("  Estudiantes en curso %d: %d", curso_id, len(estudiantes))

            if not estudiantes:
                # Curso sin estudiantes: agregar fila vacía
                fila_vacia = _construir_fila_curso_vacio(curso, categories)
                filas.append(fila_vacia)
                continue

            # Obtener notas de todos los estudiantes del curso
            grades = api.get_grades(curso_id)

            # Para cada estudiante: obtener progreso y construir fila
            for est in estudiantes:
                try:
                    userid = est.get("id")
                    progreso = api.get_completion_status(curso_id, userid)
                    grade_data = grades.get(userid, {
                        "nota_final": None,
                        "evaluaciones_rendidas": 0,
                        "total_evaluaciones": 0,
                        "promedio_evaluadas": None,
                        "resumen_evaluaciones": "0/0"
                    })

                    fila = _construir_fila(curso, est, progreso, grade_data, categories)
                    filas.append(fila)
                    total_estudiantes += 1

                except Exception as e:
                    logger.warning(
                        "  Error procesando estudiante %s en curso %d: %s",
                        est.get("fullname", "?"), curso_id, e
                    )
                    # Continuar con el siguiente estudiante

        except Exception as e:
            logger.error("Error procesando curso %d (%s): %s", curso_id, curso_nombre, e)
            # Continuar con el siguiente curso

    # 3. Construir DataFrame
    if not filas:
        logger.warning("No se generaron filas. Retornando DataFrame vacío")
        return pd.DataFrame(columns=_get_column_names())

    df = pd.DataFrame(filas)

    logger.info(
        "DataFrame construido: %d cursos, %d estudiantes, %d filas totales",
        len(courses), total_estudiantes, len(df)
    )

    return df


def _construir_fila(
    curso: dict,
    estudiante: dict,
    progreso: float,
    grade_data: dict,
    categories: dict[int, str]
) -> dict:
    """Construye una fila del DataFrame con todos los campos del pipeline.

    Parameters
    ----------
    curso : dict
        Datos del curso desde Moodle API
    estudiante : dict
        Datos del estudiante desde Moodle API
    progreso : float
        Porcentaje de progreso (0-100)
    grade_data : dict
        Datos de calificación: {
            'nota_final': float | None,
            'evaluaciones_rendidas': int,
            'total_evaluaciones': int,
            'promedio_evaluadas': float | None,
            'resumen_evaluaciones': str
        }
    categories : dict
        Mapa de categorías {id: nombre}

    Returns
    -------
    dict
        Fila con todas las columnas del DataFrame
    """
    # Extraer datos del curso
    nombre_corto = str(curso.get("shortname", "")).strip().lower()
    nombre_completo = str(curso.get("fullname", "")).strip()
    categoria_id = curso.get("categoryid")
    categoria_nombre = categories.get(categoria_id, "")

    # Determinar modalidad según categoría
    # Categoría 6 → Asincrónico, Categoría 12 → Sincrónico
    if categoria_id == 6:
        modalidad = "Asincrónico"
    elif categoria_id == 12:
        modalidad = "Sincrónico"
    else:
        # Fallback: intentar extraer del nombre de la categoría
        if "asincr" in categoria_nombre.lower():
            modalidad = "Asincrónico"
        elif "sincr" in categoria_nombre.lower():
            modalidad = "Sincrónico"
        else:
            modalidad = categoria_nombre  # Usar el nombre de la categoría como está

    # Convertir fechas Unix a formato largo español
    fecha_inicio = _unix_to_fecha_espanol(curso.get("startdate", 0))
    fecha_fin = _unix_to_fecha_espanol(curso.get("enddate", 0))

    # Extraer datos del estudiante
    nombre_participante = str(estudiante.get("fullname", "")).strip().title()
    rut = str(estudiante.get("username", "")).strip().lower()
    email = str(estudiante.get("email", "")).strip().lower()
    ultimo_acceso = _unix_to_fecha_espanol(estudiante.get("lastcourseaccess", 0))

    # Extraer IDSence del primer grupo (si existe)
    groups = estudiante.get("groups", [])
    id_sence = ""
    if groups and len(groups) > 0:
        id_sence = str(groups[0].get("name", "")).strip()

    # Construir LLave para merge con SENCE
    llave = rut
    if id_sence:
        llave = f"{rut}{id_sence}"

    # Extraer datos de calificación
    calificacion = grade_data.get("nota_final")
    evaluaciones_rendidas = grade_data.get("evaluaciones_rendidas", 0)
    total_evaluaciones = grade_data.get("total_evaluaciones", 0)
    promedio_evaluadas = grade_data.get("promedio_evaluadas")
    resumen_evaluaciones = grade_data.get("resumen_evaluaciones", "0/0")

    # Construir fila con TODAS las columnas esperadas por el pipeline
    fila = {
        # ── Campos del curso ────────────────────────────────
        "nombre_curso": nombre_completo,
        "nombre_corto": nombre_corto,
        "Nombre completo del curso": nombre_completo,
        "Nombre corto del curso": nombre_corto,
        "Fecha de inicio del curso": fecha_inicio,
        "Fecha de finalización del curso": fecha_fin,
        "Nombre de la categoría": categoria_nombre,
        "categoria": categoria_nombre,
        "Modalidad": modalidad,  # NUEVO

        # ── Campos del estudiante ───────────────────────────
        "Nombre completo Participante": nombre_participante,
        "ID del Usuario": rut,
        "Dirección de correo": email,
        "Rol": "Estudiante",  # Ya filtrado en get_enrolled_users

        # ── Progreso y notas ────────────────────────────────
        "Progreso del estudiante": progreso,
        "Calificación": calificacion,
        "Último acceso al curso": ultimo_acceso,

        # ── Evaluaciones (NUEVO) ────────────────────────────
        "Evaluaciones Rendidas": evaluaciones_rendidas,
        "Total Evaluaciones": total_evaluaciones,
        "Promedio Evaluadas": promedio_evaluadas,
        "Resumen Evaluaciones": resumen_evaluaciones,

        # ── SENCE (se llenará después con merge) ────────────
        "IDSence": id_sence,
        "LLave": llave,
        "N_Ingresos": 0,  # Se llena con merge SENCE
        "DJ": "",  # Se llena con merge SENCE

        # ── Para compatibilidad con merge ───────────────────
        "Nombre corto del curso con enlace": nombre_corto,
    }

    return fila


def _construir_fila_curso_vacio(curso: dict, categories: dict[int, str]) -> dict:
    """Construye una fila para curso sin estudiantes.

    Parameters
    ----------
    curso : dict
        Datos del curso desde Moodle API
    categories : dict
        Mapa de categorías {id: nombre}

    Returns
    -------
    dict
        Fila con datos del curso y campos de estudiante vacíos
    """
    # Extraer datos del curso
    nombre_corto = str(curso.get("shortname", "")).strip().lower()
    nombre_completo = str(curso.get("fullname", "")).strip()
    categoria_id = curso.get("categoryid")
    categoria_nombre = categories.get(categoria_id, "")

    # Determinar modalidad según categoría
    if categoria_id == 6:
        modalidad = "Asincrónico"
    elif categoria_id == 12:
        modalidad = "Sincrónico"
    else:
        if "asincr" in categoria_nombre.lower():
            modalidad = "Asincrónico"
        elif "sincr" in categoria_nombre.lower():
            modalidad = "Sincrónico"
        else:
            modalidad = categoria_nombre

    # Convertir fechas
    fecha_inicio = _unix_to_fecha_espanol(curso.get("startdate", 0))
    fecha_fin = _unix_to_fecha_espanol(curso.get("enddate", 0))

    # Fila con datos del curso y campos de estudiante vacíos
    fila = {
        # ── Campos del curso ────────────────────────────────
        "nombre_curso": nombre_completo,
        "nombre_corto": nombre_corto,
        "Nombre completo del curso": nombre_completo,
        "Nombre corto del curso": nombre_corto,
        "Fecha de inicio del curso": fecha_inicio,
        "Fecha de finalización del curso": fecha_fin,
        "Nombre de la categoría": categoria_nombre,
        "categoria": categoria_nombre,
        "Modalidad": modalidad,  # NUEVO

        # ── Campos del estudiante (vacíos) ──────────────────
        "Nombre completo Participante": "",
        "ID del Usuario": "",
        "Dirección de correo": "",
        "Rol": "",
        "Progreso del estudiante": None,
        "Calificación": None,
        "Último acceso al curso": "",

        # ── Evaluaciones (vacíos) ───────────────────────────
        "Evaluaciones Rendidas": 0,
        "Total Evaluaciones": 0,
        "Promedio Evaluadas": None,
        "Resumen Evaluaciones": "0/0",

        # ── SENCE (vacíos) ──────────────────────────────────
        "IDSence": "",
        "LLave": "",
        "N_Ingresos": 0,
        "DJ": "",

        # ── Compatibilidad ──────────────────────────────────
        "Nombre corto del curso con enlace": nombre_corto,
    }

    return fila


def _unix_to_fecha_espanol(timestamp: int) -> str:
    """Convierte timestamp Unix a formato largo español.

    Formato de salida: "día_semana, día de mes de año, HH:MM"
    Ejemplo: "domingo, 5 de noviembre de 2025, 00:00"

    Este formato es parseable por cleaner.py::parse_fecha_espanol()

    Parameters
    ----------
    timestamp : int
        Unix timestamp (segundos desde epoch)

    Returns
    -------
    str
        Fecha en formato largo español, o cadena vacía si timestamp es 0 o inválido
    """
    if timestamp == 0 or timestamp is None:
        return ""

    try:
        dt = datetime.fromtimestamp(timestamp)

        dia_semana = _DIAS_SEMANA_ES[dt.weekday()]
        dia = dt.day
        mes = _MESES_ES[dt.month]
        anio = dt.year
        hora = dt.hour
        minuto = dt.minute

        return f"{dia_semana}, {dia} de {mes} de {anio}, {hora:02d}:{minuto:02d}"

    except (OSError, ValueError, OverflowError) as e:
        logger.warning("Timestamp inválido %s: %s", timestamp, e)
        return ""


def _get_column_names() -> list[str]:
    """Retorna lista de nombres de columnas del DataFrame.

    Se usa para crear DataFrames vacíos con la estructura correcta.

    Returns
    -------
    list[str]
        Nombres de todas las columnas del DataFrame
    """
    return [
        "nombre_curso",
        "nombre_corto",
        "Nombre completo del curso",
        "Nombre corto del curso",
        "Fecha de inicio del curso",
        "Fecha de finalización del curso",
        "Nombre de la categoría",
        "categoria",
        "Modalidad",  # NUEVO
        "Nombre completo Participante",
        "ID del Usuario",
        "Dirección de correo",
        "Rol",
        "Progreso del estudiante",
        "Calificación",
        "Último acceso al curso",
        "Evaluaciones Rendidas",  # NUEVO
        "Total Evaluaciones",  # NUEVO
        "Promedio Evaluadas",  # NUEVO
        "Resumen Evaluaciones",  # NUEVO
        "IDSence",
        "LLave",
        "N_Ingresos",
        "DJ",
        "Nombre corto del curso con enlace",
    ]

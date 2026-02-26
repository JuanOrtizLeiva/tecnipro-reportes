"""Cliente HTTP para Moodle API REST.

Este módulo proporciona funciones para interactuar con la API REST de Moodle.
Incluye retry logic, rate limiting y manejo robusto de errores.
"""

import logging
import time
from typing import Any
from urllib.parse import urlencode

import requests

from config import settings

logger = logging.getLogger(__name__)

# Constantes
RATE_LIMIT_DELAY = 0.05  # segundos entre llamadas (20 req/s, Moodle soporta 20+)
MAX_RETRIES = 2
RETRY_DELAY = 5  # segundos
TIMEOUT = settings.MOODLE_TIMEOUT if hasattr(settings, 'MOODLE_TIMEOUT') else 60

# Control de última llamada para rate limiting
_last_call_time = 0.0


class MoodleAPIError(Exception):
    """Error específico de Moodle API."""
    pass


def moodle_api_call(function: str, params: dict[str, Any] | None = None) -> dict | list:
    """Llamada genérica a Moodle API REST con retry y error handling.

    Parameters
    ----------
    function : str
        Nombre de la función Moodle API (ej: "core_course_get_courses")
    params : dict, optional
        Parámetros adicionales para la llamada

    Returns
    -------
    dict | list
        Respuesta JSON de la API

    Raises
    ------
    MoodleAPIError
        Si la API retorna un error
    RuntimeError
        Si hay error de red o HTTP
    """
    global _last_call_time

    if not settings.MOODLE_URL or not settings.MOODLE_TOKEN:
        raise RuntimeError(
            "Credenciales Moodle incompletas. "
            "Verificar MOODLE_URL y MOODLE_TOKEN en .env"
        )

    if params is None:
        params = {}

    # Rate limiting: esperar si la última llamada fue muy reciente
    elapsed = time.time() - _last_call_time
    if elapsed < RATE_LIMIT_DELAY:
        time.sleep(RATE_LIMIT_DELAY - elapsed)

    # Construir parámetros de la URL
    url_params = {
        "wstoken": settings.MOODLE_TOKEN,
        "wsfunction": function,
        "moodlewsrestformat": "json",
        **params,
    }

    url = f"{settings.MOODLE_URL}?{urlencode(url_params)}"

    logger.debug("Llamando Moodle API: %s con params: %s", function, params)

    # Intentar la llamada con retry
    last_exception = None
    for intento in range(MAX_RETRIES + 1):
        try:
            response = requests.get(url, timeout=TIMEOUT)
            _last_call_time = time.time()

            if response.status_code != 200:
                raise RuntimeError(
                    f"Error HTTP {response.status_code} llamando {function}: "
                    f"{response.text[:200]}"
                )

            data = response.json()

            # Verificar si hay error en la respuesta Moodle
            if isinstance(data, dict) and "exception" in data:
                error_msg = data.get("message", "Error desconocido")
                raise MoodleAPIError(
                    f"Error Moodle {function}: {error_msg}"
                )

            logger.debug(
                "Respuesta Moodle API: %d bytes, %s items",
                len(response.content),
                len(data) if isinstance(data, list) else 1
            )

            return data

        except requests.exceptions.Timeout as e:
            last_exception = RuntimeError(f"Timeout llamando {function}: {e}")
            logger.warning("Timeout en intento %d/%d: %s", intento + 1, MAX_RETRIES + 1, e)

        except requests.exceptions.RequestException as e:
            last_exception = RuntimeError(f"Error de red llamando {function}: {e}")
            logger.warning("Error de red en intento %d/%d: %s", intento + 1, MAX_RETRIES + 1, e)

        except MoodleAPIError:
            # Error de Moodle, no reintentar
            raise

        # Si no es el último intento, esperar antes de reintentar
        if intento < MAX_RETRIES:
            logger.info("Reintentando en %d segundos...", RETRY_DELAY)
            time.sleep(RETRY_DELAY)

    # Si llegamos aquí, todos los intentos fallaron
    raise last_exception


def get_categories() -> dict[int, str]:
    """Obtiene todas las categorías de cursos.

    Returns
    -------
    dict[int, str]
        Mapa {id_categoria: nombre_categoria}
    """
    logger.info("Obteniendo categorías de cursos")
    response = moodle_api_call("core_course_get_categories", {})

    if not isinstance(response, list):
        logger.warning("Respuesta inesperada de get_categories: %s", type(response))
        return {}

    categories = {cat["id"]: cat["name"] for cat in response if "id" in cat and "name" in cat}
    logger.info("Categorías obtenidas: %d", len(categories))

    return categories


def get_courses(category_ids: list[int] | None = None) -> list[dict]:
    """Obtiene todos los cursos, opcionalmente filtrados por categorías.

    Parameters
    ----------
    category_ids : list[int], optional
        Lista de IDs de categorías para filtrar. Si es None, retorna todos los cursos.

    Returns
    -------
    list[dict]
        Lista de cursos con campos: id, fullname, shortname, categoryid, startdate, enddate
    """
    logger.info("Obteniendo cursos")
    response = moodle_api_call("core_course_get_courses", {})

    if not isinstance(response, list):
        logger.warning("Respuesta inesperada de get_courses: %s", type(response))
        return []

    # Filtrar por categorías si se especificaron
    if category_ids:
        courses = [
            c for c in response
            if c.get("categoryid") in category_ids
        ]
        logger.info(
            "Cursos obtenidos: %d (filtrados de %d por categorías %s)",
            len(courses), len(response), category_ids
        )
    else:
        courses = response
        logger.info("Cursos obtenidos: %d", len(courses))

    return courses


def get_enrolled_users(courseid: int) -> list[dict]:
    """Obtiene estudiantes inscritos en un curso.

    Filtra automáticamente para retornar solo usuarios con rol "student" y no suspendidos.

    Parameters
    ----------
    courseid : int
        ID del curso en Moodle

    Returns
    -------
    list[dict]
        Lista de estudiantes con campos: id, username, fullname, email, lastcourseaccess, groups, roles
    """
    logger.debug("Obteniendo estudiantes del curso %d", courseid)
    response = moodle_api_call("core_enrol_get_enrolled_users", {"courseid": courseid})

    if not isinstance(response, list):
        logger.warning(
            "Respuesta inesperada de get_enrolled_users para curso %d: %s",
            courseid, type(response)
        )
        return []

    # Filtrar solo estudiantes activos (role="student", no suspended)
    estudiantes = []
    for user in response:
        # Verificar si está suspendido
        if user.get("suspended", False):
            continue

        # Verificar si tiene rol "student"
        roles = user.get("roles", [])
        tiene_rol_student = any(
            role.get("shortname") == "student"
            for role in roles
        )

        if tiene_rol_student:
            estudiantes.append(user)

    logger.debug("Estudiantes activos en curso %d: %d", courseid, len(estudiantes))
    return estudiantes


def get_grades(courseid: int) -> dict[int, dict]:
    """Obtiene notas finales y detalles de evaluaciones de todos los usuarios.

    Extrae:
    - Nota final del item con itemtype="course"
    - Detalles de evaluaciones individuales (excluyendo course y category)

    Parameters
    ----------
    courseid : int
        ID del curso en Moodle

    Returns
    -------
    dict[int, dict]
        Mapa {userid: {
            'nota_final': float | None,
            'evaluaciones_rendidas': int,
            'total_evaluaciones': int,
            'promedio_evaluadas': float | None,
            'resumen_evaluaciones': str (e.g., "3/5")
        }}
    """
    logger.debug("Obteniendo notas del curso %d", courseid)
    response = moodle_api_call("gradereport_user_get_grade_items", {"courseid": courseid})

    if not isinstance(response, dict) or "usergrades" not in response:
        logger.warning(
            "Respuesta inesperada de get_grades para curso %d: %s",
            courseid, type(response)
        )
        return {}

    grades = {}
    usergrades = response.get("usergrades", [])

    for usergrade in usergrades:
        userid = usergrade.get("userid")
        if not userid:
            continue

        # Procesar items de calificación
        gradeitems = usergrade.get("gradeitems", [])
        nota_final = None
        evaluaciones = []  # Solo evaluaciones individuales (no course, no category)

        for item in gradeitems:
            itemtype = item.get("itemtype", "")

            if itemtype == "course":
                # Nota final del curso
                nota_final = item.get("graderaw")

            elif itemtype not in ["course", "category"]:
                # Evaluación individual (mod, manual, etc.)
                graderaw = item.get("graderaw")
                if graderaw is not None:
                    evaluaciones.append(graderaw)

        # Calcular estadísticas de evaluaciones
        total_evaluaciones = len(gradeitems) - sum(
            1 for item in gradeitems
            if item.get("itemtype") in ["course", "category"]
        )
        evaluaciones_rendidas = len(evaluaciones)

        # Promedio de solo las evaluaciones rendidas
        promedio_evaluadas = None
        if evaluaciones_rendidas > 0:
            promedio_evaluadas = round(sum(evaluaciones) / evaluaciones_rendidas, 1)

        resumen_evaluaciones = f"{evaluaciones_rendidas}/{total_evaluaciones}"

        grades[userid] = {
            "nota_final": nota_final,
            "evaluaciones_rendidas": evaluaciones_rendidas,
            "total_evaluaciones": total_evaluaciones,
            "promedio_evaluadas": promedio_evaluadas,
            "resumen_evaluaciones": resumen_evaluaciones,
        }

    logger.debug("Notas obtenidas para curso %d: %d usuarios", courseid, len(grades))
    return grades


def get_completion_status(courseid: int, userid: int) -> float:
    """Calcula el progreso de un estudiante en un curso.

    El progreso se calcula como: (actividades completadas / total actividades) × 100

    Actividades completadas son aquellas con state in [1, 2]:
    - 1: Completada
    - 2: Completada con aprobación

    Parameters
    ----------
    courseid : int
        ID del curso en Moodle
    userid : int
        ID del usuario en Moodle

    Returns
    -------
    float
        Porcentaje de progreso (0-100). Retorna 0.0 si no hay completion tracking.
    """
    logger.debug("Obteniendo progreso del usuario %d en curso %d", userid, courseid)

    try:
        response = moodle_api_call(
            "core_completion_get_activities_completion_status",
            {"courseid": courseid, "userid": userid}
        )
    except MoodleAPIError as e:
        # El curso puede no tener completion tracking habilitado
        logger.debug(
            "No se pudo obtener completion para curso %d, usuario %d: %s",
            courseid, userid, e
        )
        return 0.0

    if not isinstance(response, dict) or "statuses" not in response:
        logger.debug(
            "Respuesta inesperada de get_completion_status para curso %d, usuario %d",
            courseid, userid
        )
        return 0.0

    statuses = response.get("statuses", [])

    if not statuses:
        # No hay actividades con completion tracking
        return 0.0

    # Contar actividades completadas (state 1 o 2)
    total = len(statuses)
    completadas = sum(
        1 for status in statuses
        if status.get("state") in [1, 2]
    )

    progreso = round((completadas / total) * 100, 1) if total > 0 else 0.0

    logger.debug(
        "Progreso usuario %d en curso %d: %.1f%% (%d/%d)",
        userid, courseid, progreso, completadas, total
    )

    return progreso


def get_all_sence_ids() -> list[str]:
    """Obtiene todos los IDs SENCE únicos de todos los cursos en las categorías configuradas.

    Esta función es usada por el orchestrator del scraper para saber qué IDs descargar.
    Extrae los IDs desde los grupos de usuario en cada curso.

    Returns
    -------
    list[str]
        Lista de IDs SENCE únicos como strings numéricos.
        Ejemplo: ["6731347", "6763148", ...]
    """
    logger.info("Obteniendo IDs SENCE desde Moodle API...")

    # Obtener todos los cursos de las categorías configuradas
    courses = get_courses(settings.MOODLE_CATEGORY_IDS)

    if not courses:
        logger.warning("No se encontraron cursos en las categorías configuradas")
        return []

    sence_ids_set = set()

    # Para cada curso, obtener los estudiantes y extraer sus grupos
    for curso in courses:
        curso_id = curso.get("id")
        curso_nombre = curso.get("fullname", "")

        try:
            estudiantes = get_enrolled_users(curso_id)

            for est in estudiantes:
                groups = est.get("groups", [])

                # El primer grupo contiene el ID SENCE
                if groups and len(groups) > 0:
                    id_sence = str(groups[0].get("name", "")).strip()

                    # Validar que sea numérico
                    if id_sence and id_sence.isdigit():
                        sence_ids_set.add(id_sence)
                    else:
                        # Intentar extraer número de formato "6731347.0"
                        try:
                            num = int(float(id_sence))
                            sence_ids_set.add(str(num))
                        except (ValueError, TypeError):
                            continue

        except Exception as e:
            logger.warning("Error obteniendo IDs SENCE del curso %d (%s): %s",
                          curso_id, curso_nombre, e)
            continue

    sence_ids = sorted(sence_ids_set)
    logger.info("IDs SENCE únicos encontrados: %d", len(sence_ids))

    return sence_ids

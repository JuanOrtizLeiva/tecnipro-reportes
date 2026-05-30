"""Persiste datos del pipeline en PostgreSQL (UPSERT idempotente)."""

import logging
from datetime import date, datetime, timezone

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy import func

from config import settings

logger = logging.getLogger(__name__)


def upsert_all(datos_json: dict, parcial: bool = False) -> dict:
    """UPSERT de datos del pipeline a PostgreSQL.

    Recibe el mismo dict que genera json_exporter.exportar_json().

    Parameters
    ----------
    parcial : bool
        Si True, el pipeline corrió filtrado a un subconjunto de cursos
        (ej. refresh disparado por un coordinador con sus cursos asignados).
        En ese caso NO se eliminan cursos no incluidos en `cursos_data`,
        porque su ausencia no significa que estén obsoletos — sólo no
        fueron procesados en esta corrida. Default False (pipeline completo).
    """
    from src.database import init_db, get_session, SessionLocal
    from src.models import (
        Curso, Estudiante, Inscripcion, Comprador,
        SnapshotDiario, SnapshotEstudiante, PipelineRun,
    )

    if not settings.USE_PG:
        logger.debug("USE_PG=false — omitiendo escritura a PostgreSQL")
        return {"status": "skipped"}

    # Inicializar BD si no se ha hecho
    if SessionLocal is None:
        if not init_db():
            return {"status": "error", "detail": "No se pudo conectar a PostgreSQL"}

    session = get_session()
    hoy = date.today()
    resumen = {"cursos": 0, "estudiantes": 0, "inscripciones": 0, "snapshots": 0}

    try:
        # Registrar ejecución
        run = PipelineRun(triggered_by="pipeline")
        session.add(run)
        session.flush()

        cursos_data = datos_json.get("cursos", [])

        for curso_data in cursos_data:
            id_moodle = curso_data.get("id_moodle", "")
            if not id_moodle:
                continue

            # ── UPSERT curso ──
            fecha_inicio = _parse_date(curso_data.get("fecha_inicio"))
            fecha_fin = _parse_date(curso_data.get("fecha_fin"))

            stmt = pg_insert(Curso).values(
                id_moodle=id_moodle,
                id_sence=curso_data.get("id_sence", ""),
                nombre=curso_data.get("nombre", ""),
                nombre_corto=curso_data.get("nombre_corto", ""),
                categoria=curso_data.get("categoria", ""),
                modalidad=curso_data.get("modalidad", ""),
                fecha_inicio=fecha_inicio,
                fecha_fin=fecha_fin,
                fecha_inicio_sence=curso_data.get("fecha_inicio_sence", ""),
                fecha_termino_sence=curso_data.get("fecha_termino_sence", ""),
                estado_dj_otec=curso_data.get("estado_dj_otec", ""),
                estado_curso_sence=curso_data.get("estado_curso_sence", ""),
            ).on_conflict_do_update(
                index_elements=["id_moodle"],
                set_={
                    "id_sence": curso_data.get("id_sence", ""),
                    "nombre": curso_data.get("nombre", ""),
                    "nombre_corto": curso_data.get("nombre_corto", ""),
                    "categoria": curso_data.get("categoria", ""),
                    "modalidad": curso_data.get("modalidad", ""),
                    "fecha_inicio": fecha_inicio,
                    "fecha_fin": fecha_fin,
                    "fecha_inicio_sence": curso_data.get("fecha_inicio_sence", ""),
                    "fecha_termino_sence": curso_data.get("fecha_termino_sence", ""),
                    "estado_dj_otec": curso_data.get("estado_dj_otec", ""),
                    "estado_curso_sence": curso_data.get("estado_curso_sence", ""),
                    "updated_at": func.now(),
                },
            )
            session.execute(stmt)
            session.flush()

            curso_obj = session.query(Curso).filter_by(id_moodle=id_moodle).one()
            resumen["cursos"] += 1

            # ── UPSERT comprador ──
            comp = curso_data.get("comprador", {})
            if comp and comp.get("nombre"):
                stmt = pg_insert(Comprador).values(
                    curso_id=curso_obj.id,
                    nombre=comp.get("nombre", ""),
                    empresa=comp.get("empresa", ""),
                    email=comp.get("email", ""),
                ).on_conflict_do_update(
                    index_elements=["curso_id"],
                    set_={
                        "nombre": comp.get("nombre", ""),
                        "empresa": comp.get("empresa", ""),
                        "email": comp.get("email", ""),
                        "updated_at": func.now(),
                    },
                )
                session.execute(stmt)

            # ── UPSERT estudiantes + inscripciones ──
            stats = {
                "aprobados": 0, "reprobados": 0, "en_proceso": 0,
                "riesgo_alto": 0, "riesgo_medio": 0, "riesgo_bajo": 0,
                "conectados_sence": 0,
            }

            estudiantes_data = curso_data.get("estudiantes", [])
            inscripcion_ids = []

            for est in estudiantes_data:
                rut = est.get("rut", "").strip()
                if not rut:
                    continue

                # UPSERT estudiante
                stmt = pg_insert(Estudiante).values(
                    rut=rut,
                    nombre=est.get("nombre", ""),
                    email=est.get("email", ""),
                ).on_conflict_do_update(
                    index_elements=["rut"],
                    set_={
                        "nombre": est.get("nombre", ""),
                        "email": est.get("email", ""),
                        "updated_at": func.now(),
                    },
                )
                session.execute(stmt)
                session.flush()

                est_obj = session.query(Estudiante).filter_by(rut=rut).one()
                resumen["estudiantes"] += 1

                # SENCE data
                sence = est.get("sence", {})
                id_sence_est = sence.get("id_sence", "") or ""
                sence_n = sence.get("n_ingresos", 0) or 0
                sence_estado = sence.get("estado", "NO_APLICA") or "NO_APLICA"
                sence_dj = sence.get("declaracion_jurada", "") or ""

                # Campos de inscripción
                progreso = est.get("progreso")
                calificacion = est.get("calificacion")
                ultimo_acceso = _parse_datetime(est.get("ultimo_acceso"))
                dias_sin = est.get("dias_sin_ingreso")
                estado = est.get("estado", "P") or "P"
                riesgo = est.get("riesgo") or None
                eval_rend = est.get("evaluaciones_rendidas", 0) or 0
                total_eval = est.get("total_evaluaciones", 0) or 0
                prom_eval = est.get("promedio_evaluadas")

                # UPSERT inscripción
                stmt = pg_insert(Inscripcion).values(
                    curso_id=curso_obj.id,
                    estudiante_id=est_obj.id,
                    progreso=progreso,
                    calificacion=calificacion,
                    evaluaciones_rendidas=eval_rend,
                    total_evaluaciones=total_eval,
                    promedio_evaluadas=prom_eval,
                    ultimo_acceso=ultimo_acceso,
                    dias_sin_ingreso=dias_sin,
                    estado=estado,
                    riesgo=riesgo,
                    id_sence=id_sence_est,
                    sence_n_ingresos=sence_n,
                    sence_estado=sence_estado,
                    sence_dj=sence_dj,
                    estado_curso=curso_data.get("estado", "active"),
                    dias_para_termino=curso_data.get("dias_restantes"),
                ).on_conflict_do_update(
                    index_elements=["curso_id", "estudiante_id"],
                    set_={
                        "progreso": progreso,
                        "calificacion": calificacion,
                        "evaluaciones_rendidas": eval_rend,
                        "total_evaluaciones": total_eval,
                        "promedio_evaluadas": prom_eval,
                        "ultimo_acceso": ultimo_acceso,
                        "dias_sin_ingreso": dias_sin,
                        "estado": estado,
                        "riesgo": riesgo,
                        "id_sence": id_sence_est,
                        "sence_n_ingresos": sence_n,
                        "sence_estado": sence_estado,
                        "sence_dj": sence_dj,
                        "estado_curso": curso_data.get("estado", "active"),
                        "dias_para_termino": curso_data.get("dias_restantes"),
                        "updated_at": func.now(),
                    },
                )
                session.execute(stmt)
                resumen["inscripciones"] += 1

                # Track stats
                if estado == "A":
                    stats["aprobados"] += 1
                elif estado == "R":
                    stats["reprobados"] += 1
                else:
                    stats["en_proceso"] += 1
                if riesgo == "alto":
                    stats["riesgo_alto"] += 1
                elif riesgo == "medio":
                    stats["riesgo_medio"] += 1
                elif riesgo == "bajo":
                    stats["riesgo_bajo"] += 1
                if sence_estado == "CONECTADO":
                    stats["conectados_sence"] += 1

            session.flush()

            # ── Eliminar inscripciones de alumnos retirados del curso en Moodle ──
            # El UPSERT nunca borra; sin esto, un alumno desinscrito en Moodle
            # quedaría "pegado" en la base (p.ej. como DJ pendiente para siempre).
            # Salvaguarda: solo se ejecuta si el curso trae al menos un RUT real,
            # para no borrar todo ante un fetch vacío/parcial transitorio de la API.
            ruts_actuales = {
                str(e.get("rut", "")).strip()
                for e in estudiantes_data
                if str(e.get("rut", "")).strip()
            }
            if ruts_actuales:
                filas_insc = (
                    session.query(Inscripcion, Estudiante.rut)
                    .join(Estudiante, Inscripcion.estudiante_id == Estudiante.id)
                    .filter(Inscripcion.curso_id == curso_obj.id)
                    .all()
                )
                retiradas = 0
                for insc_row, rut_insc in filas_insc:
                    if rut_insc not in ruts_actuales:
                        session.delete(insc_row)  # cascade elimina sus snapshots
                        retiradas += 1
                if retiradas:
                    session.flush()
                    logger.info(
                        "Curso %s: %d inscripción(es) eliminada(s) por retiro en Moodle",
                        id_moodle, retiradas,
                    )
                    resumen["inscripciones_retiradas"] = (
                        resumen.get("inscripciones_retiradas", 0) + retiradas
                    )

            # Obtener IDs de inscripciones para snapshots
            inscripciones_db = session.query(Inscripcion).filter_by(curso_id=curso_obj.id).all()

            # ── Snapshot diario del curso ──
            est_stats = curso_data.get("estadisticas", {})
            progs = [e.get("progreso") for e in estudiantes_data if e.get("progreso") is not None]
            califs = [e.get("calificacion") for e in estudiantes_data if e.get("calificacion") is not None]

            stmt = pg_insert(SnapshotDiario).values(
                fecha=hoy,
                curso_id=curso_obj.id,
                id_moodle=id_moodle,
                total_estudiantes=len(estudiantes_data),
                promedio_progreso=round(sum(progs) / len(progs), 1) if progs else 0.0,
                promedio_calificacion=round(sum(califs) / len(califs), 1) if califs else 0.0,
                aprobados=stats["aprobados"],
                reprobados=stats["reprobados"],
                en_proceso=stats["en_proceso"],
                riesgo_alto=stats["riesgo_alto"],
                riesgo_medio=stats["riesgo_medio"],
                riesgo_bajo=stats["riesgo_bajo"],
                conectados_sence=stats["conectados_sence"],
                avance_temporal=est_stats.get("avance_temporal"),
            ).on_conflict_do_update(
                index_elements=["fecha", "curso_id"],
                set_={
                    "total_estudiantes": len(estudiantes_data),
                    "promedio_progreso": round(sum(progs) / len(progs), 1) if progs else 0.0,
                    "promedio_calificacion": round(sum(califs) / len(califs), 1) if califs else 0.0,
                    "aprobados": stats["aprobados"],
                    "reprobados": stats["reprobados"],
                    "en_proceso": stats["en_proceso"],
                    "riesgo_alto": stats["riesgo_alto"],
                    "riesgo_medio": stats["riesgo_medio"],
                    "riesgo_bajo": stats["riesgo_bajo"],
                    "conectados_sence": stats["conectados_sence"],
                    "avance_temporal": est_stats.get("avance_temporal"),
                },
            )
            session.execute(stmt)
            resumen["snapshots"] += 1

            # ── Snapshots de estudiantes ──
            insc_map = {i.estudiante_id: i.id for i in inscripciones_db}
            for est in estudiantes_data:
                rut = est.get("rut", "").strip()
                if not rut:
                    continue
                est_obj = session.query(Estudiante).filter_by(rut=rut).first()
                if not est_obj or est_obj.id not in insc_map:
                    continue
                insc_id = insc_map[est_obj.id]

                stmt = pg_insert(SnapshotEstudiante).values(
                    fecha=hoy,
                    inscripcion_id=insc_id,
                    progreso=est.get("progreso"),
                    calificacion=est.get("calificacion"),
                    estado=est.get("estado", "P") or "P",
                    riesgo=est.get("riesgo") or None,
                    sence_n_ingresos=(est.get("sence", {}).get("n_ingresos", 0) or 0),
                    dias_sin_ingreso=est.get("dias_sin_ingreso"),
                ).on_conflict_do_update(
                    index_elements=["fecha", "inscripcion_id"],
                    set_={
                        "progreso": est.get("progreso"),
                        "calificacion": est.get("calificacion"),
                        "estado": est.get("estado", "P") or "P",
                        "riesgo": est.get("riesgo") or None,
                        "sence_n_ingresos": (est.get("sence", {}).get("n_ingresos", 0) or 0),
                        "dias_sin_ingreso": est.get("dias_sin_ingreso"),
                    },
                )
                session.execute(stmt)

        # ── Eliminar cursos que ya no están en las categorías activas ──
        # Si un curso fue movido de categoría en Moodle, ya no viene en
        # cursos_data y debe dejar de mostrarse en el dashboard.
        # En modo parcial NO se ejecuta: la ausencia de un curso sólo
        # significa que no fue procesado en esta corrida, no que esté obsoleto.
        ids_activos = {str(c.get("id_moodle", "")) for c in cursos_data if c.get("id_moodle")}
        if ids_activos and not parcial:
            cursos_obsoletos = session.query(Curso).filter(
                ~Curso.id_moodle.in_(ids_activos)
            ).all()
            for curso_obs in cursos_obsoletos:
                logger.info(
                    "Eliminando curso obsoleto: %s (id_moodle=%s, categoría=%s)",
                    curso_obs.nombre, curso_obs.id_moodle, curso_obs.categoria,
                )
                session.delete(curso_obs)  # cascade elimina inscripciones, snapshots, comprador
            if cursos_obsoletos:
                resumen["eliminados"] = len(cursos_obsoletos)
                logger.info("Cursos eliminados por cambio de categoría: %d", len(cursos_obsoletos))

        # Finalizar pipeline run
        run.status = "ok"
        run.total_cursos = len(cursos_data)
        run.total_estudiantes = resumen["inscripciones"]
        run.finished_at = datetime.now(timezone.utc)
        session.commit()

        logger.info(
            "PostgreSQL: %d cursos, %d estudiantes, %d inscripciones, %d snapshots",
            resumen["cursos"], resumen["estudiantes"],
            resumen["inscripciones"], resumen["snapshots"],
        )
        resumen["status"] = "ok"
        return resumen

    except Exception as e:
        session.rollback()
        logger.error("Error en upsert PostgreSQL: %s", e, exc_info=True)
        try:
            run.status = "error"
            run.error_message = str(e)[:500]
            run.finished_at = datetime.now(timezone.utc)
            session.commit()
        except Exception as commit_err:
            logger.error(
                "No se pudo marcar pipeline_run como error: %s", commit_err,
            )
        resumen["status"] = "error"
        resumen["detail"] = str(e)
        return resumen
    finally:
        session.close()


def _parse_date(val):
    """Convierte string ISO a date, o None."""
    if not val:
        return None
    try:
        return date.fromisoformat(str(val))
    except (ValueError, TypeError):
        return None


def _parse_datetime(val):
    """Convierte string ISO a datetime, o None."""
    if not val:
        return None
    try:
        d = date.fromisoformat(str(val))
        return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None

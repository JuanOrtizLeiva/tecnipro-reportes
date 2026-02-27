#!/usr/bin/env python3
"""Script para ejecutar pipeline de refresh en segundo plano.

Se ejecuta como proceso independiente, desvinculado del servidor web.
Acepta course_ids como argumento JSON opcional.
Escribe un archivo de estado al finalizar para que el cliente pueda consultar.

Uso:
    python run_pipeline_refresh.py <job_id> [course_ids_json]

Ejemplo:
    python run_pipeline_refresh.py abc12345
    python run_pipeline_refresh.py abc12345 '[101, 102, 103]'
"""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

# Agregar directorio raíz al path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.main import run_pipeline

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def write_status(status_path: Path, status: dict):
    """Escribe el archivo de estado de forma atómica."""
    try:
        status_path.parent.mkdir(parents=True, exist_ok=True)
        # Escribir a archivo temporal primero, luego renombrar (atómico en Linux)
        tmp_path = status_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(status), encoding="utf-8")
        tmp_path.replace(status_path)
    except Exception as e:
        logger.error("Error escribiendo archivo de estado: %s", e)


def main():
    """Ejecuta pipeline y escribe resultado en archivo de estado."""
    if len(sys.argv) < 2:
        print("Uso: run_pipeline_refresh.py <job_id> [course_ids_json]")
        sys.exit(1)

    job_id = sys.argv[1]
    course_ids = None

    if len(sys.argv) >= 3:
        try:
            course_ids = json.loads(sys.argv[2])
            if not isinstance(course_ids, list):
                course_ids = None
        except Exception:
            course_ids = None

    project_root = Path(__file__).parent.parent
    status_path = project_root / "data" / "output" / f"refresh_status_{job_id}.json"
    lock_path = project_root / "data" / "output" / "pipeline_refresh.lock"

    # ── Lock: evitar procesos simultáneos ─────────────────────────
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        # Lock atómico: open('x') falla si archivo ya existe (O_CREAT|O_EXCL)
        fd = open(str(lock_path), "x")
        fd.close()
    except FileExistsError:
        # Si routes.py ya creó el lock antes de spawnearnos, es normal
        # Solo abortar si NO fuimos invocados con un job_id (ejecución standalone duplicada)
        if lock_path.exists() and job_id:
            logger.info("Lock ya existente (creado por routes.py) — continuando job_id=%s", job_id)
        else:
            logger.warning("Ya hay un proceso de refresh en ejecución. Abortando job_id=%s", job_id)
            write_status(status_path, {
                "status": "error",
                "message": "Ya hay una actualización en proceso. Espere a que termine e intente nuevamente.",
                "finished_at": datetime.now().isoformat(),
            })
            sys.exit(1)

    modo = f"{len(course_ids)} cursos" if course_ids else "todos los cursos (admin)"
    logger.info("=" * 60)
    logger.info("PIPELINE REFRESH EN SEGUNDO PLANO")
    logger.info("Job ID : %s", job_id)
    logger.info("Modo   : %s", modo)
    logger.info("Inicio : %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("=" * 60)

    # Marcar como running
    write_status(status_path, {
        "status": "running",
        "message": "Procesando datos desde Moodle...",
        "started_at": datetime.now().isoformat(),
    })

    try:
        datos_json = run_pipeline(course_ids=course_ids)

        write_status(status_path, {
            "status": "ok",
            "message": "Datos actualizados exitosamente",
            "cursos": datos_json["metadata"]["total_cursos"],
            "estudiantes": datos_json["metadata"]["total_estudiantes"],
            "fecha": datos_json["metadata"]["fecha_procesamiento"],
            "finished_at": datetime.now().isoformat(),
        })

        logger.info("Pipeline refresh completado exitosamente (job_id=%s)", job_id)
        sys.exit(0)

    except Exception as e:
        logger.error("Error en pipeline refresh (job_id=%s): %s", job_id, e, exc_info=True)

        write_status(status_path, {
            "status": "error",
            "message": f"Error al actualizar datos: {str(e)}",
            "finished_at": datetime.now().isoformat(),
        })

        sys.exit(1)

    finally:
        # Siempre liberar el lock al terminar (éxito o error)
        try:
            lock_path.unlink(missing_ok=True)
        except Exception:
            pass


if __name__ == "__main__":
    main()

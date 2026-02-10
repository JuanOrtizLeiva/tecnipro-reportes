"""Guarda snapshots diarios en SQLite."""

import json
import logging
import sqlite3
from datetime import date
from pathlib import Path

from config import settings

logger = logging.getLogger(__name__)

_SCHEMA_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha DATE NOT NULL,
    datos_json TEXT NOT NULL
);
"""

_SCHEMA_METRICAS = """
CREATE TABLE IF NOT EXISTS metricas_diarias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha DATE NOT NULL,
    id_curso TEXT NOT NULL,
    total_estudiantes INTEGER,
    promedio_progreso REAL,
    aprobados INTEGER,
    reprobados INTEGER,
    en_proceso INTEGER
);
"""


def guardar_snapshot(datos_json, db_path=None):
    """Guarda el JSON completo como snapshot diario y extrae métricas por curso.

    Parameters
    ----------
    datos_json : dict
        Estructura completa generada por ``json_exporter``.
    db_path : Path | str | None
        Ruta al archivo SQLite.  Si es ``None`` usa ``settings.SQLITE_PATH``.
    """
    if db_path is None:
        db_path = settings.SQLITE_PATH

    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    hoy = date.today().isoformat()

    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()

        # Crear tablas si no existen
        cur.execute(_SCHEMA_SNAPSHOTS)
        cur.execute(_SCHEMA_METRICAS)

        # Guardar snapshot
        json_str = json.dumps(datos_json, ensure_ascii=False, default=str)
        cur.execute(
            "INSERT INTO snapshots (fecha, datos_json) VALUES (?, ?)",
            (hoy, json_str),
        )

        # Guardar métricas por curso
        for curso in datos_json.get("cursos", []):
            stats = curso.get("estadisticas", {})
            cur.execute(
                """INSERT INTO metricas_diarias
                   (fecha, id_curso, total_estudiantes, promedio_progreso,
                    aprobados, reprobados, en_proceso)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    hoy,
                    curso.get("id_moodle", ""),
                    stats.get("total_estudiantes", 0),
                    stats.get("promedio_progreso", 0.0),
                    stats.get("aprobados", 0),
                    stats.get("reprobados", 0),
                    stats.get("en_proceso", 0),
                ),
            )

        conn.commit()
        logger.info("Snapshot guardado en %s (fecha: %s)", db_path, hoy)

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

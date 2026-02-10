"""Tests para los módulos de salida."""

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest


def _get_processed_df():
    """Helper: ejecuta el pipeline hasta obtener el DataFrame procesado."""
    from src.ingest.dreporte_reader import leer_dreporte
    from src.ingest.greporte_reader import leer_greporte
    from src.ingest.sence_reader import leer_sence
    from src.ingest.compradores_reader import leer_compradores
    from src.transform.merger import (
        merge_sence_into_dreporte,
        merge_greporte_dreporte,
        merge_compradores,
    )
    from src.transform.calculator import calcular_campos

    df_d = leer_dreporte()
    df_s = leer_sence()
    df_g = leer_greporte()
    df_c = leer_compradores()

    df_d = merge_sence_into_dreporte(df_d, df_s)
    df_merged = merge_greporte_dreporte(df_g, df_d)
    df_merged = merge_compradores(df_merged, df_c)
    df_merged = calcular_campos(df_merged)
    return df_merged


class TestJsonExporter:
    def test_exportar_json_estructura(self):
        from src.output.json_exporter import exportar_json

        df = _get_processed_df()
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "test.json"
            result = exportar_json(df, output_path=out_path)

            # Verificar estructura
            assert "metadata" in result
            assert "cursos" in result
            assert result["metadata"]["total_cursos"] > 0
            assert result["metadata"]["version"] == "1.0"

            # Verificar que el archivo es JSON válido
            with open(out_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            assert loaded == result

    def test_estructura_curso(self):
        from src.output.json_exporter import exportar_json

        df = _get_processed_df()
        with tempfile.TemporaryDirectory() as tmpdir:
            result = exportar_json(df, output_path=Path(tmpdir) / "test.json")

            for curso in result["cursos"]:
                assert "id_moodle" in curso
                assert "nombre" in curso
                assert "estadisticas" in curso
                assert "estudiantes" in curso
                assert "comprador" in curso

                stats = curso["estadisticas"]
                assert "total_estudiantes" in stats
                assert "promedio_progreso" in stats

    def test_estructura_estudiante(self):
        from src.output.json_exporter import exportar_json

        df = _get_processed_df()
        with tempfile.TemporaryDirectory() as tmpdir:
            result = exportar_json(df, output_path=Path(tmpdir) / "test.json")

            # Buscar un curso con estudiantes
            for curso in result["cursos"]:
                if curso["estudiantes"]:
                    est = curso["estudiantes"][0]
                    assert "id" in est
                    assert "nombre" in est
                    assert "email" in est
                    assert "progreso" in est
                    assert "estado" in est
                    assert "sence" in est
                    break


class TestSqliteStore:
    def test_guardar_snapshot(self):
        import sqlite3
        from src.output.sqlite_store import guardar_snapshot
        from src.output.json_exporter import exportar_json

        df = _get_processed_df()
        with tempfile.TemporaryDirectory() as tmpdir:
            json_data = exportar_json(df, output_path=Path(tmpdir) / "test.json")
            db_path = Path(tmpdir) / "test.db"
            guardar_snapshot(json_data, db_path=db_path)

            # Verificar que se crearon las tablas
            conn = sqlite3.connect(str(db_path))
            cur = conn.cursor()

            cur.execute("SELECT COUNT(*) FROM snapshots")
            assert cur.fetchone()[0] == 1

            cur.execute("SELECT COUNT(*) FROM metricas_diarias")
            assert cur.fetchone()[0] > 0

            conn.close()

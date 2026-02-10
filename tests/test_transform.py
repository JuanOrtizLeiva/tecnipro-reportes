"""Tests para los módulos de transformación."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest
from datetime import datetime

from src.transform.cleaner import parse_fecha_espanol, clean_rut


class TestParseFechaEspanol:
    def test_formato_completo(self):
        dt = parse_fecha_espanol("miércoles, 5 de noviembre de 2025, 00:00")
        assert dt == datetime(2025, 11, 5, 0, 0)

    def test_formato_con_hora(self):
        dt = parse_fecha_espanol("domingo, 30 de noviembre de 2025, 23:59")
        assert dt == datetime(2025, 11, 30, 23, 59)

    def test_nunca(self):
        assert parse_fecha_espanol("Nunca") is None

    def test_vacio(self):
        assert parse_fecha_espanol("") is None
        assert parse_fecha_espanol(None) is None

    def test_todos_los_meses(self):
        meses = [
            ("enero", 1), ("febrero", 2), ("marzo", 3), ("abril", 4),
            ("mayo", 5), ("junio", 6), ("julio", 7), ("agosto", 8),
            ("septiembre", 9), ("octubre", 10), ("noviembre", 11), ("diciembre", 12),
        ]
        for nombre, num in meses:
            dt = parse_fecha_espanol(f"lunes, 15 de {nombre} de 2025, 10:00")
            assert dt is not None, f"Falló para {nombre}"
            assert dt.month == num, f"Mes incorrecto para {nombre}"

    def test_fecha_real_greporte(self):
        dt = parse_fecha_espanol("miércoles, 5 de noviembre de 2025, 00:00")
        assert dt.year == 2025
        assert dt.month == 11
        assert dt.day == 5

    def test_fecha_real_dreporte(self):
        dt = parse_fecha_espanol("viernes, 5 de diciembre de 2025, 23:59")
        assert dt == datetime(2025, 12, 5, 23, 59)


class TestCleanRut:
    def test_rut_con_puntos(self):
        assert clean_rut("15.083.435-K") == "15083435-k"

    def test_rut_sin_puntos(self):
        assert clean_rut("15083435-k") == "15083435-k"

    def test_rut_vacio(self):
        assert clean_rut("") == ""
        assert clean_rut(None) == ""

    def test_rut_con_espacios(self):
        assert clean_rut(" 15.083.435-K ") == "15083435-k"


class TestMerger:
    def test_merge_sence_dreporte(self):
        import pandas as pd
        from src.ingest.dreporte_reader import leer_dreporte
        from src.ingest.sence_reader import leer_sence
        from src.transform.merger import merge_sence_into_dreporte

        df_d = leer_dreporte()
        df_s = leer_sence()
        result = merge_sence_into_dreporte(df_d, df_s)

        assert "N_Ingresos" in result.columns
        assert "DJ" in result.columns
        assert len(result) == len(df_d)

    def test_merge_greporte_dreporte(self):
        import pandas as pd
        from src.ingest.dreporte_reader import leer_dreporte
        from src.ingest.greporte_reader import leer_greporte
        from src.ingest.sence_reader import leer_sence
        from src.transform.merger import merge_sence_into_dreporte, merge_greporte_dreporte

        df_d = leer_dreporte()
        df_s = leer_sence()
        df_g = leer_greporte()

        df_d = merge_sence_into_dreporte(df_d, df_s)
        result = merge_greporte_dreporte(df_g, df_d)

        assert "nombre_curso" in result.columns
        assert "nombre_corto" in result.columns
        assert len(result) > 0


class TestCalculator:
    def test_calcular_campos(self):
        import pandas as pd
        from src.ingest.dreporte_reader import leer_dreporte
        from src.ingest.greporte_reader import leer_greporte
        from src.ingest.sence_reader import leer_sence
        from src.transform.merger import merge_sence_into_dreporte, merge_greporte_dreporte
        from src.transform.calculator import calcular_campos

        df_d = leer_dreporte()
        df_s = leer_sence()
        df_g = leer_greporte()

        df_d = merge_sence_into_dreporte(df_d, df_s)
        df_merged = merge_greporte_dreporte(df_g, df_d)
        df_merged = calcular_campos(df_merged)

        assert "estado_participante" in df_merged.columns
        assert "riesgo" in df_merged.columns
        assert "estado_sence" in df_merged.columns
        assert "dias_para_termino" in df_merged.columns

        # Verificar valores válidos
        estados_validos = {"A", "R", "P"}
        for val in df_merged["estado_participante"].dropna():
            assert val in estados_validos, f"Estado inválido: {val}"

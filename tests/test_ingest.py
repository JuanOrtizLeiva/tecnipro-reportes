"""Tests para los módulos de ingesta."""

import sys
from pathlib import Path

# Asegurar que la raíz del proyecto esté en sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest
import pandas as pd


class TestGreporteReader:
    def test_lectura_basica(self):
        from src.ingest.greporte_reader import leer_greporte
        df = leer_greporte()
        assert isinstance(df, pd.DataFrame)
        assert len(df) > 0

    def test_filtro_restauracion(self):
        from src.ingest.greporte_reader import leer_greporte
        df = leer_greporte()
        assert not df["Nombre completo del curso"].str.contains(
            "Restauración del curso iniciada", na=False
        ).any()

    def test_nombre_corto_minuscula(self):
        from src.ingest.greporte_reader import leer_greporte
        df = leer_greporte()
        for val in df["Nombre corto del curso"]:
            assert val == val.lower().strip()


class TestDreporteReader:
    def test_lectura_basica(self):
        from src.ingest.dreporte_reader import leer_dreporte
        df = leer_dreporte()
        assert isinstance(df, pd.DataFrame)
        assert len(df) > 0

    def test_solo_estudiantes(self):
        from src.ingest.dreporte_reader import leer_dreporte
        df = leer_dreporte()
        # El filtro ya se aplicó, no debe haber profesores
        assert "Rol" in df.columns
        assert (df["Rol"].str.strip().str.lower() == "estudiante").all()

    def test_sin_suspendidos(self):
        from src.ingest.dreporte_reader import leer_dreporte
        df = leer_dreporte()
        # Columna Estado fue removida por merger, pero aquí todavía existe
        if "Estado" in df.columns:
            assert (df["Estado"].str.strip().str.lower() != "suspendido").all()

    def test_progreso_numerico(self):
        from src.ingest.dreporte_reader import leer_dreporte
        df = leer_dreporte()
        assert pd.api.types.is_numeric_dtype(df["Progreso del estudiante"])
        assert (df["Progreso del estudiante"] >= 0).all()

    def test_llave_generada(self):
        from src.ingest.dreporte_reader import leer_dreporte
        df = leer_dreporte()
        assert "LLave" in df.columns


class TestSenceReader:
    def test_lectura_basica(self):
        from src.ingest.sence_reader import leer_sence
        df = leer_sence()
        assert isinstance(df, pd.DataFrame)
        assert len(df) > 0

    def test_columnas_esperadas(self):
        from src.ingest.sence_reader import leer_sence
        df = leer_sence()
        for col in ["LLave", "IDUser", "IDSence", "N_Ingresos", "DJ"]:
            assert col in df.columns, f"Falta columna {col}"

    def test_llave_no_vacia(self):
        from src.ingest.sence_reader import leer_sence
        df = leer_sence()
        assert (df["LLave"].str.strip() != "").all()

    def test_n_ingresos_entero(self):
        from src.ingest.sence_reader import leer_sence
        df = leer_sence()
        assert pd.api.types.is_integer_dtype(df["N_Ingresos"])


class TestCompradoresReader:
    def test_lectura_basica(self):
        from src.ingest.compradores_reader import leer_compradores
        df = leer_compradores()
        assert isinstance(df, pd.DataFrame)

    def test_columnas_esperadas(self):
        from src.ingest.compradores_reader import leer_compradores
        df = leer_compradores()
        for col in ["id_curso_moodle", "comprador_nombre", "empresa", "email_comprador"]:
            assert col in df.columns, f"Falta columna {col}"

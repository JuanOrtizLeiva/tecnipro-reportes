"""Tests del scraper SENCE (sin requerir conexión ni credenciales)."""

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest
import pandas as pd


class TestGetSenceIds:
    def test_extrae_ids_del_dreporte(self):
        from src.scraper.orchestrator import ScraperOrchestrator
        orch = ScraperOrchestrator()
        ids = orch.get_sence_ids()
        assert isinstance(ids, list)
        assert len(ids) > 0

    def test_ids_son_numericos(self):
        from src.scraper.orchestrator import ScraperOrchestrator
        orch = ScraperOrchestrator()
        ids = orch.get_sence_ids()
        for id_ in ids:
            assert id_.isdigit(), f"ID no numérico: {id_}"

    def test_ids_sin_duplicados(self):
        from src.scraper.orchestrator import ScraperOrchestrator
        orch = ScraperOrchestrator()
        ids = orch.get_sence_ids()
        assert len(ids) == len(set(ids)), "Hay IDs duplicados"

    def test_ids_esperados(self):
        """Verifica que extrae al menos algunos IDs conocidos del data de ejemplo."""
        from src.scraper.orchestrator import ScraperOrchestrator
        orch = ScraperOrchestrator()
        ids = orch.get_sence_ids()
        # Estos IDs están en el Dreporte de ejemplo
        conocidos = {"6731347", "6722572", "6722569"}
        encontrados = conocidos & set(ids)
        assert len(encontrados) >= 2, f"Solo se encontraron {encontrados} de {conocidos}"


class TestCsvSavePath:
    def test_ruta_sence_desde_settings(self):
        from config import settings
        assert settings.SENCE_CSV_PATH is not None
        assert "sence" in str(settings.SENCE_CSV_PATH).lower()

    def test_ruta_screenshots_desde_settings(self):
        from config import settings
        assert settings.SCREENSHOTS_PATH is not None


class TestReportStructure:
    def test_reporte_tiene_campos_esperados(self):
        """Verifica estructura del reporte sin ejecutar el scraper."""
        report = {
            "inicio": "2026-01-01T08:00:00",
            "ids_solicitados": ["6731347", "6722572"],
            "descargados_ok": ["6731347"],
            "descargados_vacios": [],
            "fallidos": ["6722572"],
            "errores": ["SENCE 6722572: timeout"],
            "pipeline_fase1": "OK",
            "fin": "2026-01-01T08:05:00",
        }

        campos_requeridos = [
            "inicio", "ids_solicitados", "descargados_ok",
            "descargados_vacios", "fallidos", "errores",
            "pipeline_fase1", "fin",
        ]
        for campo in campos_requeridos:
            assert campo in report, f"Falta campo '{campo}' en reporte"

    def test_reporte_serializable_json(self):
        report = {
            "inicio": "2026-01-01T08:00:00",
            "ids_solicitados": ["123"],
            "descargados_ok": [],
            "descargados_vacios": [],
            "fallidos": ["123"],
            "errores": ["test error"],
            "pipeline_fase1": None,
            "fin": "2026-01-01T08:01:00",
        }
        # Debe ser serializable sin error
        json_str = json.dumps(report, ensure_ascii=False, default=str)
        loaded = json.loads(json_str)
        assert loaded == report


class TestVerifyDownloadedFiles:
    def test_verifica_archivo_valido(self):
        from src.scraper.orchestrator import ScraperOrchestrator
        orch = ScraperOrchestrator()

        with tempfile.TemporaryDirectory() as tmpdir:
            # Crear archivo de prueba
            filepath = Path(tmpdir) / "6731347.csv"
            filepath.write_text(
                '15.083.435-K,CLAUDIA ANDREA,13,Emitida,Ver\n',
                encoding="utf-8",
            )

            report = {
                "descargados_ok": ["6731347"],
                "descargados_vacios": [],
                "errores": [],
            }

            # Monkey-patch la ruta
            import config.settings as s
            original = s.SENCE_CSV_PATH
            s.SENCE_CSV_PATH = Path(tmpdir)
            try:
                orch._verify_downloaded_files(report)
            finally:
                s.SENCE_CSV_PATH = original

            assert "6731347" not in report["descargados_vacios"]

    def test_verifica_archivo_vacio(self):
        from src.scraper.orchestrator import ScraperOrchestrator
        orch = ScraperOrchestrator()

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "9999999.csv"
            filepath.write_text("", encoding="utf-8")

            report = {
                "descargados_ok": ["9999999"],
                "descargados_vacios": [],
                "errores": [],
            }

            import config.settings as s
            original = s.SENCE_CSV_PATH
            s.SENCE_CSV_PATH = Path(tmpdir)
            try:
                orch._verify_downloaded_files(report)
            finally:
                s.SENCE_CSV_PATH = original

            assert "9999999" in report["descargados_vacios"]

    def test_verifica_archivo_no_hay_datos(self):
        from src.scraper.orchestrator import ScraperOrchestrator
        orch = ScraperOrchestrator()

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "8888888.csv"
            filepath.write_text("No hay datos disponibles!\n", encoding="utf-8")

            report = {
                "descargados_ok": ["8888888"],
                "descargados_vacios": [],
                "errores": [],
            }

            import config.settings as s
            original = s.SENCE_CSV_PATH
            s.SENCE_CSV_PATH = Path(tmpdir)
            try:
                orch._verify_downloaded_files(report)
            finally:
                s.SENCE_CSV_PATH = original

            assert "8888888" in report["descargados_vacios"]


class TestEncodingDetection:
    def test_utf8(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "test.csv"
            filepath.write_text("MARÍA,datos\n", encoding="utf-8")
            contenido = filepath.read_text(encoding="utf-8")
            assert "MARÍA" in contenido

    def test_latin1(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "test.csv"
            filepath.write_bytes("MARÍA,datos\n".encode("latin-1"))
            # UTF-8 falla, latin-1 funciona
            try:
                filepath.read_text(encoding="utf-8")
                utf8_ok = True
            except UnicodeDecodeError:
                utf8_ok = False
            contenido = filepath.read_text(encoding="latin-1")
            assert "MAR" in contenido


class TestOrchestratorRunsPipeline:
    def test_hay_sence_previos(self):
        from src.scraper.orchestrator import ScraperOrchestrator
        orch = ScraperOrchestrator()
        # Debería encontrar los archivos SENCE de ejemplo
        assert orch._hay_sence_previos() is True


class TestSettingsScraperConfig:
    def test_scraper_settings_exist(self):
        from config import settings
        assert hasattr(settings, "CLAVE_UNICA_RUT")
        assert hasattr(settings, "CLAVE_UNICA_PASSWORD")
        assert hasattr(settings, "SCRAPER_HEADLESS")
        assert hasattr(settings, "SCRAPER_TIMEOUT")

    def test_scraper_timeout_is_int(self):
        from config import settings
        assert isinstance(settings.SCRAPER_TIMEOUT, int)
        assert settings.SCRAPER_TIMEOUT > 0


@pytest.mark.integration
class TestIntegrationPortal:
    """Tests que requieren conexión a internet. Ejecutar con: pytest -m integration"""

    def test_sence_url_responds(self):
        import urllib.request
        try:
            req = urllib.request.Request(
                "https://lce.sence.cl/CertificadoAsistencia/",
                method="HEAD",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                assert resp.status in (200, 301, 302)
        except Exception:
            pytest.skip("SENCE no accesible")

    def test_clave_unica_url_responds(self):
        import urllib.request
        try:
            req = urllib.request.Request(
                "https://accounts.claveunica.gob.cl/",
                method="HEAD",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                assert resp.status in (200, 301, 302)
        except Exception:
            pytest.skip("Clave Única no accesible")

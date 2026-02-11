"""Tests para el servidor web Flask (Fase 3.5).

Nota: Estos tests usan LOGIN_DISABLED=True para testear funcionalidad web
sin autenticación. Los tests de autenticación están en test_auth.py.
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Necesitamos que config sea importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ── Fixtures ────────────────────────────────────────────────

@pytest.fixture
def sample_json_data():
    """Datos de ejemplo que simulan datos_procesados.json."""
    return {
        "metadata": {
            "fecha_procesamiento": "2026-02-10T23:37:18",
            "total_cursos": 1,
            "total_estudiantes": 2,
            "version": "1.0",
        },
        "cursos": [
            {
                "id_moodle": "140",
                "id_sence": "6731347",
                "nombre": "Curso de Prueba",
                "nombre_corto": "140",
                "categoria": "Test",
                "fecha_inicio": "2025-11-17",
                "fecha_fin": "2025-12-31",
                "estado": "expired",
                "dias_restantes": -41,
                "comprador": {
                    "nombre": "Test",
                    "empresa": "TestCo",
                    "email": "test@test.cl",
                },
                "estudiantes": [
                    {
                        "id": "12345678-9",
                        "nombre": "Juan Pérez",
                        "email": "juan@test.cl",
                        "progreso": 100.0,
                        "calificacion": 7.0,
                        "ultimo_acceso": "2026-01-07",
                        "dias_sin_ingreso": 33,
                        "estado": "A",
                        "riesgo": "",
                        "sence": {
                            "id_sence": "6731347",
                            "n_ingresos": 4,
                            "estado": "CONECTADO",
                            "declaracion_jurada": "",
                        },
                    },
                    {
                        "id": "98765432-1",
                        "nombre": "María López",
                        "email": "maria@test.cl",
                        "progreso": 50.0,
                        "calificacion": 4.5,
                        "ultimo_acceso": "2025-12-20",
                        "dias_sin_ingreso": 52,
                        "estado": "P",
                        "riesgo": "medio",
                        "sence": None,
                    },
                ],
                "estadisticas": {
                    "total_estudiantes": 2,
                    "promedio_progreso": 75.0,
                    "promedio_calificacion": 5.75,
                    "aprobados": 1,
                    "reprobados": 0,
                    "en_proceso": 1,
                    "riesgo_alto": 0,
                    "riesgo_medio": 1,
                    "conectados_sence": 1,
                },
            }
        ],
    }


@pytest.fixture
def json_file(tmp_path, sample_json_data):
    """Crea un archivo JSON temporal con datos de prueba."""
    path = tmp_path / "datos_procesados.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sample_json_data, f, ensure_ascii=False)
    return path


@pytest.fixture
def app_client(json_file, tmp_path):
    """Crea un test client de Flask con datos de prueba (login deshabilitado)."""
    with patch("config.settings.JSON_DATOS_PATH", json_file), \
         patch("config.settings.TEMPLATES_PATH",
               Path(__file__).resolve().parent.parent / "templates"):
        from src.web.app import create_app
        app = create_app()
        app.config["TESTING"] = True
        app.config["LOGIN_DISABLED"] = True
        with app.test_client() as client:
            yield client


@pytest.fixture
def app_client_no_json(tmp_path):
    """Test client sin datos JSON (simula pipeline no ejecutado)."""
    fake_path = tmp_path / "no_existe.json"
    with patch("config.settings.JSON_DATOS_PATH", fake_path), \
         patch("config.settings.TEMPLATES_PATH",
               Path(__file__).resolve().parent.parent / "templates"):
        from src.web.app import create_app
        app = create_app()
        app.config["TESTING"] = True
        app.config["LOGIN_DISABLED"] = True
        with app.test_client() as client:
            yield client


# ── Test 1: Index retorna HTML ───────────────────────────

class TestIndexRoute:
    def test_index_returns_html(self, app_client):
        """GET / retorna 200 y content-type text/html."""
        response = app_client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.content_type
        assert b"Sistema de Gesti" in response.data  # título del dashboard


# ── Test 2: API datos ────────────────────────────────────

class TestApiDatos:
    def test_api_datos_returns_json(self, app_client):
        """GET /api/datos retorna JSON válido con cursos y metadata."""
        response = app_client.get("/api/datos")
        assert response.status_code == 200
        assert response.content_type == "application/json"
        data = response.get_json()
        assert "metadata" in data
        assert "cursos" in data
        assert data["metadata"]["total_cursos"] == 1
        assert len(data["cursos"]) == 1
        assert len(data["cursos"][0]["estudiantes"]) == 2

    def test_api_datos_sin_json(self, app_client_no_json):
        """Si no existe datos_procesados.json, retorna 404."""
        response = app_client_no_json.get("/api/datos")
        assert response.status_code == 404
        data = response.get_json()
        assert "error" in data


# ── Test 3: Health check ─────────────────────────────────

class TestApiHealth:
    def test_api_health(self, app_client):
        """GET /api/health retorna status ok y fecha de datos."""
        response = app_client.get("/api/health")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "ok"
        assert data["fecha_datos"] == "2026-02-10T23:37:18"

    def test_api_health_sin_json(self, app_client_no_json):
        """Health check sin JSON retorna ok pero fecha_datos null."""
        response = app_client_no_json.get("/api/health")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "ok"
        assert data["fecha_datos"] is None


# ── Test 4: Enviar correo - validación ──────────────────

class TestApiEnviarCorreo:
    def test_sin_destinatarios(self, app_client):
        """POST /api/enviar-correo sin destinatarios retorna 400."""
        response = app_client.post(
            "/api/enviar-correo",
            json={"asunto": "Test", "cuerpo": "Hola"},
        )
        assert response.status_code == 400
        assert "destinatario" in response.get_json()["error"].lower()

    def test_sin_asunto(self, app_client):
        """POST /api/enviar-correo sin asunto retorna 400."""
        response = app_client.post(
            "/api/enviar-correo",
            json={"destinatarios": ["a@b.cl"], "cuerpo": "Hola"},
        )
        assert response.status_code == 400
        assert "asunto" in response.get_json()["error"].lower()

    def test_sin_cuerpo(self, app_client):
        """POST /api/enviar-correo sin cuerpo retorna 400."""
        response = app_client.post(
            "/api/enviar-correo",
            json={"destinatarios": ["a@b.cl"], "asunto": "Test"},
        )
        assert response.status_code == 400
        assert "cuerpo" in response.get_json()["error"].lower()

    def test_envio_exitoso(self, app_client):
        """POST /api/enviar-correo con datos válidos envía correo."""
        with patch("src.reports.email_sender.enviar_correo") as mock_enviar:
            mock_enviar.return_value = {"status": "OK", "detalle": "Enviado"}
            response = app_client.post(
                "/api/enviar-correo",
                json={
                    "destinatarios": ["juan@test.cl", "maria@test.cl"],
                    "asunto": "Test Dashboard",
                    "cuerpo": "Hola desde el dashboard",
                },
            )
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "ok"
        assert data["enviados"] == 2
        mock_enviar.assert_called_once()

    def test_envio_fallido(self, app_client):
        """POST /api/enviar-correo con error retorna 500."""
        with patch("src.reports.email_sender.enviar_correo") as mock_enviar:
            mock_enviar.return_value = {"status": "ERROR", "detalle": "Sin token"}
            response = app_client.post(
                "/api/enviar-correo",
                json={
                    "destinatarios": ["juan@test.cl"],
                    "asunto": "Test",
                    "cuerpo": "Hola",
                },
            )
        assert response.status_code == 500
        assert "error" in response.get_json()

    def test_sin_json_body(self, app_client):
        """POST /api/enviar-correo sin body JSON retorna 400."""
        response = app_client.post(
            "/api/enviar-correo",
            data="no es json",
            content_type="text/plain",
        )
        assert response.status_code == 400


# ── Test 5: Security headers ────────────────────────────

class TestSecurityHeaders:
    def test_x_frame_options(self, app_client):
        """Respuestas incluyen X-Frame-Options: DENY."""
        response = app_client.get("/")
        assert response.headers.get("X-Frame-Options") == "DENY"

    def test_x_content_type_options(self, app_client):
        """Respuestas incluyen X-Content-Type-Options: nosniff."""
        response = app_client.get("/api/health")
        assert response.headers.get("X-Content-Type-Options") == "nosniff"


# ── Test 6: Rate limiting ────────────────────────────────

class TestRateLimiting:
    def test_rate_limiting(self, app_client):
        """Más de 10 envíos por minuto son rechazados con 429."""
        # Reset timestamps for clean test
        from src.web import routes
        routes._email_timestamps.clear()

        with patch("src.reports.email_sender.enviar_correo") as mock_enviar:
            mock_enviar.return_value = {"status": "OK", "detalle": "OK"}

            payload = {
                "destinatarios": ["test@test.cl"],
                "asunto": "Rate test",
                "cuerpo": "Test",
            }

            # 10 envíos OK
            for i in range(10):
                resp = app_client.post("/api/enviar-correo", json=payload)
                assert resp.status_code == 200, f"Request {i+1} should succeed"

            # El 11vo debe ser rechazado
            resp = app_client.post("/api/enviar-correo", json=payload)
            assert resp.status_code == 429

        # Limpiar para no afectar otros tests
        routes._email_timestamps.clear()


# ── Test 7: Dashboard carga datos vía fetch ──────────────

class TestDashboardLoadData:
    def test_dashboard_contains_fetch_call(self, app_client):
        """El HTML del dashboard contiene la llamada a /api/datos."""
        response = app_client.get("/")
        html = response.data.decode("utf-8")
        assert "/api/datos" in html
        assert "fetch(" in html
        assert "loadData" in html

    def test_dashboard_no_hardcoded_data(self, app_client):
        """El dashboard no tiene datos hardcodeados (const DATA = {...})."""
        response = app_client.get("/")
        html = response.data.decode("utf-8")
        assert "const DATA = {" not in html
        assert "let DATA = null" in html

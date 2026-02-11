"""Tests de autenticación — Fase 4."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import bcrypt
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ── Helpers ────────────────────────────────────────────────

def _make_hash(password):
    """Helper para generar hash bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=4)).decode("utf-8")


def _make_usuarios_file(tmp_path, users=None):
    """Crea un archivo usuarios.json temporal."""
    if users is None:
        users = [
            {
                "email": "admin@test.cl",
                "password_hash": _make_hash("admin123"),
                "nombre": "Admin Test",
                "rol": "admin",
                "cursos": [],
            },
            {
                "email": "comprador@test.cl",
                "password_hash": _make_hash("comp123"),
                "nombre": "Comprador Test",
                "rol": "comprador",
                "cursos": [140],
            },
        ]
    path = tmp_path / "usuarios.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"usuarios": users}, f, ensure_ascii=False)
    return path


def _make_json_file(tmp_path):
    """Crea datos_procesados.json temporal con 2 cursos."""
    data = {
        "metadata": {
            "fecha_procesamiento": "2026-02-10T23:37:18",
            "total_cursos": 2,
            "total_estudiantes": 3,
            "version": "1.0",
        },
        "cursos": [
            {
                "id_moodle": "140",
                "id_sence": "6731347",
                "nombre": "Curso 140",
                "nombre_corto": "140",
                "categoria": "Test",
                "fecha_inicio": "2025-11-17",
                "fecha_fin": "2025-12-31",
                "estado": "expired",
                "dias_restantes": -41,
                "comprador": {
                    "nombre": "Comprador Test",
                    "empresa": "TestCo",
                    "email": "comprador@test.cl",
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
                        "sence": {"id_sence": "6731347", "n_ingresos": 4, "estado": "CONECTADO", "declaracion_jurada": ""},
                    },
                ],
                "estadisticas": {
                    "total_estudiantes": 1,
                    "promedio_progreso": 100.0,
                    "promedio_calificacion": 7.0,
                    "aprobados": 1,
                    "reprobados": 0,
                    "en_proceso": 0,
                    "riesgo_alto": 0,
                    "riesgo_medio": 0,
                    "conectados_sence": 1,
                },
            },
            {
                "id_moodle": "141",
                "id_sence": "6731348",
                "nombre": "Curso 141",
                "nombre_corto": "141",
                "categoria": "Test",
                "fecha_inicio": "2025-11-17",
                "fecha_fin": "2025-12-31",
                "estado": "expired",
                "dias_restantes": -41,
                "comprador": {
                    "nombre": "Otro",
                    "empresa": "OtraCo",
                    "email": "otro@test.cl",
                },
                "estudiantes": [
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
                    {
                        "id": "11111111-1",
                        "nombre": "Pedro Soto",
                        "email": "pedro@test.cl",
                        "progreso": 30.0,
                        "calificacion": 3.0,
                        "ultimo_acceso": "2025-12-10",
                        "dias_sin_ingreso": 62,
                        "estado": "R",
                        "riesgo": "alto",
                        "sence": None,
                    },
                ],
                "estadisticas": {
                    "total_estudiantes": 2,
                    "promedio_progreso": 40.0,
                    "promedio_calificacion": 3.75,
                    "aprobados": 0,
                    "reprobados": 1,
                    "en_proceso": 1,
                    "riesgo_alto": 1,
                    "riesgo_medio": 1,
                    "conectados_sence": 0,
                },
            },
        ],
    }
    path = tmp_path / "datos_procesados.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return path


# ── Fixtures ──────────────────────────────────────────────

@pytest.fixture
def auth_app(tmp_path):
    """Crea app Flask con usuarios de prueba y datos JSON."""
    usuarios_path = _make_usuarios_file(tmp_path)
    json_path = _make_json_file(tmp_path)

    with patch("config.settings.USUARIOS_PATH", usuarios_path), \
         patch("config.settings.JSON_DATOS_PATH", json_path), \
         patch("config.settings.TEMPLATES_PATH",
               Path(__file__).resolve().parent.parent / "templates"):
        from src.web.app import create_app
        app = create_app()
        app.config["TESTING"] = True
        yield app


@pytest.fixture
def auth_app_client(auth_app):
    """Test client from the auth app."""
    with auth_app.test_client() as client:
        yield client


def _login_session(client, user_email):
    """Simula login estableciendo la sesión directamente."""
    with client.session_transaction() as sess:
        sess["_user_id"] = user_email
        sess["_fresh"] = True


def _login_form(client, email, password):
    """Login vía formulario POST."""
    return client.post("/login", data={"email": email, "password": password},
                       follow_redirects=False)


# ── Test 1: Login page renders ────────────────────────────

class TestLoginPage:
    def test_login_page_renders(self, auth_app_client):
        """GET /login retorna 200 con formulario."""
        response = auth_app_client.get("/login")
        assert response.status_code == 200
        assert b"Ingresar" in response.data
        assert b"email" in response.data
        assert b"password" in response.data


# ── Test 2: Login success admin ───────────────────────────

class TestLoginSuccessAdmin:
    def test_login_success_admin(self, auth_app_client):
        """Login con credenciales admin válidas redirige a /."""
        resp = _login_form(auth_app_client, "admin@test.cl", "admin123")
        assert resp.status_code == 302
        assert resp.headers.get("Location") in ("/", "http://localhost/")


# ── Test 3: Login success comprador ───────────────────────

class TestLoginSuccessComprador:
    def test_login_success_comprador(self, auth_app_client):
        """Login con credenciales comprador válidas redirige a /."""
        resp = _login_form(auth_app_client, "comprador@test.cl", "comp123")
        assert resp.status_code == 302
        assert resp.headers.get("Location") in ("/", "http://localhost/")


# ── Test 4: Login failure ─────────────────────────────────

class TestLoginFailure:
    def test_login_failure(self, auth_app_client):
        """Credenciales inválidas muestra error."""
        resp = _login_form(auth_app_client, "admin@test.cl", "wrong")
        assert resp.status_code == 200
        assert "inv" in resp.data.decode("utf-8").lower()  # "inválidas"


# ── Test 5: Logout ────────────────────────────────────────

class TestLogout:
    def test_logout(self, auth_app_client):
        """GET /logout destruye sesión y redirige a /login."""
        _login_session(auth_app_client, "admin@test.cl")
        resp = auth_app_client.get("/logout", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers.get("Location", "")

        # Verificar que ya no tiene acceso
        resp2 = auth_app_client.get("/api/me")
        assert resp2.status_code == 302  # redirige a login


# ── Test 6: Protected routes ─────────────────────────────

class TestProtectedRoutes:
    def test_protected_routes(self, auth_app_client):
        """Rutas sin login redirigen a /login."""
        for path in ["/", "/api/datos", "/api/me"]:
            resp = auth_app_client.get(path)
            assert resp.status_code == 302, f"{path} should redirect"
            assert "/login" in resp.headers.get("Location", ""), f"{path} should redirect to /login"

        # POST endpoint also requires auth
        resp = auth_app_client.post("/api/enviar-correo", json={
            "destinatarios": ["a@b.cl"], "asunto": "t", "cuerpo": "t",
        })
        assert resp.status_code == 302

    def test_health_is_public(self, auth_app_client):
        """Health check no requiere login."""
        resp = auth_app_client.get("/api/health")
        assert resp.status_code == 200


# ── Test 7: API datos admin — all courses ─────────────────

class TestApiDatosAdmin:
    def test_api_datos_admin_all_courses(self, auth_app_client):
        """Admin recibe todos los cursos."""
        _login_session(auth_app_client, "admin@test.cl")
        resp = auth_app_client.get("/api/datos")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["cursos"]) == 2
        assert data["metadata"]["total_cursos"] == 2


# ── Test 8: API datos comprador — filtered ────────────────

class TestApiDatosComprador:
    def test_api_datos_comprador_filtered(self, auth_app_client):
        """Comprador recibe solo sus cursos (id_moodle=140)."""
        _login_session(auth_app_client, "comprador@test.cl")
        resp = auth_app_client.get("/api/datos")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["cursos"]) == 1
        assert data["cursos"][0]["id_moodle"] == "140"
        assert data["metadata"]["total_cursos"] == 1
        assert data["metadata"]["total_estudiantes"] == 1


# ── Test 9: API /api/me admin ─────────────────────────────

class TestApiMeAdmin:
    def test_api_me_admin(self, auth_app_client):
        """GET /api/me retorna rol admin."""
        _login_session(auth_app_client, "admin@test.cl")
        resp = auth_app_client.get("/api/me")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["email"] == "admin@test.cl"
        assert data["nombre"] == "Admin Test"
        assert data["rol"] == "admin"


# ── Test 10: API /api/me comprador ────────────────────────

class TestApiMeComprador:
    def test_api_me_comprador(self, auth_app_client):
        """GET /api/me retorna rol comprador con cursos."""
        _login_session(auth_app_client, "comprador@test.cl")
        resp = auth_app_client.get("/api/me")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["rol"] == "comprador"
        assert 140 in data["cursos"]


# ── Test 11: Comprador cannot send email ──────────────────

class TestCompradorCannotSendEmail:
    def test_comprador_cannot_send_email(self, auth_app_client):
        """POST /api/enviar-correo con comprador retorna 403."""
        _login_session(auth_app_client, "comprador@test.cl")
        resp = auth_app_client.post(
            "/api/enviar-correo",
            json={
                "destinatarios": ["test@test.cl"],
                "asunto": "Test",
                "cuerpo": "Hola",
            },
        )
        assert resp.status_code == 403


# ── Test 12: Rate limiting login ──────────────────────────

class TestRateLimitingLogin:
    def test_rate_limiting_login(self, auth_app_client):
        """Más de 5 intentos de login bloquea con 429."""
        from src.web import auth
        auth._login_attempts.clear()

        for i in range(5):
            _login_form(auth_app_client, "bad@test.cl", "wrong")

        # El 6to intento debe ser bloqueado
        resp = _login_form(auth_app_client, "bad@test.cl", "wrong")
        assert resp.status_code == 429

        auth._login_attempts.clear()


# ── Test 13: Password hashing ─────────────────────────────

class TestPasswordHashing:
    def test_password_hashing(self):
        """bcrypt hash y verificación funcionan correctamente."""
        from src.web.auth import hash_password
        hashed = hash_password("testpass")
        assert hashed.startswith("$2b$")
        assert bcrypt.checkpw(b"testpass", hashed.encode("utf-8"))
        assert not bcrypt.checkpw(b"wrongpass", hashed.encode("utf-8"))


# ── Test 14: User manager add ─────────────────────────────

class TestUserManagerAdd:
    def test_user_manager_add(self, tmp_path):
        """Agregar usuario funciona."""
        path = tmp_path / "usuarios.json"
        with patch("config.settings.USUARIOS_PATH", path):
            from src.web.user_manager import add_user, _load_users
            result = add_user("new@test.cl", "New User", "admin", "pass123")
            assert result is True
            data = _load_users()
            assert len(data["usuarios"]) == 1
            assert data["usuarios"][0]["email"] == "new@test.cl"
            assert data["usuarios"][0]["rol"] == "admin"

    def test_user_manager_add_duplicate(self, tmp_path):
        """No permite duplicados."""
        path = _make_usuarios_file(tmp_path)
        with patch("config.settings.USUARIOS_PATH", path):
            from src.web.user_manager import add_user
            result = add_user("admin@test.cl", "Dup", "admin", "pass")
            assert result is False


# ── Test 15: User manager list ────────────────────────────

class TestUserManagerList:
    def test_user_manager_list(self, tmp_path, capsys):
        """Listar usuarios funciona."""
        path = _make_usuarios_file(tmp_path)
        with patch("config.settings.USUARIOS_PATH", path):
            from src.web.user_manager import list_users
            list_users()
            output = capsys.readouterr().out
            assert "admin@test.cl" in output
            assert "comprador@test.cl" in output
            assert "Total: 2" in output


# ── Test 16: User manager remove ──────────────────────────

class TestUserManagerRemove:
    def test_user_manager_remove(self, tmp_path):
        """Eliminar usuario funciona."""
        path = _make_usuarios_file(tmp_path)
        with patch("config.settings.USUARIOS_PATH", path):
            from src.web.user_manager import remove_user, _load_users
            result = remove_user("comprador@test.cl")
            assert result is True
            data = _load_users()
            assert len(data["usuarios"]) == 1
            assert data["usuarios"][0]["email"] == "admin@test.cl"

    def test_user_manager_remove_nonexistent(self, tmp_path):
        """Eliminar usuario inexistente retorna False."""
        path = _make_usuarios_file(tmp_path)
        with patch("config.settings.USUARIOS_PATH", path):
            from src.web.user_manager import remove_user
            result = remove_user("noexiste@test.cl")
            assert result is False

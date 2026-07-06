"""Autenticación con Flask-Login — usuarios desde JSON."""

import fcntl
import json
import logging
import os
import time
from pathlib import Path

import bcrypt
from flask_login import LoginManager, UserMixin

from config import settings

logger = logging.getLogger(__name__)

# Rate limiting para login: máximo 5 intentos por IP cada 15 minutos.
# Estado compartido entre workers de gunicorn vía archivo + fcntl locks
# (stdlib, sin dependencias extra). Simple y atómico para una sola máquina.
LOGIN_RATE_LIMIT_MAX = 5
LOGIN_RATE_LIMIT_WINDOW = 900  # 15 minutos en segundos
LOGIN_RATE_LIMIT_FILE = Path("/tmp/tecnipro_login_rate_limit.json")

login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.login_message = ""


class User(UserMixin):
    """Modelo de usuario para Flask-Login."""

    # Todos los permisos disponibles en el sistema
    TODOS_LOS_PERMISOS = {
        "dashboard", "sii_monitor", "licitaciones",
        "encuestas", "evalpro", "erp", "cotizador", "sence", "coordinadores",
        "control_general", "carga_academica", "diplomas", "dashboard_sincronico",
        "certificados",
    }

    def __init__(self, email, nombre, rol, cursos, password_hash="", permisos=None):
        self.id = email  # Flask-Login usa self.id
        self.email = email
        self.nombre = nombre
        self.rol = rol
        self.cursos = cursos or []
        self.password_hash = password_hash
        # Admin tiene todos los permisos; comprador recibe "dashboard" por
        # defecto (su uso natural: ver sus cursos asignados) más cualquier
        # permiso adicional explícito; otros roles solo los explícitos.
        if rol in ("admin", "superadmin"):
            self.permisos = set(self.TODOS_LOS_PERMISOS)
        elif rol == "comprador":
            self.permisos = {"dashboard"} | (set(permisos) if permisos else set())
        else:
            self.permisos = set(permisos) if permisos else set()

    def tiene_permiso(self, permiso):
        """Verifica si el usuario tiene un permiso específico."""
        return permiso in self.permisos

    def to_dict(self):
        """Serializa el usuario (sin password_hash) para /api/me."""
        return {
            "email": self.email,
            "nombre": self.nombre,
            "rol": self.rol,
            "cursos": self.cursos,
            "permisos": sorted(self.permisos),
        }


def _load_users_file():
    """Lee usuarios.json y retorna la lista de dicts."""
    path = settings.USUARIOS_PATH
    if not path.exists():
        logger.warning("Archivo de usuarios no encontrado: %s", path)
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("usuarios", [])


def _find_user_data(email):
    """Busca un usuario por email en el JSON."""
    for u in _load_users_file():
        if u["email"].lower() == email.lower():
            return u
    return None


@login_manager.user_loader
def load_user(user_id):
    """Callback de Flask-Login para cargar usuario desde sesión."""
    data = _find_user_data(user_id)
    if data is None:
        return None
    return User(
        email=data["email"],
        nombre=data["nombre"],
        rol=data["rol"],
        cursos=data.get("cursos", []),
        password_hash=data.get("password_hash", ""),
        permisos=data.get("permisos", []),
    )


def verify_password(email, password):
    """Verifica credenciales. Retorna User si son válidas, None si no."""
    data = _find_user_data(email)
    if data is None:
        return None

    stored_hash = data.get("password_hash", "")
    if not stored_hash:
        return None

    try:
        if bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8")):
            return User(
                email=data["email"],
                nombre=data["nombre"],
                rol=data["rol"],
                cursos=data.get("cursos", []),
                password_hash=stored_hash,
                permisos=data.get("permisos", []),
            )
    except (ValueError, TypeError):
        logger.error("Error verificando password para %s", email)

    return None


def hash_password(password):
    """Genera hash bcrypt de una contraseña."""
    return bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt(rounds=12),
    ).decode("utf-8")


def check_login_rate_limit(ip):
    """Retorna True si el IP excedió el límite de intentos de login.

    Estado persistido en archivo con fcntl lock exclusivo para que todos
    los workers de gunicorn vean el mismo contador (antes cada worker
    tenía su propio defaultdict en memoria → el límite efectivo era N*5).
    """
    now = time.time()
    try:
        # Abrir/crear archivo en modo read+write; crear si no existe.
        fd = os.open(str(LOGIN_RATE_LIMIT_FILE), os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as exc:
        logger.error("No se pudo abrir archivo rate-limit: %s — fallback allow", exc)
        return False

    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            raw = os.read(fd, 1024 * 1024).decode("utf-8") or "{}"
            state = json.loads(raw) if raw.strip() else {}
        except (ValueError, json.JSONDecodeError):
            state = {}

        # Purgar intentos fuera de ventana y limpiar IPs sin intentos
        attempts = [
            t for t in state.get(ip, []) if now - t < LOGIN_RATE_LIMIT_WINDOW
        ]
        # GC ocasional: descartar IPs con lista vacía tras purga
        state = {
            k: [t for t in v if now - t < LOGIN_RATE_LIMIT_WINDOW]
            for k, v in state.items()
            if k != ip
        }
        state = {k: v for k, v in state.items() if v}

        if len(attempts) >= LOGIN_RATE_LIMIT_MAX:
            state[ip] = attempts  # conservar timestamps para próxima llamada
            exceeded = True
        else:
            attempts.append(now)
            state[ip] = attempts
            exceeded = False

        # Reescribir archivo (truncar y escribir)
        payload = json.dumps(state).encode("utf-8")
        os.lseek(fd, 0, os.SEEK_SET)
        os.ftruncate(fd, 0)
        os.write(fd, payload)
        return exceeded
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)

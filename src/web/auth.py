"""Autenticación con Flask-Login — usuarios desde JSON."""

import json
import logging
import time
from collections import defaultdict
from pathlib import Path

import bcrypt
from flask_login import LoginManager, UserMixin

from config import settings

logger = logging.getLogger(__name__)

# Rate limiting para login: máximo 5 intentos por IP cada 15 minutos
_login_attempts = defaultdict(list)
LOGIN_RATE_LIMIT_MAX = 5
LOGIN_RATE_LIMIT_WINDOW = 900  # 15 minutos en segundos

login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.login_message = ""


class User(UserMixin):
    """Modelo de usuario para Flask-Login."""

    def __init__(self, email, nombre, rol, cursos, password_hash=""):
        self.id = email  # Flask-Login usa self.id
        self.email = email
        self.nombre = nombre
        self.rol = rol
        self.cursos = cursos or []
        self.password_hash = password_hash

    def to_dict(self):
        """Serializa el usuario (sin password_hash) para /api/me."""
        return {
            "email": self.email,
            "nombre": self.nombre,
            "rol": self.rol,
            "cursos": self.cursos,
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
    """Retorna True si el IP excedió el límite de intentos de login."""
    now = time.time()
    _login_attempts[ip] = [
        t for t in _login_attempts[ip] if now - t < LOGIN_RATE_LIMIT_WINDOW
    ]
    if len(_login_attempts[ip]) >= LOGIN_RATE_LIMIT_MAX:
        return True
    _login_attempts[ip].append(now)
    return False

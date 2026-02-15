"""Recuperación de contraseña por email."""

import json
import logging
import secrets
import time
from pathlib import Path

import requests

from config import settings
from src.web import user_manager

logger = logging.getLogger(__name__)

# Almacenamiento temporal de tokens (en producción usar Redis/DB)
_reset_tokens_path = settings.PROJECT_ROOT / "data" / "config" / "reset_tokens.json"
TOKEN_EXPIRY_SECONDS = 3600  # 1 hora

GRAPH_TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
GRAPH_SEND_MAIL_URL = "https://graph.microsoft.com/v1.0/users/{user}/sendMail"


def _load_tokens():
    """Carga tokens de reset desde archivo JSON."""
    if not _reset_tokens_path.exists():
        return {"tokens": []}
    with open(_reset_tokens_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_tokens(data):
    """Guarda tokens de reset a archivo JSON."""
    _reset_tokens_path.parent.mkdir(parents=True, exist_ok=True)
    with open(_reset_tokens_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _limpiar_tokens_expirados():
    """Elimina tokens que han expirado."""
    data = _load_tokens()
    now = time.time()
    data["tokens"] = [
        t for t in data["tokens"]
        if now - t["timestamp"] < TOKEN_EXPIRY_SECONDS
    ]
    _save_tokens(data)


def generar_token_reset(email):
    """Genera un token de reset para el usuario.

    Parameters
    ----------
    email : str
        Email del usuario.

    Returns
    -------
    str | None
        Token generado, o None si el usuario no existe.
    """
    # Verificar que el usuario existe
    user_data = user_manager._find_user_data(email)
    if not user_data:
        logger.warning("Intento de reset para email inexistente: %s", email)
        return None

    # Generar token seguro de 32 caracteres
    token = secrets.token_urlsafe(32)

    # Guardar token con timestamp
    _limpiar_tokens_expirados()
    data = _load_tokens()
    data["tokens"].append({
        "email": email,
        "token": token,
        "timestamp": time.time(),
    })
    _save_tokens(data)

    logger.info("Token de reset generado para %s", email)
    return token


def validar_token_reset(token):
    """Valida un token de reset.

    Parameters
    ----------
    token : str
        Token a validar.

    Returns
    -------
    str | None
        Email del usuario si el token es válido, None si no.
    """
    _limpiar_tokens_expirados()
    data = _load_tokens()

    for t in data["tokens"]:
        if t["token"] == token:
            return t["email"]

    return None


def invalidar_token_reset(token):
    """Invalida un token de reset después de usarlo.

    Parameters
    ----------
    token : str
        Token a invalidar.
    """
    data = _load_tokens()
    data["tokens"] = [t for t in data["tokens"] if t["token"] != token]
    _save_tokens(data)


def _obtener_token_azure():
    """Obtiene access token de Azure AD."""
    client_id = settings.AZURE_CLIENT_ID
    tenant_id = settings.AZURE_TENANT_ID
    client_secret = settings.AZURE_CLIENT_SECRET

    if not all([client_id, tenant_id, client_secret]):
        raise RuntimeError(
            "Credenciales Azure incompletas. Verificar AZURE_CLIENT_ID, "
            "AZURE_TENANT_ID, AZURE_CLIENT_SECRET en .env"
        )

    url = GRAPH_TOKEN_URL.format(tenant=tenant_id)
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials",
    }

    resp = requests.post(url, data=data, timeout=30)

    if resp.status_code != 200:
        raise RuntimeError(f"Error obteniendo token Azure (HTTP {resp.status_code})")

    return resp.json().get("access_token")


def enviar_email_credenciales(email, nombre, password, base_url):
    """Envía email con credenciales de acceso al crear coordinador.

    Parameters
    ----------
    email : str
        Email del usuario.
    nombre : str
        Nombre del usuario.
    password : str
        Contraseña generada.
    base_url : str
        URL base del servidor.

    Returns
    -------
    bool
        True si se envió correctamente, False si no.
    """
    html = f"""
<html>
<body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6;">
<p>Hola {nombre},</p>

<p>Se ha creado tu cuenta de acceso al <strong>Dashboard de Gestión de Capacitación</strong> de Instituto Tecnipro.</p>

<div style="background: #f8fafc; border-left: 4px solid #2563eb; padding: 1rem; margin: 1.5rem 0; border-radius: 4px;">
    <p style="margin: 0; font-size: 0.9rem; color: #64748b;"><strong>Tus credenciales de acceso:</strong></p>
    <p style="margin: 0.5rem 0 0; font-size: 1rem;">
        <strong>Usuario:</strong> {email}<br>
        <strong>Contraseña:</strong> <code style="background: #e2e8f0; padding: 0.25rem 0.5rem; border-radius: 3px; font-family: monospace;">{password}</code>
    </p>
</div>

<p>Para acceder al dashboard, ingresa a:</p>
<p style="margin: 1rem 0;">
    <a href="{base_url}"
       style="background-color: #2563eb; color: white; padding: 12px 24px;
              text-decoration: none; border-radius: 4px; display: inline-block; font-weight: 600;">
        Acceder al Dashboard
    </a>
</p>

<p style="margin-top: 1.5rem; font-size: 0.9rem; color: #64748b;">
    <strong>Nota:</strong> Por seguridad, te recomendamos cambiar tu contraseña después del primer inicio de sesión.
    Puedes hacerlo desde el enlace "¿Olvidaste tu contraseña?" en la página de login.
</p>

<hr style="border: 0; border-top: 1px solid #eee; margin: 2rem 0;">

<p style="font-size: 0.85rem; color: #999;">
    Este es un mensaje automático del sistema de Dashboard Tecnipro.<br>
    Por favor no respondas a este correo. Si tienes dudas, contacta al administrador.
</p>
</body>
</html>
"""

    # Obtener token de Azure
    try:
        access_token = _obtener_token_azure()
    except Exception as e:
        logger.error("Error obteniendo token Azure para email credenciales: %s", e)
        return False

    # Preparar mensaje
    remitente = "ygonzalez@duocapital.cl"
    mensaje = {
        "message": {
            "subject": "Credenciales de Acceso - Dashboard Tecnipro",
            "body": {
                "contentType": "HTML",
                "content": html,
            },
            "toRecipients": [
                {"emailAddress": {"address": email}}
            ],
        },
        "saveToSentItems": "false",
    }

    # Enviar correo
    url = GRAPH_SEND_MAIL_URL.format(user=remitente)
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(url, json=mensaje, headers=headers, timeout=30)

        if resp.status_code == 202:
            logger.info("Email de credenciales enviado a %s", email)
            return True
        else:
            logger.error(
                "Error enviando email de credenciales (HTTP %d): %s",
                resp.status_code,
                resp.text[:200]
            )
            return False

    except Exception as e:
        logger.error("Excepción enviando email de credenciales: %s", e)
        return False


def enviar_email_reset(email, token, base_url):
    """Envía email de recuperación de contraseña.

    Parameters
    ----------
    email : str
        Email del usuario.
    token : str
        Token de reset.
    base_url : str
        URL base del servidor (ej: "https://dashboard.tecnipro.cl").

    Returns
    -------
    bool
        True si se envió correctamente, False si no.
    """
    user_data = user_manager._find_user_data(email)
    if not user_data:
        return False

    nombre = user_data.get("nombre", "Usuario")
    reset_link = f"{base_url}/reset-password?token={token}"

    html = f"""
<html>
<body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6;">
<p>Hola {nombre},</p>

<p>Recibimos una solicitud para restablecer la contraseña de tu cuenta en el Dashboard Tecnipro.</p>

<p>Para crear una nueva contraseña, haz clic en el siguiente enlace:</p>

<p style="margin: 20px 0;">
    <a href="{reset_link}"
       style="background-color: #007bff; color: white; padding: 12px 24px;
              text-decoration: none; border-radius: 4px; display: inline-block;">
        Restablecer Contraseña
    </a>
</p>

<p>O copia y pega este enlace en tu navegador:</p>
<p style="color: #007bff; word-break: break-all;">{reset_link}</p>

<p><strong>Este enlace expirará en 1 hora.</strong></p>

<p>Si no solicitaste restablecer tu contraseña, puedes ignorar este correo de forma segura.</p>

<hr style="border: 0; border-top: 1px solid #eee; margin: 20px 0;">

<p style="font-size: 12px; color: #999;">
    Este es un mensaje automático enviado desde el sistema de Dashboard Tecnipro.<br>
    Por favor no respondas a este correo.
</p>
</body>
</html>
"""

    # Obtener token de Azure
    try:
        access_token = _obtener_token_azure()
    except Exception as e:
        logger.error("Error obteniendo token Azure: %s", e)
        return False

    # Preparar mensaje
    remitente = "ygonzalez@duocapital.cl"  # Email desde donde se envía el reset
    mensaje = {
        "message": {
            "subject": "Recuperación de Contraseña - Dashboard Tecnipro",
            "body": {
                "contentType": "HTML",
                "content": html,
            },
            "toRecipients": [
                {"emailAddress": {"address": email}}
            ],
        },
        "saveToSentItems": "false",
    }

    # Enviar correo
    url = GRAPH_SEND_MAIL_URL.format(user=remitente)
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(url, json=mensaje, headers=headers, timeout=30)

        if resp.status_code == 202:
            logger.info("Email de reset enviado a %s", email)
            return True
        else:
            logger.error(
                "Error enviando email de reset (HTTP %d): %s",
                resp.status_code,
                resp.text[:200]
            )
            return False

    except Exception as e:
        logger.error("Excepción enviando email de reset: %s", e)
        return False

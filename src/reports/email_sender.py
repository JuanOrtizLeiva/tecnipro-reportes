"""Envío de correos con reportes PDF adjuntos via Microsoft Graph API."""

import base64
import logging
import time
from pathlib import Path

import requests

from config import settings

logger = logging.getLogger(__name__)

GRAPH_TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
GRAPH_SEND_MAIL_URL = "https://graph.microsoft.com/v1.0/users/{user}/sendMail"

MAX_RETRIES = 1
RETRY_DELAY = 10       # segundos
DELAY_ENTRE_ENVIOS = 2  # segundos


def obtener_token_azure():
    """Obtiene access token de Azure AD usando client credentials.

    Returns
    -------
    str
        Access token.

    Raises
    ------
    RuntimeError
        Si no se pueden obtener las credenciales o el token.
    """
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
        body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text
        error_desc = ""
        if isinstance(body, dict):
            error_desc = body.get("error_description", body.get("error", ""))
        raise RuntimeError(
            f"Error obteniendo token Azure (HTTP {resp.status_code}): {error_desc}"
        )

    token = resp.json().get("access_token")
    if not token:
        raise RuntimeError("Respuesta de Azure no contiene access_token")

    logger.info("Token Azure obtenido correctamente")
    return token


def generar_cuerpo_correo(nombre_comprador, empresa, resumen_cursos):
    """Genera el cuerpo HTML del correo.

    Parameters
    ----------
    nombre_comprador : str
    empresa : str
    resumen_cursos : list[dict]
        Lista de dicts con 'nombre', 'total_estudiantes', 'aprobados', 'en_proceso'.

    Returns
    -------
    str
        HTML del cuerpo del correo.
    """
    total_cursos = len(resumen_cursos)
    total_participantes = sum(c.get("total_estudiantes", 0) for c in resumen_cursos)
    total_aprobados = sum(c.get("aprobados", 0) for c in resumen_cursos)
    total_en_proceso = sum(c.get("en_proceso", 0) for c in resumen_cursos)

    saludo = f"Estimado/a {nombre_comprador}" if nombre_comprador else "Estimado/a"

    html = f"""\
<html>
<body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6;">
<p>{saludo},</p>

<p>Le adjuntamos el reporte de capacitación actualizado para <strong>{empresa}</strong>.</p>

<p><strong>Resumen:</strong></p>
<ul style="list-style: none; padding-left: 0;">
  <li>&#8226; Cursos activos: <strong>{total_cursos}</strong></li>
  <li>&#8226; Total participantes: <strong>{total_participantes}</strong></li>
  <li>&#8226; Aprobados: <strong>{total_aprobados}</strong></li>
  <li>&#8226; En proceso: <strong>{total_en_proceso}</strong></li>
</ul>

<p>El reporte detallado se encuentra en el archivo PDF adjunto.</p>

<p>Saludos cordiales,<br>
<strong>Instituto de Capacitación Tecnipro</strong><br>
<a href="https://www.institutotecnipro.cl">www.institutotecnipro.cl</a></p>
</body>
</html>"""
    return html


def generar_cuerpo_alerta_validacion(errores, fecha_hora):
    """Genera el cuerpo HTML del correo de alerta por conflicto de compradores.

    Parameters
    ----------
    errores : list[dict]
        Lista de dicts con 'curso', 'id_moodle', 'emails'.
    fecha_hora : str
        Fecha y hora del intento.

    Returns
    -------
    str
        HTML del cuerpo del correo de alerta.
    """
    filas_html = ""
    for e in errores:
        emails_str = ", ".join(e["emails"])
        filas_html += (
            f'<tr>'
            f'<td style="padding:8px;border:1px solid #ddd;">{e["curso"]}</td>'
            f'<td style="padding:8px;border:1px solid #ddd;text-align:center;">{e["id_moodle"]}</td>'
            f'<td style="padding:8px;border:1px solid #ddd;">{emails_str}</td>'
            f'</tr>\n'
        )

    html = f"""\
<html>
<body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6;">
<div style="background-color: #dc3545; color: white; padding: 16px 20px; border-radius: 4px 4px 0 0;">
  <h2 style="margin: 0;">&#9888;&#65039; ERROR: Conflicto de compradores detectado</h2>
</div>

<div style="padding: 20px; background: #fff3f3; border: 1px solid #dc3545; border-top: none; border-radius: 0 0 4px 4px;">
  <p>El proceso de generaci&oacute;n de reportes se ha <strong>detenido</strong> porque se detectaron emails de comprador inconsistentes en el archivo <code>compradores_tecnipro.xlsx</code>.</p>

  <p><strong>Cursos con conflicto:</strong></p>
  <table style="border-collapse: collapse; width: 100%; margin: 12px 0;">
    <thead>
      <tr style="background-color: #dc3545; color: white;">
        <th style="padding: 8px; border: 1px solid #ddd; text-align: left;">Curso</th>
        <th style="padding: 8px; border: 1px solid #ddd; text-align: center;">ID Moodle</th>
        <th style="padding: 8px; border: 1px solid #ddd; text-align: left;">Emails encontrados</th>
      </tr>
    </thead>
    <tbody>
      {filas_html}
    </tbody>
  </table>

  <div style="background: #fff; border-left: 4px solid #dc3545; padding: 12px 16px; margin: 16px 0;">
    <strong>Acci&oacute;n requerida:</strong> Corrija el archivo <code>compradores_tecnipro.xlsx</code> para que cada curso tenga un &uacute;nico email de comprador, y vuelva a ejecutar el proceso.
  </div>

  <p style="color: #666; font-size: 13px;">Fecha y hora del intento: {fecha_hora}</p>
</div>

<p style="font-size: 12px; color: #999; margin-top: 16px;">
Instituto de Capacitaci&oacute;n Tecnipro &mdash; Reporte generado autom&aacute;ticamente
</p>
</body>
</html>"""
    return html


def _parsear_emails(campo_email):
    """Parsea un campo de email que puede tener múltiples direcciones separadas por coma.

    Returns
    -------
    list[str]
        Lista de emails limpios.
    """
    if not campo_email:
        return []
    return [e.strip() for e in campo_email.split(",") if e.strip() and "@" in e.strip()]


def enviar_correo(destinatario, asunto, cuerpo_html, adjunto_path=None,
                  cc=None, dry_run=False):
    """Envía un correo via Microsoft Graph API, opcionalmente con adjunto PDF.

    Parameters
    ----------
    destinatario : str
        Email(s) del destinatario.  Soporta múltiples separados por coma.
    asunto : str
        Asunto del correo.
    cuerpo_html : str
        Cuerpo del correo en HTML.
    adjunto_path : Path | str | None
        Ruta al archivo PDF adjunto.  Si es None, se envía sin adjunto.
    cc : str | None
        Email para CC.
    dry_run : bool
        Si True, no envía realmente el correo.

    Returns
    -------
    dict
        Resultado con 'status' ('OK' o 'ERROR') y 'detalle'.
    """
    if adjunto_path is not None:
        adjunto_path = Path(adjunto_path)

    # Parsear múltiples destinatarios
    lista_emails = _parsear_emails(destinatario)
    if not lista_emails:
        return {"status": "ERROR", "detalle": f"Email destinatario inválido: {destinatario}"}

    if dry_run:
        logger.info("[DRY-RUN] Correo NO enviado a %s (asunto: %s)", lista_emails, asunto)
        return {"status": "DRY-RUN", "detalle": "Correo no enviado (modo prueba)"}

    # Obtener token
    try:
        token = obtener_token_azure()
    except RuntimeError as e:
        return {"status": "ERROR", "detalle": str(e)}

    # Leer adjunto y codificar en base64 (si existe)
    adjunto_b64 = None
    if adjunto_path is not None:
        try:
            contenido_adjunto = adjunto_path.read_bytes()
            adjunto_b64 = base64.b64encode(contenido_adjunto).decode("utf-8")
        except Exception as e:
            return {"status": "ERROR", "detalle": f"Error leyendo adjunto: {e}"}

    # Construir el payload
    remitente = settings.EMAIL_REMITENTE
    if not remitente:
        return {"status": "ERROR", "detalle": "EMAIL_REMITENTE no configurado en .env"}

    message = {
        "subject": asunto,
        "body": {
            "contentType": "HTML",
            "content": cuerpo_html,
        },
        "toRecipients": [
            {"emailAddress": {"address": email}} for email in lista_emails
        ],
    }

    if adjunto_b64 is not None:
        message["attachments"] = [
            {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": adjunto_path.name,
                "contentType": "application/pdf",
                "contentBytes": adjunto_b64,
            }
        ]

    if cc:
        message["ccRecipients"] = [
            {"emailAddress": {"address": cc}}
        ]

    url = GRAPH_SEND_MAIL_URL.format(user=remitente)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {"message": message, "saveToSentItems": "true"}

    # Enviar con retry
    for intento in range(MAX_RETRIES + 1):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=30)

            if resp.status_code == 202:
                logger.info("Correo enviado a %s", lista_emails)
                return {"status": "OK", "detalle": f"Enviado a {lista_emails}"}

            # Error
            error_body = resp.text
            if resp.status_code == 403:
                error_body = (
                    f"HTTP 403 Forbidden. La app de Azure probablemente no "
                    f"tiene el permiso 'Mail.Send'. Agregar el permiso en "
                    f"Azure Portal > App registrations > API permissions. "
                    f"Detalle: {resp.text}"
                )

            if intento < MAX_RETRIES:
                logger.warning(
                    "Envío a %s falló (intento %d): HTTP %d — reintentando en %ds",
                    lista_emails, intento + 1, resp.status_code, RETRY_DELAY,
                )
                time.sleep(RETRY_DELAY)
            else:
                logger.error("Envío a %s falló definitivamente: HTTP %d", lista_emails, resp.status_code)
                return {"status": "ERROR", "detalle": f"HTTP {resp.status_code}: {error_body}"}

        except requests.RequestException as e:
            if intento < MAX_RETRIES:
                logger.warning("Error de red enviando a %s: %s — reintentando", lista_emails, e)
                time.sleep(RETRY_DELAY)
            else:
                return {"status": "ERROR", "detalle": f"Error de red: {e}"}

    return {"status": "ERROR", "detalle": "Agotados los reintentos"}

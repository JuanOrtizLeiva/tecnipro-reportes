"""Cliente OneDrive/SharePoint para descargar archivos Moodle en producción.

Usa Microsoft Graph API con las mismas credenciales Azure del proyecto.
Descarga Greporte.csv, Dreporte.csv y compradores_tecnipro.xlsx
desde SharePoint a las rutas locales de data/.
"""

import logging
import os
from pathlib import Path

import requests

from config import settings

logger = logging.getLogger(__name__)

GRAPH_TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
GRAPH_DRIVE_URL = "https://graph.microsoft.com/v1.0/sites/{site_id}/drive"


def _obtener_token():
    """Obtiene access token de Azure AD."""
    client_id = settings.AZURE_CLIENT_ID
    tenant_id = settings.AZURE_TENANT_ID
    client_secret = settings.AZURE_CLIENT_SECRET

    if not all([client_id, tenant_id, client_secret]):
        raise RuntimeError("Credenciales Azure incompletas para OneDrive")

    resp = requests.post(
        GRAPH_TOKEN_URL.format(tenant=tenant_id),
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        },
        timeout=30,
    )

    if resp.status_code != 200:
        raise RuntimeError(f"Error obteniendo token Azure: HTTP {resp.status_code}")

    token = resp.json().get("access_token")
    if not token:
        raise RuntimeError("Token Azure vacío")

    return token


def _download_file(token, site_id, folder_path, filename, dest_path):
    """Descarga un archivo de SharePoint/OneDrive vía Graph API.

    Parameters
    ----------
    token : str
        Access token de Azure.
    site_id : str
        ID del sitio de SharePoint.
    folder_path : str
        Ruta de la carpeta en el drive (e.g. "Carpeta/Sub/archivo.csv").
    filename : str
        Nombre del archivo a descargar.
    dest_path : Path
        Ruta local de destino.
    """
    headers = {"Authorization": f"Bearer {token}"}

    # Construir ruta completa del archivo en el drive
    file_path = f"{folder_path}/{filename}" if folder_path else filename
    # Encode especial para Graph API: reemplazar / con :/ en la URL
    encoded_path = file_path.replace(" ", "%20")

    url = (
        f"https://graph.microsoft.com/v1.0/sites/{site_id}"
        f"/drive/root:/{encoded_path}:/content"
    )

    resp = requests.get(url, headers=headers, timeout=60, allow_redirects=True)

    if resp.status_code != 200:
        raise RuntimeError(
            f"Error descargando {filename}: HTTP {resp.status_code} — {resp.text[:200]}"
        )

    # Verificar que no está vacío
    if len(resp.content) == 0:
        raise RuntimeError(f"Archivo {filename} descargado está vacío")

    # Guardar
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(resp.content)

    logger.info(
        "Descargado %s → %s (%d bytes)",
        filename, dest_path, len(resp.content),
    )


def download_moodle_csvs():
    """Descarga los CSVs de Moodle y compradores desde SharePoint.

    Descarga:
      - Greporte.csv → data/Greporte.csv
      - Dreporte.csv → data/Dreporte.csv
      - compradores_tecnipro.xlsx → data/config/compradores_tecnipro.xlsx

    Si falla alguna descarga, loggea el error y continúa con los demás.
    """
    site_id = os.getenv("ONEDRIVE_SITE_ID", "")
    moodle_folder = os.getenv(
        "ONEDRIVE_MOODLE_FOLDER",
        "Instituto de Capacitacion Tecnipro/Cursos/Cursos en Proceso/"
        "Control Cursos Abiertos/Datos Moodle para control de cursos",
    )
    compradores_folder = os.getenv(
        "ONEDRIVE_COMPRADORES_FOLDER",
        "Instituto de Capacitacion Tecnipro/Cursos/Cursos en Proceso/"
        "Control Cursos Abiertos/Reporteria",
    )

    if not site_id:
        logger.warning(
            "ONEDRIVE_SITE_ID no configurado — "
            "saltando descarga de OneDrive"
        )
        return

    try:
        token = _obtener_token()
    except RuntimeError as e:
        logger.error("No se pudo autenticar con OneDrive: %s", e)
        return

    # Lista de archivos a descargar: (carpeta, nombre, destino)
    archivos = [
        (moodle_folder, "Greporte.csv", settings.DATA_INPUT_PATH / "Greporte.csv"),
        (moodle_folder, "Dreporte.csv", settings.DATA_INPUT_PATH / "Dreporte.csv"),
        (compradores_folder, "compradores_tecnipro.xlsx", settings.COMPRADORES_PATH),
    ]

    ok = 0
    for folder, filename, dest in archivos:
        try:
            _download_file(token, site_id, folder, filename, dest)
            ok += 1
        except Exception as e:
            logger.error("Error descargando %s: %s", filename, e)

    logger.info("OneDrive: %d/%d archivos descargados", ok, len(archivos))

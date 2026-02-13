"""Lector de correos desde Microsoft 365 via Graph API.

Módulo adicional para leer correos de info@duocapital.cl.
NO reemplaza el sistema actual de Gmail IMAP.
"""
import base64
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from config import settings

logger = logging.getLogger(__name__)

# Configuración
TARGET_MAILBOX = "info@duocapital.cl"
EXPECTED_SUBJECTS = [
    "Control de cursos Asincrónicos y Sincrónicos",
    "Reporte Asincronico",
    "Reporte Asincrónico",
]
EXPECTED_SENDER = "noreply@virtual.institutotecnipro.cl"
SEARCH_WINDOW_HOURS = 48

# URLs de Graph API
GRAPH_TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
GRAPH_MESSAGES_URL = "https://graph.microsoft.com/v1.0/users/{mailbox}/messages"
GRAPH_ATTACHMENTS_URL = "https://graph.microsoft.com/v1.0/users/{mailbox}/messages/{message_id}/attachments"


class GraphMailReader:
    """Lee correos de Microsoft 365 via Graph API."""

    def __init__(self):
        """Inicializa el lector usando credenciales de settings."""
        self.tenant_id = settings.AZURE_TENANT_ID
        self.client_id = settings.AZURE_CLIENT_ID
        self.client_secret = settings.AZURE_CLIENT_SECRET
        self.token = None

        if not all([self.tenant_id, self.client_id, self.client_secret]):
            raise RuntimeError(
                "Faltan credenciales de Azure. Verificar AZURE_CLIENT_ID, "
                "AZURE_TENANT_ID, AZURE_CLIENT_SECRET en .env"
            )

    def authenticate(self):
        """Obtiene access token via client_credentials."""
        url = GRAPH_TOKEN_URL.format(tenant=self.tenant_id)
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        }

        try:
            resp = requests.post(url, data=data, timeout=30)
            if resp.status_code != 200:
                error_body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text
                error_desc = ""
                if isinstance(error_body, dict):
                    error_desc = error_body.get("error_description", error_body.get("error", ""))
                raise RuntimeError(
                    f"Error obteniendo token Azure (HTTP {resp.status_code}): {error_desc}"
                )

            self.token = resp.json().get("access_token")
            if not self.token:
                raise RuntimeError("Respuesta de Azure no contiene access_token")

            logger.info("✅ Autenticación Graph API exitosa")
            return True

        except Exception as e:
            logger.error(f"❌ Error en autenticación: {e}")
            return False

    def _headers(self):
        """Retorna headers para requests a Graph API."""
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def get_moodle_emails(self):
        """Busca correos de Moodle en el buzón.

        Filtra por:
        - Asunto que contenga alguno de los EXPECTED_SUBJECTS
        - Que tenga adjuntos
        - Recibido en las últimas SEARCH_WINDOW_HOURS horas
        - Del remitente esperado

        Returns
        -------
        list[dict]
            Lista de mensajes con estructura de Graph API.
        """
        if not self.token:
            logger.error("No autenticado. Ejecutar authenticate() primero.")
            return []

        # Calcular ventana de búsqueda
        since = (datetime.now(timezone.utc) - timedelta(hours=SEARCH_WINDOW_HOURS)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

        # Construir filtro OData
        subject_filters = " or ".join(
            [f"contains(subject, '{s}')" for s in EXPECTED_SUBJECTS]
        )
        odata_filter = (
            f"receivedDateTime ge {since} "
            f"and hasAttachments eq true "
            f"and ({subject_filters})"
        )

        url = (
            GRAPH_MESSAGES_URL.format(mailbox=TARGET_MAILBOX)
            + f"?$filter={odata_filter}"
            + "&$select=id,subject,from,receivedDateTime,hasAttachments,isRead"
            + "&$orderby=receivedDateTime desc"
            + "&$top=50"
        )

        try:
            resp = requests.get(url, headers=self._headers(), timeout=30)
            if resp.status_code != 200:
                logger.error(f"❌ Error buscando correos: {resp.status_code} - {resp.text}")
                return []

            messages = resp.json().get("value", [])
            logger.info(f"📧 {len(messages)} correos encontrados con filtros iniciales")

            # Filtro adicional por remitente
            if EXPECTED_SENDER:
                filtered = []
                for msg in messages:
                    sender_email = msg.get("from", {}).get("emailAddress", {}).get("address", "").lower()
                    if EXPECTED_SENDER.lower() in sender_email:
                        filtered.append(msg)
                    else:
                        logger.debug(f"Descartado por remitente: {sender_email} - {msg['subject']}")
                messages = filtered
                logger.info(f"📧 {len(messages)} correos después de filtro por remitente")

            return messages

        except Exception as e:
            logger.error(f"❌ Excepción buscando correos: {e}")
            return []

    def download_csv_attachments(self, message_id, subject):
        """Descarga adjuntos CSV de un mensaje.

        Parameters
        ----------
        message_id : str
            ID del mensaje en Graph API.
        subject : str
            Asunto del mensaje (para logging).

        Returns
        -------
        list[Path]
            Lista de rutas de archivos descargados.
        """
        url = GRAPH_ATTACHMENTS_URL.format(mailbox=TARGET_MAILBOX, message_id=message_id)

        try:
            resp = requests.get(url, headers=self._headers(), timeout=30)
            if resp.status_code != 200:
                logger.error(f"❌ Error obteniendo adjuntos: {resp.status_code}")
                return []

            attachments = resp.json().get("value", [])
            downloaded = []

            for att in attachments:
                filename = att.get("name", "")
                content_type = att.get("contentType", "")

                # Solo descargar CSVs
                if not (filename.lower().endswith(".csv") or "csv" in content_type.lower()):
                    logger.debug(f"Saltando adjunto no-CSV: {filename}")
                    continue

                # Decodificar contenido (viene en base64)
                content_bytes = base64.b64decode(att.get("contentBytes", ""))

                # Determinar destino según nombre de archivo
                output_path = self._determine_output_path(filename)

                # Guardar archivo
                output_path.write_bytes(content_bytes)
                logger.info(f"📥 CSV descargado: {output_path.name} ({len(content_bytes)} bytes)")
                downloaded.append(output_path)

            return downloaded

        except Exception as e:
            logger.error(f"❌ Excepción descargando adjuntos: {e}")
            return []

    def _determine_output_path(self, filename):
        """Determina la ruta de salida según el nombre del archivo.

        Greporte.csv → data/Greporte.csv
        Dreporte.csv → data/Dreporte.csv
        Otros → data/output/<timestamp>_<filename>

        Parameters
        ----------
        filename : str
            Nombre original del archivo adjunto.

        Returns
        -------
        Path
            Ruta donde guardar el archivo.
        """
        data_dir = Path(settings.DATA_INPUT_PATH)
        data_dir.mkdir(parents=True, exist_ok=True)

        filename_lower = filename.lower()

        if "greporte" in filename_lower:
            return data_dir / "Greporte.csv"
        elif "dreporte" in filename_lower:
            return data_dir / "Dreporte.csv"
        else:
            # Archivo desconocido → guardar con timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_dir = Path(settings.OUTPUT_PATH)
            output_dir.mkdir(parents=True, exist_ok=True)
            return output_dir / f"{timestamp}_{filename}"

    def mark_as_read(self, message_id):
        """Marca un mensaje como leído.

        Parameters
        ----------
        message_id : str
            ID del mensaje.
        """
        url = GRAPH_MESSAGES_URL.format(mailbox=TARGET_MAILBOX) + f"/{message_id}"
        data = {"isRead": True}

        try:
            resp = requests.patch(url, headers=self._headers(), json=data, timeout=15)
            if resp.status_code in (200, 204):
                logger.debug(f"Mensaje {message_id[:8]}... marcado como leído")
            else:
                logger.warning(f"No se pudo marcar como leído: {resp.status_code}")
        except Exception as e:
            logger.warning(f"Excepción marcando como leído: {e}")


def descargar_adjuntos_moodle_graph():
    """Función principal para descargar adjuntos de Moodle via Graph API.

    Diseñada para ser drop-in replacement de email_reader.descargar_adjuntos_moodle().

    Returns
    -------
    dict
        {
            'status': 'OK' | 'PARCIAL' | 'ERROR',
            'archivos_descargados': [Path, ...],
            'detalle': str,
        }
    """
    logger.info("=" * 60)
    logger.info("🚀 Descarga de adjuntos Moodle via Graph API")
    logger.info(f"   Buzón: {TARGET_MAILBOX}")
    logger.info(f"   Ventana: últimas {SEARCH_WINDOW_HOURS} horas")
    logger.info("=" * 60)

    try:
        # Inicializar lector
        reader = GraphMailReader()

        # Autenticar
        if not reader.authenticate():
            return {
                "status": "ERROR",
                "archivos_descargados": [],
                "detalle": "Error de autenticación con Graph API",
            }

        # Buscar correos
        messages = reader.get_moodle_emails()

        if not messages:
            logger.info("📭 No hay correos nuevos de Moodle")
            return {
                "status": "OK",
                "archivos_descargados": [],
                "detalle": "Sin correos nuevos",
            }

        # Procesar cada correo
        all_files = []
        for msg in messages:
            msg_id = msg["id"]
            subject = msg["subject"]
            received = msg["receivedDateTime"]
            sender = msg.get("from", {}).get("emailAddress", {}).get("address", "desconocido")
            is_read = msg.get("isRead", False)

            logger.info(f"\n📧 Procesando: {subject}")
            logger.info(f"   De: {sender}")
            logger.info(f"   Recibido: {received}")
            logger.info(f"   Leído: {'Sí' if is_read else 'No'}")

            # Descargar CSVs
            csv_files = reader.download_csv_attachments(msg_id, subject)

            if csv_files:
                all_files.extend(csv_files)
                # Marcar como leído
                reader.mark_as_read(msg_id)
                logger.info(f"   ✅ {len(csv_files)} CSV(s) descargados")
            else:
                logger.warning(f"   ⚠️ Correo sin adjuntos CSV")

        # Verificar que tengamos Greporte y Dreporte
        archivos_descargados_str = [str(f.name) for f in all_files]
        tiene_greporte = any("greporte" in n.lower() for n in archivos_descargados_str)
        tiene_dreporte = any("dreporte" in n.lower() for n in archivos_descargados_str)

        if tiene_greporte and tiene_dreporte:
            status = "OK"
            detalle = f"Descargados: {', '.join(archivos_descargados_str)}"
        elif all_files:
            status = "PARCIAL"
            faltantes = []
            if not tiene_greporte:
                faltantes.append("Greporte.csv")
            if not tiene_dreporte:
                faltantes.append("Dreporte.csv")
            detalle = f"Descargados: {', '.join(archivos_descargados_str)}. Faltan: {', '.join(faltantes)}"
        else:
            status = "ERROR"
            detalle = "No se descargó ningún archivo"

        logger.info(f"\n{'=' * 60}")
        logger.info(f"✅ FINALIZADO: {len(all_files)} CSV(s) descargados de {len(messages)} correo(s)")
        logger.info(f"   Status: {status}")
        logger.info(f"   Archivos: {archivos_descargados_str}")
        logger.info(f"{'=' * 60}")

        return {
            "status": status,
            "archivos_descargados": all_files,
            "detalle": detalle,
        }

    except Exception as e:
        logger.error(f"❌ Error procesando correos: {e}", exc_info=True)
        return {
            "status": "ERROR",
            "archivos_descargados": [],
            "detalle": str(e),
        }

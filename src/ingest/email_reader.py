"""Descarga archivos Moodle desde correo vía IMAP.

Lee emails de Moodle con adjuntos Greporte.csv y Dreporte.csv,
los descarga a DATA_INPUT_PATH y marca los emails como leídos.
"""

import email
import imaplib
import logging
from email.header import decode_header
from pathlib import Path

from config import settings

logger = logging.getLogger(__name__)


def descargar_adjuntos_moodle():
    """Descarga Greporte.csv y Dreporte.csv desde emails de Moodle vía IMAP.

    Proceso:
    1. Conecta a Gmail vía IMAP
    2. Busca emails no leídos de Moodle
    3. Descarga adjuntos .csv (Greporte.csv, Dreporte.csv)
    4. Guarda en DATA_INPUT_PATH
    5. Marca emails como leídos

    Returns
    -------
    dict
        Resultado con status y archivos descargados.

    Raises
    ------
    RuntimeError
        Si falla la conexión o no hay credenciales.
    """
    user = settings.EMAIL_MOODLE_USER
    password = settings.EMAIL_MOODLE_PASSWORD
    imap_server = settings.IMAP_SERVER

    if not user or not password:
        raise RuntimeError(
            "Credenciales de email no configuradas. "
            "Configure EMAIL_MOODLE_USER y EMAIL_MOODLE_PASSWORD en .env"
        )

    logger.info("=" * 60)
    logger.info("EMAIL: Conectando a %s (%s)", imap_server, user)
    logger.info("=" * 60)

    resultado = {
        "status": "OK",
        "archivos_descargados": [],
        "emails_procesados": 0,
        "errores": [],
    }

    try:
        # Conectar a IMAP
        mail = imaplib.IMAP4_SSL(imap_server)
        mail.login(user, password)
        logger.info("Conexión IMAP exitosa")

        # Seleccionar carpeta INBOX
        mail.select("inbox")

        # Buscar emails no leídos de Moodle
        # Criterio: UNSEEN (no leídos) y FROM contiene "@" (ajustar según remitente real)
        status, messages = mail.search(None, "UNSEEN")

        if status != "OK":
            raise RuntimeError("Error buscando emails no leídos")

        email_ids = messages[0].split()
        logger.info("Emails no leídos encontrados: %d", len(email_ids))

        if not email_ids:
            logger.info("No hay emails nuevos de Moodle")
            mail.logout()
            return resultado

        # Procesar cada email
        archivos_encontrados = {"Greporte.csv": False, "Dreporte.csv": False}

        for email_id in email_ids:
            # Obtener email
            status, msg_data = mail.fetch(email_id, "(RFC822)")
            if status != "OK":
                logger.warning("Error obteniendo email ID %s", email_id)
                continue

            # Parsear email
            msg = email.message_from_bytes(msg_data[0][1])

            # Obtener asunto (decodificar si está en formato MIME)
            subject_header = msg.get("Subject", "")
            subject = _decodificar_header(subject_header)

            # Obtener remitente
            from_header = msg.get("From", "")
            from_addr = _decodificar_header(from_header)

            logger.info("Procesando email: '%s' de %s", subject, from_addr)

            # Verificar si es de Moodle (ajustar según remitente real)
            # Moodle típicamente envía desde noreply@... o el dominio del sitio
            # Por ahora procesamos todos los no leídos con adjuntos .csv

            # Procesar adjuntos
            if msg.is_multipart():
                for part in msg.walk():
                    if _es_adjunto_moodle(part):
                        filename = _obtener_nombre_adjunto(part)
                        if filename and filename.lower().endswith(".csv"):
                            # Descargar adjunto
                            try:
                                _guardar_adjunto(part, filename, archivos_encontrados)
                                resultado["archivos_descargados"].append(filename)
                            except Exception as e:
                                logger.error("Error guardando %s: %s", filename, e)
                                resultado["errores"].append(str(e))

            # Marcar como leído
            mail.store(email_id, "+FLAGS", "\\Seen")
            resultado["emails_procesados"] += 1

        # Cerrar conexión
        mail.logout()

        # Verificar que se descargaron ambos archivos
        if not all(archivos_encontrados.values()):
            faltantes = [k for k, v in archivos_encontrados.items() if not v]
            logger.warning("No se encontraron archivos: %s", faltantes)
            resultado["status"] = "PARCIAL"
            resultado["archivos_faltantes"] = faltantes

        logger.info("=" * 60)
        logger.info("EMAIL: Descarga completada")
        logger.info("  Emails procesados: %d", resultado["emails_procesados"])
        logger.info("  Archivos descargados: %d", len(resultado["archivos_descargados"]))
        logger.info("=" * 60)

        return resultado

    except imaplib.IMAP4.error as e:
        logger.error("Error IMAP: %s", e)
        raise RuntimeError(f"Error de conexión IMAP: {e}")
    except Exception as e:
        logger.error("Error descargando emails: %s", e)
        raise RuntimeError(f"Error procesando emails: {e}")


def _decodificar_header(header_value):
    """Decodifica un header de email que puede estar en formato MIME.

    Parameters
    ----------
    header_value : str
        Valor del header a decodificar.

    Returns
    -------
    str
        Header decodificado.
    """
    if not header_value:
        return ""

    decoded_parts = decode_header(header_value)
    decoded_str = ""

    for content, encoding in decoded_parts:
        if isinstance(content, bytes):
            decoded_str += content.decode(encoding or "utf-8", errors="ignore")
        else:
            decoded_str += content

    return decoded_str


def _es_adjunto_moodle(part):
    """Verifica si una parte del email es un adjunto válido.

    Parameters
    ----------
    part : email.message.Message
        Parte del mensaje a verificar.

    Returns
    -------
    bool
        True si es un adjunto (no inline, tiene filename).
    """
    content_disposition = part.get("Content-Disposition", "")
    if not content_disposition:
        return False

    # Es adjunto si tiene disposition "attachment" o tiene filename
    return (
        "attachment" in content_disposition.lower()
        or part.get_filename() is not None
    )


def _obtener_nombre_adjunto(part):
    """Obtiene el nombre del archivo adjunto.

    Parameters
    ----------
    part : email.message.Message
        Parte del mensaje con adjunto.

    Returns
    -------
    str | None
        Nombre del archivo o None si no se puede determinar.
    """
    filename = part.get_filename()
    if not filename:
        return None

    # Decodificar filename si está en formato MIME
    return _decodificar_header(filename)


def _guardar_adjunto(part, filename, archivos_encontrados):
    """Guarda un adjunto en DATA_INPUT_PATH.

    Solo guarda si es Greporte.csv o Dreporte.csv.

    Parameters
    ----------
    part : email.message.Message
        Parte del mensaje con adjunto.
    filename : str
        Nombre del archivo.
    archivos_encontrados : dict
        Dict para trackear qué archivos se encontraron.
    """
    # Solo procesar Greporte.csv y Dreporte.csv
    nombre_base = filename.lower()
    if nombre_base not in ("greporte.csv", "dreporte.csv"):
        logger.debug("Adjunto ignorado (no es G/Dreporte): %s", filename)
        return

    # Obtener contenido
    payload = part.get_payload(decode=True)
    if not payload:
        logger.warning("Adjunto %s no tiene contenido", filename)
        return

    # Guardar en DATA_INPUT_PATH
    output_path = settings.DATA_INPUT_PATH / filename
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "wb") as f:
        f.write(payload)

    logger.info("Adjunto guardado: %s (%d bytes)", output_path, len(payload))

    # Marcar como encontrado
    if nombre_base == "greporte.csv":
        archivos_encontrados["Greporte.csv"] = True
    elif nombre_base == "dreporte.csv":
        archivos_encontrados["Dreporte.csv"] = True

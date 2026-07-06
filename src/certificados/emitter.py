"""Procesamiento de un lote de certificados: PDFs, correos y ZIPs.

Diseñado para correr en un proceso desacoplado del servidor web y ser
reanudable: cada certificado avanza pendiente → generado → enviado y los
ya enviados se saltan, por lo que relanzar un lote interrumpido (caída de
internet, reinicio del servidor) no duplica correos a alumnos. El ZIP por
curso solo se reenvía a los coordinadores si en la corrida hubo
certificados nuevos enviados o si nunca se había enviado.

Correos (remitente = coordinadora, save_to_sent=True → copia en Enviados):
  - Alumno: su certificado PDF adjunto.
  - Coordinadores del curso (usuarios.json rol=comprador activo): ZIP con
    todos los certificados del curso + listado. CC a CERT_COPIA.
  - Si el curso no tiene coordinadores, el ZIP va directo a CERT_COPIA.
"""

import html
import json
import logging
import os
import zipfile
from datetime import datetime
from pathlib import Path

from config import settings
from src.certificados import generator, registry
from src.reports.email_sender import enviar_correo
from src.reports.pdf_generator import _cargar_coordinadores_por_curso

logger = logging.getLogger(__name__)

AZUL = "#1F4E79"
DORADO = "#B49A5B"


# ── Lock por lote ──────────────────────────────────────────


def _lock_path(lote_id):
    d = settings.CERTIFICADOS_PATH / "locks"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{lote_id}.lock"


def _pid_vivo(pid):
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def adquirir_lock(lote_id):
    """Lock exclusivo por lote. Detecta y limpia locks huérfanos por PID."""
    path = _lock_path(lote_id)
    for _ in range(2):
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return True
        except FileExistsError:
            try:
                pid = int(path.read_text().strip() or "0")
            except (OSError, ValueError):
                pid = 0
            if pid and _pid_vivo(pid):
                logger.warning("Lote %s ya está siendo procesado por PID %d", lote_id, pid)
                return False
            logger.info("Lock huérfano de lote %s (PID %s muerto) — se limpia", lote_id, pid)
            path.unlink(missing_ok=True)
    return False


def liberar_lock(lote_id):
    _lock_path(lote_id).unlink(missing_ok=True)


def lote_en_proceso(lote_id):
    path = _lock_path(lote_id)
    if not path.exists():
        return False
    try:
        pid = int(path.read_text().strip() or "0")
    except (OSError, ValueError):
        return False
    return bool(pid and _pid_vivo(pid))


# ── Cuerpos de correo ──────────────────────────────────────


def _cuerpo_alumno(cert):
    url = generator.url_validacion(cert["codigo"])
    return f"""<html><body style="font-family: 'Segoe UI', Arial, sans-serif; color: #333; max-width: 620px;">
<div style="border-bottom: 3px solid {DORADO}; padding-bottom: 12px; margin-bottom: 20px;">
  <h2 style="color: {AZUL}; margin: 0;">Instituto de Capacitaci&oacute;n TECNIPRO</h2>
</div>
<p>Estimado/a <strong>{html.escape(cert['alumno_nombre'])}</strong>:</p>
<p>Nos complace hacerte entrega de tu <strong>Certificado de Participaci&oacute;n</strong> del curso
<strong>&laquo;{html.escape(cert['curso_nombre'])}&raquo;</strong>, que encontrar&aacute;s adjunto a este correo.</p>
<table style="border-collapse: collapse; margin: 16px 0; font-size: 14px;">
  <tr><td style="padding: 4px 12px 4px 0; color: #666;">Folio</td>
      <td style="padding: 4px 0;"><strong>{cert['folio']}</strong></td></tr>
  <tr><td style="padding: 4px 12px 4px 0; color: #666;">C&oacute;digo de verificaci&oacute;n</td>
      <td style="padding: 4px 0;"><strong>{cert['codigo']}</strong></td></tr>
</table>
<p>Puedes verificar la autenticidad de tu certificado en cualquier momento escaneando el
c&oacute;digo QR del documento o ingresando a
<a href="{url}" style="color: {AZUL};">www.tecnipro.cl/validar</a>.</p>
<p>&iexcl;Felicitaciones por completar tu capacitaci&oacute;n!</p>
<p style="margin-top: 24px;">Saludos cordiales,<br>
<strong>Yessenia Gonz&aacute;lez L.</strong><br>
Coordinadora Acad&eacute;mica<br>
Instituto de Capacitaci&oacute;n TECNIPRO<br>
<a href="https://www.tecnipro.cl" style="color: {AZUL};">www.tecnipro.cl</a></p>
<p style="font-size: 11px; color: #999; margin-top: 16px;">
Este certificado cuenta con un c&oacute;digo QR de validaci&oacute;n p&uacute;blica.</p>
</body></html>"""


def _cuerpo_coordinador(curso_nombre, certs):
    filas = "".join(
        f"<tr>"
        f"<td style='padding:6px 10px;border-bottom:1px solid #eee;'>{c['folio']}</td>"
        f"<td style='padding:6px 10px;border-bottom:1px solid #eee;'>{html.escape(c['alumno_nombre'])}</td>"
        f"<td style='padding:6px 10px;border-bottom:1px solid #eee;'>{generator.rut_formateado(c['alumno_rut'])}</td>"
        f"</tr>"
        for c in certs
    )
    return f"""<html><body style="font-family: 'Segoe UI', Arial, sans-serif; color: #333; max-width: 680px;">
<div style="border-bottom: 3px solid {DORADO}; padding-bottom: 12px; margin-bottom: 20px;">
  <h2 style="color: {AZUL}; margin: 0;">Instituto de Capacitaci&oacute;n TECNIPRO</h2>
</div>
<p>Estimado/a coordinador/a:</p>
<p>Junto con saludar, adjuntamos en archivo ZIP los <strong>certificados de participaci&oacute;n</strong>
emitidos para el curso <strong>&laquo;{html.escape(curso_nombre)}&raquo;</strong>
({len(certs)} certificado{'s' if len(certs) != 1 else ''}).</p>
<p>Cada participante recibi&oacute; adem&aacute;s su certificado individual por correo.
Todos los certificados incluyen c&oacute;digo QR de validaci&oacute;n p&uacute;blica en
<a href="https://www.tecnipro.cl/validar/" style="color: {AZUL};">www.tecnipro.cl/validar</a>.</p>
<table style="border-collapse: collapse; margin: 16px 0; font-size: 13px; width: 100%;">
  <tr style="background: {AZUL}; color: white;">
    <th style="padding: 8px 10px; text-align: left;">Folio</th>
    <th style="padding: 8px 10px; text-align: left;">Participante</th>
    <th style="padding: 8px 10px; text-align: left;">RUT</th>
  </tr>
  {filas}
</table>
<p style="margin-top: 24px;">Saludos cordiales,<br>
<strong>Yessenia Gonz&aacute;lez L.</strong><br>
Coordinadora Acad&eacute;mica<br>
Instituto de Capacitaci&oacute;n TECNIPRO<br>
<a href="https://www.tecnipro.cl" style="color: {AZUL};">www.tecnipro.cl</a></p>
</body></html>"""


# ── ZIP por curso ──────────────────────────────────────────


def _generar_zip(curso_id, curso_nombre, certs, lote_id):
    settings.CERT_ZIPS_PATH.mkdir(parents=True, exist_ok=True)
    fecha = datetime.now().strftime("%Y%m%d")
    nombre = f"Certificados_{generator.sanitizar_nombre(curso_nombre)}_ID{curso_id}_{fecha}.zip"
    destino = settings.CERT_ZIPS_PATH / nombre
    with zipfile.ZipFile(str(destino), "w", zipfile.ZIP_DEFLATED) as zf:
        for c in certs:
            archivo = Path(c["archivo"])
            if archivo.exists():
                zf.write(str(archivo), arcname=archivo.name)
    return destino


# ── Procesamiento principal ────────────────────────────────


def procesar_lote(lote_id, dry_run=False):
    """Procesa un lote completo. Retorna dict con resumen."""
    lote = registry.obtener_lote(lote_id)
    if lote is None:
        raise ValueError(f"Lote no existe: {lote_id}")

    if not adquirir_lock(lote_id):
        raise RuntimeError(f"El lote {lote_id} ya está siendo procesado")

    try:
        return _procesar(lote_id, lote, dry_run)
    finally:
        liberar_lock(lote_id)


def _procesar(lote_id, lote, dry_run):
    registry.actualizar_lote(lote_id, estado="procesando")
    detalle = {}
    try:
        detalle = json.loads(lote.get("detalle") or "{}")
    except (ValueError, TypeError):
        detalle = {}
    zips_enviados = detalle.get("zips_enviados", {})

    certs = [c for c in registry.certificados_de_lote(lote_id) if not c["anulado"]]
    total = len(certs)
    cursos_con_novedades = set()
    procesados = errores = 0

    for i, cert in enumerate(certs, 1):
        if cert["estado"] == "enviado":
            procesados += 1
            continue
        try:
            # 1. PDF (idempotente: reutiliza si ya existe en disco)
            archivo = Path(cert["archivo"]) if cert["archivo"] else None
            if archivo is None or not archivo.exists():
                archivo = generator.generar_certificado(cert)
                registry.marcar_generado(cert["folio_num"], archivo)
                cert["archivo"] = str(archivo)

            # 2. Correo al alumno
            email = (cert["alumno_email"] or "").strip()
            if not email or "@" not in email:
                raise RuntimeError("El alumno no tiene email válido en Moodle")
            resultado = enviar_correo(
                destinatario=email,
                asunto=f"Certificado de Participación — {cert['curso_nombre']}",
                cuerpo_html=_cuerpo_alumno(cert),
                adjunto_path=archivo,
                remitente=settings.CERT_REMITENTE,
                save_to_sent=True,
                dry_run=dry_run,
            )
            if resultado["status"] not in ("OK", "DRY-RUN"):
                raise RuntimeError(f"Envío al alumno falló: {resultado['detalle']}")

            registry.marcar_enviado(cert["folio_num"])
            cursos_con_novedades.add(cert["curso_id"])
            procesados += 1
            logger.info("[%d/%d] %s — %s enviado a %s",
                        i, total, cert["folio"], cert["alumno_nombre"], email)
        except Exception as e:
            errores += 1
            registry.marcar_error(cert["folio_num"], str(e))
            logger.error("[%d/%d] %s — ERROR: %s", i, total, cert["folio"], e)

        registry.actualizar_lote(lote_id, procesados=procesados, errores=errores)

    # ── ZIPs por curso a coordinadores ─────────────────────
    certs = [c for c in registry.certificados_de_lote(lote_id) if not c["anulado"]]
    por_curso = {}
    for c in certs:
        por_curso.setdefault(c["curso_id"], []).append(c)

    coordinadores = _cargar_coordinadores_por_curso()

    for curso_id, lista in por_curso.items():
        listos = [c for c in lista if c["estado"] == "enviado"
                  or (c["estado"] == "generado" and c["archivo"])]
        con_pdf = [c for c in listos if c["archivo"] and Path(c["archivo"]).exists()]
        if not con_pdf:
            logger.warning("Curso %s sin certificados generados — sin ZIP", curso_id)
            continue
        if curso_id in zips_enviados and curso_id not in cursos_con_novedades:
            logger.info("Curso %s: ZIP ya enviado y sin novedades — se omite", curso_id)
            continue

        curso_nombre = con_pdf[0]["curso_nombre"]
        try:
            zip_path = _generar_zip(curso_id, curso_nombre, con_pdf, lote_id)
            coords = coordinadores.get(str(curso_id), [])
            emails_coord = [e for (e, _n, _emp) in coords]
            if emails_coord:
                destinatario = ", ".join(emails_coord)
                cc = settings.CERT_COPIA if settings.CERT_COPIA not in emails_coord else None
            else:
                destinatario = settings.CERT_COPIA
                cc = None
                logger.warning("Curso %s sin coordinadores activos — ZIP solo a %s",
                               curso_id, destinatario)

            resultado = enviar_correo(
                destinatario=destinatario,
                asunto=f"Certificados de Participación — {curso_nombre} "
                       f"({len(con_pdf)} participante{'s' if len(con_pdf) != 1 else ''})",
                cuerpo_html=_cuerpo_coordinador(curso_nombre, con_pdf),
                adjunto_path=zip_path,
                cc=cc,
                remitente=settings.CERT_REMITENTE,
                save_to_sent=True,
                dry_run=dry_run,
            )
            if resultado["status"] not in ("OK", "DRY-RUN"):
                raise RuntimeError(resultado["detalle"])
            zips_enviados[curso_id] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            logger.info("ZIP del curso %s enviado a %s (CC %s)", curso_id, destinatario, cc)
        except Exception as e:
            errores += 1
            logger.error("ZIP curso %s — ERROR: %s", curso_id, e)

    detalle["zips_enviados"] = zips_enviados
    estado_final = "completado" if errores == 0 else "completado_con_errores"
    registry.actualizar_lote(
        lote_id, estado=estado_final, procesados=procesados,
        errores=errores, detalle=detalle,
    )
    resumen = {"lote_id": lote_id, "estado": estado_final,
               "procesados": procesados, "errores": errores, "total": total}
    logger.info("Lote %s finalizado: %s", lote_id, resumen)
    return resumen

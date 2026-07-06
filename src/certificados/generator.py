"""Generación del PDF de un certificado de participación.

Flujo: plantilla DOCX preparada (docxtpl) → render con datos + QR →
conversión a PDF con LibreOffice headless. El nombre del archivo final es
"{Nombre}_{RUT sin DV}_ID{curso_moodle}.pdf" (ej: Juan_Ortiz_13058127_ID256.pdf).
"""

import logging
import re
import shutil
import subprocess
import tempfile
import unicodedata
from datetime import date, datetime
from pathlib import Path

import qrcode
from docx.shared import Mm
from docxtpl import DocxTemplate, InlineImage

from config import settings

logger = logging.getLogger(__name__)

MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]

# Perfil de usuario dedicado para LibreOffice (evita choques con otros usos).
_LO_PROFILE = "file:///tmp/lo_profile_certificados"
_LO_TIMEOUT = 180


# ── Helpers de formato ─────────────────────────────────────


def _sin_acentos(texto):
    return "".join(
        c for c in unicodedata.normalize("NFKD", texto or "")
        if not unicodedata.combining(c)
    )


def sanitizar_nombre(nombre):
    """"María José Núñez" → "Maria_Jose_Nunez" (seguro para nombre de archivo)."""
    limpio = _sin_acentos(nombre).replace("ñ", "n").replace("Ñ", "N")
    limpio = re.sub(r"[^A-Za-z0-9]+", "_", limpio).strip("_")
    return limpio or "Participante"


def rut_sin_dv(rut):
    """"20.680.206-5" → "20680206" (sin puntos y sin dígito verificador)."""
    limpio = str(rut or "").replace(".", "").replace(" ", "").strip()
    if "-" in limpio:
        limpio = limpio.split("-")[0]
    elif len(limpio) > 1:
        # Sin guion: asumir que el último carácter es el DV
        limpio = limpio[:-1]
    return re.sub(r"\D", "", limpio)


def rut_formateado(rut):
    """"20680206-5" → "20.680.206-5" (para mostrar en el certificado)."""
    limpio = str(rut or "").replace(".", "").replace(" ", "").strip().upper()
    if "-" in limpio:
        cuerpo, dv = limpio.rsplit("-", 1)
    elif len(limpio) > 1:
        cuerpo, dv = limpio[:-1], limpio[-1]
    else:
        return limpio
    if not cuerpo.isdigit():
        return limpio
    con_puntos = f"{int(cuerpo):,}".replace(",", ".")
    return f"{con_puntos}-{dv}"


def fecha_larga(fecha_iso):
    """"2026-06-24" → "24 de junio de 2026"."""
    if isinstance(fecha_iso, (date, datetime)):
        d = fecha_iso
    else:
        d = datetime.strptime(str(fecha_iso)[:10], "%Y-%m-%d")
    return f"{d.day} de {MESES[d.month - 1]} de {d.year}"


def _num_chileno(valor, decimales=1):
    """7.0 → "7,0"; 87.5 → "87,5"; 88.0 con drop → "88"."""
    txt = f"{float(valor):.{decimales}f}".replace(".", ",")
    return txt


def _horas_texto(horas):
    h = float(horas)
    return str(int(h)) if h == int(h) else _num_chileno(h)


def nombre_archivo(alumno_nombre, alumno_rut, curso_id):
    return f"{sanitizar_nombre(alumno_nombre)}_{rut_sin_dv(alumno_rut)}_ID{curso_id}.pdf"


# ── QR ─────────────────────────────────────────────────────


def url_validacion(codigo):
    base = settings.CERT_URL_VALIDACION
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}c={codigo}"


def _generar_qr(codigo, destino):
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    qr.add_data(url_validacion(codigo))
    qr.make(fit=True)
    img = qr.make_image(fill_color="#1F3B63", back_color="white")
    img.save(str(destino))
    return destino


# ── Render + conversión ────────────────────────────────────


def _contexto(cert, tpl, qr_path):
    """Construye el contexto docxtpl desde una fila del registro."""
    sincronico = (cert.get("modalidad") == "sincronico")
    calificacion = cert.get("calificacion")
    asistencia = cert.get("asistencia_pct")

    if sincronico and asistencia is not None:
        sep_asist = ", con un porcentaje de asistencia del "
        asistencia_txt = f"{_num_chileno(asistencia)}%".replace(",0%", "%")
    else:
        sep_asist, asistencia_txt = "", ""

    if calificacion is not None:
        sep_cal = " y una calificación final de "
        calificacion_txt = _num_chileno(calificacion)
    else:
        sep_cal, calificacion_txt = "", ""

    return {
        "NOMBRE": cert["alumno_nombre"],
        "RUT": rut_formateado(cert["alumno_rut"]),
        "CURSO": cert["curso_nombre"],
        "FECHA_INICIO": fecha_larga(cert["fecha_inicio"]),
        "FECHA_TERMINO": fecha_larga(cert["fecha_termino"]),
        "HORAS": _horas_texto(cert["horas"]),
        "SEP_ASIST": sep_asist,
        "ASISTENCIA_TXT": asistencia_txt,
        "SEP_CAL": sep_cal,
        "CALIFICACION_TXT": calificacion_txt,
        "FOLIO": cert["folio"],
        "FECHA_EMISION": fecha_larga(datetime.now()),
        "URL_VALIDACION": f"www.tecnipro.cl/validar — código {cert['codigo']}",
        "QR": InlineImage(tpl, str(qr_path), width=Mm(22)),
    }


def _convertir_a_pdf(docx_path, outdir):
    cmd = [
        "soffice", "--headless",
        f"-env:UserInstallation={_LO_PROFILE}",
        "--convert-to", "pdf",
        "--outdir", str(outdir),
        str(docx_path),
    ]
    resultado = subprocess.run(
        cmd, capture_output=True, text=True, timeout=_LO_TIMEOUT,
    )
    pdf = Path(outdir) / (Path(docx_path).stem + ".pdf")
    if not pdf.exists():
        raise RuntimeError(
            f"LibreOffice no produjo el PDF (rc={resultado.returncode}): "
            f"{resultado.stdout} {resultado.stderr}"
        )
    return pdf


def generar_certificado(cert, output_dir=None):
    """Genera el PDF de un certificado y retorna la ruta final.

    Parameters
    ----------
    cert : dict
        Fila del registro (ver registry.crear_lote).
    output_dir : Path | None
        Carpeta destino; por defecto CERT_EMITIDOS_PATH/<lote_id>/.
    """
    if output_dir is None:
        output_dir = settings.CERT_EMITIDOS_PATH / cert["lote_id"]
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    destino = output_dir / nombre_archivo(
        cert["alumno_nombre"], cert["alumno_rut"], cert["curso_id"]
    )

    with tempfile.TemporaryDirectory(prefix="cert_") as tmp:
        tmp = Path(tmp)
        qr_path = _generar_qr(cert["codigo"], tmp / "qr.png")

        tpl = DocxTemplate(str(settings.CERT_PLANTILLA_PATH))
        tpl.render(_contexto(cert, tpl, qr_path))
        docx_render = tmp / f"cert_{cert['folio_num']}.docx"
        tpl.save(str(docx_render))

        pdf_tmp = _convertir_a_pdf(docx_render, tmp)
        shutil.move(str(pdf_tmp), str(destino))

    logger.info("Certificado %s generado: %s", cert["folio"], destino.name)
    return destino

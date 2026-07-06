"""Prepara la plantilla DOCX de certificados de participación.

Toma la plantilla de referencia (Certificado_TECNIPRO_plantilla2.docx) y
produce data/certificados/plantilla/plantilla_certificado.docx lista para
docxtpl:

1. Repara el placeholder {{ASISTENCIA}} partido en dos runs.
2. Reestructura la frase de detalle para poder omitir la asistencia en
   cursos asincrónicos y la calificación cuando no exista:
   "...horas cronológicas{{SEP_ASIST}}{{ASISTENCIA_TXT}}{{SEP_CAL}}{{CALIFICACION_TXT}}."
3. Sustituye las imágenes embebidas (firma y logo) por las versiones en
   alta resolución (Firma 2.png / H Dorado.png), mismas proporciones.

Uso: venv/bin/python scripts/preparar_plantilla_certificado.py
"""

import shutil
import sys
import zipfile
from pathlib import Path

from docx import Document

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ORIGEN = PROJECT_ROOT / "Certificado_TECNIPRO_plantilla2.docx"
FIRMA_HD = PROJECT_ROOT / "Firma 2.png"
LOGO_HD = PROJECT_ROOT / "H Dorado.png"
DESTINO_DIR = PROJECT_ROOT / "data" / "certificados" / "plantilla"
DESTINO = DESTINO_DIR / "plantilla_certificado.docx"

# Textos exactos de los runs del párrafo de detalle en la plantilla original.
RUN_EDITS = {
    " horas cronológicas, con un porcentaje de asistencia del ":
        " horas cronológicas{{SEP_ASIST}}",
    "{{ASISTENCIA": "{{ASISTENCIA_TXT}}",
    "}}": "",
    "%": "",
    " y una calificación final de ": "{{SEP_CAL}}",
    "{{CALIFICACION}}": "{{CALIFICACION_TXT}}",
}


def main():
    if not ORIGEN.exists():
        sys.exit(f"No existe la plantilla de origen: {ORIGEN}")

    DESTINO_DIR.mkdir(parents=True, exist_ok=True)

    doc = Document(str(ORIGEN))

    # 1+2. Cirugía del párrafo de detalle (identificado por su texto).
    objetivo = None
    for p in doc.paragraphs:
        if "duración total" in p.text and "{{HORAS}}" in p.text:
            objetivo = p
            break
    if objetivo is None:
        sys.exit("No se encontró el párrafo de detalle con {{HORAS}}")

    pendientes = dict(RUN_EDITS)
    for run in objetivo.runs:
        if run.text in pendientes:
            nuevo = pendientes.pop(run.text)
            run.text = nuevo
    if pendientes:
        sys.exit(f"Runs no encontrados en el párrafo de detalle: {list(pendientes)}")

    esperado = ("El programa tuvo una duración total de {{HORAS}} horas "
                "cronológicas{{SEP_ASIST}}{{ASISTENCIA_TXT}}{{SEP_CAL}}"
                "{{CALIFICACION_TXT}}.")
    if objetivo.text != esperado:
        sys.exit(f"Párrafo resultante inesperado: {objetivo.text!r}")

    tmp = DESTINO.with_suffix(".tmp.docx")
    doc.save(str(tmp))

    # 3. Sustituir media por versiones HD (image1 = firma, image2 = logo).
    reemplazos = {
        "word/media/image1.png": FIRMA_HD.read_bytes(),
        "word/media/image2.png": LOGO_HD.read_bytes(),
    }
    with zipfile.ZipFile(str(tmp), "r") as zin, \
            zipfile.ZipFile(str(DESTINO), "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = reemplazos.get(item.filename, None)
            if data is None:
                data = zin.read(item.filename)
            zout.writestr(item, data)
    tmp.unlink()

    # Copiar activos de referencia junto a la plantilla.
    shutil.copy(str(FIRMA_HD), str(DESTINO_DIR / "firma.png"))
    shutil.copy(str(LOGO_HD), str(DESTINO_DIR / "logo.png"))
    shutil.copy(str(ORIGEN), str(DESTINO_DIR / "plantilla_original.docx"))

    print(f"Plantilla preparada: {DESTINO}")


if __name__ == "__main__":
    main()

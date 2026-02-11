"""Generación de reportes PDF por comprador usando fpdf2."""

import json
import logging
import re
import unicodedata
from datetime import datetime
from pathlib import Path

from fpdf import FPDF

from config import settings

logger = logging.getLogger(__name__)

# ── Colores corporativos ──────────────────────────────────
AZUL_OSCURO = (31, 78, 121)       # #1F4E79
AZUL_CLARO = (213, 232, 240)      # #D5E8F0
VERDE = (16, 185, 129)            # #10b981
ROJO = (239, 68, 68)              # #ef4444
AMARILLO = (245, 158, 11)         # #f59e0b
GRIS_CLARO = (240, 240, 240)
BLANCO = (255, 255, 255)
NEGRO = (0, 0, 0)


def cargar_datos(json_path=None):
    """Carga datos_procesados.json y retorna el dict."""
    if json_path is None:
        json_path = settings.JSON_DATOS_PATH

    json_path = Path(json_path)
    if not json_path.exists():
        raise FileNotFoundError(f"JSON no encontrado: {json_path}")

    with open(json_path, "r", encoding="utf-8") as f:
        datos = json.load(f)

    if not datos.get("cursos"):
        raise ValueError("JSON sin cursos")

    logger.info("Datos cargados: %d cursos", len(datos["cursos"]))
    return datos


def agrupar_por_comprador(datos):
    """Agrupa cursos por EMAIL del comprador.

    Cursos con 0 estudiantes se excluyen.  Si un comprador solo tiene
    cursos vacíos, no aparece en el resultado.

    Returns
    -------
    dict[str, dict]
        Clave: email del comprador (o ``_sin_email_<empresa>``).
        Valor: dict con ``nombre``, ``empresa``, ``email``, ``cursos``.
    """
    grupos = {}

    for curso in datos["cursos"]:
        # Fix 2: excluir cursos sin estudiantes
        if not curso.get("estudiantes"):
            logger.debug("Saltando curso sin estudiantes: %s", curso.get("nombre", "?"))
            continue

        comprador = curso.get("comprador", {})
        empresa = (comprador.get("empresa") or "").strip()
        nombre = (comprador.get("nombre") or "").strip()
        email = (comprador.get("email") or "").strip()

        if not empresa:
            empresa = "Sin comprador asignado"

        # Fix 1: agrupar por email, no por empresa
        clave = email if email else f"_sin_email_{empresa}"

        if clave not in grupos:
            grupos[clave] = {
                "nombre": nombre,
                "empresa": empresa,
                "email": email,
                "cursos": [],
            }

        grupos[clave]["cursos"].append(curso)

    logger.info("Agrupados en %d compradores (por email)", len(grupos))
    return grupos


def sanitizar_nombre_archivo(nombre):
    """Limpia un nombre para usar como nombre de archivo.

    Quita acentos, reemplaza espacios con guión bajo,
    elimina caracteres especiales.
    """
    # Normalizar Unicode (quitar acentos)
    nfkd = unicodedata.normalize("NFKD", nombre)
    sin_acentos = "".join(c for c in nfkd if not unicodedata.combining(c))

    # Reemplazar espacios y caracteres no alfanuméricos
    limpio = re.sub(r"[^\w\s-]", "", sin_acentos)
    limpio = re.sub(r"[\s]+", "_", limpio).strip("_")

    return limpio or "reporte"


def generar_pdf(grupo_comprador, output_dir=None):
    """Genera un PDF para un comprador (con todos sus cursos).

    Parameters
    ----------
    grupo_comprador : dict
        Con claves: nombre, empresa, email, cursos.
    output_dir : Path | None

    Returns
    -------
    Path
        Ruta del PDF generado.
    """
    if output_dir is None:
        output_dir = settings.REPORTS_PATH
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    empresa = grupo_comprador["empresa"]
    fecha_str = datetime.now().strftime("%Y%m%d")
    nombre_archivo = sanitizar_nombre_archivo(empresa)
    destino = output_dir / f"{nombre_archivo}_{fecha_str}.pdf"

    pdf = ReportePDF(grupo_comprador)
    pdf.generar()
    pdf.output(str(destino))

    logger.info("PDF generado: %s (%d bytes)", destino.name, destino.stat().st_size)
    return destino


def generar_todos_los_pdfs(json_path=None, output_dir=None):
    """Genera PDFs para todos los compradores.

    Returns
    -------
    list[dict]
        Lista de reportes por PDF generado.
    """
    datos = cargar_datos(json_path)
    grupos = agrupar_por_comprador(datos)

    resultados = []
    for empresa, grupo in grupos.items():
        try:
            ruta = generar_pdf(grupo, output_dir)
            total_est = sum(
                len(c.get("estudiantes", [])) for c in grupo["cursos"]
            )
            resultados.append({
                "empresa": empresa,
                "archivo": ruta.name,
                "ruta": str(ruta),
                "cursos": len(grupo["cursos"]),
                "estudiantes": total_est,
                "status": "OK",
            })
        except Exception as e:
            logger.error("Error generando PDF para %s: %s", empresa, e)
            resultados.append({
                "empresa": empresa,
                "archivo": "",
                "ruta": "",
                "cursos": len(grupo["cursos"]),
                "estudiantes": 0,
                "status": f"ERROR: {e}",
            })

    return resultados


# ══════════════════════════════════════════════════════════
#  Clase ReportePDF — construye el PDF con fpdf2
# ══════════════════════════════════════════════════════════

class ReportePDF(FPDF):
    """PDF profesional de reporte de capacitación por comprador."""

    def __init__(self, grupo_comprador):
        super().__init__(orientation="P", unit="mm", format="Letter")
        self.grupo = grupo_comprador
        self.set_auto_page_break(auto=True, margin=25)
        self.set_margins(20, 20, 20)

    def header(self):
        # Barra azul superior
        self.set_fill_color(*AZUL_OSCURO)
        self.rect(0, 0, self.w, 8, "F")

        # Título
        self.set_y(12)
        self.set_font("Helvetica", "B", 18)
        self.set_text_color(*AZUL_OSCURO)
        self.cell(0, 10, "Reporte de Capacitación", align="C", new_x="LMARGIN", new_y="NEXT")

        # Subtítulo
        self.set_font("Helvetica", "", 11)
        self.set_text_color(100, 100, 100)
        self.cell(0, 6, "Instituto de Capacitación Tecnipro", align="C", new_x="LMARGIN", new_y="NEXT")

        # Fecha
        fecha = datetime.now().strftime("%d de %B de %Y").replace(
            "January", "enero").replace("February", "febrero").replace(
            "March", "marzo").replace("April", "abril").replace(
            "May", "mayo").replace("June", "junio").replace(
            "July", "julio").replace("August", "agosto").replace(
            "September", "septiembre").replace("October", "octubre").replace(
            "November", "noviembre").replace("December", "diciembre")
        self.cell(0, 5, fecha, align="C", new_x="LMARGIN", new_y="NEXT")

        # Línea separadora
        self.set_y(self.get_y() + 3)
        self.set_draw_color(*AZUL_OSCURO)
        self.set_line_width(0.5)
        self.line(20, self.get_y(), self.w - 20, self.get_y())
        self.set_y(self.get_y() + 5)

    def footer(self):
        self.set_y(-20)
        self.set_draw_color(*AZUL_OSCURO)
        self.set_line_width(0.3)
        self.line(20, self.get_y(), self.w - 20, self.get_y())
        self.set_y(self.get_y() + 2)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(100, 100, 100)
        self.cell(0, 4, "Instituto de Capacitación Tecnipro | institutotecnipro.cl", align="L")
        self.set_x(20)
        self.cell(0, 4, f"Página {self.page_no()}/{{nb}}", align="R")
        self.set_y(self.get_y() + 4)
        self.cell(0, 4, "Reporte generado automáticamente", align="C")

    def generar(self):
        """Genera todas las páginas del reporte."""
        self.alias_nb_pages()
        self.add_page()

        # ── Info del comprador ─────────────────────────
        self._seccion_comprador()

        # ── Cada curso ─────────────────────────────────
        for i, curso in enumerate(self.grupo["cursos"]):
            if i > 0:
                self.add_page()
            self._seccion_curso(curso)

    def _seccion_comprador(self):
        """Sección con info del comprador/empresa."""
        y0 = self.get_y()
        self.set_fill_color(*AZUL_CLARO)
        self.rect(20, y0, self.w - 40, 24, "F")

        self.set_xy(25, y0 + 3)
        self.set_font("Helvetica", "B", 12)
        self.set_text_color(*AZUL_OSCURO)
        self.cell(0, 6, f"Empresa: {self.grupo['empresa']}", new_x="LMARGIN", new_y="NEXT")

        self.set_x(25)
        self.set_font("Helvetica", "", 10)
        self.set_text_color(*NEGRO)
        self.cell(80, 5, f"Contacto: {self.grupo['nombre']}")
        self.cell(0, 5, f"Cursos activos: {len(self.grupo['cursos'])}", new_x="LMARGIN", new_y="NEXT")

        self.set_y(y0 + 28)

    def _seccion_curso(self, curso):
        """Sección completa de un curso."""
        nombre = curso.get("nombre", "Sin nombre")
        id_sence = curso.get("id_sence", "")
        estado = curso.get("estado", "")
        fecha_fin = curso.get("fecha_fin", "")
        dias_rest = curso.get("dias_restantes")
        estadisticas = curso.get("estadisticas", {})
        estudiantes = curso.get("estudiantes", [])

        # ── Encabezado del curso ───────────────────────
        self.set_fill_color(*AZUL_OSCURO)
        self.set_text_color(*BLANCO)
        self.set_font("Helvetica", "B", 11)
        self.cell(0, 8, f"  CURSO: {nombre}", fill=True, new_x="LMARGIN", new_y="NEXT")

        # Info del curso
        self.set_text_color(*NEGRO)
        self.set_font("Helvetica", "", 9)
        self.set_fill_color(*GRIS_CLARO)

        info_parts = []
        if id_sence:
            info_parts.append(f"ID SENCE: {id_sence}")
        if estado:
            estado_display = {"active": "Activo", "expired": "Finalizado"}.get(estado, estado)
            info_parts.append(f"Estado: {estado_display}")
        if fecha_fin:
            info_parts.append(f"Fecha fin: {fecha_fin}")
        if dias_rest is not None:
            info_parts.append(f"Días restantes: {dias_rest}")

        self.cell(0, 6, "  " + "  |  ".join(info_parts), fill=True, new_x="LMARGIN", new_y="NEXT")
        self.ln(3)

        # ── Resumen ────────────────────────────────────
        self._cuadro_resumen(estadisticas)
        self.ln(3)

        # ── Tabla de participantes ─────────────────────
        if estudiantes:
            self._tabla_participantes(estudiantes)
            self.ln(3)

            # ── Tabla SENCE ────────────────────────────
            sence_data = [e for e in estudiantes if e.get("sence", {}).get("n_ingresos")]
            if sence_data:
                self._tabla_sence(sence_data)

    def _cuadro_resumen(self, stats):
        """Cuadro de resumen estadístico."""
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(*AZUL_OSCURO)
        self.cell(0, 6, "Resumen", new_x="LMARGIN", new_y="NEXT")

        self.set_fill_color(*AZUL_CLARO)
        y0 = self.get_y()
        w = self.w - 40
        self.rect(20, y0, w, 28, "F")

        self.set_font("Helvetica", "", 9)
        self.set_text_color(*NEGRO)
        col_w = w / 3

        # Fila 1
        self.set_xy(22, y0 + 2)
        self.cell(col_w, 5, f"Total participantes: {stats.get('total_estudiantes', 0)}")
        self.cell(col_w, 5, f"Aprobados: {stats.get('aprobados', 0)}")
        self.cell(col_w, 5, f"Reprobados: {stats.get('reprobados', 0)}")

        # Fila 2
        self.set_xy(22, y0 + 9)
        self.cell(col_w, 5, f"En proceso: {stats.get('en_proceso', 0)}")
        self.cell(col_w, 5, f"Progreso promedio: {stats.get('promedio_progreso', 0):.1f}%")
        self.cell(col_w, 5, f"Calificación promedio: {stats.get('promedio_calificacion', 0):.1f}")

        # Fila 3
        self.set_xy(22, y0 + 16)
        conectados = stats.get("conectados_sence", 0)
        total = stats.get("total_estudiantes", 0)
        self.cell(col_w, 5, f"Conectados SENCE: {conectados} de {total}")
        self.cell(col_w, 5, f"Riesgo alto: {stats.get('riesgo_alto', 0)}")
        self.cell(col_w, 5, f"Riesgo medio: {stats.get('riesgo_medio', 0)}")

        self.set_y(y0 + 30)

    def _tabla_participantes(self, estudiantes):
        """Tabla de detalle de participantes."""
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(*AZUL_OSCURO)
        self.cell(0, 6, "Detalle Participantes", new_x="LMARGIN", new_y="NEXT")

        # Anchos de columna
        w_num = 8
        w_nombre = 62
        w_progreso = 30
        w_nota = 18
        w_estado = 20
        w_riesgo = 20
        col_widths = [w_num, w_nombre, w_progreso, w_nota, w_estado, w_riesgo]
        headers = ["#", "Nombre", "Progreso", "Nota", "Estado", "Riesgo"]

        # Encabezado de tabla
        self.set_font("Helvetica", "B", 8)
        self.set_fill_color(*AZUL_OSCURO)
        self.set_text_color(*BLANCO)
        for i, h in enumerate(headers):
            self.cell(col_widths[i], 6, h, border=1, fill=True, align="C")
        self.ln()

        # Filas
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*NEGRO)

        for idx, est in enumerate(estudiantes, 1):
            # Check page break
            if self.get_y() > self.h - 35:
                self.add_page()
                # Re-draw header
                self.set_font("Helvetica", "B", 8)
                self.set_fill_color(*AZUL_OSCURO)
                self.set_text_color(*BLANCO)
                for i, h in enumerate(headers):
                    self.cell(col_widths[i], 6, h, border=1, fill=True, align="C")
                self.ln()
                self.set_font("Helvetica", "", 8)
                self.set_text_color(*NEGRO)

            # Alternar fondo
            if idx % 2 == 0:
                self.set_fill_color(*GRIS_CLARO)
            else:
                self.set_fill_color(*BLANCO)

            fill = True
            y_row = self.get_y()

            # Número
            self.cell(w_num, 6, str(idx), border=1, fill=fill, align="C")

            # Nombre (truncar si es largo)
            nombre = est.get("nombre", "")
            if len(nombre) > 35:
                nombre = nombre[:33] + ".."
            self.cell(w_nombre, 6, nombre, border=1, fill=fill)

            # Progreso con barra
            progreso = est.get("progreso") or 0
            x_prog = self.get_x()
            self.cell(w_progreso, 6, "", border=1, fill=fill)
            # Dibujar barra dentro de la celda
            bar_x = x_prog + 1
            bar_y = y_row + 1.5
            bar_w = w_progreso - 12
            bar_h = 3
            # Fondo barra
            self.set_fill_color(200, 200, 200)
            self.rect(bar_x, bar_y, bar_w, bar_h, "F")
            # Relleno barra
            if progreso > 0:
                color = VERDE if progreso >= 80 else (AMARILLO if progreso >= 50 else ROJO)
                self.set_fill_color(*color)
                self.rect(bar_x, bar_y, bar_w * min(progreso, 100) / 100, bar_h, "F")
            # Texto porcentaje
            self.set_xy(x_prog + bar_w + 2, y_row)
            self.set_font("Helvetica", "", 7)
            self.cell(9, 6, f"{progreso:.0f}%", align="R")
            self.set_font("Helvetica", "", 8)

            # Nota
            calif = est.get("calificacion")
            nota_str = f"{calif:.1f}" if calif is not None else "-"
            self.cell(w_nota, 6, nota_str, border=1, fill=fill, align="C")

            # Estado con color
            estado = est.get("estado", "")
            self._celda_estado(w_estado, estado)

            # Riesgo con color
            riesgo = est.get("riesgo", "")
            self._celda_riesgo(w_riesgo, riesgo)

            self.ln()

            # Restaurar colores
            self.set_fill_color(*BLANCO)
            self.set_text_color(*NEGRO)

    def _celda_estado(self, w, estado):
        """Celda con color según estado."""
        if estado == "A":
            self.set_fill_color(*VERDE)
            self.set_text_color(*BLANCO)
            texto = "A - Ok"
        elif estado == "R":
            self.set_fill_color(*ROJO)
            self.set_text_color(*BLANCO)
            texto = "R - Rep"
        elif estado == "P":
            self.set_fill_color(*AMARILLO)
            self.set_text_color(*NEGRO)
            texto = "P - Proc"
        else:
            self.set_fill_color(*GRIS_CLARO)
            self.set_text_color(*NEGRO)
            texto = estado or "-"

        self.cell(w, 6, texto, border=1, fill=True, align="C")
        self.set_text_color(*NEGRO)

    def _celda_riesgo(self, w, riesgo):
        """Celda con color según riesgo."""
        riesgo_lower = (riesgo or "").strip().lower()
        if riesgo_lower == "alto":
            self.set_fill_color(254, 226, 226)   # Rojo claro
            texto = "ALTO"
        elif riesgo_lower == "medio":
            self.set_fill_color(254, 243, 199)   # Amarillo claro
            texto = "MEDIO"
        else:
            self.set_fill_color(*BLANCO)
            texto = riesgo_lower.capitalize() if riesgo_lower else "-"

        self.cell(w, 6, texto, border=1, fill=True, align="C")

    def _tabla_sence(self, estudiantes):
        """Tabla de estado SENCE."""
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(*AZUL_OSCURO)
        self.cell(0, 6, "Estado SENCE", new_x="LMARGIN", new_y="NEXT")

        w_num = 8
        w_nombre = 70
        w_ingresos = 25
        w_dj = 55
        col_widths = [w_num, w_nombre, w_ingresos, w_dj]
        headers = ["#", "Nombre", "Ingresos", "Declaración Jurada"]

        # Encabezado
        self.set_font("Helvetica", "B", 8)
        self.set_fill_color(*AZUL_OSCURO)
        self.set_text_color(*BLANCO)
        for i, h in enumerate(headers):
            self.cell(col_widths[i], 6, h, border=1, fill=True, align="C")
        self.ln()

        # Filas
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*NEGRO)

        for idx, est in enumerate(estudiantes, 1):
            if self.get_y() > self.h - 35:
                self.add_page()
                self.set_font("Helvetica", "B", 8)
                self.set_fill_color(*AZUL_OSCURO)
                self.set_text_color(*BLANCO)
                for i, h in enumerate(headers):
                    self.cell(col_widths[i], 6, h, border=1, fill=True, align="C")
                self.ln()
                self.set_font("Helvetica", "", 8)
                self.set_text_color(*NEGRO)

            if idx % 2 == 0:
                self.set_fill_color(*GRIS_CLARO)
            else:
                self.set_fill_color(*BLANCO)

            sence = est.get("sence", {})
            nombre = est.get("nombre", "")
            if len(nombre) > 40:
                nombre = nombre[:38] + ".."

            self.cell(w_num, 6, str(idx), border=1, fill=True, align="C")
            self.cell(w_nombre, 6, nombre, border=1, fill=True)
            self.cell(w_ingresos, 6, str(sence.get("n_ingresos", 0)), border=1, fill=True, align="C")
            self.cell(w_dj, 6, sence.get("declaracion_jurada", "-") or "-", border=1, fill=True, align="C")
            self.ln()

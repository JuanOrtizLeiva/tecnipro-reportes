"""Descarga de CSVs de conectividad SENCE curso por curso.

Flujo real verificado con diagnóstico (debug_curso_detail.py):

1. En BusquedaAccion: llenar #FilterCodigoCurso → clic "Buscar"
2. Dialog jQuery UI aparece con "Listado de Cursos"
3. Clic en icono de estado (última columna) → link <a> a CursoSeleccionado
4. Página "Detalle de Acción" (DetalleAccion) con info del curso
5. Clic en #Btn_DescargarConectividad → descarga CSV de conectividad
6. Clic en "Volver" → regresa (puede requerir re-configurar búsqueda)

Selectores reales:
- #FilterCodigoCurso            input de búsqueda por ID
- div.ui-dialog:visible         dialog de resultados
- td:last-child a               link al icono de estado en el dialog
- #Btn_DescargarConectividad    botón de descarga en DetalleAccion
- a:has-text('Volver')          link para volver
"""

import csv
import logging
from pathlib import Path

from config import settings

logger = logging.getLogger(__name__)

PAGE_TIMEOUT = settings.SCRAPER_TIMEOUT  # 90s
DOWNLOAD_TIMEOUT = 120000  # 120s para descargas (archivos pueden ser grandes)


async def descargar_curso(page, sence_id, output_dir=None):
    """Busca un curso, entra al detalle, y descarga el CSV de conectividad.

    Parameters
    ----------
    page : playwright.async_api.Page
    sence_id : str
    output_dir : Path | None

    Returns
    -------
    bool
        ``True`` si la descarga fue exitosa.
    """
    if output_dir is None:
        output_dir = settings.SENCE_CSV_PATH
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    destino = output_dir / f"{sence_id}.csv"

    logger.info("Buscando curso SENCE %s", sence_id)

    # ── 1. Ingresar ID y buscar ──────────────────────────
    campo = page.locator("input#FilterCodigoCurso")
    await campo.wait_for(state="visible", timeout=PAGE_TIMEOUT)
    await campo.click()
    await campo.fill("")
    await campo.fill(sence_id)

    boton_buscar = page.locator("input[value='Buscar']").or_(
        page.get_by_role("button", name="Buscar")
    )
    await boton_buscar.first.click(timeout=PAGE_TIMEOUT)

    # Esperar que aparezca el dialog de resultados
    dialog = page.locator("div.ui-dialog:visible")
    try:
        await dialog.wait_for(state="visible", timeout=PAGE_TIMEOUT)
    except Exception:
        pass
    await page.wait_for_timeout(2000)

    # ── 2. Verificar si hay resultados ───────────────────
    # Buscar el link del icono en la última columna (Ver Estado)
    link_estado = page.locator(
        "div.ui-dialog:visible table td:last-child a"
    )
    if await link_estado.count() == 0:
        logger.warning("SENCE %s: sin resultados en búsqueda", sence_id)
        destino.write_text("No hay datos disponibles!\n", encoding="utf-8")
        await _cerrar_dialog(page)
        return True

    # ── 3. Clic en el icono de estado → Detalle de Acción ─
    href = await link_estado.first.get_attribute("href") or ""
    logger.info("SENCE %s: entrando al detalle (%s)", sence_id, href.split("?")[0])
    await link_estado.first.click(timeout=PAGE_TIMEOUT)

    await page.wait_for_load_state("networkidle", timeout=PAGE_TIMEOUT)
    await page.wait_for_timeout(1000)
    logger.info("SENCE %s: en página de detalle: %s", sence_id, page.url)

    # ── 4. Descargar Conectividad ────────────────────────
    btn_descargar = page.locator("input#Btn_DescargarConectividad")

    if await btn_descargar.count() > 0 and await btn_descargar.is_visible():
        try:
            async with page.expect_download(timeout=DOWNLOAD_TIMEOUT) as download_info:
                await btn_descargar.click(timeout=PAGE_TIMEOUT)
            download = await download_info.value
            await download.save_as(str(destino))
            logger.info(
                "SENCE %s: conectividad descargada (%d bytes)",
                sence_id, destino.stat().st_size,
            )
        except Exception as e:
            logger.warning(
                "SENCE %s: descarga falló (%s), intentando scraping de tabla",
                sence_id, e,
            )
            # Fallback: scrappear la tabla de participantes
            scrapeado = await _scrappear_tabla_participantes(page, destino, sence_id)
            if not scrapeado:
                logger.warning("SENCE %s: no se pudo obtener datos", sence_id)
                destino.write_text("No hay datos disponibles!\n", encoding="utf-8")
    else:
        # Si no hay botón, intentar scrappear la tabla
        logger.info("SENCE %s: sin botón Descargar Conectividad, scrapeando tabla", sence_id)
        scrapeado = await _scrappear_tabla_participantes(page, destino, sence_id)
        if not scrapeado:
            destino.write_text("No hay datos disponibles!\n", encoding="utf-8")

    # ── 5. Volver a la página de búsqueda ────────────────
    await _volver(page)

    return True


async def _scrappear_tabla_participantes(page, destino, sence_id):
    """Extrae datos de la tabla 'Listado de Participantes' en DetalleAccion."""
    # Buscar tabla con encabezado "Rut Participante"
    tabla = page.locator("table:has(th:has-text('Rut'))")
    if await tabla.count() == 0:
        tabla = page.locator("table").last

    if await tabla.count() == 0:
        return False

    # Verificar si dice "No hay datos disponibles"
    no_data = tabla.locator("text='No hay datos disponibles'")
    if await no_data.count() > 0:
        logger.info("SENCE %s: tabla sin datos de participantes", sence_id)
        destino.write_text("No hay datos disponibles!\n", encoding="utf-8")
        return True

    filas = tabla.first.locator("tbody tr")
    n_filas = await filas.count()
    if n_filas == 0:
        return False

    registros = []
    for i in range(n_filas):
        fila = filas.nth(i)
        celdas = fila.locator("td")
        n_celdas = await celdas.count()
        if n_celdas == 0:
            continue

        valores = []
        for j in range(n_celdas):
            texto = await celdas.nth(j).text_content()
            valores.append((texto or "").strip())

        if valores and any(v for v in valores):
            registros.append(valores)

    if not registros:
        return False

    with open(destino, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(registros)

    logger.info("SENCE %s: tabla scrapeada (%d registros)", sence_id, len(registros))
    return True


async def _volver(page):
    """Hace clic en 'Volver' para regresar a la búsqueda."""
    try:
        link_volver = page.locator("a:has-text('Volver')")
        if await link_volver.count() > 0:
            await link_volver.first.click(timeout=PAGE_TIMEOUT)
            await page.wait_for_load_state("networkidle", timeout=PAGE_TIMEOUT)
            logger.debug("Clic en 'Volver' — URL: %s", page.url)
        else:
            # Fallback: ir atrás en el navegador
            await page.go_back(wait_until="networkidle", timeout=PAGE_TIMEOUT)
            logger.debug("Navegador atrás — URL: %s", page.url)
    except Exception as e:
        logger.warning("Error al volver: %s", e)


async def _cerrar_dialog(page):
    """Cierra el jQuery UI dialog de resultados."""
    try:
        btn_cerrar = page.locator(
            "div.ui-dialog:visible input[value='Cerrar'], "
            "div.ui-dialog:visible button:has-text('Cerrar')"
        )
        if await btn_cerrar.count() > 0:
            await btn_cerrar.first.click(timeout=5000)
            await page.wait_for_timeout(500)
            return

        btn_x = page.locator("div.ui-dialog:visible .ui-dialog-titlebar-close")
        if await btn_x.count() > 0:
            await btn_x.first.click(timeout=5000)
            await page.wait_for_timeout(500)
            return

        await page.keyboard.press("Escape")
        await page.wait_for_timeout(500)
    except Exception:
        try:
            await page.evaluate(
                "document.querySelectorAll('.ui-dialog').forEach(d => d.style.display = 'none')"
            )
        except Exception:
            pass


async def limpiar_busqueda(page):
    """Cierra dialog abierto y limpia el campo de búsqueda."""
    await _cerrar_dialog(page)

    campo = page.locator("input#FilterCodigoCurso")
    if await campo.count() > 0 and await campo.is_visible():
        try:
            await campo.fill("")
        except Exception:
            pass

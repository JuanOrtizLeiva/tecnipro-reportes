"""Descarga de CSVs de asistencia SENCE curso por curso."""

import csv
import logging
from pathlib import Path

from config import settings

logger = logging.getLogger(__name__)

PAGE_TIMEOUT = settings.SCRAPER_TIMEOUT
DOWNLOAD_TIMEOUT = 60000
WAIT_BETWEEN_DOWNLOADS = 3  # segundos


async def descargar_curso(page, sence_id, output_dir=None):
    """Busca un curso por ID SENCE y descarga su CSV de asistencia.

    Parameters
    ----------
    page : playwright.async_api.Page
    sence_id : str
        ID SENCE del curso (ej: ``"6731347"``).
    output_dir : Path | None
        Carpeta de destino.  Por defecto ``settings.SENCE_CSV_PATH``.

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

    # ── Limpiar e ingresar ID ──────────────────────────────
    campo = page.locator(
        "input[name*='codigo'], input[name*='Codigo'], "
        "input[id*='codigo'], input[id*='Codigo'], "
        "input[name*='accion'], input[name*='Accion'], "
        "input[id*='idAccion'], input[id*='txtCodigo']"
    ).or_(
        page.locator("input[type='text']").last
    )
    await campo.first.click()
    await campo.first.fill("")
    await campo.first.fill(sence_id)

    # ── Clic en "Buscar" ──────────────────────────────────
    boton_buscar = page.get_by_role("button", name="Buscar").or_(
        page.locator("button:has-text('Buscar'), input[value='Buscar']")
    )
    await boton_buscar.first.click(timeout=PAGE_TIMEOUT)

    # Esperar resultados
    await page.wait_for_load_state("networkidle", timeout=PAGE_TIMEOUT)
    await page.wait_for_timeout(2000)

    # ── Verificar si hay resultados ────────────────────────
    sin_datos = page.locator("text='No hay datos disponibles'").or_(
        page.locator("text='Sin resultados'")
    ).or_(
        page.locator("text='no se encontraron'")
    )
    if await sin_datos.count() > 0:
        logger.warning("SENCE %s: sin resultados", sence_id)
        # Guardar CSV con mensaje de "no hay datos" para consistencia
        destino.write_text("No hay datos disponibles!\n", encoding="utf-8")
        return True  # No es un error, simplemente no hay datos

    # ── Intentar descarga vía botón Exportar/Descargar ─────
    descargado = await _intentar_descarga_boton(page, destino)
    if descargado:
        logger.info("SENCE %s: CSV descargado (%d bytes)", sence_id, destino.stat().st_size)
        return True

    # ── Fallback: scrappear tabla HTML ─────────────────────
    scrapeado = await _scrappear_tabla(page, destino, sence_id)
    if scrapeado:
        logger.info("SENCE %s: tabla extraída a CSV (%d bytes)", sence_id, destino.stat().st_size)
        return True

    logger.warning("SENCE %s: no se pudo descargar ni extraer datos", sence_id)
    return False


async def _intentar_descarga_boton(page, destino):
    """Intenta descargar CSV haciendo clic en botón de exportar."""
    boton_export = page.locator(
        "a:has-text('Exportar'), button:has-text('Exportar'), "
        "a:has-text('Descargar'), button:has-text('Descargar'), "
        "a:has-text('CSV'), button:has-text('CSV'), "
        "a:has-text('Excel'), button:has-text('Excel'), "
        "a[href*='export'], a[href*='download']"
    )

    if await boton_export.count() == 0:
        return False

    try:
        async with page.expect_download(timeout=DOWNLOAD_TIMEOUT) as download_info:
            await boton_export.first.click()
        download = await download_info.value
        await download.save_as(str(destino))
        return True
    except Exception as e:
        logger.debug("Descarga vía botón falló: %s", e)
        return False


async def _scrappear_tabla(page, destino, sence_id):
    """Extrae datos de una tabla HTML y los guarda como CSV."""
    tabla = page.locator("table").last
    if await tabla.count() == 0:
        return False

    filas = tabla.locator("tbody tr").or_(tabla.locator("tr"))
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

    # Guardar como CSV sin encabezados (formato SENCE)
    with open(destino, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(registros)

    return True


async def limpiar_busqueda(page):
    """Limpia el campo de búsqueda para el siguiente curso."""
    # Intentar botón "Limpiar"
    boton_limpiar = page.get_by_role("button", name="Limpiar").or_(
        page.locator("button:has-text('Limpiar'), input[value='Limpiar']")
    )
    if await boton_limpiar.count() > 0:
        await boton_limpiar.first.click()
        await page.wait_for_timeout(500)
        return

    # Fallback: limpiar el campo de texto directamente
    campo = page.locator(
        "input[name*='codigo'], input[name*='Codigo'], "
        "input[id*='codigo'], input[id*='Codigo'], "
        "input[name*='accion'], input[name*='Accion'], "
        "input[id*='idAccion'], input[id*='txtCodigo']"
    ).or_(
        page.locator("input[type='text']").last
    )
    if await campo.count() > 0:
        await campo.first.fill("")

"""Navegación por menús del portal SENCE (selección de perfil y búsqueda)."""

import logging

from config import settings

logger = logging.getLogger(__name__)

PAGE_TIMEOUT = settings.SCRAPER_TIMEOUT

# Valores exactos para los dropdowns
PERFIL = "CAPACITADOR - ADMINISTRADOR NACIONAL"
INSTITUCION = "Servicios de Capacitación Tecnipro Limitada"
ACCION = "Emitir Declaración Jurada – E-learning"
LINEA_CAPACITACION = "Franquicia Tributaria E-Learning"
CRITERIO = "Curso"


async def seleccionar_perfil(page):
    """Selecciona perfil, institución y acción en la pantalla post-login.

    Returns
    -------
    bool
    """
    logger.info("Seleccionando perfil e institución")

    await page.wait_for_load_state("networkidle", timeout=PAGE_TIMEOUT)

    # ── Perfil ─────────────────────────────────────────────
    select_perfil = page.locator("select").filter(has_text="CAPACITADOR").or_(
        page.locator("select[name*='perfil'], select[id*='perfil'], select[name*='Perfil']")
    )
    if await select_perfil.count() > 0:
        await select_perfil.first.select_option(label=PERFIL)
        logger.info("Perfil seleccionado: %s", PERFIL)
        # Esperar posible recarga del siguiente dropdown
        await page.wait_for_timeout(1000)
    else:
        # Intentar por texto visible en cualquier select
        selects = page.locator("select")
        for i in range(await selects.count()):
            opciones = await selects.nth(i).locator("option").all_text_contents()
            if any(PERFIL in opt for opt in opciones):
                await selects.nth(i).select_option(label=PERFIL)
                logger.info("Perfil seleccionado (fallback)")
                await page.wait_for_timeout(1000)
                break

    # ── Institución ────────────────────────────────────────
    select_inst = page.locator("select").filter(has_text="Tecnipro").or_(
        page.locator("select[name*='institucion'], select[id*='institucion'], select[name*='Institucion']")
    )
    if await select_inst.count() > 0:
        await select_inst.first.select_option(label=INSTITUCION)
        logger.info("Institución seleccionada: %s", INSTITUCION)
        await page.wait_for_timeout(1000)
    else:
        selects = page.locator("select")
        for i in range(await selects.count()):
            opciones = await selects.nth(i).locator("option").all_text_contents()
            if any("Tecnipro" in opt for opt in opciones):
                await selects.nth(i).select_option(label=INSTITUCION)
                logger.info("Institución seleccionada (fallback)")
                await page.wait_for_timeout(1000)
                break

    # ── Acción ─────────────────────────────────────────────
    select_accion = page.locator(
        "select[name*='accion'], select[id*='accion'], select[name*='Accion']"
    ).or_(
        page.locator("select").filter(has_text="Declaración Jurada")
    )
    if await select_accion.count() > 0:
        await select_accion.first.select_option(label=ACCION)
        logger.info("Acción seleccionada: %s", ACCION)
        await page.wait_for_timeout(1000)
    else:
        selects = page.locator("select")
        for i in range(await selects.count()):
            opciones = await selects.nth(i).locator("option").all_text_contents()
            if any("Declaración Jurada" in opt or "E-learning" in opt for opt in opciones):
                await selects.nth(i).select_option(label=ACCION)
                logger.info("Acción seleccionada (fallback)")
                await page.wait_for_timeout(1000)
                break

    # ── Clic en "Seleccionar" ──────────────────────────────
    boton = page.get_by_role("button", name="Seleccionar").or_(
        page.locator("button:has-text('Seleccionar'), input[value='Seleccionar']")
    )
    await boton.first.click(timeout=PAGE_TIMEOUT)
    logger.info("Clic en 'Seleccionar'")

    await page.wait_for_load_state("networkidle", timeout=PAGE_TIMEOUT)
    return True


async def configurar_busqueda(page):
    """Configura la búsqueda: Línea de Capacitación y Criterio.

    Returns
    -------
    bool
    """
    logger.info("Configurando búsqueda")

    await page.wait_for_load_state("networkidle", timeout=PAGE_TIMEOUT)

    # ── Línea de Capacitación ──────────────────────────────
    select_linea = page.locator(
        "select[name*='linea'], select[id*='linea'], select[name*='Linea']"
    ).or_(
        page.locator("select").filter(has_text="Franquicia")
    )
    if await select_linea.count() > 0:
        await select_linea.first.select_option(label=LINEA_CAPACITACION)
        logger.info("Línea seleccionada: %s", LINEA_CAPACITACION)
        await page.wait_for_timeout(1000)
    else:
        selects = page.locator("select")
        for i in range(await selects.count()):
            opciones = await selects.nth(i).locator("option").all_text_contents()
            if any("Franquicia" in opt for opt in opciones):
                await selects.nth(i).select_option(label=LINEA_CAPACITACION)
                logger.info("Línea seleccionada (fallback)")
                await page.wait_for_timeout(1000)
                break

    # ── Criterio ───────────────────────────────────────────
    select_criterio = page.locator(
        "select[name*='criterio'], select[id*='criterio'], select[name*='Criterio']"
    ).or_(
        page.locator("select").filter(has_text="Curso")
    )
    if await select_criterio.count() > 0:
        await select_criterio.first.select_option(label=CRITERIO)
        logger.info("Criterio seleccionado: %s", CRITERIO)
        await page.wait_for_timeout(1000)
    else:
        selects = page.locator("select")
        for i in range(await selects.count()):
            opciones = await selects.nth(i).locator("option").all_text_contents()
            if any("Curso" in opt for opt in opciones):
                await selects.nth(i).select_option(label=CRITERIO)
                logger.info("Criterio seleccionado (fallback)")
                await page.wait_for_timeout(1000)
                break

    logger.info("Búsqueda configurada")
    return True

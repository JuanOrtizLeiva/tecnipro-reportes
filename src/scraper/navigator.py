"""Navegación por menús del portal SENCE (selección de perfil y búsqueda).

Página de selección de perfil (verificada con diagnóstico):
URL: lce.sence.cl/CertificadoAsistencia/SeleccionarPerfil
Form id="Formulario"

Selectores reales:
- #cmbPerfiles      (name="Perfiles")       → value="73"  CAPACITADOR - ADMIN NAC.
- #cmbInstituciones (name="Instituciones")   → cargado vía AJAX tras seleccionar perfil
- #cmdDestino       (name="Destino")         → value="2"   Emitir DJ – E-learning
- #btnSeleccionar   (input type="button")    → onclick="Seleccionar()"

Las instituciones se cargan dinámicamente al cambiar el perfil.
"""

import logging

from config import settings

logger = logging.getLogger(__name__)

PAGE_TIMEOUT = settings.SCRAPER_TIMEOUT

# Valores para los dropdowns (por value, no por label)
PERFIL_VALUE = "73"                # CAPACITADOR - ADMINISTRADOR NACIONAL
PERFIL_LABEL = "CAPACITADOR - ADMINISTRADOR NACIONAL"
INSTITUCION_LABEL = "Servicios de Capacitación Tecnipro Limitada"
DESTINO_VALUE = "2"                # Emitir Declaración Jurada – E-learning


async def seleccionar_perfil(page):
    """Selecciona perfil, institución y acción en SeleccionarPerfil.

    El flujo es secuencial: perfil → esperar carga instituciones → institución
    → acción → clic Seleccionar.

    Returns
    -------
    bool
    """
    logger.info("Página de selección de perfil: %s", page.url)

    # Detectar si estamos en la página de selección de perfil
    if "SeleccionarPerfil" not in page.url:
        logger.info("No es página de selección de perfil — puede haber sesión previa")
        return True

    await page.wait_for_load_state("networkidle", timeout=PAGE_TIMEOUT)

    # ── 1. Perfil ────────────────────────────────────────
    select_perfil = page.locator("select#cmbPerfiles")
    await select_perfil.wait_for(state="visible", timeout=PAGE_TIMEOUT)
    await select_perfil.select_option(value=PERFIL_VALUE)
    logger.info("Perfil seleccionado: %s (value=%s)", PERFIL_LABEL, PERFIL_VALUE)

    # Esperar a que se carguen las instituciones vía AJAX.
    # El dropdown #cmbInstituciones se llena dinámicamente tras seleccionar perfil.
    # Esperamos a que tenga más de 1 opción (la primera es el placeholder).
    select_inst = page.locator("select#cmbInstituciones")
    try:
        await select_inst.locator("option:nth-child(2)").wait_for(
            state="attached", timeout=PAGE_TIMEOUT
        )
    except Exception:
        # Si no cargaron, esperar un poco más y reintentar
        await page.wait_for_timeout(3000)

    # ── 2. Institución ───────────────────────────────────
    # Listar opciones para encontrar la correcta
    opciones_inst = await select_inst.locator("option").all()
    institucion_value = None
    for opt in opciones_inst:
        text = (await opt.text_content() or "").strip()
        value = await opt.get_attribute("value") or ""
        if "Tecnipro" in text:
            institucion_value = value
            logger.info("Institución encontrada: '%s' (value=%s)", text, value)
            break

    if institucion_value:
        await select_inst.select_option(value=institucion_value)
        logger.info("Institución seleccionada")
    else:
        # Fallback: seleccionar por label parcial
        all_texts = await select_inst.locator("option").all_text_contents()
        logger.warning(
            "Institución 'Tecnipro' no encontrada. Opciones: %s", all_texts
        )
        # Intentar seleccionar la primera opción no-placeholder
        if len(all_texts) > 1:
            await select_inst.select_option(index=1)
            logger.warning("Seleccionada primera institución disponible")
        else:
            raise RuntimeError(
                f"No hay instituciones disponibles para perfil {PERFIL_LABEL}"
            )

    await page.wait_for_timeout(500)

    # ── 3. ¿Qué desea realizar? ─────────────────────────
    select_destino = page.locator("select#cmdDestino")
    await select_destino.select_option(value=DESTINO_VALUE)
    logger.info("Destino seleccionado: Emitir DJ E-learning (value=%s)", DESTINO_VALUE)

    await page.wait_for_timeout(500)

    # ── 4. Clic en "Seleccionar" ─────────────────────────
    boton = page.locator("input#btnSeleccionar")
    await boton.click(timeout=PAGE_TIMEOUT)
    logger.info("Clic en 'Seleccionar'")

    await page.wait_for_load_state("networkidle", timeout=PAGE_TIMEOUT)
    logger.info("Perfil configurado — URL: %s", page.url)
    return True


async def configurar_busqueda(page):
    """Configura la búsqueda si hay dropdowns adicionales post-perfil.

    En algunas versiones del portal hay una página intermedia para
    seleccionar Línea de Capacitación y Criterio de búsqueda.
    Si no existen esos dropdowns, se asume que la configuración
    ya se hizo en la selección de perfil.

    Returns
    -------
    bool
    """
    logger.info("Verificando configuración de búsqueda: %s", page.url)

    await page.wait_for_load_state("networkidle", timeout=PAGE_TIMEOUT)

    # Verificar si hay selects de línea/criterio en esta página
    selects = page.locator("select")
    count = await selects.count()

    if count == 0:
        logger.info("No hay dropdowns adicionales — búsqueda lista")
        return True

    # Buscar select de Línea de Capacitación
    for i in range(count):
        sel = selects.nth(i)
        sel_id = await sel.get_attribute("id") or ""
        opciones = await sel.locator("option").all_text_contents()

        if any("Franquicia" in opt for opt in opciones):
            # Seleccionar "Franquicia Tributaria E-Learning"
            for opt_el in await sel.locator("option").all():
                text = (await opt_el.text_content() or "").strip()
                if "Franquicia" in text and "E-Learning" in text:
                    value = await opt_el.get_attribute("value") or ""
                    await sel.select_option(value=value)
                    logger.info("Línea seleccionada: %s", text)
                    break
            await page.wait_for_timeout(1000)

        if any("Curso" == opt.strip() for opt in opciones):
            # Seleccionar "Curso" como criterio
            for opt_el in await sel.locator("option").all():
                text = (await opt_el.text_content() or "").strip()
                if text == "Curso":
                    value = await opt_el.get_attribute("value") or ""
                    await sel.select_option(value=value)
                    logger.info("Criterio seleccionado: %s", text)
                    break
            await page.wait_for_timeout(1000)

    # Verificar que el campo de búsqueda por código de curso sea visible
    campo_codigo = page.locator("input#FilterCodigoCurso")
    try:
        await campo_codigo.wait_for(state="visible", timeout=PAGE_TIMEOUT)
        logger.info("Búsqueda configurada — campo #FilterCodigoCurso visible")
    except Exception:
        logger.warning(
            "Búsqueda configurada pero #FilterCodigoCurso no visible — "
            "puede requerir selección adicional"
        )
    return True

"""Login en SENCE con Clave Única.

Flujo real (verificado con debug_sence.py):
1. lce.sence.cl/CertificadoAsistencia/ → clic "Ingresar"
2. Redirige a sistemas.sence.cl/ClaveUnica (página intermedia con 3 opciones)
3. Clic en botón Clave Única (onclick="IniciarClaveUnica()")
   → navega a /ClaveUnica/Autorizacion/IniciarClaveUnica
4. Redirige a accounts.claveunica.gob.cl/accounts/login/
5. Llenar input[name='run'] (RUT) + input[name='password']
6. Clic en button#login-submit ("INGRESA")
7. Redirige de vuelta a sistemas.sence.cl/claveunica → SENCE
"""

import logging

from config import settings

logger = logging.getLogger(__name__)

SENCE_URL = "https://lce.sence.cl/CertificadoAsistencia/"
MAX_RETRIES_LOGIN = 1
PAGE_TIMEOUT = settings.SCRAPER_TIMEOUT


async def abrir_portal(page):
    """Abre el portal SENCE y hace clic en 'Ingresar'.

    Returns
    -------
    bool
        ``True`` si se llegó a la página intermedia de SENCE.
    """
    logger.info("Abriendo portal SENCE: %s", SENCE_URL)
    await page.goto(SENCE_URL, wait_until="networkidle", timeout=PAGE_TIMEOUT)

    # Esperar a que la página termine de cargar completamente
    await page.wait_for_load_state("networkidle", timeout=PAGE_TIMEOUT)
    logger.debug("Página SENCE cargada, buscando botón Ingresar")

    # Buscar botón "Ingresar" (es un <button type="submit">)
    boton = page.locator("button:has-text('Ingresar')").or_(
        page.get_by_role("link", name="Ingresar")
    ).or_(
        page.locator("a:has-text('Ingresar')")
    )

    # Esperar a que el botón sea visible antes de hacer click
    await boton.first.wait_for(state="visible", timeout=PAGE_TIMEOUT)
    await boton.first.click(timeout=PAGE_TIMEOUT)
    logger.info("Clic en 'Ingresar' — esperando página intermedia")

    await page.wait_for_load_state("networkidle", timeout=PAGE_TIMEOUT)
    logger.info("Página intermedia cargada: %s", page.url)
    return True


async def seleccionar_clave_unica(page):
    """En la página intermedia de SENCE, hace clic en el botón de Clave Única.

    La página sistemas.sence.cl/ClaveUnica tiene 3 opciones de login:
    1. Persona Ciudadana → botón Clave Única (onclick="IniciarClaveUnica()")
    2. Empresa → Clave Tributaria
    3. Clave SENCE (formulario propio)

    Necesitamos la opción 1.

    Returns
    -------
    bool
        ``True`` si se llegó a la página de ClaveUnica.gob.cl.
    """
    logger.info("Buscando botón Clave Única en página intermedia")

    # El botón tiene onclick="IniciarClaveUnica();" y una imagen de fondo
    boton_cu = page.locator("button[onclick*='IniciarClaveUnica']")

    if await boton_cu.count() > 0:
        await boton_cu.first.click(timeout=PAGE_TIMEOUT)
        logger.info("Clic en botón Clave Única")
    else:
        # Fallback: navegar directamente a la URL que IniciarClaveUnica() usa
        logger.warning("Botón Clave Única no encontrado, navegando directo")
        base = page.url.split("/ClaveUnica")[0]
        await page.goto(
            f"{base}/ClaveUnica/Autorizacion/IniciarClaveUnica",
            timeout=PAGE_TIMEOUT,
        )

    # Esperar redirección a accounts.claveunica.gob.cl
    await page.wait_for_url(
        "**/accounts.claveunica.gob.cl/**", timeout=PAGE_TIMEOUT
    )
    await page.wait_for_load_state("networkidle", timeout=PAGE_TIMEOUT)
    logger.info("En página Clave Única: %s", page.url)
    return True


async def login_clave_unica(page):
    """Ingresa RUT y contraseña en accounts.claveunica.gob.cl.

    Selectores reales (verificados con diagnóstico):
    - RUT:      input[name='run'] (id='uname', type='text')
    - Password: input[name='password'] (id='pword', type='password')
    - Submit:   button#login-submit (texto 'INGRESA')
    - Form:     form#login-form (method='POST')

    Returns
    -------
    bool
        ``True`` si el login fue exitoso y redirigió a SENCE.

    Raises
    ------
    RuntimeError
        Si se detecta captcha o error de credenciales.
    """
    import re
    rut_raw = settings.CLAVE_UNICA_RUT
    password = settings.CLAVE_UNICA_PASSWORD

    if not rut_raw or not password:
        raise RuntimeError("Credenciales Clave Única no configuradas en .env")

    # Limpiar RUT: quitar puntos y guiones, dejar solo dígitos + K
    rut = re.sub(r"[^0-9kK]", "", rut_raw)
    logger.info("Iniciando login Clave Única (RUT: %s...)", rut[:4])

    # Verificar si ya estamos en SENCE (sesión activa)
    if "sence.cl" in page.url and "claveunica" not in page.url.lower():
        logger.info("Ya estamos en SENCE - sesión activa detectada")
        return True

    # Detectar captcha
    captcha = page.locator("iframe[src*='captcha'], .g-recaptcha, #captcha")
    if await captcha.count() > 0:
        raise RuntimeError(
            "CAPTCHA detectado en Clave Única — login automático no posible"
        )

    # Ingresar RUT — selector real: input[name='run'] id='uname'
    campo_rut = page.locator("input#uname")

    try:
        await campo_rut.wait_for(state="visible", timeout=PAGE_TIMEOUT)
    except Exception as e:
        # El campo no apareció - capturar diagnósticos
        logger.error("Campo RUT no encontrado - capturando diagnósticos")
        logger.error("URL actual: %s", page.url)
        logger.error("Título página: %s", await page.title())

        # Buscar mensajes de error comunes
        posibles_errores = [
            ".alert", ".error", ".mensaje-error",
            "[class*='error']", "[class*='alert']",
            "#error-message", ".notification"
        ]
        for selector in posibles_errores:
            elementos = page.locator(selector)
            if await elementos.count() > 0:
                for i in range(await elementos.count()):
                    texto = await elementos.nth(i).text_content()
                    if texto and texto.strip():
                        logger.error("Posible error en página: %s", texto.strip())

        # Capturar HTML parcial para diagnóstico (primeros 2000 chars del body)
        try:
            body_text = await page.locator("body").text_content()
            if body_text:
                logger.error("Contenido página (primeros 500 chars): %s", body_text[:500])
        except Exception:
            pass

        # Re-lanzar el error original
        raise RuntimeError(
            f"Campo de RUT (input#uname) no encontrado. "
            f"URL: {page.url}, Error: {e}"
        )

    await campo_rut.fill(rut)
    logger.debug("RUT ingresado")

    # Ingresar contraseña — selector real: input[name='password'] id='pword'
    campo_pass = page.locator("input#pword")
    await campo_pass.wait_for(state="visible", timeout=PAGE_TIMEOUT)
    await campo_pass.fill(password)
    logger.debug("Contraseña ingresada")

    # El botón #login-submit está deshabilitado hasta que ambos campos
    # tengan valor (verificado via jQuery keyup). Playwright .fill() no
    # dispara keyup, así que ejecutamos el check manualmente.
    await page.evaluate("checkInputAndDisableSubmitButton()")

    # Esperar a que el botón se habilite
    boton_login = page.locator("button#login-submit:not([disabled])")
    await boton_login.wait_for(state="visible", timeout=PAGE_TIMEOUT)
    await boton_login.click()
    logger.info("Credenciales enviadas — esperando redirección")

    # Esperar redirección de vuelta a SENCE.
    # Post-login pasa por: claveunica.gob.cl → sistemas.sence.cl → lce.sence.cl
    # La página final es SeleccionarPerfil (con hash #no-back-button).
    # Usamos wait_for_url con regex para capturar la URL con o sin hash.
    try:
        await page.wait_for_url(
            lambda url: "sence.cl" in url and "claveunica" not in url,
            timeout=PAGE_TIMEOUT,
        )
    except Exception:
        # Verificar si hubo error de credenciales
        error_msg = page.locator(
            ".alert-danger, .error-message, [class*='error'], .validation-summary-errors"
        )
        if await error_msg.count() > 0:
            texto = await error_msg.first.text_content()
            raise RuntimeError(f"Error de login Clave Única: {texto}")
        raise RuntimeError(
            f"Timeout esperando redirección post-login (URL actual: {page.url})"
        )

    await page.wait_for_load_state("networkidle", timeout=PAGE_TIMEOUT)
    logger.info("Login exitoso — redirigido a SENCE: %s", page.url)
    return True


async def login_completo(page):
    """Ejecuta el flujo completo: portal → intermedia → Clave Única → login.

    Reintenta hasta ``MAX_RETRIES_LOGIN`` veces si hay timeout.

    Returns
    -------
    bool
    """
    last_error = None

    for intento in range(MAX_RETRIES_LOGIN + 1):
        try:
            await abrir_portal(page)
            await seleccionar_clave_unica(page)
            await login_clave_unica(page)
            return True
        except RuntimeError:
            # Errores de credenciales o captcha: no reintentar
            raise
        except Exception as e:
            last_error = e
            if intento < MAX_RETRIES_LOGIN:
                logger.warning(
                    "Login intento %d falló: %s — reintentando...",
                    intento + 1, e,
                )
                await page.goto("about:blank")
                continue

    raise RuntimeError(f"Login fallido tras {MAX_RETRIES_LOGIN + 1} intentos: {last_error}")

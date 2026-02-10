"""Login en SENCE con Clave Única."""

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
        ``True`` si se llegó a la página de Clave Única.
    """
    logger.info("Abriendo portal SENCE: %s", SENCE_URL)
    await page.goto(SENCE_URL, wait_until="networkidle", timeout=PAGE_TIMEOUT)

    # Buscar botón "Ingresar"
    boton = page.get_by_role("link", name="Ingresar").or_(
        page.get_by_role("button", name="Ingresar")
    ).or_(
        page.locator("a:has-text('Ingresar')")
    )
    await boton.first.click(timeout=PAGE_TIMEOUT)
    logger.info("Clic en 'Ingresar' — esperando Clave Única")

    # Esperar a que cargue la página de Clave Única
    await page.wait_for_load_state("networkidle", timeout=PAGE_TIMEOUT)
    return True


async def login_clave_unica(page):
    """Ingresa RUT y contraseña en ClaveUnica.gob.cl.

    Returns
    -------
    bool
        ``True`` si el login fue exitoso y redirigió a SENCE.

    Raises
    ------
    RuntimeError
        Si se detecta captcha o error de credenciales.
    """
    rut = settings.CLAVE_UNICA_RUT
    password = settings.CLAVE_UNICA_PASSWORD

    if not rut or not password:
        raise RuntimeError("Credenciales Clave Única no configuradas en .env")

    logger.info("Iniciando login Clave Única (RUT: %s...)", rut[:4])

    # Detectar captcha
    captcha = page.locator("iframe[src*='captcha'], .g-recaptcha, #captcha")
    if await captcha.count() > 0:
        raise RuntimeError(
            "CAPTCHA detectado en Clave Única — login automático no posible"
        )

    # Ingresar RUT
    campo_rut = page.locator("input[name='run'], input[id='run'], input[name='rut']").first
    await campo_rut.wait_for(state="visible", timeout=PAGE_TIMEOUT)
    await campo_rut.fill(rut)

    # Ingresar contraseña
    campo_pass = page.locator("input[type='password']").first
    await campo_pass.wait_for(state="visible", timeout=PAGE_TIMEOUT)
    await campo_pass.fill(password)

    # Clic en botón de login
    boton_login = page.get_by_role("button", name="Iniciar sesión").or_(
        page.get_by_role("button", name="Ingresar")
    ).or_(
        page.locator("button[type='submit']")
    )
    await boton_login.first.click()

    logger.info("Credenciales enviadas — esperando redirección")

    # Esperar redirección de vuelta a SENCE
    try:
        await page.wait_for_url(
            "**/lce.sence.cl/**", timeout=PAGE_TIMEOUT
        )
    except Exception:
        # Verificar si hubo error de credenciales
        error_msg = page.locator(
            ".error-message, .alert-danger, .error, [class*='error']"
        )
        if await error_msg.count() > 0:
            texto = await error_msg.first.text_content()
            raise RuntimeError(f"Error de login Clave Única: {texto}")
        raise RuntimeError("Timeout esperando redirección post-login")

    await page.wait_for_load_state("networkidle", timeout=PAGE_TIMEOUT)
    logger.info("Login exitoso — redirigido a SENCE")
    return True


async def login_completo(page):
    """Ejecuta el flujo completo: abrir portal + login Clave Única.

    Reintenta hasta ``MAX_RETRIES_LOGIN`` veces si hay timeout.

    Returns
    -------
    bool
    """
    last_error = None

    for intento in range(MAX_RETRIES_LOGIN + 1):
        try:
            await abrir_portal(page)
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

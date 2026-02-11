"""Clase principal del scraper SENCE — coordina auth, navegación y descargas."""

import logging
from datetime import datetime
from pathlib import Path

from config import settings

logger = logging.getLogger(__name__)

MAX_RETRIES_DOWNLOAD = 3
WAIT_BETWEEN_DOWNLOADS = 3   # segundos
WAIT_BETWEEN_RETRIES = 10    # segundos


async def capture_error_screenshot(page, error_name, sence_id=None):
    """Captura screenshot cuando hay error para facilitar debugging."""
    screenshots_dir = settings.SCREENSHOTS_PATH
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"error_{error_name}_{sence_id or 'general'}_{timestamp}.png"
    filepath = screenshots_dir / filename

    try:
        await page.screenshot(path=str(filepath), full_page=True, timeout=15000)
        logger.error("Screenshot guardado: %s", filepath)
    except Exception as e:
        logger.error("No se pudo guardar screenshot: %s", e)


class SenceScraper:
    """Scraper completo de CSVs SENCE vía Playwright."""

    def __init__(self, headless=True):
        self.headless = headless
        self.playwright = None
        self.browser = None
        self.page = None

    async def start(self):
        """Inicia Playwright y crea el navegador."""
        from playwright.async_api import async_playwright
        from urllib.parse import urlparse

        self.playwright = await async_playwright().start()

        # Configurar proxy si está disponible
        launch_options = {"headless": self.headless}
        if settings.PROXY_URL:
            # Parsear URL del proxy para extraer credenciales y servidor
            parsed = urlparse(settings.PROXY_URL)
            proxy_config = {
                "server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
            }
            if parsed.username:
                proxy_config["username"] = parsed.username
            if parsed.password:
                proxy_config["password"] = parsed.password
            launch_options["proxy"] = proxy_config

        self.browser = await self.playwright.chromium.launch(**launch_options)
        context = await self.browser.new_context(
            accept_downloads=True,
            locale="es-CL",
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            extra_http_headers={
                "Accept-Language": "es-CL,es;q=0.9,en;q=0.8",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            },
        )
        self.page = await context.new_page()
        self.page.set_default_timeout(settings.SCRAPER_TIMEOUT)

        # Log con info del proxy (sin credenciales)
        proxy_info = ""
        if settings.PROXY_URL:
            # Extraer solo el host (sin credenciales)
            proxy_host = settings.PROXY_URL.split("@")[-1] if "@" in settings.PROXY_URL else settings.PROXY_URL
            proxy_host = proxy_host.replace("http://", "").replace("https://", "")
            proxy_info = f", proxy={proxy_host}"

        logger.info("Navegador iniciado (headless=%s, user-agent=Chrome/131%s)", self.headless, proxy_info)

    async def run(self, sence_ids):
        """Ejecuta el scraping completo para la lista de IDs SENCE.

        Parameters
        ----------
        sence_ids : list[str]
            IDs SENCE a descargar.

        Returns
        -------
        dict
            Reporte con ``descargados``, ``fallidos``, ``errores``.
        """
        from src.scraper.auth import login_completo
        from src.scraper.navigator import seleccionar_perfil, configurar_busqueda
        from src.scraper.downloader import descargar_curso, limpiar_busqueda

        report = {
            "descargados": [],
            "fallidos": [],
            "errores": [],
        }

        if not sence_ids:
            logger.warning("Lista de IDs SENCE vacía — nada que descargar")
            return report

        # ── Login ──────────────────────────────────────────
        try:
            await login_completo(self.page)
        except RuntimeError as e:
            msg = str(e)
            logger.error("Login fallido: %s", msg)
            await capture_error_screenshot(self.page, "login")
            report["errores"].append(f"Login: {msg}")
            return report

        # ── Selección de perfil ────────────────────────────
        try:
            await seleccionar_perfil(self.page)
        except Exception as e:
            msg = str(e)
            logger.error("Selección de perfil fallida: %s", msg)
            await capture_error_screenshot(self.page, "perfil")
            report["errores"].append(f"Selección perfil: {msg}")
            return report

        # ── Configurar búsqueda ────────────────────────────
        try:
            await configurar_busqueda(self.page)
        except Exception as e:
            msg = str(e)
            logger.error("Configuración de búsqueda fallida: %s", msg)
            await capture_error_screenshot(self.page, "busqueda")
            report["errores"].append(f"Config búsqueda: {msg}")
            return report

        # ── Descargar cada curso ───────────────────────────
        logger.info("Iniciando descarga de %d cursos SENCE", len(sence_ids))

        for idx, sence_id in enumerate(sence_ids, 1):
            logger.info(
                "── Curso %d/%d: SENCE %s ──", idx, len(sence_ids), sence_id
            )

            exito = False
            for intento in range(MAX_RETRIES_DOWNLOAD):
                try:
                    exito = await descargar_curso(self.page, sence_id)
                    if exito:
                        report["descargados"].append(sence_id)
                        break
                except Exception as e:
                    msg = f"SENCE {sence_id} intento {intento + 1}: {e}"
                    logger.warning(msg)

                    # Verificar si la sesión expiró
                    sesion_ok = await self._verificar_sesion()
                    if not sesion_ok:
                        logger.warning("Sesión expirada — reintentando login")
                        try:
                            await login_completo(self.page)
                            await seleccionar_perfil(self.page)
                            await configurar_busqueda(self.page)
                        except Exception as login_err:
                            report["errores"].append(
                                f"Re-login fallido: {login_err}"
                            )
                            # Abortar el resto
                            for remaining_id in sence_ids[idx:]:
                                report["fallidos"].append(remaining_id)
                            return report

                    if intento < MAX_RETRIES_DOWNLOAD - 1:
                        await self.page.wait_for_timeout(WAIT_BETWEEN_RETRIES * 1000)

            if not exito:
                report["fallidos"].append(sence_id)
                await capture_error_screenshot(self.page, "download", sence_id)

            # Re-configurar búsqueda para el siguiente curso.
            # Tras "Volver" desde DetalleAccion, la página resetea los
            # dropdowns (Línea / Criterio), así que hay que re-seleccionar
            # Franquicia + Curso antes de buscar el siguiente ID.
            if idx < len(sence_ids):
                await self.page.wait_for_timeout(WAIT_BETWEEN_DOWNLOADS * 1000)
                try:
                    await limpiar_busqueda(self.page)
                    await configurar_busqueda(self.page)
                except Exception as e:
                    logger.warning(
                        "Error re-configurando búsqueda: %s", e
                    )

        logger.info(
            "Scraping completado: %d descargados, %d fallidos",
            len(report["descargados"]),
            len(report["fallidos"]),
        )
        return report

    async def _verificar_sesion(self):
        """Verifica si la sesión SENCE sigue activa."""
        try:
            url = self.page.url
            # Si redirigió al login, la sesión expiró
            if "login" in url.lower() or "claveunica" in url.lower():
                return False
            return True
        except Exception:
            return False

    async def close(self):
        """Cierra sesión y navegador limpiamente."""
        if self.page:
            try:
                # Intentar cerrar sesión
                boton_logout = self.page.locator(
                    "a:has-text('Cerrar sesión'), a:has-text('Cerrar Sesión'), "
                    "a:has-text('Salir'), button:has-text('Cerrar sesión')"
                )
                if await boton_logout.count() > 0:
                    await boton_logout.first.click(timeout=5000)
                    logger.info("Sesión cerrada")
            except Exception:
                pass

        if self.browser:
            await self.browser.close()

        if self.playwright:
            await self.playwright.stop()

        logger.info("Navegador cerrado")

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
import json
import logging
import re
import tempfile
from datetime import datetime
from pathlib import Path

from config import settings

logger = logging.getLogger(__name__)

PAGE_TIMEOUT = settings.SCRAPER_TIMEOUT  # 90s
DOWNLOAD_TIMEOUT = 120000  # 120s para descargas (archivos pueden ser grandes)


async def descargar_curso(page, sence_id, output_dir=None, scrappear_dj=False):
    """Busca un curso, entra al detalle, y descarga el CSV de conectividad.

    Parameters
    ----------
    page : playwright.async_api.Page
    sence_id : str
    output_dir : Path | None
    scrappear_dj : bool
        Si True, además de descargar conectividad, scrapea la tabla de
        participantes para obtener el estado de Declaración Jurada (DJ).

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
    await link_estado.first.scroll_into_view_if_needed(timeout=PAGE_TIMEOUT)
    await page.wait_for_timeout(500)
    await link_estado.first.click(timeout=PAGE_TIMEOUT)

    await page.wait_for_load_state("networkidle", timeout=PAGE_TIMEOUT)
    await page.wait_for_timeout(2000)
    logger.info("SENCE %s: en página de detalle: %s", sence_id, page.url)

    # ── 3b. Extraer metadatos del curso (fecha, DJ OTEC, estado) ─
    metadatos = await _extraer_metadatos_curso(page, sence_id)
    if metadatos:
        _guardar_metadatos(sence_id, metadatos)

    # ── 4. Descargar Conectividad ────────────────────────
    btn_descargar = page.locator("input#Btn_DescargarConectividad")

    if await btn_descargar.count() > 0 and await btn_descargar.is_visible():
        try:
            # Scroll al botón para asegurar que sea visible y clickeable
            await btn_descargar.scroll_into_view_if_needed(timeout=PAGE_TIMEOUT)
            await page.wait_for_timeout(1000)

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
        # Scroll hacia abajo por si el botón está fuera de la vista
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(2000)

        # Re-buscar el botón después del scroll
        btn_descargar = page.locator("input#Btn_DescargarConectividad")
        if await btn_descargar.count() > 0 and await btn_descargar.is_visible():
            try:
                await btn_descargar.scroll_into_view_if_needed(timeout=PAGE_TIMEOUT)
                await page.wait_for_timeout(1000)

                async with page.expect_download(timeout=DOWNLOAD_TIMEOUT) as download_info:
                    await btn_descargar.click(timeout=PAGE_TIMEOUT)
                download = await download_info.value
                await download.save_as(str(destino))
                logger.info(
                    "SENCE %s: conectividad descargada tras scroll (%d bytes)",
                    sence_id, destino.stat().st_size,
                )
            except Exception as e:
                logger.warning(
                    "SENCE %s: descarga tras scroll falló (%s), scrapeando tabla",
                    sence_id, e,
                )
                scrapeado = await _scrappear_tabla_participantes(page, destino, sence_id)
                if not scrapeado:
                    destino.write_text("No hay datos disponibles!\n", encoding="utf-8")
        else:
            # Si definitivamente no hay botón, intentar scrappear la tabla
            logger.info("SENCE %s: sin botón Descargar Conectividad, scrapeando tabla", sence_id)
            scrapeado = await _scrappear_tabla_participantes(page, destino, sence_id)
            if not scrapeado:
                destino.write_text("No hay datos disponibles!\n", encoding="utf-8")

    # ── 5. Scrappear tabla de participantes para DJ (si solicitado) ─
    if scrappear_dj:
        dj_destino = output_dir / f"{sence_id}_dj.csv"
        dj_ok = await _scrappear_tabla_participantes(page, dj_destino, sence_id)
        if dj_ok:
            logger.info("SENCE %s: DJ scrapeada de tabla de participantes", sence_id)
        else:
            logger.warning("SENCE %s: no se pudo scrappear DJ de tabla", sence_id)

    # ── 6. Volver a la página de búsqueda ────────────────
    await _volver(page)

    return True


async def _extraer_metadatos_curso(page, sence_id):
    """Extrae metadatos del curso desde la página 'Detalle de Acción'.

    La página SENCE muestra los datos como pares label/valor en líneas
    consecutivas (cada label en su propia línea, valor en la siguiente).
    Se usa regex sobre el texto plano de la página para extraer los campos.

    Returns
    -------
    dict | None
        Metadatos extraídos o None si falla.
    """
    try:
        texto = await page.evaluate("""() => {
            const body = document.querySelector('body');
            return body ? body.innerText : '';
        }""")

        if not texto:
            logger.warning("SENCE %s: página sin texto para metadatos", sence_id)
            return None

        metadatos = {}

        # Fecha Inicio (línea siguiente al label)
        m = re.search(r'Fecha\s+Inicio\n(\d{2}/\d{2}/\d{4})', texto)
        if m:
            try:
                dt = datetime.strptime(m.group(1), "%d/%m/%Y")
                metadatos["fecha_inicio_sence"] = dt.strftime("%Y-%m-%d")
            except ValueError:
                pass

        # Fecha Término (línea siguiente al label)
        m = re.search(r'Fecha\s+T[eé]rmino\n(\d{2}/\d{2}/\d{4})', texto)
        if m:
            try:
                dt = datetime.strptime(m.group(1), "%d/%m/%Y")
                metadatos["fecha_termino_sence"] = dt.strftime("%Y-%m-%d")
            except ValueError:
                pass

        # Estado del Curso (línea siguiente al label)
        m = re.search(r'Estado\s+del\s+Curso\n(.+)', texto)
        if m:
            metadatos["estado_curso_sence"] = m.group(1).strip()

        # Modalidad del Curso (línea siguiente al label)
        m = re.search(r'Modalidad\s+del\s+Curso\n(.+)', texto)
        if m:
            metadatos["modalidad_curso_sence"] = m.group(1).strip()

        # Estado Declaración Jurada OTEC (línea siguiente al label)
        m = re.search(r'Estado\s+Declaraci[oó]n\s+Jurada\s+OTEC\n(.+)', texto)
        if m:
            metadatos["estado_dj_otec"] = m.group(1).strip()

        if metadatos:
            logger.info(
                "SENCE %s: metadatos — termino=%s, dj_otec=%s, estado=%s",
                sence_id,
                metadatos.get("fecha_termino_sence", "?"),
                metadatos.get("estado_dj_otec", "?"),
                metadatos.get("estado_curso_sence", "?"),
            )
        else:
            logger.warning("SENCE %s: no se encontraron metadatos en la página", sence_id)

        return metadatos if metadatos else None

    except Exception as e:
        logger.warning("SENCE %s: error extrayendo metadatos: %s", sence_id, e)
        return None


def _guardar_metadatos(sence_id, metadatos):
    """Actualiza metadatos_sence.json con los datos extraídos de un curso.

    Usa escritura atómica (archivo temporal + rename) para evitar corrupción.
    """
    ruta = settings.SENCE_METADATOS_PATH
    ruta.parent.mkdir(parents=True, exist_ok=True)

    # Leer existente
    datos = {}
    if ruta.exists():
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Error leyendo metadatos existentes: %s", e)

    # Actualizar entrada del curso
    metadatos["ultima_actualizacion"] = datetime.now().isoformat(timespec="seconds")
    datos[sence_id] = metadatos

    # Escritura atómica
    try:
        fd, tmp_path = tempfile.mkstemp(
            dir=str(ruta.parent), suffix=".tmp", prefix="metadatos_"
        )
        with open(fd, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False, indent=2)
        Path(tmp_path).replace(ruta)
        logger.debug("Metadatos SENCE %s guardados en %s", sence_id, ruta)
    except Exception as e:
        logger.error("Error guardando metadatos SENCE: %s", e)
        # Limpieza del temporal si existe
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass


async def _scrappear_tabla_participantes(page, destino, sence_id):
    """Extrae datos de la tabla 'Listado de Participantes' en DetalleAccion."""
    # Asegurar que la tabla muestre TODOS los participantes en una sola
    # página. El portal pagina de a 10 por defecto; sin esto, los alumnos de
    # RUT más alto quedan en la página 2+ y nunca se capturan, apareciendo
    # con DJ "Pendiente" pese a tenerla emitida.
    await _seleccionar_max_por_pagina(page, sence_id)

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

    # ── Punto de control: nº de filas leídas vs total del portal ──
    # El paginador muestra "Mostrando registros 1 a X de N". Si leímos menos
    # de N, hubo truncamiento (falló el ajuste de 'Registros por página').
    total = await _leer_total_participantes(page)
    if total is not None and len(registros) < total:
        logger.warning(
            "SENCE %s: tabla de participantes INCOMPLETA — %d filas leídas "
            "de %d totales en el portal. Revisar paginación.",
            sence_id, len(registros), total,
        )
    else:
        sufijo = f" de {total} totales" if total is not None else ""
        logger.info(
            "SENCE %s: tabla scrapeada (%d registros%s)",
            sence_id, len(registros), sufijo,
        )
    return True


async def _seleccionar_max_por_pagina(page, sence_id):
    """Ajusta el selector 'Registros por página' al máximo disponible.

    La tabla de participantes del portal SENCE pagina de a 10 por defecto y
    expone un ``<select>`` (sin id/name) con opciones 10/25/50/100/250/500.
    Se elige la opción numérica más alta para mostrar a todos los alumnos en
    una sola página y evitar el truncamiento a la primera página.

    Returns
    -------
    bool
        ``True`` si se ajustó el tamaño de página.
    """
    try:
        selects = page.locator("select")
        for i in range(await selects.count()):
            sel = selects.nth(i)
            try:
                if not await sel.is_visible():
                    continue
            except Exception:
                continue

            opciones = [
                (v or "").strip()
                for v in await sel.locator("option").all_text_contents()
            ]
            numericas = [v for v in opciones if v.isdigit()]

            # El selector de tamaño de página empieza en "10" (10/25/50/100/…).
            # El de 'Ir a página' empieza en "1" (y en cursos grandes podría
            # llegar a tener un "10"), así que se excluye si contiene "1".
            if "10" in numericas and "1" not in numericas and len(numericas) >= 2:
                objetivo = max(numericas, key=int)  # mayor disponible (ej. 500)
                await sel.select_option(label=objetivo)
                # El cambio dispara postback/AJAX: esperar el re-render.
                try:
                    await page.wait_for_load_state("networkidle", timeout=PAGE_TIMEOUT)
                except Exception:
                    pass
                await page.wait_for_timeout(1500)
                logger.info(
                    "SENCE %s: 'Registros por página' ajustado a %s",
                    sence_id, objetivo,
                )
                return True

        logger.debug(
            "SENCE %s: no se encontró selector 'Registros por página'", sence_id
        )
        return False
    except Exception as e:
        logger.warning(
            "SENCE %s: no se pudo ajustar 'Registros por página': %s",
            sence_id, e,
        )
        return False


async def _leer_total_participantes(page):
    """Lee el total de participantes del paginador del portal.

    Busca el texto 'Mostrando registros 1 a X de N' y retorna N.

    Returns
    -------
    int | None
        Total de participantes según el portal, o ``None`` si no se encontró.
    """
    try:
        cuerpo = await page.evaluate(
            "() => document.body ? document.body.innerText : ''"
        )
        m = re.search(
            r"Mostrando\s+registros?\s+\d+\s+a\s+\d+\s+de\s+(\d+)",
            cuerpo or "",
            re.IGNORECASE,
        )
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return None


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

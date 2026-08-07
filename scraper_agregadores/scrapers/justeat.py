import logging
import re

from scrapers.base import BaseAggregatorScraper, ResultadoChequeo

logger = logging.getLogger(__name__)

BASE_URL = "https://www.just-eat.es"

SEL_COOKIE_ACCEPT_NECESSARY = 'button:has-text("Sólo necesarias")'

# La barra de dirección tiene distintos data-qa según esté enfocada o no; el prefijo cubre ambos.
SEL_ADDRESS_INPUT = '[data-qa^="location-panel-search-input-address-element"]'
SEL_ADDRESS_CHANGE_BUTTON = '[data-qa="header-location"]'
SEL_ADDRESS_SUGGESTION = '[data-qa="location-panel-results-item-element"]'

# Cuando la dirección no tiene número de portal (una rotonda, una carretera, un
# punto del grid sin dirección exacta), tras elegir la sugerencia JustEat mete un
# segundo modal pidiendo el número de edificio antes de dejar seguir -- si no se
# rellena, la barra de búsqueda normal nunca aparece y el chequeo revienta como
# si fuera un fallo técnico cuando en realidad la zona sí tiene cobertura.
SEL_BUILDING_INPUT = 'input[placeholder*="edificio"]'
SEL_BUILDING_CONFIRM = 'button:has-text("Confirmar dirección")'

# La página "de área" a la que redirige cuando se confirma sin portal exacto ya
# trae el buscador como <input> visible directamente -- no pasa por la barra
# "readonly" intermedia que sí usa la página de dirección exacta.
SEL_SEARCH_INPUT_DIRECTO = '[data-qa^="restaurant-list-search-element"]:visible'

SEL_SEARCH_READONLY = '[data-qa="aggregation-options-search-element-readonly"]'
SEL_SEARCH_INPUT = '[data-qa^="restaurant-list-search-element"]'
SEL_SEARCH_SUGGESTION = '[data-qa="search-autocomplete-list-list-item"]'

# JustEat dejó de ofrecer casi siempre una sugerencia directa con el nombre de
# la marca (SEL_SEARCH_SUGGESTION de arriba, que ahora está desactualizado --
# confirmado con logs/screenshots/*_tienda_no_confirmada_*.html: solo aparecía
# este botón genérico). Hay que pulsarlo para llegar a una página de
# resultados de verdad, donde SÍ aparece la tarjeta real de la tienda
# (confirmado con investigar_justeat.py).
SEL_SEE_ALL_BUTTON = 'button:has-text("Ver todas las opciones")'
SEL_RESULT_CARD_NAME = '[data-qa="restaurant-info-name"]'

# Estado "sin resultados" explícito y definitivo de JustEat (mensaje "No hemos
# encontrado 'Krispy Kreme'") -- aparece cuando la búsqueda SÍ se ejecutó pero
# no hay ningún restaurante que encaje, sin necesidad de que además haya otras
# tarjetas visibles (confirmado con capturas reales: esto se estaba tratando
# como fallo técnico y reintentando 4 veces en vano).
SEL_SIN_RESULTADOS = '[data-qa="restaurant-list-empty"]'

SEL_DELIVERY_INPUT = 'input[value="delivery"][data-qa^="service-type-switcher-item-element"]'
SEL_DELIVERY_TEXT = '[data-qa="service-type-switcher-delivery-availability-text"]'

# JustEat nombra las sucursales sin el espacio del nombre oficial (p.ej. "Parquesur" vs
# "Parque Sur"), así que buscamos solo por la marca y no por el nombre completo de la tienda.
MARCA_BUSQUEDA = "Krispy Kreme"


class JustEatScraper(BaseAggregatorScraper):
    nombre_agregador = "justeat"
    url_base = BASE_URL

    async def _verificar(self, page, tienda_nombre: str, direccion: str) -> ResultadoChequeo:
        await page.goto(BASE_URL, wait_until="domcontentloaded")
        await self._comprobar_challenge(page)

        await self._aceptar_cookies(page)
        await self._establecer_direccion(page, direccion)

        # El banner de cookies puede tardar en aparecer (analítica/consentimiento
        # cargando en diferido) y no estar listo todavía en el primer intento de
        # _aceptar_cookies -- si aparece justo después, se queda tapando la lista
        # de sugerencias de _buscar_tienda y el selector nunca la ve (confirmado
        # con capturas: banner de cookies visible en el fallo, resultados vacíos
        # debajo). Se repite aquí, justo antes de buscar, por si acaba de aparecer.
        await self._aceptar_cookies(page, timeout_ms=2500)

        encontrado = await self._buscar_tienda(page)
        if not encontrado:
            return ResultadoChequeo(
                disponible=False,
                mensaje_bloqueo="Tienda no aparece en resultados de búsqueda para esta dirección",
                status_http=200,
            )

        return await self._leer_disponibilidad(page)

    async def _aceptar_cookies(self, page, timeout_ms: int = 5000):
        try:
            boton = page.locator(SEL_COOKIE_ACCEPT_NECESSARY).first
            await boton.wait_for(state="visible", timeout=timeout_ms)
            await boton.click()
        except Exception:
            pass

    async def _establecer_direccion(self, page, direccion: str):
        # Si ya hay una dirección puesta (sesión con caché), el control está arriba a la
        # izquierda y hay que abrir el panel antes de que aparezca el input.
        try:
            boton_cambiar = page.locator(SEL_ADDRESS_CHANGE_BUTTON).first
            if await boton_cambiar.is_visible(timeout=3000):
                await boton_cambiar.click()
        except Exception:
            pass

        campo = page.locator(SEL_ADDRESS_INPUT).first
        await campo.click(force=True)
        await campo.fill(direccion)

        try:
            sugerencia = page.locator(SEL_ADDRESS_SUGGESTION).first
            await sugerencia.wait_for(state="visible", timeout=15000)
            await sugerencia.click(force=True)
        except Exception:
            # Diagnóstico: sin esto no hay forma de ver qué pasaba en pantalla
            # cuando la sugerencia nunca aparece -- ¿la dirección de verdad no
            # tiene cobertura, o es un fallo de carga real? La excepción sigue
            # subiendo igual (no cambia el resultado), solo se deja constancia.
            ruta = await self.screenshot_on_error(page, "direccion_sin_sugerencia")
            logger.warning("justeat: sin sugerencia de dirección para '%s' -- captura: %s", direccion, ruta)
            raise

        await page.wait_for_load_state("domcontentloaded")

        # Direcciones sin portal exacto (rotondas, carreteras, puntos del grid)
        # disparan un segundo modal pidiendo el número de edificio antes de
        # dejar avanzar. Cualquier valor sirve -- solo hace falta cerrar el
        # modal para llegar a los resultados de la zona.
        try:
            campo_edificio = page.locator(SEL_BUILDING_INPUT).first
            await campo_edificio.wait_for(state="visible", timeout=3000)
        except Exception:
            campo_edificio = None

        if campo_edificio is not None:
            # El banner de cookies a veces reaparece justo aquí y tapa el
            # botón de confirmar -- hay que volver a cerrarlo antes de tocar
            # el modal.
            await self._aceptar_cookies(page)
            try:
                await campo_edificio.fill("1", force=True)
                await page.locator(SEL_BUILDING_CONFIRM).first.click(force=True)
                await page.wait_for_load_state("domcontentloaded")
            except Exception as exc:
                logger.warning("justeat: fallo rellenando modal de edificio: %s", exc)

    async def _buscar_tienda(self, page) -> bool:
        # Hay dos layouts distintos según cómo se resolvió la dirección: la
        # página de dirección exacta muestra una barra "readonly" que hay que
        # pulsar para que aparezca el input de verdad; la página "de área"
        # (direcciones sin portal, ver _establecer_direccion) ya trae el
        # input de búsqueda visible directamente, sin barra intermedia.
        campo_readonly = page.locator(SEL_SEARCH_READONLY)
        campo_directo = page.locator(SEL_SEARCH_INPUT_DIRECTO)
        try:
            await campo_readonly.or_(campo_directo).first.wait_for(state="visible", timeout=8000)
        except Exception:
            ruta = await self.screenshot_on_error(page, "sin_buscador")
            logger.warning("justeat: sin buscador de tienda, url=%s -- captura: %s", page.url, ruta)
            raise

        if await campo_readonly.first.is_visible():
            await campo_readonly.first.click(force=True)

        campo_busqueda = page.locator(SEL_SEARCH_INPUT).first
        await campo_busqueda.fill(MARCA_BUSQUEDA)

        sugerencia = page.locator(f'{SEL_SEARCH_SUGGESTION}:has-text("{MARCA_BUSQUEDA}")').first
        try:
            await sugerencia.wait_for(state="visible", timeout=8000)
            await sugerencia.click()
            await page.wait_for_load_state("domcontentloaded")
            return True
        except Exception:
            pass  # sigue abajo con el camino "ver todas las opciones"

        # Casi nunca aparece ya la sugerencia directa de arriba -- en su lugar
        # sale un botón genérico "Ver todas las opciones" que lleva a una
        # página de resultados de verdad, con tarjetas de restaurante reales.
        boton_ver_todas = page.locator(SEL_SEE_ALL_BUTTON).first
        try:
            await boton_ver_todas.wait_for(state="visible", timeout=3000)
            await boton_ver_todas.click()
            await page.wait_for_load_state("domcontentloaded")
        except Exception:
            ruta = await self.screenshot_on_error(page, "tienda_no_confirmada")
            ruta_html = await self.guardar_html_debug(page, "tienda_no_confirmada")
            logger.warning(
                "justeat: sin sugerencia ni botón 'ver todas', url=%s -- captura: %s -- html: %s",
                page.url,
                ruta,
                ruta_html,
            )
            raise TimeoutError("justeat: tienda no confirmada en resultados de búsqueda (ver captura)")

        return await self._confirmar_tarjeta(page)

    async def _confirmar_tarjeta(self, page) -> bool:
        # Busca la tarjeta real de Krispy Kreme (tras pulsar 'ver todas las
        # opciones') y la pulsa. Igual que en Glovo (ver scrapers/glovo.py):
        # si no aparece pero SÍ hay otras tarjetas de restaurante (la
        # búsqueda funcionó de verdad), es una señal fiable de que no
        # reparte ahí -- no un fallo técnico. Solo se trata como fallo
        # técnico si no hay ninguna tarjeta en absoluto NI el mensaje
        # explícito de "sin resultados" (ver más abajo).
        tarjeta = page.locator(f'{SEL_RESULT_CARD_NAME}:has-text("{MARCA_BUSQUEDA}")').first
        try:
            await tarjeta.wait_for(state="visible", timeout=8000)
        except Exception:
            total_tarjetas = await page.locator(SEL_RESULT_CARD_NAME).count()
            if total_tarjetas > 0:
                logger.info(
                    "justeat: Krispy Kreme no aparece entre %d resultados en %s -- no reparte aquí.",
                    total_tarjetas,
                    page.url,
                )
                return False

            # JustEat también puede confirmar "sin resultados" con un mensaje
            # explícito ("No hemos encontrado 'Krispy Kreme'") sin mostrar
            # ninguna otra tarjeta -- confirmado con capturas reales: esto se
            # trataba como fallo técnico y se reintentaba 4 veces en vano
            # cuando en realidad JustEat ya había respondido con seguridad.
            try:
                sin_resultados = page.locator(SEL_SIN_RESULTADOS).first
                if await sin_resultados.is_visible(timeout=2000):
                    logger.info(
                        "justeat: JustEat confirma 'sin resultados' para esta búsqueda en %s -- no reparte aquí.",
                        page.url,
                    )
                    return False
            except Exception:
                pass

            ruta = await self.screenshot_on_error(page, "tienda_no_confirmada")
            ruta_html = await self.guardar_html_debug(page, "tienda_no_confirmada")
            logger.warning(
                "justeat: tienda no confirmada (sin ninguna tarjeta), url=%s -- captura: %s -- html: %s",
                page.url,
                ruta,
                ruta_html,
            )
            raise TimeoutError("justeat: tienda no confirmada en resultados de búsqueda (ver captura)")

        await tarjeta.click()
        await page.wait_for_load_state("domcontentloaded")
        return True

    async def _leer_disponibilidad(self, page) -> ResultadoChequeo:
        try:
            delivery_input = page.locator(SEL_DELIVERY_INPUT).first
            await delivery_input.wait_for(state="attached", timeout=10000)
            disabled = await delivery_input.get_attribute("disabled")

            texto_disponibilidad = ""
            try:
                texto_disponibilidad = await page.locator(SEL_DELIVERY_TEXT).first.inner_text(
                    timeout=5000
                )
            except Exception:
                pass

            disponible = disabled is None and "no disponible" not in texto_disponibilidad.lower()

            tiempo_entrega_min = None
            numeros = re.findall(r"\d+", texto_disponibilidad)
            if numeros and "min" in texto_disponibilidad.lower():
                tiempo_entrega_min = int(numeros[-1])

            return ResultadoChequeo(
                disponible=disponible,
                tiempo_entrega_min=tiempo_entrega_min,
                mensaje_bloqueo=None if disponible else (texto_disponibilidad or "No disponible"),
                status_http=200,
            )
        except Exception as exc:
            logger.error("Error leyendo disponibilidad JustEat: %s", exc)
            screenshot = await self.screenshot_on_error(page, "error_lectura")
            return ResultadoChequeo(
                disponible=False,
                error_texto=str(exc),
                url_captura=screenshot,
            )

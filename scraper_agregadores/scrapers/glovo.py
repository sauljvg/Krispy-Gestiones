import json
import logging
import re
import urllib.parse

from scrapers.base import BaseAggregatorScraper, PaginaSobrecargadaError, ResultadoChequeo, _pagina_muestra_error_generico

logger = logging.getLogger(__name__)

# URL con localización fija a Madrid en español -- antes se usaba la raíz
# (https://glovoapp.com), que según sesión/geolocalización del navegador
# devolvía la interfaz en inglés (pedido explícito del usuario 26/08: usar
# la web en español). Todas las tiendas están en Madrid (config.TIENDAS_SCHEDULER),
# así que fijar la ciudad en la URL no pierde cobertura.
URL_INICIO = "https://glovoapp.com/es/es/madrid"

SEL_COOKIE_DENY = 'button:has-text("Denegar")'

SEL_ADDRESS_CHANGE_BUTTON = 'button[class*="AddressPicker_addressButton"]'
# El input inicial (home) es readonly: al pulsarlo abre un panel con el input real editable.
SEL_ADDRESS_OPENER = 'input[placeholder="¿Cuál es tu dirección?"]:visible'
SEL_ADDRESS_EDITABLE_INPUT = 'input[data-testid="address-book-search-input"]'
SEL_ADDRESS_SUGGESTION = 'div[class*="ListItem_pintxo-list-item"]'

SEL_PLACE_TYPE_OTHER = 'button:has-text("Otro")'
SEL_CONFIRM_BUTTON = 'button:has-text("Confirmar")'

SEL_SEARCH_INPUT = 'input[placeholder="¿Qué necesitas?"]'
SEL_SEARCH_BUTTON = 'button:has-text("Buscar")'
SEL_STORE_CARD = 'a[class*="StoreTile_wrapper"]'

SEL_STORE_ETA_TEXT = '[class*="StoreEta_text"]'

MARCA_BUSQUEDA = "Krispy Kreme"


class GlovoScraper(BaseAggregatorScraper):
    nombre_agregador = "glovo"
    url_base = URL_INICIO

    async def _verificar(
        self, page, tienda_nombre: str, direccion: str,
        lat: float | None = None, lng: float | None = None,
    ) -> ResultadoChequeo:
        # 27/08: se probó un atajo con la cookie glovo_delivery_address (ver
        # _verificar_via_cookie, se deja el código documentado por si se retoma)
        # para saltarse el flujo de interfaz de la dirección -- confirmado en un
        # navegador YA con sesión establecida que funciona, pero en 4 pruebas
        # reales seguidas con un Playwright recién arrancado (sin el historial de
        # sesión/dispositivo que acumula una sesión de verdad) la página de
        # resultados se queda vacía siempre, ni con más tiempo de espera se
        # arregla. Descartado por ahora -- vuelta al flujo de interfaz de
        # siempre, que es el que de verdad funciona.
        await page.goto(URL_INICIO, wait_until="domcontentloaded")
        await self._comprobar_challenge(page)
        await self._aceptar_cookies(page)
        await self._establecer_direccion(page, direccion)
        encontrado = await self._buscar_tienda(page)

        if not encontrado:
            return ResultadoChequeo(
                disponible=False,
                mensaje_bloqueo="Tienda no aparece en resultados de búsqueda para esta dirección",
                status_http=200,
            )

        # Glovo solo lista tiendas que reparten en la dirección buscada -- que la
        # tarjeta de Krispy Kreme aparezca en los resultados de _buscar_tienda YA es
        # la señal real de disponibilidad. La lectura de "cerrado"/ETA de la página
        # de la tienda es poco fiable (texto de otras tiendas recomendadas, avisos
        # genéricos, etc. producían falsos "no disponible" con la tienda repartiendo
        # de verdad), así que ahora solo se usa para el dato informativo del tiempo
        # de entrega, nunca para decidir disponible/no disponible.
        return await self._leer_tiempo_entrega(page)

    async def _verificar_via_cookie(self, page, direccion: str, lat: float, lng: float) -> bool:
        """Atajo (27/08, confirmado en vivo con el navegador): Glovo guarda la
        dirección de entrega en una cookie de cliente en texto plano
        (`glovo_delivery_address`, un JSON con lat/lng), no la resuelve contra
        Google Places en el servidor -- se puede escribir directamente sin pasar
        por el flujo de interfaz de "escribir -> esperar sugerencias -> elegir tipo
        de lugar -> confirmar" (~7 pasos, cada uno un punto más de fallo). Con la
        cookie puesta, ir derecho a la URL de búsqueda con la marca en `?q=` hace
        lo mismo que rellenar el buscador a mano -- confirmado que da el resultado
        correcto tanto para una dirección con cobertura como para una sin ella.
        placeId/isVerified van con un valor cualquiera -- confirmado que el
        backend no los valida contra Google, solo lee lat/lng."""
        valor_cookie = json.dumps(
            {
                "latitude": lat,
                "longitude": lng,
                "cityCode": "MAD",
                "countryCode": "ES",
                "cityName": "Madrid",
                "text": direccion,
                "details": "",
                "placeId": "",
                "isVerified": True,
                "postalCode": None,
            },
            separators=(",", ":"),
        )
        # Doble percent-encoding -- así es como lo escribe la propia web (confirmado
        # inspeccionando document.cookie en vivo), no un capricho nuestro.
        valor_doble_encoded = urllib.parse.quote(urllib.parse.quote(valor_cookie, safe=""), safe="")

        # Visitar la home ANTES de poner la cookie de dirección -- una sesión
        # arrancando en frío directo en /search, sin las cookies de sesión/
        # dispositivo que la propia web pone en la primera visita (device id,
        # A/B, etc.), no llegó a mostrar ninguna tarjeta en la prueba real 28/08
        # (probablemente su lógica de fetch en cliente depende de ese estado).
        # Sale más caro que el atajo puro pero sigue ahorrando los ~7 pasos del
        # flujo de dirección (escribir, esperar sugerencias, hover, click, tipo
        # de lugar, confirmar).
        await page.goto(URL_INICIO, wait_until="domcontentloaded")
        await self._comprobar_challenge(page)
        await self._aceptar_cookies(page)
        await page.wait_for_timeout(3000)  # prueba: dar tiempo a init async (Incognia, etc.)

        await page.context.add_cookies(
            [{"name": "glovo_delivery_address", "value": valor_doble_encoded, "domain": "glovoapp.com", "path": "/"}]
        )

        url_busqueda = f"{URL_INICIO}/search?q={urllib.parse.quote(MARCA_BUSQUEDA)}"
        await page.goto(url_busqueda, wait_until="networkidle")
        await self._comprobar_challenge(page)
        await page.wait_for_timeout(5000)  # prueba: dar mas tiempo al fetch de resultados en cliente

        return await self._esperar_y_abrir_tarjeta(page)

    async def _click_js(self, locator):
        """Click vía JS: el click sintético de Playwright no siempre dispara el handler
        de estos componentes React (posible carrera con el cierre por blur del input)."""
        await locator.evaluate("e => e.click()")

    async def _aceptar_cookies(self, page):
        try:
            boton = page.locator(SEL_COOKIE_DENY).first
            await boton.wait_for(state="visible", timeout=8000)
            await boton.click()
        except Exception:
            pass

    async def _esperar_sugerencias_estables(self, page, intentos_max=10):
        """El autocompletado de Google es asíncrono/debounced: la lista de sugerencias
        cambia varias veces tras el fill(). Sondeamos hasta que el texto de la primera
        sugerencia deja de cambiar entre dos lecturas consecutivas."""
        anterior = None
        for _ in range(intentos_max):
            try:
                sugerencia = page.locator(SEL_ADDRESS_SUGGESTION + ":visible").first
                await sugerencia.wait_for(state="visible", timeout=3000)
                actual = await sugerencia.inner_text()
            except Exception:
                actual = None

            if actual and actual == anterior:
                return
            anterior = actual
            await page.wait_for_timeout(400)

    async def _seleccionar_primera_sugerencia(self, page):
        await self._esperar_sugerencias_estables(page)

        # La lista solo activa la selección tras un evento de hover real (estado
        # "activeIndex" en React): un click directo sin hover previo no navega.
        for intento in range(3):
            sugerencia = page.locator(SEL_ADDRESS_SUGGESTION + ":visible").first
            await sugerencia.wait_for(state="visible", timeout=10000)
            await sugerencia.hover()
            await page.wait_for_timeout(300)
            await sugerencia.click(timeout=5000)

            try:
                await page.locator(
                    f"{SEL_PLACE_TYPE_OTHER}, {SEL_SEARCH_INPUT}"
                ).first.wait_for(state="visible", timeout=4000)
                return
            except Exception:
                continue

    async def _establecer_direccion(self, page, direccion: str):
        abrio_panel = False
        try:
            boton_cambiar = page.locator(SEL_ADDRESS_CHANGE_BUTTON).first
            if await boton_cambiar.is_visible(timeout=3000):
                await boton_cambiar.click()
                abrio_panel = True
        except Exception:
            pass

        if not abrio_panel:
            abridor = page.locator(SEL_ADDRESS_OPENER).first
            try:
                await abridor.click(force=True)
            except Exception:
                # Ni el botón de cambiar dirección ni este input inicial aparecieron --
                # la home de Glovo no cargó el layout esperado en absoluto (visto en
                # vivo 26/08: ~29% de fallos en una vuelta completa con 20 workers a la
                # vez). Captura ambas cosas ANTES de relanzar -- si no se guarda aquí,
                # se pierde: el reintento siguiente abre una page/browser nuevos.
                ruta = await self.screenshot_on_error(page, "sin_campo_direccion")
                ruta_html = await self.guardar_html_debug(page, "sin_campo_direccion")
                logger.warning(
                    "glovo: no aparece ni el botón de cambiar dirección ni el campo inicial de "
                    "dirección -- captura: %s -- html: %s",
                    ruta, ruta_html,
                )
                # Antes de asumir un fallo genérico, comprobar si es LA PÁGINA la que
                # se cayó (confirmado en vivo 27/08, ver PaginaSobrecargadaError) --
                # cambia el backoff del reintento en base.py, mucho más largo que el
                # de un fallo normal.
                if await _pagina_muestra_error_generico(page):
                    raise PaginaSobrecargadaError("glovo") from None
                raise

        campo = page.locator(SEL_ADDRESS_EDITABLE_INPUT).first
        await campo.wait_for(state="visible", timeout=10000)
        await campo.fill(direccion)

        await self._seleccionar_primera_sugerencia(page)

        # Paso opcional: "What kind of place is this?" (solo en direcciones nuevas)
        try:
            boton_other = page.locator(SEL_PLACE_TYPE_OTHER).first
            if await boton_other.is_visible(timeout=5000):
                await self._click_js(boton_other)
        except Exception:
            pass

        # Paso opcional: confirmar detalles de dirección
        try:
            boton_confirmar = page.locator(SEL_CONFIRM_BUTTON).first
            if await boton_confirmar.is_visible(timeout=5000):
                await self._click_js(boton_confirmar)
        except Exception:
            pass

        await page.wait_for_load_state("domcontentloaded")

    async def _buscar_tienda(self, page) -> bool:
        campo_busqueda = page.locator(SEL_SEARCH_INPUT).first
        await campo_busqueda.wait_for(state="visible", timeout=15000)
        await campo_busqueda.click(force=True)
        await campo_busqueda.fill(MARCA_BUSQUEDA)

        boton_buscar = page.locator(SEL_SEARCH_BUTTON).first
        await boton_buscar.click(force=True)

        return await self._esperar_y_abrir_tarjeta(page)

    async def _esperar_y_abrir_tarjeta(self, page) -> bool:
        """Parte común a las dos formas de llegar a los resultados de búsqueda
        (rellenar el buscador a mano en _buscar_tienda, o ir directo a la URL con
        ?q=... en _verificar cuando hay lat/lng -- ver ese método): esperar la
        tarjeta de la tienda y abrirla. Separado de _buscar_tienda el 27/08 para
        no duplicar esta lógica entre las dos rutas."""
        tarjeta = page.locator(f'{SEL_STORE_CARD}:has-text("{MARCA_BUSQUEDA}")').first
        try:
            await tarjeta.wait_for(state="visible", timeout=8000)
        except Exception:
            # Antes de asumir fallo técnico: si SÍ hay otras tiendas listadas, la
            # búsqueda funcionó de verdad (página cargada, resultados reales) y
            # Krispy Kreme simplemente no está entre ellas -- confirmado con un
            # HTML de diagnóstico real (14 tarjetas de otras tiendas, ninguna de
            # Krispy Kreme). Ahí sí es un "no disponible" fiable, no ambiguo.
            # Solo se trata como fallo técnico (con reintentos, ver
            # _verificar_con_retry) cuando no hay NINGUNA tarjeta -- eso sí puede
            # ser una carga rota/a medias, mismo motivo que en Uber Eats.
            total_tarjetas = await page.locator(SEL_STORE_CARD).count()
            if total_tarjetas > 0:
                logger.info(
                    "glovo: Krispy Kreme no aparece entre %d tiendas listadas en %s -- no reparte aquí.",
                    total_tarjetas,
                    page.url,
                )
                return False

            ruta = await self.screenshot_on_error(page, "tienda_no_confirmada")
            ruta_html = await self.guardar_html_debug(page, "tienda_no_confirmada")
            logger.warning(
                "glovo: tienda no confirmada en resultados de búsqueda (sin ninguna tarjeta), url=%s -- captura: %s -- html: %s",
                page.url,
                ruta,
                ruta_html,
            )
            raise TimeoutError("glovo: tienda no confirmada en resultados de búsqueda (ver captura)")

        await self._click_js(tarjeta)
        await page.wait_for_load_state("domcontentloaded")
        return True

    async def _leer_tiempo_entrega(self, page) -> ResultadoChequeo:
        # Llegar aquí ya significa disponible=True (ver comentario en _verificar:
        # que la tarjeta apareciera en la búsqueda ya es la señal real). Un fallo
        # leyendo el ETA es solo la pérdida de un dato informativo, nunca motivo
        # para marcar la tienda como no disponible ni como error técnico.
        texto_eta = ""
        for _ in range(5):
            try:
                texto_eta = await page.locator(SEL_STORE_ETA_TEXT).first.inner_text(timeout=2000)
                if texto_eta:
                    break
            except Exception:
                pass
            await page.wait_for_timeout(1000)

        tiempo_entrega_min = None
        numeros = re.findall(r"\d+", texto_eta)
        if numeros:
            tiempo_entrega_min = int(numeros[-1])

        return ResultadoChequeo(
            disponible=True,
            tiempo_entrega_min=tiempo_entrega_min,
            status_http=200,
        )

import re

from scrapers.base import BaseAggregatorScraper, ResultadoChequeo

BASE_URL = "https://glovoapp.com"

SEL_COOKIE_DENY = 'button:has-text("Deny")'

SEL_ADDRESS_CHANGE_BUTTON = 'button[class*="AddressPicker_addressButton"]'
# El input inicial (home) es readonly: al pulsarlo abre un panel con el input real editable.
SEL_ADDRESS_OPENER = 'input[placeholder="What'"'"'s your address?"]:visible'
SEL_ADDRESS_EDITABLE_INPUT = 'input[data-testid="address-book-search-input"]'
SEL_ADDRESS_SUGGESTION = 'div[class*="ListItem_pintxo-list-item"]'

SEL_PLACE_TYPE_OTHER = 'button:has-text("Other")'
SEL_CONFIRM_BUTTON = 'button:has-text("Confirm")'

SEL_SEARCH_INPUT = 'input[placeholder="What can we get you?"]'
SEL_SEARCH_BUTTON = 'button:has-text("Search")'
SEL_STORE_CARD = 'a[class*="StoreTile_wrapper"]'

SEL_STORE_ETA_TEXT = '[class*="StoreEta_text"]'

MARCA_BUSQUEDA = "Krispy Kreme"


class GlovoScraper(BaseAggregatorScraper):
    nombre_agregador = "glovo"
    url_base = BASE_URL

    async def _verificar(self, page, tienda_nombre: str, direccion: str) -> ResultadoChequeo:
        await page.goto(BASE_URL, wait_until="domcontentloaded")
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
            await abridor.click(force=True)

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

        tarjeta = page.locator(f'{SEL_STORE_CARD}:has-text("{MARCA_BUSQUEDA}")').first
        try:
            await tarjeta.wait_for(state="visible", timeout=8000)
        except Exception:
            return False

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

import logging
import re

from scrapers.base import BaseAggregatorScraper, ResultadoChequeo

logger = logging.getLogger(__name__)

BASE_URL = "https://www.ubereats.com"

SEL_COOKIE_REJECT = 'button:has-text("Rechazar")'

SEL_ADDRESS_INPUT = "#location-typeahead-home-input"
SEL_ADDRESS_SUGGESTION = '[id^="location-typeahead-home-item-"]'
SEL_BUSCAR_COMIDA_BUTTON = 'button:has-text("Buscar comida")'

SEL_SEARCH_INPUT = 'input[placeholder*="Buscar en Uber"]'
SEL_STORE_LINK = 'a[href*="/store/"]'

SEL_MODALITY_DELIVERY = '[data-testid="modality-option-DELIVERY"]'

MARCA_BUSQUEDA = "Krispy Kreme"


class UberEatsScraper(BaseAggregatorScraper):
    nombre_agregador = "ubereats"
    url_base = BASE_URL

    # Cloudflare bloquea Chromium headless en este sitio incluso con stealth aplicado,
    # pero deja pasar una ventana visible sin intervención humana.
    iniciar_headless = False

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

        return await self._leer_disponibilidad(page)

    async def _aceptar_cookies(self, page):
        try:
            boton = page.locator(SEL_COOKIE_REJECT).first
            await boton.wait_for(state="visible", timeout=8000)
            await boton.click()
        except Exception:
            pass

    async def _establecer_direccion(self, page, direccion: str):
        campo = page.locator(SEL_ADDRESS_INPUT).first
        await campo.wait_for(state="visible", timeout=15000)
        # fill() ya enfoca el campo por sí solo; un click() previo es un paso de más que
        # exige que el elemento esté "estable" (sin animarse) antes de tiempo.
        await campo.fill(direccion)

        sugerencia = page.locator(SEL_ADDRESS_SUGGESTION).first
        await sugerencia.wait_for(state="visible", timeout=15000)
        await sugerencia.click()

        # Tras seleccionar la sugerencia, a veces navega sola a /feed y a veces hay que
        # confirmar con "Buscar comida" (el campo geocodifica en segundo plano: pulsar el
        # botón demasiado pronto no navega). La URL /feed es la señal fiable de que llegamos.
        try:
            await page.wait_for_url(re.compile(r"/feed"), timeout=4000)
        except Exception:
            try:
                boton_buscar = page.locator(SEL_BUSCAR_COMIDA_BUTTON).first
                if await boton_buscar.is_visible(timeout=3000):
                    await boton_buscar.click(timeout=5000)
            except Exception:
                pass
            await page.wait_for_url(re.compile(r"/feed"), timeout=15000)

    async def _buscar_tienda(self, page) -> bool:
        campo_busqueda = page.locator(SEL_SEARCH_INPUT + ":visible").first
        await campo_busqueda.wait_for(state="visible", timeout=15000)
        await campo_busqueda.click()
        await campo_busqueda.fill(MARCA_BUSQUEDA)

        enlace = page.locator(f'{SEL_STORE_LINK}:has-text("{MARCA_BUSQUEDA}")').first
        try:
            await enlace.wait_for(state="visible", timeout=8000)
        except Exception:
            return False

        await enlace.click()
        await page.wait_for_load_state("domcontentloaded")
        return True

    async def _leer_disponibilidad(self, page) -> ResultadoChequeo:
        try:
            modalidad = page.locator(SEL_MODALITY_DELIVERY).first
            try:
                await modalidad.wait_for(state="attached", timeout=10000)
            except Exception:
                pass
            existe_delivery = await modalidad.count() > 0

            disponible = False
            if existe_delivery:
                aria_checked = await modalidad.get_attribute("aria-checked")
                aria_disabled = await modalidad.get_attribute("aria-disabled")
                disponible = aria_disabled != "true" and aria_checked is not None

            texto_eta = ""
            try:
                candidato = page.locator("text=/\\d+\\s*min/").first
                texto_eta = await candidato.inner_text(timeout=5000)
            except Exception:
                pass

            tiempo_entrega_min = None
            numeros = re.findall(r"\d+", texto_eta)
            if numeros:
                tiempo_entrega_min = int(numeros[-1])

            return ResultadoChequeo(
                disponible=disponible,
                tiempo_entrega_min=tiempo_entrega_min if disponible else None,
                mensaje_bloqueo=None if disponible else "Entrega no disponible para esta dirección",
                status_http=200,
            )
        except Exception as exc:
            logger.error("Error leyendo disponibilidad Uber Eats: %s", exc)
            screenshot = await self.screenshot_on_error(page, "error_lectura")
            return ResultadoChequeo(
                disponible=False,
                error_texto=str(exc),
                url_captura=screenshot,
            )

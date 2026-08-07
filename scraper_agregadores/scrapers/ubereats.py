import logging
import re

from scrapers.base import BaseAggregatorScraper, ResultadoChequeo

logger = logging.getLogger(__name__)

BASE_URL = "https://www.ubereats.com"

SEL_COOKIE_REJECT = 'button:has-text("Rechazar")'

SEL_ADDRESS_INPUT = "#location-typeahead-home-input"
SEL_ADDRESS_SUGGESTION = '[id^="location-typeahead-home-item-"]'
SEL_BUSCAR_COMIDA_BUTTON = 'button:has-text("Buscar comida")'

SEL_SEARCH_BUTTON = '[data-testid="label-wrapper-query"]:visible'
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

        try:
            sugerencia = page.locator(SEL_ADDRESS_SUGGESTION).first
            await sugerencia.wait_for(state="visible", timeout=15000)
            await sugerencia.click()
        except Exception:
            ruta = await self.screenshot_on_error(page, "direccion_sin_sugerencia")
            logger.warning("ubereats: sin sugerencia de dirección para '%s' -- captura: %s", direccion, ruta)
            raise

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
            try:
                await page.wait_for_url(re.compile(r"/feed"), timeout=15000)
            except Exception:
                # Diagnóstico: la sugerencia sí se seleccionó, pero nunca navegó a
                # /feed -- puede ser que la dirección exista pero Uber Eats no
                # reparte ahí (no hay redirección real) o un fallo de carga.
                ruta = await self.screenshot_on_error(page, "sin_navegacion_feed")
                logger.warning("ubereats: no navegó a /feed para '%s' -- captura: %s", direccion, ruta)
                raise

    async def _buscar_tienda(self, page) -> bool:
        # Layout viejo: la caja de búsqueda del feed era un botón/span de mentira
        # (data-testid "label-wrapper-query") que había que pulsar para que
        # apareciera el input real. Desde el 07/08 se ve que Uber Eats a veces ya
        # muestra el <input> de verdad directamente, sin ese paso intermedio
        # (capturas de fallo mostraban la barra de búsqueda ya rellenable en
        # pantalla, con el botón viejo inexistente). Se intenta el botón primero
        # con timeout corto y, si no aparece, se comprueba si el input ya está
        # visible sin necesidad de pulsar nada antes de darlo por fallo real.
        boton_busqueda = page.locator(SEL_SEARCH_BUTTON).first
        try:
            await boton_busqueda.wait_for(state="visible", timeout=8000)
            await boton_busqueda.click()
        except Exception:
            campo_directo = page.locator(SEL_SEARCH_INPUT + ":visible").first
            try:
                await campo_directo.wait_for(state="visible", timeout=15000)
            except Exception:
                ruta = await self.screenshot_on_error(page, "sin_boton_buscador")
                logger.warning("ubereats: sin botón ni input de búsqueda, url=%s -- captura: %s", page.url, ruta)
                raise

        campo_busqueda = page.locator(SEL_SEARCH_INPUT + ":visible").first
        try:
            await campo_busqueda.wait_for(state="visible", timeout=15000)
        except Exception:
            ruta = await self.screenshot_on_error(page, "sin_buscador")
            logger.warning("ubereats: sin campo de búsqueda tras pulsar botón, url=%s -- captura: %s", page.url, ruta)
            raise
        await campo_busqueda.fill(MARCA_BUSQUEDA)

        enlace = page.locator(f'{SEL_STORE_LINK}:has-text("{MARCA_BUSQUEDA}")').first
        try:
            # 20s en vez de 8s: un caso real (07/08 11:02, dirección "8, Calle de
            # Miguel Català") tardó ~58s en total entre el fill() y que el
            # resultado apareciera -- con 3 navegadores compitiendo por CPU, 8s
            # no siempre alcanza aunque la tienda sí esté ahí (confirmado a mano:
            # aparecía la primera en los resultados). 8s era tan corto que un
            # simple retraso de red se leía como "no disponible" de verdad.
            await enlace.wait_for(state="visible", timeout=20000)
        except Exception:
            # IMPORTANTE: no devolver False aquí. Que el selector no encuentre la
            # tienda en el tiempo dado NO es lo mismo que "confirmado que no
            # reparte ahí" -- devolver False lo convertía en un resultado "no
            # disponible" con confianza total a la primera pasada, sin
            # reintentos, provocando transiciones DD->DND falsas por un simple
            # render lento. Al lanzar la excepción, pasa por el mecanismo normal
            # de reintentos (_verificar_con_retry, 3 intentos con backoff) y solo
            # si persiste tras agotarlos se guarda como fallo técnico (error_texto)
            # en vez de como "no disponible" real.
            ruta = await self.screenshot_on_error(page, "tienda_no_confirmada")
            logger.warning(
                "ubereats: tienda no confirmada en resultados tras espera, url=%s -- captura: %s",
                page.url,
                ruta,
            )
            raise TimeoutError("ubereats: tienda no confirmada en resultados de búsqueda (ver captura)")

        # Click vía JS en vez de enlace.click(): la cabecera sticky de Uber Eats
        # (buscador + pills de categoría) se superpone visualmente a la parte de
        # arriba de los resultados. Playwright ve la tarjeta como "visible" pero
        # su chequeo de "recibe eventos de puntero" falla porque un <div> de la
        # cabecera está por encima en ese punto exacto -- reintenta con scroll
        # una y otra vez durante 30s (visible como scroll infinito) hasta
        # rendirse. El elemento SÍ es el correcto (confirmado en logs: resuelve
        # bien la tarjeta de Krispy Kreme); disparar el evento click directamente
        # en el DOM se salta ese chequeo de superposición y no falla nunca.
        await enlace.evaluate("e => e.click()")
        await page.wait_for_load_state("domcontentloaded")
        return True

    async def _detectar_cerrado_por_horario(self, page) -> str:
        """Busca el aviso de "Cerrado" con horario que Uber Eats muestra en la
        propia página de la tienda (p.ej. "Cerrado · Disponible los Viernes a
        las 8:00"). Devuelve el texto del aviso, o cadena vacía si no aparece."""
        try:
            aviso = page.locator("text=/Cerrado/i").first
            texto = await aviso.inner_text(timeout=3000)
            return texto.strip()
        except Exception:
            return ""

    async def _leer_disponibilidad(self, page) -> ResultadoChequeo:
        try:
            modalidad = page.locator(SEL_MODALITY_DELIVERY).first
            try:
                await modalidad.wait_for(state="attached", timeout=10000)
            except Exception:
                pass

            # El toggle a veces queda "attached" sin que aria-checked/aria-disabled se
            # hayan hidratado todavía (visto en pruebas: misma tienda, misma dirección,
            # a veces resuelve al instante y a veces tarda unos segundos más) -- reintenta
            # antes de darlo por no disponible para no confundir esto con un bloqueo real.
            disponible = False
            aria_checked = None
            for _ in range(5):
                if await modalidad.count() > 0:
                    aria_checked = await modalidad.get_attribute("aria-checked")
                    aria_disabled = await modalidad.get_attribute("aria-disabled")
                    if aria_checked is not None:
                        disponible = aria_disabled != "true"
                        break
                await page.wait_for_timeout(1000)

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

            # Señal de refuerzo: si el toggle no resolvió a tiempo pero la tienda sí
            # muestra un tiempo de entrega real en la página, hay reparto -- era un falso
            # negativo del toggle, no falta de cobertura (confirmado con un caso real:
            # Uber Eats mostraba "12 min" a mano en una dirección que el scraper marcó
            # como no disponible).
            if not disponible and tiempo_entrega_min is not None:
                disponible = True

            mensaje_bloqueo = None
            if not disponible:
                mensaje_bloqueo = "Entrega no disponible para esta dirección"
                # A diferencia de Glovo/JustEat (donde la tienda cerrada simplemente
                # no aparece en la búsqueda), Uber Eats sí muestra la tienda cerrada
                # con un aviso de horario (p.ej. "Cerrado · Disponible los Viernes a
                # las 8:00"). Esto es una señal distinta de "sin cobertura de
                # reparto en esta zona" -- se distingue en el mensaje para que el
                # reporte de transiciones no las trate como lo mismo.
                texto_cerrado = await self._detectar_cerrado_por_horario(page)
                if texto_cerrado:
                    mensaje_bloqueo = f"Tienda cerrada por horario (no es falta de cobertura): {texto_cerrado}"

            return ResultadoChequeo(
                disponible=disponible,
                tiempo_entrega_min=tiempo_entrega_min if disponible else None,
                mensaje_bloqueo=mensaje_bloqueo,
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

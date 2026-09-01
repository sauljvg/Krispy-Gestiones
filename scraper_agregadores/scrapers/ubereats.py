import logging
import re

from scrapers.base import BaseAggregatorScraper, ResultadoChequeo

logger = logging.getLogger(__name__)

BASE_URL = "https://www.ubereats.com"

SEL_COOKIE_REJECT = 'button:has-text("Rechazar")'

SEL_ADDRESS_INPUT = "#location-typeahead-home-input"
SEL_ADDRESS_SUGGESTION = '[id^="location-typeahead-home-item-"]'
SEL_BUSCAR_COMIDA_BUTTON = 'button:has-text("Buscar comida")'

# Flujo alternativo entrando directo por /feed en vez de la portada -- confirmado
# a mano 08/08 (selectores reales sacados del DOM, no adivinados): evita cargar
# toda la home con sus carruseles/promos. Solo aplica si /feed ya trae un chip
# de ubicación (típico si el sitio resolvió algo por geolocalización/IP); si no,
# se cae al flujo de portada de siempre (ver _establecer_direccion).
SEL_EDIT_LOCATION_BUTTON = '[data-testid="edit-delivery-location-button"]'
SEL_CHANGE_ADDRESS_BUTTON = '[data-testid="change-address-button"]'
SEL_ADDRESS_INPUT_FEED = '[data-testid="location-typeahead-input"]'
SEL_ADDRESS_SUGGESTION_FEED = '[id^="location-typeahead-location-manager-item-"]'

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
    # Confirmado en vivo 08/08: no basta con "no headless" -- si la ventana se manda
    # fuera de pantalla (comportamiento por defecto para no interrumpir al usuario),
    # Uber Eats seguía bloqueando con challenge el 100% de las veces. Con la ventana
    # genuinamente en pantalla, dejó de bloquear.
    mantener_visible = True

    async def _verificar(self, page, tienda_nombre: str, direccion: str, lat: float | None = None, lng: float | None = None) -> ResultadoChequeo:
        # Confirmado en vivo 08/08: /feed nunca trae chip de ubicación aquí porque
        # cada chequeo lanza un navegador nuevo sin cookies/geolocalización previa
        # (ver _run_once) -- el intento de /feed caía al fallback de portada el
        # 100% de las veces, añadiendo ~10s perdidos por chequeo sin ganar nada.
        # Se va directo a la portada, que es el único camino que de verdad funciona
        # con este modelo de sesión nueva por chequeo.
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

    async def _rellenar_sin_scroll(self, page, selector: str, valor: str):
        """Rellena un input por JS puro, sin pasar por el fill()/scrollIntoView
        de Playwright.

        Confirmado en vivo 08/08 (viendo la ventana real en pantalla): la home
        sigue cargando contenido de forma diferida por debajo (secciones de
        "añade tu restaurante", "reparte con Uber Eats", "ciudades cerca de
        ti"...) que la empuja a desplazarse sola durante ~30s. fill(force=True)
        NO lo arregla -- se salta el chequeo de estabilidad pero sigue haciendo
        scroll-into-view antes de escribir, y ese scroll choca con el que la
        propia página dispara. La solución real es no tocar el scroll para
        nada: se fija el value directamente vía el setter nativo (el mismo
        truco confirmado a mano en el navegador esta sesión) y se dispara
        'input' para que React lo detecte igual que si se hubiera escrito.
        """
        # OJO: document.querySelector no entiende ":visible" (eso es una extensión
        # de Playwright, no CSS real) -- se filtra la visibilidad a mano en JS.
        await page.evaluate(
            """([selector, valor]) => {
                const candidatos = Array.from(document.querySelectorAll(selector));
                const el = candidatos.find(e => e.offsetParent !== null) || candidatos[0];
                const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                setter.call(el, valor);
                el.dispatchEvent(new Event('input', {bubbles: true}));
            }""",
            [selector, valor],
        )

    async def _establecer_direccion(self, page, direccion: str):
        campo = page.locator(SEL_ADDRESS_INPUT).first
        await campo.wait_for(state="visible", timeout=15000)
        await self._rellenar_sin_scroll(page, SEL_ADDRESS_INPUT, direccion)

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
        await self._rellenar_sin_scroll(page, SEL_SEARCH_INPUT, MARCA_BUSQUEDA)

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
            # Confirmado en vivo 08/08 (viendo un punto real atascado 15+ min en
            # reintentos): el desplegable en vivo (lo de arriba) puede no mostrar
            # la tienda a tiempo aunque SÍ exista -- probado a mano que pulsar
            # Enter (página de resultados completa) encuentra coincidencias que
            # el desplegable no llegó a mostrar. Último intento antes de darlo
            # por "no confirmada" de verdad.
            try:
                await campo_busqueda.press("Enter")
                await enlace.wait_for(state="visible", timeout=10000)
                logger.info("ubereats: tienda encontrada tras pulsar Enter (el desplegable no la mostró a tiempo)")
            except Exception:
                pass
            else:
                await enlace.evaluate("e => e.click()")
                await page.wait_for_load_state("domcontentloaded")
                return True

            # Confirmado en vivo 08/08: el reCAPTCHA real de Uber Eats no sale
            # siempre al cargar la página -- a veces aparece justo aquí, a mitad
            # del flujo, tras escribir la búsqueda. Sin este chequeo, ese caso se
            # confundía con "tienda no confirmada" (un simple fallo técnico) en
            # vez de tratarse como el challenge real que es (ventana visible +
            # aviso para resolverlo a mano, ver _comprobar_challenge). Se
            # comprueba primero, antes de asumir que es solo un render lento.
            await self._comprobar_challenge(page)

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
            # Confirmado en vivo 08/08: cuando la tienda está cerrada por horario,
            # Uber Eats muestra un modal de "Programar la entrega" y el toggle de
            # modalidad NO lleva aria-disabled="true" -- el atributo simplemente
            # no existe (aria-disabled=None), y el código de abajo interpretaba
            # "no es 'true'" como "disponible". Se comprueba "Cerrado" primero,
            # ANTES de fiarse del toggle, porque el toggle no es señal fiable en
            # este estado (el modal lo tapa/desactiva de otra forma).
            #
            # IMPORTANTE (aclarado por el usuario 08/08): lo que buscamos aquí es
            # ZONA de reparto, no si la tienda está abierta ahora mismo. Que Uber
            # Eats ofrezca PROGRAMAR la entrega para cuando reabra es en sí mismo
            # la prueba de que esta dirección SÍ está dentro de su zona de reparto
            # -- si no lo estuviera, no dejaría programar nada. Así que "cerrado
            # con opción de programar" cuenta como disponible=True (señal positiva
            # de cobertura), no como un dato a descartar ni como "no disponible".
            texto_cerrado_temprano = await self._detectar_cerrado_por_horario(page)
            if texto_cerrado_temprano:
                return ResultadoChequeo(
                    disponible=True,
                    mensaje_bloqueo=f"Cerrado ahora, pero permite programar entrega -- confirma zona de reparto: {texto_cerrado_temprano}",
                    status_http=200,
                )

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

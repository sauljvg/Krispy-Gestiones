import asyncio
import json
import logging
import random
import re
import urllib.parse

from playwright.async_api import async_playwright

from scrapers.base import (
    CHALLENGE_KEYWORDS,
    _USER_AGENTS,
    _viewport_aleatorio,
    BaseAggregatorScraper,
    PaginaSobrecargadaError,
    ResultadoChequeo,
    _STEALTH,
    _bloquear_recursos_pesados,
    _pagina_muestra_error_generico,
)

logger = logging.getLogger(__name__)

# URL con localización fija a Madrid en español -- antes se usaba la raíz
# (https://glovoapp.com), que según sesión/geolocalización del navegador
# devolvía la interfaz en inglés (pedido explícito del usuario 26/08: usar
# la web en español). Todas las tiendas están en Madrid (config.TIENDAS_SCHEDULER),
# así que fijar la ciudad en la URL no pierde cobertura.
URL_INICIO = "https://glovoapp.com/es/es/madrid"

# El banner de cookies es Usercentrics (confirmado en vivo 03/09 inspeccionando
# el DOM real): expone id="deny"/clase "uc-deny-button" ESTABLES sin importar el
# idioma con el que cargue el banner ese momento -- antes solo se buscaba el
# texto "Denegar", que fallaba en silencio (el except Exception de
# _aceptar_cookies se comía el error) las veces que el banner salía en inglés
# ("Deny") pese al locale="es-ES" fijado en base.py, dejando el banner abierto
# tapando el resto del flujo (causa raíz de un fallo real, ver captura
# glovo_tienda_no_confirmada_20260826_123213). Se prueban los dos por si acaso.
SEL_COOKIE_DENY = '#deny, button.uc-deny-button, button:has-text("Denegar")'

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

# Buscador de la pagina de RESULTADOS (04/09). OJO: no es el de la portada
# (SEL_SEARCH_INPUT); aqui hay DOS con el mismo placeholder y uno esta oculto, de ahi
# el :visible.
SEL_SEARCH_PANEL_INPUT = '[data-testid="search-panel-input"]:visible'

SEL_STORE_ETA_TEXT = '[class*="StoreEta_text"]'

MARCA_BUSQUEDA = "Krispy Kreme"

# API interna de Glovo (04/09). Es la que de verdad devuelve el listado de tiendas; la
# pagina solo la envuelve. La UBICACION le llega por CABECERAS, no por URL ni cookie:
# glovo-delivery-location-latitude/-longitude. No se puede llamar desde fuera (da 404,
# probado con las 30 cabeceras capturadas) ni desde dentro con fetch (su propio JS
# envuelve fetch y salta CORS) -- pero SI se puede dejar que la haga la pagina e
# interceptarla con context.route() para reescribirle las coordenadas al vuelo.
API_STORE_WALL = "store_wall"

# Donde vive el listado REAL de tiendas dentro del JSON. Buscar "krispy kreme" en el
# texto en bruto NO vale: la marca aparece 184 veces en metadatos de analitica y da
# falsos positivos en direcciones sin cobertura (comprobado). Hay que leer los
# elementos y mirar su slug/titulo.
RUTA_ELEMENTS = ("data", "body", "data", "elements")

# CAUSA RAÍZ real de la inmensa mayoría de "tienda no confirmada" (confirmado
# 03/09 revisando TODAS las capturas de un día real de fallos -- ~49 de 50
# mostraban exactamente este banner, ninguna un bloqueo/challenge de verdad, y
# reproducido en vivo en una dirección real sin cobertura, en español e
# inglés): cuando la dirección buscada no tiene NINGUNA tienda repartiendo ahí
# (ni Krispy Kreme ni ninguna otra), Glovo no deja la página en blanco ni
# rota -- muestra este banner de "sin resultados", una respuesta VÁLIDA de
# "aquí no llega nadie", igual de fiable que ver otras tiendas sin Krispy
# Kreme entre ellas. El código de antes solo confiaba en "hay otras tarjetas
# listadas" como prueba de que la búsqueda funcionó; cuando el banner de sin
# resultados aparecía (total_tarjetas=0 siempre en ese caso), lo trataba como
# fallo técnico -- captura, reintento, backoff -- por algo que en realidad ya
# era el dato bueno. En minúsculas y sin tilde para comparar tolerante a
# mayúsculas; cubre español e inglés porque el idioma de la interfaz no
# siempre es español pese a locale="es-ES" (ver SEL_COOKIE_DENY más arriba,
# mismo motivo de fondo).
MARCADORES_SIN_RESULTADOS = ("no se han encontrado resultados", "no results found")

# Mismo texto que MARCADOR_PAGINA_SOBRECARGADA de base.py, en minúsculas para comparar
# contra el innerText ya pasado a minúsculas en la ruta rápida.
MARCADOR_PAGINA_SOBRECARGADA_LOWER = "oh, no!"


class GlovoScraper(BaseAggregatorScraper):
    nombre_agregador = "glovo"
    url_base = URL_INICIO

    # --- Sesión caliente + cookie de dirección (03/09) --------------------------
    # Mismo hallazgo que en Uber Eats (ver scrapers/ubereats.py): el coste real por
    # dirección no estaba en la búsqueda en sí, sino en repetir para CADA punto el
    # lanzamiento del navegador + la carga de la portada + los ~7 pasos de la
    # interfaz de dirección. Glovo guarda la dirección de entrega en una cookie de
    # cliente en texto plano (`glovo_delivery_address`, descubierta el 27/08 -- ver
    # _verificar_via_cookie), así que basta con cambiar esa cookie y volver a la URL
    # de búsqueda para cambiar de punto.
    #
    # Por qué falló cuando se intentó el 27/08: se probó con un navegador NUEVO en
    # cada chequeo y "la página de resultados se queda vacía siempre". La diferencia
    # ahora es la SESIÓN CALIENTE -- se abre una vez (portada + cookies, ~8s) y se
    # reutiliza para todas las direcciones de esa tienda.
    #
    # Comprobado en vivo 03/09: con la sesión caliente, 4/4 direcciones con cobertura
    # real dieron "Krispy Kreme entre las 100 tiendas listadas", y los negativos se
    # resuelven en ~1.4s (frente a 15-44s del flujo de interfaz). Hay direcciones
    # sueltas (vistas en Getafe/Leganés) donde la página de resultados sigue saliendo
    # vacía pese a la cookie -- esas caen solas al flujo de siempre, que sí las
    # resuelve; no se pierde ningún punto por esto.
    # Ruta por API (04/09): en vez de leer el DOM, se lee la respuesta JSON de la
    # propia API de Glovo, interceptando su peticion para inyectarle las coordenadas de
    # cada direccion. Ventaja decisiva: recargar la pagina de busqueda cuesta ~150
    # peticiones por punto (medido), y con 5 workers eso son ~100 peticiones/segundo
    # contra Glovo -- de ahi que su limitador por IP saltara constantemente y que
    # acelerar por punto no sirviera de nada. Repitiendo la busqueda DENTRO de la app,
    # sin recargar, cada punto cuesta unas pocas peticiones.
    _api_destino = None      # {"lat":…, "lng":…} que se inyecta en la peticion
    _api_respuesta = None    # ultimo JSON devuelto por la API
    _api_lista = False       # ya se cargo una vez la pagina de resultados

    _sesion_pw = None
    _sesion_browser = None
    _sesion_context = None
    _sesion_page = None

    # Umbral más alto que en Uber Eats a propósito: aquí los fallos suelen ser de
    # DIRECCIONES concretas (la página sale vacía para ese punto), no de la sesión,
    # así que una racha corta no debe desactivar el atajo para toda la tienda.
    # Corte TEMPORAL (corregido el 04/09, mismo error que en ubereats.py): antes
    # desactivaba la ruta rápida mientras viviera el scraper, y al reutilizarlo para
    # todo el worker (~66 puntos) una racha mala la mataba para el resto de la ronda.
    _FALLOS_RAPIDOS_MAX = 8
    _PUNTOS_ENFRIAMIENTO = 15
    _fallos_rapidos = 0
    _enfriamiento_restante = 0

    @staticmethod
    def _cookie_direccion(direccion_texto: str, lat: float, lng: float) -> str:
        """Valor de la cookie glovo_delivery_address: doble percent-encoding de un
        JSON con lat/lng -- así es como lo escribe la propia web (confirmado
        inspeccionando document.cookie en vivo). placeId puede ir vacío: el backend
        no lo valida contra Google, solo lee lat/lng."""
        valor = json.dumps(
            {
                "latitude": lat,
                "longitude": lng,
                "cityCode": "MAD",
                "countryCode": "ES",
                "cityName": "Madrid",
                "text": direccion_texto,
                "details": "",
                "placeId": "",
                "isVerified": True,
                "postalCode": None,
            },
            separators=(",", ":"),
        )
        return urllib.parse.quote(urllib.parse.quote(valor, safe=""), safe="")

    @staticmethod
    def _leer_respuesta_api(texto: str):
        """(disponible, detalle) leyendo el listado REAL de tiendas del JSON.
        None si la respuesta no es interpretable (el caller cae al flujo de siempre)."""
        try:
            datos = json.loads(texto)
        except Exception:
            return None, "json ilegible"
        elementos = datos
        for clave in RUTA_ELEMENTS:
            elementos = elementos.get(clave) if isinstance(elementos, dict) else None
            if elementos is None:
                return None, "estructura inesperada"
        if not isinstance(elementos, list):
            return None, "sin listado de tiendas"
        for elemento in elementos:
            datos_el = elemento.get("data", {}) if isinstance(elemento, dict) else {}
            slug = str(datos_el.get("slug", "")).lower()
            titulo = datos_el.get("title") or {}
            texto_titulo = str(titulo.get("text", "")).lower() if isinstance(titulo, dict) else ""
            if "krispy-kreme" in slug or MARCA_BUSQUEDA.lower() in texto_titulo:
                return True, "Krispy Kreme en el listado"
        return False, f"{len(elementos)} tiendas, ninguna Krispy Kreme"

    async def _abrir_sesion(self):
        """Abre UNA sesión y la deja caliente (portada + banner de cookies) para
        reutilizarla en todas las direcciones siguientes."""
        self._sesion_pw = await async_playwright().start()
        self._sesion_browser = await self._sesion_pw.chromium.launch(
            headless=True, args=["--disable-blink-features=AutomationControlled"], proxy=self.proxy,
        )
        self._sesion_context = await self._sesion_browser.new_context(
            # MISMA aleatorización de huella que el flujo de siempre (ver _run_once en
            # base.py). Error real del 03/09, detectado el 04/09: la sesión caliente se
            # creaba sin user_agent ni viewport, así que salía con los valores POR
            # DEFECTO de Playwright -- y el UA por defecto anuncia la versión interna de
            # Chromium ("Chrome/151.0.0.0", una versión que no existe en escritorio
            # real), con viewport fijo 1280x720. Encima esa misma huella se mantenía
            # durante TODOS los chequeos de la sesión (cientos), mientras que el flujo de
            # siempre estrenaba una por chequeo. La aleatorización se añadió el 27/08
            # justo como mitigación anti-detección y esta ruta se la saltaba sin querer.
            user_agent=random.choice(_USER_AGENTS),
            viewport=_viewport_aleatorio(),
            locale="es-ES",
        )
        await _STEALTH.apply_stealth_async(self._sesion_context)
        if self.bloquear_recursos:
            await self._sesion_context.route("**/*", _bloquear_recursos_pesados)
        # Interceptar la peticion a la API para inyectar las coordenadas del punto que
        # toque, y quedarnos con su respuesta (ver comentario de _api_destino).
        async def _inyectar(route):
            peticion = route.request
            if API_STORE_WALL in peticion.url and self._api_destino:
                cabeceras = dict(peticion.headers)
                cabeceras["glovo-delivery-location-latitude"] = str(self._api_destino["lat"])
                cabeceras["glovo-delivery-location-longitude"] = str(self._api_destino["lng"])
                await route.continue_(headers=cabeceras)
            else:
                await route.continue_()

        await self._sesion_context.route("**/api.glovoapp.com/**", _inyectar)

        async def _guardar(respuesta):
            if API_STORE_WALL in respuesta.url and "search" in respuesta.url:
                try:
                    self._api_respuesta = (respuesta.status, await respuesta.text())
                except Exception:
                    pass

        self._sesion_page = await self._sesion_context.new_page()
        self._sesion_page.on("response", lambda r: asyncio.create_task(_guardar(r)))
        self._api_lista = False

        await self._sesion_page.goto(URL_INICIO, wait_until="domcontentloaded", timeout=45000)
        await self._aceptar_cookies(self._sesion_page)

    async def cerrar_sesion(self):
        """Cierra la sesión caliente si está abierta (la llama chequear_tienda al
        terminar con la tienda, ver main.py)."""
        for cerrar in (
            getattr(self._sesion_context, "close", None),
            getattr(self._sesion_browser, "close", None),
            getattr(self._sesion_pw, "stop", None),
        ):
            if cerrar is not None:
                try:
                    await cerrar()
                except Exception:
                    pass
        self._sesion_pw = self._sesion_browser = self._sesion_context = self._sesion_page = None

    async def verificar_disponibilidad(self, tienda_nombre: str, direccion: str, lat=None, lng=None) -> ResultadoChequeo:
        """Ruta rápida (sesión caliente + cookie de dirección) con caída automática al
        flujo de interfaz de siempre. Sin lat/lng no se puede montar la cookie."""
        if lat is None or lng is None:
            return await super().verificar_disponibilidad(tienda_nombre, direccion, lat, lng)

        if self._enfriamiento_restante > 0:
            self._enfriamiento_restante -= 1
            if self._enfriamiento_restante == 0:
                self._fallos_rapidos = 0
                logger.info("glovo: fin del enfriamiento -- se vuelve a intentar la ruta rápida")
            return await super().verificar_disponibilidad(tienda_nombre, direccion, lat, lng)

        try:
            if self._sesion_page is None:
                await self._abrir_sesion()
            resultado = await self._verificar_por_cookie(direccion, lat, lng)
            self._fallos_rapidos = 0
            return resultado
        except Exception as exc:
            self._fallos_rapidos += 1
            if self._fallos_rapidos >= self._FALLOS_RAPIDOS_MAX:
                self._enfriamiento_restante = self._PUNTOS_ENFRIAMIENTO
            logger.info(
                "glovo: ruta rápida sin resultado para '%s' (%r) -- se resuelve por el flujo de siempre%s",
                direccion, exc,
                "" if self._fallos_rapidos < self._FALLOS_RAPIDOS_MAX
                else f" -- en pausa los próximos {self._PUNTOS_ENFRIAMIENTO} puntos",
            )
            if self._fallos_rapidos >= self._FALLOS_RAPIDOS_MAX:
                await self.cerrar_sesion()
            return await super().verificar_disponibilidad(tienda_nombre, direccion, lat, lng)

    async def _verificar_por_cookie(self, direccion: str, lat: float, lng: float) -> ResultadoChequeo:
        """Lee la disponibilidad de la RESPUESTA DE LA API, no del DOM.

        La primera direccion carga la pagina de resultados; las siguientes solo repiten
        la busqueda DENTRO de la app, sin recargar -- que es lo que hace barata esta
        ruta (~150 peticiones por punto recargando, unas pocas repitiendo la busqueda).
        Las coordenadas se inyectan interceptando la peticion (ver _abrir_sesion)."""
        page = self._sesion_page
        self._api_destino = {"lat": lat, "lng": lng}
        self._api_respuesta = None

        # La cookie se mantiene por coherencia con lo que la app muestra en pantalla;
        # quien manda de verdad para la API son las cabeceras inyectadas.
        await self._sesion_context.clear_cookies(name="glovo_delivery_address")
        await self._sesion_context.add_cookies([{
            "name": "glovo_delivery_address",
            "value": self._cookie_direccion(direccion, lat, lng),
            "domain": "glovoapp.com",
            "path": "/",
        }])

        if not self._api_lista:
            await page.goto(
                f"{URL_INICIO}/search?q={urllib.parse.quote(MARCA_BUSQUEDA)}",
                wait_until="domcontentloaded", timeout=30000,
            )
            self._api_lista = True
        else:
            # Repetir la busqueda sin recargar. Se pasa por otro termino primero para
            # forzar una peticion nueva: repetir el mismo texto no siempre la dispara.
            campo = page.locator(SEL_SEARCH_PANEL_INPUT).first
            await campo.wait_for(state="visible", timeout=10000)
            await campo.fill("donuts")
            await campo.press("Enter")
            await page.wait_for_timeout(800)
            self._api_respuesta = None
            await campo.fill(MARCA_BUSQUEDA)
            await campo.press("Enter")

        # Si la busqueda interna no dispara la peticion (visto sobre todo en direcciones
        # de Getafe/Leganes), se recarga la pagina, que si la dispara siempre. Antes se
        # esperaba 15s en balde y se caia al flujo de interfaz: 55s por punto en vez de 3.
        recarga_de_rescate = self._api_lista
        for intento in range(30):  # hasta ~15s
            if recarga_de_rescate and intento == 10 and self._api_respuesta is None:
                recarga_de_rescate = False
                logger.info("glovo: la busqueda interna no disparo la API -- recargando la pagina")
                await page.goto(
                    f"{URL_INICIO}/search?q={urllib.parse.quote(MARCA_BUSQUEDA)}",
                    wait_until="domcontentloaded", timeout=30000,
                )
            if self._api_respuesta is not None:
                estado, cuerpo = self._api_respuesta
                if estado == 422:
                    # OJO: 422 NO significa "no reparte aqui". Se interpreto asi con solo
                    # dos casos de evidencia y produjo FALSOS NEGATIVOS reales (Avenida
                    # de Salvador Allende y Calle de Brasil, ambas en Getafe/Leganes:
                    # esta ruta decia False y el flujo de interfaz decia True). Lo que
                    # significa es que la ubicacion NO PERTENECE AL CONTEXTO DE CIUDAD de
                    # la peticion: la sesion se calienta en /es/es/madrid y al inyectar
                    # coordenadas de otra zona (leganes-getafe) Glovo rechaza la consulta,
                    # aunque alli SI reparta desde esa otra zona.
                    #
                    # Hasta que se resuelva el cambio de ciudad, estos puntos se mandan al
                    # flujo de interfaz de siempre, que los resuelve bien. Es mas lento
                    # pero CORRECTO, que es lo que importa: un falso negativo marcaria
                    # como sin cobertura una zona que si reparte.
                    raise TimeoutError("glovo: 422 -- direccion fuera del contexto de ciudad de la sesion")
                if estado == 200:
                    disponible, detalle = self._leer_respuesta_api(cuerpo)
                    if disponible is None:
                        raise TimeoutError(f"glovo: respuesta de API no interpretable ({detalle})")
                    logger.info("glovo: por API -> disponible=%s (%s)", disponible, detalle)
                    return ResultadoChequeo(
                        disponible=disponible,
                        mensaje_bloqueo=None if disponible else "Tienda no aparece en resultados para esta direccion",
                        status_http=200,
                    )
                raise TimeoutError(f"glovo: la API respondio {estado}")

            texto = await page.evaluate("() => document.body.innerText")
            bajo = texto.lower()
            if any(clave in bajo for clave in CHALLENGE_KEYWORDS):
                raise RuntimeError("challenge anti-bot en la ruta rapida")
            if MARCADOR_PAGINA_SOBRECARGADA_LOWER in bajo:
                raise PaginaSobrecargadaError("glovo")
            if any(marcador in bajo for marcador in MARCADORES_SIN_RESULTADOS):
                # La pagina ya ha respondido: aqui no reparte NADIE. En estas
                # direcciones la app puede ni llegar a llamar a la API (no hay nada que
                # buscar), asi que esperar su respuesta es esperar algo que no va a
                # llegar -- eso costaba 15s de espera + recarga + flujo de interfaz,
                # unos 55s, para una respuesta que la pagina daba desde el primer
                # segundo. Es un no disponible VALIDO, igual que en el flujo de siempre.
                logger.info("glovo: banner de \"sin resultados\" -- aqui no reparte nadie")
                return ResultadoChequeo(
                    disponible=False,
                    mensaje_bloqueo="Sin resultados de reparto para esta direccion",
                    status_http=200,
                )
            await page.wait_for_timeout(500)

        # Sin respuesta de la API: la sesion puede haberse quedado tocada -> que la
        # siguiente direccion recargue la pagina en vez de repetir la busqueda.
        self._api_lista = False
        raise TimeoutError("glovo: la API no respondio a tiempo")

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
        # Segunda comprobación, barata (timeout corto -- no añade espera si el banner
        # ya no está, que es el caso normal): por si el banner de cookies llegó
        # incluso más tarde de los 15s de arriba (03/09, ver comentario en
        # _aceptar_cookies) -- red de seguridad extra antes del paso que de verdad
        # se bloquea si el banner sigue abierto (escribir la dirección).
        await self._aceptar_cookies_rapido(page)
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
        # Timeout subido de 8s a 15s (03/09, confirmado en vivo bajo carga real con
        # varios Chrome a la vez -- ver captura glovo_tienda_no_confirmada_20260903_185202):
        # el banner de Usercentrics es asíncrono (se inyecta tras cargar su propio
        # script) y bajo contención de CPU/red (varios scrapers corriendo a la vez en
        # la misma máquina) a veces tarda más de 8s en aparecer. Con el timeout viejo,
        # el wait_for expiraba, el except lo tragaba en silencio, y el código seguía
        # como si ya estuviera aceptado -- pero el banner aparecía IGUAL unos
        # instantes después y se quedaba ahí tapando el resto del flujo (dirección,
        # búsqueda) para todo el resto del chequeo, que entonces fallaba como
        # "tienda no confirmada" ambiguo (con sus 3 reintentos) por una causa que no
        # tenía nada que ver con la tienda. Confirmado que esto explica una parte
        # importante del tiempo real de una ronda de Glovo bajo carga (revalidar_completo.py
        # con 20 workers), no solo un caso aislado.
        try:
            boton = page.locator(SEL_COOKIE_DENY).first
            await boton.wait_for(state="visible", timeout=15000)
            await boton.click()
        except Exception as exc:
            # Antes "except Exception: pass" sin ningún rastro -- si el banner de
            # verdad nunca aparece (o tarda más de 15s incluso), ahora queda constancia
            # en el log en vez de desaparecer en silencio como el bug de arriba.
            logger.debug("glovo: no se pudo aceptar/denegar cookies (se sigue igualmente): %r", exc)

    async def _aceptar_cookies_rapido(self, page):
        """Igual que _aceptar_cookies pero con timeout corto (1.5s) -- red de
        seguridad barata para el caso, más raro todavía, de que el banner llegue
        incluso después de los 15s de la comprobación principal. Con timeout corto no
        penaliza el caso normal (banner ya aceptado o nunca llegó a aparecer)."""
        try:
            boton = page.locator(SEL_COOKIE_DENY).first
            await boton.wait_for(state="visible", timeout=1500)
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
            # Primero: ¿es el banner de "sin resultados"? (ver MARCADORES_SIN_RESULTADOS
            # arriba -- causa raíz confirmada de la inmensa mayoría de estos fallos).
            # Esto es una respuesta VÁLIDA, no un fallo técnico -- se devuelve
            # directamente, sin capturas ni reintentos.
            try:
                texto_pagina = (await page.evaluate("() => document.body.innerText")).lower()
            except Exception:
                texto_pagina = ""
            if any(marcador in texto_pagina for marcador in MARCADORES_SIN_RESULTADOS):
                logger.info(
                    "glovo: banner de \"sin resultados\" -- ninguna tienda reparte en esta "
                    "dirección (ni Krispy Kreme ni ninguna otra), respuesta válida de Glovo, url=%s",
                    page.url,
                )
                return False

            # Si no es el banner de sin resultados: antes de asumir fallo técnico,
            # ¿SÍ hay otras tiendas listadas? -- la búsqueda funcionó de verdad
            # (página cargada, resultados reales) y Krispy Kreme simplemente no
            # está entre ellas -- confirmado con un HTML de diagnóstico real (14
            # tarjetas de otras tiendas, ninguna de Krispy Kreme). Ahí también es
            # un "no disponible" fiable, no ambiguo. Solo se trata como fallo
            # técnico (con reintentos, ver _verificar_con_retry) cuando no hay
            # NINGUNA tarjeta Y tampoco el banner de sin resultados -- eso sí
            # puede ser una carga rota/a medias, mismo motivo que en Uber Eats.
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

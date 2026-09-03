import asyncio
import logging
import random
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright
from playwright_stealth import Stealth

logger = logging.getLogger(__name__)


def _avisar_captcha_pendiente(agregador: str, segundos_espera: int) -> None:
    """Aviso nativo de Windows (globo + sonido) cuando aparece un captcha que
    necesita resolución manual -- para no tener que estar mirando la terminal
    esperando a que salga el mensaje. No resuelve nada, solo avisa a un
    humano de que tiene que actuar él (ver _comprobar_challenge)."""
    try:
        import winsound

        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
    except Exception:
        pass

    mensaje = f"{agregador}: resuelve el captcha en la ventana del navegador ({segundos_espera}s)"
    try:
        subprocess.Popen(
            [
                "powershell", "-NoProfile", "-Command",
                "Add-Type -AssemblyName System.Windows.Forms; "
                "$n = New-Object System.Windows.Forms.NotifyIcon; "
                "$n.Icon = [System.Drawing.SystemIcons]::Warning; "
                "$n.Visible = $true; "
                f"$n.ShowBalloonTip(15000, 'Captcha pendiente', '{mensaje}', "
                "[System.Windows.Forms.ToolTipIcon]::Warning); "
                "Start-Sleep -Seconds 16; $n.Dispose()",
            ],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        logger.warning("No se pudo lanzar el aviso nativo de captcha (sigue esperando igual)")

SCREENSHOTS_DIR = Path(__file__).resolve().parent.parent / "logs" / "screenshots"

CHALLENGE_KEYWORDS = (
    "verificación de seguridad",
    "checking your browser",
    "attention required",
    "cloudflare",
    "please verify you are a human",
    "sorry, you have been blocked",
    # Añadidos tras un reCAPTCHA real de Uber Eats (07/08) con texto distinto al
    # resto, que la lista anterior no reconocía. OJO: "un paso más" (probado
    # aquí mismo un rato después) resultó ser demasiado genérico -- daba falso
    # positivo en páginas normales de Uber Eats y tumbaba el 100% de los
    # chequeos con EOFError (ver _comprobar_challenge). Solo frases que no
    # tienen sentido fuera de una pantalla de challenge real.
    "comprobación de seguridad automatizada",
    "no soy un robot",
    # "recaptcha" (sin más) SE QUITÓ el 08/08: confirmado en vivo que Uber Eats
    # mete el aviso legal "Este sitio está protegido por reCAPTCHA..." en el
    # footer de TODA página, real challenge o no -- disparaba la alarma
    # siempre, en cada chequeo, sin que hubiera nada que resolver. La frase
    # específica del widget real ("no soy un robot") ya cubre el caso real.
)

_STEALTH = Stealth()

# Las fuentes se dejan pasar a propósito: bloquearlas ahorra algo de peso por
# página, pero deja las capturas de pantalla ilegibles ("word word word" en
# vez del texto real) -- y ahora se sube una captura de CADA chequeo para
# poder auditarlo, así que necesitan poder leerse.
_RECURSOS_BLOQUEADOS = ("image", "media")

# Peticiones de analítica/tracking (03/09, confirmado en vivo inspeccionando la red
# real de Glovo): cada carga de página dispara decenas de llamadas a
# "glovoapp.com/gtm-metrics/..." (Google Tag Manager, PROXIADO por su propio dominio,
# no google.com) -- puro tracking, cero función para el scraper, pero SÍ carga real
# contra los servidores de Glovo en cada chequeo. Con Glovo limitando por volumen/IP
# (ver PaginaSobrecargadaError), cada petición de más cuenta. A diferencia de
# _RECURSOS_BLOQUEADOS (por resource_type), esto es por URL -- gtm-metrics no tiene
# un resource_type propio distinguible (llega como fetch/xhr, igual que las
# peticiones reales que sí hacen falta), así que hay que mirar la URL.
_URLS_TRACKING_BLOQUEADAS = ("gtm-metrics", "google-analytics.com", "doubleclick.net", "facebook.com/tr")


async def _bloquear_recursos_pesados(route):
    if route.request.resource_type in _RECURSOS_BLOQUEADOS:
        await route.abort()
    elif any(patron in route.request.url for patron in _URLS_TRACKING_BLOQUEADAS):
        await route.abort()
    else:
        await route.continue_()


class ChallengeDetectedError(Exception):
    """El sitio ha mostrado un challenge anti-bot (Cloudflare u otro WAF)."""


class PaginaSobrecargadaError(Exception):
    """El sitio mostró su propia página de error genérica ("Oh, no! It looks like
    there's a problem", confirmado en vivo 27/08 con capturas reales de Glovo bajo
    carga concurrente) -- no es un challenge anti-bot ni un timeout de red nuestro,
    es EL SITIO diciendo que está teniendo problemas. Se trata distinto en
    _verificar_con_retry: un backoff mucho más largo que el de un fallo normal, para
    darle tiempo real a recuperarse en vez de darle más carga a los pocos segundos."""

    def __init__(self, contexto: str, texto_pagina: str | None = None):
        super().__init__(f"{contexto}: la página mostró su propio error genérico (sobrecarga)")
        self.texto_pagina = texto_pagina


# Frase EXACTA que lanzan glovo.py/justeat.py/ubereats.py (con su propio prefijo
# "<agregador>: ") cuando la búsqueda de la tienda se completó de verdad (sin
# challenge, sin fallo de red) pero Krispy Kreme sencillamente no salió en los
# resultados. Confirmado a mano por el usuario 09/08: esto NO es un fallo técnico --
# es una búsqueda válida que no encontró la tienda, la misma señal que "no
# disponible". Centralizada aquí (antes solo vivía en buscar_limite_cobertura.py) para
# que main.py/chequear_tienda pueda tratarla igual en el flujo normal del daemon, no
# solo en la búsqueda de límite.
MARCADOR_TIENDA_NO_CONFIRMADA = "tienda no confirmada en resultados de búsqueda"

# Texto EXACTO de la página de error genérica que Glovo muestra cuando su propio
# backend tiene problemas bajo carga (confirmado con captura real 27/08, ver
# PaginaSobrecargadaError) -- no es un mensaje nuestro, es el suyo.
MARCADOR_PAGINA_SOBRECARGADA = "Oh, no!"


# Antes SIEMPRE el mismo UA + mismo viewport exacto (800x900) en TODOS los workers,
# TODAS las peticiones -- huella idéntica de sesión en sesión, sea cual sea la IP.
# Pequeño pool de UAs reales de escritorio (Windows, navegadores/versiones que de
# verdad se ven hoy) + viewport con algo de variación, elegidos al azar en cada
# _run_once (27/08, uno de los cambios probados junto al backoff largo de
# PaginaSobrecargadaError -- ver docstring de esa excepción).
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]


def _viewport_aleatorio() -> dict:
    return {"width": random.randint(780, 900), "height": random.randint(860, 960)}


async def _pagina_muestra_error_generico(page) -> bool:
    """True si la página actual es la de error genérico del sitio (ver
    MARCADOR_PAGINA_SOBRECARGADA) -- para distinguir "el sitio nos dijo que tiene un
    problema" de un timeout/fallo nuestro cualquiera. Silencioso ante cualquier fallo
    al leer la página (si ni eso se puede leer, mejor tratarlo como el error normal
    de siempre que como este caso especial)."""
    try:
        texto = await page.inner_text("body", timeout=2000)
        return MARCADOR_PAGINA_SOBRECARGADA in texto
    except Exception:
        return False


@dataclass
class ResultadoChequeo:
    disponible: bool
    tiempo_entrega_min: Optional[int] = None
    comisiones: Optional[float] = None
    mensaje_bloqueo: Optional[str] = None
    url_captura: Optional[str] = None
    status_http: Optional[int] = None
    error_texto: Optional[str] = None
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)


class BaseAggregatorScraper:
    """Clase base para scrapers de agregadores. Cada subclase implementa `_verificar`."""

    nombre_agregador: str = "base"
    url_base: str = ""

    # Si el sitio muestra un challenge anti-bot en modo headless, se reintenta una vez
    # con una ventana visible para que un humano lo resuelva a mano -- pero SOLO tiene
    # sentido cuando alguien ha lanzado el scraper a mano sabiendo que va a estar
    # pendiente. Por defecto False: el daemon/scheduler/scripts de background NUNCA
    # deben abrir ventanas ni disparar notificaciones sin que nadie lo esté esperando
    # (confirmado en vivo 08/08: sys.stdin.isatty() daba falso positivo incluso en un
    # proceso lanzado en background, así que "hay terminal" no basta como filtro --
    # cada intento de challenge reintentaba con ventana + notificación, decenas de
    # veces, sin que hubiera un humano real delante). Los scripts interactivos que sí
    # quieran este flujo lo activan ellos mismos (ver _check_ubereats_rapido.py).
    permitir_resolucion_manual: bool = False

    # Si nadie responde en este tiempo, se da por perdido el intento manual y se falla de
    # forma controlada en vez de bloquear el proceso para siempre.
    timeout_resolucion_manual_seg: int = 90

    # Algunos sitios (p.ej. Uber Eats) bloquean Chromium headless vía Cloudflare incluso
    # con stealth aplicado, pero dejan pasar una ventana visible sin intervención humana.
    iniciar_headless: bool = True

    # Confirmado en vivo 08/08: con iniciar_headless=False pero la ventana mandada fuera
    # de pantalla (ver _run_once), Uber Eats seguía bloqueando con challenge el 100% de
    # las veces -- "no headless" no basta, hace falta que la ventana esté genuinamente
    # en pantalla (misma huella que un usuario real). En cuanto se dejó en pantalla de
    # verdad, dejó de bloquear. Así que para este sitio la ventana se queda siempre
    # visible, no solo durante una resolución manual.
    mantener_visible: bool = False

    # Setup del usuario (08/08): pantalla principal 1920x1080 a la izquierda (x=0),
    # segunda pantalla 1920x1080 a la derecha (x=1920) -- ahí quiere la ventana visible,
    # junto a la ventana de Claude, en vez de tapando la pantalla principal.
    # Valor por defecto para un único proceso. Cuando corren varios procesos en
    # paralelo (ver --ventana-slot en buscar_limite_cobertura.py), cada uno pisa
    # estos dos atributos de clase con una celda distinta de una rejilla en el
    # segundo monitor -- si todos usaran el mismo punto, sus ventanas de Uber Eats
    # quedarían apiladas exactamente encima unas de otras y un challenge real solo
    # sería visible/resoluble en la que quedara arriba del todo.
    posicion_ventana_visible: str = "1930,40"
    tamano_ventana_visible: str = "900,1000"

    # True de normal (comportamiento de siempre). Solo se pone a False desde fuera
    # (ver revalidar_completo.py --permitir-imagenes) para una prueba puntual 26/08:
    # comprobar si bloquear imágenes es lo que dispara la página de error genérica
    # de Glovo ("Oh, no! It looks like there's a problem") bajo carga -- hipótesis
    # del usuario, sin confirmar todavía. No tocar este default fuera de esa prueba.
    bloquear_recursos: bool = True

    # Proxy opcional (27/08, experimento de rotación de IP -- ver config.PROXIES y
    # revalidar_completo.py --proxy-index). None = sale por la IP propia, como
    # siempre. dict con {"server", "username", "password"} = todo el tráfico de
    # este worker (todas sus peticiones, todos sus reintentos) sale por ese proxy.
    proxy: dict | None = None

    def __init__(self, timeout_seg: int = 30, retry_max: int = 3):
        self.timeout_ms = timeout_seg * 1000
        self.retry_max = retry_max
        # True solo cuando la ventana visible es para que un humano resuelva un
        # challenge a mano -- ahí SÍ debe verse en pantalla. El resto de veces que se
        # corre sin headless (p.ej. Uber Eats de forma rutinaria) es solo para no
        # parecer un bot, sin nadie mirando, así que esa ventana se manda fuera de
        # pantalla en vez de interrumpir al usuario mientras trabaja.
        self._modo_resolucion_manual = False
        SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

    async def verificar_disponibilidad(
        self, tienda_nombre: str, direccion: str, lat: float | None = None, lng: float | None = None
    ) -> ResultadoChequeo:
        """Punto de entrada público: lanza browser, reintenta y captura errores.

        lat/lng (27/08, opcionales): coordenadas reales del punto, si el caller las
        tiene (main.py sí las tiene siempre, ver direccion["lat"]/["lng"]). Solo las
        usa GlovoScraper de momento (ver su _verificar) para saltarse el flujo de
        interfaz de "escribir dirección -> esperar sugerencias -> elegir tipo de
        lugar -> confirmar" (~7 pasos) escribiendo la cookie de dirección
        directamente -- confirmado en vivo que Glovo guarda la dirección de entrega
        en una cookie de cliente en texto plano (`glovo_delivery_address`), no en el
        servidor. Otros scrapers ignoran estos parámetros sin más."""
        try:
            return await self._verificar_con_retry(tienda_nombre, direccion, lat, lng)
        except Exception as exc:
            logger.error(
                "%s: fallo definitivo verificando '%s' en '%s': %s",
                self.nombre_agregador,
                tienda_nombre,
                direccion,
                exc,
            )
            return ResultadoChequeo(disponible=False, error_texto=str(exc))

    async def _verificar_con_retry(
        self, tienda_nombre: str, direccion: str, lat: float | None = None, lng: float | None = None
    ) -> ResultadoChequeo:
        headless = self.iniciar_headless
        last_exc = None
        espera_seg = None  # None = usar el backoff normal (2**intento)

        for intento in range(self.retry_max + 1):
            espera_seg = None
            try:
                return await self._run_once(tienda_nombre, direccion, headless=headless, lat=lat, lng=lng)
            except PaginaSobrecargadaError as exc:
                last_exc = exc
                # El SITIO dijo que tiene un problema (ver docstring de la excepción)
                # -- no es un fallo nuestro de red/timeout, es su backend
                # sobrecargado. 2s/4s de backoff normal solo le añade más carga a los
                # pocos segundos; aquí esperamos mucho más (30-60s con aleatoriedad,
                # para no sincronizar el reintento de varios workers en el mismo
                # instante) a ver si para entonces ya se recuperó.
                espera_seg = random.uniform(30, 60)
                logger.warning(
                    "%s: la página mostró su propio error de sobrecarga (intento %d/%d) -- "
                    "esperando %.0fs antes de reintentar (más que un fallo normal, a propósito).",
                    self.nombre_agregador, intento + 1, self.retry_max, espera_seg,
                )
            except ChallengeDetectedError as exc:
                last_exc = exc
                # OJO: antes esto comprobaba "and headless", pensado solo para
                # scrapers que arrancan headless (JustEat/Glovo). Uber Eats arranca
                # ya con headless=False (lo necesita para no toparse con
                # Cloudflare), así que esa condición nunca era cierta para él y
                # nunca pasaba a modo visible-de-verdad -- seguía reintentando con
                # la ventana oculta fuera de pantalla (ver _run_once) para
                # siempre, sin que un humano pudiera ver ni resolver el challenge.
                # Lo que importa no es si es headless, es si ya se le dio una
                # oportunidad con ventana genuinamente visible.
                if self.permitir_resolucion_manual and not self._modo_resolucion_manual:
                    logger.warning(
                        "%s: challenge anti-bot detectado. Reintentando con ventana visible "
                        "para resolverlo manualmente...",
                        self.nombre_agregador,
                    )
                    headless = False
                    self._modo_resolucion_manual = True
                else:
                    logger.warning(
                        "%s: challenge anti-bot persiste (intento %d/%d).",
                        self.nombre_agregador,
                        intento + 1,
                        self.retry_max,
                    )
            except Exception as exc:
                last_exc = exc
                headless = self.iniciar_headless
                self._modo_resolucion_manual = False
                logger.warning(
                    "%s falló (intento %d/%d): %s",
                    self.nombre_agregador,
                    intento + 1,
                    self.retry_max,
                    exc,
                )

            if intento < self.retry_max:
                await asyncio.sleep(espera_seg if espera_seg is not None else 2**intento)

        raise last_exc

    async def _run_once(
        self, tienda_nombre: str, direccion: str, headless: bool,
        lat: float | None = None, lng: float | None = None,
    ) -> ResultadoChequeo:
        args = ["--disable-blink-features=AutomationControlled"]
        if not headless:
            if self._modo_resolucion_manual or self.mantener_visible:
                # Ventana genuinamente en pantalla, en la segunda pantalla (derecha),
                # junto a la ventana de Claude -- ni tapa la pantalla principal ni
                # queda fuera de vista (que es lo que hacía que Uber Eats la bloqueara).
                args.append(f"--window-position={self.posicion_ventana_visible}")
                args.append(f"--window-size={self.tamano_ventana_visible}")
            else:
                # Se manda fuera del área visible para no taparte la pantalla mientras
                # trabajas -- solo vale para sitios donde de verdad no importa que la
                # ventana esté fuera de pantalla (Uber Eats no entra aquí, ver arriba).
                args.append("--window-position=-32000,-32000")
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=headless,
                args=args,
                proxy=self.proxy,
            )
            try:
                context = await browser.new_context(
                    user_agent=random.choice(_USER_AGENTS),
                    viewport=_viewport_aleatorio(),
                    locale="es-ES",
                )
                await _STEALTH.apply_stealth_async(context)
                # No necesitamos ver nada: solo leemos texto/atributos del DOM. Bloquear
                # imágenes, fuentes y vídeo reduce el peso de cada página bastante (promos,
                # carruseles, iconos) sin tocar el HTML/CSS que el scraper sí necesita leer.
                # EXCEPCIÓN: en modo resolución manual (o mantener_visible, p.ej. Uber
                # Eats) la ventana es justo para que un humano pueda ver un challenge
                # anti-bot si aparece -- si se bloquean sus recursos, el propio widget
                # del captcha no puede pintarse. Confirmado en vivo 08/08: con
                # mantener_visible=True pero esta excepción atada solo a
                # _modo_resolucion_manual, el captcha seguía saliendo con las imágenes
                # rotas en el primer intento (antes de que _modo_resolucion_manual se
                # active, que solo pasa en el REINTENTO tras un ChallengeDetectedError).
                if self.bloquear_recursos and not self._modo_resolucion_manual and not self.mantener_visible:
                    await context.route("**/*", _bloquear_recursos_pesados)
                # Estos sitios tienen carruseles/banners promocionales en autoplay. Playwright
                # espera a que un elemento esté "estable" (que deje de moverse) antes de hacer
                # click/fill, así que una animación de fondo lo hace reintentar con scroll una
                # y otra vez — desperdicia tiempo en algo que debería ser instantáneo. Cortamos
                # el problema de raíz desactivando animaciones/transiciones CSS en toda la
                # página, antes de que cargue nada.
                await context.add_init_script(
                    """
                    const estilo = document.createElement('style');
                    estilo.textContent = `*, *::before, *::after {
                        animation-duration: 0s !important;
                        animation-delay: 0s !important;
                        transition-duration: 0s !important;
                        transition-delay: 0s !important;
                        scroll-behavior: auto !important;
                    }`;
                    document.documentElement.appendChild(estilo);

                    // Glovo pide geolocalización al cargar -- en headless nunca se ve
                    // (Chromium deniega el prompt sin mostrar nada), pero con ventana
                    // visible (mantener_visible) sale el globo nativo de permiso de
                    // Chrome, que Playwright no puede tocar (es UI del navegador, no
                    // del DOM) y que bloquea la interacción con la página hasta que un
                    // humano lo cierra (confirmado en vivo 27/08: reintentos por
                    // timeout esperando el buscador mientras el globo seguía abierto).
                    // Se sobreescribe la API antes de que cargue nada para que la
                    // página reciba un PERMISSION_DENIED al instante, igual que pasaría
                    // en headless -- mismo comportamiento en los dos modos.
                    if (navigator.geolocation) {
                      const denegar = (_ok, error) => {
                        if (error) error({ code: 1, message: 'User denied Geolocation', PERMISSION_DENIED: 1 });
                      };
                      navigator.geolocation.getCurrentPosition = denegar;
                      navigator.geolocation.watchPosition = denegar;
                    }
                    """
                )
                page = await context.new_page()
                page.set_default_timeout(self.timeout_ms)
                resultado = await self._verificar(page, tienda_nombre, direccion, lat=lat, lng=lng)
                if not resultado.disponible and not resultado.error_texto:
                    # Antes de aceptar un "no disponible" como dato real: el chequeo de
                    # challenge (_comprobar_challenge) solo se hace una vez, justo al
                    # cargar la página inicial -- si el sitio muestra un reCAPTCHA más
                    # adelante en el flujo (tras poner la dirección o buscar), no se
                    # detecta ahí, y el resto del código puede malinterpretar esa
                    # pantalla como "tienda no encontrada". Caso real confirmado: la
                    # captura subida como "evidencia" de una transición DD->DND era un
                    # reCAPTCHA de Uber Eats, no la página de resultados. Se vuelve a
                    # comprobar aquí, justo antes de dar el resultado por bueno -- si
                    # hay challenge, esto lanza ChallengeDetectedError y pasa por el
                    # mecanismo normal de reintento en vez de guardarse como dato real.
                    await self._comprobar_challenge(page)
                # Captura de CADA chequeo (disponible, no disponible o error), no
                # solo los "interesantes" -- confirmado un caso real donde Glovo dio
                # un resultado con confianza total pero sobre la DIRECCIÓN
                # EQUIVOCADA (bug de coordenadas en bruto, ver main.py); sin la
                # captura no había forma de detectarlo desde el dashboard. Se sube
                # a KG siempre (ver main.py), no solo cuando el backend confirma
                # que es una transición.
                if not resultado.url_captura:
                    contexto = (
                        "disponible" if resultado.disponible
                        else "error" if resultado.error_texto
                        else "no_disponible"
                    )
                    resultado.url_captura = await self.screenshot_on_error(page, contexto)
                return resultado
            finally:
                await browser.close()

    async def _verificar(
        self, page, tienda_nombre: str, direccion: str,
        lat: float | None = None, lng: float | None = None,
    ) -> ResultadoChequeo:
        raise NotImplementedError("Cada scraper debe implementar _verificar()")

    async def _comprobar_challenge(self, page):
        """Detecta páginas de verificación anti-bot (Cloudflare, WAF genérico).

        En modo headless, lanza ChallengeDetectedError para que se reintente con ventana
        visible. En modo visible, espera a que un humano lo resuelva — pero SOLO si hay
        una terminal interactiva de verdad delante (sys.stdin.isatty()): el scheduler corre
        desatendido en background, y esperar input() ahí cuelga el proceso para siempre
        (nadie va a pulsar Enter). En ese caso falla directo, de forma controlada.
        """
        try:
            # page.evaluate con document.body.innerText (no locator().inner_text()
            # de Playwright) -- confirmado en vivo el 08/08 que el método de
            # Playwright puede leer texto de dentro de <script> (JSON de traducciones
            # interno de Uber Eats con la palabra "cloudflare" y "comprobación de
            # seguridad automatizada" de verdad, pero nunca visibles para un humano),
            # disparando falsos positivos constantes. document.body.innerText es el
            # mismo algoritmo que usa un navegador real para lo que el usuario ve.
            texto = (await page.evaluate("() => document.body.innerText")).lower()
        except Exception:
            return

        coincidencias = [palabra for palabra in CHALLENGE_KEYWORDS if palabra in texto]
        if not coincidencias:
            return

        # Guarda captura + qué frase exacta disparó la detección -- antes esto
        # simplemente lanzaba la excepción sin dejar rastro visual, así que un
        # falso positivo (o uno real) no se podía diagnosticar después.
        ruta_captura = await self.screenshot_on_error(page, "challenge")
        logger.warning(
            "%s: texto de challenge detectado (%s) -- captura: %s",
            self.nombre_agregador, coincidencias, ruta_captura,
        )

        try:
            hay_terminal = sys.stdin.isatty()
        except Exception:
            hay_terminal = False

        # No basta con "no headless": Uber Eats arranca siempre así (lo necesita
        # para no toparse con Cloudflare) pero esa ventana normalmente está fuera
        # de pantalla (ver _run_once) porque nadie la está mirando. El chequeo
        # correcto es _modo_resolucion_manual -- solo True cuando la ventana está
        # realmente colocada en pantalla para que un humano la vea.
        if not self._modo_resolucion_manual or not hay_terminal:
            raise ChallengeDetectedError(f"{self.nombre_agregador}: challenge anti-bot detectado")

        print(
            f"\n>>> {self.nombre_agregador}: se ha abierto una verificación anti-bot en la "
            f"ventana del navegador. Resuélvela manualmente y pulsa Enter aquí en los próximos "
            f"{self.timeout_resolucion_manual_seg}s para continuar...\n"
        )
        _avisar_captcha_pendiente(self.nombre_agregador, self.timeout_resolucion_manual_seg)
        try:
            await asyncio.wait_for(
                asyncio.to_thread(input), timeout=self.timeout_resolucion_manual_seg
            )
        except asyncio.TimeoutError:
            raise ChallengeDetectedError(
                f"{self.nombre_agregador}: challenge anti-bot sin resolver tras "
                f"{self.timeout_resolucion_manual_seg}s de espera"
            )
        except (EOFError, OSError):
            # isatty() puede devolver True aunque no haya nadie de verdad al otro
            # lado (visto en el daemon lanzado por iniciar_daemon.bat via
            # Start-Process: sin stdin real pero isatty() no lo detecta) --
            # input() revienta con EOFError al instante en vez de esperar a que
            # alguien escriba. Mismo desenlace que un timeout: no hay humano
            # disponible, así que se falla de forma controlada en vez de dejar
            # el EOFError sin capturar.
            raise ChallengeDetectedError(
                f"{self.nombre_agregador}: challenge anti-bot detectado sin terminal real disponible"
            )

        # Damos margen a que la página termine de cargar tras resolver el challenge.
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(1500)

    async def screenshot_on_error(self, page, contexto: str) -> Optional[str]:
        try:
            filename = f"{self.nombre_agregador}_{contexto}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            path = SCREENSHOTS_DIR / filename
            await page.screenshot(path=str(path))
            return str(path)
        except Exception as exc:
            logger.warning("No se pudo capturar screenshot: %s", exc)
            return None

    async def guardar_html_debug(self, page, contexto: str) -> Optional[str]:
        """Como screenshot_on_error pero con el HTML real en vez de una imagen --
        las capturas no sirven para diagnosticar fallos de selector porque
        _bloquear_recursos_pesados bloquea las fuentes (rinden como texto
        ilegible), y de todos modos una imagen no deja inspeccionar el DOM.
        Solo se usa en fallos ya reintentados varias veces sin explicación
        clara (ver 'tienda no confirmada' en justeat.py/glovo.py)."""
        try:
            filename = f"{self.nombre_agregador}_{contexto}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
            path = SCREENSHOTS_DIR / filename
            contenido = await page.content()
            path.write_text(contenido, encoding="utf-8")
            return str(path)
        except Exception as exc:
            logger.warning("No se pudo guardar HTML de diagnóstico: %s", exc)
            return None

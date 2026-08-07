import asyncio
import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright
from playwright_stealth import Stealth

logger = logging.getLogger(__name__)

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
    "recaptcha",
)

_STEALTH = Stealth()

_RECURSOS_BLOQUEADOS = ("image", "media", "font")


async def _bloquear_recursos_pesados(route):
    if route.request.resource_type in _RECURSOS_BLOQUEADOS:
        await route.abort()
    else:
        await route.continue_()


class ChallengeDetectedError(Exception):
    """El sitio ha mostrado un challenge anti-bot (Cloudflare u otro WAF)."""


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
    # con una ventana visible para que un humano lo resuelva a mano (solo tiene sentido
    # cuando el scraper se ejecuta de forma interactiva en la máquina local).
    permitir_resolucion_manual: bool = True

    # Si nadie responde en este tiempo, se da por perdido el intento manual y se falla de
    # forma controlada en vez de bloquear el proceso para siempre.
    timeout_resolucion_manual_seg: int = 90

    # Algunos sitios (p.ej. Uber Eats) bloquean Chromium headless vía Cloudflare incluso
    # con stealth aplicado, pero dejan pasar una ventana visible sin intervención humana.
    iniciar_headless: bool = True

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
        self, tienda_nombre: str, direccion: str
    ) -> ResultadoChequeo:
        """Punto de entrada público: lanza browser, reintenta y captura errores."""
        try:
            return await self._verificar_con_retry(tienda_nombre, direccion)
        except Exception as exc:
            logger.error(
                "%s: fallo definitivo verificando '%s' en '%s': %s",
                self.nombre_agregador,
                tienda_nombre,
                direccion,
                exc,
            )
            return ResultadoChequeo(disponible=False, error_texto=str(exc))

    async def _verificar_con_retry(self, tienda_nombre: str, direccion: str) -> ResultadoChequeo:
        headless = self.iniciar_headless
        last_exc = None

        for intento in range(self.retry_max + 1):
            try:
                return await self._run_once(tienda_nombre, direccion, headless=headless)
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
                await asyncio.sleep(2**intento)

        raise last_exc

    async def _run_once(self, tienda_nombre: str, direccion: str, headless: bool) -> ResultadoChequeo:
        args = ["--disable-blink-features=AutomationControlled"]
        if not headless and not self._modo_resolucion_manual:
            # Uber Eats necesita una ventana "real" (no headless) para no toparse con
            # Cloudflare, pero eso no significa que tenga que taparte la pantalla mientras
            # trabajas: se coloca fuera del área visible. Sigue siendo una ventana normal
            # a ojos del sitio (misma huella que una visible), solo que no la ves. Si la
            # ventana visible es para que la resuelva un humano (challenge anti-bot), se
            # deja donde se ve -- ocultarla ahí rompería la resolución manual.
            args.append("--window-position=-32000,-32000")
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=headless,
                args=args,
            )
            try:
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 800, "height": 900},
                    locale="es-ES",
                )
                await _STEALTH.apply_stealth_async(context)
                # No necesitamos ver nada: solo leemos texto/atributos del DOM. Bloquear
                # imágenes, fuentes y vídeo reduce el peso de cada página bastante (promos,
                # carruseles, iconos) sin tocar el HTML/CSS que el scraper sí necesita leer.
                # EXCEPCIÓN: en modo resolución manual la ventana es justo para que un
                # humano vea y resuelva un challenge anti-bot -- si se bloquean sus
                # recursos, el propio widget del captcha no puede pintarse (confirmado
                # visualmente: salía un rectángulo de color liso en vez del reto real).
                if not self._modo_resolucion_manual:
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
                    """
                )
                page = await context.new_page()
                page.set_default_timeout(self.timeout_ms)
                resultado = await self._verificar(page, tienda_nombre, direccion)
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

    async def _verificar(self, page, tienda_nombre: str, direccion: str) -> ResultadoChequeo:
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
            texto = (await page.locator("body").inner_text(timeout=3000)).lower()
        except Exception:
            return

        if not any(palabra in texto for palabra in CHALLENGE_KEYWORDS):
            return

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

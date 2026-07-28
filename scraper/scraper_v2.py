#!/usr/bin/env python3
"""Extractor de reseñas de Krispy Kreme (Google Maps).

Corrige el problema del script anterior: las reseñas viven dentro de un
panel con scroll propio (no la ventana principal), así que Google Maps solo
renderiza ~8 reseñas hasta que se hace scroll sobre ESE panel concreto.
"""
import csv
import json
import os
import re
import shutil
import sqlite3
import sys
import threading
import time
from datetime import datetime

# La consola de Windows usa cp1252 por defecto al redirigir stdout a archivo,
# lo que rompe al imprimir símbolos como ✓.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from selenium import webdriver
from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from common import calcular_sentimiento, fecha_categoria, parse_relative_date  # noqa: E402
import config  # noqa: E402
from stores import DEFAULT_STORE, STORES  # noqa: E402

CURRENT_DATE = datetime.now()

# Qué tienda scrapear: `python scraper_v2.py <clave>` (ver stores.py). Sin
# argumento, usa la tienda por defecto (mantiene el comportamiento anterior).
# `--update` activa el modo incremental (ver UPDATE_MODE más abajo).
_args = [a for a in sys.argv[1:] if not a.startswith("--")]
UPDATE_MODE = "--update" in sys.argv
STORE_KEY = _args[0] if _args else DEFAULT_STORE
if STORE_KEY not in STORES:
    print(f"Tienda desconocida: '{STORE_KEY}'. Opciones: {', '.join(STORES)}")
    sys.exit(1)
STORE_NAME = STORES[STORE_KEY]["nombre"]
STORE_URL = STORES[STORE_KEY]["url"]

# Si el backend lanza este script desde el botón "Actualizar" (ver
# backend/scrape_jobs.py), pasa esta variable con la ruta de un JSON donde
# volcar el progreso para que el dashboard lo muestre como barra/spinner.
STATUS_FILE = os.environ.get("KT_STATUS_FILE")


# Evita que dos scrapers de la MISMA tienda corran a la vez (manual + botón
# "Actualizar", o dos clics seguidos): dos sesiones de Chrome/Selenium para el
# mismo local compiten por CPU/memoria y terminan haciendo que ambas
# revienten con "invalid session id" (nos pasó una vez). El candado es un
# archivo con marca de tiempo; si tiene menos de LOCK_STALE_SECONDS de
# antigüedad, asumimos que sigue corriendo de verdad y abortamos.
LOCK_DIR = os.path.join(os.path.dirname(__file__), "status")
LOCK_PATH = os.path.join(LOCK_DIR, f"{STORE_KEY}.lock")
LOCK_STALE_SECONDS = 3 * 60 * 60  # 3h: más que de sobra para la pasada más larga observada


def acquire_lock():
    os.makedirs(LOCK_DIR, exist_ok=True)
    if os.path.exists(LOCK_PATH):
        age = time.time() - os.path.getmtime(LOCK_PATH)
        if age < LOCK_STALE_SECONDS:
            print(
                f"\n✗ Ya parece haber un scraping en curso para '{STORE_KEY}' "
                f"(candado activo desde hace {int(age)}s: {LOCK_PATH}).\n"
                "Si estás seguro de que no hay ninguno corriendo de verdad, "
                "borra ese archivo y vuelve a intentarlo.",
                flush=True,
            )
            sys.exit(1)
    with open(LOCK_PATH, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))


def release_lock():
    try:
        os.remove(LOCK_PATH)
    except OSError:
        pass


def write_status(**fields):
    if not STATUS_FILE:
        return
    data = {}
    try:
        if os.path.exists(STATUS_FILE):
            with open(STATUS_FILE, encoding="utf-8") as f:
                data = json.load(f)
    except (OSError, json.JSONDecodeError):
        data = {}
    data.update(fields)
    data["tienda"] = STORE_NAME
    data["actualizado"] = datetime.now().isoformat(timespec="seconds")
    try:
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError:
        pass

# Cuántas tarjetas seguidas ya conocidas hacen falta para asumir que llegamos
# a territorio ya scrapeado y podemos parar (modo --update).
STOP_AFTER_KNOWN_STREAK = 15

REVIEW_CARD_SELECTOR = "div.jftiEf[data-review-id]"

FIND_SCROLLABLE_PANEL_JS = """
function findScrollableAncestor(el) {
  let node = el.parentElement;
  while (node) {
    const style = getComputedStyle(node);
    if ((style.overflowY === 'auto' || style.overflowY === 'scroll') && node.scrollHeight > node.clientHeight) {
      return node;
    }
    node = node.parentElement;
  }
  return null;
}
const card = document.querySelector(arguments[0]);
if (!card) return null;
const panel = findScrollableAncestor(card);
return panel;
"""

EXPAND_REVIEWS_JS = """
document.querySelectorAll("button.w8nwRe").forEach((btn) => {
  try { btn.click(); } catch (e) {}
});
"""

EXTRACT_REVIEWS_JS = """
const cards = document.querySelectorAll(arguments[0]);
const out = [];
cards.forEach((card) => {
  function text(sel) {
    const el = card.querySelector(sel);
    return el ? el.textContent.trim() : "";
  }
  // El texto de la RESPUESTA DEL PROPIETARIO usa la misma clase ".wiI7pd"
  // que el comentario del cliente, pero vive dentro de un contenedor
  // ".CDe7pd". Si el cliente no escribió nada (solo puso estrellas), el
  // primer/único ".wiI7pd" de la tarjeta es esa respuesta — sin excluirla
  // aquí, acabábamos guardando el texto de la empresa como si fuera el del
  // cliente.
  function textoCliente() {
    for (const el of card.querySelectorAll(".wiI7pd")) {
      if (!el.closest(".CDe7pd")) return el.textContent.trim();
    }
    return "";
  }
  const ratingLabel = card.querySelector("span.kvMYJc")?.getAttribute("aria-label") || "";
  out.push({
    review_id: card.getAttribute("data-review-id"),
    autor: text(".d4r55"),
    fecha_relativa: text(".rsqaWe"),
    calificacion_raw: ratingLabel,
    texto: textoCliente(),
  });
});
return out;
"""

# Cambiar el orden fuerza a Google Maps a pedir un lote nuevo al servidor con
# un cursor de paginación distinto. Cuando el scroll se estanca del todo en un
# orden, probamos los demás para cubrir más reseñas únicas del total real.
# Textos parciales (no la etiqueta completa): el menú varía por sesión
# ("Calificación más alta" vs "Valoración más alta"), pero "más alta"/"más
# baja"/"recientes" aparecen igual en ambas variantes.
SORT_OPTIONS_TO_TRY = ["recientes", "más alta", "más baja"]

# Permite repetir solo algunos órdenes en una sesión de relleno (p.ej. ya
# tenemos "recientes" cubierto tras una pasada larga y solo queremos
# reintentar "más alta"/"más baja"): `python scraper_v2.py <tienda> --orders=más_alta,más_baja`
_orders_arg = next((a for a in sys.argv[1:] if a.startswith("--orders=")), None)
if _orders_arg:
    SORT_OPTIONS_TO_TRY = [o.replace("_", " ") for o in _orders_arg.split("=", 1)[1].split(",") if o]


# Perfil de Chrome persistente (cookies, sesión de Google si inicias sesión
# con `python scraper_v2.py --login`) — sin esto, cada scrape abría un Chrome
# "en blanco" que olvidaba todo al cerrarse.
#
# Solo `--login` escribe directamente en este perfil "maestro". Los scrapes
# normales usan una COPIA propia por tienda (ver _prepare_work_profile):
# Chrome bloquea el directorio de perfil mientras está en uso, así que si dos
# tiendas (o un --login abierto) compartieran literalmente el mismo
# --user-data-dir, la segunda en llegar revienta con "session not created:
# failed to write first run file". Con una copia por tienda, cada una tiene
# su propio directorio y pueden correr a la vez sin pisarse, heredando igual
# la sesión iniciada en el perfil maestro.
CHROME_PROFILE_MASTER_DIR = os.path.join(os.path.dirname(__file__), "chrome_profile")
CHROME_PROFILE_WORK_DIR = os.path.join(os.path.dirname(__file__), "chrome_profile_work")


# Solo hace falta copiar lo que guarda la sesión (cookies, Local State con la
# clave para descifrarlas); las cachés de Chrome (Service Worker, GPU, shaders,
# etc.) son pesadas, innecesarias, y sus rutas internas son tan profundas que
# sumadas a esta carpeta de OneDrive superan el límite de ruta de Windows.
_PROFILE_COPY_IGNORE = shutil.ignore_patterns(
    "Service Worker", "*Cache*", "GrShaderCache", "ShaderCache", "Crashpad",
    "component_crx_cache", "blob_storage", "Session Storage", "Local Storage",
    "Extension State", "Sessions",
)


def _prepare_work_profile(store_key):
    work_dir = os.path.join(CHROME_PROFILE_WORK_DIR, store_key)
    if os.path.exists(CHROME_PROFILE_MASTER_DIR):
        if os.path.exists(work_dir):
            shutil.rmtree(work_dir, ignore_errors=True)
        try:
            shutil.copytree(CHROME_PROFILE_MASTER_DIR, work_dir, ignore=_PROFILE_COPY_IGNORE)
        except OSError as e:
            print(f"Aviso: no se pudo copiar el perfil de Chrome ({e}), se sigue sin sesión iniciada.", flush=True)
    return work_dir


def build_driver(for_login=False):
    options = webdriver.ChromeOptions()
    options.add_argument("--disable-extensions")
    options.add_argument("--lang=es-ES")
    profile_dir = CHROME_PROFILE_MASTER_DIR if for_login else _prepare_work_profile(STORE_KEY)
    options.add_argument(f"--user-data-dir={profile_dir}")
    options.add_argument("--profile-directory=Default")
    # Google reduce/corta el listado de reseñas cuando detecta una sesión
    # automatizada (navigator.webdriver=true). Estas opciones son la mitigación
    # estándar de Selenium para que la sesión se comporte como un Chrome normal.
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    driver = webdriver.Chrome(options=options)
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"},
    )
    return driver


def dismiss_cookie_consent(driver):
    """Si Google muestra el diálogo de consentimiento, rechaza lo no esencial."""
    try:
        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.XPATH, "//button[.//span[contains(text(),'Rechazar')]] | //button[contains(., 'Rechazar todo')]"))
        )
        buttons = driver.find_elements(By.XPATH, "//button[contains(., 'Rechazar todo')]")
        if buttons:
            buttons[0].click()
            time.sleep(1)
    except Exception:
        pass  # No apareció el diálogo (ya se aceptó antes, u otra región)


def open_reviews_tab(driver, attempts=3):
    """Hace clic en la pestaña 'Opiniones'.

    Los enlaces cortos (maps.app.goo.gl) o URLs de tienda sin los parámetros
    especiales aterrizan en 'Descripción general', donde solo se ven unas
    pocas reseñas destacadas (el mismo bug que tenía el script original).
    Hay que entrar explícitamente a la pestaña de Opiniones para tener el
    panel completo con scroll propio.

    Usa el .click() nativo de Selenium (no JS): los manejadores jsaction de
    Google Maps no siempre reaccionan a un `element.click()` disparado por
    execute_script dentro de una sesión controlada por ChromeDriver, aunque
    ese mismo JS funcione perfectamente en un navegador normal.

    El texto de la pestaña varía según la sesión/variante regional ("Opiniones"
    vs "Reseñas"), así que se busca por coincidencia parcial de cualquiera de
    los dos, no por texto exacto.
    """
    for _ in range(attempts):
        try:
            tabs = driver.find_elements(By.CSS_SELECTOR, '[role="tab"]')
            target = next(
                (t for t in tabs if any(k in t.text.lower() for k in ("opinion", "reseñ"))),
                None,
            )
            if target:
                target.click()
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


# La tira de "reseñas destacadas" de la pestaña Overview también coincide con
# el selector de tarjeta de reseña, pero solo trae unas pocas (3-8) y no tiene
# scroll vertical propio. Si tras abrir Opiniones seguimos viendo menos que
# esto, es que el clic no llegó a registrarse y hay que reintentar.
MIN_REVIEWS_FOR_REAL_PANEL = 9


def ensure_reviews_panel_loaded(driver, attempts=3):
    """Abre la pestaña de reseñas y confirma que cargó el panel real (no la
    tira de destacadas de Overview), reintentando si hace falta."""
    for _ in range(attempts):
        open_reviews_tab(driver)
        try:
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, REVIEW_CARD_SELECTOR))
            )
        except Exception:
            continue
        time.sleep(1.5)
        count = driver.execute_script(
            f"return document.querySelectorAll('{REVIEW_CARD_SELECTOR}').length;"
        )
        if count >= MIN_REVIEWS_FOR_REAL_PANEL:
            return True
    return False


def get_total_reviews_hint(driver):
    """Lee el número total de opiniones que Google Maps anuncia (p. ej. '2.884 opiniones')."""
    try:
        el = driver.find_element(By.XPATH, "//*[contains(text(),'opiniones')]")
        match = re.search(r"([\d.,]+)\s+opiniones", el.text)
        if match:
            return int(match.group(1).replace(".", "").replace(",", ""))
    except Exception:
        pass
    return None


def wait_for_any_reviews(driver, timeout=25):
    end = time.time() + timeout
    while time.time() < end:
        count = driver.execute_script(
            f"return document.querySelectorAll('{REVIEW_CARD_SELECTOR}').length;"
        )
        if count > 0:
            return count
        time.sleep(1)
    return 0


def switch_sort(driver, label_text, attempts=6):
    """Abre el menú 'Ordenar' y selecciona la opción dada.

    Cambiar el orden hace que Google Maps recargue el listado desde cero con
    un cursor de paginación distinto, lo que en la práctica revela reseñas
    que en el orden anterior no llegaban a cargarse. Usa clics nativos de
    Selenium (ver open_reviews_tab) en vez de JS puro.

    El aria-label del botón varía según la sesión ("Ordenar opiniones" vs
    "Ordenar reseñas" — mismo problema que la pestaña de Opiniones/Reseñas),
    así que se busca por coincidencia parcial.

    Tras sesiones largas de scroll (miles de tarjetas) el clic al botón a
    veces no abre el menú al primer intento — se reintenta con más paciencia
    y, si nada responde, se vuelve a comprobar el diálogo de cookies por si
    reapareció tapando el botón.
    """
    for attempt in range(attempts):
        try:
            # find_element (singular) coge el primero del DOM aunque no sea
            # visible; tras muchas horas de sesión puede haber más de un
            # candidato y el visible no ser el primero, así que filtramos.
            candidates = driver.find_elements(By.XPATH, "//button[contains(@aria-label, 'rdenar')]")
            btn = next((b for b in candidates if b.is_displayed()), None)
            if btn is None:
                raise RuntimeError(f"botón 'Ordenar' no visible ({len(candidates)} candidatos en el DOM)")
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
            btn.click()
            try:
                WebDriverWait(driver, 4).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, 'div[role="menu"] [role="menuitemradio"]'))
                )
            except Exception:
                pass
            items = driver.find_elements(By.CSS_SELECTOR, 'div[role="menu"] [role="menuitemradio"]')
            target = next((i for i in items if label_text.lower() in i.text.strip().lower()), None)
            if target:
                target.click()
                return True
            print(f"[switch_sort] intento {attempt + 1}/{attempts}: menú abierto pero sin opción '{label_text}' (opciones vistas: {[i.text.strip() for i in items]})", flush=True)
        except Exception as e:
            print(f"[switch_sort] intento {attempt + 1}/{attempts} falló: {e}", flush=True)
            dismiss_cookie_consent(driver)
        time.sleep(2.5)
    return False


def load_fresh_page(driver):
    """Carga la página desde cero y espera a que aparezcan las primeras
    reseñas. Se usa antes de cada cambio de orden para partir de un DOM
    limpio, en vez de intentar pivotar el orden sobre un listado ya scrolleado
    cientos de veces (donde el menú de orden puede dejar de responder).

    Devuelve True solo si confirmó el panel real de reseñas — si se queda en
    la pestaña de Overview (destacadas), el botón "Ordenar" existe en el DOM
    pero no es visible, y cambiar de orden falla siempre en ese caso."""
    driver.get(STORE_URL)
    time.sleep(3)
    dismiss_cookie_consent(driver)
    return ensure_reviews_panel_loaded(driver)


def get_existing_review_ids(tienda):
    """IDs de reseñas que ya tenemos guardadas de esta tienda (para el modo
    --update: nos deja parar en cuanto pisamos territorio ya conocido)."""
    if not os.path.exists(config.DB_PATH):
        return set()
    conn = sqlite3.connect(config.DB_PATH)
    cur = conn.cursor()
    try:
        cur.execute("SELECT review_id FROM reviews WHERE tienda = ?", (tienda,))
        ids = {row[0] for row in cur.fetchall()}
    except sqlite3.OperationalError:
        ids = set()  # tabla/columna aún no existe (primera vez)
    conn.close()
    return ids


def save_total_google(tienda, total_google):
    """Guarda el total de reseñas que Google anuncia para esta tienda, para
    que el dashboard pueda marcar con un check cuando ya tenemos el 100%."""
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS store_meta (
            tienda TEXT PRIMARY KEY,
            total_google INTEGER,
            actualizado TEXT
        )
    """)
    conn.execute("""
        INSERT INTO store_meta (tienda, total_google, actualizado)
        VALUES (?, ?, datetime('now'))
        ON CONFLICT(tienda) DO UPDATE SET
            total_google=excluded.total_google, actualizado=excluded.actualizado
    """, (tienda, total_google))
    conn.commit()
    conn.close()


def run_scroll_pass(driver, panel, total_hint, pass_label, existing_ids=None):
    """Hace scroll sobre `panel` hasta estancarse, guardando checkpoints.

    Si `existing_ids` se indica (modo --update, orden 'Más recientes'), para
    en cuanto ve STOP_AFTER_KNOWN_STREAK tarjetas seguidas que ya están en la
    BD — todo lo que venga después, en orden cronológico, ya lo tenemos.
    """
    previous_count = 0
    last_checkpoint_count = 0
    no_growth_iterations = 0
    iteration = 0
    pause = config.SCROLL_PAUSE_SECONDS

    # Google Maps sirve las reseñas en lotes de red con latencia variable:
    # a veces se estanca 10-15 iteraciones y luego sigue cargando. En vez de
    # rendirnos con un umbral fijo, vamos alargando la pausa mientras no haya
    # crecimiento y solo damos por terminado tras un estancamiento largo.
    while (
        iteration < config.MAX_SCROLL_ITERATIONS
        and no_growth_iterations < config.MAX_ITERATIONS_WITHOUT_GROWTH
    ):
        if iteration % config.EXPAND_EVERY_N_ITERATIONS == 0:
            driver.execute_script(EXPAND_REVIEWS_JS)

        try:
            driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight;", panel)
        except StaleElementReferenceException:
            # Google Maps a veces reconstruye el panel de golpe (p.ej. tras un
            # hipo de red). Si la referencia queda obsoleta, la recuperamos en
            # vez de morir y perder todo lo escaneado en esta pasada.
            print(f"\n[{pass_label}] Panel obsoleto, relocalizando...", flush=True)
            panel = driver.execute_script(FIND_SCROLLABLE_PANEL_JS, REVIEW_CARD_SELECTOR)
            if panel is None:
                print(f"[{pass_label}] No se pudo relocalizar el panel, se corta esta pasada.", flush=True)
                break
            time.sleep(1)
            continue
        time.sleep(pause)

        current_count = driver.execute_script(
            f"return document.querySelectorAll('{REVIEW_CARD_SELECTOR}').length;"
        )

        print(
            f"[{pass_label}] Scroll {iteration} | reseñas visibles: {current_count}"
            + (f" / ~{total_hint}" if total_hint else "")
            + f" | pausa: {pause:.1f}s",
            flush=True,
        )

        if existing_ids is not None:
            visible_ids = driver.execute_script(
                f"return [...document.querySelectorAll('{REVIEW_CARD_SELECTOR}')]"
                ".map(el => el.getAttribute('data-review-id'));"
            )
            nuevas = sum(1 for rid in visible_ids if rid and rid not in existing_ids)
            write_status(
                status="running", mensaje=pass_label, reviews_visibles=current_count,
                nuevas=nuevas, total_google=total_hint,
            )
            if current_count >= STOP_AFTER_KNOWN_STREAK:
                tail = visible_ids[-STOP_AFTER_KNOWN_STREAK:]
                if all(rid in existing_ids for rid in tail):
                    print(
                        f"\n[{pass_label}] {STOP_AFTER_KNOWN_STREAK} reseñas seguidas ya "
                        "conocidas — el resto ya está en la BD, paramos aquí.",
                        flush=True,
                    )
                    break
        else:
            write_status(status="running", mensaje=pass_label, reviews_visibles=current_count, total_google=total_hint)

        if current_count > previous_count:
            previous_count = current_count
            no_growth_iterations = 0
            pause = config.SCROLL_PAUSE_SECONDS
        else:
            no_growth_iterations += 1
            if no_growth_iterations % 5 == 0:
                pause = min(pause * 1.5, config.MAX_SCROLL_PAUSE_SECONDS)

        # Checkpoint: si el proceso se corta a mitad de camino, no perdemos
        # todo lo ya cargado.
        if current_count - last_checkpoint_count >= config.CHECKPOINT_EVERY_N_REVIEWS:
            print(f"Guardando checkpoint ({pass_label}, {current_count} en pantalla)...", flush=True)
            driver.execute_script(EXPAND_REVIEWS_JS)
            checkpoint_raw = driver.execute_script(EXTRACT_REVIEWS_JS, REVIEW_CARD_SELECTOR)
            save_outputs(process_reviews(checkpoint_raw))
            last_checkpoint_count = current_count

        if total_hint and current_count >= total_hint:
            break

        iteration += 1

    print(f"\n[{pass_label}] Scroll terminado tras {iteration} iteraciones. Expandiendo texto restante...")
    driver.execute_script(EXPAND_REVIEWS_JS)
    time.sleep(1)
    return driver.execute_script(EXTRACT_REVIEWS_JS, REVIEW_CARD_SELECTOR)


def scrape_all_reviews():
    print("Iniciando Chrome...")
    driver = build_driver()
    all_raw = []
    try:
        print("Accediendo a Google Maps...")
        driver.get(STORE_URL)
        time.sleep(4)
        dismiss_cookie_consent(driver)

        # El total ("X opiniones") vive en el resumen de calificación, que es
        # más fiable justo después de cargar la página (antes de entrar a la
        # pestaña Opiniones) — una vez dentro de esa pestaña, ese resumen a
        # veces ya no está en el DOM. Se intenta aquí primero y, si falla, se
        # reintenta después de abrir el panel por si acaso.
        total_hint = get_total_reviews_hint(driver)

        print("Abriendo la pestaña de Opiniones...")
        if not ensure_reviews_panel_loaded(driver):
            print("Aviso: no se confirmó la carga completa del panel de reseñas, se continúa igualmente.", flush=True)

        if not total_hint:
            total_hint = get_total_reviews_hint(driver)
        if total_hint:
            print(f"Google Maps anuncia ~{total_hint} opiniones en total", flush=True)
            save_total_google(STORE_NAME, total_hint)

        existing_ids = None
        if UPDATE_MODE:
            existing_ids = get_existing_review_ids(STORE_NAME)
            print(f"Modo actualización: ya tenemos {len(existing_ids)} reseñas de {STORE_NAME} guardadas.", flush=True)
            write_status(status="running", mensaje="Buscando reseñas nuevas…", ya_conocidas=len(existing_ids), nuevas=0)
            if switch_sort(driver, "recientes"):
                wait_for_any_reviews(driver)
            else:
                print("No se pudo poner el orden 'Más recientes'; se sigue con el orden por defecto (más lento).", flush=True)

        panel = driver.execute_script(FIND_SCROLLABLE_PANEL_JS, REVIEW_CARD_SELECTOR)
        if panel is None:
            raise RuntimeError(
                "No se encontró el panel scrollable de reseñas. "
                "Es probable que Google Maps haya cambiado su estructura HTML."
            )

        pass_label = "Más recientes (actualización)" if UPDATE_MODE else "Más relevantes (por defecto)"
        all_raw += run_scroll_pass(driver, panel, total_hint, pass_label, existing_ids=existing_ids)
        unique_so_far = len({r["review_id"] for r in all_raw if r.get("review_id")})
        print(f"Únicas tras el orden por defecto: {unique_so_far}", flush=True)

        if UPDATE_MODE:
            # En modo actualización no probamos otros órdenes: el objetivo es
            # solo coger lo nuevo, no maximizar cobertura del histórico.
            print(f"Tarjetas de reseña extraídas en total: {len(all_raw)}")
            return all_raw

        for label in SORT_OPTIONS_TO_TRY:
            if total_hint and unique_so_far >= total_hint:
                break
            print(f"\nReiniciando Chrome (proceso nuevo) para probar orden: {label}...", flush=True)
            # Tras una pasada de scroll muy larga la misma pestaña/proceso de
            # Chrome queda "fatigado" (mucho DOM acumulado) y las recargas
            # dejan de cargar el panel real de reseñas. En vez de solo
            # recargar la página, se cierra el driver y se abre uno
            # completamente nuevo (mismo perfil, así que las cookies/sesión
            # se mantienen) antes de cada orden alternativo.
            driver.quit()
            driver = build_driver()
            # Tras una pasada de scroll muy larga, la primera recarga a veces
            # no basta (el driver/la página quedan en un estado raro) — se
            # reintenta una vez más con una recarga completamente nueva antes
            # de rendirse con este orden.
            switched = False
            for sort_retry in range(4):
                panel_ok = load_fresh_page(driver)
                if not panel_ok:
                    print(f"Recarga {sort_retry + 1}/4: no se confirmó el panel de reseñas (se quedó en Overview), reintentando recarga...", flush=True)
                    continue
                if switch_sort(driver, label):
                    switched = True
                    break
                print(f"Reintento de recarga+orden para '{label}' (intento {sort_retry + 1}/4) falló.", flush=True)
            if not switched:
                print(f"No se pudo cambiar el orden a '{label}', se omite este intento.", flush=True)
                continue
            if wait_for_any_reviews(driver) == 0:
                print(f"No cargaron reseñas tras cambiar a '{label}', se omite.", flush=True)
                continue
            panel = driver.execute_script(FIND_SCROLLABLE_PANEL_JS, REVIEW_CARD_SELECTOR)
            if panel is None:
                print(f"No se encontró el panel tras cambiar a '{label}', se omite.", flush=True)
                continue
            all_raw += run_scroll_pass(driver, panel, total_hint, label)
            unique_so_far = len({r["review_id"] for r in all_raw if r.get("review_id")})
            print(f"Únicas acumuladas tras '{label}': {unique_so_far}", flush=True)

        print(f"Tarjetas de reseña extraídas en total (con posibles duplicados entre pasadas): {len(all_raw)}")
        return all_raw

    finally:
        driver.quit()
        print("Chrome cerrado")


def parse_rating(calificacion_raw: str):
    match = re.search(r"(\d+)", calificacion_raw)
    return int(match.group(1)) if match else None


def process_reviews(raw_reviews):
    processed = []
    seen_ids = set()
    for r in raw_reviews:
        review_id = r.get("review_id")
        if not review_id or review_id in seen_ids:
            continue
        seen_ids.add(review_id)

        rating = parse_rating(r.get("calificacion_raw", ""))
        fecha_dt = parse_relative_date(r.get("fecha_relativa", ""), CURRENT_DATE)
        categoria = fecha_categoria(fecha_dt)
        sentiment, sentiment_score = calcular_sentimiento(r.get("texto", ""), rating)

        es_reciente = bool(fecha_dt and (CURRENT_DATE - fecha_dt).days <= 120)

        processed.append({
            "review_id": review_id,
            "tienda": STORE_NAME,
            "autor": r.get("autor", "").strip(),
            "fecha": r.get("fecha_relativa", "").strip(),
            "fecha_datetime": fecha_dt.strftime("%Y-%m-%d") if fecha_dt else None,
            "fecha_categoria": categoria,
            "calificación": f"{rating}★" if rating else "No especificada",
            "calificacion_num": rating,
            "texto": r.get("texto", "").strip(),
            "es_abril_o_reciente": es_reciente,
            "sentiment": sentiment,
            "sentiment_score": sentiment_score,
        })
    return processed


def save_to_sqlite(reviews, db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            review_id TEXT PRIMARY KEY,
            tienda TEXT,
            autor TEXT,
            fecha TEXT,
            fecha_datetime TEXT,
            fecha_categoria TEXT,
            calificacion TEXT,
            calificacion_num INTEGER,
            texto TEXT,
            es_reciente INTEGER,
            sentiment TEXT,
            sentiment_score REAL
        )
    """)
    # Migración idempotente para bases de datos creadas antes de añadir
    # soporte multi-tienda.
    try:
        cur.execute("ALTER TABLE reviews ADD COLUMN tienda TEXT")
        cur.execute("UPDATE reviews SET tienda = 'ParqueSur' WHERE tienda IS NULL")
    except sqlite3.OperationalError:
        pass  # La columna ya existía

    # Migración idempotente para hora exacta y respuesta del negocio — solo
    # las rellena la importación de Google Takeout (import_takeout.py), el
    # scraping de Maps no tiene esos datos, así que aquí solo se asegura de
    # que las columnas existan (quedan NULL en las reseñas scrapeadas).
    cols = {row[1] for row in cur.execute("PRAGMA table_info(reviews)")}
    for col in ("fecha_hora", "respuesta_texto", "respuesta_fecha"):
        if col not in cols:
            cur.execute(f"ALTER TABLE reviews ADD COLUMN {col} TEXT")

    for r in reviews:
        cur.execute("""
            INSERT INTO reviews (
                review_id, tienda, autor, fecha, fecha_datetime, fecha_categoria,
                calificacion, calificacion_num, texto, es_reciente, sentiment, sentiment_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(review_id) DO UPDATE SET
                tienda=excluded.tienda, autor=excluded.autor, fecha=excluded.fecha,
                fecha_datetime=excluded.fecha_datetime, fecha_categoria=excluded.fecha_categoria,
                calificacion=excluded.calificacion, calificacion_num=excluded.calificacion_num,
                texto=excluded.texto, es_reciente=excluded.es_reciente, sentiment=excluded.sentiment,
                sentiment_score=excluded.sentiment_score
        """, (
            r["review_id"], r["tienda"], r["autor"], r["fecha"], r["fecha_datetime"], r["fecha_categoria"],
            r["calificación"], r["calificacion_num"], r["texto"], int(r["es_abril_o_reciente"]),
            r["sentiment"], r["sentiment_score"],
        ))
    conn.commit()
    conn.close()


def load_all_from_sqlite(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM reviews")
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    for r in rows:
        r["calificación"] = r.pop("calificacion")
        r["es_abril_o_reciente"] = bool(r.pop("es_reciente"))
    return rows


def save_outputs(reviews):
    if not reviews:
        print("\n✗ No se extrajeron reseñas en esta pasada (0 nuevas)")
        return

    save_to_sqlite(reviews, config.DB_PATH)
    print(f"✓ SQLite actualizado en: {config.DB_PATH}")

    # JSON/CSV siempre reflejan el TOTAL acumulado en la BD (no solo esta
    # pasada), porque en scraping multi-pasada (distintos órdenes) cada
    # llamada solo trae un subconjunto.
    all_reviews = load_all_from_sqlite(config.DB_PATH)

    with open(config.JSON_OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(all_reviews, f, ensure_ascii=False, indent=2)
    print(f"✓ JSON guardado en: {config.JSON_OUTPUT_PATH} ({len(all_reviews)} reseñas totales)")

    with open(config.CSV_OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(all_reviews[0].keys()))
        writer.writeheader()
        writer.writerows(all_reviews)
    print(f"✓ CSV guardado en: {config.CSV_OUTPUT_PATH}")

    esta_tienda = [r for r in all_reviews if r["tienda"] == STORE_NAME]
    print(f"\n{'='*60}\nESTADÍSTICAS — {STORE_NAME}\n{'='*60}")
    print(f"Reseñas únicas de {STORE_NAME}: {len(esta_tienda)}")
    if esta_tienda:
        positivas = sum(1 for r in esta_tienda if r["sentiment"] == "positivo")
        print(f"Positivas: {positivas} ({positivas*100//len(esta_tienda)}%)")
        print(f"Recientes (<=120 días): {sum(1 for r in esta_tienda if r['es_abril_o_reciente'])}")
    if len(all_reviews) != len(esta_tienda):
        print(f"Total combinado (todas las tiendas en la BD): {len(all_reviews)}")


def run_login_setup():
    """Abre un Chrome real (mismo perfil persistente que usan los scrapes) en
    la página de login de Google y espera a que el usuario inicie sesión a
    mano — nunca se automatiza el login en sí, solo se deja el navegador listo
    para que la persona lo haga. Tras cerrar, la sesión queda guardada en
    CHROME_PROFILE_DIR para los scrapes siguientes."""
    print("Abriendo Chrome para iniciar sesión manualmente...")
    driver = build_driver(for_login=True)
    try:
        driver.get("https://accounts.google.com/")
        print("\nInicia sesión en la ventana de Chrome que se acaba de abrir.")
        input("Cuando hayas terminado (o si prefieres seguir sin iniciar sesión), pulsa Enter aquí para continuar... ")
    finally:
        driver.quit()
        print("Chrome cerrado. La sesión (si iniciaste) queda guardada para los próximos scrapes.")


def run_manual_assist():
    """Abre Chrome con Selenium (para poder capturar los datos con el mismo
    JS que usa el scroll automático) pero deja que la persona haga scroll a
    mano en esa misma ventana. Google Maps corta/limita el scroll
    automatizado pero no el humano (confirmado: el bloqueo desaparece cuando
    el scroll lo hace una persona), así que este modo combina lo mejor de
    los dos: captura automática, scroll humano. Un hilo en segundo plano va
    extrayendo lo que se ha cargado cada pocos segundos mientras el humano
    scrollea, para no perder nada aunque la sesión se corte."""
    print("Iniciando Chrome en modo manual asistido...")
    driver = build_driver()
    all_raw = []
    seen_ids = set()
    stop_event = threading.Event()

    def poll_loop():
        while not stop_event.is_set():
            try:
                driver.execute_script(EXPAND_REVIEWS_JS)
                raw = driver.execute_script(EXTRACT_REVIEWS_JS, REVIEW_CARD_SELECTOR)
                nuevas = 0
                for r in raw:
                    rid = r.get("review_id")
                    if rid and rid not in seen_ids:
                        seen_ids.add(rid)
                        all_raw.append(r)
                        nuevas += 1
                if nuevas:
                    print(f"[modo manual] +{nuevas} nuevas | únicas capturadas: {len(seen_ids)}", flush=True)
                    write_status(status="running", mensaje="Capturando scroll manual…", nuevas=len(seen_ids))
            except Exception as e:
                print(f"[modo manual] aviso al capturar: {e}", flush=True)
            stop_event.wait(2.5)

    try:
        driver.get(STORE_URL)
        time.sleep(4)
        dismiss_cookie_consent(driver)
        if not ensure_reviews_panel_loaded(driver):
            print("Aviso: no se confirmó la carga completa del panel de reseñas, se continúa igualmente.", flush=True)

        total_hint = get_total_reviews_hint(driver)
        if total_hint:
            print(f"Google Maps anuncia ~{total_hint} opiniones en total", flush=True)
            save_total_google(STORE_NAME, total_hint)

        print("\n" + "=" * 60)
        print("MODO MANUAL ASISTIDO")
        print("Haz scroll TÚ MISMO dentro de la ventana de Chrome, sobre el")
        print("panel de reseñas (a la izquierda). El script va guardando en")
        print("segundo plano lo que se va cargando cada ~2.5s.")
        print("Cuando termines de bajar hasta el final (o quieras parar),")
        print("vuelve a esta terminal y pulsa Enter.")
        print("=" * 60 + "\n")

        poller = threading.Thread(target=poll_loop, daemon=True)
        poller.start()
        input("Pulsa Enter aquí cuando termines de hacer scroll manual... ")
        stop_event.set()
        poller.join(timeout=5)

        print(f"\nCapturadas {len(all_raw)} tarjetas de reseña en modo manual.")
        return all_raw
    finally:
        driver.quit()
        print("Chrome cerrado")


if __name__ == "__main__":
    if "--login" in sys.argv:
        run_login_setup()
        sys.exit(0)

    MANUAL_MODE = "--manual" in sys.argv

    print("="*60)
    print(f"EXTRACTOR V2 - KRISPY KREME {STORE_NAME.upper()}")
    print("="*60)
    print(f"Fecha de ejecución: {CURRENT_DATE.strftime('%d/%m/%Y %H:%M')}")
    print("="*60)

    acquire_lock()
    try:
        write_status(status="running", mensaje="Iniciando Chrome…", reviews_visibles=0, nuevas=0)
        try:
            raw = run_manual_assist() if MANUAL_MODE else scrape_all_reviews()
            reviews = process_reviews(raw)
            save_outputs(reviews)
        except Exception as e:
            write_status(status="error", mensaje=str(e))
            raise
        write_status(status="done", mensaje="Completado", reviews_total=len(reviews))
        print("\n✓ ¡Proceso completado!")
    finally:
        release_lock()

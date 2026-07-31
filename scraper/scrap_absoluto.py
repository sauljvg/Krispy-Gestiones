#!/usr/bin/env python3
"""SCRAP ABSOLUTO — recorre TODAS las tiendas y detecta cuáles tienen
reseñas guardadas que ya no aparecen en Google.

Es una herramienta MANUAL, no algo que corra solo: no hay ningún cron ni
botón en la web que la dispare — el contenedor de producción no tiene
Chrome instalado, así que esto solo puede correr desde este ordenador
(Chrome real + tu sesión logueada), cuando tú decidas lanzarla (p.ej. una
vez por semana, o cuando sospeches un desfase). El día a día para traer
reseñas nuevas sigue siendo "Importar Takeout" en la web — esto es solo
para auditar/corregir el desfase ocasional entre lo que tenemos guardado y
lo que Google todavía muestra en público.

Por cada tienda hace primero el check BARATO (sin scroll): compara el número
de cabecera que anuncia Google ("X opiniones") contra lo que ya tenemos en
la BD. Si coinciden, no hace nada y pasa a la siguiente — solo cuando NO
coinciden dispara la reconciliación completa (scraper_v2.py --reconciliar),
que sí hace scroll completo, identifica exactamente cuáles faltan, y sube el
resultado a producción automáticamente (ver _push_produccion en
scraper_v2.py — necesita KT_USERNAME/KT_PIN en el entorno).

Uso:
    python scrap_absoluto.py
"""
import os
import sqlite3
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa: E402
from stores import STORES  # noqa: E402

from selenium import webdriver  # noqa: E402

CHROME_PROFILE_MASTER_DIR = os.path.join(os.path.dirname(__file__), "chrome_profile")


def _build_driver_rapido():
    """Versión mínima de build_driver() (ver scraper_v2.py) para el check
    barato: usa el perfil maestro directamente en vez de copiar uno de
    trabajo por tienda — no hace falta, aquí se abre y cierra Chrome de
    forma secuencial, nunca dos tiendas a la vez."""
    options = webdriver.ChromeOptions()
    options.add_argument("--disable-extensions")
    options.add_argument("--lang=es-ES")
    if os.path.exists(CHROME_PROFILE_MASTER_DIR):
        options.add_argument(f"--user-data-dir={CHROME_PROFILE_MASTER_DIR}")
        options.add_argument("--profile-directory=Default")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    driver = webdriver.Chrome(options=options)
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"},
    )
    return driver


def _total_google_rapido(tienda_key, url):
    """Abre la ficha, lee SOLO el número de cabecera ('X opiniones') y cierra
    Chrome — no entra a la pestaña de Opiniones, no hace scroll. Devuelve
    None si no consiguió leerlo (se trata como "no se pudo comprobar", nunca
    como mismatch)."""
    import re
    from selenium.webdriver.common.by import By

    driver = _build_driver_rapido()
    try:
        driver.get(url)
        time.sleep(4)
        try:
            btns = driver.find_elements(By.XPATH, "//button[contains(., 'Rechazar todo')]")
            if btns:
                btns[0].click()
                time.sleep(1)
        except Exception:
            pass
        try:
            el = driver.find_element(By.XPATH, "//*[contains(text(),'opiniones')]")
            match = re.search(r"([\d.,]+)\s+opiniones", el.text)
            if match:
                return int(match.group(1).replace(".", "").replace(",", ""))
        except Exception:
            pass
        return None
    finally:
        driver.quit()


def _total_en_bd(tienda_nombre):
    if not os.path.exists(config.DB_PATH):
        return 0
    conn = sqlite3.connect(config.DB_PATH)
    try:
        row = conn.execute("SELECT COUNT(*) FROM reviews WHERE tienda = ?", (tienda_nombre,)).fetchone()
        return row[0] if row else 0
    except sqlite3.OperationalError:
        return 0
    finally:
        conn.close()


def main():
    print("=" * 60)
    print("SCRAP ABSOLUTO — todas las tiendas")
    print("=" * 60)
    resumen = []
    for tienda_key, data in STORES.items():
        nombre = data["nombre"]
        total_bd = _total_en_bd(nombre)
        print(f"\n[{nombre}] Comprobando cabecera de Google (sin scroll)...", flush=True)
        total_google = _total_google_rapido(tienda_key, data["url"])

        if total_google is None:
            print(f"[{nombre}] No se pudo leer el número de Google, se omite esta vuelta.", flush=True)
            resumen.append((nombre, total_bd, "?", "omitida"))
            continue

        print(f"[{nombre}] Google anuncia {total_google} · en BD tenemos {total_bd}", flush=True)
        if total_google == total_bd:
            print(f"[{nombre}] Coincide, no hace falta reconciliar.", flush=True)
            resumen.append((nombre, total_bd, total_google, "sin cambios"))
            continue

        print(f"[{nombre}] No coincide — lanzando reconciliación completa (esto tarda)...", flush=True)
        resultado = subprocess.run(
            [sys.executable, "-u", os.path.join(os.path.dirname(__file__), "scraper_v2.py"), tienda_key, "--reconciliar"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )
        resumen.append((nombre, total_bd, total_google, "reconciliada" if resultado.returncode == 0 else "ERROR"))

    print("\n" + "=" * 60)
    print("RESUMEN")
    print("=" * 60)
    for nombre, total_bd, total_google, estado in resumen:
        print(f"  {nombre:<16} BD={total_bd:<6} Google={total_google!s:<6} → {estado}")


if __name__ == "__main__":
    main()

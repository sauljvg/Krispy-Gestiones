"""Mini dashboard local de solo lectura: por tienda y agregador, cuántas direcciones
del grid ya tienen dato real ("vistas") y cuántas faltan, contra la MISMA API en vivo
que usa el scraper (misma X-API-Key del .env) -- no lee ninguna base de datos local, no
hay estado propio que mantener. Pensado para no tener que abrir el dashboard completo
(que pide login de staff) solo para ver el progreso de cobertura.

También cuenta cuántos workers de daemon.py están corriendo ahora mismo en ESTA
máquina (Windows) como proxy de "cuántos a la vez" -- eso sí es local, no viene de la
API (el backend no expone quién está scrapeando en este momento sin sesión de staff).

Uso:
    venv/Scripts/python status_server.py
    -> abre http://localhost:8787 (se refresca solo cada 30s)
"""
import asyncio
import subprocess
from datetime import datetime

from aiohttp import web

import config
from utils import api_client

PUERTO = 8787


def _workers_activos() -> int:
    """Cuenta índices de --worker-index distintos entre los procesos daemon.py vivos en
    esta máquina. No cuenta PIDs a secas: en Windows el launcher del venv arranca el
    intérprete real como un proceso hijo con la MISMA línea de comandos (ver
    detener_daemon.bat), así que un solo worker aparecería como 2 PIDs si contáramos
    procesos en vez de índices."""
    try:
        salida = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                "Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='pythonw.exe'\" "
                "| Where-Object { $_.CommandLine -like '*daemon.py*' } "
                "| ForEach-Object { $_.CommandLine }",
            ],
            capture_output=True, text=True, timeout=10,
        )
        indices = set()
        for linea in salida.stdout.splitlines():
            if "--worker-index" in linea:
                indices.add(linea.split("--worker-index")[1].split()[0])
            elif "daemon.py" in linea:
                indices.add("0")
        return len(indices)
    except Exception:
        return -1  # no se pudo determinar (p.ej. no es Windows o powershell no disponible)


async def _resumen_tienda(tienda: str) -> dict:
    por_agregador = {}
    for agregador in config.AGREGADORES:
        total, faltan = await asyncio.gather(
            api_client.obtener_direcciones(tienda, cercano=False, agregador=agregador),
            api_client.obtener_direcciones(tienda, cercano=False, agregador=agregador, solo_sin_datos=True),
        )
        por_agregador[agregador] = {
            "total": len(total),
            "faltan": len(faltan),
            "vistos": len(total) - len(faltan),
            "faltan_direcciones": sorted(d["direccion_text"] for d in faltan),
        }
    return {"tienda": tienda, "agregadores": por_agregador}


def _celda_html(info: dict) -> str:
    lista = "".join(f"<li>{d}</li>" for d in info["faltan_direcciones"]) or "<li>(ninguna)</li>"
    return (
        f"<td><b>{info['vistos']}</b>/{info['total']} vistos"
        f"<details><summary>{info['faltan']} faltan</summary><ul>{lista}</ul></details></td>"
    )


def _celda_dedup_html(info: dict) -> str:
    lista = "".join(f"<li>{d}</li>" for d in info["faltan_direcciones"]) or "<li>(ninguna)</li>"
    return (
        f"<td><b>{info['vistos']}</b>/{info['total']} vistos"
        f"<details><summary>{info['faltan']} faltan</summary><ul>{lista}</ul></details></td>"
    )


async def _resumen_dedup_seguro() -> dict | None:
    try:
        return await api_client.resumen_cobertura_deduplicada()
    except Exception:
        return None  # endpoint nuevo -- si el backend desplegado todavía no lo tiene, se omite la sección


async def handle(request):
    resumenes, dedup = await asyncio.gather(
        asyncio.gather(*(_resumen_tienda(t) for t in config.TIENDAS_SCHEDULER)),
        _resumen_dedup_seguro(),
    )
    workers = _workers_activos()

    totales = {a: {"vistos": 0, "faltan": 0, "total": 0} for a in config.AGREGADORES}
    for r in resumenes:
        for a, info in r["agregadores"].items():
            totales[a]["vistos"] += info["vistos"]
            totales[a]["faltan"] += info["faltan"]
            totales[a]["total"] += info["total"]

    filas = "".join(
        f"<tr><td>{r['tienda']}</td>" + "".join(_celda_html(r["agregadores"][a]) for a in config.AGREGADORES) + "</tr>"
        for r in resumenes
    )
    fila_totales = "".join(
        f"<td><b>{totales[a]['vistos']}</b>/{totales[a]['total']} vistos, {totales[a]['faltan']} faltan</td>"
        for a in config.AGREGADORES
    )
    cabeceras = "".join(f"<th>{a}</th>" for a in config.AGREGADORES)
    texto_workers = str(workers) if workers >= 0 else "no se pudo determinar"

    if dedup is not None:
        fila_dedup = "".join(_celda_dedup_html(dedup[a]) for a in config.AGREGADORES)
        seccion_dedup = f"""
  <h2>Cobertura real (deduplicada entre tiendas)</h2>
  <p><small>Cuenta sitios reales únicos, no filas -- los grids de tiendas vecinas se solapan
  geográficamente, así que el mismo sitio puede tener una fila por tienda.</small></p>
  <table>
    <thead><tr><th></th>{cabeceras}</tr></thead>
    <tbody><tr><td><b>TOTAL único</b></td>{fila_dedup}</tr></tbody>
  </table>
"""
    else:
        seccion_dedup = "<p><small>(Resumen deduplicado no disponible -- backend sin desplegar todavía.)</small></p>"

    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Estado scraper agregadores</title>
<meta http-equiv="refresh" content="30">
<style>
  body {{ font-family: system-ui, sans-serif; margin: 2rem; color: #222; }}
  table {{ border-collapse: collapse; width: 100%; margin-top: 1rem; }}
  td, th {{ border: 1px solid #ccc; padding: 8px; text-align: left; vertical-align: top; }}
  th {{ background: #fafafa; }}
  tfoot td {{ font-weight: bold; background: #f5f5f5; }}
  details summary {{ cursor: pointer; color: #a00; }}
  details ul {{ margin: 4px 0 0; padding-left: 1.2rem; max-height: 200px; overflow-y: auto; }}
</style></head>
<body>
  <h1>Estado del scraper de agregadores</h1>
  <p><b>Workers corriendo ahora en esta máquina:</b> {texto_workers}</p>
  <p><small>Actualizado {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} — se refresca solo cada 30s</small></p>
  {seccion_dedup}
  <h2>Por tienda (bruto, con solape entre tiendas vecinas)</h2>
  <table>
    <thead><tr><th>Tienda</th>{cabeceras}</tr></thead>
    <tbody>{filas}</tbody>
    <tfoot><tr><td>TOTAL</td>{fila_totales}</tr></tfoot>
  </table>
</body></html>
"""
    return web.Response(text=html, content_type="text/html")


app = web.Application()
app.router.add_get("/", handle)

if __name__ == "__main__":
    print(f"Mini dashboard en http://localhost:{PUERTO}")
    web.run_app(app, host="127.0.0.1", port=PUERTO)

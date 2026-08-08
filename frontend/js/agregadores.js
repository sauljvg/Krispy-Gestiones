const AGR_API = `${AUTH_API_BASE}/agregadores`;
const AGR_TODAS = "__todas__";
let agrTiendaActual = null;
let agrIntervalo = null;
let agrMap = null;
let agrDireccionMarkers = [];
let agrMarkersPorId = {};
let agrChart = null;
let agrModoAnadir = false;
let agrTiendaCentro = null;
let agrCentrosPorTienda = {}; // slug -> {lat,lng}, usado en la vista "Todas"
let agrFiltroAgregador = null; // null = todos los agregadores a la vez
let agrEstadosOcultos = new Set();

// Tarjetas del "Resumen (24h)" ocultas a mano desde este navegador (ver
// agrToggleTarjetaOculta) -- solo afecta a lo que se pinta aquí, nunca se
// manda al backend ni borra nada de la DB. persiste en localStorage (no en
// memoria como agrEstadosOcultos) porque el objetivo es no volver a verlas
// cada vez que se recarga el dashboard, no solo mientras dura la pestaña.
const AGR_TARJETAS_OCULTAS_KEY = "agr_tarjetas_ocultas";
let agrTarjetasOcultas = new Set(JSON.parse(localStorage.getItem(AGR_TARJETAS_OCULTAS_KEY) || "[]"));
let agrUltimoReporte = null;

// Reinicios de contador por agregador (ver agrReiniciarContador) -- {agregador: iso_timestamp}.
// Solo cambia qué le pedimos al backend que cuente (chequeos posteriores al timestamp), nunca
// borra chequeos reales -- permite ver "cómo va desde que apliqué este fix" sin que los fallos
// de antes sigan mezclados en el % del día. Persiste en localStorage, solo en este navegador.
const AGR_REINICIOS_KEY = "agr_reinicios_contador";
let agrReinicios = JSON.parse(localStorage.getItem(AGR_REINICIOS_KEY) || "{}");

// Corte de "limpiar alertas" (ver agrLimpiarAlertas) -- oculta las alertas
// anteriores a este momento, solo en este navegador. No borra nada del
// backend: una alerta nueva de verdad (posterior al corte) sigue apareciendo.
const AGR_ALERTAS_LIMPIADAS_KEY = "agr_alertas_limpiadas_hasta";
let agrAlertasLimpiadasHasta = localStorage.getItem(AGR_ALERTAS_LIMPIADAS_KEY) || null;

// Mismo patrón que las alertas, para "Últimos chequeos".
const AGR_TABLA_LIMPIADA_KEY = "agr_tabla_limpiada_hasta";
let agrTablaLimpiadaHasta = localStorage.getItem(AGR_TABLA_LIMPIADA_KEY) || null;
const AGR_TABLA_COLAPSADA_KEY = "agr_tabla_colapsada";
let agrTablaColapsada = localStorage.getItem(AGR_TABLA_COLAPSADA_KEY) === "1";

// Mismo patrón, para "Dejaron de estar disponibles".
const AGR_TRANSICIONES_LIMPIADAS_KEY = "agr_transiciones_limpiadas_hasta";
let agrTransicionesLimpiadasHasta = localStorage.getItem(AGR_TRANSICIONES_LIMPIADAS_KEY) || null;

const AGR_COLOR_MARCA = { justeat: "#ff8000", glovo: "#ffc244", ubereats: "#06c167" };
const AGR_NOMBRE_AGREGADOR = { justeat: "JustEat", glovo: "Glovo", ubereats: "Uber Eats" };
let agrMostrarCorrectos = false;

async function agrFetchConTimeout(url, options = {}, ms = 15000) {
  // Sin esto, un fetch que se queda colgado (proxy que corta la conexión sin
  // devolver error, red caída a medias) deja "Buscando dirección..." para
  // siempre -- con AbortController al menos falla y se puede reintentar.
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), ms);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

const AGR_COLOR_CATEGORIA = {
  todos: "#0ca30c",
  disponible: "#0ca30c",
  algunos: "#fab219",
  ninguno: "#d03b3b",
  no_disponible: "#d03b3b",
  sin_datos: "#898781",
  error: "#e8a33d",
};

const AGR_LEYENDA_AGREGADO = [
  { cat: "todos", label: "Disponible en todos" },
  { cat: "algunos", label: "Disponible en algunos" },
  { cat: "ninguno", label: "No disponible (real)" },
  { cat: "sin_datos", label: "Sin datos válidos" },
];
const AGR_LEYENDA_AGREGADOR = [
  { cat: "disponible", label: "Disponible" },
  { cat: "no_disponible", label: "No disponible" },
  { cat: "error", label: "Error del scraper" },
  { cat: "sin_datos", label: "Sin datos" },
];

function agrCategoriaDireccion(dir) {
  if (agrFiltroAgregador) {
    const info = (dir.detalle || {})[agrFiltroAgregador];
    if (!info) return "sin_datos";
    if (info.estado === "error") return "error";
    return info.estado === "disponible" ? "disponible" : "no_disponible";
  }
  const validos = dir.disponible_count + dir.no_disponible_count;
  if (validos === 0) return "sin_datos";
  if (dir.disponible_count === 0) return "ninguno";
  if (dir.no_disponible_count === 0) return "todos";
  return "algunos";
}

function agrMarcadorVisible(dir) {
  return !agrEstadosOcultos.has(agrCategoriaDireccion(dir));
}

function agrInitMap(lat, lng) {
  if (agrMap) agrMap.remove();
  agrMap = L.map("agr-map").setView([lat, lng], 12);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap",
  }).addTo(agrMap);
}

function agrDistanciaKm(lat1, lng1, lat2, lng2) {
  const R = 6371;
  const dLat = ((lat2 - lat1) * Math.PI) / 180;
  const dLng = ((lng2 - lng1) * Math.PI) / 180;
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos((lat1 * Math.PI) / 180) * Math.cos((lat2 * Math.PI) / 180) * Math.sin(dLng / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function agrIconoDireccion(dir) {
  const color = AGR_COLOR_CATEGORIA[agrCategoriaDireccion(dir)] || "#898781";
  return L.divIcon({
    className: "agr-marker-dot",
    html: `<span style="background:${color}"></span>`,
    iconSize: [16, 16],
    iconAnchor: [8, 8],
  });
}

function agrIconoTienda(tienda) {
  // Parquesur ya lleva el letrero "Hot Now" (donuts recién hechos) en la
  // tienda real -- de ahí el icono especial en negro para ese centro.
  const esHotNow = tienda === "parquesur";
  const src = esHotNow ? "assets/hotnow-icon-white.png" : "assets/shop-icon-white.png";
  const tam = esHotNow ? 44 : 38;
  return L.divIcon({
    className: esHotNow ? "agr-marker-tienda agr-marker-tienda-hotnow" : "agr-marker-tienda",
    html: `<span><img src="${src}" alt=""></span>`,
    iconSize: [tam, tam],
    iconAnchor: [tam / 2, tam / 2],
  });
}

function agrPopupDireccion(dir, editable) {
  const iconos = { disponible: "✅", no_disponible: "❌", error: "⚠️" };
  const detalleHtml = Object.entries(dir.detalle || {})
    .map(([nombre, info]) => {
      const icono = iconos[info.estado] || "❔";
      const tiempo = info.tiempo_entrega_min ? ` (${info.tiempo_entrega_min} min)` : "";
      const nota = info.estado === "error" ? " — fallo del scraper" : "";
      const nombreMostrar = AGR_NOMBRE_AGREGADOR[nombre] || nombre;
      const hora = info.timestamp
        ? ` <span style="color:var(--text-muted);font-size:11px;">(${new Date(info.timestamp).toLocaleString("es-ES", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Madrid" })})</span>`
        : "";
      return `${icono} ${nombreMostrar}${tiempo}${nota}${hora}`;
    })
    .join("<br>");
  const tiendaLinea = dir.tienda_nombre ? `<b>${dir.tienda_nombre}</b><br>` : "";
  const pieEditable = editable
    ? `<i style="color:var(--text-muted);font-size:11px;">Arrastra el punto para reubicarlo</i><br>
       <button type="button" class="btn btn-ghost" style="margin-top:6px;font-size:12px;padding:3px 8px;" onclick="agrEliminarPunto(${dir.id})">🗑️ Eliminar punto</button>`
    : "";
  return `${tiendaLinea}<b>${dir.direccion_text || "Punto de test"}</b><br>${dir.distancia_km.toFixed(2)} km · ${dir.angulo_grados}°<br>${detalleHtml || "Sin datos aún"}<br>${pieEditable}`;
}

async function agrEliminarPunto(direccionId) {
  try {
    const res = await fetch(`${AGR_API}/direcciones/${direccionId}`, { method: "DELETE", credentials: "include" });
    if (!res.ok) throw new Error("No se pudo eliminar");
    const marker = agrMarkersPorId[direccionId];
    if (marker) {
      agrMap.removeLayer(marker);
      delete agrMarkersPorId[direccionId];
      agrDireccionMarkers = agrDireccionMarkers.filter((m) => m !== marker);
      agrRecalcularContador();
    }
  } catch (e) {
    alert("No se pudo eliminar el punto. Inténtalo de nuevo.");
  }
}

async function agrAnadirPunto(lat, lng) {
  // Marcador provisional mientras el servidor consulta la dirección de este
  // punto exacto (una sola llamada, sin desplazarlo -- se queda donde se
  // hizo clic aunque no tenga número de portal cerca).
  const provisional = L.marker([lat, lng], {
    icon: L.divIcon({ className: "agr-marker-dot", html: `<span style="background:#898781;opacity:0.6;"></span>`, iconSize: [16, 16], iconAnchor: [8, 8] }),
  }).addTo(agrMap).bindPopup("Buscando dirección…").openPopup();

  try {
    const res = await agrFetchConTimeout(`${AGR_API}/direcciones`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tienda: agrTiendaActual, lat, lng }),
      credentials: "include",
    });
    if (!res.ok) throw new Error("No se pudo añadir");
    const dir = await res.json();
    dir.detalle = {};
    dir.disponible_count = dir.no_disponible_count = dir.error_count = 0;
    agrMap.removeLayer(provisional);
    agrAgregarMarcador(dir, { editable: true });
    agrRecalcularContador();
  } catch (e) {
    agrMap.removeLayer(provisional);
    alert("No se pudo añadir el punto. Inténtalo de nuevo.");
  }
}

async function agrGuardarReubicacion(dir, marker, lat, lng) {
  marker.setPopupContent("Buscando dirección…").openPopup();
  try {
    const res = await agrFetchConTimeout(`${AGR_API}/direcciones/${dir.id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lat, lng }),
      credentials: "include",
    });
    if (!res.ok) throw new Error("No se pudo guardar");
    const actualizado = await res.json();
    dir.lat = actualizado.lat;
    dir.lng = actualizado.lng;
    dir.direccion_text = actualizado.direccion_text;
    marker.setLatLng([dir.lat, dir.lng]);
    marker.setPopupContent(agrPopupDireccion(dir, true));
  } catch (e) {
    alert("No se pudo guardar la reubicación. Inténtalo de nuevo.");
    marker.setLatLng([dir.lat, dir.lng]);
    marker.setPopupContent(agrPopupDireccion(dir, true));
  }
}

function agrAgregarMarcador(dir, opts = {}) {
  const editable = opts.editable !== false;
  const marker = L.marker([dir.lat, dir.lng], {
    icon: agrIconoDireccion(dir),
    draggable: editable,
  })
    .bindPopup(agrPopupDireccion(dir, editable))
    .bindTooltip("", { permanent: false, direction: "top", className: "agr-drag-tooltip" });

  marker._agrDir = dir;

  if (editable) {
    const centro = (dir.tienda && agrCentrosPorTienda[dir.tienda]) || agrTiendaCentro;
    marker.on("drag", (e) => {
      const { lat, lng } = e.target.getLatLng();
      const distKm = agrDistanciaKm(centro.lat, centro.lng, lat, lng);
      marker.setTooltipContent(`${distKm.toFixed(2)} km línea recta (objetivo ${dir.distancia_km.toFixed(2)} km)`);
      marker.openTooltip();
    });

    marker.on("dragend", (e) => {
      marker.closeTooltip();
      const { lat, lng } = e.target.getLatLng();
      agrGuardarReubicacion(dir, marker, lat, lng);
    });
  }

  agrDireccionMarkers.push(marker);
  agrMarkersPorId[dir.id] = marker;
  if (agrMarcadorVisible(dir)) marker.addTo(agrMap);
  return marker;
}

function agrActualizarMarcadores() {
  agrDireccionMarkers.forEach((marker) => {
    const dir = marker._agrDir;
    marker.setIcon(agrIconoDireccion(dir));
    const visible = agrMarcadorVisible(dir);
    const enMapa = agrMap.hasLayer(marker);
    if (visible && !enMapa) marker.addTo(agrMap);
    if (!visible && enMapa) agrMap.removeLayer(marker);
  });
}

function agrActualizarLeyenda() {
  const items = agrFiltroAgregador ? AGR_LEYENDA_AGREGADOR : AGR_LEYENDA_AGREGADO;
  const cont = document.getElementById("agr-leyenda");
  if (!cont) return;

  const conteos = {};
  agrDireccionMarkers.forEach((m) => {
    const cat = agrCategoriaDireccion(m._agrDir);
    conteos[cat] = (conteos[cat] || 0) + 1;
  });

  cont.innerHTML = items
    .map((it) => {
      const oculto = agrEstadosOcultos.has(it.cat);
      const n = conteos[it.cat] || 0;
      return `<span class="agr-leyenda-item${oculto ? " oculto" : ""}" data-cat="${it.cat}" title="Clic para ${oculto ? "mostrar" : "ocultar"}">
        <i class="agr-dot" style="background:${AGR_COLOR_CATEGORIA[it.cat]}"></i> ${it.label} <b class="agr-leyenda-n">${n}</b>
      </span>`;
    })
    .join("");
  cont.querySelectorAll(".agr-leyenda-item").forEach((el) => {
    el.addEventListener("click", () => {
      const cat = el.dataset.cat;
      if (agrEstadosOcultos.has(cat)) agrEstadosOcultos.delete(cat);
      else agrEstadosOcultos.add(cat);
      agrActualizarLeyenda();
      agrActualizarMarcadores();
    });
  });
}

function agrWireFiltroAgregador() {
  document.querySelectorAll(".agr-filtro-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".agr-filtro-btn").forEach((b) => b.classList.remove("activo"));
      btn.classList.add("activo");
      agrFiltroAgregador = btn.dataset.agregador || null;
      agrEstadosOcultos.clear(); // las categorías cambian de significado al cambiar de filtro
      agrActualizarLeyenda();
      agrActualizarMarcadores();
      agrRecalcularContador();
    });
  });
}

function agrToggleModoAnadir() {
  if (agrTiendaActual === AGR_TODAS) return;
  agrModoAnadir = !agrModoAnadir;
  const btn = document.getElementById("agr-btn-anadir");
  if (btn) {
    btn.classList.toggle("activo", agrModoAnadir);
    btn.textContent = agrModoAnadir ? "✓ Clic en el mapa para añadir…" : "➕ Añadir punto";
  }
  if (agrMap) {
    document.getElementById("agr-map").style.cursor = agrModoAnadir ? "crosshair" : "";
  }
}

function agrLimpiarMapa() {
  agrDireccionMarkers.forEach((m) => agrMap.removeLayer(m));
  agrDireccionMarkers = [];
  agrMarkersPorId = {};
}

function agrActualizarContador(texto) {
  const el = document.getElementById("agr-contador-puntos");
  if (el) el.textContent = texto;
}

function agrRecalcularContador() {
  const n = agrDireccionMarkers.length;
  const base = agrTiendaActual === AGR_TODAS
    ? `${n} puntos en ${Object.keys(agrCentrosPorTienda).length} tiendas`
    : `${n} punto${n === 1 ? "" : "s"}`;

  if (!agrFiltroAgregador) {
    agrActualizarContador(base);
    return;
  }

  // Filtrado por un agregador concreto: de los N puntos totales, cuántos
  // tienen dato real de ese agregador (disponible/no disponible/error) --
  // "sin datos" no cuenta como un punto "que existe" para ese filtro.
  const conDatos = agrDireccionMarkers.filter(
    (m) => ((m._agrDir.detalle || {})[agrFiltroAgregador])
  ).length;
  const nombre = AGR_NOMBRE_AGREGADOR[agrFiltroAgregador] || agrFiltroAgregador;
  agrActualizarContador(`${conDatos} de ${n} con dato de ${nombre}`);
}

function agrRenderMapa(data) {
  const { tienda, direcciones } = data;
  if (!tienda) return;
  agrTiendaCentro = tienda;
  agrInitMap(tienda.lat, tienda.lng);

  L.marker([tienda.lat, tienda.lng], { icon: agrIconoTienda(tienda.tienda) }).addTo(agrMap).bindPopup(`<b>${tienda.nombre}</b>`);

  agrLimpiarMapa();
  direcciones.forEach((dir) => agrAgregarMarcador(dir, { editable: true }));

  agrMap.on("click", (e) => {
    if (!agrModoAnadir) return;
    agrAnadirPunto(e.latlng.lat, e.latlng.lng);
  });
  agrActualizarLeyenda();
  agrActualizarContador(`${direcciones.length} punto${direcciones.length === 1 ? "" : "s"}`);
}

function agrRenderMapaTodas(data) {
  const { tiendas, direcciones } = data;
  if (!tiendas || !tiendas.length) return;
  agrTiendaCentro = null;
  agrCentrosPorTienda = {};
  tiendas.forEach((t) => { agrCentrosPorTienda[t.tienda] = t; });

  const lat0 = tiendas.reduce((s, t) => s + t.lat, 0) / tiendas.length;
  const lng0 = tiendas.reduce((s, t) => s + t.lng, 0) / tiendas.length;
  agrInitMap(lat0, lng0);

  tiendas.forEach((t) => {
    L.marker([t.lat, t.lng], { icon: agrIconoTienda(t.tienda) }).addTo(agrMap).bindPopup(`<b>${t.nombre}</b>`);
  });

  agrLimpiarMapa();
  direcciones.forEach((dir) => agrAgregarMarcador(dir, { editable: true }));

  const bounds = L.latLngBounds(tiendas.map((t) => [t.lat, t.lng]));
  agrMap.fitBounds(bounds.pad(0.25));
  agrActualizarLeyenda();
  agrActualizarContador(`${direcciones.length} puntos en ${tiendas.length} tiendas`);
}

function agrBadge(c) {
  if (c.error_texto) return '<span class="agr-badge error" title="Fallo del scraper, no del agregador">Error</span>';
  return c.disponible
    ? '<span class="agr-badge si">Sí</span>'
    : '<span class="agr-badge no">No</span>';
}

async function agrCargarTiendas() {
  const res = await fetch(`${AGR_API}/tiendas`);
  const tiendas = await res.json();
  const select = document.getElementById("agr-tienda-select");
  const opciones = [`<option value="${AGR_TODAS}">Todas</option>`].concat(
    tiendas.map((t) => `<option value="${t.tienda}">${t.nombre}</option>`)
  );
  select.innerHTML = opciones.join("");
  agrTiendaActual = tiendas.length ? tiendas[0].tienda : AGR_TODAS;
  select.value = agrTiendaActual;
  select.addEventListener("change", (e) => {
    agrTiendaActual = e.target.value;
    if (agrModoAnadir) agrToggleModoAnadir();
    agrCargarTodo();
  });
}

async function agrCargarMapa() {
  if (!agrTiendaActual) return;
  if (agrTiendaActual === AGR_TODAS) {
    const res = await fetch(`${AGR_API}/mapa-datos-todas`, { credentials: "include" });
    agrRenderMapaTodas(await res.json());
    return;
  }
  const res = await fetch(`${AGR_API}/mapa-datos?tienda=${agrTiendaActual}`, { credentials: "include" });
  agrRenderMapa(await res.json());
}

function agrLimpiarTabla() {
  agrTablaLimpiadaHasta = new Date().toISOString();
  localStorage.setItem(AGR_TABLA_LIMPIADA_KEY, agrTablaLimpiadaHasta);
  agrCargarTabla();
}

function agrColapsarTabla() {
  agrTablaColapsada = !agrTablaColapsada;
  localStorage.setItem(AGR_TABLA_COLAPSADA_KEY, agrTablaColapsada ? "1" : "0");
  agrAplicarColapsoTabla();
}

function agrAplicarColapsoTabla() {
  document.getElementById("agr-tabla-scroll").classList.toggle("agr-colapsado", agrTablaColapsada);
  document.getElementById("agr-tabla-colapsar-icono").classList.toggle("agr-colapsado", agrTablaColapsada);
}

function agrFilaTabla(c) {
  const hora = new Date(c.timestamp).toLocaleString("es-ES", { timeZone: "Europe/Madrid" });
  const detalle = c.error_texto ? `⚠️ ${c.error_texto}` : c.mensaje_bloqueo || "-";
  const filaClase = c.error_texto ? "agr-fila-error" : "agr-fila-correcta";
  const nombre = AGR_NOMBRE_AGREGADOR[c.agregador] || c.agregador;
  return `<tr class="${filaClase}">
    <td>${hora}</td><td>${nombre}</td><td>${agrBadge(c)}</td>
    <td>${c.tiempo_entrega_min ? c.tiempo_entrega_min + " min" : "-"}</td>
    <td>${c.direccion_text || "-"}</td><td>${detalle}</td>
  </tr>`;
}

async function agrCargarTabla() {
  const tbody = document.querySelector("#agr-tabla tbody");
  const contador = document.getElementById("agr-tabla-contador");
  const toggle = document.getElementById("agr-tabla-toggle");
  if (!agrTiendaActual || agrTiendaActual === AGR_TODAS) {
    tbody.innerHTML = '<tr><td colspan="6" style="color:var(--text-muted);">Selecciona una tienda para ver el detalle.</td></tr>';
    contador.textContent = "";
    toggle.hidden = true;
    return;
  }
  const res = await fetch(`${AGR_API}/ultimos?tienda=${agrTiendaActual}&horas=24`, { credentials: "include" });
  let chequeos = await res.json();
  const totalSinLimpiar = chequeos.length;
  if (agrTablaLimpiadaHasta) {
    chequeos = chequeos.filter((c) => c.timestamp > agrTablaLimpiadaHasta);
  }
  const incorrectos = chequeos.filter((c) => c.error_texto);
  const correctos = chequeos.filter((c) => !c.error_texto);
  const notaLimpiados = totalSinLimpiar > chequeos.length ? ` -- ${totalSinLimpiar - chequeos.length} ocultos` : "";

  contador.textContent = `(${incorrectos.length} con fallo técnico / ${correctos.length} correctos${notaLimpiados})`;

  if (incorrectos.length === 0) {
    const motivo = totalSinLimpiar > 0 && chequeos.length === 0
      ? "Sin chequeos nuevos desde que limpiaste."
      : "Sin fallos técnicos en 24h. Todos los chequeos se completaron correctamente.";
    tbody.innerHTML = `<tr><td colspan="6" style="color:var(--text-muted);">${motivo}</td></tr>`;
  } else {
    tbody.innerHTML = incorrectos.slice(0, 30).map(agrFilaTabla).join("");
  }

  toggle.hidden = correctos.length === 0;
  toggle.textContent = agrMostrarCorrectos
    ? "Ocultar detalles correctos"
    : `Mostrar detalles correctos (${correctos.length})`;
  toggle.onclick = () => {
    agrMostrarCorrectos = !agrMostrarCorrectos;
    agrCargarTabla();
  };

  if (agrMostrarCorrectos && correctos.length > 0) {
    tbody.innerHTML += correctos.slice(0, 30).map(agrFilaTabla).join("");
  }
}

function agrRenderCards(reporte) {
  const cont = document.getElementById("agr-cards");
  const entradas = Object.entries(reporte.agregadores).filter(([nombre]) => !agrTarjetasOcultas.has(nombre));
  if (entradas.length === 0) {
    const motivo = Object.keys(reporte.agregadores).length === 0 ? "Sin chequeos en 24h." : "Todas las tarjetas están ocultas -- usa el icono 🗑 para volver a mostrarlas.";
    cont.innerHTML = `<p style="color:var(--text-muted);font-size:0.85rem;grid-column:1/-1;">${motivo}</p>`;
    return;
  }
  cont.innerHTML = entradas
    .map(([nombre, datos]) => {
      const etiqueta = AGR_NOMBRE_AGREGADOR[nombre] || nombre;
      const notaReinicio = datos.reiniciado_desde
        ? ` <span class="agr-card-reinicio">· contador reiniciado ${new Date(datos.reiniciado_desde).toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Madrid" })}</span>`
        : "";
      return `<div class="agr-card">
        <div class="etiqueta">${etiqueta}</div>
        <div class="agr-card-total">${datos.total_chequeos} intentos en total${notaReinicio}</div>
        <div class="agr-card-desglose">
          <div class="agr-card-fila ok agr-clicable" onclick="agrMostrarDrill('${nombre}', 'disponible')"><span class="agr-card-pct">${datos.disponible_pct}%</span> disponible <span class="agr-card-n">(${datos.disponibles})</span></div>
          <div class="agr-card-fila no agr-clicable" onclick="agrMostrarDrill('${nombre}', 'no_disponible')"><span class="agr-card-pct">${datos.no_disponible_pct}%</span> no disponible <span class="agr-card-n">(${datos.no_disponibles})</span></div>
          <div class="agr-card-fila fallo agr-clicable" onclick="agrMostrarDrill('${nombre}', 'error')"><span class="agr-card-pct">${datos.error_pct}%</span> fallo técnico <span class="agr-card-n">(${datos.errores})</span></div>
        </div>
        <div class="agr-card-barra">
          <span style="width:${datos.disponible_pct}%;background:var(--status-good);"></span><span style="width:${datos.no_disponible_pct}%;background:var(--status-critical);"></span><span style="width:${datos.error_pct}%;background:var(--status-warning);"></span>
        </div>
      </div>`;
    })
    .join("");
}

async function agrMostrarDrill(agregador, estado) {
  const overlay = document.getElementById("agr-drill-overlay");
  const titulo = document.getElementById("agr-drill-titulo");
  const lista = document.getElementById("agr-drill-lista");
  const etiquetaEstado = estado === "disponible" ? "Disponibles" : estado === "error" ? "Fallo técnico" : "No disponibles";

  titulo.textContent = `${AGR_NOMBRE_AGREGADOR[agregador] || agregador} — ${etiquetaEstado}`;
  lista.innerHTML = '<li style="color:var(--text-muted);">Cargando...</li>';
  overlay.classList.add("visible");

  let direcciones;
  try {
    const url = agrTiendaActual === AGR_TODAS
      ? `${AGR_API}/mapa-datos-todas`
      : `${AGR_API}/mapa-datos?tienda=${agrTiendaActual}`;
    const res = await agrFetchConTimeout(url, { credentials: "include" });
    direcciones = (await res.json()).direcciones;
  } catch (err) {
    lista.innerHTML = '<li style="color:var(--status-critical);">No se pudo cargar. Inténtalo de nuevo.</li>';
    return;
  }

  const filtradas = direcciones
    .filter((d) => d.detalle[agregador]?.estado === estado)
    .sort((a, b) => new Date(b.detalle[agregador].timestamp) - new Date(a.detalle[agregador].timestamp));
  if (filtradas.length === 0) {
    lista.innerHTML = '<li style="color:var(--text-muted);">Sin puntos en este estado ahora mismo.</li>';
    return;
  }

  // Construcción vía DOM (no innerHTML con interpolación) porque el texto de
  // dirección viene de geocoding externo (Nominatim) -- así no hace falta
  // escapar nada a mano para que sea seguro meterlo en el atributo/HTML.
  lista.innerHTML = "";
  for (const d of filtradas) {
    const texto = d.direccion_text || `${d.lat.toFixed(5)}, ${d.lng.toFixed(5)}`;
    const li = document.createElement("li");

    const span = document.createElement("span");
    span.className = "agr-drill-direccion";
    if (d.tienda) {
      const tag = document.createElement("span");
      tag.style.color = "var(--text-muted)";
      tag.style.fontSize = "0.68rem";
      tag.textContent = `[${d.tienda}] `;
      span.appendChild(tag);
    }
    span.appendChild(document.createTextNode(texto));

    const info = d.detalle[agregador];
    if (info?.timestamp) {
      const hora = document.createElement("span");
      hora.className = "agr-drill-hora";
      hora.textContent = ` (${new Date(info.timestamp).toLocaleString("es-ES", {
        day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Madrid",
      })})`;
      span.appendChild(hora);
    }

    const boton = document.createElement("button");
    boton.type = "button";
    boton.className = "agr-drill-copiar";
    boton.textContent = "📋 Copiar";
    boton.onclick = () => agrCopiarDireccionDrill(boton, texto);

    li.appendChild(span);
    li.appendChild(boton);
    lista.appendChild(li);
  }
}

function agrCerrarDrill() {
  document.getElementById("agr-drill-overlay").classList.remove("visible");
}

async function agrCopiarDireccionDrill(boton, texto) {
  try {
    await navigator.clipboard.writeText(texto);
    const original = boton.textContent;
    boton.textContent = "✓ Copiado";
    setTimeout(() => { boton.textContent = original; }, 1500);
  } catch (err) {
    // Clipboard API puede fallar sin HTTPS/permisos -- el texto sigue
    // siendo seleccionable a mano (user-select:text en .agr-drill-direccion).
  }
}

function agrRenderChart(reporte) {
  const ctx = document.getElementById("agr-chart");
  const claves = Object.keys(reporte.agregadores).filter((nombre) => !agrTarjetasOcultas.has(nombre));
  const labels = claves.map((n) => AGR_NOMBRE_AGREGADOR[n] || n);
  const valores = claves.map((n) => reporte.agregadores[n].disponible_pct);
  const colores = claves.map((n) => AGR_COLOR_MARCA[n] || "#e07b00");
  if (agrChart) agrChart.destroy();
  agrChart = new Chart(ctx, {
    type: "bar",
    data: { labels, datasets: [{ label: "% Disponible (24h, sobre el total de intentos)", data: valores, backgroundColor: colores, borderRadius: 6 }] },
    options: {
      responsive: true,
      scales: { y: { beginAtZero: true, max: 100 } },
      plugins: { legend: { display: false } },
    },
  });
}

async function agrCargarResumen() {
  const cont = document.getElementById("agr-cards");
  if (!agrTiendaActual) {
    cont.innerHTML = '<p style="color:var(--text-muted);font-size:0.85rem;grid-column:1/-1;">Selecciona una tienda para ver el resumen.</p>';
    if (agrChart) { agrChart.destroy(); agrChart = null; }
    return;
  }
  const params = new URLSearchParams();
  if (agrTiendaActual !== AGR_TODAS) params.set("tienda", agrTiendaActual);
  if (Object.keys(agrReinicios).length > 0) params.set("resets", JSON.stringify(agrReinicios));
  const url = `${AGR_API}/reportes/diario${params.toString() ? "?" + params.toString() : ""}`;
  const res = await fetch(url, { credentials: "include" });
  const reporte = await res.json();
  agrUltimoReporte = reporte;
  agrRenderCards(reporte);
  agrRenderChart(reporte);
}

function agrGuardarTarjetasOcultas() {
  localStorage.setItem(AGR_TARJETAS_OCULTAS_KEY, JSON.stringify([...agrTarjetasOcultas]));
}

function agrGuardarReinicios() {
  localStorage.setItem(AGR_REINICIOS_KEY, JSON.stringify(agrReinicios));
}

function agrPoblarMenuBorrar() {
  const menu = document.getElementById("agr-borrar-menu");
  const disponibles = agrUltimoReporte ? Object.keys(agrUltimoReporte.agregadores) : Object.keys(AGR_NOMBRE_AGREGADOR);
  const items = disponibles
    .map((nombre) => {
      const oculta = agrTarjetasOcultas.has(nombre);
      const reiniciado = !!agrReinicios[nombre];
      const tituloReset = reiniciado
        ? "El % de este agregador solo cuenta desde el reinicio -- clic para volver a contar todo el día"
        : "Recalcula el % de este agregador solo con chequeos a partir de ahora (no borra nada)";
      return `<div class="agr-borrar-menu-fila">
        <label class="agr-borrar-menu-item">
          <input type="checkbox" data-agregador="${nombre}" ${oculta ? "checked" : ""} onchange="agrToggleTarjetaOculta('${nombre}', this.checked)">
          Ocultar ${AGR_NOMBRE_AGREGADOR[nombre] || nombre}
        </label>
        <button type="button" class="agr-borrar-menu-reset${reiniciado ? " activo" : ""}" onclick="agrToggleReinicioContador('${nombre}')" title="${tituloReset}">${reiniciado ? "✕ Quitar reinicio" : "↺ Reiniciar"}</button>
      </div>`;
    })
    .join("");
  menu.innerHTML = items + '<div class="agr-borrar-menu-nota">Solo en este navegador -- no borra nada en el servidor ni en la base de datos.</div>';
}

function agrToggleReinicioContador(agregador) {
  if (agrReinicios[agregador]) {
    delete agrReinicios[agregador];
  } else {
    agrReinicios[agregador] = new Date().toISOString();
  }
  agrGuardarReinicios();
  agrPoblarMenuBorrar();
  agrCargarResumen();
}

function agrToggleMenuBorrar(evt) {
  evt.stopPropagation();
  const menu = document.getElementById("agr-borrar-menu");
  const abrir = menu.hidden;
  if (abrir) agrPoblarMenuBorrar();
  menu.hidden = !abrir;
}

function agrToggleTarjetaOculta(agregador, oculta) {
  if (oculta) agrTarjetasOcultas.add(agregador);
  else agrTarjetasOcultas.delete(agregador);
  agrGuardarTarjetasOcultas();
  if (agrUltimoReporte) {
    agrRenderCards(agrUltimoReporte);
    agrRenderChart(agrUltimoReporte);
  }
}

document.addEventListener("click", (evt) => {
  const menu = document.getElementById("agr-borrar-menu");
  if (menu && !menu.hidden && !menu.contains(evt.target) && evt.target.id !== "agr-btn-borrar-stats") {
    menu.hidden = true;
  }
});

function agrLimpiarAlertas() {
  agrAlertasLimpiadasHasta = new Date().toISOString();
  localStorage.setItem(AGR_ALERTAS_LIMPIADAS_KEY, agrAlertasLimpiadasHasta);
  agrCargarAlertas();
}

async function agrCargarAlertas() {
  const lista = document.getElementById("agr-alertas");
  const resumen = document.getElementById("agr-alertas-resumen");
  if (agrTiendaActual === AGR_TODAS) {
    const res = await fetch(`${AGR_API}/alertas?horas=24`, { credentials: "include" });
    var alertas = await res.json();
  } else {
    if (!agrTiendaActual) return;
    const res = await fetch(`${AGR_API}/alertas?tienda=${agrTiendaActual}&horas=24`, { credentials: "include" });
    var alertas = await res.json();
  }

  const totalSinLimpiar = alertas.length;
  if (agrAlertasLimpiadasHasta) {
    alertas = alertas.filter((a) => a.timestamp > agrAlertasLimpiadasHasta);
  }

  const nuestras = alertas.filter((a) => a.tipo === "scraper_error").length;
  const otras = alertas.length - nuestras;
  const notaLimpiadas = totalSinLimpiar > alertas.length
    ? ` (${totalSinLimpiar - alertas.length} ocultas)`
    : "";
  resumen.textContent = alertas.length === 0
    ? (notaLimpiadas ? `Todo limpio${notaLimpiadas}` : "")
    : `${alertas.length} total — ${nuestras} nuestras (scraper) / ${otras} de agregadores${notaLimpiadas}`;

  if (alertas.length === 0) {
    lista.innerHTML = `<li style="color:var(--text-muted);">Sin alertas nuevas${totalSinLimpiar > 0 ? " desde que limpiaste" : " en 24h"}.</li>`;
    return;
  }
  lista.innerHTML = alertas
    .map((a) => {
      const hora = new Date(a.timestamp).toLocaleString("es-ES", { timeZone: "Europe/Madrid" });
      const claseTipo = a.tipo === "scraper_error" ? "tipo nuestro" : "tipo";
      const etiquetaTipo = a.tipo === "scraper_error" ? "Nuestro" : a.tipo;
      return `<li><span class="hora">${hora}</span><span class="${claseTipo}">${etiquetaTipo}</span>${a.mensaje}</li>`;
    })
    .join("");
}

async function agrEliminarTransicion(chequeoId, boton) {
  if (!confirm("¿Borrar este registro? Es para casos confirmados como error (p.ej. dirección o captura equivocada) -- no se puede deshacer.")) {
    return;
  }
  boton.disabled = true;
  boton.textContent = "Borrando...";
  try {
    const res = await fetch(`${AGR_API}/chequeo/${chequeoId}`, { method: "DELETE", credentials: "include" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    boton.closest("li").remove();
  } catch (err) {
    boton.disabled = false;
    boton.textContent = "🗑 Es un error, borrar";
    alert("No se pudo borrar. Inténtalo de nuevo.");
  }
}

function agrLimpiarTransiciones() {
  agrTransicionesLimpiadasHasta = new Date().toISOString();
  localStorage.setItem(AGR_TRANSICIONES_LIMPIADAS_KEY, agrTransicionesLimpiadasHasta);
  agrCargarTransiciones();
}

async function agrCargarTransiciones() {
  const lista = document.getElementById("agr-transiciones");
  const resumen = document.getElementById("agr-transiciones-resumen");
  if (!lista) return;
  const url = agrTiendaActual === AGR_TODAS
    ? `${AGR_API}/transiciones?horas=24`
    : `${AGR_API}/transiciones?tienda=${agrTiendaActual}&horas=24`;
  if (!agrTiendaActual) return;
  const res = await fetch(url, { credentials: "include" });
  let transiciones = await res.json();

  const totalSinLimpiar = transiciones.length;
  if (agrTransicionesLimpiadasHasta) {
    transiciones = transiciones.filter((t) => t.timestamp > agrTransicionesLimpiadasHasta);
  }
  if (resumen) {
    resumen.textContent = totalSinLimpiar > transiciones.length
      ? `(${totalSinLimpiar - transiciones.length} ocultas)`
      : "";
  }

  if (transiciones.length === 0) {
    const motivo = totalSinLimpiar > 0
      ? "Sin transiciones nuevas desde que limpiaste."
      : "Ningún punto ha pasado de disponible a no disponible en las últimas 24h.";
    lista.innerHTML = `<li style="color:var(--text-muted);">${motivo}</li>`;
    return;
  }
  lista.innerHTML = transiciones
    .map((t) => {
      const opcionesHora = { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Madrid" };
      const hora = new Date(t.timestamp).toLocaleString("es-ES", opcionesHora);
      const nombre = AGR_NOMBRE_AGREGADOR[t.agregador] || t.agregador;
      const direccion = t.direccion_text || `${t.lat?.toFixed(5)}, ${t.lng?.toFixed(5)}`;
      const tiendaLinea = agrTiendaActual === AGR_TODAS && t.nombre_tienda ? `${t.nombre_tienda} — ` : "";
      const horaAnterior = t.timestamp_anterior
        ? new Date(t.timestamp_anterior).toLocaleString("es-ES", opcionesHora)
        : null;
      const duracionHtml = horaAnterior
        ? `<div class="agr-trans-duracion">✅ Disponible hasta las ${horaAnterior} · ❌ ya no desde las ${hora}${t.duracion_disponible ? ` (${t.duracion_disponible})` : ""}</div>`
        : "";
      const captura = t.tiene_captura
        ? `<a href="${AGR_API}/capturas/${t.id}" target="_blank" rel="noopener" class="agr-trans-link">📷 Ver captura</a>`
        : '<span style="color:var(--text-muted);font-size:0.72rem;">Sin captura</span>';
      return `<li>
        <div class="agr-trans-meta">
          <span class="agr-trans-hora">${hora}</span>
          <span class="agr-trans-agregador ${t.agregador}">${nombre}</span>
        </div>
        <div>
          <div class="agr-trans-direccion">${tiendaLinea}${direccion}</div>
          <div class="agr-trans-bloqueo">${t.mensaje_bloqueo || "No disponible"}</div>
          ${duracionHtml}
        </div>
        <div class="agr-trans-acciones">
          ${captura}
          <button type="button" class="agr-trans-link agr-trans-borrar" onclick="agrEliminarTransicion(${t.id}, this)">🗑 Es un error, borrar</button>
        </div>
      </li>`;
    })
    .join("");
}

let agrMapaCobertura = null;
let agrCoberturaPoligono = []; // uno o varios (vista "Todos": uno por agregador)
let agrCoberturaMarkers = [];

// "Solo dots nuevos": guarda el id más alto ya visto al activar el filtro,
// así el mapa solo dibuja marcadores creados DESPUÉS de ese momento -- para
// ver en vivo dónde va cayendo la búsqueda de límite de cobertura sin el
// ruido de todo el grid ya existente. Por tienda, en localStorage, para que
// sobreviva a los refrescos automáticos (cada 30s) y a recargar la página.
function agrSoloNuevosKey(tienda) {
  return `agr_solo_nuevos_baseline_${tienda}`;
}

function agrSoloNuevosBaseline() {
  if (!agrTiendaActual) return null;
  const v = localStorage.getItem(agrSoloNuevosKey(agrTiendaActual));
  return v == null ? null : parseInt(v, 10);
}

async function agrToggleSoloNuevos() {
  const activo = document.getElementById("agr-solo-nuevos")?.checked;
  if (!agrTiendaActual) return;
  if (activo) {
    // Fetch fresco (no los ya cargados en el mapa) para que el corte sea el
    // id más alto que existe AHORA, sin depender de qué vista/agregador
    // estuviera seleccionado antes de activar el filtro.
    const res = await fetch(`${AGR_API}/cobertura?tienda=${agrTiendaActual}`, { credentials: "include" });
    const puntos = await res.json();
    const maxId = puntos.reduce((max, p) => Math.max(max, p.id || 0), 0);
    localStorage.setItem(agrSoloNuevosKey(agrTiendaActual), String(maxId));
  } else {
    localStorage.removeItem(agrSoloNuevosKey(agrTiendaActual));
  }
  agrCargarMapaCobertura();
}

function agrInitMapaCobertura(lat, lng) {
  if (agrMapaCobertura) agrMapaCobertura.remove();
  agrMapaCobertura = L.map("agr-mapa-cobertura").setView([lat, lng], 12);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap",
  }).addTo(agrMapaCobertura);
}

function agrMoverPunto(lat, lng, bearingDeg, distanciaKm) {
  // Igual que _mover_punto en el backend: punto de destino a una distancia
  // y rumbo dados desde (lat, lng), sobre la esfera terrestre.
  const R = 6371;
  const bearing = (bearingDeg * Math.PI) / 180;
  const lat1 = (lat * Math.PI) / 180;
  const lng1 = (lng * Math.PI) / 180;
  const lat2 = Math.asin(
    Math.sin(lat1) * Math.cos(distanciaKm / R) + Math.cos(lat1) * Math.sin(distanciaKm / R) * Math.cos(bearing)
  );
  const lng2 = lng1 + Math.atan2(
    Math.sin(bearing) * Math.sin(distanciaKm / R) * Math.cos(lat1),
    Math.cos(distanciaKm / R) - Math.sin(lat1) * Math.sin(lat2)
  );
  return [(lat2 * 180) / Math.PI, (lng2 * 180) / Math.PI];
}

function agrRadioDeLimite(limite) {
  // limite_km es el dato bueno; si es null, el "nota" casi siempre trae un
  // número aprovechable ("no disponible incluso a 0.77km" -> cierre real
  // cerca de la tienda, ">= 5.0km" -> cota inferior porque no se encontró
  // el borde) -- mejor esa aproximación que dejar un hueco en el polígono.
  if (limite.limite_km != null) return limite.limite_km;
  const m = (limite.nota || "").match(/(\d+\.?\d*)\s*km/);
  return m ? parseFloat(m[1]) : 0.05;
}

function agrDibujarPoligonoLimite(limites, centro, color) {
  // Polígono "araña/radar": un vértice por ángulo, a la distancia real del
  // límite de cobertura en esa dirección concreta -- a diferencia del
  // envolvente convexo (turf.convex), esto SÍ puede representar huecos de
  // cobertura (ej. cerrado al norte, abierto al sur), porque conecta los
  // vértices en orden angular en vez de "abombar hacia fuera".
  if (!limites || limites.length < 3) return null;
  const ordenados = [...limites].sort((a, b) => a.angulo_grados - b.angulo_grados);
  const puntos = ordenados.map((l) => agrMoverPunto(centro.lat, centro.lng, l.angulo_grados, Math.max(agrRadioDeLimite(l), 0.05)));
  return L.polygon(puntos, { color, weight: 2, fillColor: color, fillOpacity: 0.12 }).addTo(agrMapaCobertura);
}

function agrDibujarCapaCobertura(puntos, colorDisponible, colorNoDisponible, dibujarMarcadores, limites, centro) {
  // Dibuja marcadores (opcional) + polígono de cobertura para un único
  // agregador, y devuelve {verdes, amarillos} para el contador.
  //
  // Si hay `limites` (resultado de la búsqueda adaptativa del límite real,
  // ver buscar_limite_cobertura.py) con al menos 3 direcciones, se dibuja el
  // polígono "araña" (un vértice por ángulo, a su distancia real) -- a
  // diferencia del envolvente convexo de abajo, ESTE sí puede representar
  // huecos de cobertura reales (cerrado en una dirección, abierto en otra).
  // Si no hay límites calculados todavía para esta tienda/agregador, se cae
  // al envolvente convexo de siempre sobre los puntos del grid normal
  // (mejor una aproximación que nada, mientras se completa la búsqueda).
  const validos = puntos.filter((p) => p.lat != null && p.lng != null);
  const verdes = validos.filter((p) => p.disponible);
  const amarillos = validos.filter((p) => !p.disponible);

  if (dibujarMarcadores) {
    validos.forEach((p) => {
      const color = p.disponible ? colorDisponible : colorNoDisponible;
      const marker = L.circleMarker([p.lat, p.lng], {
        radius: 7, color, fillColor: color, fillOpacity: 0.85, weight: 2,
      })
        .bindPopup(`<b>${p.direccion_text || "Punto"}</b><br>${p.disponible ? "✅ Disponible" : "❌ No disponible"}`)
        .addTo(agrMapaCobertura);
      agrCoberturaMarkers.push(marker);
    });
  }

  if (limites && limites.length >= 3 && centro) {
    const poligono = agrDibujarPoligonoLimite(limites, centro, colorDisponible);
    if (poligono) agrCoberturaPoligono.push(poligono);
    return { verdes, amarillos };
  }

  if (verdes.length >= 3 && typeof turf !== "undefined") {
    try {
      const fc = turf.featureCollection(verdes.map((p) => turf.point([p.lng, p.lat])));
      const hull = turf.convex(fc);
      if (hull) {
        const latlngs = hull.geometry.coordinates[0].map(([lng, lat]) => [lat, lng]);
        const poligono = L.polygon(latlngs, {
          color: colorDisponible, weight: 2, fillColor: colorDisponible, fillOpacity: 0.1,
        }).addTo(agrMapaCobertura);
        agrCoberturaPoligono.push(poligono);
      }
    } catch (e) {
      // Puntos colineales u otro caso degenerado: se queda solo con los marcadores.
    }
  }

  return { verdes, amarillos };
}

async function agrCargarMapaCobertura() {
  const cont = document.getElementById("agr-mapa-cobertura");
  const contador = document.getElementById("agr-cobertura-contador");
  if (!cont || !agrTiendaActual || agrTiendaActual === AGR_TODAS) {
    if (contador) contador.textContent = "El mapa de cobertura no está disponible en la vista \"Todas\" — selecciona una tienda.";
    if (agrMapaCobertura) {
      agrMapaCobertura.remove();
      agrMapaCobertura = null;
      agrCoberturaMarkers = [];
      agrCoberturaPoligono = [];
    }
    return;
  }
  const btnActivo = document.querySelector("#agr-filtro-cobertura .agr-filtro-btn-cobertura.activo");
  const agregador = btnActivo ? btnActivo.dataset.agregador : "";

  const url = agregador
    ? `${AGR_API}/cobertura?tienda=${agrTiendaActual}&agregador=${agregador}`
    : `${AGR_API}/cobertura?tienda=${agrTiendaActual}`;
  const [res, resLimites] = await Promise.all([
    fetch(url, { credentials: "include" }),
    fetch(`${AGR_API}/limites/${agrTiendaActual}`, { credentials: "include" }),
  ]);
  let puntos = await res.json();
  const limites = resLimites.ok ? await resLimites.json() : [];

  const checkboxNuevos = document.getElementById("agr-solo-nuevos");
  const baseline = agrSoloNuevosBaseline();
  if (checkboxNuevos) checkboxNuevos.checked = baseline != null;
  if (baseline != null) {
    puntos = puntos.filter((p) => (p.id || 0) > baseline);
  }

  const centro = (agrCentrosPorTienda[agrTiendaActual] || agrTiendaCentro) || { lat: 40.4168, lng: -3.7038 };
  if (!agrMapaCobertura) {
    agrInitMapaCobertura(centro.lat, centro.lng);
  }

  agrCoberturaMarkers.forEach((m) => agrMapaCobertura.removeLayer(m));
  agrCoberturaMarkers = [];
  (agrCoberturaPoligono || []).forEach((p) => agrMapaCobertura.removeLayer(p));
  agrCoberturaPoligono = [];

  const nota = document.getElementById("agr-cobertura-nota");
  const hayLimitesReales = limites.length >= 3;

  if (!agregador) {
    // "Todos": un polígono por agregador, cada uno con su color de marca, sin
    // marcadores individuales (con 3 agregadores solapados se saturaría el mapa).
    const resumenes = [];
    for (const nombre of Object.keys(AGR_NOMBRE_AGREGADOR)) {
      const puntosAgregador = puntos.filter((p) => p.agregador === nombre);
      const limitesAgregador = limites.filter((l) => l.agregador === nombre);
      const color = AGR_COLOR_MARCA[nombre] || "#888";
      const { verdes } = agrDibujarCapaCobertura(puntosAgregador, color, color, false, limitesAgregador, centro);
      resumenes.push(`${AGR_NOMBRE_AGREGADOR[nombre]}: ${verdes.length}`);
    }
    if (contador) contador.textContent = `Con cobertura -- ${resumenes.join(" · ")}${baseline != null ? " (solo dots nuevos)" : ""}`;
    if (nota) {
      nota.textContent = hayLimitesReales
        ? "Un polígono por agregador (JustEat naranja, Glovo amarillo, Uber Eats verde) con la forma real de cobertura (límite comprobado en cada dirección, no un envolvente aproximado)."
        : "Un polígono por agregador (JustEat naranja, Glovo amarillo, Uber Eats verde) uniendo los puntos donde SÍ reparte cada uno. Usa el último estado conocido de cada punto, no solo las últimas 24h.";
    }
  } else {
    const limitesAgregador = limites.filter((l) => l.agregador === agregador);
    const { verdes, amarillos } = agrDibujarCapaCobertura(puntos, "#0ca30c", "#fab219", true, limitesAgregador, centro);
    const nombre = AGR_NOMBRE_AGREGADOR[agregador] || agregador;
    if (contador) {
      contador.textContent = `${verdes.length} con cobertura / ${amarillos.length} sin cobertura (${nombre})${baseline != null ? " -- solo dots nuevos" : ""}`;
    }
    if (nota) {
      nota.textContent = hayLimitesReales
        ? "Polígono con la forma real de cobertura -- un vértice por dirección comprobada, a su límite real (puede tener huecos: cerrado en una dirección, abierto en otra)."
        : "Polígono que une los puntos más alejados donde el agregador SÍ reparte (verde) — la superficie de cobertura real, frente a los puntos donde no reparte (amarillo). Usa el último estado conocido de cada punto, no solo las últimas 24h.";
    }
  }
}

async function agrCargarEstado() {
  const pill = document.getElementById("agr-estado");
  try {
    const res = await fetch(`${AGR_API}/estado`, { credentials: "include" });
    const estado = await res.json();
    if (!estado.es_horario_apertura) {
      pill.textContent = "⏸ Fuera de horario";
      pill.className = "agr-estado-pill neutro";
      return;
    }
    if (estado.cercano.retrasado || estado.completo.retrasado) {
      pill.textContent = "⚠ Scraper retrasado";
      pill.className = "agr-estado-pill alerta";
      return;
    }
    pill.textContent = "● Scraper OK";
    pill.className = "agr-estado-pill ok";
  } catch {
    pill.textContent = "? Estado desconocido";
    pill.className = "agr-estado-pill neutro";
  }
}

async function agrCargarTodo() {
  // agrCargarMapa() debe ir primero: fija agrTiendaCentro/agrCentrosPorTienda,
  // que agrCargarMapaCobertura() usa para centrar su propio mapa la primera vez.
  await agrCargarMapa();
  await Promise.all([agrCargarTabla(), agrCargarResumen(), agrCargarAlertas(), agrCargarTransiciones(), agrCargarMapaCobertura(), agrCargarEstado()]);
  document.getElementById("agr-actualizado").textContent = "Actualizado: " + new Date().toLocaleTimeString("es-ES", { timeZone: "Europe/Madrid" });
}

document.addEventListener("DOMContentLoaded", async () => {
  const user = await checkAuth("/agregadores.html");
  if (!user) return;
  if (!(user.modulos || []).includes("agregadores")) {
    window.location.href = "/";
    return;
  }
  wireUserBar(user);
  agrWireFiltroAgregador();
  agrAplicarColapsoTabla();

  document.querySelectorAll("#agr-filtro-cobertura .agr-filtro-btn-cobertura").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#agr-filtro-cobertura .agr-filtro-btn-cobertura").forEach((b) => b.classList.remove("activo"));
      btn.classList.add("activo");
      agrCargarMapaCobertura();
    });
  });

  await agrCargarTiendas();
  await agrCargarTodo();

  if (agrIntervalo) clearInterval(agrIntervalo);
  agrIntervalo = setInterval(agrCargarTodo, 30000);
});

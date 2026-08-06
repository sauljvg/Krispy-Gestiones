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

const AGR_COLOR_MARCA = { justeat: "#ff8000", glovo: "#ffc244", ubereats: "#06c167" };

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
      return `${icono} ${nombre}${tiempo}${nota}`;
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
  cont.innerHTML = items
    .map((it) => {
      const oculto = agrEstadosOcultos.has(it.cat);
      return `<span class="agr-leyenda-item${oculto ? " oculto" : ""}" data-cat="${it.cat}" title="Clic para ${oculto ? "mostrar" : "ocultar"}">
        <i class="agr-dot" style="background:${AGR_COLOR_CATEGORIA[it.cat]}"></i> ${it.label}
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

async function agrCargarTabla() {
  const tbody = document.querySelector("#agr-tabla tbody");
  if (!agrTiendaActual || agrTiendaActual === AGR_TODAS) {
    tbody.innerHTML = '<tr><td colspan="6" style="color:var(--text-muted);">Selecciona una tienda para ver el detalle.</td></tr>';
    return;
  }
  const res = await fetch(`${AGR_API}/ultimos?tienda=${agrTiendaActual}&horas=24`, { credentials: "include" });
  const chequeos = await res.json();
  tbody.innerHTML = chequeos
    .slice(0, 30)
    .map((c) => {
      const hora = new Date(c.timestamp).toLocaleString("es-ES");
      const detalle = c.error_texto ? `⚠️ ${c.error_texto}` : c.mensaje_bloqueo || "-";
      const filaClase = c.error_texto ? ' class="agr-fila-error"' : "";
      return `<tr${filaClase}>
        <td>${hora}</td><td>${c.agregador}</td><td>${agrBadge(c)}</td>
        <td>${c.tiempo_entrega_min ? c.tiempo_entrega_min + " min" : "-"}</td>
        <td>${c.direccion_text || "-"}</td><td>${detalle}</td>
      </tr>`;
    })
    .join("");
}

function agrRenderCards(reporte) {
  const cont = document.getElementById("agr-cards");
  const entradas = Object.entries(reporte.agregadores);
  if (entradas.length === 0) {
    cont.innerHTML = '<p style="color:var(--text-muted);font-size:0.85rem;grid-column:1/-1;">Sin chequeos en 24h.</p>';
    return;
  }
  cont.innerHTML = entradas
    .map(([nombre, datos]) => {
      const aviso = datos.errores > 0
        ? `<div class="errores">⚠️ ${datos.errores} fallo(s) (${datos.errores_pct}%)</div>` : "";
      return `<div class="agr-card"><div class="valor">${datos.disponibilidad_pct}%</div><div class="etiqueta">${nombre}</div>${aviso}</div>`;
    })
    .join("");
}

function agrRenderChart(reporte) {
  const ctx = document.getElementById("agr-chart");
  const labels = Object.keys(reporte.agregadores);
  const valores = labels.map((n) => reporte.agregadores[n].disponibilidad_pct);
  const colores = labels.map((n) => AGR_COLOR_MARCA[n] || "#e07b00");
  if (agrChart) agrChart.destroy();
  agrChart = new Chart(ctx, {
    type: "bar",
    data: { labels, datasets: [{ label: "% Disponibilidad (24h)", data: valores, backgroundColor: colores, borderRadius: 6 }] },
    options: {
      responsive: true,
      scales: { y: { beginAtZero: true, max: 100 } },
      plugins: { legend: { display: false } },
    },
  });
}

async function agrCargarResumen() {
  const cont = document.getElementById("agr-cards");
  if (!agrTiendaActual || agrTiendaActual === AGR_TODAS) {
    cont.innerHTML = '<p style="color:var(--text-muted);font-size:0.85rem;grid-column:1/-1;">Selecciona una tienda para ver el resumen.</p>';
    if (agrChart) { agrChart.destroy(); agrChart = null; }
    return;
  }
  const res = await fetch(`${AGR_API}/reportes/diario?tienda=${agrTiendaActual}`, { credentials: "include" });
  const reporte = await res.json();
  agrRenderCards(reporte);
  agrRenderChart(reporte);
}

async function agrCargarAlertas() {
  const lista = document.getElementById("agr-alertas");
  if (agrTiendaActual === AGR_TODAS) {
    const res = await fetch(`${AGR_API}/alertas?horas=24`, { credentials: "include" });
    var alertas = await res.json();
  } else {
    if (!agrTiendaActual) return;
    const res = await fetch(`${AGR_API}/alertas?tienda=${agrTiendaActual}&horas=24`, { credentials: "include" });
    var alertas = await res.json();
  }
  if (alertas.length === 0) {
    lista.innerHTML = '<li style="color:var(--text-muted);">Sin alertas en 24h.</li>';
    return;
  }
  lista.innerHTML = alertas
    .map((a) => {
      const hora = new Date(a.timestamp).toLocaleString("es-ES");
      return `<li><span class="hora">${hora}</span><span class="tipo">${a.tipo}</span>${a.mensaje}</li>`;
    })
    .join("");
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
  await Promise.all([agrCargarMapa(), agrCargarTabla(), agrCargarResumen(), agrCargarAlertas(), agrCargarEstado()]);
  document.getElementById("agr-actualizado").textContent = "Actualizado: " + new Date().toLocaleTimeString("es-ES");
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

  await agrCargarTiendas();
  await agrCargarTodo();

  if (agrIntervalo) clearInterval(agrIntervalo);
  agrIntervalo = setInterval(agrCargarTodo, 30000);
});

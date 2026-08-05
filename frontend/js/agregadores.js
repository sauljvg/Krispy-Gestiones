const AGR_API = `${AUTH_API_BASE}/agregadores`;
let agrTiendaActual = null;
let agrIntervalo = null;
let agrMap = null;
let agrDireccionMarkers = [];
let agrMarkersPorId = {};
let agrChart = null;
let agrModoAnadir = false;
let agrTiendaCentro = null;

function agrColorParaDireccion(dir) {
  const validos = dir.disponible_count + dir.no_disponible_count;
  if (validos === 0) return "#898781";
  if (dir.disponible_count === 0) return "#d03b3b";
  if (dir.no_disponible_count === 0) return "#0ca30c";
  return "#fab219";
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
  return L.divIcon({
    className: "agr-marker-dot",
    html: `<span style="background:${agrColorParaDireccion(dir)}"></span>`,
    iconSize: [16, 16],
    iconAnchor: [8, 8],
  });
}

function agrPopupDireccion(dir) {
  const iconos = { disponible: "✅", no_disponible: "❌", error: "⚠️" };
  const detalleHtml = Object.entries(dir.detalle || {})
    .map(([nombre, info]) => {
      const icono = iconos[info.estado] || "❔";
      const tiempo = info.tiempo_entrega_min ? ` (${info.tiempo_entrega_min} min)` : "";
      const nota = info.estado === "error" ? " — fallo del scraper" : "";
      return `${icono} ${nombre}${tiempo}${nota}`;
    })
    .join("<br>");
  return `<b>${dir.direccion_text || "Punto de test"}</b><br>${dir.distancia_km.toFixed(2)} km · ${dir.angulo_grados}°<br>${detalleHtml || "Sin datos aún"}<br>
    <i style="color:var(--text-muted);font-size:11px;">Arrastra el punto para reubicarlo</i><br>
    <button type="button" class="btn btn-ghost" style="margin-top:6px;font-size:12px;padding:3px 8px;" onclick="agrEliminarPunto(${dir.id})">🗑️ Eliminar punto</button>`;
}

async function agrEliminarPunto(direccionId) {
  if (!confirm("¿Quitar este punto de test? Ya no se comprobará más.")) return;
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
  const texto = prompt("Dirección de este nuevo punto (mira el mapa/Google Maps si hace falta):", "");
  if (texto === null || texto.trim() === "") return;
  try {
    const res = await fetch(`${AGR_API}/direcciones`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tienda: agrTiendaActual, lat, lng, direccion_text: texto.trim() }),
      credentials: "include",
    });
    if (!res.ok) throw new Error("No se pudo añadir");
    const dir = await res.json();
    dir.detalle = {};
    dir.disponible_count = dir.no_disponible_count = dir.error_count = 0;
    agrAgregarMarcador(dir);
  } catch (e) {
    alert("No se pudo añadir el punto. Inténtalo de nuevo.");
  }
}

async function agrGuardarReubicacion(dir, marker, lat, lng) {
  const actual = prompt(
    `Nueva dirección para este punto (objetivo: ${dir.distancia_km} km del centro):`,
    dir.direccion_text || ""
  );
  if (actual === null || actual.trim() === "") {
    marker.setLatLng([dir.lat, dir.lng]); // canceló o dejó vacío: revertir
    return;
  }
  try {
    const res = await fetch(`${AGR_API}/direcciones/${dir.id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lat, lng, direccion_text: actual.trim() }),
      credentials: "include",
    });
    if (!res.ok) throw new Error("No se pudo guardar");
    const actualizado = await res.json();
    dir.lat = actualizado.lat;
    dir.lng = actualizado.lng;
    dir.direccion_text = actualizado.direccion_text;
    marker.setPopupContent(agrPopupDireccion(dir));
  } catch (e) {
    alert("No se pudo guardar la reubicación. Inténtalo de nuevo.");
    marker.setLatLng([dir.lat, dir.lng]);
  }
}

function agrAgregarMarcador(dir) {
  const marker = L.marker([dir.lat, dir.lng], {
    icon: agrIconoDireccion(dir),
    draggable: true,
  })
    .addTo(agrMap)
    .bindPopup(agrPopupDireccion(dir))
    .bindTooltip("", { permanent: false, direction: "top", className: "agr-drag-tooltip" });

  marker.on("drag", (e) => {
    const { lat, lng } = e.target.getLatLng();
    const distKm = agrDistanciaKm(agrTiendaCentro.lat, agrTiendaCentro.lng, lat, lng);
    marker.setTooltipContent(`${distKm.toFixed(2)} km línea recta (objetivo ${dir.distancia_km.toFixed(2)} km)`);
    marker.openTooltip();
  });

  marker.on("dragend", (e) => {
    marker.closeTooltip();
    const { lat, lng } = e.target.getLatLng();
    agrGuardarReubicacion(dir, marker, lat, lng);
  });

  agrDireccionMarkers.push(marker);
  agrMarkersPorId[dir.id] = marker;
  return marker;
}

function agrToggleModoAnadir() {
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

function agrRenderMapa(data) {
  const { tienda, direcciones } = data;
  if (!tienda) return;
  agrTiendaCentro = tienda;
  agrInitMap(tienda.lat, tienda.lng);

  const iconoTienda = L.divIcon({
    className: "agr-marker-tienda",
    html: `<span><img src="assets/shop-icon-white.png" alt=""></span>`,
    iconSize: [38, 38],
    iconAnchor: [19, 19],
  });
  L.marker([tienda.lat, tienda.lng], { icon: iconoTienda }).addTo(agrMap).bindPopup(`<b>${tienda.nombre}</b>`);

  agrDireccionMarkers.forEach((m) => agrMap.removeLayer(m));
  agrDireccionMarkers = [];
  agrMarkersPorId = {};

  direcciones.forEach((dir) => agrAgregarMarcador(dir));

  agrMap.on("click", (e) => {
    if (!agrModoAnadir) return;
    agrAnadirPunto(e.latlng.lat, e.latlng.lng);
  });
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
  select.innerHTML = tiendas.map((t) => `<option value="${t.tienda}">${t.nombre}</option>`).join("");
  agrTiendaActual = tiendas.length ? tiendas[0].tienda : null;
  select.addEventListener("change", (e) => {
    agrTiendaActual = e.target.value;
    agrCargarTodo();
  });
}

async function agrCargarMapa() {
  if (!agrTiendaActual) return;
  const res = await fetch(`${AGR_API}/mapa-datos?tienda=${agrTiendaActual}`);
  agrRenderMapa(await res.json());
}

async function agrCargarTabla() {
  if (!agrTiendaActual) return;
  const res = await fetch(`${AGR_API}/ultimos?tienda=${agrTiendaActual}&horas=24`);
  const chequeos = await res.json();
  const tbody = document.querySelector("#agr-tabla tbody");
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

const AGR_COLOR_MARCA = { justeat: "#ff8000", glovo: "#ffc244", ubereats: "#06c167" };

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
  if (!agrTiendaActual) return;
  const res = await fetch(`${AGR_API}/reportes/diario?tienda=${agrTiendaActual}`);
  const reporte = await res.json();
  agrRenderCards(reporte);
  agrRenderChart(reporte);
}

async function agrCargarAlertas() {
  if (!agrTiendaActual) return;
  const res = await fetch(`${AGR_API}/alertas?tienda=${agrTiendaActual}&horas=24`);
  const alertas = await res.json();
  const lista = document.getElementById("agr-alertas");
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
    const res = await fetch(`${AGR_API}/estado`);
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

  await agrCargarTiendas();
  await agrCargarTodo();

  if (agrIntervalo) clearInterval(agrIntervalo);
  agrIntervalo = setInterval(agrCargarTodo, 30000);
});

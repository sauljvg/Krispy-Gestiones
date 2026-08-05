const AGR_API = `${AUTH_API_BASE}/agregadores`;
let agrTiendaActual = null;
let agrIntervalo = null;
let agrMap = null;
let agrDireccionMarkers = [];
let agrChart = null;

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

function agrRenderMapa(data) {
  const { tienda, direcciones } = data;
  if (!tienda) return;
  agrInitMap(tienda.lat, tienda.lng);

  L.circleMarker([tienda.lat, tienda.lng], {
    radius: 12, fillColor: "#e07b00", fillOpacity: 1, color: "#a85800", weight: 2,
  }).addTo(agrMap).bindPopup(`<b>${tienda.nombre}</b>`);

  agrDireccionMarkers.forEach((m) => agrMap.removeLayer(m));
  agrDireccionMarkers = [];

  const iconos = { disponible: "✅", no_disponible: "❌", error: "⚠️" };
  direcciones.forEach((dir) => {
    const detalleHtml = Object.entries(dir.detalle)
      .map(([nombre, info]) => {
        const icono = iconos[info.estado] || "❔";
        const tiempo = info.tiempo_entrega_min ? ` (${info.tiempo_entrega_min} min)` : "";
        const nota = info.estado === "error" ? " — fallo del scraper" : "";
        return `${icono} ${nombre}${tiempo}${nota}`;
      })
      .join("<br>");

    const marker = L.circleMarker([dir.lat, dir.lng], {
      radius: 7, fillColor: agrColorParaDireccion(dir), fillOpacity: 0.9, color: "#111", weight: 1,
    }).addTo(agrMap).bindPopup(
      `<b>${dir.direccion_text || "Punto de test"}</b><br>${dir.distancia_km} km · ${dir.angulo_grados}°<br>${detalleHtml || "Sin datos aún"}`
    );
    agrDireccionMarkers.push(marker);
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

function agrRenderChart(reporte) {
  const ctx = document.getElementById("agr-chart");
  const labels = Object.keys(reporte.agregadores);
  const valores = labels.map((n) => reporte.agregadores[n].disponibilidad_pct);
  if (agrChart) agrChart.destroy();
  agrChart = new Chart(ctx, {
    type: "bar",
    data: { labels, datasets: [{ label: "% Disponibilidad (24h)", data: valores, backgroundColor: "#e07b00", borderRadius: 6 }] },
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
    if (!estado.es_hora_punta) {
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

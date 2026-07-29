let currentOleada = null;
let currentCentro = null;
let ultimoReporte = null;
let centrosActuales = [];
let chartsBloques = [];
let chartMotivos = null;
let chartEvolucionTotal = null;
let chartEvolucionMinMax = null;
let MARCA_COLOR = "#006838";

// Icono SVG en vez de 🔗 — se ve igual de nítido en cualquier sistema.
const ICONO_ENLACE = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>`;

// Un color por cuatrimestre (no por bloque) — valores por defecto, se
// sobreescriben con los tokens de marca (KK o Saona) en cargarTokensDiseno().
let COLORES_PERIODO = ["#38761d", "#c00000", "#1155cc", "#bf9000", "#6a3d9a", "#e08214"];

const EMPRESA = new URLSearchParams(location.search).get("empresa") === "saona" ? "saona" : "kk";
function conEmpresa(params) {
  params.set("empresa", EMPRESA);
  return params;
}

function escapeHTML(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

function colorTextoActual() {
  return getComputedStyle(document.documentElement).getPropertyValue("--text-primary").trim() || "#000";
}

async function cargarTokensDiseno() {
  try {
    const res = await fetch("assets/design-tokens.json");
    if (!res.ok) return;
    const tokens = await res.json();
    const marca = EMPRESA === "saona" ? tokens.marca_saona : tokens.marca;
    MARCA_COLOR = marca.verde_kk;
    const periodos = EMPRESA === "saona" ? tokens.periodos_saona : tokens.periodos;
    if (periodos && periodos.lista) COLORES_PERIODO = periodos.lista;
  } catch (e) {
    // Se queda con los valores por defecto de arriba.
  }
}

function descargarChartPNG(canvasId, nombreArchivo) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const a = document.createElement("a");
  a.href = canvas.toDataURL("image/png");
  a.download = `${nombreArchivo}.png`;
  a.click();
}

function aplicarBrandingEmpresa() {
  if (EMPRESA !== "saona") return;
  document.title = document.title.replace("Krispy Gestiones", "SAONA Gestiones");
  const icon = document.getElementById("brand-icon");
  if (icon) icon.textContent = "🌿";
  const favicon = document.querySelector('link[rel="icon"]');
  if (favicon) favicon.href = "assets/favicon-saona.png";
  const title = document.getElementById("brand-title");
  if (title) title.textContent = "SAONA Gestiones";
  const logo = document.getElementById("entrevistas-report-logo");
  if (logo) {
    logo.src = "assets/saona-logo.png";
    logo.alt = "Saona";
    logo.style.height = "90px";
  }
  document.documentElement.dataset.empresa = "saona";
}

async function loadOleadas() {
  const res = await fetch(`${AUTH_API_BASE}/entrevistas/oleadas?${conEmpresa(new URLSearchParams())}`);
  const oleadas = await res.json();
  const select = document.getElementById("select-oleada");
  select.innerHTML = oleadas
    .map((o) => `<option value="${o.id}">${o.etiqueta || `Oleada #${o.numero}`} (${o.num_respuestas} respuestas · ${o.creado_en.slice(0, 10)})</option>`)
    .join("");
  if (oleadas.length === 0) {
    document.getElementById("centro-grid").innerHTML = `<p class="staff-hint">Todavía no has importado ningún Excel de Entrevista de Salida.</p>`;
    return;
  }
  currentOleada = oleadas[0].id;
  select.value = currentOleada;
  await loadCentros();
}

async function loadCentros() {
  const res = await fetch(`${AUTH_API_BASE}/entrevistas/${currentOleada}/centros`);
  const centros = await res.json();
  centrosActuales = centros;

  // El selector de "registrar salida manualmente" lista TODAS las tiendas
  // conocidas de la empresa, no solo las que ya tienen alguna respuesta —
  // si no, no se podría dar de alta una salida en un centro sin respuestas
  // todavía.
  const resConocidos = await fetch(`${AUTH_API_BASE}/entrevistas/centros-conocidos?${conEmpresa(new URLSearchParams())}`);
  const centrosConocidos = resConocidos.ok ? await resConocidos.json() : centros;
  const selectManual = document.getElementById("salida-manual-centro");
  if (selectManual) selectManual.innerHTML = centrosConocidos.map((c) => `<option value="${escapeHTML(c)}">${escapeHTML(c)}</option>`).join("");

  const grid = document.getElementById("centro-grid");
  const cards = [`<div class="centro-card" data-centro="">🏢 Todos los centros</div>`].concat(
    centros.map((c) => `<div class="centro-card" data-centro="${escapeHTML(c)}">${escapeHTML(c)}</div>`)
  );
  grid.innerHTML = cards.join("");
  grid.querySelectorAll(".centro-card").forEach((card) => {
    card.addEventListener("click", () => {
      grid.querySelectorAll(".centro-card").forEach((c) => c.classList.remove("active"));
      card.classList.add("active");
      loadReporte(card.dataset.centro || null);
    });
  });
  grid.querySelector(".centro-card").classList.add("active");
  await loadReporte(null);
}

function renderChartBloque(canvasId, existingChart, items) {
  const ctx = document.getElementById(canvasId);
  if (existingChart) existingChart.destroy();
  ctx.parentElement.style.height = "320px";
  const colorTexto = colorTextoActual();
  return new Chart(ctx, {
    type: "bar",
    data: {
      labels: items.map((i) => i.pregunta),
      datasets: [{ data: items.map((i) => i.promedio), backgroundColor: MARCA_COLOR, borderRadius: 4 }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        y: { min: 0, max: 5, ticks: { color: colorTexto }, grid: { color: "rgba(128,128,128,0.2)" } },
        x: { ticks: { color: colorTexto, autoSkip: false, maxRotation: 60, minRotation: 30 }, grid: { display: false } },
      },
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: (ctx) => `${ctx.parsed.y ?? 0} / 5` } },
      },
    },
  });
}

function renderChartMotivos(items) {
  const ctx = document.getElementById("chart-motivos");
  if (chartMotivos) chartMotivos.destroy();
  ctx.parentElement.style.height = "320px";
  const colorTexto = colorTextoActual();
  chartMotivos = new Chart(ctx, {
    type: "bar",
    data: {
      labels: items.map((i) => i.motivo),
      datasets: [{ data: items.map((i) => i.porcentaje), backgroundColor: MARCA_COLOR, borderRadius: 4 }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        y: { min: 0, max: 100, ticks: { color: colorTexto, callback: (v) => `${v}%` }, grid: { color: "rgba(128,128,128,0.2)" } },
        x: { ticks: { color: colorTexto, autoSkip: false, maxRotation: 60, minRotation: 30 }, grid: { display: false } },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const item = items[ctx.dataIndex];
              return `${item.cantidad} (${item.porcentaje}%)`;
            },
          },
        },
      },
    },
  });
}

// Los dos gráficos que de verdad importan (según el usuario): el resumen
// POR BLOQUE, no por pregunta suelta — y siempre diferenciando a qué
// cuatrimestre pertenece cada línea (antes todo salía en un único color por
// bloque, sin distinguir periodos). El eje X son los bloques; cada
// cuatrimestre es una línea de color distinto.

function renderChartEvolucionTotal(statsPorPeriodo) {
  const ctx = document.getElementById("chart-evolucion-total");
  if (chartEvolucionTotal) chartEvolucionTotal.destroy();
  ctx.parentElement.style.height = "320px";
  const colorTexto = colorTextoActual();
  const nombresBloque = statsPorPeriodo.length ? statsPorPeriodo[0].bloques.map((b) => b.nombre) : [];
  const datasets = statsPorPeriodo.map((p, i) => ({
    label: p.label,
    data: p.bloques.map((b) => b.total_ponderado),
    borderColor: COLORES_PERIODO[i % COLORES_PERIODO.length],
    backgroundColor: COLORES_PERIODO[i % COLORES_PERIODO.length],
    tension: 0.15,
  }));
  chartEvolucionTotal = new Chart(ctx, {
    type: "line",
    data: { labels: nombresBloque, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        y: { min: 1, max: 5, ticks: { color: colorTexto }, grid: { color: "rgba(128,128,128,0.2)" } },
        x: { ticks: { color: colorTexto }, grid: { display: false } },
      },
      plugins: {
        legend: { position: "bottom", labels: { color: colorTexto, usePointStyle: true, pointStyle: "circle" } },
      },
    },
  });
}

function renderChartEvolucionMinMax(statsPorPeriodo) {
  const ctx = document.getElementById("chart-evolucion-minmax");
  if (chartEvolucionMinMax) chartEvolucionMinMax.destroy();
  ctx.parentElement.style.height = "320px";
  const colorTexto = colorTextoActual();
  const primerPeriodo = statsPorPeriodo[0];
  const labels = primerPeriodo ? primerPeriodo.min_max.flatMap((m) => [`${m.bloque} (Mín)`, `${m.bloque} (Máx)`]) : [];
  const datasets = statsPorPeriodo.map((p, i) => ({
    label: p.label,
    data: p.min_max.flatMap((m) => [m.min, m.max]),
    borderColor: COLORES_PERIODO[i % COLORES_PERIODO.length],
    backgroundColor: COLORES_PERIODO[i % COLORES_PERIODO.length],
    tension: 0.15,
  }));
  chartEvolucionMinMax = new Chart(ctx, {
    type: "line",
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        y: { min: 1, max: 5, ticks: { color: colorTexto }, grid: { color: "rgba(128,128,128,0.2)" } },
        x: { ticks: { color: colorTexto, autoSkip: false, maxRotation: 45, minRotation: 0 }, grid: { display: false } },
      },
      plugins: {
        legend: { position: "bottom", labels: { color: colorTexto, usePointStyle: true, pointStyle: "circle" } },
      },
    },
  });
}

// Detalle por bloque, escondido detrás de un "mostrar más" — el desglose
// pregunta por pregunta no es lo importante a simple vista (eso ya lo dijo
// el usuario), pero se puede consultar sin recargar nada.
function renderDetalleBloques(statsPorPeriodo) {
  const wrap = document.getElementById("detalle-bloques-wrap");
  if (!statsPorPeriodo.length) {
    wrap.innerHTML = "";
    return;
  }
  const nombresBloque = statsPorPeriodo[0].bloques.map((b) => b.nombre);
  wrap.innerHTML = nombresBloque
    .map((nombre, i) => {
      const preguntas = statsPorPeriodo[0].bloques[i].items.map((it) => it.pregunta);
      const filas = preguntas
        .map((pregunta, pi) => {
          const celdas = statsPorPeriodo
            .map((p) => {
              const item = p.bloques[i] && p.bloques[i].items[pi];
              const media = item && item.media !== null ? item.media.toFixed(2) : "—";
              return `<td>${media}</td>`;
            })
            .join("");
          return `<tr><td>${escapeHTML(pregunta)}</td>${celdas}</tr>`;
        })
        .join("");
      const cabecera = statsPorPeriodo.map((p) => `<th>${escapeHTML(p.label)}</th>`).join("");
      return `
        <details class="detalle-bloque-details">
          <summary>${escapeHTML(nombre)} — ver detalle por pregunta</summary>
          <table class="detalle-tabla">
            <thead><tr><th>Pregunta</th>${cabecera}</tr></thead>
            <tbody>${filas}</tbody>
          </table>
        </details>`;
    })
    .join("");
}

function renderAuditoria(wrapId, summaryId, listaId, items, formatoItem, etiquetaVacio) {
  const wrap = document.getElementById(wrapId);
  const lista = document.getElementById(listaId);
  document.getElementById(summaryId).textContent = `${items.length} ${etiquetaVacio}`;
  wrap.hidden = items.length === 0;
  lista.innerHTML = items.map((it) => `<li><span>${escapeHTML(formatoItem(it))}</span></li>`).join("");
}

// La auditoría G (respuestas que no cruzaron con ninguna salida) necesita
// algo más que la F: cuando la misma persona real aparece en las dos listas
// con el nombre escrito distinto (el caso real: "FLORES, LENIN MICHAEL" en
// Salidas Totales vs "Lenin flores alvarado" en su propia respuesta, con un
// score de fuzzy-match por debajo de 1.0), hay que poder vincularlas a mano
// en vez de "registrar como salida" — eso último crearía una salida NUEVA y
// la persona quedaría contada dos veces.
function renderAuditoriaG(items, auditoriaF) {
  const wrap = document.getElementById("auditoria-g-wrap");
  const lista = document.getElementById("auditoria-g-lista");
  document.getElementById("auditoria-g-summary").textContent = `${items.length} respuestas que no cruzaron con ninguna salida`;
  wrap.hidden = items.length === 0;
  const opcionesF = auditoriaF
    .map((f) => `<option value="${f.salida_id}">${escapeHTML(f.nombre)} — ${escapeHTML(f.centro || "")} (baja: ${(f.fecha_baja || "").slice(0, 10)})</option>`)
    .join("");
  lista.innerHTML = items
    .map(
      (it, i) => `
    <li>
      <span>${escapeHTML(it.nombre)} — ${escapeHTML(it.centro || "")}</span>
      <span class="auditoria-g-acciones">
        <select class="select-vincular-salida" data-idx="${i}">
          <option value="">¿Es la misma persona que...?</option>
          ${opcionesF}
        </select>
        <button type="button" class="btn-registrar-salida btn-vincular" data-idx="${i}">${ICONO_ENLACE} Vincular</button>
        <button type="button" class="btn-registrar-salida btn-registrar-nueva" data-idx="${i}">＋ Registrar como salida</button>
        <button type="button" class="btn-registrar-salida btn-ghost btn-eliminar-respuesta" data-idx="${i}"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg> Eliminar</button>
      </span>
    </li>`
    )
    .join("");
  lista.querySelectorAll(".btn-vincular").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const idx = Number(btn.dataset.idx);
      const select = lista.querySelector(`.select-vincular-salida[data-idx="${idx}"]`);
      const salidaId = Number(select.value);
      if (!salidaId) {
        alert("Elige a qué salida corresponde esta respuesta.");
        return;
      }
      await vincularRespuestaSalida(items[idx].respuesta_id, salidaId);
    });
  });
  lista.querySelectorAll(".btn-registrar-nueva").forEach((btn) => {
    btn.addEventListener("click", () => registrarSalidaDesdeAuditoria(items[Number(btn.dataset.idx)]));
  });
  lista.querySelectorAll(".btn-eliminar-respuesta").forEach((btn) => {
    btn.addEventListener("click", () => {
      const item = items[Number(btn.dataset.idx)];
      if (!confirm(`¿Eliminar la respuesta de "${item.nombre}"? Esta acción no se puede deshacer.`)) return;
      eliminarRespuesta(item.respuesta_id);
    });
  });
}

async function eliminarRespuesta(respuestaId) {
  const res = await fetch(`${AUTH_API_BASE}/entrevistas/${currentOleada}/respuestas/${respuestaId}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    alert(err.detail || "No se pudo eliminar la respuesta.");
    return;
  }
  await loadEvolucion(currentCentro);
}

async function vincularRespuestaSalida(respuestaId, salidaId) {
  const res = await fetch(`${AUTH_API_BASE}/entrevistas/${currentOleada}/matches`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ respuesta_id: respuestaId, salida_id: salidaId }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    alert(err.detail || "No se pudo vincular la respuesta a esa salida.");
    return;
  }
  await loadEvolucion(currentCentro);
}

async function registrarSalidaDesdeAuditoria(item) {
  const centro = item.centro || (centrosActuales[0] || "");
  const fecha = (item.fecha || "").slice(0, 10) || new Date().toISOString().slice(0, 10);
  await crearSalidaManual(centro, item.nombre, fecha);
}

async function crearSalidaManual(centro, nombre, fechaBaja) {
  const res = await fetch(`${AUTH_API_BASE}/entrevistas/${currentOleada}/salidas`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ centro, nombre, fecha_baja: fechaBaja }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    alert(err.detail || "No se pudo registrar la salida.");
    return;
  }
  await loadEvolucion(currentCentro);
}

async function loadEvolucion(centro) {
  const params = new URLSearchParams();
  if (centro) params.set("centro", centro);
  const res = await fetch(`${AUTH_API_BASE}/entrevistas/${currentOleada}/evolucion?${params.toString()}`);
  const evolucionCard = document.getElementById("evolucion-card");
  if (!res.ok) {
    evolucionCard.hidden = true;
    return;
  }
  const data = await res.json();
  if (!data.stats_por_periodo || data.stats_por_periodo.length === 0) {
    evolucionCard.hidden = true;
    return;
  }
  evolucionCard.hidden = false;
  renderChartEvolucionTotal(data.stats_por_periodo);
  renderChartEvolucionMinMax(data.stats_por_periodo);
  renderDetalleBloques(data.stats_por_periodo);

  const coberturaWrap = document.getElementById("cobertura-wrap");
  if (data.tiene_salidas_totales) {
    coberturaWrap.hidden = false;
    document.getElementById("total-salidas-txt").textContent = `Total de salidas registradas: ${data.total_salidas}`;
    document.getElementById("cobertura-tbody").innerHTML = data.cobertura
      .map(
        (c) => `<tr><td>${escapeHTML(c.label)}</td><td>${c.debieron}</td><td>${c.respondieron}</td><td>${c.porcentaje !== null ? c.porcentaje + "%" : "—"}</td></tr>`
      )
      .join("");
    renderAuditoria(
      "auditoria-f-wrap", "auditoria-f-summary", "auditoria-f-lista",
      data.auditoria_f, (a) => `${a.nombre} — ${a.centro || ""} (baja: ${(a.fecha_baja || "").slice(0, 10)})`,
      "salidas sin ninguna respuesta detectada"
    );
    renderAuditoriaG(data.auditoria_g, data.auditoria_f);
  } else {
    coberturaWrap.hidden = true;
    document.getElementById("total-salidas-txt").textContent = "";
  }
}

async function loadReporte(centro) {
  currentCentro = centro;
  const params = new URLSearchParams();
  if (centro) params.set("centro", centro);
  const res = await fetch(`${AUTH_API_BASE}/entrevistas/${currentOleada}/reporte?${params.toString()}`);
  if (!res.ok) return;
  const data = await res.json();
  ultimoReporte = data;

  document.getElementById("reporte-wrap").hidden = false;
  document.getElementById("btn-exportar-pdf").hidden = false;

  document.getElementById("entrevistas-header-stats").innerHTML = `<span>N = <b>${data.n}</b></span>`;

  const satisfaccionBox = document.getElementById("satisfaccion-box");
  satisfaccionBox.style.background = MARCA_COLOR;
  satisfaccionBox.innerHTML = `
    <div class="label">Satisfacción general</div>
    <div class="valor">${data.satisfaccion_general !== null ? data.satisfaccion_general.toFixed(2) + " / 5" : "—"}</div>
  `;

  const bloquesWrap = document.getElementById("bloques-wrap");
  bloquesWrap.innerHTML = data.bloques
    .map(
      (b, i) => `
    <div class="bloque-card">
      <div class="bloque-head">
        <h2>${escapeHTML(b.nombre)}</h2>
        <div class="bloque-score">${b.promedio !== null ? b.promedio.toFixed(2) + " / 5" : "—"}</div>
      </div>
      <details class="bloque-detalle-details">
        <summary>Mostrar detalle por pregunta</summary>
        <div class="chart-wrap"><canvas id="chart-bloque-${i}"></canvas></div>
      </details>
    </div>`
    )
    .join("");
  // Lo importante es el resumen por bloque (arriba); el desglose pregunta
  // por pregunta solo se dibuja cuando el usuario abre el detalle — así no
  // se sobrecarga la vista con un gráfico por cada pregunta suelta.
  chartsBloques.forEach((c) => c && c.destroy());
  chartsBloques = data.bloques.map(() => null);
  bloquesWrap.querySelectorAll(".bloque-detalle-details").forEach((det, i) => {
    det.addEventListener("toggle", () => {
      if (det.open && !chartsBloques[i]) {
        chartsBloques[i] = renderChartBloque(`chart-bloque-${i}`, null, data.bloques[i].preguntas);
      }
    });
  });

  await loadEvolucion(centro);

  const motivosCard = document.getElementById("motivos-card");
  if (data.motivos && data.motivos.length > 0) {
    motivosCard.hidden = false;
    renderChartMotivos(data.motivos);
  } else {
    motivosCard.hidden = true;
  }

  const comentariosWrap = document.getElementById("comentarios-wrap");
  const headers = Object.keys(data.abiertas);
  comentariosWrap.innerHTML = headers
    .map(
      (h, i) => `
      <h3 style="font-size:15px;">${escapeHTML(h)}</h3>
      <div class="comentarios-lista" id="lista-${i}"></div>
    `
    )
    .join("");
  headers.forEach((h, i) => {
    renderListaComentarios(document.getElementById(`lista-${i}`), data.abiertas[h]);
  });
}

function renderListaComentarios(container, textos) {
  if (!textos || textos.length === 0) {
    container.innerHTML = `<p class="staff-hint">(sin comentarios)</p>`;
    return;
  }
  container.innerHTML = `<ol>${textos.map((t) => `<li>${escapeHTML(t)}</li>`).join("")}</ol>`;
}

document.addEventListener("DOMContentLoaded", async () => {
  const user = await checkAuth("/entrevistas.html");
  if (!user) return;
  const moduloRequerido = EMPRESA === "saona" ? "saona_informes" : "informes";
  if (!(user.modulos || []).includes(moduloRequerido)) {
    window.location.href = "/";
    return;
  }
  wireUserBar(user);
  aplicarBrandingEmpresa();

  await cargarTokensDiseno();
  await loadOleadas();

  document.querySelectorAll(".btn-descargar-chart").forEach((btn) => {
    btn.addEventListener("click", () => descargarChartPNG(btn.dataset.target, btn.dataset.nombre));
  });

  document.getElementById("select-oleada").addEventListener("change", async (e) => {
    currentOleada = Number(e.target.value);
    document.getElementById("reporte-wrap").hidden = true;
    document.getElementById("btn-exportar-pdf").hidden = true;
    await loadCentros();
  });

  document.getElementById("input-entrevistas-upload").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const nuevaOleada = document.getElementById("check-nueva-oleada").checked;
    const formData = new FormData();
    formData.append("file", file);
    formData.append("nueva_oleada", nuevaOleada ? "true" : "false");
    formData.append("empresa", EMPRESA);
    const res = await fetch(`${AUTH_API_BASE}/entrevistas/importar`, { method: "POST", body: formData });
    e.target.value = "";
    document.getElementById("check-nueva-oleada").checked = false;
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      alert(err.detail || "Fallo al importar el Excel.");
      return;
    }
    const result = await res.json();
    alert(`Importación completa: ${result.nuevas} respuestas nuevas, ${result.actualizadas} actualizadas, ${result.ya_existian} ya existían (de ${result.total_en_excel} filas).`);
    await loadOleadas();
  });

  document.getElementById("btn-salida-manual-agregar").addEventListener("click", async () => {
    const centro = document.getElementById("salida-manual-centro").value;
    const nombre = document.getElementById("salida-manual-nombre").value.trim();
    const fecha = document.getElementById("salida-manual-fecha").value;
    if (!centro || !nombre || !fecha) {
      alert("Completa centro, nombre y fecha de baja.");
      return;
    }
    await crearSalidaManual(centro, nombre, fecha);
    document.getElementById("salida-manual-nombre").value = "";
    document.getElementById("salida-manual-fecha").value = "";
  });

  document.getElementById("btn-exportar-pdf").addEventListener("click", () => {
    const params = new URLSearchParams();
    if (currentCentro) params.set("centro", currentCentro);
    window.open(`${AUTH_API_BASE}/entrevistas/${currentOleada}/reporte.pdf?${params.toString()}`, "_blank");
  });

  document.getElementById("btn-theme-toggle").addEventListener("click", () => {
    setTimeout(() => {
      if (!ultimoReporte) return;
      // Solo se redibujan (con los colores del nuevo tema) los bloques cuyo
      // detalle ya estaba abierto — los demás siguen sin dibujarse hasta que
      // el usuario los abra.
      chartsBloques.forEach((c, i) => {
        if (!c) return;
        c.destroy();
        chartsBloques[i] = renderChartBloque(`chart-bloque-${i}`, null, ultimoReporte.bloques[i].preguntas);
      });
      if (ultimoReporte.motivos && ultimoReporte.motivos.length > 0) renderChartMotivos(ultimoReporte.motivos);
      loadEvolucion(currentCentro);
    }, 0);
  });
});

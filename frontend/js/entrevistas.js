let currentOleada = null;
let currentCentro = null;
let ultimoReporte = null;
let centrosActuales = [];
let chartsBloques = [];
let chartMotivos = null;
let chartEvolucion = null;
let MARCA_COLOR = "#006838";

// Mismos colores fijos por bloque que usaba el Apps Script original (rojo,
// verde, dorado, azul) — así el gráfico de evolución se lee igual que en
// las hojas de siempre, en vez de un color por empresa que no aporta nada
// aquí (son 4 líneas distintas, no una sola serie de marca).
const COLORES_BLOQUE = ["#c00000", "#38761d", "#bf9000", "#1155cc", "#6a3d9a", "#e08214"];

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
  } catch (e) {
    // Se queda con el verde KK por defecto.
  }
}

function aplicarBrandingEmpresa() {
  if (EMPRESA !== "saona") return;
  document.title = document.title.replace("Krispy Gestiones", "SAONA Gestiones");
  const icon = document.getElementById("brand-icon");
  if (icon) icon.textContent = "🌿";
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
  const selectManual = document.getElementById("salida-manual-centro");
  if (selectManual) selectManual.innerHTML = centros.map((c) => `<option value="${escapeHTML(c)}">${escapeHTML(c)}</option>`).join("");
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

function renderChartEvolucion(statsPorPeriodo) {
  const ctx = document.getElementById("chart-evolucion");
  if (chartEvolucion) chartEvolucion.destroy();
  ctx.parentElement.style.height = "320px";
  const colorTexto = colorTextoActual();
  const labels = statsPorPeriodo.map((p) => p.label);
  const nombresBloque = statsPorPeriodo.length ? statsPorPeriodo[0].bloques.map((b) => b.nombre) : [];
  const datasets = nombresBloque.map((nombre, i) => ({
    label: nombre,
    data: statsPorPeriodo.map((p) => p.bloques[i] ? p.bloques[i].total_ponderado : null),
    borderColor: COLORES_BLOQUE[i % COLORES_BLOQUE.length],
    backgroundColor: COLORES_BLOQUE[i % COLORES_BLOQUE.length],
    tension: 0.15,
  }));
  chartEvolucion = new Chart(ctx, {
    type: "line",
    data: { labels, datasets },
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

function renderAuditoria(wrapId, summaryId, listaId, items, formatoItem, etiquetaVacio, accionRegistrar) {
  const wrap = document.getElementById(wrapId);
  const lista = document.getElementById(listaId);
  document.getElementById(summaryId).textContent = `${items.length} ${etiquetaVacio}`;
  wrap.hidden = items.length === 0;
  lista.innerHTML = items
    .map((it, i) => {
      const texto = `<span>${escapeHTML(formatoItem(it))}</span>`;
      if (!accionRegistrar) return `<li>${texto}</li>`;
      return `<li>${texto}<button type="button" class="btn-registrar-salida" data-idx="${i}">＋ Registrar como salida</button></li>`;
    })
    .join("");
  if (accionRegistrar) {
    lista.querySelectorAll(".btn-registrar-salida").forEach((btn) => {
      btn.addEventListener("click", () => accionRegistrar(items[Number(btn.dataset.idx)]));
    });
  }
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
  renderChartEvolucion(data.stats_por_periodo);

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
    renderAuditoria(
      "auditoria-g-wrap", "auditoria-g-summary", "auditoria-g-lista",
      data.auditoria_g, (a) => `${a.nombre} — ${a.centro || ""}`,
      "respuestas que no cruzaron con ninguna salida",
      registrarSalidaDesdeAuditoria
    );
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
      <div class="chart-wrap"><canvas id="chart-bloque-${i}"></canvas></div>
    </div>`
    )
    .join("");
  chartsBloques.forEach((c) => c && c.destroy());
  chartsBloques = data.bloques.map((b, i) => renderChartBloque(`chart-bloque-${i}`, null, b.preguntas));

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
  container.innerHTML = `<ul>${textos.map((t) => `<li>${escapeHTML(t)}</li>`).join("")}</ul>`;
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
    alert(`Importación completa: ${result.nuevas} respuestas nuevas, ${result.ya_existian} ya existían (de ${result.total_en_excel} filas).`);
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
      chartsBloques.forEach((c) => c && c.destroy());
      chartsBloques = ultimoReporte.bloques.map((b, i) => renderChartBloque(`chart-bloque-${i}`, null, b.preguntas));
      if (ultimoReporte.motivos && ultimoReporte.motivos.length > 0) renderChartMotivos(ultimoReporte.motivos);
      loadEvolucion(currentCentro);
    }, 0);
  });
});

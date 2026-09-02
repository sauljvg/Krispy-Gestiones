// Dashboard de KPIs de personal -- todo se calcula en vivo en el backend
// (ver backend/kpis.py) a partir de la última importación del informe de
// plantilla; aquí solo se pinta. Importar es solo admin, ver el resto de
// módulos de hoy (Entrevistas/Clima/Agregadores) para el mismo criterio.

const MARCA_COLOR = "#006838";
const COLORES = ["#006838", "#c98a12", "#1d6fb8", "#c23a72", "#7b4fb0", "#0e8a86", "#e0641e", "#3d5a80"];

function colorTextoActual() {
  return getComputedStyle(document.documentElement).getPropertyValue("--text-primary").trim() || "#000";
}

function wrapLabel(texto, maxLen = 18) {
  const palabras = (texto || "").split(/\s+/);
  const lineas = [];
  let actual = "";
  for (const palabra of palabras) {
    const candidata = actual ? `${actual} ${palabra}` : palabra;
    if (candidata.length > maxLen && actual) {
      lineas.push(actual);
      actual = palabra;
    } else {
      actual = candidata;
    }
  }
  if (actual) lineas.push(actual);
  return lineas;
}

let chartPorCentro, chartJornada, chartBajasMotivo, chartBajasCentro, chartPorPuesto;
let usuarioActual = null;

function barChart(canvasId, pares, { horizontal = true } = {}) {
  const el = document.getElementById(canvasId);
  const ctx = el.getContext("2d");
  const colorTexto = colorTextoActual();
  const movil = window.innerWidth < 700;
  const labels = pares.map(([nombre]) => wrapLabel(nombre, movil ? 16 : 20));
  const valores = pares.map(([, n]) => n);
  const eje = horizontal || movil ? "y" : "x";
  const escalaValor = { beginAtZero: true, ticks: { color: colorTexto, precision: 0 }, grid: { color: "rgba(128,128,128,0.2)" } };
  const escalaCategoria = { ticks: { color: colorTexto, autoSkip: false }, grid: { display: false } };
  return new Chart(ctx, {
    type: "bar",
    data: { labels, datasets: [{ data: valores, backgroundColor: MARCA_COLOR, borderRadius: 4 }] },
    options: {
      indexAxis: eje,
      responsive: true,
      maintainAspectRatio: false,
      scales: eje === "y" ? { x: escalaValor, y: escalaCategoria } : { y: escalaValor, x: escalaCategoria },
      plugins: { legend: { display: false } },
    },
  });
}

function donutChart(canvasId, labels, valores) {
  const ctx = document.getElementById(canvasId).getContext("2d");
  return new Chart(ctx, {
    type: "doughnut",
    data: { labels, datasets: [{ data: valores, backgroundColor: COLORES }] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { position: "bottom", labels: { color: colorTextoActual() } } },
    },
  });
}

function destruirCharts() {
  [chartPorCentro, chartJornada, chartBajasMotivo, chartBajasCentro, chartPorPuesto].forEach((c) => c?.destroy());
}

async function cargarResumen() {
  const dias = document.getElementById("kpi-periodo").value;
  const r = await fetch(`${AUTH_API_BASE}/kpis/resumen?dias=${dias}`);
  if (!r.ok) return;
  const d = await r.json();

  const sinDatos = d.headcount_activo === 0 && d.bajas_totales_historico === 0;
  document.getElementById("kpi-sin-datos").hidden = !sinDatos;
  document.getElementById("kpi-contenido").querySelectorAll(".kpi-stats-grid, .kpi-charts-grid, .kpi-chart-card").forEach((el) => {
    el.style.display = sinDatos ? "none" : "";
  });
  if (sinDatos) return;

  document.getElementById("kpi-headcount").textContent = d.headcount_activo;
  document.getElementById("kpi-rotacion").textContent = `${d.tasa_rotacion_pct}%`;
  document.getElementById("kpi-rotacion-sub").textContent = `${d.bajas_periodo} bajas en el periodo`;
  document.getElementById("kpi-antiguedad").textContent = d.antiguedad_media_meses != null ? `${d.antiguedad_media_meses} meses` : "--";
  document.getElementById("kpi-altas").textContent = d.altas_ultimos_90_dias;
  document.getElementById("kpi-bajas-prueba").textContent = `${d.bajas_prueba_pct}%`;

  destruirCharts();
  chartPorCentro = barChart("chart-por-centro", d.por_centro);
  chartJornada = donutChart("chart-jornada", ["Completa", "Parcial"], [d.jornada_completa, d.jornada_parcial]);
  chartBajasMotivo = barChart("chart-bajas-motivo", d.bajas_por_motivo);
  chartBajasCentro = barChart("chart-bajas-centro", d.bajas_por_centro);
  chartPorPuesto = barChart("chart-por-puesto", d.por_puesto);
}

async function cargarUltimaImportacion() {
  const r = await fetch(`${AUTH_API_BASE}/kpis/ultima-importacion`);
  if (!r.ok) return;
  const info = await r.json();
  const el = document.getElementById("kpi-ultima-importacion");
  el.textContent = info ? `Última importación: ${info.filas} empleados, ${info.importado_en}` : "";
}

async function importarExcel(file) {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch(`${AUTH_API_BASE}/kpis/importar`, { method: "POST", body: formData });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    mostrarAviso(err.detail || "No se pudo importar el archivo.");
    return;
  }
  await cargarUltimaImportacion();
  await cargarResumen();
}

document.addEventListener("DOMContentLoaded", async () => {
  const user = await checkAuth("/kpis.html");
  if (!user) return;
  if (!(user.modulos || []).includes("kpis")) {
    window.location.href = "/";
    return;
  }
  usuarioActual = user;
  wireUserBar(user);

  if (user.rol === "admin") {
    document.getElementById("kpi-import-wrap").hidden = false;
  }
  document.getElementById("kpi-input-importar").addEventListener("change", (e) => {
    const file = e.target.files[0];
    if (!file) return;
    importarExcel(file);
    e.target.value = "";
  });
  document.getElementById("kpi-periodo").addEventListener("change", cargarResumen);

  await cargarUltimaImportacion();
  await cargarResumen();
});

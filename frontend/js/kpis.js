// Dashboard de KPIs de personal -- todo se calcula en vivo en el backend
// (ver backend/kpis.py) a partir de dos fuentes: la última importación del
// informe de plantilla (Excel de GO) y las bajas registradas en Entrevista
// de Salida (en vivo, se actualiza sola). Aquí solo se pinta. Importar es
// solo admin, ver el resto de módulos de hoy (Entrevistas/Clima/Agregadores)
// para el mismo criterio.

const MARCA_COLOR = "#006838";
const COLOR_ALERTA = "#c23a72";
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

function formatMes(clave) {
  if (!clave) return "";
  const [anio, mes] = clave.split("-");
  const nombres = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
  return `${nombres[parseInt(mes, 10) - 1]} ${anio.slice(2)}`;
}

function motivoCorto(motivo) {
  // Los motivos son textos largos tipo SEPE ("02 Despido por causas
  // objetivas. Amortización por causas económicas, técnicas..."). Para el
  // gráfico basta con la primera frase -- si no hay punto, se recorta a un
  // máximo razonable para que no se solape con las barras vecinas.
  if (!motivo) return motivo;
  const corte = motivo.indexOf(".");
  let corto = corte > 0 ? motivo.slice(0, corte) : motivo;
  if (corto.length > 45) corto = `${corto.slice(0, 42)}…`;
  return corto;
}

let chartRotacionMensual, chartRotacionCentro, chartHorasCentro, chartBajasMotivo;
let usuarioActual = null;
let ultimoResumen = null;

function lineChart(canvasId, labels, valores) {
  const ctx = document.getElementById(canvasId).getContext("2d");
  const colorTexto = colorTextoActual();
  return new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [{
        data: valores,
        borderColor: MARCA_COLOR,
        backgroundColor: MARCA_COLOR,
        tension: 0.3,
        pointRadius: 4,
        pointBackgroundColor: MARCA_COLOR,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: { ticks: { color: colorTexto }, grid: { display: false } },
        y: { beginAtZero: true, ticks: { color: colorTexto, precision: 0 }, grid: { color: "rgba(128,128,128,0.2)" } },
      },
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: (ctx2) => `${ctx2.parsed.y} baja${ctx2.parsed.y === 1 ? "" : "s"}` } },
      },
    },
  });
}

function barChart(canvasId, pares, { horizontal = true, sufijo = "" } = {}) {
  const el = document.getElementById(canvasId);
  const ctx = el.getContext("2d");
  const colorTexto = colorTextoActual();
  const movil = window.innerWidth < 700;
  const labels = pares.map(([nombre]) => wrapLabel(nombre, movil ? 16 : 20));
  const valores = pares.map(([, n]) => n);
  const eje = horizontal || movil ? "y" : "x";
  const escalaValor = { beginAtZero: true, ticks: { color: colorTexto, precision: 0, callback: (v) => `${v}${sufijo}` }, grid: { color: "rgba(128,128,128,0.2)" } };
  const escalaCategoria = { ticks: { color: colorTexto, autoSkip: false }, grid: { display: false } };
  return new Chart(ctx, {
    type: "bar",
    data: { labels, datasets: [{ data: valores, backgroundColor: MARCA_COLOR, borderRadius: 4 }] },
    options: {
      indexAxis: eje,
      responsive: true,
      maintainAspectRatio: false,
      scales: eje === "y" ? { x: escalaValor, y: escalaCategoria } : { y: escalaValor, x: escalaCategoria },
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: (ctx2) => `${ctx2.parsed[eje === "y" ? "x" : "y"]}${sufijo}` } } },
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
  [chartRotacionMensual, chartRotacionCentro, chartHorasCentro, chartBajasMotivo].forEach((c) => c?.destroy());
}

async function cargarResumen() {
  const r = await fetch(`${AUTH_API_BASE}/kpis/resumen`);
  if (!r.ok) return;
  const d = await r.json();

  document.getElementById("kpi-sin-datos").hidden = !d.sin_datos_plantilla;
  document.getElementById("kpi-contenido").querySelectorAll(".kpi-stats-grid, .kpi-charts-grid, .kpi-chart-card").forEach((el) => {
    el.style.display = d.sin_datos_plantilla ? "none" : "";
  });
  if (d.sin_datos_plantilla) return;

  document.getElementById("kpi-headcount").textContent = d.headcount_activo;
  document.getElementById("kpi-rotacion-anual").textContent = `${d.acumulado_anual_pct}%`;
  document.getElementById("kpi-rotacion-anual-sub").textContent = `${d.bajas_ytd} bajas en lo que va de año`;

  const mesActualPct = d.rotacion_mensual.length ? d.rotacion_mensual[d.rotacion_mensual.length - 1].pct : 0;
  const bajasMesActual = d.rotacion_mensual.length ? d.rotacion_mensual[d.rotacion_mensual.length - 1].bajas : 0;
  document.getElementById("kpi-rotacion-mes").textContent = bajasMesActual;
  document.getElementById("kpi-rotacion-mes-sub").textContent = `${formatMes(d.mes_actual)} -- ${mesActualPct}% sobre la plantilla activa`;
  document.getElementById("kpi-rotacion-centro-sub").textContent = `Mes en curso (${formatMes(d.mes_actual)}).`;

  document.getElementById("kpi-nspp").textContent = d.bajas_ytd ? `${d.nspp_pct}%` : "--";
  document.getElementById("kpi-horas").textContent = `${d.horas_contratadas_totales} h/sem`;

  document.getElementById("kpi-rotacion-sin-nspp").textContent = `${d.rotacion_sin_nspp_empresario_pct}%`;
  document.getElementById("kpi-rotacion-sin-nspp-sub").textContent =
    `${d.bajas_sin_nspp_empresario_ytd} de ${d.bajas_ytd} bajas del año -- sin los ceses en prueba a instancia del empresario`;

  destruirCharts();
  chartRotacionMensual = lineChart(
    "chart-rotacion-mensual",
    d.rotacion_mensual.map((m) => formatMes(m.mes)),
    d.rotacion_mensual.map((m) => m.bajas)
  );
  if (d.rotacion_por_centro_mes_actual.length) {
    chartRotacionCentro = barChart("chart-rotacion-centro", d.rotacion_por_centro_mes_actual, { sufijo: "%" });
  }
  if (d.horas_por_centro.length) {
    chartHorasCentro = barChart("chart-horas-centro", d.horas_por_centro, { sufijo: "h" });
  }

  ultimoResumen = d;
  poblarFiltroMesMotivo(d);
  renderBajasMotivo();
}

const NOMBRES_MES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"];

function poblarFiltroMesMotivo(d) {
  const selectMes = document.getElementById("kpi-bajas-motivo-mes");
  const selectAnio = document.getElementById("kpi-bajas-motivo-anio");
  const mesPrevio = selectMes.value;
  const anioPrevio = selectAnio.value;

  selectMes.innerHTML = '<option value="todos">Todo el año</option>';
  NOMBRES_MES.forEach((nombre, i) => {
    const opt = document.createElement("option");
    opt.value = String(i + 1).padStart(2, "0");
    opt.textContent = nombre;
    selectMes.appendChild(opt);
  });

  const anios = d.anios_disponibles && d.anios_disponibles.length ? d.anios_disponibles : [String(new Date().getFullYear())];
  selectAnio.innerHTML = "";
  for (const anio of anios) {
    const opt = document.createElement("option");
    opt.value = anio;
    opt.textContent = anio;
    selectAnio.appendChild(opt);
  }

  const opcionesMes = Array.from(selectMes.options).map((o) => o.value);
  selectMes.value = opcionesMes.includes(mesPrevio) ? mesPrevio : "todos";
  selectAnio.value = anios.includes(anioPrevio) ? anioPrevio : anios[anios.length - 1];
}

function renderBajasMotivo() {
  if (!ultimoResumen) return;
  const d = ultimoResumen;
  const mes = document.getElementById("kpi-bajas-motivo-mes").value;
  const anio = document.getElementById("kpi-bajas-motivo-anio").value;

  let pares;
  let etiqueta;
  if (mes === "todos") {
    const acumulado = {};
    for (const [clave, lista] of Object.entries(d.bajas_por_motivo_mensual)) {
      if (!clave.startsWith(`${anio}-`)) continue;
      for (const [motivo, n] of lista) acumulado[motivo] = (acumulado[motivo] || 0) + n;
    }
    pares = Object.entries(acumulado).sort((a, b) => b[1] - a[1]);
    etiqueta = `Año ${anio}`;
  } else {
    const clave = `${anio}-${mes}`;
    pares = d.bajas_por_motivo_mensual[clave] || [];
    etiqueta = `${NOMBRES_MES[parseInt(mes, 10) - 1]} ${anio}`;
  }
  document.getElementById("kpi-bajas-motivo-sub").textContent = `${etiqueta}, según Entrevista de Salida.`;

  const sinBajas = pares.length === 0;
  document.getElementById("kpi-bajas-motivo-aviso").hidden = !sinBajas;
  document.getElementById("chart-bajas-motivo").style.display = sinBajas ? "none" : "";
  chartBajasMotivo?.destroy();
  if (!sinBajas) {
    chartBajasMotivo = barChart("chart-bajas-motivo", pares.map(([m, n]) => [motivoCorto(m), n]));
  }
}

async function cargarUltimaImportacion() {
  const r = await fetch(`${AUTH_API_BASE}/kpis/ultima-importacion`);
  if (!r.ok) return;
  const info = await r.json();
  const el = document.getElementById("kpi-ultima-importacion");
  el.textContent = info ? `Última importación de plantilla: ${info.filas} empleados, ${info.importado_en}` : "";
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
  document.getElementById("kpi-bajas-motivo-mes").addEventListener("change", () => renderBajasMotivo());
  document.getElementById("kpi-bajas-motivo-anio").addEventListener("change", () => renderBajasMotivo());

  await cargarUltimaImportacion();
  await cargarResumen();
});

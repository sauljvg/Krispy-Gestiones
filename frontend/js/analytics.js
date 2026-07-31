let timelineChart = null;
let distributionChart = null;
let horaChart = null;
let diaSemanaChart = null;

// Paleta fija por tienda (no depende de design-tokens.json, que es de marca
// KK/Saona — aquí hacen falta N colores distintos para distinguir líneas).
const PALETA_EVOLUCION = ["#1b5e20", "#c62828", "#1565c0", "#ef6c00", "#6a1b9a", "#00838f", "#ad1457"];

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

// Con `porTienda` (solo llega cuando la vista es "Todas", ver loadTimeline)
// se dibuja una línea ACUMULADA por tienda en vez del único agregado
// diario — así se ve el crecimiento de cada una en el mismo gráfico, con o
// sin filtro de fechas puesto (los días que se muestren ya vienen
// recortados desde el backend si hay Desde/Hasta). Granularidad diaria (no
// mensual): con meses de historia esto son varios cientos de puntos, así
// que se dibuja sin marcador por punto (solo la línea) para que no se vea
// saturado — Chart.js igual resalta el punto más cercano al pasar el ratón.
function renderTimelineChart(timeline, porTienda) {
  const ctx = document.getElementById("chart-timeline");
  if (timelineChart) timelineChart.destroy();

  if (porTienda && porTienda.series.length) {
    const datasets = porTienda.series.map((s, i) => ({
      label: s.tienda,
      data: s.acumulado,
      borderColor: PALETA_EVOLUCION[i % PALETA_EVOLUCION.length],
      backgroundColor: PALETA_EVOLUCION[i % PALETA_EVOLUCION.length],
      borderWidth: 2,
      pointRadius: 0,
      pointHoverRadius: 4,
      fill: false,
      tension: 0.1,
    }));
    timelineChart = new Chart(ctx, {
      type: "line",
      data: { labels: porTienda.dias, datasets },
      options: {
        responsive: true,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { position: "bottom", labels: { usePointStyle: true, pointStyle: "circle", color: cssVar("--text-muted") } },
        },
        scales: {
          x: { grid: { color: cssVar("--gridline") }, ticks: { color: cssVar("--text-muted"), autoSkip: true, maxRotation: 0 } },
          y: { beginAtZero: true, grid: { color: cssVar("--gridline") }, ticks: { color: cssVar("--text-muted"), precision: 0 } },
        },
      },
    });
    return;
  }

  const labels = timeline.map((t) => t.dia);
  const counts = timeline.map((t) => t.cantidad);
  timelineChart = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [{
        label: "Reseñas por día",
        data: counts,
        borderColor: cssVar("--acento"),
        backgroundColor: cssVar("--acento") + "26",
        borderWidth: 2,
        pointRadius: 0,
        pointHoverRadius: 4,
        fill: true,
        tension: 0.2,
      }],
    },
    options: {
      responsive: true,
      interaction: { mode: "index", intersect: false },
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { color: cssVar("--gridline") }, ticks: { color: cssVar("--text-muted"), autoSkip: true, maxRotation: 0 } },
        y: { beginAtZero: true, grid: { color: cssVar("--gridline") }, ticks: { color: cssVar("--text-muted") } },
      },
    },
  });
}

function renderDistributionChart(distribucion) {
  const ctx = document.getElementById("chart-distribution");
  const orderedStars = [5, 4, 3, 2, 1];
  const byStars = Object.fromEntries(distribucion.map((d) => [d.estrellas, d.cantidad]));
  const counts = orderedStars.map((s) => byStars[s] || 0);

  if (distributionChart) distributionChart.destroy();
  distributionChart = new Chart(ctx, {
    type: "bar",
    data: {
      labels: orderedStars.map((s) => `${s} ★`),
      datasets: [{
        label: "Reseñas",
        data: counts,
        backgroundColor: cssVar("--acento"),
        borderRadius: 4,
        maxBarThickness: 46,
      }],
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { display: false }, ticks: { color: cssVar("--text-muted") } },
        y: { beginAtZero: true, grid: { color: cssVar("--gridline") }, ticks: { color: cssVar("--text-muted") } },
      },
    },
  });
}

function renderHoraChart(porHora) {
  const ctx = document.getElementById("chart-hora");
  if (horaChart) horaChart.destroy();
  horaChart = new Chart(ctx, {
    type: "bar",
    data: {
      labels: porHora.map((h) => `${h.hora}h`),
      datasets: [{
        label: "Reseñas",
        data: porHora.map((h) => h.cantidad),
        backgroundColor: cssVar("--acento"),
        borderRadius: 4,
        maxBarThickness: 22,
      }],
    },
    options: {
      responsive: true,
      onClick: (evt, elements) => {
        if (!elements.length) return;
        selectHoraFiltro(porHora[elements[0].index].hora);
      },
      onHover: (evt, elements) => {
        evt.native.target.style.cursor = elements.length ? "pointer" : "default";
      },
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { display: false }, ticks: { color: cssVar("--text-muted") } },
        y: { beginAtZero: true, grid: { color: cssVar("--gridline") }, ticks: { color: cssVar("--text-muted"), precision: 0 } },
      },
    },
  });
}

function renderDiaSemanaChart(porDia) {
  const ctx = document.getElementById("chart-dia-semana");
  if (diaSemanaChart) diaSemanaChart.destroy();
  diaSemanaChart = new Chart(ctx, {
    type: "bar",
    data: {
      labels: porDia.map((d) => d.dia),
      datasets: [{
        label: "Reseñas",
        data: porDia.map((d) => d.cantidad),
        backgroundColor: cssVar("--acento"),
        borderRadius: 4,
        maxBarThickness: 46,
      }],
    },
    options: {
      responsive: true,
      onClick: (evt, elements) => {
        if (!elements.length) return;
        selectDiaSemanaFiltro(porDia[elements[0].index].dia);
      },
      onHover: (evt, elements) => {
        evt.native.target.style.cursor = elements.length ? "pointer" : "default";
      },
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { display: false }, ticks: { color: cssVar("--text-muted") } },
        y: { beginAtZero: true, grid: { color: cssVar("--gridline") }, ticks: { color: cssVar("--text-muted"), precision: 0 } },
      },
    },
  });
}

function evolucionFilaHTML(e) {
  const deltaResenas = e.total_final - e.total_inicio;
  const tieneAmbasNotas = e.promedio_inicio != null && e.promedio_final != null;
  const deltaEstrellas = tieneAmbasNotas ? Math.round((e.promedio_final - e.promedio_inicio) * 10) / 10 : null;
  const claseDelta = deltaResenas > 0 ? "rating-trend-up" : deltaResenas < 0 ? "rating-trend-down" : "";
  const textoDelta = deltaEstrellas !== null
    ? `${deltaResenas >= 0 ? "+" : ""}${deltaResenas} reseñas / ${deltaEstrellas >= 0 ? "+" : ""}${deltaEstrellas.toFixed(1)}★`
    : `${deltaResenas >= 0 ? "+" : ""}${deltaResenas} reseñas`;
  return `
    <tr>
      <td>${escapeHTML(e.tienda)}</td>
      <td>${e.total_inicio.toLocaleString("es-ES")} → ${e.total_final.toLocaleString("es-ES")}</td>
      <td>${e.promedio_inicio ?? "—"} → ${e.promedio_final ?? "—"} ★</td>
      <td class="${claseDelta}">${textoDelta}</td>
    </tr>
  `;
}

function renderKeywords(keywords) {
  const container = document.getElementById("keywords-list");
  container.innerHTML = keywords
    .map((k) => `<span class="keyword-chip"><b>${k.palabra}</b> · ${k.frecuencia}</span>`)
    .join("");
}

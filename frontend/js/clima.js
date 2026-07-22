let currentOleada = null;
let currentCentro = null;

const COLOR_CATEGORIA = {
  "Totalmente de acuerdo": "#006838",
  "De acuerdo": "#eda100",
  "Neutral": "#8f8f89",
  "En desacuerdo": "#e8622c",
  "Totalmente en desacuerdo": "#a83232",
};
const ORDEN_CATEGORIAS = Object.keys(COLOR_CATEGORIA);

let chartResultados = null;
let chartImpulsores = null;
let ultimoReporte = null;

function colorTextoActual() {
  return getComputedStyle(document.documentElement).getPropertyValue("--text-primary").trim() || "#000";
}

function escapeHTML(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

async function loadOleadas() {
  const res = await fetch(`${AUTH_API_BASE}/clima/oleadas`);
  const oleadas = await res.json();
  const select = document.getElementById("select-oleada");
  select.innerHTML = oleadas
    .map((o) => `<option value="${o.id}">${o.etiqueta || `Oleada #${o.id}`} (${o.num_respuestas} respuestas · ${o.creado_en.slice(0, 10)})</option>`)
    .join("");
  if (oleadas.length === 0) {
    document.getElementById("centro-grid").innerHTML = `<p class="staff-hint">Todavía no has importado ningún Excel de Clima Laboral.</p>`;
    return;
  }
  currentOleada = oleadas[0].id;
  select.value = currentOleada;
  await loadCentros();
}

async function loadCentros() {
  const res = await fetch(`${AUTH_API_BASE}/clima/${currentOleada}/centros`);
  const centros = await res.json();
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
  if (centros.length > 0) {
    grid.querySelector(".centro-card").classList.add("active");
    await loadReporte(null);
  }
}

function barraStackedData(items) {
  const labels = items.map((i) => i.pregunta);
  const datasets = ORDEN_CATEGORIAS.map((cat) => ({
    label: cat,
    data: items.map((i) => i.porcentajes[cat]),
    backgroundColor: COLOR_CATEGORIA[cat],
    stack: "s",
  }));
  return { labels, datasets };
}

const percentLabelsPlugin = {
  id: "percentLabels",
  afterDatasetsDraw(chart) {
    const { ctx } = chart;
    chart.data.datasets.forEach((dataset, datasetIndex) => {
      const meta = chart.getDatasetMeta(datasetIndex);
      if (meta.hidden) return;
      meta.data.forEach((bar, index) => {
        const value = dataset.data[index];
        if (value >= 6) {
          const centroX = (bar.x + bar.base) / 2;
          ctx.save();
          ctx.fillStyle = "#fff";
          ctx.font = "bold 11px Poppins, sans-serif";
          ctx.textAlign = "center";
          ctx.textBaseline = "middle";
          ctx.fillText(`${value}%`, centroX, bar.y);
          ctx.restore();
        }
      });
    });
  },
};

function renderChart(canvasId, existingChart, items) {
  const ctx = document.getElementById(canvasId);
  if (existingChart) existingChart.destroy();
  const alturaPorFila = 42;
  ctx.parentElement.style.height = `${Math.max(items.length * alturaPorFila, 80)}px`;
  const colorTexto = colorTextoActual();
  return new Chart(ctx, {
    type: "bar",
    data: barraStackedData(items),
    plugins: [percentLabelsPlugin],
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: { stacked: true, max: 100, ticks: { color: colorTexto, callback: (v) => `${v}%` }, grid: { color: "rgba(128,128,128,0.2)" } },
        y: { stacked: true, ticks: { color: colorTexto }, grid: { display: false } },
      },
      plugins: {
        legend: {
          display: canvasId === "chart-resultados",
          position: "bottom",
          labels: { boxWidth: 12, font: { size: 11 }, color: colorTexto },
        },
        tooltip: {
          callbacks: {
            label: (ctx) => `${ctx.dataset.label}: ${ctx.parsed.x}%`,
          },
        },
      },
    },
  });
}

function renderNube(container, entradas) {
  if (!entradas || entradas.length === 0) {
    container.innerHTML = `<p class="staff-hint">(sin comentarios)</p>`;
    return;
  }
  const max = Math.max(...entradas.map((e) => e.veces));
  container.innerHTML = entradas
    .map((e) => {
      const tam = 12 + Math.round((e.veces / max) * 20);
      return `<span class="nube-palabra" style="font-size:${tam}px;">${escapeHTML(e.palabra)}</span>`;
    })
    .join(" ");
}

async function loadReporte(centro) {
  currentCentro = centro;
  const params = new URLSearchParams();
  if (centro) params.set("centro", centro);
  const res = await fetch(`${AUTH_API_BASE}/clima/${currentOleada}/reporte?${params.toString()}`);
  if (!res.ok) return;
  const data = await res.json();
  ultimoReporte = data;

  document.getElementById("reporte-wrap").hidden = false;
  document.getElementById("btn-exportar-pdf").hidden = false;

  document.getElementById("clima-header-stats").innerHTML = `
    <span>N = <b>${data.n}</b></span>
    <span>Empleados = <b>${data.empleados ?? "—"}</b></span>
    <span>Participación = <b>${data.participacion !== null ? data.participacion + "%" : "—"}</b></span>
  `;

  document.getElementById("score-boxes").innerHTML = `
    <div class="score-box score-presente">
      <div class="score-label">Presente</div>
      <div class="score-value">${data.engagement_presente !== null ? data.engagement_presente + "%" : "—"}</div>
    </div>
    <div class="score-box score-anterior">
      <div class="score-label">Anterior</div>
      <div class="score-value">${data.engagement_anterior !== null ? data.engagement_anterior + "%" : "—"}</div>
    </div>
  `;

  chartResultados = renderChart("chart-resultados", chartResultados, data.resultados_engagement);
  chartImpulsores = renderChart("chart-impulsores", chartImpulsores, data.impulsores_engagement);

  document.getElementById("fo-grid").innerHTML = `
    <div class="fo-col">
      <h3>Fortalezas (¡Celébralo con el equipo!)</h3>
      ${data.fortalezas.map((i) => `<p class="fo-fortaleza">+ ${escapeHTML(i.pregunta)} (${i.top2box}%)</p>`).join("")}
    </div>
    <div class="fo-col">
      <h3>Oportunidades (plan de acción)</h3>
      ${data.oportunidades.map((i) => `<p class="fo-oportunidad">- ${escapeHTML(i.pregunta)} (${i.top2box}%)</p>`).join("")}
    </div>
  `;

  const comentariosWrap = document.getElementById("comentarios-wrap");
  const headers = Object.keys(data.nube_palabras);
  comentariosWrap.innerHTML = headers
    .map(
      (h, i) => `
      <h3 style="font-size:13px;">${escapeHTML(h)}</h3>
      <div class="nube-wrap" id="nube-${i}"></div>
      <div class="comentarios-lista" id="lista-${i}"></div>
    `
    )
    .join("");
  headers.forEach((h, i) => {
    renderNube(document.getElementById(`nube-${i}`), data.nube_palabras[h]);
    renderListaComentarios(document.getElementById(`lista-${i}`), data.abiertas[h]);
  });
}

function renderListaComentarios(container, textos) {
  if (!textos || textos.length === 0) {
    container.innerHTML = "";
    return;
  }
  container.innerHTML =
    `<p class="comentarios-lista-titulo">Respuestas</p>` +
    `<ul>${textos.map((t) => `<li>${escapeHTML(t)}</li>`).join("")}</ul>`;
}

document.addEventListener("DOMContentLoaded", async () => {
  const user = await checkAuth("/clima.html");
  if (!user) return;
  if (!esRolTodo(user.rol)) {
    window.location.href = "/";
    return;
  }
  wireUserBar(user);

  await loadOleadas();

  document.getElementById("select-oleada").addEventListener("change", async (e) => {
    currentOleada = Number(e.target.value);
    document.getElementById("reporte-wrap").hidden = true;
    document.getElementById("btn-exportar-pdf").hidden = true;
    await loadCentros();
  });

  document.getElementById("input-clima-upload").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const nuevaOleada = document.getElementById("check-nueva-oleada").checked;
    const formData = new FormData();
    formData.append("file", file);
    formData.append("nueva_oleada", nuevaOleada ? "true" : "false");
    const res = await fetch(`${AUTH_API_BASE}/clima/importar`, { method: "POST", body: formData });
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

  document.getElementById("btn-exportar-pdf").addEventListener("click", () => {
    const params = new URLSearchParams();
    if (currentCentro) params.set("centro", currentCentro);
    window.open(`${AUTH_API_BASE}/clima/${currentOleada}/reporte.pdf?${params.toString()}`, "_blank");
  });

  document.getElementById("btn-theme-toggle").addEventListener("click", () => {
    setTimeout(() => {
      if (!ultimoReporte) return;
      chartResultados = renderChart("chart-resultados", chartResultados, ultimoReporte.resultados_engagement);
      chartImpulsores = renderChart("chart-impulsores", chartImpulsores, ultimoReporte.impulsores_engagement);
    }, 0);
  });
});

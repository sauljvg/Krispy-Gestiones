const LETRAS_DISC = ["D", "I", "S", "C"];
const COLOR_LETRA_DISC = { D: "#f15b4e", I: "#f2d351", S: "#80ba5b", C: "#5090ad" };

let PREGUNTAS_DISC = [];
let PESOS_RANKING = [4, 3, 2, 1];
let FACTORES_TTI = {
  adaptado: { top: 3.5, bottom: 0.7, target: 200 },
  natural: { top: 3.8, bottom: 0.5, target: 205 },
};

let respondidas = new Set();
let chartPreview = null;
let chartResultado = null;
let ultimoResultado = null;

function escapeHTML(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

function shuffle(arr) {
  const a = arr.slice();
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

function colorTextoActual() {
  return getComputedStyle(document.documentElement).getPropertyValue("--text-primary").trim() || "#000";
}

// ==================== Algoritmo (espejo del backend, ver disc_module.py) ====================

function calcularPuntosBrutos(respuestas) {
  const puntos = { D: 0, I: 0, S: 0, C: 0 };
  respuestas.forEach((ordenLetras) => {
    ordenLetras.forEach((letra, i) => {
      puntos[letra] += PESOS_RANKING[i];
    });
  });
  return puntos;
}

function perfilTti(puntosBrutos, perfil) {
  const factores = FACTORES_TTI[perfil];
  const orden = Object.entries(puntosBrutos).sort((a, b) => b[1] - a[1]);
  const [[l1, v1], [l2, v2], [l3, v3], [l4, v4]] = orden;
  const total = v1 + v2 + v3 + v4;
  if (total <= 0) return { D: 0, I: 0, S: 0, C: 0 };
  const [pct1, pct2, pct3, pct4] = [v1, v2, v3, v4].map((v) => (v / total) * 100);
  const val1 = pct1 * factores.top;
  const val2 = pct2 * factores.top;
  const val3 = pct3 * factores.bottom;
  const val4 = pct4 * factores.bottom;
  const totalPol = val1 + val2 + val3 + val4;
  const factorNorm = totalPol ? factores.target / totalPol : 0;
  const resultado = {};
  resultado[l1] = Math.round(val1 * factorNorm);
  resultado[l2] = Math.round(val2 * factorNorm);
  resultado[l3] = Math.round(val3 * factorNorm);
  resultado[l4] = Math.round(val4 * factorNorm);
  return resultado;
}

function tipoDisc(perfil) {
  const orden = Object.entries(perfil).sort((a, b) => b[1] - a[1]);
  return orden[0][0] + orden[1][0];
}

function leerRespuestasActuales() {
  return [...document.querySelectorAll(".disc-opciones")].map((ul) =>
    [...ul.querySelectorAll("li")].map((li) => li.dataset.letra)
  );
}

// ==================== Render preguntas + drag&drop ====================

function renderPreguntas() {
  const wrap = document.getElementById("disc-preguntas-wrap");
  wrap.innerHTML = PREGUNTAS_DISC.map((p, i) => {
    const opciones = shuffle(LETRAS_DISC.map((letra) => ({ letra, texto: p[letra] })));
    const lis = opciones
      .map((o, rankIdx) => `<li draggable="true" data-letra="${o.letra}"><span class="disc-rank-badge">${rankIdx + 1}</span>${escapeHTML(o.texto)}</li>`)
      .join("");
    return `
    <div class="disc-pregunta" id="disc-pregunta-${i}">
      <div class="disc-pregunta-num">Pregunta ${i + 1} / ${PREGUNTAS_DISC.length}</div>
      <p class="disc-pregunta-hint">Arrastra para ordenar: arriba = lo que más te describe, abajo = lo que menos.</p>
      <ul class="disc-opciones" data-q="${i}">${lis}</ul>
    </div>`;
  }).join("");

  wrap.querySelectorAll(".disc-opciones").forEach((ul) => habilitarDragDrop(ul));
  respondidas = new Set();
  actualizarProgreso();
  recalcularPreview();
}

function habilitarDragDrop(ul) {
  ul.querySelectorAll("li").forEach((li) => {
    li.addEventListener("dragstart", () => {
      li.classList.add("dragging");
    });
    li.addEventListener("dragend", () => {
      li.classList.remove("dragging");
      actualizarBadges(ul);
      marcarRespondida(ul);
      recalcularPreview();
    });
  });

  ul.addEventListener("dragover", (e) => {
    e.preventDefault();
    const dragging = ul.querySelector(".dragging");
    if (!dragging) return;
    const after = elementoTrasCursor(ul, e.clientY);
    if (after == null) ul.appendChild(dragging);
    else ul.insertBefore(dragging, after);
  });
}

function elementoTrasCursor(container, y) {
  const els = [...container.querySelectorAll("li:not(.dragging)")];
  return els.reduce(
    (closest, child) => {
      const box = child.getBoundingClientRect();
      const offset = y - box.top - box.height / 2;
      if (offset < 0 && offset > closest.offset) return { offset, element: child };
      return closest;
    },
    { offset: Number.NEGATIVE_INFINITY, element: null }
  ).element;
}

function actualizarBadges(ul) {
  ul.querySelectorAll("li").forEach((li, i) => {
    li.querySelector(".disc-rank-badge").textContent = i + 1;
  });
}

function marcarRespondida(ul) {
  const idx = Number(ul.dataset.q);
  respondidas.add(idx);
  document.getElementById(`disc-pregunta-${idx}`).classList.add("respondida");
  actualizarProgreso();
}

function actualizarProgreso() {
  document.getElementById("disc-progreso").textContent = `${respondidas.size} / ${PREGUNTAS_DISC.length} respondidas`;
  const nombreOk = document.getElementById("input-nombre-disc").value.trim().length > 0;
  document.getElementById("btn-guardar-disc").disabled = !(nombreOk && respondidas.size === PREGUNTAS_DISC.length);
}

// ==================== Vista previa en tiempo real ====================

function recalcularPreview() {
  const respuestas = leerRespuestasActuales();
  const puntosBrutos = calcularPuntosBrutos(respuestas);
  const adaptado = perfilTti(puntosBrutos, "adaptado");
  const natural = perfilTti(puntosBrutos, "natural");
  const tipo = tipoDisc(adaptado);

  document.getElementById("disc-preview-tipo").textContent = respondidas.size > 0 ? tipo : "— —";
  renderRadar("chart-disc-preview", adaptado, natural, (c) => {
    chartPreview = c;
  }, chartPreview);
}

function renderRadar(canvasId, adaptado, natural, setter, existing) {
  const ctx = document.getElementById(canvasId);
  if (existing) existing.destroy();
  const colorTexto = colorTextoActual();
  const chart = new Chart(ctx, {
    type: "radar",
    data: {
      labels: LETRAS_DISC.map((l) => ({ D: "D · Dominancia", I: "I · Influencia", S: "S · Estabilidad", C: "C · Cumplimiento" }[l])),
      datasets: [
        {
          label: "Adaptado",
          data: LETRAS_DISC.map((l) => adaptado[l] ?? 0),
          borderColor: "#e0824a",
          backgroundColor: "rgba(224,130,74,0.2)",
        },
        {
          label: "Natural",
          data: LETRAS_DISC.map((l) => natural[l] ?? 0),
          borderColor: "#5090ad",
          backgroundColor: "rgba(80,144,173,0.2)",
        },
      ],
    },
    options: {
      responsive: true,
      scales: {
        r: {
          min: 0,
          suggestedMax: 100,
          angleLines: { color: "rgba(128,128,128,0.25)" },
          grid: { color: "rgba(128,128,128,0.25)" },
          pointLabels: { color: colorTexto, font: { size: 11 } },
          ticks: { display: false, backdropColor: "transparent" },
        },
      },
      plugins: { legend: { labels: { color: colorTexto } } },
    },
  });
  setter(chart);
  return chart;
}

// ==================== Guardar / resultado ====================

async function guardarResultado() {
  const nombre = document.getElementById("input-nombre-disc").value.trim();
  const respuestas = leerRespuestasActuales();
  const btn = document.getElementById("btn-guardar-disc");
  btn.disabled = true;
  btn.textContent = "Guardando...";
  try {
    const res = await fetch(`${AUTH_API_BASE}/disc/calcular`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nombre, respuestas }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      alert(err.detail || "No se pudo guardar el resultado.");
      return;
    }
    const data = await res.json();
    mostrarResultado(data);
  } finally {
    btn.textContent = "Guardar resultado";
    actualizarProgreso();
  }
}

function mostrarResultado(data) {
  ultimoResultado = data;
  document.getElementById("disc-resultado-card").hidden = false;
  document.getElementById("disc-resultado-tipo").textContent = data.tipo_disc;
  renderRadar("chart-disc-resultado", data.perfil_adaptado, data.perfil_natural, (c) => {
    chartResultado = c;
  }, chartResultado);
  document.getElementById("btn-exportar-pdf-disc").onclick = () => {
    window.open(`${AUTH_API_BASE}/disc/resultado/${data.id}/pdf`, "_blank");
  };
  document.getElementById("disc-resultado-card").scrollIntoView({ behavior: "smooth", block: "start" });
}

function nuevoTest() {
  document.getElementById("input-nombre-disc").value = "";
  document.getElementById("disc-resultado-card").hidden = true;
  renderPreguntas();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

// ==================== Histórico ====================

let historicoCache = [];

async function cargarHistorico() {
  const res = await fetch(`${AUTH_API_BASE}/disc/historico`);
  if (!res.ok) return;
  historicoCache = await res.json();
  renderHistorico(historicoCache);
}

function renderHistorico(items) {
  const tbody = document.getElementById("tabla-historico-body");
  if (items.length === 0) {
    tbody.innerHTML = `<tr><td colspan="8" class="staff-hint">(sin tests registrados todavía)</td></tr>`;
    return;
  }
  tbody.innerHTML = items
    .map(
      (it) => `
    <tr data-id="${it.id}">
      <td>${escapeHTML(it.nombre)}</td>
      <td>${escapeHTML((it.fecha_test || "").slice(0, 16).replace("T", " "))}</td>
      <td><span class="disc-tipo-pill">${escapeHTML(it.tipo_disc)}</span></td>
      <td>${it.perfil_adaptado.D}</td>
      <td>${it.perfil_adaptado.I}</td>
      <td>${it.perfil_adaptado.S}</td>
      <td>${it.perfil_adaptado.C}</td>
      <td style="white-space:nowrap;">
        <button type="button" class="btn-registrar-salida btn-ver-pdf-historico">PDF</button>
        <button type="button" class="btn-registrar-salida btn-ghost btn-borrar-historico">Borrar</button>
      </td>
    </tr>`
    )
    .join("");

  tbody.querySelectorAll(".btn-ver-pdf-historico").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = btn.closest("tr").dataset.id;
      window.open(`${AUTH_API_BASE}/disc/resultado/${id}/pdf`, "_blank");
    });
  });
  tbody.querySelectorAll(".btn-borrar-historico").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.closest("tr").dataset.id;
      if (!confirm("¿Borrar este resultado DISC?")) return;
      const res = await fetch(`${AUTH_API_BASE}/disc/resultado/${id}`, { method: "DELETE" });
      if (res.ok) await cargarHistorico();
    });
  });
}

// ==================== Init ====================

function mostrarTab(tab) {
  const esNuevo = tab === "nuevo";
  document.getElementById("vista-nuevo").hidden = !esNuevo;
  document.getElementById("vista-historico").hidden = esNuevo;
  document.getElementById("tab-nuevo").classList.toggle("active", esNuevo);
  document.getElementById("tab-historico").classList.toggle("active", !esNuevo);
  if (!esNuevo) cargarHistorico();
}

document.addEventListener("DOMContentLoaded", async () => {
  const user = await checkAuth("/disc_form.html");
  if (!user) return;
  if (!(user.modulos || []).includes("disc")) {
    window.location.href = "/";
    return;
  }
  wireUserBar(user);

  const [preguntasRes, configRes] = await Promise.all([
    fetch(`${AUTH_API_BASE}/disc/preguntas`),
    fetch(`${AUTH_API_BASE}/disc/config`),
  ]);
  PREGUNTAS_DISC = await preguntasRes.json();
  const config = await configRes.json();
  PESOS_RANKING = config.pesos_ranking;
  FACTORES_TTI = config.factores_tti;

  renderPreguntas();

  document.getElementById("input-nombre-disc").addEventListener("input", actualizarProgreso);
  document.getElementById("btn-guardar-disc").addEventListener("click", guardarResultado);
  document.getElementById("btn-nuevo-test-disc").addEventListener("click", nuevoTest);

  document.getElementById("tab-nuevo").addEventListener("click", () => mostrarTab("nuevo"));
  document.getElementById("tab-historico").addEventListener("click", () => mostrarTab("historico"));

  document.getElementById("input-buscar-historico").addEventListener("input", (e) => {
    const q = e.target.value.trim().toLowerCase();
    renderHistorico(historicoCache.filter((it) => it.nombre.toLowerCase().includes(q)));
  });

  document.getElementById("btn-theme-toggle").addEventListener("click", () => {
    setTimeout(() => {
      recalcularPreview();
      if (ultimoResultado && !document.getElementById("disc-resultado-card").hidden) {
        renderRadar("chart-disc-resultado", ultimoResultado.perfil_adaptado, ultimoResultado.perfil_natural, (c) => { chartResultado = c; }, chartResultado);
      }
    }, 0);
  });
});

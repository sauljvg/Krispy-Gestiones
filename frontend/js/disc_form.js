const LETRAS_DISC = ["D", "I", "S", "C"];
const ICONO_FLECHA_ARRIBA = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="18 15 12 9 6 15"></polyline></svg>`;
const ICONO_FLECHA_ABAJO = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>`;
const POR_PAGINA_DISC = 4;

let PREGUNTAS_DISC = [];
let respondidas = new Set();
let paginaActualDisc = 0;
let totalPaginasDisc = 1;
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

function leerRespuestasActuales() {
  return [...document.querySelectorAll(".disc-opciones")]
    .sort((a, b) => Number(a.dataset.q) - Number(b.dataset.q))
    .map((ul) => [...ul.querySelectorAll("li")].map((li) => li.dataset.letra));
}

// ==================== Render preguntas, en paginas de 4 + reordenar (drag o flechas) ====================

function renderPreguntas() {
  totalPaginasDisc = Math.ceil(PREGUNTAS_DISC.length / POR_PAGINA_DISC);
  const wrap = document.getElementById("disc-preguntas-wrap");

  const paginasHtml = [];
  for (let pagina = 0; pagina < totalPaginasDisc; pagina++) {
    const inicio = pagina * POR_PAGINA_DISC;
    const preguntasPagina = PREGUNTAS_DISC.slice(inicio, inicio + POR_PAGINA_DISC);
    const bloques = preguntasPagina
      .map((p, offset) => {
        const i = inicio + offset;
        const opciones = shuffle(LETRAS_DISC.map((letra) => ({ letra, texto: p[letra] })));
        const lis = opciones
          .map(
            (o) => `
          <li draggable="true" data-letra="${o.letra}">
            <span class="disc-rank-badge"></span>
            <span class="disc-opcion-texto">${escapeHTML(o.texto)}</span>
            <span class="disc-opcion-flechas">
              <button type="button" class="btn-flecha-arriba" aria-label="Subir">${ICONO_FLECHA_ARRIBA}</button>
              <button type="button" class="btn-flecha-abajo" aria-label="Bajar">${ICONO_FLECHA_ABAJO}</button>
            </span>
          </li>`
          )
          .join("");
        return `
        <div class="disc-pregunta" id="disc-pregunta-${i}">
          <div class="disc-pregunta-num">Pregunta ${i + 1} / ${PREGUNTAS_DISC.length}</div>
          <p class="disc-pregunta-hint">Ordena arrastrando o con las flechas: arriba = lo que más te describe, abajo = lo que menos.</p>
          <ul class="disc-opciones" data-q="${i}">${lis}</ul>
        </div>`;
      })
      .join("");
    paginasHtml.push(`<div class="disc-pagina" data-pagina="${pagina}"${pagina === 0 ? "" : " hidden"}>${bloques}</div>`);
  }
  wrap.innerHTML = paginasHtml.join("");

  wrap.querySelectorAll(".disc-opciones").forEach((ul) => {
    actualizarBadges(ul);
    habilitarDragDrop(ul);
    habilitarFlechas(ul);
    actualizarFlechasDisabled(ul);
  });
  respondidas = new Set();
  paginaActualDisc = 0;
  actualizarProgreso();
}

function habilitarDragDrop(ul) {
  ul.querySelectorAll("li").forEach((li) => {
    li.addEventListener("dragstart", () => {
      li.classList.add("dragging");
    });
    li.addEventListener("dragend", () => {
      li.classList.remove("dragging");
      actualizarBadges(ul);
      actualizarFlechasDisabled(ul);
      marcarRespondida(ul);
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

function habilitarFlechas(ul) {
  ul.querySelectorAll(".btn-flecha-arriba").forEach((btn) => {
    btn.addEventListener("click", () => moverOpcion(btn.closest("li"), -1, ul));
  });
  ul.querySelectorAll(".btn-flecha-abajo").forEach((btn) => {
    btn.addEventListener("click", () => moverOpcion(btn.closest("li"), 1, ul));
  });
}

function moverOpcion(li, direccion, ul) {
  const hermano = direccion === -1 ? li.previousElementSibling : li.nextElementSibling;
  if (!hermano) return;
  if (direccion === -1) ul.insertBefore(li, hermano);
  else ul.insertBefore(hermano, li);
  actualizarBadges(ul);
  actualizarFlechasDisabled(ul);
  marcarRespondida(ul);
}

function actualizarBadges(ul) {
  ul.querySelectorAll("li").forEach((li, i) => {
    li.querySelector(".disc-rank-badge").textContent = i + 1;
  });
}

function actualizarFlechasDisabled(ul) {
  const lis = [...ul.querySelectorAll("li")];
  lis.forEach((li, i) => {
    li.querySelector(".btn-flecha-arriba").disabled = i === 0;
    li.querySelector(".btn-flecha-abajo").disabled = i === lis.length - 1;
  });
}

function marcarRespondida(ul) {
  const idx = Number(ul.dataset.q);
  respondidas.add(idx);
  document.getElementById(`disc-pregunta-${idx}`).classList.add("respondida");
  actualizarProgreso();
}

// ==================== Paginacion ====================

function paginaCompletaDisc(pagina) {
  const inicio = pagina * POR_PAGINA_DISC;
  for (let i = inicio; i < inicio + POR_PAGINA_DISC && i < PREGUNTAS_DISC.length; i++) {
    if (!respondidas.has(i)) return false;
  }
  return true;
}

function mostrarPaginaDisc(n) {
  document.querySelectorAll(".disc-pagina").forEach((div) => {
    div.hidden = Number(div.dataset.pagina) !== n;
  });
  paginaActualDisc = n;
  actualizarProgreso();
  document.getElementById("detalle-manual").scrollIntoView({ behavior: "smooth", block: "start" });
}

function actualizarProgreso() {
  document.getElementById("disc-progreso-txt").textContent =
    `Página ${paginaActualDisc + 1} de ${totalPaginasDisc} · ${respondidas.size} / ${PREGUNTAS_DISC.length} respondidas`;
  document.getElementById("disc-progreso-fill").style.width =
    `${(respondidas.size / (PREGUNTAS_DISC.length || 1)) * 100}%`;

  document.getElementById("btn-atras-disc").disabled = paginaActualDisc === 0;

  const esUltima = paginaActualDisc === totalPaginasDisc - 1;
  const btnSiguiente = document.getElementById("btn-siguiente-disc");
  const btnGuardar = document.getElementById("btn-guardar-disc");
  btnSiguiente.hidden = esUltima;
  btnGuardar.hidden = !esUltima;

  if (!esUltima) {
    btnSiguiente.disabled = !paginaCompletaDisc(paginaActualDisc);
  } else {
    const nombreOk = document.getElementById("input-nombre-disc").value.trim().length > 0;
    btnGuardar.disabled = !(nombreOk && respondidas.size === PREGUNTAS_DISC.length);
  }
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

function renderInformePerfil(perfilInfo) {
  const wrap = document.getElementById("disc-informe-perfil");
  if (!perfilInfo) {
    wrap.innerHTML = "";
    return;
  }
  const lista = (items) => `<ul>${items.map((it) => `<li>${escapeHTML(it)}</li>`).join("")}</ul>`;
  wrap.innerHTML = `
    <h3>${escapeHTML(perfilInfo.nombre)}</h3>
    <p class="disc-informe-resumen">${escapeHTML(perfilInfo.resumen)}</p>
    <h4>Características generales</h4>
    ${lista(perfilInfo.caracteristicas)}
    <h4>Fortalezas</h4>
    ${lista(perfilInfo.fortalezas)}
    <h4>Posibles áreas de mejora</h4>
    ${lista(perfilInfo.areas_de_mejora)}
    <h4>Qué le motiva</h4>
    ${lista(perfilInfo.motivadores)}
    <h4>Bajo presión</h4>
    <p>${escapeHTML(perfilInfo.bajo_presion)}</p>
    <h4>Cómo comunicarse con esta persona</h4>
    ${lista(perfilInfo.como_comunicarse)}
    <h4>Entorno ideal</h4>
    <p>${escapeHTML(perfilInfo.entorno_ideal)}</p>
    <p class="disc-informe-nota">Contenido descriptivo propio, no es el informe oficial de TTI Success Insights.</p>
  `;
}

function mostrarResultado(data) {
  ultimoResultado = data;
  document.getElementById("disc-resultado-card").hidden = false;
  document.getElementById("disc-resultado-tipo").textContent = data.tipo_disc;
  renderInformePerfil(data.perfil_info);
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
  document.getElementById("disc-informe-perfil").innerHTML = "";
  ultimoResultado = null;
  renderPreguntas();
  document.getElementById("detalle-manual").scrollIntoView({ behavior: "smooth", block: "start" });
}

// ==================== Enlace publico + enlace corto ====================

async function cargarEnlaces() {
  document.getElementById("input-enlace-publico").value = `${window.location.origin}/disc_publico.html`;
  try {
    const res = await fetch(`${AUTH_API_BASE}/disc/ajustes`);
    if (res.ok) {
      const data = await res.json();
      document.getElementById("input-enlace-corto").value = data.enlace_corto || "";
    }
  } catch {
    // sin conexion: se deja vacio, no bloquea el resto de la pagina
  }
}

async function copiarAlPortapapeles(texto, btn) {
  const textoOriginal = btn.textContent;
  try {
    await navigator.clipboard.writeText(texto);
    btn.textContent = "✓ Copiado";
  } catch {
    prompt("Copia el enlace:", texto);
    return;
  }
  setTimeout(() => { btn.textContent = textoOriginal; }, 2000);
}

async function guardarEnlaceCorto() {
  const btn = document.getElementById("btn-guardar-enlace-corto");
  const valor = document.getElementById("input-enlace-corto").value.trim();
  const textoOriginal = btn.textContent;
  btn.disabled = true;
  const res = await fetch(`${AUTH_API_BASE}/disc/ajustes`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enlace_corto: valor }),
  });
  btn.disabled = false;
  btn.textContent = res.ok ? "✓ Guardado" : "Error";
  setTimeout(() => { btn.textContent = textoOriginal; }, 2000);
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

  await cargarEnlaces();

  const preguntasRes = await fetch(`${AUTH_API_BASE}/disc/preguntas`);
  PREGUNTAS_DISC = await preguntasRes.json();

  renderPreguntas();

  document.getElementById("input-nombre-disc").addEventListener("input", actualizarProgreso);
  document.getElementById("btn-guardar-disc").addEventListener("click", guardarResultado);
  document.getElementById("btn-nuevo-test-disc").addEventListener("click", nuevoTest);
  document.getElementById("btn-atras-disc").addEventListener("click", () => mostrarPaginaDisc(paginaActualDisc - 1));
  document.getElementById("btn-siguiente-disc").addEventListener("click", () => {
    if (paginaCompletaDisc(paginaActualDisc)) mostrarPaginaDisc(paginaActualDisc + 1);
  });

  document.getElementById("tab-nuevo").addEventListener("click", () => mostrarTab("nuevo"));
  document.getElementById("tab-historico").addEventListener("click", () => mostrarTab("historico"));

  document.getElementById("btn-copiar-enlace-publico").addEventListener("click", (e) => {
    copiarAlPortapapeles(document.getElementById("input-enlace-publico").value, e.currentTarget);
  });
  document.getElementById("btn-guardar-enlace-corto").addEventListener("click", guardarEnlaceCorto);

  document.getElementById("input-buscar-historico").addEventListener("input", (e) => {
    const q = e.target.value.trim().toLowerCase();
    renderHistorico(historicoCache.filter((it) => it.nombre.toLowerCase().includes(q)));
  });

  document.getElementById("btn-theme-toggle").addEventListener("click", () => {
    setTimeout(() => {
      if (ultimoResultado && !document.getElementById("disc-resultado-card").hidden) {
        renderRadar("chart-disc-resultado", ultimoResultado.perfil_adaptado, ultimoResultado.perfil_natural, (c) => { chartResultado = c; }, chartResultado);
      }
    }, 0);
  });
});

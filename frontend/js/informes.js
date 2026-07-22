let currentTipo = null;
let currentHoja = null;
let currentColumnas = [];
let selectedIds = new Set();
let usuariosParaCompartir = [];
let hiddenCols = new Set();
let lastData = null;

const LARGO_TEXTO_UMBRAL = 100; // por encima de esto, una columna se oculta por defecto la primera vez

function hiddenColsKey() {
  return `kt-informes-hidden-${currentTipo}-${currentHoja}`;
}

function aplicarPreferenciaColumnas(data) {
  const key = hiddenColsKey();
  const guardado = localStorage.getItem(key);
  if (guardado !== null) {
    hiddenCols = new Set(JSON.parse(guardado));
    return;
  }
  // Primera vez que se ve esta hoja: ocultar por defecto las columnas de
  // texto muy largo (p.ej. "ALERTA DETALLADA"), para que la tabla no se
  // estire. El usuario puede reactivarlas desde "Columnas" cuando quiera.
  const porDefecto = new Set();
  data.columnas.forEach((c) => {
    const valores = data.respuestas.map((r) => String(r.datos[c] ?? ""));
    const maximo = valores.reduce((acc, v) => Math.max(acc, v.length), 0);
    if (maximo > LARGO_TEXTO_UMBRAL) porDefecto.add(c);
  });
  hiddenCols = porDefecto;
  localStorage.setItem(key, JSON.stringify(Array.from(hiddenCols)));
}

function guardarPreferenciaColumnas() {
  localStorage.setItem(hiddenColsKey(), JSON.stringify(Array.from(hiddenCols)));
}

function renderColumnasPanel() {
  const list = document.getElementById("columnas-checklist");
  list.innerHTML = currentColumnas
    .map(
      (c, i) => `
      <div class="columna-check-row">
        <input type="checkbox" id="colchk-${i}" data-col="${escapeHTML(c)}" ${hiddenCols.has(c) ? "" : "checked"}>
        <label for="colchk-${i}">${escapeHTML(c)}</label>
      </div>`
    )
    .join("");
  list.querySelectorAll("input[type=checkbox]").forEach((cb) => {
    cb.addEventListener("change", () => {
      if (cb.checked) hiddenCols.delete(cb.dataset.col);
      else hiddenCols.add(cb.dataset.col);
      guardarPreferenciaColumnas();
      renderTable();
    });
  });
}

function escapeHTML(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

async function loadTipos() {
  const res = await fetch(`${AUTH_API_BASE}/informes/tipos`);
  const tipos = await res.json();
  const grid = document.getElementById("tipos-grid");
  grid.innerHTML = tipos
    .map(
      (t) => `
      <a href="#" class="home-card" data-clave="${t.clave}" data-nombre="${escapeHTML(t.nombre)}">
        <span class="home-icon">📋</span>
        <h2>${escapeHTML(t.nombre)}</h2>
        <p>${t.num_respuestas} respuesta(s) importada(s).</p>
      </a>`
    )
    .join("");
  grid.querySelectorAll(".home-card").forEach((card) => {
    card.addEventListener("click", (e) => {
      e.preventDefault();
      openTipo(card.dataset.clave, card.dataset.nombre);
    });
  });
}

function currentFiltros() {
  const params = new URLSearchParams();
  if (currentHoja) params.set("hoja", currentHoja);
  const q = document.getElementById("f-buscar").value.trim();
  if (q) params.set("q", q);
  const orden = document.getElementById("f-orden").value;
  if (orden) {
    params.set("orden", orden);
    params.set("orden_dir", document.getElementById("f-orden-dir").value);
  }
  const desde = document.getElementById("f-fecha-desde").value;
  const hasta = document.getElementById("f-fecha-hasta").value;
  const fechaCol = document.getElementById("f-fecha-wrap").dataset.col;
  if (fechaCol && (desde || hasta)) {
    params.set("fecha_col", fechaCol);
    if (desde) params.set("fecha_desde", desde);
    if (hasta) params.set("fecha_hasta", hasta);
  }
  params.set("page_size", "500");
  return params;
}

let todasLasHojas = [];

async function loadHojas() {
  const res = await fetch(`${AUTH_API_BASE}/informes/${currentTipo}/hojas`);
  todasLasHojas = await res.json();
  const visibles = todasLasHojas.filter((h) => !h.oculta);

  const gearBtn = document.getElementById("btn-hojas-gestionar");
  gearBtn.hidden = todasLasHojas.length <= 1;

  const wrap = document.getElementById("hoja-tabs");
  if (visibles.length === 0) {
    wrap.innerHTML = `<span class="staff-hint">No hay hojas visibles — revisa "⚙ Hojas".</span>`;
    currentHoja = null;
    renderHojasPanel();
    return;
  }
  if (!currentHoja || !visibles.some((h) => h.hoja === currentHoja)) {
    currentHoja = visibles[0].hoja;
  }
  wrap.innerHTML = visibles
    .map(
      (h) => `<button type="button" class="hoja-tab ${h.hoja === currentHoja ? "active" : ""}" data-hoja="${escapeHTML(h.hoja)}">${escapeHTML(h.hoja)} (${h.total})</button>`
    )
    .join("");
  wrap.querySelectorAll(".hoja-tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      currentHoja = btn.dataset.hoja;
      selectedIds.clear();
      renderHojasPanel();
      loadRespuestas();
    });
  });
  renderHojasPanel();
}

function renderHojasPanel() {
  const list = document.getElementById("hojas-checklist");
  list.innerHTML = todasLasHojas
    .map(
      (h) => `
      <div class="columna-check-row" style="flex-direction:column; align-items:flex-start; gap:2px; border-bottom:1px solid var(--border); padding-bottom:6px; margin-bottom:6px;">
        <div style="display:flex; align-items:center; gap:8px; width:100%;">
          <input type="checkbox" id="hojachk-${escapeHTML(h.hoja)}" data-hoja="${escapeHTML(h.hoja)}" ${h.oculta ? "" : "checked"}>
          <label for="hojachk-${escapeHTML(h.hoja)}" style="flex:1;">${escapeHTML(h.hoja)} (${h.total})</label>
          <button type="button" class="btn-eliminar-hoja" data-hoja="${escapeHTML(h.hoja)}" title="Eliminar esta hoja (no es un dato real)" style="background:none; border:none; color:var(--status-critical); cursor:pointer; font-size:13px;">🗑</button>
        </div>
        <label style="font-size:11px; color:var(--text-secondary); display:flex; align-items:center; gap:5px; padding-left:22px;">
          <input type="radio" name="hoja-principal" data-hoja="${escapeHTML(h.hoja)}" ${h.principal ? "checked" : ""}>
          Usar esta hoja para el total (evita contar dos veces a las mismas personas)
        </label>
      </div>`
    )
    .join("");
  list.querySelectorAll("input[type=checkbox]").forEach((cb) => {
    cb.addEventListener("change", async () => {
      await fetch(`${AUTH_API_BASE}/informes/${currentTipo}/hojas/ocultar`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ hoja: cb.dataset.hoja, oculta: !cb.checked }),
      });
      await loadHojas();
      await loadRespuestas();
      await loadTipos();
    });
  });
  list.querySelectorAll("input[name=hoja-principal]").forEach((radio) => {
    radio.addEventListener("change", async () => {
      await fetch(`${AUTH_API_BASE}/informes/${currentTipo}/hojas/principal`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ hoja: radio.dataset.hoja }),
      });
      await loadHojas();
      await loadTipos();
    });
  });
  list.querySelectorAll(".btn-eliminar-hoja").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm(`¿Eliminar por completo la hoja "${btn.dataset.hoja}"? Esto borra sus datos, no es reversible.`)) return;
      await fetch(`${AUTH_API_BASE}/informes/${currentTipo}/hojas/eliminar`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ hoja: btn.dataset.hoja }),
      });
      await loadHojas();
      await loadRespuestas();
      await loadTipos();
    });
  });
}

function renderCompartirBar() {
  const bar = document.getElementById("compartir-bar");
  const count = document.getElementById("compartir-count");
  if (selectedIds.size > 0) {
    bar.classList.add("visible");
    count.textContent = `${selectedIds.size} seleccionado(s)`;
  } else {
    bar.classList.remove("visible");
  }
}

async function loadRespuestas() {
  const params = currentFiltros();
  const res = await fetch(`${AUTH_API_BASE}/informes/${currentTipo}/respuestas?${params.toString()}`);
  const data = await res.json();
  currentHoja = data.hoja;
  currentColumnas = data.columnas;
  lastData = data;

  document.getElementById("tipo-detail-hint").textContent = `${data.total} respuesta(s) en total.`;

  const ordenSelect = document.getElementById("f-orden");
  const ordenActual = ordenSelect.value;
  ordenSelect.innerHTML =
    `<option value="">Más recientes primero</option>` +
    data.columnas.map((c) => `<option value="${escapeHTML(c)}">${escapeHTML(c)}</option>`).join("");
  ordenSelect.value = ordenActual;

  const fechaWrap = document.getElementById("f-fecha-wrap");
  const fechaHastaWrap = document.getElementById("f-fecha-hasta-wrap");
  if (data.columnas_fecha.length > 0) {
    fechaWrap.hidden = false;
    fechaHastaWrap.hidden = false;
    fechaWrap.dataset.col = data.columnas_fecha[0];
  } else {
    fechaWrap.hidden = true;
    fechaHastaWrap.hidden = true;
    fechaWrap.dataset.col = "";
  }

  aplicarPreferenciaColumnas(data);
  renderColumnasPanel();
  renderTable();
}

function renderTable() {
  const data = lastData;
  if (!data) return;
  const columnasVisibles = data.columnas.filter((c) => !hiddenCols.has(c));

  const thead = document.getElementById("tipo-detail-thead");
  thead.innerHTML =
    `<th><input type="checkbox" id="check-all"></th>` +
    columnasVisibles.map((c) => `<th>${escapeHTML(c)}</th>`).join("") +
    `<th>CV</th>`;

  const tbody = document.getElementById("tipo-detail-tbody");
  if (data.respuestas.length === 0) {
    tbody.innerHTML = `<tr><td colspan="${columnasVisibles.length + 2}">Todavía no hay respuestas importadas. Usa "Importar Excel" arriba.</td></tr>`;
  } else {
    tbody.innerHTML = data.respuestas
      .map((r) => {
        const checked = selectedIds.has(r.id) ? "checked" : "";
        const cvBtn = r.tiene_cv
          ? `<a href="${AUTH_API_BASE}/informes/respuestas/${r.id}/cv" target="_blank" class="btn btn-ghost btn-cv">📄 Ver</a>`
          : "";
        return `<tr data-id="${r.id}">
          <td><input type="checkbox" class="row-check" data-id="${r.id}" ${checked}></td>
          ${columnasVisibles.map((c) => {
            const valor = r.datos[c] ?? "";
            return `<td title="${escapeHTML(valor)}">${escapeHTML(valor)}</td>`;
          }).join("")}
          <td>
            ${cvBtn}
            <label class="btn btn-ghost btn-cv btn-upload">⬆
              <input type="file" class="input-cv-upload" data-id="${r.id}" accept=".pdf,.doc,.docx" hidden>
            </label>
          </td>
        </tr>`;
      })
      .join("");
  }

  document.getElementById("check-all")?.addEventListener("change", (e) => {
    tbody.querySelectorAll(".row-check").forEach((cb) => {
      cb.checked = e.target.checked;
      const id = Number(cb.dataset.id);
      if (e.target.checked) selectedIds.add(id);
      else selectedIds.delete(id);
    });
    renderCompartirBar();
  });

  tbody.querySelectorAll(".row-check").forEach((cb) => {
    cb.addEventListener("change", () => {
      const id = Number(cb.dataset.id);
      if (cb.checked) selectedIds.add(id);
      else selectedIds.delete(id);
      renderCompartirBar();
    });
  });

  tbody.querySelectorAll(".input-cv-upload").forEach((input) => {
    input.addEventListener("change", async (e) => {
      const file = e.target.files[0];
      if (!file) return;
      const id = input.dataset.id;
      const formData = new FormData();
      formData.append("file", file);
      const res = await fetch(`${AUTH_API_BASE}/informes/respuestas/${id}/cv`, { method: "POST", body: formData });
      e.target.value = "";
      if (!res.ok) {
        alert("No se pudo subir el CV.");
        return;
      }
      loadRespuestas();
    });
  });

  renderCompartirBar();
}

async function openTipo(clave, nombre) {
  currentTipo = clave;
  currentHoja = null;
  selectedIds.clear();
  document.getElementById("tipo-detail").hidden = false;
  document.getElementById("tipo-detail-title").textContent = nombre;
  await loadHojas();
  await loadRespuestas();
  document.getElementById("tipo-detail").scrollIntoView({ behavior: "smooth" });
}

async function abrirModalCompartir() {
  if (selectedIds.size === 0) return;
  if (usuariosParaCompartir.length === 0) {
    const res = await fetch(`${AUTH_API_BASE}/informes/usuarios-para-compartir`);
    usuariosParaCompartir = await res.json();
  }
  const select = document.getElementById("compartir-usuario-select");
  select.innerHTML = usuariosParaCompartir
    .map((u) => `<option value="${u.id}">${escapeHTML(u.nombre)} (${escapeHTML(u.username)} · ${escapeHTML(u.rol)})</option>`)
    .join("");
  document.getElementById("compartir-modal").classList.add("visible");
}

function cerrarModalCompartir() {
  document.getElementById("compartir-modal").classList.remove("visible");
}

document.addEventListener("DOMContentLoaded", async () => {
  const user = await checkAuth("/informes.html");
  if (!user) return;
  if (!esRolTodo(user.rol)) {
    window.location.href = "/";
    return;
  }
  wireUserBar(user);

  await loadTipos();

  document.getElementById("input-informe-upload").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file || !currentTipo) return;
    const formData = new FormData();
    formData.append("file", file);
    const res = await fetch(`${AUTH_API_BASE}/informes/${currentTipo}/importar`, { method: "POST", body: formData });
    e.target.value = "";
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      alert(err.detail || "Fallo al importar el Excel.");
      return;
    }
    const result = await res.json();
    const detalle = Object.entries(result.hojas)
      .map(([hoja, r]) => `${hoja}: ${r.nuevas} nueva(s), ${r.ya_existian} ya existían (de ${r.total_en_excel})`)
      .join("\n");
    alert(`Importación completa:\n${detalle}`);
    await loadTipos();
    await loadHojas();
    await loadRespuestas();
  });

  document.getElementById("btn-new-tipo").addEventListener("click", async () => {
    const nombre = prompt("Nombre del nuevo tipo de informe (ej. 'Encuesta de Onboarding'):");
    if (!nombre || !nombre.trim()) return;
    const clave = nombre
      .trim()
      .toLowerCase()
      .normalize("NFD")
      .replace(/[̀-ͯ]/g, "")
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "");
    const res = await fetch(`${AUTH_API_BASE}/informes/tipos`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ clave, nombre: nombre.trim() }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      alert(err.detail || "No se pudo crear el tipo.");
      return;
    }
    await loadTipos();
  });

  ["f-buscar"].forEach((id) => {
    document.getElementById(id).addEventListener("input", () => loadRespuestas());
  });
  ["f-orden", "f-orden-dir", "f-fecha-desde", "f-fecha-hasta"].forEach((id) => {
    document.getElementById(id).addEventListener("change", () => loadRespuestas());
  });

  document.getElementById("btn-limpiar-filtros").addEventListener("click", () => {
    document.getElementById("f-buscar").value = "";
    document.getElementById("f-orden").value = "";
    document.getElementById("f-orden-dir").value = "asc";
    document.getElementById("f-fecha-desde").value = "";
    document.getElementById("f-fecha-hasta").value = "";
    loadRespuestas();
  });

  document.getElementById("btn-limpiar-seleccion").addEventListener("click", () => {
    selectedIds.clear();
    loadRespuestas();
  });

  document.getElementById("btn-columnas").addEventListener("click", (e) => {
    e.stopPropagation();
    document.getElementById("columnas-panel").classList.toggle("visible");
  });
  document.getElementById("btn-columnas-cerrar").addEventListener("click", () => {
    document.getElementById("columnas-panel").classList.remove("visible");
  });
  document.getElementById("btn-columnas-todas").addEventListener("click", () => {
    hiddenCols.clear();
    guardarPreferenciaColumnas();
    renderColumnasPanel();
    renderTable();
  });
  document.getElementById("btn-hojas-gestionar").addEventListener("click", (e) => {
    e.stopPropagation();
    document.getElementById("hojas-panel").classList.toggle("visible");
  });
  document.getElementById("btn-hojas-cerrar").addEventListener("click", () => {
    document.getElementById("hojas-panel").classList.remove("visible");
  });

  document.addEventListener("click", (e) => {
    const panel = document.getElementById("columnas-panel");
    if (panel.classList.contains("visible") && !panel.contains(e.target) && e.target.id !== "btn-columnas") {
      panel.classList.remove("visible");
    }
    const hojasPanel = document.getElementById("hojas-panel");
    if (hojasPanel.classList.contains("visible") && !hojasPanel.contains(e.target) && e.target.id !== "btn-hojas-gestionar") {
      hojasPanel.classList.remove("visible");
    }
  });

  document.getElementById("btn-compartir").addEventListener("click", abrirModalCompartir);
  document.getElementById("btn-compartir-cancelar").addEventListener("click", cerrarModalCompartir);
  document.getElementById("btn-compartir-confirmar").addEventListener("click", async () => {
    const usuarioId = Number(document.getElementById("compartir-usuario-select").value);
    const res = await fetch(`${AUTH_API_BASE}/informes/compartir`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ respuesta_ids: Array.from(selectedIds), usuario_id: usuarioId }),
    });
    if (!res.ok) {
      alert("No se pudo compartir.");
      return;
    }
    cerrarModalCompartir();
    alert(`Compartido con éxito (${selectedIds.size} candidato(s)).`);
    selectedIds.clear();
    loadRespuestas();
  });
});

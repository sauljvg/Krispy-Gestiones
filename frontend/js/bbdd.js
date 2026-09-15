// BBDD: vista única de TODOS los candidatos de Reclutamiento (KK + Saona),
// sin importar estado ni vacante, con gestión de etiquetas -- ver
// backend/bbdd.py y backend/bbdd_routes.py. Reutiliza los endpoints de
// Reclutamiento para leer/editar la ficha (misma tabla candidatos) y añade
// los propios de BBDD solo para lo que Reclutamiento no tenía: listar sin
// filtrar por vacante, y las etiquetas.

const EMPRESAS_BBDD = ["kk", "saona"];
const ESTADO_LABEL = { pendiente: "Pendiente", entrevistado: "Entrevistado", contratado: "Contratado", descartado: "Descartado" };

let etiquetasCache = [];
let carrerasIE = [];
let candidatosCache = [];
let etiquetaFiltroActiva = null;
let candidatoAbiertoId = null;

function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

async function cargarEtiquetas() {
  const res = await fetch(`${AUTH_API_BASE}/bbdd/etiquetas`);
  etiquetasCache = res.ok ? await res.json() : [];
  renderEtiquetasBar();
}

function renderEtiquetasBar() {
  const wrap = document.getElementById("bbdd-etiquetas-bar");
  const todas = `<button type="button" class="pill-ghost${etiquetaFiltroActiva === null ? " activa" : ""}" data-etiqueta="">Todas</button>`;
  const resto = etiquetasCache.map((e) => `
    <button type="button" class="pill-ghost${etiquetaFiltroActiva === e.id ? " activa" : ""}" data-etiqueta="${e.id}"
      style="${etiquetaFiltroActiva === e.id ? `border-color:${e.color}; color:${e.color}; background:color-mix(in srgb, ${e.color} 14%, transparent);` : ""}">
      ${escapeHTML(e.nombre)} <span class="staff-hint" style="margin:0;">(${e.candidatos_count})</span>
    </button>
  `).join("");
  wrap.innerHTML = todas + resto;
  wrap.querySelectorAll("[data-etiqueta]").forEach((btn) => {
    btn.addEventListener("click", () => {
      etiquetaFiltroActiva = btn.dataset.etiqueta ? Number(btn.dataset.etiqueta) : null;
      renderEtiquetasBar();
      cargarCandidatos();
    });
  });
}

function poblarFiltroCarreras() {
  const select = document.getElementById("bbdd-filtro-carrera");
  const enUso = new Set(candidatosCache.map((c) => c.carrera).filter(Boolean));
  const todas = Array.from(new Set([...carrerasIE, ...enUso])).sort((a, b) => a.localeCompare(b, "es"));
  const actual = select.value;
  select.innerHTML = '<option value="">Todas las carreras</option>' + todas.map((c) => `<option value="${escapeHTML(c)}">${escapeHTML(c)}</option>`).join("");
  select.value = actual;
}

function filtrosActuales() {
  return {
    q: document.getElementById("bbdd-buscar").value.trim(),
    estado: document.getElementById("bbdd-filtro-estado").value,
    carrera: document.getElementById("bbdd-filtro-carrera").value,
    edad_min: document.getElementById("bbdd-edad-min").value,
    edad_max: document.getElementById("bbdd-edad-max").value,
    etiqueta_id: etiquetaFiltroActiva || "",
  };
}

async function cargarCandidatos() {
  const filtros = filtrosActuales();
  const params = new URLSearchParams();
  Object.entries(filtros).forEach(([k, v]) => { if (v) params.set(k, v); });

  const resultados = await Promise.all(EMPRESAS_BBDD.map(async (empresa) => {
    const p = new URLSearchParams(params);
    p.set("empresa", empresa);
    try {
      const res = await fetch(`${AUTH_API_BASE}/bbdd/candidatos?${p.toString()}`);
      if (!res.ok) return [];
      const lista = await res.json();
      lista.forEach((c) => { c._empresa = empresa; });
      return lista;
    } catch {
      return [];
    }
  }));

  candidatosCache = resultados.flat().sort((a, b) => (b.actualizado_en || "").localeCompare(a.actualizado_en || ""));
  poblarFiltroCarreras();
  renderLista();
}

function badgeEstadoHTML(estado) {
  return `<span class="badge-estado badge-${estado}">${ESTADO_LABEL[estado] || estado}</span>`;
}

function etiquetasPillsHTML(candidato) {
  return (candidato.etiquetas || []).map((e) => `
    <span class="pill" style="background:${e.color}">${escapeHTML(e.nombre)}</span>
  `).join("");
}

function renderLista() {
  const contador = document.getElementById("bbdd-contador");
  contador.textContent = `${candidatosCache.length} candidato${candidatosCache.length === 1 ? "" : "s"}`;
  const lista = document.getElementById("bbdd-lista");
  if (candidatosCache.length === 0) {
    lista.innerHTML = '<p class="staff-hint">No hay candidatos que coincidan con estos filtros.</p>';
    return;
  }
  lista.innerHTML = candidatosCache.map((c) => `
    <div class="bbdd-card${candidatoAbiertoId === c.id ? " abierta" : ""}" data-id="${c.id}" data-empresa="${c._empresa}">
      <div class="bbdd-card-top">
        <span class="badge-empresa badge-empresa-${c._empresa}">${c._empresa === "kk" ? "KK" : "SAONA"}</span>
        <h4>${escapeHTML(c.nombre_completo || "(sin nombre)")}</h4>
        ${badgeEstadoHTML(c.estado)}
        ${c.edad != null ? `<span class="staff-hint" style="margin:0;">${c.edad} años</span>` : ""}
      </div>
      <p class="bbdd-card-meta">
        ${c.telefono ? `<span>📞 ${escapeHTML(c.telefono)}</span>` : ""}
        ${c.email ? `<span>✉️ ${escapeHTML(c.email)}</span>` : ""}
        ${c.carrera ? `<span>🎓 ${escapeHTML(c.carrera)}</span>` : ""}
      </p>
      <div class="bbdd-card-etiquetas">${etiquetasPillsHTML(c)}</div>
    </div>
  `).join("");
  lista.querySelectorAll(".bbdd-card").forEach((card) => {
    card.addEventListener("click", () => {
      const id = Number(card.dataset.id);
      const empresa = card.dataset.empresa;
      if (candidatoAbiertoId === id) {
        candidatoAbiertoId = null;
        document.getElementById("bbdd-ficha-wrap").innerHTML = "";
      } else {
        candidatoAbiertoId = id;
        abrirFicha(id, empresa);
      }
      renderLista();
    });
  });
}

function candidatoPorId(id) {
  return candidatosCache.find((c) => c.id === id);
}

async function abrirFicha(id, empresa) {
  const c = candidatoPorId(id);
  const wrap = document.getElementById("bbdd-ficha-wrap");
  const idsAsignados = new Set((c.etiquetas || []).map((e) => e.id));
  const etiquetasDisponibles = etiquetasCache.filter((e) => !idsAsignados.has(e.id));
  wrap.innerHTML = `
    <div class="bbdd-ficha">
      <h3>${escapeHTML(c.nombre_completo || "(sin nombre)")}</h3>
      <div class="bbdd-ficha-etiquetas" id="ficha-etiquetas">
        ${(c.etiquetas || []).map((e) => `
          <span class="pill" style="background:${e.color}">${escapeHTML(e.nombre)} <span class="pill-x" data-quitar-etiqueta="${e.id}">✕</span></span>
        `).join("")}
        ${etiquetasDisponibles.length > 0 ? `
          <select class="bbdd-select-etiqueta" id="ficha-agregar-etiqueta">
            <option value="">+ añadir etiqueta...</option>
            ${etiquetasDisponibles.map((e) => `<option value="${e.id}">${escapeHTML(e.nombre)}</option>`).join("")}
          </select>
        ` : ""}
      </div>
      <div class="form-grid">
        <div class="form-field"><label>Nombre completo</label><input type="text" id="f-nombre" value="${escapeHTML(c.nombre_completo || "")}"></div>
        <div class="form-field"><label>Teléfono</label><input type="text" id="f-telefono" value="${escapeHTML(c.telefono || "")}"></div>
        <div class="form-field"><label>Email</label><input type="text" id="f-email" value="${escapeHTML(c.email || "")}"></div>
        <div class="form-field"><label>Fecha de nacimiento</label><input type="date" id="f-fecha-nacimiento" value="${c.fecha_nacimiento ? c.fecha_nacimiento.slice(0, 10) : ""}"></div>
        <div class="form-field">
          <label>Estado</label>
          <select id="f-estado">
            ${Object.entries(ESTADO_LABEL).map(([v, label]) => `<option value="${v}"${c.estado === v ? " selected" : ""}>${label}</option>`).join("")}
          </select>
        </div>
        <div class="form-field">
          <label>Carrera</label>
          <input type="text" id="f-carrera" list="lista-carreras-ie" value="${escapeHTML(c.carrera || "")}">
        </div>
        <div class="form-field"><label>Idiomas</label><input type="text" id="f-idiomas" value="${escapeHTML(c.idiomas || "")}"></div>
        <div class="form-field"><label>Nacionalidad</label><input type="text" id="f-nacionalidad" value="${escapeHTML(c.nacionalidad || "")}"></div>
        <div class="form-field"><label>Disponibilidad geográfica</label><input type="text" id="f-disponibilidad" value="${escapeHTML(c.disponibilidad || "")}"></div>
        <div class="form-field form-field-full"><label>Notas</label><textarea id="f-notas" rows="2">${escapeHTML(c.notas || "")}</textarea></div>
      </div>
      <div class="form-actions">
        <button type="button" class="btn btn-primary" id="btn-guardar-ficha">Guardar</button>
        <button type="button" class="btn btn-ghost" id="btn-cerrar-ficha">Cerrar</button>
      </div>
    </div>
    <datalist id="lista-carreras-ie">${carrerasIE.map((cr) => `<option value="${escapeHTML(cr)}">`).join("")}</datalist>
  `;

  wrap.querySelectorAll("[data-quitar-etiqueta]").forEach((btn) => {
    btn.addEventListener("click", async (ev) => {
      ev.stopPropagation();
      await fetch(`${AUTH_API_BASE}/bbdd/candidatos/${id}/etiquetas/${btn.dataset.quitarEtiqueta}`, { method: "DELETE" });
      await Promise.all([cargarEtiquetas(), cargarCandidatos()]);
      abrirFicha(id, empresa);
    });
  });
  const selectAgregar = document.getElementById("ficha-agregar-etiqueta");
  if (selectAgregar) {
    selectAgregar.addEventListener("change", async () => {
      if (!selectAgregar.value) return;
      await fetch(`${AUTH_API_BASE}/bbdd/candidatos/${id}/etiquetas/${selectAgregar.value}`, { method: "POST" });
      await Promise.all([cargarEtiquetas(), cargarCandidatos()]);
      abrirFicha(id, empresa);
    });
  }

  document.getElementById("btn-cerrar-ficha").addEventListener("click", () => {
    candidatoAbiertoId = null;
    wrap.innerHTML = "";
    renderLista();
  });

  document.getElementById("btn-guardar-ficha").addEventListener("click", async () => {
    const body = {
      nombre_completo: document.getElementById("f-nombre").value.trim() || null,
      telefono: document.getElementById("f-telefono").value.trim() || null,
      email: document.getElementById("f-email").value.trim() || null,
      fecha_nacimiento: document.getElementById("f-fecha-nacimiento").value || null,
      estado: document.getElementById("f-estado").value,
      carrera: document.getElementById("f-carrera").value.trim() || null,
      idiomas: document.getElementById("f-idiomas").value.trim() || null,
      nacionalidad: document.getElementById("f-nacionalidad").value.trim() || null,
      disponibilidad: document.getElementById("f-disponibilidad").value.trim() || null,
      notas: document.getElementById("f-notas").value.trim() || null,
    };
    const res = await fetch(`${AUTH_API_BASE}/reclutamiento/candidatos/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      await mostrarAviso("No se pudo guardar la ficha.");
      return;
    }
    await cargarCandidatos();
  });
}

function wireModalNuevaEtiqueta() {
  const overlay = document.getElementById("nueva-etiqueta-modal");
  document.getElementById("btn-nueva-etiqueta").addEventListener("click", () => {
    document.getElementById("nueva-etiqueta-nombre").value = "";
    document.getElementById("nueva-etiqueta-color").value = "#6b7280";
    overlay.classList.add("visible");
  });
  document.getElementById("btn-nueva-etiqueta-cancelar").addEventListener("click", () => overlay.classList.remove("visible"));
  document.getElementById("btn-nueva-etiqueta-confirmar").addEventListener("click", async () => {
    const nombre = document.getElementById("nueva-etiqueta-nombre").value.trim();
    if (!nombre) return;
    const color = document.getElementById("nueva-etiqueta-color").value;
    const res = await fetch(`${AUTH_API_BASE}/bbdd/etiquetas`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nombre, color }),
    });
    if (!res.ok) {
      await mostrarAviso("No se pudo crear la etiqueta.");
      return;
    }
    overlay.classList.remove("visible");
    await cargarEtiquetas();
  });
}

document.addEventListener("DOMContentLoaded", async () => {
  const user = await checkAuth("/");
  if (!user) return;
  wireUserBar(user);

  const enlaceIE = `${window.location.origin}/ie-formulario.html`;
  const linkEl = document.getElementById("link-formulario-ie");
  linkEl.href = enlaceIE;
  linkEl.textContent = enlaceIE;
  document.getElementById("btn-copiar-enlace-ie").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(enlaceIE);
      await mostrarAviso("Enlace copiado.");
    } catch {
      await mostrarAviso("No se pudo copiar el enlace -- cópialo a mano.");
    }
  });

  wireModalNuevaEtiqueta();

  const res = await fetch(`${AUTH_API_BASE}/bbdd/carreras-ie`);
  carrerasIE = res.ok ? await res.json() : [];

  document.getElementById("bbdd-buscar").addEventListener("input", debounce(cargarCandidatos, 300));
  document.getElementById("bbdd-filtro-estado").addEventListener("change", cargarCandidatos);
  document.getElementById("bbdd-filtro-carrera").addEventListener("change", cargarCandidatos);
  document.getElementById("bbdd-edad-min").addEventListener("input", debounce(cargarCandidatos, 400));
  document.getElementById("bbdd-edad-max").addEventListener("input", debounce(cargarCandidatos, 400));

  await cargarEtiquetas();
  await cargarCandidatos();
});

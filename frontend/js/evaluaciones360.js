const EMPRESA = new URLSearchParams(location.search).get("empresa") === "saona" ? "saona" : "kk";

let PERSONAS = [];
let PUESTOS = [];
let USUARIOS = [];
let editandoPersonaId = null;

function aplicarBrandingEmpresa() {
  if (EMPRESA !== "saona") return;
  document.title = document.title.replace("Krispy Gestiones", "SAONA Gestiones");
  const icon = document.getElementById("brand-icon");
  if (icon) icon.textContent = "🌿";
  const favicon = document.querySelector('link[rel="icon"]');
  if (favicon) favicon.href = "assets/favicon-saona.png";
  const title = document.getElementById("brand-title");
  if (title) title.textContent = "SAONA Gestiones";
}

function escapeHTML(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

async function cargarTodo() {
  const [personas, puestos, usuarios] = await Promise.all([
    fetch(`${AUTH_API_BASE}/evaluaciones360/personas?empresa=${EMPRESA}`).then((r) => r.json()),
    fetch(`${AUTH_API_BASE}/evaluaciones360/puestos?empresa=${EMPRESA}`).then((r) => r.json()),
    fetch(`${AUTH_API_BASE}/evaluaciones360/usuarios-seleccionables?empresa=${EMPRESA}`).then((r) => r.json()),
  ]);
  PERSONAS = personas;
  PUESTOS = puestos;
  USUARIOS = usuarios;
  renderOrganigrama();
}

function renderOrganigrama() {
  const ul = document.getElementById("organigrama-lista");
  if (PERSONAS.length === 0) {
    ul.innerHTML = `<p class="staff-hint">Todavía no hay nadie en el organigrama. Empieza por la persona de más arriba (sin jefe directo) y ve añadiendo debajo.</p>`;
    return;
  }
  const porJefe = new Map();
  for (const p of PERSONAS) {
    const clave = p.jefe_directo_id || "raiz";
    if (!porJefe.has(clave)) porJefe.set(clave, []);
    porJefe.get(clave).push(p);
  }
  const html = [];
  function pintar(clave, profundidad, vistos) {
    const hijos = porJefe.get(clave) || [];
    for (const persona of hijos) {
      if (vistos.has(persona.id)) continue; // corta ciclos si alguna edición manual creara uno
      html.push(filaPersona(persona, profundidad));
      pintar(persona.id, profundidad + 1, new Set(vistos).add(persona.id));
    }
  }
  pintar("raiz", 0, new Set());
  ul.innerHTML = html.join("");
  ul.querySelectorAll("[data-editar]").forEach((btn) => {
    btn.addEventListener("click", () => abrirEditor(Number(btn.dataset.editar)));
  });
}

function filaPersona(persona, profundidad) {
  const cuenta = persona.usuario_nombre
    ? `<span class="badge-cuenta">🔑 ${escapeHTML(persona.usuario_nombre)}</span>`
    : `<span class="badge-sin-cuenta">Sin cuenta vinculada</span>`;
  const puesto = persona.puesto_nombre ? `<span class="persona-puesto">${escapeHTML(persona.puesto_nombre)}</span>` : "";
  return `
    <li style="margin-left:${profundidad * 26}px;">
      <div class="persona-row">
        <span class="persona-nombre">${escapeHTML(persona.nombre_completo)}</span>
        ${puesto}
        ${cuenta}
        <div class="persona-acciones">
          <button type="button" class="btn btn-ghost btn-mini" data-editar="${persona.id}">Editar</button>
        </div>
      </div>
    </li>`;
}

function poblarSelects() {
  const selPuesto = document.getElementById("persona-puesto");
  selPuesto.innerHTML = `<option value="">— Sin puesto asignado —</option>` +
    PUESTOS.map((p) => `<option value="${p.id}">${escapeHTML(p.nombre)}</option>`).join("");

  const selJefe = document.getElementById("persona-jefe");
  const candidatos = PERSONAS.filter((p) => p.id !== editandoPersonaId);
  selJefe.innerHTML = `<option value="">— Sin jefe (raíz del organigrama) —</option>` +
    candidatos.map((p) => `<option value="${p.id}">${escapeHTML(p.nombre_completo)}</option>`).join("");

  const selUsuario = document.getElementById("persona-usuario");
  const usuariosVinculadosAOtros = new Set(
    PERSONAS.filter((p) => p.usuario_id && p.id !== editandoPersonaId).map((p) => p.usuario_id)
  );
  selUsuario.innerHTML = `<option value="">— Sin vincular —</option>` +
    USUARIOS.filter((u) => !usuariosVinculadosAOtros.has(u.id))
      .map((u) => `<option value="${u.id}">${escapeHTML(u.nombre)} (${escapeHTML(u.username)})</option>`)
      .join("");
}

function abrirEditor(personaId) {
  editandoPersonaId = personaId || null;
  poblarSelects();
  const persona = personaId ? PERSONAS.find((p) => p.id === personaId) : null;
  document.getElementById("editor-titulo-h2").textContent = persona ? "Editar persona" : "Nueva persona";
  document.getElementById("persona-nombre").value = persona ? persona.nombre_completo : "";
  document.getElementById("persona-puesto").value = persona?.puesto_id || "";
  document.getElementById("persona-jefe").value = persona?.jefe_directo_id || "";
  document.getElementById("persona-usuario").value = persona?.usuario_id || "";
  document.getElementById("btn-eliminar-persona").hidden = !persona;
  document.getElementById("editor-card").hidden = false;
  document.getElementById("lista-organigrama-wrap").hidden = true;
  document.getElementById("persona-nombre").focus();
}

function cerrarEditor() {
  document.getElementById("editor-card").hidden = true;
  document.getElementById("lista-organigrama-wrap").hidden = false;
  editandoPersonaId = null;
}

async function guardarPersona() {
  const nombre = document.getElementById("persona-nombre").value.trim();
  if (!nombre) {
    await mostrarAviso("Ponle un nombre a la persona.");
    return;
  }
  const body = {
    nombre_completo: nombre,
    puesto_id: document.getElementById("persona-puesto").value ? Number(document.getElementById("persona-puesto").value) : null,
    jefe_directo_id: document.getElementById("persona-jefe").value ? Number(document.getElementById("persona-jefe").value) : null,
    usuario_id: document.getElementById("persona-usuario").value ? Number(document.getElementById("persona-usuario").value) : null,
  };
  const url = editandoPersonaId
    ? `${AUTH_API_BASE}/evaluaciones360/personas/${editandoPersonaId}`
    : `${AUTH_API_BASE}/evaluaciones360/personas`;
  const res = await fetch(url, {
    method: editandoPersonaId ? "PATCH" : "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(editandoPersonaId ? body : { ...body, empresa: EMPRESA }),
  });
  if (!res.ok) {
    await mostrarAviso("No se pudo guardar. Inténtalo de nuevo.");
    return;
  }
  cerrarEditor();
  await cargarTodo();
}

async function eliminarPersona() {
  if (!editandoPersonaId) return;
  if (!(await pedirConfirmacion("¿Quitar a esta persona del organigrama? No se borran evaluaciones ya hechas, pero dejará de aparecer para nuevas campañas."))) return;
  const res = await fetch(`${AUTH_API_BASE}/evaluaciones360/personas/${editandoPersonaId}`, { method: "DELETE" });
  if (!res.ok) {
    await mostrarAviso("No se pudo eliminar.");
    return;
  }
  cerrarEditor();
  await cargarTodo();
}

async function nuevoPuesto() {
  const nombre = await pedirTexto("Nombre del nuevo puesto:");
  if (!nombre || !nombre.trim()) return;
  const res = await fetch(`${AUTH_API_BASE}/evaluaciones360/puestos`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ empresa: EMPRESA, nombre: nombre.trim() }),
  });
  if (!res.ok) {
    await mostrarAviso("No se pudo crear el puesto.");
    return;
  }
  const { id } = await res.json();
  // poblarSelects() reconstruye los 3 <select> desde cero -- hay que
  // conservar lo que ya se había elegido en jefe/usuario, o se pierde
  // silenciosamente cada vez que se crea un puesto nuevo desde el editor.
  const jefeActual = document.getElementById("persona-jefe").value;
  const usuarioActual = document.getElementById("persona-usuario").value;
  PUESTOS = await fetch(`${AUTH_API_BASE}/evaluaciones360/puestos?empresa=${EMPRESA}`).then((r) => r.json());
  poblarSelects();
  document.getElementById("persona-puesto").value = id;
  document.getElementById("persona-jefe").value = jefeActual;
  document.getElementById("persona-usuario").value = usuarioActual;
}

document.addEventListener("DOMContentLoaded", async () => {
  const user = await checkAuth("/evaluaciones360.html");
  if (!user) return;
  const moduloRequerido = EMPRESA === "saona" ? "saona_evaluaciones360" : "evaluaciones360";
  if (!(user.modulos || []).includes(moduloRequerido)) {
    window.location.href = "/";
    return;
  }
  wireUserBar(user);
  aplicarBrandingEmpresa();

  await cargarTodo();

  document.getElementById("btn-nueva-persona").addEventListener("click", () => abrirEditor(null));
  document.getElementById("btn-cerrar-editor").addEventListener("click", cerrarEditor);
  document.getElementById("btn-cerrar-editor-x").addEventListener("click", cerrarEditor);
  document.getElementById("btn-guardar-persona").addEventListener("click", guardarPersona);
  document.getElementById("btn-eliminar-persona").addEventListener("click", eliminarPersona);
  document.getElementById("btn-nuevo-puesto").addEventListener("click", nuevoPuesto);
});

const EMPRESA = new URLSearchParams(location.search).get("empresa") === "saona" ? "saona" : "kk";

let CURRENT_USER = null;
let PERSONAS = [];
let PUESTOS = [];
let USUARIOS = [];
let editandoPersonaId = null;

let PREGUNTAS = [];

let CAMPANAS = [];
let currentCampana = null;
let currentEvaluadoId = null;

let MIS_PENDIENTES = [];
let currentAsignacionId = null;
let currentFormulario = null;

const RELACION_LABEL = {
  autoevaluacion: "Autoevaluación",
  superior: "Superior",
  par: "Par",
  reporte: "Reporte",
  manual: "Añadido a mano",
};

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

// ---------------------------------------------------------------------------
// Pestañas
// ---------------------------------------------------------------------------

async function activarTab(nombre) {
  document.querySelectorAll(".eval360-tab-btn").forEach((b) => b.classList.toggle("activa", b.dataset.tab === nombre));
  document.querySelectorAll(".eval360-vista").forEach((v) => v.classList.toggle("activa", v.id === `vista-${nombre}`));
  if (nombre === "organigrama" && PERSONAS.length === 0) await cargarOrganigrama();
  if (nombre === "preguntas" && PREGUNTAS.length === 0) await cargarPreguntas();
  if (nombre === "campanas" && CAMPANAS.length === 0) await cargarCampanas();
  if (nombre === "mis") await cargarMisPendientes();
}

// ---------------------------------------------------------------------------
// Organigrama
// ---------------------------------------------------------------------------

async function cargarOrganigrama() {
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

// Claves de colapso ("por persona") -- desplegable tipo Bizneo: cada persona
// con reportes puede colapsar su propia rama, para poder centrarse en una
// parte del organigrama sin que estorbe el resto.
const personasColapsadas = new Set();

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
  function nodoHTML(clave, vistos) {
    const hijos = porJefe.get(clave) || [];
    return hijos
      .filter((persona) => !vistos.has(persona.id))
      .map((persona) => {
        const vistosHijo = new Set(vistos).add(persona.id);
        const hijosHTML = nodoHTML(persona.id, vistosHijo);
        return filaPersona(persona, hijosHTML);
      })
      .join("");
  }
  ul.innerHTML = nodoHTML("raiz", new Set());
  ul.querySelectorAll("[data-editar]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      abrirEditorPersona(Number(btn.dataset.editar));
    });
  });
  ul.querySelectorAll("[data-toggle-persona]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const id = Number(btn.dataset.togglePersona);
      if (personasColapsadas.has(id)) personasColapsadas.delete(id);
      else personasColapsadas.add(id);
      renderOrganigrama();
    });
  });
  wirePersonaRows(ul);
}

function filaPersona(persona, hijosHTML) {
  const cuenta = persona.usuario_nombre
    ? `<span class="badge-cuenta">🔑 ${escapeHTML(persona.usuario_nombre)}</span>`
    : `<span class="badge-sin-cuenta">Sin cuenta vinculada</span>`;
  const puesto = persona.puestos?.length
    ? `<span class="persona-puesto">${persona.puestos.map((p) => escapeHTML(p.nombre)).join(", ")}</span>`
    : "";
  const colapsado = personasColapsadas.has(persona.id);
  const toggle = hijosHTML
    ? `<button type="button" class="persona-toggle" data-toggle-persona="${persona.id}" title="${colapsado ? "Expandir" : "Colapsar"}">${colapsado ? "▸" : "▾"}</button>`
    : `<span class="persona-toggle-spacer"></span>`;
  const hijosVisibles = hijosHTML && !colapsado ? `<ul class="persona-tree-children">${hijosHTML}</ul>` : "";
  return `
    <li class="persona-tree-node">
      <div class="persona-row" draggable="true" data-persona-id="${persona.id}">
        ${toggle}
        <span class="persona-nombre">${escapeHTML(persona.nombre_completo)}</span>
        ${puesto}
        ${cuenta}
        <div class="persona-acciones">
          <button type="button" class="btn btn-ghost btn-mini" data-editar="${persona.id}">Editar</button>
        </div>
      </div>
      ${hijosVisibles}
    </li>`;
}

// ---------------------------------------------------------------------------
// Arrastrar y soltar personas para cambiar su jefe directo
// ---------------------------------------------------------------------------

let personaArrastradaId = null;

function esReparentadoValidoPersona(arrastradaId, destinoId) {
  if (arrastradaId === destinoId) return false;
  // Igual que con los puestos: el destino no puede ser un reporte (directo
  // o indirecto) de la persona que se arrastra, o se crearía un ciclo.
  let cursor = PERSONAS.find((p) => p.id === destinoId);
  while (cursor && cursor.jefe_directo_id) {
    if (cursor.jefe_directo_id === arrastradaId) return false;
    cursor = PERSONAS.find((p) => p.id === cursor.jefe_directo_id);
  }
  return true;
}

async function reparentarPersona(personaId, nuevoJefeId) {
  // A petición expresa: mover a alguien de jefe directo también mueve su
  // PUESTO para que dependa del puesto de su nuevo jefe -- así "Por
  // persona" y "Por puesto de trabajo" no se desincronizan. Como una
  // persona puede tener más de un puesto (ej. alguien con dos direcciones
  // a la vez) o el nuevo jefe también, solo se reasigna el puesto cuando
  // no hay ambigüedad posible: exactamente un puesto a cada lado.
  const persona = PERSONAS.find((p) => p.id === personaId);
  const nuevoJefe = nuevoJefeId ? PERSONAS.find((p) => p.id === nuevoJefeId) : null;
  const puestoUnicoPersona = persona?.puestos?.length === 1 ? persona.puestos[0].id : null;
  const puestoUnicoJefe = nuevoJefeId === null ? null : (nuevoJefe?.puestos?.length === 1 ? nuevoJefe.puestos[0].id : undefined);
  const puedeReasignarPuesto = puestoUnicoPersona && puestoUnicoJefe !== undefined;

  if (puedeReasignarPuesto) {
    const nuevoPuestoPadreId = puestoUnicoJefe;
    const puestoActual = PUESTOS.find((p) => p.id === puestoUnicoPersona);
    const yaEsPadre = puestoActual && puestoActual.puesto_padre_id === nuevoPuestoPadreId;
    const esValido = nuevoPuestoPadreId === null || esReparentadoValido(puestoUnicoPersona, nuevoPuestoPadreId);
    if (puestoActual && !yaEsPadre && esValido) {
      const companeros = PERSONAS.filter(
        (p) => p.id !== personaId && (p.puestos || []).some((pu) => pu.id === puestoUnicoPersona)
      );
      let continuar = true;
      if (companeros.length) {
        continuar = await pedirConfirmacion(
          `El puesto "${puestoActual.nombre}" también lo ocupan ${companeros.map((c) => c.nombre_completo).join(", ")}. ` +
          `Moverlo hará que a ellos también les cambie el puesto padre. ¿Continuar?`
        );
      }
      if (continuar) {
        await fetch(`${AUTH_API_BASE}/evaluaciones360/puestos/${puestoUnicoPersona}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ puesto_padre_id: nuevoPuestoPadreId }),
        });
      }
    }
  }
  await fetch(`${AUTH_API_BASE}/evaluaciones360/personas/${personaId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ jefe_directo_id: nuevoJefeId }),
  });
  PUESTOS = await fetch(`${AUTH_API_BASE}/evaluaciones360/puestos?empresa=${EMPRESA}`).then((r) => r.json());
  await cargarOrganigrama();
}

function wirePersonaRows(ul) {
  ul.querySelectorAll(".persona-row").forEach((row) => {
    row.addEventListener("dragstart", (e) => {
      personaArrastradaId = Number(row.dataset.personaId);
      row.classList.add("arrastrando");
      e.dataTransfer.effectAllowed = "move";
    });
    row.addEventListener("dragend", () => {
      personaArrastradaId = null;
      ul.querySelectorAll(".arrastrando, .drop-valido, .drop-invalido").forEach((r) => {
        r.classList.remove("arrastrando", "drop-valido", "drop-invalido");
      });
    });
    row.addEventListener("dragover", (e) => {
      if (personaArrastradaId === null) return;
      e.preventDefault();
    });
    row.addEventListener("dragenter", (e) => {
      if (personaArrastradaId === null) return;
      e.preventDefault();
      const destinoId = Number(row.dataset.personaId);
      row.classList.toggle("drop-valido", esReparentadoValidoPersona(personaArrastradaId, destinoId));
      row.classList.toggle("drop-invalido", !esReparentadoValidoPersona(personaArrastradaId, destinoId));
    });
    row.addEventListener("dragleave", () => {
      row.classList.remove("drop-valido", "drop-invalido");
    });
    row.addEventListener("drop", async (e) => {
      e.preventDefault();
      e.stopPropagation();
      row.classList.remove("drop-valido", "drop-invalido");
      const destinoId = Number(row.dataset.personaId);
      const arrastradaId = personaArrastradaId;
      personaArrastradaId = null;
      if (arrastradaId === null || !esReparentadoValidoPersona(arrastradaId, destinoId)) return;
      await reparentarPersona(arrastradaId, destinoId);
    });
  });
}

// ---------------------------------------------------------------------------
// Organigrama por puesto de trabajo
// ---------------------------------------------------------------------------

let editandoPuestoId = null;
let puestoArrastradoId = null;
const puestosColapsados = new Set();
let personasPorPuestoActual = new Map();

function activarSubvistaOrganigrama(nombre) {
  document.querySelectorAll(".eval360-subtab-btn").forEach((b) => b.classList.toggle("activa", b.dataset.subvista === nombre));
  document.getElementById("lista-organigrama-wrap").hidden = nombre !== "personas";
  document.getElementById("lista-puestos-wrap").hidden = nombre !== "puestos";
  if (nombre === "puestos") renderPuestosArbol();
}

function renderPuestosArbol() {
  const cont = document.getElementById("puestos-arbol-inner");
  if (PUESTOS.length === 0) {
    cont.innerHTML = `<p class="staff-hint">Todavía no hay puestos de trabajo. Empieza por el puesto de más arriba (sin puesto al que reporta) y ve añadiendo debajo.</p>`;
    return;
  }
  const personasPorPuesto = new Map();
  for (const persona of PERSONAS) {
    for (const puesto of persona.puestos || []) {
      if (!personasPorPuesto.has(puesto.id)) personasPorPuesto.set(puesto.id, []);
      personasPorPuesto.get(puesto.id).push(persona);
    }
  }
  personasPorPuestoActual = personasPorPuesto; // para los handlers de drag, fuera de esta función
  const porPadre = new Map();
  for (const p of PUESTOS) {
    const clave = p.puesto_padre_id || "raiz";
    if (!porPadre.has(clave)) porPadre.set(clave, []);
    porPadre.get(clave).push(p);
  }
  const raices = porPadre.get("raiz") || [];
  if (raices.length === 0) {
    cont.innerHTML = `<p class="staff-hint">Todos los puestos tienen un padre -- algo no cuadra. Revisa el listado.</p>`;
    return;
  }
  cont.innerHTML = raices
    .map((raiz, i) => `<ul class="orgchart${i > 0 ? " orgchart-raiz-extra" : ""}">${nodoPuestoHTML(raiz, porPadre, personasPorPuesto, new Set())}</ul>`)
    .join("");
  wirePuestoBoxes(cont);
}

function nodoPuestoHTML(puesto, porPadre, personasPorPuesto, vistos) {
  if (vistos.has(puesto.id)) return "";
  const vistosHijo = new Set(vistos).add(puesto.id);
  const hijos = (porPadre.get(puesto.id) || []).filter((h) => !vistosHijo.has(h.id));
  const personas = personasPorPuesto.get(puesto.id) || [];
  // Cada persona es su propia ficha arrastrable -- cuando un puesto lo
  // comparten varios (ej. "Gerente de Retail"), cada uno puede tener un
  // jefe directo distinto (su encargado de turno concreto), no todos el
  // mismo por defecto solo por compartir puesto.
  const personasHTML = personas.length
    ? `<span class="puesto-personas">${personas.map((p) => `<span class="persona-chip" draggable="true" data-persona-id="${p.id}" title="Arrastra para cambiar su jefe directo">${escapeHTML(p.nombre_completo)}</span>`).join("")}</span>`
    : `<span class="puesto-vacante">Vacante</span>`;
  const colapsado = puestosColapsados.has(puesto.id);
  const toggleHTML = hijos.length
    ? `<button type="button" class="orgchart-toggle" data-toggle-puesto="${puesto.id}" title="${colapsado ? "Expandir" : "Colapsar"}">${colapsado ? "+" : "−"}</button>`
    : "";
  const hijosHTML = hijos.length && !colapsado
    ? `<ul>${hijos.map((h) => nodoPuestoHTML(h, porPadre, personasPorPuesto, vistosHijo)).join("")}</ul>`
    : "";
  return `
    <li>
      <div class="orgchart-box" draggable="true" data-puesto-id="${puesto.id}">
        <span class="puesto-nombre">${escapeHTML(puesto.nombre)}</span>
        ${personasHTML}
        <div class="puesto-acciones">
          <button type="button" class="btn btn-ghost btn-mini" data-nuevo-subpuesto="${puesto.id}">＋</button>
          <button type="button" class="btn btn-ghost btn-mini" data-editar-puesto="${puesto.id}">✎</button>
        </div>
        ${toggleHTML}
      </div>
      ${hijosHTML}
    </li>`;
}

function esReparentadoValido(arrastradoId, destinoId) {
  if (arrastradoId === destinoId) return false;
  // El destino no puede ser descendiente de lo que se arrastra -- si lo
  // fuera, soltarlo ahí crearía un ciclo (un puesto reportando, por una
  // cadena de padres, a sí mismo).
  let cursor = PUESTOS.find((p) => p.id === destinoId);
  while (cursor && cursor.puesto_padre_id) {
    if (cursor.puesto_padre_id === arrastradoId) return false;
    cursor = PUESTOS.find((p) => p.id === cursor.puesto_padre_id);
  }
  return true;
}

async function reparentarPuesto(puestoId, nuevoPadreId) {
  // Sincronizado con "Por persona": quien ocupe el puesto que se mueve
  // pasa a tener como jefe directo a quien ocupe el nuevo puesto padre --
  // es la misma empresa, las dos vistas del organigrama no pueden quedar
  // desincronizadas por moverlo desde un solo lado.
  const nuevoJefeId = nuevoPadreId
    ? (PERSONAS.find((p) => (p.puestos || []).some((pu) => pu.id === nuevoPadreId))?.id ?? null)
    : null;
  const ocupantes = PERSONAS.filter((p) => (p.puestos || []).some((pu) => pu.id === puestoId));
  for (const persona of ocupantes) {
    await fetch(`${AUTH_API_BASE}/evaluaciones360/personas/${persona.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jefe_directo_id: nuevoJefeId }),
    });
  }
  await fetch(`${AUTH_API_BASE}/evaluaciones360/puestos/${puestoId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ puesto_padre_id: nuevoPadreId }),
  });
  PUESTOS = await fetch(`${AUTH_API_BASE}/evaluaciones360/puestos?empresa=${EMPRESA}`).then((r) => r.json());
  PERSONAS = await fetch(`${AUTH_API_BASE}/evaluaciones360/personas?empresa=${EMPRESA}`).then((r) => r.json());
  renderPuestosArbol();
}

function wirePuestoBoxes(cont) {
  cont.querySelectorAll("[data-editar-puesto]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      abrirEditorPuesto(Number(btn.dataset.editarPuesto));
    });
  });
  cont.querySelectorAll("[data-nuevo-subpuesto]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      abrirEditorPuesto(null, Number(btn.dataset.nuevoSubpuesto));
    });
  });
  cont.querySelectorAll("[data-toggle-puesto]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const id = Number(btn.dataset.togglePuesto);
      if (puestosColapsados.has(id)) puestosColapsados.delete(id);
      else puestosColapsados.add(id);
      renderPuestosArbol();
    });
  });

  cont.querySelectorAll(".persona-chip").forEach((chip) => {
    chip.addEventListener("dragstart", (e) => {
      e.stopPropagation(); // que no dispare también el drag de la caja del puesto
      personaArrastradaId = Number(chip.dataset.personaId);
      chip.classList.add("arrastrando");
      e.dataTransfer.effectAllowed = "move";
    });
    chip.addEventListener("dragend", (e) => {
      e.stopPropagation();
      personaArrastradaId = null;
      cont.querySelectorAll(".arrastrando, .drop-valido, .drop-invalido").forEach((b) => {
        b.classList.remove("arrastrando", "drop-valido", "drop-invalido");
      });
    });
    chip.addEventListener("click", (e) => e.stopPropagation());
  });

  cont.querySelectorAll(".orgchart-box").forEach((box) => {
    box.addEventListener("dragstart", (e) => {
      puestoArrastradoId = Number(box.dataset.puestoId);
      box.classList.add("arrastrando");
      e.dataTransfer.effectAllowed = "move";
    });
    box.addEventListener("dragend", () => {
      puestoArrastradoId = null;
      cont.querySelectorAll(".arrastrando, .drop-valido, .drop-invalido").forEach((b) => {
        b.classList.remove("arrastrando", "drop-valido", "drop-invalido");
      });
    });
    box.addEventListener("dragover", (e) => {
      if (puestoArrastradoId === null && personaArrastradaId === null) return;
      e.preventDefault();
    });
    box.addEventListener("dragenter", (e) => {
      const destinoId = Number(box.dataset.puestoId);
      if (personaArrastradaId !== null) {
        e.preventDefault();
        const valido = esValidoSoltarPersonaEnPuesto(personaArrastradaId, destinoId);
        box.classList.toggle("drop-valido", valido);
        box.classList.toggle("drop-invalido", !valido);
        return;
      }
      if (puestoArrastradoId === null) return;
      e.preventDefault();
      box.classList.toggle("drop-valido", esReparentadoValido(puestoArrastradoId, destinoId));
      box.classList.toggle("drop-invalido", !esReparentadoValido(puestoArrastradoId, destinoId));
    });
    box.addEventListener("dragleave", () => {
      box.classList.remove("drop-valido", "drop-invalido");
    });
    box.addEventListener("drop", async (e) => {
      e.preventDefault();
      e.stopPropagation();
      box.classList.remove("drop-valido", "drop-invalido");
      const destinoId = Number(box.dataset.puestoId);

      if (personaArrastradaId !== null) {
        const arrastradaId = personaArrastradaId;
        personaArrastradaId = null;
        if (!esValidoSoltarPersonaEnPuesto(arrastradaId, destinoId)) {
          await mostrarAviso("Ese puesto no tiene un único responsable claro (está vacante o lo comparte más de una persona), así que no se puede usar directamente como jefe. Ábrelo y asigna el jefe directo a mano si hace falta.");
          return;
        }
        const nuevoJefeId = (personasPorPuestoActual.get(destinoId) || [])[0].id;
        await asignarJefeDirectoSolo(arrastradaId, nuevoJefeId);
        return;
      }

      const arrastradoId = puestoArrastradoId;
      puestoArrastradoId = null;
      if (arrastradoId === null || !esReparentadoValido(arrastradoId, destinoId)) return;
      await reparentarPuesto(arrastradoId, destinoId);
    });
  });
}

async function asignarJefeDirectoSolo(personaId, nuevoJefeId) {
  // A diferencia de reparentarPersona(), esto NO mueve el puesto -- es
  // justo lo contrario de lo que se busca al arrastrar una ficha individual
  // dentro de un puesto compartido: que cada persona pueda tener un jefe
  // directo distinto sin arrastrar consigo a sus compañeros de puesto.
  await fetch(`${AUTH_API_BASE}/evaluaciones360/personas/${personaId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ jefe_directo_id: nuevoJefeId }),
  });
  await cargarOrganigrama();
  renderPuestosArbol();
}

function esValidoSoltarPersonaEnPuesto(personaId, puestoDestinoId) {
  const ocupantes = personasPorPuestoActual.get(puestoDestinoId) || [];
  if (ocupantes.length !== 1) return false;
  if (ocupantes[0].id === personaId) return false; // no puede ser su propio jefe
  return true;
}

function poblarSelectPuestoPadre() {
  const sel = document.getElementById("puesto-padre");
  const candidatos = PUESTOS.filter((p) => p.id !== editandoPuestoId);
  sel.innerHTML = `<option value="">— Es un puesto raíz —</option>` +
    candidatos.map((p) => `<option value="${p.id}">${escapeHTML(p.nombre)}</option>`).join("");
}

function abrirEditorPuesto(puestoId, padreSugeridoId) {
  editandoPuestoId = puestoId || null;
  poblarSelectPuestoPadre();
  const puesto = puestoId ? PUESTOS.find((p) => p.id === puestoId) : null;
  document.getElementById("editor-puesto-titulo-h2").textContent = puesto ? "Editar puesto" : "Nuevo puesto";
  document.getElementById("puesto-nombre").value = puesto ? puesto.nombre : "";
  document.getElementById("puesto-padre").value = puesto ? (puesto.puesto_padre_id || "") : (padreSugeridoId || "");
  document.getElementById("btn-desactivar-puesto").hidden = !puesto;
  document.getElementById("editor-puesto-card").hidden = false;
  document.getElementById("lista-puestos-wrap").hidden = true;
  document.getElementById("puesto-nombre").focus();
}

function cerrarEditorPuesto() {
  document.getElementById("editor-puesto-card").hidden = true;
  document.getElementById("lista-puestos-wrap").hidden = false;
  editandoPuestoId = null;
}

async function guardarPuesto() {
  const nombre = document.getElementById("puesto-nombre").value.trim();
  if (!nombre) {
    await mostrarAviso("Ponle un nombre al puesto.");
    return;
  }
  const puestoPadreId = document.getElementById("puesto-padre").value ? Number(document.getElementById("puesto-padre").value) : null;

  // Un puesto nuevo sin padre, cuando ya hay uno o más puestos raíz, antes
  // se quedaba como un árbol aparte, desconectado -- eso es lo que hacía
  // que pareciera "fuera" del organigrama principal. Si es justo lo que se
  // busca (un nuevo puesto por encima de todo, tipo "JV" sobre "Director
  // General"), se ofrece reengancharlo automáticamente.
  let raicesParaReenganchar = [];
  if (!editandoPuestoId && puestoPadreId === null) {
    const raicesActuales = PUESTOS.filter((p) => !p.puesto_padre_id);
    if (raicesActuales.length) {
      const nombres = raicesActuales.map((p) => p.nombre).join(", ");
      const convertir = await pedirConfirmacion(
        `Ya hay puesto(s) sin padre (${nombres}). ¿"${nombre}" pasa a ser el nuevo puesto más alto, por encima de ellos? Si dices que no, quedará como un árbol aparte.`
      );
      if (convertir) raicesParaReenganchar = raicesActuales;
    }
  }

  const url = editandoPuestoId
    ? `${AUTH_API_BASE}/evaluaciones360/puestos/${editandoPuestoId}`
    : `${AUTH_API_BASE}/evaluaciones360/puestos`;
  const body = editandoPuestoId
    ? { nombre, puesto_padre_id: puestoPadreId }
    : { empresa: EMPRESA, nombre, puesto_padre_id: puestoPadreId };
  const res = await fetch(url, {
    method: editandoPuestoId ? "PATCH" : "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    await mostrarAviso("No se pudo guardar el puesto.");
    return;
  }
  const nuevoId = editandoPuestoId || (await res.json()).id;

  for (const raiz of raicesParaReenganchar) {
    await fetch(`${AUTH_API_BASE}/evaluaciones360/puestos/${raiz.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ puesto_padre_id: nuevoId }),
    });
  }

  cerrarEditorPuesto();
  PUESTOS = await fetch(`${AUTH_API_BASE}/evaluaciones360/puestos?empresa=${EMPRESA}`).then((r) => r.json());
  renderPuestosArbol();
  // Un puesto nuevo (sobre todo si es raíz) puede aparecer lejos de donde se
  // estaba mirando -- se centra la vista en él para que no parezca que se
  // perdió por ahí fuera.
  const cajaNueva = document.querySelector(`.orgchart-box[data-puesto-id="${nuevoId}"]`);
  if (cajaNueva) cajaNueva.scrollIntoView({ block: "center", inline: "center" });
}

async function desactivarPuesto() {
  if (!editandoPuestoId) return;
  if (!(await pedirConfirmacion("¿Desactivar este puesto? Las personas que lo tengan asignado lo conservan, pero dejará de aparecer para asignar a más gente. Si tenía subpuestos debajo, pasan a depender directamente de a quién reportaba este."))) return;
  await fetch(`${AUTH_API_BASE}/evaluaciones360/puestos/${editandoPuestoId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ activo: false }),
  });
  cerrarEditorPuesto();
  PUESTOS = await fetch(`${AUTH_API_BASE}/evaluaciones360/puestos?empresa=${EMPRESA}`).then((r) => r.json());
  renderPuestosArbol();
}

function poblarSelectsPersona(puestosMarcados) {
  const listaPuestos = document.getElementById("persona-puestos-lista");
  const marcados = new Set(puestosMarcados || []);
  listaPuestos.innerHTML = PUESTOS.length
    ? PUESTOS.map((p) => `
        <label><input type="checkbox" value="${p.id}" ${marcados.has(p.id) ? "checked" : ""}> ${escapeHTML(p.nombre)}</label>
      `).join("")
    : `<p class="staff-hint" style="margin:0;">Todavía no hay puestos creados.</p>`;

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

function abrirEditorPersona(personaId) {
  editandoPersonaId = personaId || null;
  const persona = personaId ? PERSONAS.find((p) => p.id === personaId) : null;
  poblarSelectsPersona(persona?.puestos?.map((p) => p.id));
  document.getElementById("editor-titulo-h2").textContent = persona ? "Editar persona" : "Nueva persona";
  document.getElementById("persona-nombre").value = persona ? persona.nombre_completo : "";
  document.getElementById("persona-jefe").value = persona?.jefe_directo_id || "";
  document.getElementById("persona-usuario").value = persona?.usuario_id || "";
  document.getElementById("btn-eliminar-persona").hidden = !persona;
  document.getElementById("editor-card").hidden = false;
  document.getElementById("lista-organigrama-wrap").hidden = true;
  document.getElementById("persona-nombre").focus();
}

function cerrarEditorPersona() {
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
  const puestoIds = [...document.querySelectorAll("#persona-puestos-lista input:checked")].map((i) => Number(i.value));
  const body = {
    nombre_completo: nombre,
    puesto_ids: puestoIds,
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
  cerrarEditorPersona();
  await cargarOrganigrama();
}

async function eliminarPersona() {
  if (!editandoPersonaId) return;
  if (!(await pedirConfirmacion("¿Quitar a esta persona del organigrama? No se borran evaluaciones ya hechas, pero dejará de aparecer para nuevas campañas."))) return;
  const res = await fetch(`${AUTH_API_BASE}/evaluaciones360/personas/${editandoPersonaId}`, { method: "DELETE" });
  if (!res.ok) {
    await mostrarAviso("No se pudo eliminar.");
    return;
  }
  cerrarEditorPersona();
  await cargarOrganigrama();
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
  const puestosMarcados = [...document.querySelectorAll("#persona-puestos-lista input:checked")].map((i) => Number(i.value));
  const jefeActual = document.getElementById("persona-jefe").value;
  const usuarioActual = document.getElementById("persona-usuario").value;
  PUESTOS = await fetch(`${AUTH_API_BASE}/evaluaciones360/puestos?empresa=${EMPRESA}`).then((r) => r.json());
  poblarSelectsPersona([...puestosMarcados, id]);
  document.getElementById("persona-jefe").value = jefeActual;
  document.getElementById("persona-usuario").value = usuarioActual;
}

// ---------------------------------------------------------------------------
// Preguntas
// ---------------------------------------------------------------------------

async function cargarPreguntas() {
  PREGUNTAS = await fetch(`${AUTH_API_BASE}/evaluaciones360/preguntas?empresa=${EMPRESA}`).then((r) => r.json());
  renderPreguntas();
}

function renderPreguntas() {
  const cont = document.getElementById("preguntas-contenido");
  if (PREGUNTAS.length === 0) {
    cont.innerHTML = `<p class="staff-hint">Sin preguntas todavía. Usa "＋ Nueva pregunta" para empezar el cuestionario de ${EMPRESA === "saona" ? "SAONA" : "Krispy Kreme"}.</p>`;
    return;
  }
  const grupos = new Map();
  const abiertas = [];
  for (const p of PREGUNTAS) {
    if (p.tipo === "abierta") {
      abiertas.push(p);
      continue;
    }
    const clave = p.grupo || "(sin grupo)";
    if (!grupos.has(clave)) grupos.set(clave, []);
    grupos.get(clave).push(p);
  }
  let html = "";
  for (const [grupo, preguntas] of grupos) {
    html += `
      <div class="preguntas-grupo">
        <h3 class="preguntas-grupo-handle" draggable="true" title="Arrastra para reordenar este bloque completo">⠿ ${escapeHTML(grupo)}</h3>
        <div class="preguntas-grupo-items">${preguntas.map(filaPregunta).join("")}</div>
      </div>`;
  }
  if (abiertas.length) {
    html += `
      <div class="preguntas-grupo">
        <h3 class="preguntas-grupo-handle" draggable="true" title="Arrastra para reordenar este bloque completo">⠿ Preguntas abiertas</h3>
        <div class="preguntas-grupo-items">${abiertas.map(filaPregunta).join("")}</div>
      </div>`;
  }
  cont.innerHTML = html;
  cont.querySelectorAll("[data-pregunta-texto]").forEach((input) => {
    input.addEventListener("change", () => guardarPreguntaCampo(Number(input.dataset.preguntaTexto), { texto: input.value.trim() }));
  });
  cont.querySelectorAll("[data-pregunta-activa]").forEach((chk) => {
    chk.addEventListener("change", () => guardarPreguntaCampo(Number(chk.dataset.preguntaActiva), { activa: chk.checked }));
  });
  wireDragReordenPreguntas(cont);
}

function filaPregunta(p) {
  return `
    <div class="pregunta-row" draggable="true" data-pregunta-id="${p.id}" title="Arrastra para reordenar dentro de este bloque">
      <span class="pregunta-drag-handle">⠿</span>
      <input type="checkbox" data-pregunta-activa="${p.id}" ${p.activa ? "checked" : ""} title="Activa">
      <input type="text" data-pregunta-texto="${p.id}" value="${escapeHTML(p.texto)}" ${p.activa ? "" : "disabled"}>
    </div>`;
}

// ---------------------------------------------------------------------------
// Arrastrar para reordenar preguntas: por bloque completo o por item suelto
// dentro de su mismo bloque.
// ---------------------------------------------------------------------------

function wireDragReordenPreguntas(cont) {
  let grupoArrastrado = null;
  let filaArrastrada = null;

  cont.querySelectorAll(".preguntas-grupo-handle").forEach((handle) => {
    const bloque = handle.closest(".preguntas-grupo");
    handle.addEventListener("dragstart", (e) => {
      grupoArrastrado = bloque;
      bloque.classList.add("arrastrando");
      e.dataTransfer.effectAllowed = "move";
    });
    handle.addEventListener("dragend", () => {
      bloque.classList.remove("arrastrando");
      grupoArrastrado = null;
      guardarNuevoOrdenPreguntas();
    });
  });
  cont.querySelectorAll(".preguntas-grupo").forEach((bloque) => {
    bloque.addEventListener("dragover", (e) => {
      if (!grupoArrastrado || grupoArrastrado === bloque) return;
      e.preventDefault();
      const antes = e.clientY < bloque.getBoundingClientRect().top + bloque.offsetHeight / 2;
      bloque.parentElement.insertBefore(grupoArrastrado, antes ? bloque : bloque.nextSibling);
    });
  });

  cont.querySelectorAll(".pregunta-row").forEach((fila) => {
    fila.addEventListener("dragstart", (e) => {
      e.stopPropagation();
      filaArrastrada = fila;
      fila.classList.add("arrastrando");
      e.dataTransfer.effectAllowed = "move";
    });
    fila.addEventListener("dragend", (e) => {
      e.stopPropagation();
      fila.classList.remove("arrastrando");
      filaArrastrada = null;
      guardarNuevoOrdenPreguntas();
    });
    fila.addEventListener("dragover", (e) => {
      if (!filaArrastrada || filaArrastrada === fila) return;
      // Solo se reordena dentro del mismo bloque -- no se mezclan preguntas
      // de un grupo con otro solo arrastrando un item suelto.
      if (filaArrastrada.parentElement !== fila.parentElement) return;
      e.preventDefault();
      e.stopPropagation();
      const antes = e.clientY < fila.getBoundingClientRect().top + fila.offsetHeight / 2;
      fila.parentElement.insertBefore(filaArrastrada, antes ? fila : fila.nextSibling);
    });
  });
}

async function guardarNuevoOrdenPreguntas() {
  const cambios = [];
  let orden = 0;
  document.querySelectorAll("#preguntas-contenido .pregunta-row").forEach((fila) => {
    const id = Number(fila.dataset.preguntaId);
    const actual = PREGUNTAS.find((p) => p.id === id);
    if (actual && actual.orden !== orden) cambios.push({ id, orden });
    orden++;
  });
  if (!cambios.length) return;
  for (const { id, orden } of cambios) {
    await fetch(`${AUTH_API_BASE}/evaluaciones360/preguntas/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ orden }),
    });
  }
  await cargarPreguntas();
}

async function guardarPreguntaCampo(preguntaId, campos) {
  const res = await fetch(`${AUTH_API_BASE}/evaluaciones360/preguntas/${preguntaId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(campos),
  });
  if (!res.ok) {
    await mostrarAviso("No se pudo guardar el cambio.");
    return;
  }
  await cargarPreguntas();
}

async function nuevaPregunta() {
  const grupo = await pedirTexto("Grupo/categoría (déjalo vacío si es una pregunta abierta):");
  if (grupo === null) return;
  const texto = await pedirTexto("Texto de la pregunta:");
  if (!texto || !texto.trim()) return;
  const res = await fetch(`${AUTH_API_BASE}/evaluaciones360/preguntas`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      empresa: EMPRESA,
      tipo: grupo.trim() ? "likert" : "abierta",
      grupo: grupo.trim() || null,
      texto: texto.trim(),
    }),
  });
  if (!res.ok) {
    await mostrarAviso("No se pudo crear la pregunta.");
    return;
  }
  await cargarPreguntas();
}

// ---------------------------------------------------------------------------
// Campañas
// ---------------------------------------------------------------------------

async function cargarCampanas() {
  CAMPANAS = await fetch(`${AUTH_API_BASE}/evaluaciones360/campanas?empresa=${EMPRESA}`).then((r) => r.json());
  renderCampanas();
}

function renderCampanas() {
  const ul = document.getElementById("campanas-lista");
  if (CAMPANAS.length === 0) {
    ul.innerHTML = `<p class="staff-hint">Todavía no hay campañas. Crea la primera con "＋ Nueva campaña".</p>`;
    return;
  }
  ul.innerHTML = CAMPANAS.map((c) => `
    <li>
      <div class="fila-simple">
        <span class="fila-titulo">${escapeHTML(c.nombre)}</span>
        <span class="badge-estado badge-${c.estado}">${c.estado}</span>
        ${c.periodo_desde ? `<span class="staff-hint">${c.periodo_desde} → ${c.periodo_hasta || "?"}</span>` : ""}
        <div class="fila-acciones">
          <button type="button" class="btn btn-ghost btn-mini" data-abrir-campana="${c.id}">Abrir</button>
        </div>
      </div>
    </li>`).join("");
  ul.querySelectorAll("[data-abrir-campana]").forEach((btn) => {
    btn.addEventListener("click", () => abrirCampana(Number(btn.dataset.abrirCampana)));
  });
}

function abrirFormCampana() {
  document.getElementById("campana-nombre").value = "";
  document.getElementById("campana-desde").value = "";
  document.getElementById("campana-hasta").value = "";
  document.getElementById("form-campana-card").hidden = false;
  document.getElementById("campanas-lista-wrap").hidden = true;
  document.getElementById("campana-nombre").focus();
}

function cerrarFormCampana() {
  document.getElementById("form-campana-card").hidden = true;
  document.getElementById("campanas-lista-wrap").hidden = false;
}

async function guardarCampana() {
  const nombre = document.getElementById("campana-nombre").value.trim();
  if (!nombre) {
    await mostrarAviso("Ponle un nombre a la campaña.");
    return;
  }
  const res = await fetch(`${AUTH_API_BASE}/evaluaciones360/campanas`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      empresa: EMPRESA,
      nombre,
      periodo_desde: document.getElementById("campana-desde").value || null,
      periodo_hasta: document.getElementById("campana-hasta").value || null,
    }),
  });
  if (!res.ok) {
    await mostrarAviso("No se pudo crear la campaña.");
    return;
  }
  const { id } = await res.json();
  cerrarFormCampana();
  await cargarCampanas();
  await abrirCampana(id);
}

async function abrirCampana(campanaId) {
  currentCampana = await fetch(`${AUTH_API_BASE}/evaluaciones360/campanas/${campanaId}`).then((r) => r.json());
  document.getElementById("campanas-lista-wrap").hidden = true;
  document.getElementById("campana-detalle").hidden = false;
  document.getElementById("evaluadores-detalle").hidden = true;
  renderCampanaDetalle();
}

function volverACampanas() {
  currentCampana = null;
  document.getElementById("campana-detalle").hidden = true;
  document.getElementById("campanas-lista-wrap").hidden = false;
  cargarCampanas();
}

function renderCampanaDetalle() {
  const c = currentCampana;
  document.getElementById("campana-detalle-titulo").textContent = `${c.nombre} · ${c.estado}`;
  document.getElementById("campana-detalle-periodo").textContent = c.periodo_desde ? `${c.periodo_desde} → ${c.periodo_hasta || "?"}` : "Sin periodo definido";
  const esBorrador = c.estado === "borrador";
  document.getElementById("btn-anadir-evaluados").hidden = !esBorrador;
  document.getElementById("btn-lanzar-campana").hidden = !esBorrador;
  document.getElementById("btn-cerrar-campana-formal").hidden = c.estado !== "abierta";
  document.getElementById("picker-evaluados-wrap").hidden = true;
  document.getElementById("campana-detalle-hint").textContent = esBorrador
    ? "Añade evaluados, revisa quién evalúa a quién y lanza cuando esté listo."
    : "Campaña ya lanzada -- puedes seguir ajustando evaluadores concretos.";

  const ul = document.getElementById("campana-evaluados-lista");
  if (c.evaluados.length === 0) {
    ul.innerHTML = `<p class="staff-hint">Todavía no hay evaluados en esta campaña.</p>`;
    return;
  }
  ul.innerHTML = c.evaluados.map((e) => `
    <li>
      <div class="fila-simple">
        <span class="fila-titulo">${escapeHTML(e.nombre_completo)}</span>
        <span class="staff-hint">${e.completadas}/${e.total_evaluadores} evaluadores respondieron</span>
        <div class="fila-acciones">
          <button type="button" class="btn btn-ghost btn-mini" data-ver-evaluadores="${e.id}">Evaluadores</button>
          ${esBorrador ? `<button type="button" class="btn btn-ghost btn-mini" data-quitar-evaluado="${e.id}">Quitar</button>` : ""}
        </div>
      </div>
    </li>`).join("");
  ul.querySelectorAll("[data-ver-evaluadores]").forEach((btn) => {
    btn.addEventListener("click", () => abrirEvaluadores(Number(btn.dataset.verEvaluadores)));
  });
  ul.querySelectorAll("[data-quitar-evaluado]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!(await pedirConfirmacion("¿Quitar a esta persona de la campaña? Se pierde su lista de evaluadores propuesta."))) return;
      await fetch(`${AUTH_API_BASE}/evaluaciones360/campanas/${currentCampana.id}/evaluados/${btn.dataset.quitarEvaluado}`, { method: "DELETE" });
      await abrirCampana(currentCampana.id);
    });
  });
}

async function abrirPickerEvaluados() {
  if (PERSONAS.length === 0) await cargarOrganigrama();
  const yaAnadidos = new Set(currentCampana.evaluados.map((e) => e.id));
  const disponibles = PERSONAS.filter((p) => !yaAnadidos.has(p.id));
  const lista = document.getElementById("picker-evaluados-lista");
  if (disponibles.length === 0) {
    lista.innerHTML = `<p class="staff-hint">Ya están todos los del organigrama en esta campaña.</p>`;
  } else {
    lista.innerHTML = disponibles.map((p) => `
      <label><input type="checkbox" value="${p.id}"> ${escapeHTML(p.nombre_completo)}</label>
    `).join("");
  }
  document.getElementById("picker-evaluados-wrap").hidden = false;
}

async function confirmarAnadirEvaluados() {
  const seleccionados = [...document.querySelectorAll("#picker-evaluados-lista input:checked")].map((i) => Number(i.value));
  for (const personaId of seleccionados) {
    await fetch(`${AUTH_API_BASE}/evaluaciones360/campanas/${currentCampana.id}/evaluados`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ persona_id: personaId }),
    });
  }
  document.getElementById("picker-evaluados-wrap").hidden = true;
  await abrirCampana(currentCampana.id);
}

async function lanzarCampana() {
  if (!(await pedirConfirmacion(`¿Lanzar "${currentCampana.nombre}"? Los evaluadores empezarán a ver sus evaluaciones pendientes.`))) return;
  const res = await fetch(`${AUTH_API_BASE}/evaluaciones360/campanas/${currentCampana.id}/lanzar`, { method: "POST" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    await mostrarAviso(err.detail || "No se pudo lanzar la campaña.");
    return;
  }
  await abrirCampana(currentCampana.id);
}

async function cerrarCampanaFormal() {
  if (!(await pedirConfirmacion("¿Cerrar esta campaña? Dejará de aparecer en las pendientes de los evaluadores."))) return;
  await fetch(`${AUTH_API_BASE}/evaluaciones360/campanas/${currentCampana.id}/cerrar`, { method: "POST" });
  await abrirCampana(currentCampana.id);
}

async function abrirEvaluadores(personaId) {
  currentEvaluadoId = personaId;
  document.getElementById("campana-detalle").hidden = true;
  document.getElementById("evaluadores-detalle").hidden = false;
  const persona = currentCampana.evaluados.find((e) => e.id === personaId);
  document.getElementById("evaluadores-titulo").textContent = `Evaluadores de ${persona.nombre_completo}`;
  await renderEvaluadores();
}

async function renderEvaluadores() {
  const evaluadores = await fetch(
    `${AUTH_API_BASE}/evaluaciones360/campanas/${currentCampana.id}/evaluados/${currentEvaluadoId}/evaluadores`
  ).then((r) => r.json());
  const ul = document.getElementById("evaluadores-lista");
  ul.innerHTML = evaluadores.map((a) => `
    <li>
      <div class="fila-simple">
        <span class="fila-titulo">${escapeHTML(a.evaluador_nombre)}</span>
        <span class="relacion-tag">${RELACION_LABEL[a.relacion] || a.relacion}</span>
        ${a.estado === "completada" ? `<span class="badge-estado badge-abierta">respondida</span>` : `<span class="staff-hint">pendiente</span>`}
        <div class="fila-acciones">
          ${a.estado !== "completada" ? `<button type="button" class="btn btn-ghost btn-mini" data-quitar-asignacion="${a.id}">Quitar</button>` : ""}
        </div>
      </div>
    </li>`).join("");
  ul.querySelectorAll("[data-quitar-asignacion]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await fetch(`${AUTH_API_BASE}/evaluaciones360/asignaciones/${btn.dataset.quitarAsignacion}`, { method: "DELETE" });
      await renderEvaluadores();
    });
  });

  if (PERSONAS.length === 0) await cargarOrganigrama();
  const yaEvaluadores = new Set(evaluadores.map((a) => a.evaluador_persona_id));
  personasDisponiblesParaEvaluador = PERSONAS.filter((p) => !yaEvaluadores.has(p.id));
  evaluadorSeleccionadoId = null;
  const buscador = document.getElementById("buscar-nuevo-evaluador");
  buscador.value = "";
  document.getElementById("sugerencias-evaluador").hidden = true;
  document.getElementById("btn-anadir-evaluador-manual").disabled = true;

  const resultadosWrap = document.getElementById("resultados-wrap");
  const puedeVerResultados = CURRENT_USER?.rol === "admin" && currentCampana.estado !== "borrador";
  resultadosWrap.hidden = !puedeVerResultados;
  if (puedeVerResultados) await renderResultados();
}

let personasDisponiblesParaEvaluador = [];
let evaluadorSeleccionadoId = null;

function filtrarSugerenciasEvaluador(query) {
  const cont = document.getElementById("sugerencias-evaluador");
  const q = query.trim().toLowerCase();
  if (!q) {
    cont.hidden = true;
    return;
  }
  // Búsqueda por substring en cualquier parte del nombre -- "am" tiene que
  // encontrar tanto a "Ramon" como a "Amparo", no solo nombres que empiecen así.
  const coincidencias = personasDisponiblesParaEvaluador
    .filter((p) => p.nombre_completo.toLowerCase().includes(q))
    .slice(0, 8);
  cont.innerHTML = coincidencias.length
    ? coincidencias.map((p) => `<button type="button" data-persona-id="${p.id}">${escapeHTML(p.nombre_completo)}</button>`).join("")
    : `<p class="sin-resultados">Sin coincidencias</p>`;
  cont.querySelectorAll("[data-persona-id]").forEach((btn) => {
    btn.addEventListener("mousedown", (e) => {
      e.preventDefault(); // que no se dispare "blur" del input antes del click
      evaluadorSeleccionadoId = Number(btn.dataset.personaId);
      document.getElementById("buscar-nuevo-evaluador").value = btn.textContent;
      cont.hidden = true;
      document.getElementById("btn-anadir-evaluador-manual").disabled = false;
    });
  });
  cont.hidden = false;
}

async function anadirEvaluadorManual() {
  if (!evaluadorSeleccionadoId) return;
  await fetch(`${AUTH_API_BASE}/evaluaciones360/campanas/${currentCampana.id}/evaluados/${currentEvaluadoId}/evaluadores`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ evaluador_persona_id: evaluadorSeleccionadoId }),
  });
  await renderEvaluadores();
}

async function renderResultados() {
  const r = await fetch(
    `${AUTH_API_BASE}/evaluaciones360/campanas/${currentCampana.id}/evaluados/${currentEvaluadoId}/resultados`
  ).then((res) => (res.ok ? res.json() : null));
  const cont = document.getElementById("resultados-contenido");
  if (!r) {
    cont.innerHTML = `<p class="staff-hint">Sin resultados todavía.</p>`;
    return;
  }
  const filasGrupo = Object.entries(r.promedio_por_grupo).map(([g, v]) => `<li>${escapeHTML(g)}: <strong>${v}</strong> / 5</li>`).join("");
  const filasRelacion = Object.entries(r.promedio_por_relacion).map(([rel, v]) => `<li>${RELACION_LABEL[rel] || rel}: <strong>${v}</strong> / 5</li>`).join("");
  const comentarios = r.comentarios_abiertos.map((c) => `
    <li style="margin-bottom:10px;">
      <span class="relacion-tag">${RELACION_LABEL[c.relacion] || c.relacion}</span>
      <strong>${escapeHTML(c.evaluador_nombre)}</strong> — <em>${escapeHTML(c.pregunta_texto)}</em>
      <p style="margin:4px 0 0;">${escapeHTML(c.comentario)}</p>
    </li>`).join("");
  cont.innerHTML = `
    <p><strong>Promedio general:</strong> ${r.promedio_general ?? "—"} / 5</p>
    <p><strong>Por competencia:</strong></p>
    <ul>${filasGrupo || "<li>Sin respuestas todavía</li>"}</ul>
    <p><strong>Por tipo de evaluador:</strong></p>
    <ul>${filasRelacion || "<li>Sin respuestas todavía</li>"}</ul>
    <p><strong>Comentarios abiertos:</strong></p>
    <ul style="list-style:none; padding:0;">${comentarios || "<li>Sin comentarios todavía</li>"}</ul>`;
}

function volverAEvaluados() {
  document.getElementById("evaluadores-detalle").hidden = true;
  document.getElementById("campana-detalle").hidden = false;
  abrirCampana(currentCampana.id);
}

// ---------------------------------------------------------------------------
// Mis evaluaciones
// ---------------------------------------------------------------------------

async function cargarMisPendientes() {
  MIS_PENDIENTES = await fetch(`${AUTH_API_BASE}/evaluaciones360/mis-pendientes`).then((r) => r.json());
  renderMisPendientes();
}

function renderMisPendientes() {
  const ul = document.getElementById("mis-pendientes-lista");
  if (MIS_PENDIENTES.length === 0) {
    ul.innerHTML = `<p class="staff-hint">No tienes evaluaciones pendientes ahora mismo.</p>`;
    return;
  }
  ul.innerHTML = MIS_PENDIENTES.map((a) => `
    <li>
      <div class="fila-simple">
        <span class="fila-titulo">Evaluando a: ${escapeHTML(a.evaluado_nombre)}</span>
        <span class="relacion-tag">${RELACION_LABEL[a.relacion] || a.relacion}</span>
        <span class="staff-hint">${escapeHTML(a.campana_nombre)}</span>
        <div class="fila-acciones">
          <button type="button" class="btn btn-primary btn-mini" data-responder="${a.asignacion_id}">Responder</button>
        </div>
      </div>
    </li>`).join("");
  ul.querySelectorAll("[data-responder]").forEach((btn) => {
    btn.addEventListener("click", () => abrirResponder(Number(btn.dataset.responder)));
  });
}

async function abrirResponder(asignacionId) {
  currentAsignacionId = asignacionId;
  currentFormulario = await fetch(`${AUTH_API_BASE}/evaluaciones360/asignacion/${asignacionId}`).then((r) => r.json());
  document.getElementById("responder-titulo").textContent = `Evaluando a: ${currentFormulario.evaluado_nombre}`;
  renderFormularioResponder();
  document.getElementById("mis-lista-wrap").hidden = true;
  document.getElementById("form-responder-card").hidden = false;
}

function renderFormularioResponder() {
  const { preguntas, respuestas } = currentFormulario;
  const grupos = new Map();
  const abiertas = [];
  for (const p of preguntas) {
    if (p.tipo === "abierta") {
      abiertas.push(p);
      continue;
    }
    const clave = p.grupo || "(sin grupo)";
    if (!grupos.has(clave)) grupos.set(clave, []);
    grupos.get(clave).push(p);
  }
  let html = "";
  for (const [grupo, lista] of grupos) {
    html += `<div class="preguntas-grupo"><h3>${escapeHTML(grupo)}</h3>${lista.map((p) => filaLikert(p, respuestas[p.id])).join("")}</div>`;
  }
  if (abiertas.length) {
    html += `<div class="preguntas-grupo"><h3>Comentarios</h3>${abiertas.map((p) => filaAbierta(p, respuestas[p.id])).join("")}</div>`;
  }
  document.getElementById("responder-preguntas").innerHTML = html;

  document.querySelectorAll("[data-likert]").forEach((radio) => {
    radio.addEventListener("change", () => guardarRespuestaLikert(Number(radio.name.replace("p", ""))));
  });
  document.querySelectorAll("[data-abierta]").forEach((textarea) => {
    textarea.addEventListener("blur", () => guardarRespuestaAbierta(Number(textarea.dataset.abierta)));
  });
}

function filaLikert(pregunta, respuesta) {
  const valorActual = respuesta ? respuesta.valor : undefined;
  const opciones = [
    [1, "Muy rara vez"], [2, "Pocas veces"], [3, "A veces"], [4, "Muy a menudo"], [5, "Siempre"],
  ];
  const radios = opciones.map(([v, label]) => `
    <label><input type="radio" name="p${pregunta.id}" value="${v}" data-likert ${valorActual === v ? "checked" : ""}> ${v} · ${label}</label>
  `).join("");
  const naChecked = respuesta && respuesta.valor === null ? "checked" : "";
  return `
    <div class="form-pregunta-likert">
      <p>${escapeHTML(pregunta.texto)}</p>
      <div class="escala-likert">
        ${radios}
        <label><input type="radio" name="p${pregunta.id}" value="na" data-likert ${naChecked}> N/A</label>
      </div>
    </div>`;
}

function filaAbierta(pregunta, respuesta) {
  return `
    <div class="form-pregunta-abierta">
      <p>${escapeHTML(pregunta.texto)}</p>
      <textarea rows="3" data-abierta="${pregunta.id}">${escapeHTML(respuesta?.comentario || "")}</textarea>
    </div>`;
}

async function guardarRespuestaLikert(preguntaId) {
  const seleccionado = document.querySelector(`input[name="p${preguntaId}"]:checked`);
  if (!seleccionado) return;
  const valor = seleccionado.value === "na" ? null : Number(seleccionado.value);
  await fetch(`${AUTH_API_BASE}/evaluaciones360/asignacion/${currentAsignacionId}/respuestas`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pregunta_id: preguntaId, valor, comentario: null }),
  });
}

async function guardarRespuestaAbierta(preguntaId) {
  const textarea = document.querySelector(`[data-abierta="${preguntaId}"]`);
  await fetch(`${AUTH_API_BASE}/evaluaciones360/asignacion/${currentAsignacionId}/respuestas`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pregunta_id: preguntaId, valor: null, comentario: textarea.value }),
  });
}

async function finalizarEvaluacion() {
  const res = await fetch(`${AUTH_API_BASE}/evaluaciones360/asignacion/${currentAsignacionId}/finalizar`, { method: "POST" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    await mostrarAviso(err.detail || "No se pudo enviar la evaluación.");
    return;
  }
  cerrarResponder();
  await cargarMisPendientes();
}

function cerrarResponder() {
  document.getElementById("form-responder-card").hidden = true;
  document.getElementById("mis-lista-wrap").hidden = false;
  currentAsignacionId = null;
  currentFormulario = null;
}

// ---------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", async () => {
  const user = await checkAuth("/evaluaciones360.html");
  if (!user) return;
  const moduloRequerido = EMPRESA === "saona" ? "saona_evaluaciones360" : "evaluaciones360";
  if (!(user.modulos || []).includes(moduloRequerido)) {
    window.location.href = "/";
    return;
  }
  CURRENT_USER = user;
  wireUserBar(user);
  aplicarBrandingEmpresa();

  document.querySelectorAll(".eval360-tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => activarTab(btn.dataset.tab));
  });
  await activarTab("mis");

  document.getElementById("btn-nueva-persona").addEventListener("click", () => abrirEditorPersona(null));
  document.getElementById("btn-cerrar-editor").addEventListener("click", cerrarEditorPersona);
  document.getElementById("btn-cerrar-editor-x").addEventListener("click", cerrarEditorPersona);
  document.getElementById("btn-guardar-persona").addEventListener("click", guardarPersona);
  document.getElementById("btn-eliminar-persona").addEventListener("click", eliminarPersona);
  document.getElementById("btn-nuevo-puesto").addEventListener("click", nuevoPuesto);
  const personasCont = document.getElementById("organigrama-lista");
  personasCont.addEventListener("dragover", (e) => {
    if (personaArrastradaId !== null) e.preventDefault();
  });
  personasCont.addEventListener("drop", async (e) => {
    if (e.target.closest(".persona-row")) return; // ya lo gestiona la fila concreta
    e.preventDefault();
    const arrastradaId = personaArrastradaId;
    personaArrastradaId = null;
    if (arrastradaId === null) return;
    await reparentarPersona(arrastradaId, null);
  });

  document.querySelectorAll(".eval360-subtab-btn").forEach((btn) => {
    btn.addEventListener("click", () => activarSubvistaOrganigrama(btn.dataset.subvista));
  });
  activarSubvistaOrganigrama("personas");
  document.getElementById("btn-nuevo-puesto-raiz").addEventListener("click", () => abrirEditorPuesto(null));
  const arbolCont = document.getElementById("puestos-arbol");
  arbolCont.addEventListener("dragover", (e) => {
    if (puestoArrastradoId !== null || personaArrastradaId !== null) e.preventDefault();
  });
  arbolCont.addEventListener("drop", async (e) => {
    if (e.target.closest(".orgchart-box")) return; // ya lo gestiona la caja concreta
    e.preventDefault();
    if (personaArrastradaId !== null) {
      const arrastradaId = personaArrastradaId;
      personaArrastradaId = null;
      await asignarJefeDirectoSolo(arrastradaId, null);
      return;
    }
    const arrastradoId = puestoArrastradoId;
    puestoArrastradoId = null;
    if (arrastradoId === null) return;
    await reparentarPuesto(arrastradoId, null);
  });
  // Arrastrar el fondo (no una caja) para desplazar el árbol -- como el
  // organigrama es más ancho/alto que el hueco disponible, la barra de
  // scroll sola no era suficiente, esto imita el "click y arrastra para
  // moverte" del organigrama de Bizneo.
  let panActivo = false;
  let panOrigenX = 0;
  let panOrigenY = 0;
  let panScrollX = 0;
  let panScrollY = 0;
  arbolCont.addEventListener("mousedown", (e) => {
    if (e.target.closest(".orgchart-box")) return; // esa caja usa su propio drag (reparent)
    panActivo = true;
    panOrigenX = e.clientX;
    panOrigenY = e.clientY;
    panScrollX = arbolCont.scrollLeft;
    panScrollY = arbolCont.scrollTop;
    arbolCont.classList.add("panning");
  });
  window.addEventListener("mousemove", (e) => {
    if (!panActivo) return;
    arbolCont.scrollLeft = panScrollX - (e.clientX - panOrigenX);
    arbolCont.scrollTop = panScrollY - (e.clientY - panOrigenY);
  });
  window.addEventListener("mouseup", () => {
    panActivo = false;
    arbolCont.classList.remove("panning");
  });
  let puestoZoom = 1;
  const arbolInner = document.getElementById("puestos-arbol-inner");
  function aplicarZoom() {
    arbolInner.style.transform = `scale(${puestoZoom})`;
    document.getElementById("btn-zoom-reset").textContent = `${Math.round(puestoZoom * 100)}%`;
  }
  document.getElementById("btn-zoom-mas").addEventListener("click", () => {
    puestoZoom = Math.min(2, Math.round((puestoZoom + 0.1) * 10) / 10);
    aplicarZoom();
  });
  document.getElementById("btn-zoom-menos").addEventListener("click", () => {
    puestoZoom = Math.max(0.3, Math.round((puestoZoom - 0.1) * 10) / 10);
    aplicarZoom();
  });
  document.getElementById("btn-zoom-reset").addEventListener("click", () => {
    puestoZoom = 1;
    aplicarZoom();
  });
  arbolCont.addEventListener("wheel", (e) => {
    if (!e.ctrlKey) return;
    e.preventDefault();
    puestoZoom = Math.min(2, Math.max(0.3, Math.round((puestoZoom + (e.deltaY < 0 ? 0.1 : -0.1)) * 10) / 10));
    aplicarZoom();
  }, { passive: false });
  document.getElementById("btn-guardar-puesto").addEventListener("click", guardarPuesto);
  document.getElementById("btn-desactivar-puesto").addEventListener("click", desactivarPuesto);
  document.getElementById("btn-cerrar-editor-puesto").addEventListener("click", cerrarEditorPuesto);
  document.getElementById("btn-cerrar-editor-puesto-x").addEventListener("click", cerrarEditorPuesto);

  document.getElementById("btn-nueva-pregunta").addEventListener("click", nuevaPregunta);

  document.getElementById("btn-nueva-campana").addEventListener("click", abrirFormCampana);
  document.getElementById("btn-cerrar-campana").addEventListener("click", cerrarFormCampana);
  document.getElementById("btn-cerrar-campana-2").addEventListener("click", cerrarFormCampana);
  document.getElementById("btn-guardar-campana").addEventListener("click", guardarCampana);
  document.getElementById("btn-volver-campanas").addEventListener("click", volverACampanas);
  document.getElementById("btn-anadir-evaluados").addEventListener("click", abrirPickerEvaluados);
  document.getElementById("btn-confirmar-evaluados").addEventListener("click", confirmarAnadirEvaluados);
  document.getElementById("btn-cancelar-evaluados").addEventListener("click", () => {
    document.getElementById("picker-evaluados-wrap").hidden = true;
  });
  document.getElementById("btn-seleccionar-todos-evaluados").addEventListener("click", () => {
    document.querySelectorAll("#picker-evaluados-lista input[type=checkbox]").forEach((i) => (i.checked = true));
  });
  document.getElementById("btn-deseleccionar-todos-evaluados").addEventListener("click", () => {
    document.querySelectorAll("#picker-evaluados-lista input[type=checkbox]").forEach((i) => (i.checked = false));
  });
  document.getElementById("btn-lanzar-campana").addEventListener("click", lanzarCampana);
  document.getElementById("btn-cerrar-campana-formal").addEventListener("click", cerrarCampanaFormal);
  document.getElementById("btn-volver-evaluados").addEventListener("click", volverAEvaluados);
  document.getElementById("btn-anadir-evaluador-manual").addEventListener("click", anadirEvaluadorManual);
  document.getElementById("buscar-nuevo-evaluador").addEventListener("input", (e) => {
    evaluadorSeleccionadoId = null;
    document.getElementById("btn-anadir-evaluador-manual").disabled = true;
    filtrarSugerenciasEvaluador(e.target.value);
  });
  document.getElementById("buscar-nuevo-evaluador").addEventListener("blur", () => {
    document.getElementById("sugerencias-evaluador").hidden = true;
  });

  document.getElementById("btn-finalizar-evaluacion").addEventListener("click", finalizarEvaluacion);
  document.getElementById("btn-cerrar-responder").addEventListener("click", cerrarResponder);
  document.getElementById("btn-cerrar-responder-2").addEventListener("click", cerrarResponder);
});

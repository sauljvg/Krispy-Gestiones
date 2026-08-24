const EMPRESA = new URLSearchParams(location.search).get("empresa") === "saona" ? "saona" : "kk";

let CURRENT_USER = null;
let PERSONAS = [];
let PUESTOS = [];
let USUARIOS = [];
let editandoPersonaId = null;

let PREGUNTAS = [];
let ACCESOS = [];

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

// escapeHTML ahora vive en common.js (cargado antes que este script) --
// antes este archivo tenía su propia copia con una implementación distinta
// (regex en vez de textContent/innerHTML) a la de los otros 13 archivos.

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
  if (nombre === "accesos") await cargarAccesos();
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

  // Antes esto se saltaba en silencio cuando había ambigüedad (persona o
  // jefe con 0 o 2+ puestos) -- con puestos compartidos por varias personas
  // (habitual en este organigrama: Gerente de Retail, Gerente de
  // producción...) eso pasaba la mayoría de las veces, y la vista "Por
  // puesto" se quedaba desincronizada sin que quedara ningún rastro de por
  // qué. Ahora se avisa siempre que el puesto no se pudo mover con la
  // persona, para que quede claro que hace falta moverlo a mano en la otra
  // vista.
  if (!puestoUnicoPersona) {
    await mostrarAviso(
      `${persona?.nombre_completo || "Esta persona"} no tiene exactamente un puesto asignado, así que su puesto no se movió junto con el jefe directo. Si hace falta, muévelo a mano en "Por puesto de trabajo".`
    );
  } else if (puestoUnicoJefe === undefined) {
    await mostrarAviso(
      `${nuevoJefe?.nombre_completo || "El nuevo jefe"} no tiene exactamente un puesto asignado, así que no se pudo mover el puesto de ${persona?.nombre_completo || "esta persona"} junto con él. Si hace falta, muévelo a mano en "Por puesto de trabajo".`
    );
  }

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
// Claves de colapso (siempre string): el id del puesto para una caja normal
// o resumen, "persona:<id>" para colapsar los hijos de una caja individual
// dentro de un puesto compartido ya desplegado.
const puestosColapsados = new Set();
// Puestos compartidos (varios ocupantes) que el usuario ha desplegado en
// "una caja por persona" -- por defecto se muestran como una única caja
// resumen con todos los nombres juntos.
const puestosDetalle = new Set();

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
    .map((raiz, i) => `<ul class="orgchart${i > 0 ? " orgchart-raiz-extra" : ""}">${nodoPuestoHTML(raiz, porPadre, personasPorPuesto, new Set(), undefined)}</ul>`)
    .join("");
  wirePuestoBoxes(cont);
}

// `jefeFiltro` (número, null o undefined) determina qué ocupantes de este
// puesto se listan: undefined = todos (modo normal); un id = solo quien
// tenga exactamente ese jefe_directo_id -- estamos dentro de la caja
// individual de una persona concreta (ocupante de un puesto compartido ya
// desplegado "por persona"), así que sus subordinados (p.ej. sus jefes de
// turno) se reparten según a quién reportan de verdad, no todos juntos.
function nodoPuestoHTML(puesto, porPadre, personasPorPuesto, vistos, jefeFiltro) {
  if (vistos.has(puesto.id)) return "";
  const vistosHijo = new Set(vistos).add(puesto.id);
  const hijos = (porPadre.get(puesto.id) || []).filter((h) => !vistosHijo.has(h.id));
  const todos = personasPorPuesto.get(puesto.id) || [];
  const ocupantes = jefeFiltro === undefined ? todos : todos.filter((p) => p.jefe_directo_id === jefeFiltro);

  if (ocupantes.length <= 1) {
    const persona = ocupantes[0] || null;
    const siguienteFiltro = persona ? persona.id : undefined;
    const personasHTML = persona
      ? `<span class="puesto-personas"><span class="persona-chip" data-persona-id="${persona.id}" title="Arrastra para cambiar su jefe directo">${escapeHTML(persona.nombre_completo)}</span></span>`
      : `<span class="puesto-vacante">Vacante</span>`;
    const clave = String(puesto.id);
    const colapsado = puestosColapsados.has(clave);
    const toggleHTML = hijos.length
      ? `<button type="button" class="orgchart-toggle" data-toggle-puesto="${clave}" title="${colapsado ? "Expandir" : "Colapsar"}">${colapsado ? "+" : "−"}</button>`
      : "";
    const hijosHTML = hijos.length && !colapsado
      ? `<ul>${hijos.map((h) => nodoPuestoHTML(h, porPadre, personasPorPuesto, vistosHijo, siguienteFiltro)).join("")}</ul>`
      : "";
    return `
      <li>
        <div class="orgchart-box" data-puesto-id="${puesto.id}" data-jefe-target-id="${persona ? persona.id : ""}">
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

  if (!puestosDetalle.has(puesto.id)) {
    // Resumen: una única caja con todos los nombres juntos (como siempre).
    const clave = String(puesto.id);
    const colapsado = puestosColapsados.has(clave);
    const toggleHTML = hijos.length
      ? `<button type="button" class="orgchart-toggle" data-toggle-puesto="${clave}" title="${colapsado ? "Expandir" : "Colapsar"}">${colapsado ? "+" : "−"}</button>`
      : "";
    const hijosHTML = hijos.length && !colapsado
      ? `<ul>${hijos.map((h) => nodoPuestoHTML(h, porPadre, personasPorPuesto, vistosHijo, undefined)).join("")}</ul>`
      : "";
    const personasHTML = `<span class="puesto-personas">${ocupantes.map((p) => `<span class="persona-chip" data-persona-id="${p.id}" title="Arrastra para cambiar su jefe directo">${escapeHTML(p.nombre_completo)}</span>`).join("")}</span>`;
    return `
      <li>
        <div class="orgchart-box" data-puesto-id="${puesto.id}">
          <span class="puesto-nombre">${escapeHTML(puesto.nombre)}</span>
          ${personasHTML}
          <div class="puesto-acciones">
            <button type="button" class="btn btn-ghost btn-mini" data-ver-detalle-puesto="${puesto.id}" title="Una caja por persona, cada una con sus propios reportes">⛶</button>
            <button type="button" class="btn btn-ghost btn-mini" data-nuevo-subpuesto="${puesto.id}">＋</button>
            <button type="button" class="btn btn-ghost btn-mini" data-editar-puesto="${puesto.id}">✎</button>
          </div>
          ${toggleHTML}
        </div>
        ${hijosHTML}
      </li>`;
  }

  // Desplegado "por persona": una caja por ocupante, cada una con sus
  // propios hijos (p.ej. cada Gerente de Retail ve solo a SUS jefes de
  // turno debajo, no los de sus compañeros de puesto).
  const idsOcupantes = new Set(ocupantes.map((o) => o.id));
  let cajas = ocupantes
    .map((persona) => {
      const clave = `persona:${persona.id}`;
      const colapsado = puestosColapsados.has(clave);
      const hijosHTML = hijos.map((h) => nodoPuestoHTML(h, porPadre, personasPorPuesto, vistosHijo, persona.id)).join("");
      const toggleHTML = hijosHTML
        ? `<button type="button" class="orgchart-toggle" data-toggle-puesto="${clave}" title="${colapsado ? "Expandir" : "Colapsar"}">${colapsado ? "+" : "−"}</button>`
        : "";
      const hijosVisibles = hijosHTML && !colapsado ? `<ul>${hijosHTML}</ul>` : "";
      return `
        <li>
          <div class="orgchart-box orgchart-box-individual" data-puesto-id="${puesto.id}" data-persona-id="${persona.id}" data-jefe-target-id="${persona.id}" title="Arrastra para cambiar su jefe directo">
            <span class="puesto-nombre">${escapeHTML(puesto.nombre)}</span>
            <span class="puesto-personas">${escapeHTML(persona.nombre_completo)}</span>
            <div class="puesto-acciones">
              <button type="button" class="btn btn-ghost btn-mini" data-ver-resumen-puesto="${puesto.id}" title="Volver a juntar en una única caja resumen">⛶</button>
            </div>
            ${toggleHTML}
          </div>
          ${hijosVisibles}
        </li>`;
    })
    .join("");
  // Si algún hijo tiene ocupantes cuyo jefe_directo_id no coincide con
  // ninguno de los actuales (datos desincronizados), no se ocultan -- salen
  // aparte con un aviso, para no perder gente de vista.
  for (const h of hijos) {
    const todosDelHijo = personasPorPuesto.get(h.id) || [];
    const huerfanos = todosDelHijo.filter((x) => !idsOcupantes.has(x.jefe_directo_id));
    if (huerfanos.length) {
      cajas += `
        <li>
          <div class="orgchart-box orgchart-box-huerfanos" title="El jefe directo actual de estas personas no coincide con ninguno de los ocupantes de &quot;${escapeHTML(puesto.nombre)}&quot; -- revisa su jefe directo (arrástralas sobre la caja correcta, o edítalas desde &quot;Por persona&quot;).">
            <span class="puesto-nombre">⚠ ${escapeHTML(h.nombre)}</span>
            <span class="puesto-personas">${huerfanos.map((p) => escapeHTML(p.nombre_completo)).join(", ")}</span>
          </div>
        </li>`;
    }
  }
  return cajas;
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

async function reparentarPuesto(puestoId, nuevoPadreId, nuevoJefeIdOverride) {
  // Sincronizado con "Por persona": quien ocupe el puesto que se mueve
  // pasa a tener como jefe directo a quien ocupe el nuevo puesto padre --
  // es la misma empresa, las dos vistas del organigrama no pueden quedar
  // desincronizadas por moverlo desde un solo lado. Si el drop fue sobre
  // una caja individual (ocupante único, o una persona concreta desplegada
  // dentro de un puesto compartido), se usa ese id exacto en vez de
  // adivinar "el primero que ocupe el puesto".
  let nuevoJefeId = null;
  if (nuevoPadreId) {
    if (nuevoJefeIdOverride !== undefined) {
      nuevoJefeId = nuevoJefeIdOverride;
    } else {
      const ocupantesDestino = PERSONAS.filter((p) => (p.puestos || []).some((pu) => pu.id === nuevoPadreId));
      nuevoJefeId = ocupantesDestino[0]?.id ?? null;
      if (ocupantesDestino.length > 1) {
        await mostrarAviso(
          `El puesto destino lo ocupan varias personas (${ocupantesDestino.map((o) => o.nombre_completo).join(", ")}). ` +
          `Se ha puesto a ${ocupantesDestino[0].nombre_completo} como jefe directo de quien ocupa el puesto movido -- ` +
          `cámbialo a mano en "Por persona" si no es quien corresponde.`
        );
      }
    }
  }
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

// ---------------------------------------------------------------------------
// Arrastre por Pointer Events -- sustituye a la API nativa de HTML5 Drag &
// Drop en el organigrama por puesto. La nativa no sigue al cursor 1:1 (usa
// una imagen fantasma de baja fidelidad, con su propio retraso); aquí es un
// clon del propio elemento el que se mueve con position:fixed en cada
// pointermove, pegado de verdad al cursor. Solo "arranca" tras superar un
// pequeño umbral de movimiento, para no robarle el click a los botones
// anidados en la caja (editar, colapsar, ⛶...) -- si sueltas sin moverte,
// nunca se llega a crear el clon y el click del botón funciona normal.
function wireArrastrePuntero(el, { obtenerDato, onMover, onSoltar, pararPropagacion }) {
  const UMBRAL_PX = 5;
  el.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return; // solo botón principal / toque primario
    if (pararPropagacion) e.stopPropagation();
    const dato = obtenerDato();
    if (dato === null) return;
    const startX = e.clientX;
    const startY = e.clientY;
    let arrancado = false;
    let clon = null;
    let grabX = 0;
    let grabY = 0;

    function elementoBajoCursor(x, y) {
      if (!clon) return document.elementFromPoint(x, y);
      clon.style.display = "none";
      const destino = document.elementFromPoint(x, y);
      clon.style.display = "";
      return destino;
    }

    function arrancar() {
      arrancado = true;
      const rect = el.getBoundingClientRect();
      grabX = startX - rect.left;
      grabY = startY - rect.top;
      clon = el.cloneNode(true);
      clon.classList.add("orgtree-clon-arrastre");
      // Se añade a document.body, nunca dentro de #puestos-arbol-inner: ese
      // contenedor tiene su propio transform: scale() (zoom) que, si el
      // clon quedara anidado dentro, convertiría su position:fixed en
      // relativo a ese ancestro en vez de al viewport -- y dejaría de
      // seguir al cursor con precisión.
      Object.assign(clon.style, {
        position: "fixed", left: `${rect.left}px`, top: `${rect.top}px`,
        width: `${rect.width}px`, margin: "0", pointerEvents: "none", zIndex: "9999",
      });
      document.body.appendChild(clon);
      el.classList.add("arrastrando");
    }

    function mover(e2) {
      if (!arrancado) {
        if (Math.hypot(e2.clientX - startX, e2.clientY - startY) < UMBRAL_PX) return;
        arrancar();
      }
      clon.style.left = `${e2.clientX - grabX}px`;
      clon.style.top = `${e2.clientY - grabY}px`;
      if (onMover) onMover(dato, elementoBajoCursor(e2.clientX, e2.clientY));
    }

    function soltar(e2) {
      window.removeEventListener("pointermove", mover);
      window.removeEventListener("pointerup", soltar);
      window.removeEventListener("pointercancel", soltar);
      if (!arrancado) return;
      const destino = elementoBajoCursor(e2.clientX, e2.clientY);
      clon.remove();
      el.classList.remove("arrastrando");
      if (onSoltar) onSoltar(dato, destino);
    }

    window.addEventListener("pointermove", mover);
    window.addEventListener("pointerup", soltar);
    window.addEventListener("pointercancel", soltar);
  });
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
      const clave = btn.dataset.togglePuesto;
      if (puestosColapsados.has(clave)) puestosColapsados.delete(clave);
      else puestosColapsados.add(clave);
      renderPuestosArbol();
    });
  });
  cont.querySelectorAll("[data-ver-detalle-puesto]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      puestosDetalle.add(Number(btn.dataset.verDetallePuesto));
      renderPuestosArbol();
    });
  });
  cont.querySelectorAll("[data-ver-resumen-puesto]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      puestosDetalle.delete(Number(btn.dataset.verResumenPuesto));
      renderPuestosArbol();
    });
  });

  const limpiarEstadosDrop = () => {
    cont.querySelectorAll(".drop-valido, .drop-invalido").forEach((b) => {
      b.classList.remove("drop-valido", "drop-invalido");
    });
  };
  function marcarDestino(destino, valido) {
    limpiarEstadosDrop();
    if (!destino) return;
    destino.classList.toggle("drop-valido", valido);
    destino.classList.toggle("drop-invalido", !valido);
  }

  // Ficha de persona (chip anidado en una caja de ocupante único, o fila
  // entera de un ocupante ya desplegado dentro de un puesto compartido):
  // arrastrarla reasigna solo su jefe directo, nunca el puesto.
  cont.querySelectorAll(".persona-chip, .orgchart-box-individual").forEach((el) => {
    const esChipAnidado = el.classList.contains("persona-chip");
    wireArrastrePuntero(el, {
      pararPropagacion: esChipAnidado, // que no dispare también el drag de la caja que lo contiene
      obtenerDato: () => (el.dataset.personaId ? Number(el.dataset.personaId) : null),
      onMover: (personaId, elBajoCursor) => {
        const box = elBajoCursor ? elBajoCursor.closest(".orgchart-box") : null;
        if (!box) { limpiarEstadosDrop(); return; }
        const jefeId = box.dataset.jefeTargetId ? Number(box.dataset.jefeTargetId) : null;
        marcarDestino(box, jefeId !== null && jefeId !== personaId);
      },
      onSoltar: async (personaId, elBajoCursor) => {
        limpiarEstadosDrop();
        const box = elBajoCursor ? elBajoCursor.closest(".orgchart-box") : null;
        if (!box) {
          await asignarJefeDirectoSolo(personaId, null);
          return;
        }
        const jefeId = box.dataset.jefeTargetId ? Number(box.dataset.jefeTargetId) : null;
        if (jefeId === null) {
          await mostrarAviso('Ese puesto no tiene un único responsable claro (está vacante o lo comparte más de una persona). Pulsa "⛶" en esa caja y suelta sobre la persona concreta.');
          return;
        }
        if (jefeId === personaId) return;
        await asignarJefeDirectoSolo(personaId, jefeId);
      },
    });
  });

  // Caja de puesto completo (ocupante único, vacante, o resumen de uno
  // compartido): arrastrarla reasigna el puesto entero a un nuevo padre.
  cont.querySelectorAll(".orgchart-box:not(.orgchart-box-individual)").forEach((box) => {
    wireArrastrePuntero(box, {
      obtenerDato: () => (box.dataset.puestoId ? Number(box.dataset.puestoId) : null),
      onMover: (puestoId, elBajoCursor) => {
        const destino = elBajoCursor ? elBajoCursor.closest(".orgchart-box[data-puesto-id]") : null;
        if (!destino) { limpiarEstadosDrop(); return; }
        marcarDestino(destino, esReparentadoValido(puestoId, Number(destino.dataset.puestoId)));
      },
      onSoltar: async (puestoId, elBajoCursor) => {
        limpiarEstadosDrop();
        const destino = elBajoCursor ? elBajoCursor.closest(".orgchart-box[data-puesto-id]") : null;
        if (!destino) {
          await reparentarPuesto(puestoId, null);
          return;
        }
        const destinoId = Number(destino.dataset.puestoId);
        if (!esReparentadoValido(puestoId, destinoId)) return;
        const jefeOverride = destino.dataset.jefeTargetId ? Number(destino.dataset.jefeTargetId) : undefined;
        await reparentarPuesto(puestoId, destinoId, jefeOverride);
      },
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

// De "Saul Vasquez Garcia" saca "saul.v@krispykreme.es" -- primer nombre +
// inicial del primer apellido, sin tildes ni espacios, patrón de email que
// usa el resto de la empresa. El departamento "JV" (Alessandro Moneta, Arnaud
// Van Coppenolle, Joe Wendling, Maria Ibañez-Fischer, Raphael Duvivier...) usa
// un patrón distinto: inicial del NOMBRE + apellido completo, sin punto,
// @krispykreme.com -- ej. "Joe Wendling" -> "jwendling@krispykreme.com". Solo
// una sugerencia de partida: el campo sigue siendo libre de editar.
function sugerirEmailDesdeNombre(nombreCompleto, esJV) {
  const partes = (nombreCompleto || "").trim().split(/\s+/).filter(Boolean);
  if (!partes.length) return "";
  // NFD separa cada letra con tilde en (letra + marca de acento aparte);
  // el filtro [^a-z0-9] de abajo descarta esa marca junto con cualquier
  // otro carácter no alfanumérico, así que el resultado ya queda sin tildes.
  const limpiar = (s) => s.normalize("NFD").toLowerCase().replace(/[^a-z0-9]/g, "");
  if (esJV) {
    const inicial = limpiar(partes[0]).slice(0, 1);
    const apellido = limpiar(partes.slice(1).join(""));
    const local = apellido ? `${inicial}${apellido}` : inicial;
    return local ? `${local}@krispykreme.com` : "";
  }
  const nombre = limpiar(partes[0]);
  const inicial = partes.length > 1 ? limpiar(partes[1]).slice(0, 1) : "";
  const local = inicial ? `${nombre}.${inicial}` : nombre;
  return local ? `${local}@krispykreme.es` : "";
}

function personaEnEdicionEsJV() {
  const puestoJV = PUESTOS.find((p) => p.nombre === "JV");
  if (!puestoJV) return false;
  return !!document.querySelector(`#persona-puestos-lista input[value="${puestoJV.id}"]:checked`);
}

function abrirEditorPersona(personaId) {
  editandoPersonaId = personaId || null;
  const persona = personaId ? PERSONAS.find((p) => p.id === personaId) : null;
  poblarSelectsPersona(persona?.puestos?.map((p) => p.id));
  document.getElementById("editor-titulo-h2").textContent = persona ? "Editar persona" : "Nueva persona";
  document.getElementById("persona-nombre").value = persona ? persona.nombre_completo : "";
  document.getElementById("persona-jefe").value = persona?.jefe_directo_id || "";
  document.getElementById("persona-usuario").value = persona?.usuario_id || "";
  const emailInput = document.getElementById("persona-email");
  emailInput.value = persona?.email || "";
  // Auto=1 mientras el campo siga tal cual la sugerencia (o vacío en una
  // persona nueva) -- en cuanto alguien lo edita a mano, se marca auto=0 y
  // deja de reescribirse solo aunque seguir cambiando el nombre.
  emailInput.dataset.auto = persona?.email ? "0" : "1";
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
    email: document.getElementById("persona-email").value.trim() || null,
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
  document.getElementById("btn-reabrir-campana").hidden = c.estado !== "cerrada";
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
  if (!(await pedirConfirmacion(`¿Lanzar "${currentCampana.nombre}"? Los evaluadores empezarán a ver sus evaluaciones pendientes y se les avisará por email.`))) return;
  const res = await fetch(`${AUTH_API_BASE}/evaluaciones360/campanas/${currentCampana.id}/lanzar`, { method: "POST" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    await mostrarAviso(err.detail || "No se pudo lanzar la campaña.");
    return;
  }
  const { avisos } = await res.json();
  await abrirCampana(currentCampana.id);
  if (avisos) {
    await mostrarAviso(
      avisos.omitidos > 0
        ? `Campaña lanzada. Aviso enviado a ${avisos.enviados} evaluador(es); ${avisos.omitidos} no se pudieron avisar (sin email registrado o fallo al enviar).`
        : `Campaña lanzada. Aviso enviado por email a ${avisos.enviados} evaluador(es).`
    );
  }
}

async function cerrarCampanaFormal() {
  if (!(await pedirConfirmacion("¿Cerrar esta campaña? Dejará de aparecer en las pendientes de los evaluadores."))) return;
  await fetch(`${AUTH_API_BASE}/evaluaciones360/campanas/${currentCampana.id}/cerrar`, { method: "POST" });
  await abrirCampana(currentCampana.id);
}

async function reabrirCampana() {
  if (!(await pedirConfirmacion("¿Reabrir esta campaña? Los evaluadores con pendientes sin completar volverán a verla en \"Mis evaluaciones\"."))) return;
  const res = await fetch(`${AUTH_API_BASE}/evaluaciones360/campanas/${currentCampana.id}/reabrir`, { method: "POST" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    await mostrarAviso(err.detail || "No se pudo reabrir la campaña.");
    return;
  }
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

// Recordatorio por mailto (abre el cliente de correo del propio usuario --
// no se envía nada desde el servidor) para un evaluador con una evaluación
// pendiente. Sin email registrado en su ficha, no hay a quién escribirle.
function enlaceMailtoRecordatorio(asignacion, evaluado) {
  if (!asignacion.evaluador_email) {
    return `<span class="staff-hint" title="Añádele un email desde Organigrama para poder escribirle">Sin email</span>`;
  }
  const asunto = `Evaluación 360° pendiente${evaluado ? ` -- ${evaluado.nombre_completo}` : ""}`;
  const cuerpo = `Hola ${asignacion.evaluador_nombre},\n\nTienes una evaluación 360° pendiente de responder en Krispy Gestiones${evaluado ? ` sobre ${evaluado.nombre_completo}` : ""}.\n\nGracias.`;
  const href = `mailto:${asignacion.evaluador_email}?subject=${encodeURIComponent(asunto)}&body=${encodeURIComponent(cuerpo)}`;
  return `<a class="btn btn-ghost btn-mini" href="${escapeHTML(href)}" title="Abrir un correo de recordatorio para ${escapeHTML(asignacion.evaluador_nombre)}">✉ Recordar</a>`;
}

async function renderEvaluadores() {
  const evaluadores = await fetch(
    `${AUTH_API_BASE}/evaluaciones360/campanas/${currentCampana.id}/evaluados/${currentEvaluadoId}/evaluadores`
  ).then((r) => r.json());
  const evaluado = currentCampana.evaluados.find((e) => e.id === currentEvaluadoId);
  const ul = document.getElementById("evaluadores-lista");
  ul.innerHTML = evaluadores.map((a) => `
    <li>
      <div class="fila-simple">
        <span class="fila-titulo">${escapeHTML(a.evaluador_nombre)}</span>
        <span class="relacion-tag">${RELACION_LABEL[a.relacion] || a.relacion}</span>
        ${a.estado === "completada" ? `<span class="badge-estado badge-abierta">respondida</span>` : `<span class="staff-hint">pendiente</span>`}
        <div class="fila-acciones">
          ${a.estado !== "completada" ? enlaceMailtoRecordatorio(a, evaluado) : ""}
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
    const preguntaId = Number(textarea.dataset.abierta);
    textarea.addEventListener("blur", () => guardarRespuestaAbierta(preguntaId));
    textarea.addEventListener("input", () => {
      const contador = document.querySelector(`[data-contador="${preguntaId}"]`);
      if (contador) contador.textContent = contadorCaracteresTexto(textarea.value);
    });
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

const MIN_CARACTERES_ABIERTA = 20;

function filaAbierta(pregunta, respuesta) {
  const texto = respuesta?.comentario || "";
  return `
    <div class="form-pregunta-abierta">
      <p>${escapeHTML(pregunta.texto)}</p>
      <textarea rows="6" data-abierta="${pregunta.id}">${escapeHTML(texto)}</textarea>
      <p class="staff-hint" data-contador="${pregunta.id}">${contadorCaracteresTexto(texto)}</p>
    </div>`;
}

function contadorCaracteresTexto(texto) {
  const n = (texto || "").trim().length;
  return n >= MIN_CARACTERES_ABIERTA
    ? `${n} caracteres`
    : `${n}/${MIN_CARACTERES_ABIERTA} caracteres mínimo`;
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
// Accesos: crear cuentas de portal (usuario + PIN que se crea la propia
// persona al entrar por primera vez) para quien todavía no tenga una
// vinculada -- separado a propósito de "Cuenta vinculada" en la ficha de
// persona (eso es para enlazar una cuenta YA existente; esto crea cuentas
// nuevas, así que solo toca a quien no tiene ninguna todavía).
// ---------------------------------------------------------------------------

async function cargarAccesos() {
  ACCESOS = await fetch(`${AUTH_API_BASE}/evaluaciones360/accesos?empresa=${EMPRESA}`).then((r) => r.json());
  renderAccesos();
}

function renderAccesos() {
  const ul = document.getElementById("accesos-lista");
  const btnTodos = document.getElementById("btn-crear-todos-accesos");
  const pendientes = ACCESOS.filter((p) => !p.tiene_acceso);
  btnTodos.hidden = pendientes.length === 0;
  if (ACCESOS.length === 0) {
    ul.innerHTML = `<p class="staff-hint">Todavía no hay nadie en el organigrama.</p>`;
    return;
  }
  ul.innerHTML = ACCESOS.map((p) => `
    <li>
      <div class="fila-simple" data-fila-acceso="${p.id}">
        <span class="fila-titulo">${escapeHTML(p.nombre_completo)}</span>
        <span class="staff-hint">${p.email ? escapeHTML(p.email) : "sin email registrado"}</span>
        <div class="fila-acciones">
          ${p.tiene_acceso
            ? `<span class="badge-estado badge-abierta">✓ acceso creado${p.username ? ` (usuario: ${escapeHTML(p.username)})` : ""}</span>`
            : `<button type="button" class="btn btn-ghost btn-mini" data-crear-acceso="${p.id}">Crear acceso</button>`}
        </div>
      </div>
    </li>`).join("");
  ul.querySelectorAll("[data-crear-acceso]").forEach((btn) => {
    btn.addEventListener("click", () => crearAcceso(Number(btn.dataset.crearAcceso)));
  });
}

async function crearAcceso(personaId) {
  const res = await fetch(`${AUTH_API_BASE}/evaluaciones360/accesos/${personaId}/crear`, { method: "POST" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    await mostrarAviso(err.detail || "No se pudo crear el acceso.");
    return false;
  }
  const { username } = await res.json();
  const persona = ACCESOS.find((p) => p.id === personaId);
  if (persona) {
    persona.tiene_acceso = true;
    persona.username = username;
  }
  const fila = document.querySelector(`[data-fila-acceso="${personaId}"] .fila-acciones`);
  if (fila) fila.innerHTML = `<span class="badge-estado badge-abierta">✓ acceso creado (usuario: ${escapeHTML(username)})</span>`;
  return true;
}

async function crearTodosAccesos() {
  const pendientes = ACCESOS.filter((p) => !p.tiene_acceso);
  if (!(await pedirConfirmacion(`¿Crear una cuenta de portal para las ${pendientes.length} personas que aún no tienen? Cada una entrará por primera vez con su usuario y creará su propio PIN.`))) return;
  for (const p of pendientes) {
    await crearAcceso(p.id);
  }
  renderAccesos();
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

  // Solo un admin gestiona campañas/organigrama/preguntas/accesos -- el resto
  // de gente con el módulo concedido únicamente responde sus evaluaciones
  // asignadas (pestaña "Mis evaluaciones"), el backend ya rechaza con 403
  // cualquier intento de llamar a esos endpoints de gestión igualmente.
  if (user.rol !== "admin") {
    ["campanas", "organigrama", "preguntas", "accesos"].forEach((nombre) => {
      const btn = document.querySelector(`.eval360-tab-btn[data-tab="${nombre}"]`);
      if (btn) btn.hidden = true;
    });
  }

  document.querySelectorAll(".eval360-tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => activarTab(btn.dataset.tab));
  });
  await activarTab("mis");

  document.getElementById("btn-crear-todos-accesos").addEventListener("click", crearTodosAccesos);
  document.getElementById("btn-nueva-persona").addEventListener("click", () => abrirEditorPersona(null));
  document.getElementById("btn-cerrar-editor").addEventListener("click", cerrarEditorPersona);
  document.getElementById("btn-cerrar-editor-x").addEventListener("click", cerrarEditorPersona);
  document.getElementById("btn-guardar-persona").addEventListener("click", guardarPersona);
  document.getElementById("btn-eliminar-persona").addEventListener("click", eliminarPersona);
  document.getElementById("persona-nombre").addEventListener("input", (e) => {
    const emailInput = document.getElementById("persona-email");
    if (emailInput.dataset.auto === "0") return; // ya lo editaron a mano, no se lo pisamos
    emailInput.value = sugerirEmailDesdeNombre(e.target.value, personaEnEdicionEsJV());
    emailInput.dataset.auto = "1";
  });
  document.getElementById("persona-email").addEventListener("input", (e) => {
    e.target.dataset.auto = "0";
  });
  // Si marcan/desmarcan el puesto "JV" después de escribir el nombre, la
  // sugerencia de email (si sigue siendo automática) se recalcula con el
  // patrón correcto en vez de quedarse con el de antes.
  document.getElementById("persona-puestos-lista").addEventListener("change", () => {
    const emailInput = document.getElementById("persona-email");
    if (emailInput.dataset.auto === "0") return;
    emailInput.value = sugerirEmailDesdeNombre(document.getElementById("persona-nombre").value, personaEnEdicionEsJV());
  });
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
  // (Soltar sobre el fondo, sin caja debajo, ya lo gestiona el propio
  // onSoltar de wireArrastrePuntero en wirePuestoBoxes -- destino null.)
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
  document.getElementById("btn-reabrir-campana").addEventListener("click", reabrirCampana);
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

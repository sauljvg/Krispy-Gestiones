function escapeHTML(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

const EMPRESA = new URLSearchParams(location.search).get("empresa") === "saona" ? "saona" : "kk";

function aplicarBrandingEmpresa() {
  if (EMPRESA !== "saona") return;
  document.title = document.title.replace("Krispy Gestiones", "SAONA Gestiones");
  const icon = document.getElementById("brand-icon");
  if (icon) icon.textContent = "🌿";
  const favicon = document.querySelector('link[rel="icon"]');
  if (favicon) favicon.href = "assets/favicon-saona.png";
  const title = document.getElementById("brand-title");
  if (title) title.textContent = "SAONA Gestiones";
  document.documentElement.dataset.empresa = "saona";
}

function nombreCandidato(datos) {
  return datos["Nombre"] || datos["nombre"] || datos["Name"] || "(sin nombre)";
}

function soloDigitos(tel) {
  return (tel || "").replace(/\D/g, "");
}

// ---------------------------------------------------------------------
// Campaña de WhatsApp: sin API de WhatsApp Business no hay forma segura de
// enviar automáticamente (cualquier "auto-clic" en WhatsApp Web viola sus
// términos y puede acabar en un bloqueo del número) — en su lugar, se
// escribe UNA plantilla con {nombre}, y se genera un enlace wa.me por
// candidato con el mensaje ya escrito; el propio usuario pulsa "Enviar" y
// confirma el envío en WhatsApp, uno por uno pero sin tener que redactar
// cada mensaje a mano.
// ---------------------------------------------------------------------

let campanaCandidatos = [];
let campanaTestsAbiertos = [];
let campanaEnlaceTest = "";

async function cargarTestsAbiertosCampana() {
  try {
    const res = await fetch(`${AUTH_API_BASE}/encuestas/encuestas`);
    if (!res.ok) return [];
    const tests = await res.json();
    return tests.filter((t) => t.estado === "abierta");
  } catch {
    return [];
  }
}

function campanaTestSelectHTML() {
  // Solo tiene sentido ofrecer tests ABIERTOS — el enlace de uno cerrado no
  // deja responder a nadie que lo reciba.
  if (campanaTestsAbiertos.length === 0) return "";
  return `
    <div class="form-field form-field-full" style="margin-bottom:10px;">
      <label>Adjuntar enlace de un test (opcional)</label>
      <select id="campana-test">
        <option value="">— Sin enlace de test —</option>
        ${campanaTestsAbiertos.map((t) => `<option value="${String(t.id).padStart(4, "0")}">${escapeHTML(t.titulo)}</option>`).join("")}
      </select>
    </div>`;
}

function candidatoWhatsappRowHTML(c, i) {
  const tieneTelefono = !!c.telefono;
  return `
    <div class="candidato-mini-card candidato-whatsapp-row">
      <div>
        <h4>${escapeHTML(c.nombre_completo || `Candidato ${i + 1}`)}</h4>
        <p>${escapeHTML(c.telefono || "Sin teléfono guardado")}</p>
      </div>
      ${tieneTelefono
        ? `<a class="btn btn-ghost btn-whatsapp-campana" data-idx="${i}" target="_blank" rel="noopener">💬 Enviar</a>`
        : ""}
    </div>`;
}

function actualizarEnlacesCampana() {
  const plantilla = document.getElementById("campana-mensaje").value;
  campanaCandidatos.forEach((c, i) => {
    const link = document.querySelector(`.btn-whatsapp-campana[data-idx="${i}"]`);
    if (!link) return;
    const primerNombre = (c.nombre_completo || "").trim().split(/\s+/)[0] || "";
    const mensaje = plantilla.replaceAll("{nombre}", primerNombre).replaceAll("{enlace}", campanaEnlaceTest);
    link.href = `https://wa.me/${soloDigitos(c.telefono)}?text=${encodeURIComponent(mensaje)}`;
  });
}

function onCambiaTestCampana() {
  const select = document.getElementById("campana-test");
  campanaEnlaceTest = select.value ? `${location.origin}/encuesta.html?slug=${select.value}` : "";
  const textarea = document.getElementById("campana-mensaje");
  // Primera vez que se elige un test en este envío: si el mensaje todavía no
  // menciona el enlace, se añade solo para que quede a la vista — si el
  // admin ya lo había escrito o borrado a mano, no se le vuelve a imponer.
  if (select.value && !textarea.value.includes("{enlace}")) {
    textarea.value = `${textarea.value}\n\n{enlace}`;
  }
  actualizarEnlacesCampana();
}

function cerrarCampanaWhatsapp() {
  campanaCandidatos = [];
  campanaEnlaceTest = "";
  document.getElementById("campana-whatsapp-wrap").innerHTML = "";
}

async function abrirCampanaWhatsapp(candidatos) {
  campanaCandidatos = candidatos;
  campanaEnlaceTest = "";
  campanaTestsAbiertos = await cargarTestsAbiertosCampana();
  const conTelefono = candidatos.filter((c) => c.telefono).length;
  const wrap = document.getElementById("campana-whatsapp-wrap");
  wrap.innerHTML = `
    <div class="vacante-form">
      <h3>💬 Mensaje por WhatsApp</h3>
      <p class="staff-hint">
        Escribe el mensaje una sola vez — usa <code>{nombre}</code> para insertar el nombre de pila de cada candidato
        ${campanaTestsAbiertos.length ? `y <code>{enlace}</code> para el enlace del test que elijas abajo` : ""}.
        Cada botón "Enviar" abre WhatsApp con el mensaje ya escrito para esa persona; tú confirmas el envío allí.
      </p>
      ${campanaTestSelectHTML()}
      <div class="form-field form-field-full" style="margin-bottom:10px;">
        <textarea id="campana-mensaje" style="min-height:80px;" placeholder="Hola {nombre}, te escribimos sobre tu candidatura...">Hola {nombre}, te escribimos sobre tu candidatura. ¿Podrías confirmarnos tu disponibilidad para una entrevista?</textarea>
      </div>
      <p class="staff-hint">${conTelefono} de ${candidatos.length} candidatos tienen teléfono guardado.</p>
      <div class="candidatos-grid">${candidatos.map(candidatoWhatsappRowHTML).join("")}</div>
      <div class="form-actions">
        <button type="button" id="btn-cerrar-campana" class="btn btn-ghost">Cerrar</button>
      </div>
    </div>`;
  document.getElementById("campana-mensaje").addEventListener("input", actualizarEnlacesCampana);
  document.getElementById("btn-cerrar-campana").addEventListener("click", cerrarCampanaWhatsapp);
  const testSelect = document.getElementById("campana-test");
  if (testSelect) testSelect.addEventListener("change", onCambiaTestCampana);
  actualizarEnlacesCampana();
  wrap.scrollIntoView({ behavior: "smooth", block: "start" });
}

const ESTADOS = ["pendiente", "entrevistado", "contratado", "descartado"];
const ESTADO_LABELS = { pendiente: "Pendiente", entrevistado: "Entrevistado", contratado: "Contratado", descartado: "Descartado" };

const VACANTE_ESTADO_LABELS = { abierta: "Abierta", cubierta: "Cubierta", cancelada: "Cancelada" };

function diasEntre(fechaIni, fechaFin) {
  const ini = new Date(fechaIni.replace(" ", "T"));
  const fin = fechaFin ? new Date(fechaFin.replace(" ", "T")) : new Date();
  return Math.max(0, Math.round((fin - ini) / 86400000));
}

function estadoBadgeHTML(estado) {
  const e = estado || "pendiente";
  return `<span class="badge-estado badge-${e}">${escapeHTML(ESTADO_LABELS[e] || e)}</span>`;
}

function resultadoBadgeHTML(resultado) {
  if (!resultado) return "";
  const clase = resultado.includes("No apto") ? "badge-resultado-malo" : "badge-resultado-bueno";
  return `<span class="badge-resultado ${clase}">${escapeHTML(resultado)}</span>`;
}

function estadoSelectHTML(candidatoId, estado) {
  const opciones = ESTADOS.map((e) => `<option value="${e}" ${e === (estado || "pendiente") ? "selected" : ""}>${ESTADO_LABELS[e]}</option>`).join("");
  return `<select class="candidato-estado-select" data-candidato-id="${candidatoId}">${opciones}</select>`;
}

const MESES_CORTOS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];

// "2026-07-22 13:44:24" -> "22 jul 2026, 13:44"
function fmtFechaHora(iso) {
  if (!iso) return "";
  const [fecha, hora = ""] = iso.split(" ");
  const [y, m, d] = fecha.split("-");
  const hhmm = hora.slice(0, 5);
  return `${parseInt(d, 10)} ${MESES_CORTOS[parseInt(m, 10) - 1]} ${y}${hhmm ? `, ${hhmm}` : ""}`;
}

// Agrupa una lista (ya ordenada por fecha desc) en "tandas": cada vez que se
// comparten varios candidatos de una sola acción comparten fecha exacta y
// contraparte, así que forman un grupo. claveOtro = campo que identifica a la
// otra persona (quién lo compartió, o con quién se compartió).
function agruparPorTanda(items, claveOtro) {
  const grupos = [];
  let actual = null;
  for (const it of items) {
    const clave = `${it.compartido_en}|${it[claveOtro] || ""}`;
    if (!actual || actual.clave !== clave) {
      actual = { clave, compartido_en: it.compartido_en, otro: it[claveOtro], items: [] };
      grupos.push(actual);
    }
    actual.items.push(it);
  }
  return grupos;
}

async function actualizarCandidatoInline(candidatoId, campos) {
  await fetch(`${AUTH_API_BASE}/reclutamiento/candidatos/${candidatoId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(campos),
  });
}

function candidatoCardHTML(item, permitirDejarDeCompartir) {
  const entries = Object.entries(item.datos).filter(([k]) => k.toLowerCase() !== "nombre");
  const cvBtn = item.tiene_cv
    ? `<a href="${AUTH_API_BASE}/informes/respuestas/${item.respuesta_id}/cv" target="_blank" rel="noopener" class="btn btn-primary">📄 Ver CV</a>`
    : `<span class="staff-hint">Sin CV subido todavía.</span>`;
  const candId = item.candidato_id;
  const whatsappBtn = item.telefono
    ? `<a class="btn btn-ghost" href="https://wa.me/${soloDigitos(item.telefono)}" target="_blank" rel="noopener">💬 WhatsApp</a>`
    : "";
  const estadoHTML = candId ? estadoSelectHTML(candId, item.estado) : "";
  const notasHTML = candId
    ? `<div class="candidato-notas"><textarea class="candidato-notas-input" data-candidato-id="${candId}" placeholder="Notas sobre este candidato...">${escapeHTML(item.notas || "")}</textarea></div>`
    : "";
  const fichaBtn = candId
    ? `<button type="button" class="btn btn-ghost candidato-abrir-ficha" data-candidato-id="${candId}">📋 Ver ficha completa</button>`
    : "";
  // Solo tiene sentido en "Compartidos por ti" -- deja de compartir ESTE
  // candidato con ESTE destinatario en concreto (no borra el candidato ni
  // afecta a otros a los que se lo hayas compartido). El origen del share
  // determina el endpoint: uno viene de Informes (informe_compartidos,
  // compartido_id numérico) y otro es un "compartir directo" desde
  // Reclutamiento (candidato_compartidos, compartido_id "candidato-N").
  const dejarDeCompartirBtn = permitirDejarDeCompartir
    ? `<button type="button" class="btn btn-ghost btn-dejar-compartir"
         data-directo="${String(item.compartido_id).startsWith("candidato-") ? "1" : "0"}"
         data-candidato-id="${candId}" data-respuesta-id="${item.respuesta_id ?? ""}"
         data-destinatario-id="${item.destinatario_id ?? ""}">✕ Dejar de compartir</button>`
    : "";
  const metaTxt = item.hoja ? `${item.tipo_nombre} · hoja "${item.hoja}"` : item.tipo_nombre;
  return `
    <div class="candidato-card">
      <h3>${escapeHTML(nombreCandidato(item.datos))} ${estadoHTML} ${resultadoBadgeHTML(item.test_resultado)}</h3>
      <p class="candidato-meta">${escapeHTML(metaTxt)}</p>
      <div class="candidato-datos">
        ${entries.map(([k, v]) => `<div><div class="campo-nombre">${escapeHTML(k)}</div><div>${escapeHTML(v)}</div></div>`).join("")}
      </div>
      <div class="candidato-acciones">${fichaBtn}${cvBtn}${whatsappBtn}${dejarDeCompartirBtn}</div>
      ${notasHTML}
    </div>`;
}

// Cada tanda es un <details> desplegable. `etiquetaOtro` describe la relación
// ("Compartido por" / "Compartido con") y `abierta` deja la más reciente
// abierta por defecto para que no haya que hacer clic para ver lo último.
function grupoHTML(grupo, etiquetaOtro, abierta, permitirDejarDeCompartir) {
  const n = grupo.items.length;
  return `
    <details class="tanda" ${abierta ? "open" : ""}>
      <summary class="tanda-summary">
        <span class="tanda-fecha">${escapeHTML(fmtFechaHora(grupo.compartido_en))}</span>
        <span class="tanda-meta">${n} candidato${n === 1 ? "" : "s"} · ${escapeHTML(etiquetaOtro)} <b>${escapeHTML(grupo.otro || "")}</b></span>
      </summary>
      <div class="tanda-body">
        ${grupo.items.map((it) => candidatoCardHTML(it, permitirDejarDeCompartir)).join("")}
      </div>
    </details>`;
}

function seccionHTML(titulo, grupos, etiquetaOtro, vacioMsg, permitirDejarDeCompartir) {
  if (grupos.length === 0) {
    return `<h2 class="reclu-seccion">${escapeHTML(titulo)}</h2><p class="staff-hint">${escapeHTML(vacioMsg)}</p>`;
  }
  return `<h2 class="reclu-seccion">${escapeHTML(titulo)}</h2>` +
    grupos.map((g, i) => grupoHTML(g, etiquetaOtro, i === 0, permitirDejarDeCompartir)).join("");
}

async function dejarDeCompartirClick(btn) {
  if (!confirm("¿Dejar de compartir este candidato? La persona ya no lo verá en su Reclutamiento.")) return;
  const url = btn.dataset.directo === "1"
    ? `${AUTH_API_BASE}/reclutamiento/candidatos/${btn.dataset.candidatoId}/compartir/${btn.dataset.destinatarioId}`
    : `${AUTH_API_BASE}/informes/compartir/${btn.dataset.respuestaId}/${btn.dataset.destinatarioId}`;
  btn.disabled = true;
  const res = await fetch(url, { method: "DELETE" });
  if (!res.ok) {
    alert("No se pudo dejar de compartir. Inténtalo de nuevo.");
    btn.disabled = false;
    return;
  }
  await loadCompartidos();
}

function wireCompartidosInteractivos(wrap) {
  wrap.querySelectorAll(".candidato-estado-select").forEach((el) => {
    el.addEventListener("change", () => actualizarCandidatoInline(el.dataset.candidatoId, { estado: el.value }));
  });
  wrap.querySelectorAll(".candidato-notas-input").forEach((el) => {
    el.addEventListener("blur", () => actualizarCandidatoInline(el.dataset.candidatoId, { notas: el.value }));
  });
  wrap.querySelectorAll(".candidato-abrir-ficha").forEach((el) => {
    el.addEventListener("click", () => abrirEdicionCandidato(el.dataset.candidatoId));
  });
  wrap.querySelectorAll(".btn-dejar-compartir").forEach((el) => {
    el.addEventListener("click", () => dejarDeCompartirClick(el));
  });
}

async function loadCompartidos() {
  const wrap = document.getElementById("compartidos-list");
  const [conmigo, porMi] = await Promise.all([
    fetch(`${AUTH_API_BASE}/informes/compartidos?empresa=${EMPRESA}`).then((r) => (r.ok ? r.json() : [])),
    fetch(`${AUTH_API_BASE}/informes/compartidos-por-mi?empresa=${EMPRESA}`).then((r) => (r.ok ? r.json() : [])),
  ]);

  const gruposConmigo = agruparPorTanda(conmigo, "compartido_por");
  const gruposPorMi = agruparPorTanda(porMi, "destinatario_nombre");

  let html = seccionHTML(
    "Compartidos conmigo",
    gruposConmigo,
    "compartido por",
    "Todavía no te han compartido ningún candidato.",
    false
  );

  // La sección "Compartidos por ti" solo tiene sentido enseñarla si esta
  // persona ha compartido algo alguna vez (a un gerente no le aparecerá).
  if (gruposPorMi.length > 0) {
    html += seccionHTML("Compartidos por ti", gruposPorMi, "compartido con", "", true);
  }

  wrap.innerHTML = html;
  wireCompartidosInteractivos(wrap);
}

// ---------------------------------------------------------------------
// Vacantes: agrupan candidatos bajo una solicitud de reclutamiento concreta
// (puesto + centro), con fecha de solicitud y estado (abierta/cubierta/
// cancelada + fecha de cierre) para poder medir cuánto lleva abierta o
// cuánto tardó en cubrirse. Un candidato puede no tener vacante (candidatura
// espontánea, o los que llegan compartidos desde Informes).
// ---------------------------------------------------------------------

let vacantesCache = []; // filtradas según vacantes-filtro-estado (para la grid)
let vacantesTodasCache = []; // sin filtrar (para el desplegable de asignación y el filtro de candidatos)
let vacanteEditando = null;

function vacanteMiniCardHTML(v) {
  const filtroActual = document.getElementById("candidatos-filtro-vacante").value;
  const activa = filtroActual === String(v.id);
  const dias = diasEntre(v.fecha_solicitud, v.fecha_cierre);
  const diasTxt = v.estado === "abierta"
    ? `${dias} día${dias === 1 ? "" : "s"} abierta`
    : `${dias} día${dias === 1 ? "" : "s"} hasta ${v.estado === "cubierta" ? "cubrirla" : "cancelarla"}`;
  return `
    <div class="vacante-mini-card ${activa ? "activa" : ""}" data-vacante-id="${v.id}">
      <h4>${escapeHTML(v.puesto)} <span class="badge-vacante-estado badge-${v.estado}">${VACANTE_ESTADO_LABELS[v.estado]}</span></h4>
      <p>${escapeHTML(v.centro || "")}</p>
      <p>${diasTxt} · ${v.candidato_count} candidato${v.candidato_count === 1 ? "" : "s"}</p>
    </div>`;
}

function renderVacantesGrid() {
  const grid = document.getElementById("vacantes-grid");
  grid.innerHTML = vacantesCache.length
    ? vacantesCache.map(vacanteMiniCardHTML).join("")
    : `<p class="staff-hint">No hay vacantes con este filtro.</p>`;
  grid.querySelectorAll(".vacante-mini-card").forEach((card) => {
    card.addEventListener("click", () => abrirEdicionVacante(Number(card.dataset.vacanteId)));
  });
}

function actualizarSelectFiltroVacante() {
  const select = document.getElementById("candidatos-filtro-vacante");
  const valorPrevio = select.value;
  select.innerHTML = `
    <option value="">Todos los candidatos</option>
    <option value="sin_vacante">Sin vacante asignada</option>
    ${vacantesTodasCache.map((v) => `<option value="${v.id}">${escapeHTML(v.puesto)}${v.centro ? ` · ${escapeHTML(v.centro)}` : ""}</option>`).join("")}
  `;
  if (Array.from(select.options).some((o) => o.value === valorPrevio)) select.value = valorPrevio;
}

async function refreshVacantes() {
  const estado = document.getElementById("vacantes-filtro-estado").value;
  const paramsFiltradas = new URLSearchParams({ empresa: EMPRESA });
  if (estado) paramsFiltradas.set("estado", estado);
  const [filtradas, todas] = await Promise.all([
    fetch(`${AUTH_API_BASE}/reclutamiento/vacantes?${paramsFiltradas}`).then((r) => (r.ok ? r.json() : [])),
    fetch(`${AUTH_API_BASE}/reclutamiento/vacantes?empresa=${EMPRESA}`).then((r) => (r.ok ? r.json() : [])),
  ]);
  vacantesCache = filtradas;
  vacantesTodasCache = todas;
  renderVacantesGrid();
  actualizarSelectFiltroVacante();
}

function vacanteFormHTML() {
  const v = vacanteEditando;
  return `
    <div class="vacante-form">
      <h3>${v ? "Editar vacante" : "Nueva vacante"}</h3>
      <div class="form-grid">
        <div class="form-field"><label>Puesto</label><input type="text" id="vacante-puesto" value="${v ? escapeHTML(v.puesto) : ""}" placeholder="p.ej. Ayudante de Cocina"></div>
        <div class="form-field"><label>Centro / ubicación</label><input type="text" id="vacante-centro" value="${v ? escapeHTML(v.centro || "") : ""}" placeholder="p.ej. SAONA Madnum"></div>
        ${v ? `<div class="form-field">
          <label>Estado</label>
          <select id="vacante-estado-form">
            ${Object.entries(VACANTE_ESTADO_LABELS).map(([val, label]) => `<option value="${val}" ${v.estado === val ? "selected" : ""}>${label}</option>`).join("")}
          </select>
        </div>` : ""}
        <div class="form-field form-field-full"><label>Notas</label><textarea id="vacante-notas" style="min-height:50px;">${v ? escapeHTML(v.notas || "") : ""}</textarea></div>
      </div>
      ${v ? `<p class="staff-hint">Solicitada el ${escapeHTML(fmtFechaHora(v.fecha_solicitud))}${v.fecha_cierre ? ` · cerrada el ${escapeHTML(fmtFechaHora(v.fecha_cierre))}` : ""}</p>` : ""}
      <div class="form-actions">
        <button type="button" id="btn-guardar-vacante" class="btn btn-primary">Guardar</button>
        ${v && v.candidatos.length ? `<button type="button" id="btn-whatsapp-vacante" class="btn btn-ghost">💬 Mensaje a los candidatos de esta vacante</button>` : ""}
        ${v ? `<button type="button" id="btn-eliminar-vacante" class="btn btn-ghost">Eliminar vacante</button>` : ""}
        <button type="button" id="btn-cerrar-vacante-form" class="btn btn-ghost">Cancelar</button>
      </div>
    </div>`;
}

function renderVacanteForm() {
  const wrap = document.getElementById("vacante-form-wrap");
  wrap.innerHTML = vacanteFormHTML();
  document.getElementById("btn-guardar-vacante").addEventListener("click", guardarVacante);
  document.getElementById("btn-cerrar-vacante-form").addEventListener("click", cerrarVacanteForm);
  if (vacanteEditando) {
    document.getElementById("btn-eliminar-vacante").addEventListener("click", eliminarVacanteActual);
    const btnWhatsapp = document.getElementById("btn-whatsapp-vacante");
    if (btnWhatsapp) btnWhatsapp.addEventListener("click", () => abrirCampanaWhatsapp(vacanteEditando.candidatos));
  }
  wrap.scrollIntoView({ behavior: "smooth", block: "start" });
}

function cerrarVacanteForm() {
  vacanteEditando = null;
  document.getElementById("vacante-form-wrap").innerHTML = "";
}

async function guardarVacante() {
  const puesto = document.getElementById("vacante-puesto").value.trim();
  if (!puesto) {
    alert("Escribe el puesto de la vacante.");
    return;
  }
  const centro = document.getElementById("vacante-centro").value.trim() || null;
  const notas = document.getElementById("vacante-notas").value.trim() || null;
  let res;
  if (vacanteEditando) {
    const estado = document.getElementById("vacante-estado-form").value;
    res = await fetch(`${AUTH_API_BASE}/reclutamiento/vacantes/${vacanteEditando.id}`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ puesto, centro, notas, estado }),
    });
  } else {
    res = await fetch(`${AUTH_API_BASE}/reclutamiento/vacantes`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ empresa: EMPRESA, puesto, centro, notas }),
    });
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    alert(err.detail || `No se pudo guardar la vacante (error ${res.status}).`);
    return;
  }
  cerrarVacanteForm();
  await refreshVacantes();
}

async function eliminarVacanteActual() {
  if (!vacanteEditando) return;
  if (!confirm(`¿Eliminar la vacante "${vacanteEditando.puesto}"? Los candidatos ya creados no se borran, quedarán sin vacante asignada.`)) return;
  const res = await fetch(`${AUTH_API_BASE}/reclutamiento/vacantes/${vacanteEditando.id}`, { method: "DELETE" });
  if (!res.ok) {
    alert(`No se pudo eliminar la vacante (error ${res.status}).`);
    return;
  }
  cerrarVacanteForm();
  await refreshVacantes();
  await loadCandidatos();
}

function abrirNuevaVacante() {
  vacanteEditando = null;
  renderVacanteForm();
}

async function abrirEdicionVacante(vacanteId) {
  const vacante = await fetch(`${AUTH_API_BASE}/reclutamiento/vacantes/${vacanteId}`).then((r) => r.json());
  vacanteEditando = vacante;
  renderVacanteForm();
  // También filtra la lista de candidatos por esta vacante, para verlos
  // juntos sin tener que buscar manualmente.
  document.getElementById("candidatos-filtro-vacante").value = String(vacanteId);
  renderVacantesGrid();
  await loadCandidatos();
}

// ---------------------------------------------------------------------
// Base de candidatos: alta manual/por CV, listado con filtros, ficha
// editable. Solo visible para quien tiene el módulo Informes (mismo check
// que hace home.js para la tarjeta de Informes).
// ---------------------------------------------------------------------

const CAMPOS_FORM = [
  ["nombre_completo", "Nombre completo"],
  ["telefono", "Teléfono"],
  ["email", "Email"],
  ["direccion", "Dirección"],
  ["fecha_nacimiento", "Fecha de nacimiento"],
  ["dni", "DNI/NIE"],
  ["puesto_solicitado", "Puesto al que aplica"],
  ["fecha_solicitud", "Fecha de solicitud"],
  ["disponibilidad", "Disponibilidad"],
  ["formacion", "Formación", true],
  ["experiencia", "Experiencia", true],
];

let candidatoEditando = null; // null = alta nueva; objeto = editando existente
let extraFieldsState = {};

function vacanteSelectHTML(selectedId, elementId) {
  const opciones = vacantesTodasCache
    .map((v) => {
      const sufijo = v.estado !== "abierta" ? ` (${VACANTE_ESTADO_LABELS[v.estado].toLowerCase()})` : "";
      return `<option value="${v.id}" ${v.id === selectedId ? "selected" : ""}>${escapeHTML(v.puesto)}${v.centro ? ` · ${escapeHTML(v.centro)}` : ""}${sufijo}</option>`;
    })
    .join("");
  return `<select id="${elementId}"><option value="">— Sin vacante —</option>${opciones}</select>`;
}

// Al abrir "Nuevo candidato" mientras el filtro de vacante está fijado en
// una concreta, se pre-selecciona esa misma vacante (lo normal es estar
// añadiendo candidatos para una vacante que ya se está mirando).
function vacantePreseleccionada() {
  const valor = document.getElementById("candidatos-filtro-vacante").value;
  return valor && valor !== "sin_vacante" ? Number(valor) : null;
}

function campoFormHTML([key, label, textarea]) {
  const valor = candidatoEditando ? escapeHTML(candidatoEditando[key] || "") : "";
  const full = textarea ? " form-field-full" : "";
  const input = textarea
    ? `<textarea class="candidato-input" data-campo="${key}" style="min-height:70px;">${valor}</textarea>`
    : `<input type="text" class="candidato-input" data-campo="${key}" value="${valor}">`;
  return `<div class="form-field${full}"><label>${escapeHTML(label)}</label>${input}</div>`;
}

function extraEditorRowHTML(key, value) {
  return `
    <div class="extra-editor-row">
      <input type="text" class="extra-key" placeholder="Campo (p.ej. Idiomas)" value="${escapeHTML(key)}">
      <input type="text" class="extra-value" placeholder="Valor" value="${escapeHTML(value)}">
      <button type="button" class="btn-mini extra-quitar">✕</button>
    </div>`;
}

function renderExtraEditor() {
  const cont = document.getElementById("extra-editor-filas");
  if (!cont) return;
  const entradas = Object.entries(extraFieldsState);
  cont.innerHTML = entradas.map(([k, v]) => extraEditorRowHTML(k, v)).join("") || "";
  cont.querySelectorAll(".extra-quitar").forEach((btn) => {
    btn.addEventListener("click", () => {
      btn.closest(".extra-editor-row").remove();
    });
  });
}

function leerExtraFieldsDelForm() {
  const extra = {};
  document.querySelectorAll("#extra-editor-filas .extra-editor-row").forEach((row) => {
    const k = row.querySelector(".extra-key").value.trim();
    const v = row.querySelector(".extra-value").value.trim();
    if (k) extra[k] = v;
  });
  return extra;
}

function renderForm() {
  const wrap = document.getElementById("form-wrap");
  const esEdicion = !!candidatoEditando;
  extraFieldsState = esEdicion ? { ...(candidatoEditando.extra_fields || {}) } : {};

  const subirCvHTML = esEdicion ? "" : `
    <div class="subir-cv-row">
      <input type="file" id="input-cv-nuevo" accept=".pdf">
      <button type="button" id="btn-extraer-cv" class="btn btn-ghost">📄 Subir CV y rellenar automáticamente</button>
    </div>
    <p class="staff-hint" style="margin-top:-6px;">Puedes subir el CV de 1 candidato o un PDF con varios CVs juntos (hasta unos 50) — se detectan todos automáticamente.</p>
    <div id="extraccion-aviso-wrap"></div>
    <div id="revision-multiple-wrap"></div>`;

  const resultadoTestHTML = esEdicion && candidatoEditando.informe_tipo_clave
    ? (() => {
        const params = new URLSearchParams({
          tipo: candidatoEditando.informe_tipo_clave,
          hoja: candidatoEditando.informe_hoja || "",
          empresa: candidatoEditando.informe_empresa || "kk",
        });
        return `<p class="staff-hint"><a href="/informes.html?${params.toString()}" target="_blank" rel="noopener">📊 Ver resultado del test</a> ${resultadoBadgeHTML(candidatoEditando.test_resultado)}</p>`;
      })()
    : "";

  const archivosHTML = esEdicion && candidatoEditando.archivos.length
    ? `<div class="archivos-lista">${candidatoEditando.archivos.map((a) =>
        `<a href="${AUTH_API_BASE}/reclutamiento/candidatos/${candidatoEditando.id}/archivos/${a.id}" target="_blank" rel="noopener">📄 ${escapeHTML(a.nombre_original)}</a>`
      ).join("")}</div>`
    : "";

  const agregarArchivoHTML = esEdicion ? `
    <div class="subir-cv-row">
      <input type="file" id="input-archivo-extra">
      <button type="button" id="btn-agregar-archivo" class="btn btn-ghost">＋ Añadir fichero</button>
    </div>` : "";

  wrap.innerHTML = `
    <div class="candidato-form">
      <h3>${esEdicion ? "Editar candidato" : "Nuevo candidato"}</h3>
      ${resultadoTestHTML}
      ${subirCvHTML}
      <div id="single-candidato-wrap">
        <div class="form-grid">
          <div class="form-field">
            <label>Vacante asociada</label>
            ${vacanteSelectHTML(esEdicion ? candidatoEditando.vacante_id : vacantePreseleccionada(), "candidato-vacante-form")}
          </div>
          ${CAMPOS_FORM.map(campoFormHTML).join("")}
          ${esEdicion ? `
            <div class="form-field">
              <label>Estado</label>
              <select id="candidato-estado-form">
                ${ESTADOS.map((e) => `<option value="${e}" ${e === candidatoEditando.estado ? "selected" : ""}>${ESTADO_LABELS[e]}</option>`).join("")}
              </select>
            </div>` : ""}
          <div class="form-field form-field-full">
            <label>Notas</label>
            <textarea id="candidato-notas-form" style="min-height:60px;">${esEdicion ? escapeHTML(candidatoEditando.notas || "") : ""}</textarea>
          </div>
        </div>
        <div class="form-field form-field-full" style="margin-bottom:12px;">
          <label>Otros datos (idiomas, carnet de conducir, certificaciones...)</label>
          <div class="extra-editor" id="extra-editor-filas"></div>
          <button type="button" id="btn-extra-agregar" class="btn-mini" style="margin-top:6px;">＋ Añadir campo</button>
        </div>
        ${archivosHTML}
        ${agregarArchivoHTML}
        <div class="form-actions">
          <button type="button" id="btn-guardar-candidato" class="btn btn-primary">Guardar</button>
          ${esEdicion ? `<a class="btn btn-ghost" id="btn-whatsapp-candidato" href="https://wa.me/${soloDigitos(candidatoEditando.telefono)}" target="_blank" rel="noopener" ${candidatoEditando.telefono ? "" : "hidden"}>💬 WhatsApp</a>` : ""}
          ${esEdicion ? `<button type="button" id="btn-eliminar-candidato" class="btn btn-ghost">Eliminar</button>` : ""}
          <button type="button" id="btn-cerrar-form" class="btn btn-ghost">Cancelar</button>
        </div>
      </div>
    </div>`;

  renderExtraEditor();
  document.getElementById("btn-extra-agregar").addEventListener("click", () => {
    const cont = document.getElementById("extra-editor-filas");
    cont.insertAdjacentHTML("beforeend", extraEditorRowHTML("", ""));
    cont.querySelectorAll(".extra-quitar").forEach((btn) => {
      btn.onclick = () => btn.closest(".extra-editor-row").remove();
    });
  });
  document.getElementById("btn-cerrar-form").addEventListener("click", cerrarForm);
  document.getElementById("btn-guardar-candidato").addEventListener("click", guardarCandidato);
  if (esEdicion) {
    document.getElementById("btn-eliminar-candidato").addEventListener("click", eliminarCandidatoActual);
  } else {
    document.getElementById("btn-extraer-cv").addEventListener("click", extraerCvYRellenar);
  }
  if (agregarArchivoHTML) {
    document.getElementById("btn-agregar-archivo").addEventListener("click", agregarArchivoAlCandidato);
  }
  wrap.scrollIntoView({ behavior: "smooth", block: "start" });
}

function cerrarForm() {
  candidatoEditando = null;
  document.getElementById("form-wrap").innerHTML = "";
}

function avisoExtraccionHTML(metodo, n) {
  const clase = metodo === "gemini" ? "gemini" : "local";
  const texto = metodo === "gemini"
    ? `✓ ${n} candidato${n === 1 ? "" : "s"} extraído${n === 1 ? "" : "s"} con IA. Revisa los datos antes de guardar.`
    : `Se usó el método local (sin IA) para leer el PDF${n > 1 ? ` (${n} candidatos detectados)` : ""}. Revisa los datos con más atención antes de guardar.`;
  return `<p class="extraccion-aviso ${clase}">${escapeHTML(texto)}</p>`;
}

function rellenarFormConCandidato(campos) {
  for (const [campo, valor] of Object.entries(campos)) {
    if (campo === "extra_fields") continue;
    const el = document.querySelector(`.candidato-input[data-campo="${campo}"]`);
    if (el) el.value = valor;
  }
  extraFieldsState = { ...extraFieldsState, ...(campos.extra_fields || {}) };
  renderExtraEditor();
}

let candidatosPorRevisar = [];

// Cuando el PDF trae varios candidatos, no tiene sentido rellenar el
// formulario de "un candidato" — se oculta y se muestra en su lugar una
// lista de revisión con checkboxes para crear varias fichas de golpe. El CV
// original (por lotes) no se adjunta a cada ficha individual: si hace falta
// el CV de uno en concreto, se puede añadir después desde su propia ficha.
function renderRevisionMultiple(candidatos) {
  candidatosPorRevisar = candidatos;
  document.getElementById("single-candidato-wrap").hidden = true;
  const wrap = document.getElementById("revision-multiple-wrap");
  wrap.innerHTML = `
    <div class="form-field" style="margin-bottom:10px; max-width:340px;">
      <label>Asignar todos a la vacante</label>
      ${vacanteSelectHTML(vacantePreseleccionada(), "revision-vacante-select")}
    </div>
    <p class="staff-hint" id="revision-contador"></p>
    <div class="candidatos-grid">
      ${candidatos
        .map(
          (c, i) => `
        <div class="candidato-mini-card" style="cursor:default;">
          <h4><label style="display:flex; align-items:center; gap:6px; cursor:pointer;">
            <input type="checkbox" class="revision-multiple-check" data-idx="${i}" checked>
            ${escapeHTML(c.nombre_completo || `Candidato ${i + 1}`)}
          </label></h4>
          <p>${escapeHTML(c.puesto_solicitado || "")}</p>
          <p>${escapeHTML([c.telefono, c.email].filter(Boolean).join(" · "))}</p>
        </div>`
        )
        .join("")}
    </div>
    <div class="form-actions">
      <button type="button" id="btn-crear-multiples" class="btn btn-primary">Crear candidatos seleccionados</button>
      <button type="button" id="btn-cancelar-multiples" class="btn btn-ghost">Cancelar</button>
    </div>`;
  document.getElementById("btn-crear-multiples").addEventListener("click", crearCandidatosMultiples);
  document.getElementById("btn-cancelar-multiples").addEventListener("click", cerrarForm);
  const checks = wrap.querySelectorAll(".revision-multiple-check");
  const actualizarContador = () => {
    const marcados = wrap.querySelectorAll(".revision-multiple-check:checked").length;
    document.getElementById("revision-contador").textContent = `${marcados} seleccionados de ${checks.length} detectados`;
  };
  checks.forEach((chk) => chk.addEventListener("change", actualizarContador));
  actualizarContador();
}

async function crearCandidatosMultiples() {
  const seleccionados = Array.from(document.querySelectorAll(".revision-multiple-check:checked"))
    .map((el) => candidatosPorRevisar[Number(el.dataset.idx)]);
  if (seleccionados.length === 0) {
    alert("Selecciona al menos un candidato.");
    return;
  }
  const vacanteValor = document.getElementById("revision-vacante-select").value;
  const vacante_id = vacanteValor ? Number(vacanteValor) : null;
  const btn = document.getElementById("btn-crear-multiples");
  btn.disabled = true;
  btn.textContent = "Creando...";
  let errores = 0;
  for (const campos of seleccionados) {
    const res = await fetch(`${AUTH_API_BASE}/reclutamiento/candidatos`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...campos, empresa: EMPRESA, vacante_id }),
    });
    if (!res.ok) errores++;
  }
  if (errores > 0) {
    alert(`No se pudieron crear ${errores} de ${seleccionados.length} candidatos. Revisa la conexión e inténtalo de nuevo.`);
    btn.disabled = false;
    btn.textContent = "Crear candidatos seleccionados";
    return;
  }
  cerrarForm();
  await refreshVacantes();
  await loadCandidatos();
}

async function extraerCvYRellenar() {
  const input = document.getElementById("input-cv-nuevo");
  const avisoWrap = document.getElementById("extraccion-aviso-wrap");
  if (!input.files.length) {
    avisoWrap.innerHTML = `<p class="extraccion-aviso local">Selecciona primero un PDF.</p>`;
    return;
  }
  const formData = new FormData();
  formData.append("file", input.files[0]);
  avisoWrap.innerHTML = `<p class="staff-hint">Leyendo el CV...</p>`;
  const resp = await fetch(`${AUTH_API_BASE}/reclutamiento/candidatos/extraer-cv`, { method: "POST", body: formData });
  if (!resp.ok) {
    avisoWrap.innerHTML = `<p class="extraccion-aviso local">No se pudo leer el CV. Rellena los datos a mano.</p>`;
    return;
  }
  const data = await resp.json();
  const candidatos = data.candidatos || [];
  if (candidatos.length === 0) {
    avisoWrap.innerHTML = `<p class="extraccion-aviso local">No se reconoció ningún candidato en el PDF. Rellena los datos a mano.</p>`;
    return;
  }
  avisoWrap.innerHTML = avisoExtraccionHTML(data.metodo, candidatos.length);
  if (candidatos.length === 1) {
    rellenarFormConCandidato(candidatos[0]);
    input.dataset.pendingUpload = "1";
  } else {
    renderRevisionMultiple(candidatos);
  }
}

async function guardarCandidato() {
  const campos = {};
  document.querySelectorAll(".candidato-input").forEach((el) => {
    campos[el.dataset.campo] = el.value.trim() || null;
  });
  campos.notas = document.getElementById("candidato-notas-form").value.trim() || null;
  campos.extra_fields = leerExtraFieldsDelForm();
  const vacanteValor = document.getElementById("candidato-vacante-form").value;
  campos.vacante_id = vacanteValor ? Number(vacanteValor) : null;

  let candidatoId;
  if (candidatoEditando) {
    campos.estado = document.getElementById("candidato-estado-form").value;
    const res = await fetch(`${AUTH_API_BASE}/reclutamiento/candidatos/${candidatoEditando.id}`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(campos),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      alert(err.detail || `No se pudo guardar el candidato (error ${res.status}).`);
      return;
    }
    candidatoId = candidatoEditando.id;
  } else {
    campos.empresa = EMPRESA;
    const resp = await fetch(`${AUTH_API_BASE}/reclutamiento/candidatos`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(campos),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      alert(err.detail || `No se pudo crear el candidato (error ${resp.status}).`);
      return;
    }
    const data = await resp.json();
    candidatoId = data.id;
    const inputCv = document.getElementById("input-cv-nuevo");
    if (inputCv && inputCv.files.length) {
      const formData = new FormData();
      formData.append("file", inputCv.files[0]);
      await fetch(`${AUTH_API_BASE}/reclutamiento/candidatos/${candidatoId}/archivos`, { method: "POST", body: formData });
    }
  }
  cerrarForm();
  await refreshVacantes();
  await loadCandidatos();
}

async function eliminarCandidatoActual() {
  if (!candidatoEditando) return;
  if (!confirm(`¿Seguro que quieres eliminar a ${candidatoEditando.nombre_completo || "este candidato"}? Esta acción no se puede deshacer.`)) return;
  const res = await fetch(`${AUTH_API_BASE}/reclutamiento/candidatos/${candidatoEditando.id}`, { method: "DELETE" });
  if (!res.ok) {
    alert(`No se pudo eliminar el candidato (error ${res.status}).`);
    return;
  }
  cerrarForm();
  await loadCandidatos();
}

async function agregarArchivoAlCandidato() {
  const input = document.getElementById("input-archivo-extra");
  if (!candidatoEditando || !input.files.length) return;
  const formData = new FormData();
  formData.append("file", input.files[0]);
  await fetch(`${AUTH_API_BASE}/reclutamiento/candidatos/${candidatoEditando.id}/archivos`, { method: "POST", body: formData });
  const actualizado = await fetch(`${AUTH_API_BASE}/reclutamiento/candidatos/${candidatoEditando.id}`).then((r) => r.json());
  candidatoEditando = actualizado;
  renderForm();
}

// Selección múltiple: activada bajo demanda para armar una campaña de
// WhatsApp con un grupo elegido a mano (independiente de una vacante
// concreta). Mientras está activa, hacer clic en una ficha la selecciona en
// vez de abrirla para editar.
let modoSeleccionCandidatos = false;
let candidatosSeleccionadosIds = new Set();
let ultimosCandidatosCargados = [];
let candidatosFiltroEstado = "";
let usuariosParaCompartirCandidatos = [];

function candidatoMiniCardHTML(c) {
  const linea2 = [c.telefono, c.email].filter(Boolean).join(" · ");
  const vacante = vacantesTodasCache.find((v) => v.id === c.vacante_id);
  const vacanteTxt = vacante ? `📁 ${vacante.puesto}${vacante.centro ? ` · ${vacante.centro}` : ""}` : "Sin vacante asignada";
  const seleccionada = modoSeleccionCandidatos && candidatosSeleccionadosIds.has(c.id);
  const checkbox = modoSeleccionCandidatos ? `<input type="checkbox" ${seleccionada ? "checked" : ""} style="margin-right:4px;">` : "";
  return `
    <div class="candidato-mini-card ${seleccionada ? "seleccionada" : ""}" data-candidato-id="${c.id}">
      <h4>${checkbox}${escapeHTML(c.nombre_completo || "(sin nombre)")} ${estadoBadgeHTML(c.estado)} ${resultadoBadgeHTML(c.test_resultado)}</h4>
      <p>${escapeHTML(c.puesto_solicitado || "")}</p>
      <p>${escapeHTML(linea2)}</p>
      <p style="color:var(--text-muted);">${escapeHTML(vacanteTxt)}</p>
    </div>`;
}

function actualizarBotonWhatsappSeleccionados() {
  const barra = document.getElementById("candidatos-seleccion-bar");
  const btnWhatsapp = document.getElementById("btn-whatsapp-seleccionados");
  const btnMailto = document.getElementById("btn-mailto-seleccionados");
  const btnCompartir = document.getElementById("btn-compartir-seleccionados");
  const btnSeleccionarTodos = document.getElementById("btn-seleccionar-todos-candidatos");
  const btnQuitarSeleccion = document.getElementById("btn-deseleccionar-todos-candidatos");
  const estadoMasivo = document.getElementById("candidatos-estado-masivo");
  const contador = document.getElementById("candidatos-seleccion-contador");
  const n = candidatosSeleccionadosIds.size;
  barra.hidden = !modoSeleccionCandidatos;
  if (!modoSeleccionCandidatos) return;
  contador.textContent = `${n} candidato${n === 1 ? "" : "s"} seleccionado${n === 1 ? "" : "s"}`;
  const sinSeleccion = n === 0;
  btnWhatsapp.hidden = sinSeleccion;
  btnWhatsapp.textContent = `💬 Mensaje por WhatsApp (${n})`;
  btnMailto.hidden = sinSeleccion;
  btnMailto.textContent = `✉ Enviar email (${n})`;
  btnCompartir.disabled = sinSeleccion;
  estadoMasivo.disabled = sinSeleccion;
  // "Seleccionar todos" toma TODOS los candidatos cargados actualmente en la
  // pantalla (respetando el filtro de vacante/búsqueda aplicado), no solo
  // los que ya se hubieran marcado a mano uno a uno.
  btnSeleccionarTodos.hidden = n >= ultimosCandidatosCargados.length;
  btnQuitarSeleccion.hidden = sinSeleccion;
}

function seleccionarTodosCandidatos() {
  ultimosCandidatosCargados.forEach((c) => candidatosSeleccionadosIds.add(c.id));
  actualizarBotonWhatsappSeleccionados();
  renderCandidatosGrid();
}

function deseleccionarTodosCandidatos() {
  candidatosSeleccionadosIds.clear();
  actualizarBotonWhatsappSeleccionados();
  renderCandidatosGrid();
}

function toggleModoSeleccion() {
  modoSeleccionCandidatos = !modoSeleccionCandidatos;
  candidatosSeleccionadosIds.clear();
  document.getElementById("btn-modo-seleccion").textContent = modoSeleccionCandidatos ? "✕ Cancelar selección" : "☑ Selección múltiple";
  actualizarBotonWhatsappSeleccionados();
  renderCandidatosGrid();
}

async function cambiarEstadoSeleccionados(estado) {
  if (!estado || candidatosSeleccionadosIds.size === 0) return;
  const ids = [...candidatosSeleccionadosIds];
  await fetch(`${AUTH_API_BASE}/reclutamiento/candidatos/estado-multiple`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ candidato_ids: ids, estado }),
  });
  document.getElementById("candidatos-estado-masivo").value = "";
  toggleModoSeleccion();
  await loadCandidatos();
}

async function abrirModalCompartirCandidatos() {
  if (candidatosSeleccionadosIds.size === 0) return;
  if (usuariosParaCompartirCandidatos.length === 0) {
    usuariosParaCompartirCandidatos = await fetch(`${AUTH_API_BASE}/informes/usuarios-para-compartir`).then((r) => r.json());
  }
  const select = document.getElementById("compartir-candidatos-usuario-select");
  select.innerHTML = usuariosParaCompartirCandidatos
    .map((u) => `<option value="${u.id}">${escapeHTML(u.nombre)} (${escapeHTML(u.username)} · ${escapeHTML(u.rol)})</option>`)
    .join("");
  document.getElementById("compartir-candidatos-modal").classList.add("visible");
}

function cerrarModalCompartirCandidatos() {
  document.getElementById("compartir-candidatos-modal").classList.remove("visible");
}

async function confirmarCompartirCandidatos() {
  const usuarioId = Number(document.getElementById("compartir-candidatos-usuario-select").value);
  const ids = [...candidatosSeleccionadosIds];
  if (!usuarioId || ids.length === 0) return;
  await fetch(`${AUTH_API_BASE}/reclutamiento/candidatos/compartir`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ candidato_ids: ids, usuario_id: usuarioId }),
  });
  cerrarModalCompartirCandidatos();
  toggleModoSeleccion();
}

async function renderCandidatosTabs() {
  const q = document.getElementById("candidatos-buscar").value.trim();
  const vacanteFiltro = document.getElementById("candidatos-filtro-vacante").value;
  const params = new URLSearchParams({ empresa: EMPRESA });
  if (q) params.set("q", q);
  if (vacanteFiltro === "sin_vacante") params.set("sin_vacante", "true");
  else if (vacanteFiltro) params.set("vacante_id", vacanteFiltro);
  const conteo = await fetch(`${AUTH_API_BASE}/reclutamiento/candidatos/conteo-por-estado?${params}`).then((r) => (r.ok ? r.json() : {}));
  const total = Object.values(conteo).reduce((a, b) => a + b, 0);
  const tabs = document.getElementById("candidatos-tabs");
  const pestañas = [{ valor: "", etiqueta: "Todos", n: total }, ...ESTADOS.map((e) => ({ valor: e, etiqueta: ESTADO_LABELS[e], n: conteo[e] || 0 }))];
  tabs.innerHTML = pestañas
    .map((p) => `
      <button type="button" class="candidatos-tab ${p.valor === candidatosFiltroEstado ? "activa" : ""}" data-estado="${p.valor}">
        ${escapeHTML(p.etiqueta)} <span class="candidatos-tab-count">${p.n}</span>
      </button>`)
    .join("");
  tabs.querySelectorAll(".candidatos-tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      candidatosFiltroEstado = btn.dataset.estado;
      loadCandidatos();
    });
  });
}

function renderCandidatosGrid() {
  const grid = document.getElementById("candidatos-grid");
  grid.innerHTML = ultimosCandidatosCargados.length
    ? ultimosCandidatosCargados.map(candidatoMiniCardHTML).join("")
    : `<p class="staff-hint">Todavía no hay candidatos en la base de datos.</p>`;
  grid.querySelectorAll(".candidato-mini-card").forEach((card) => {
    card.addEventListener("click", () => {
      const id = Number(card.dataset.candidatoId);
      if (modoSeleccionCandidatos) {
        if (candidatosSeleccionadosIds.has(id)) candidatosSeleccionadosIds.delete(id);
        else candidatosSeleccionadosIds.add(id);
        actualizarBotonWhatsappSeleccionados();
        renderCandidatosGrid();
      } else {
        abrirEdicionCandidato(card.dataset.candidatoId);
      }
    });
  });
}

async function loadCandidatos() {
  const q = document.getElementById("candidatos-buscar").value.trim();
  const vacanteFiltro = document.getElementById("candidatos-filtro-vacante").value;
  const params = new URLSearchParams({ empresa: EMPRESA });
  if (q) params.set("q", q);
  if (candidatosFiltroEstado) params.set("estado", candidatosFiltroEstado);
  if (vacanteFiltro === "sin_vacante") params.set("sin_vacante", "true");
  else if (vacanteFiltro) params.set("vacante_id", vacanteFiltro);
  ultimosCandidatosCargados = await fetch(`${AUTH_API_BASE}/reclutamiento/candidatos?${params}`).then((r) => (r.ok ? r.json() : []));
  renderCandidatosGrid();
  renderCandidatosTabs();
}

function abrirCampanaWhatsappSeleccionados() {
  const candidatos = ultimosCandidatosCargados.filter((c) => candidatosSeleccionadosIds.has(c.id));
  abrirCampanaWhatsapp(candidatos);
}

// Igual que el recordatorio de Entrevista de Salida: nunca se envía nada
// desde el servidor, se arma un enlace mailto: con todos los correos en
// copia oculta (bcc) y se abre el cliente de correo del propio usuario, que
// es quien de verdad manda el email desde su cuenta.
function abrirMailtoSeleccionados() {
  const candidatos = ultimosCandidatosCargados.filter((c) => candidatosSeleccionadosIds.has(c.id));
  const conEmail = candidatos.filter((c) => c.email);
  if (conEmail.length === 0) {
    alert("Ninguno de los candidatos seleccionados tiene email guardado.");
    return;
  }
  if (conEmail.length < candidatos.length) {
    alert(`${candidatos.length - conEmail.length} de ${candidatos.length} candidatos no tienen email guardado y se quedarán fuera del correo.`);
  }
  const destinatarios = conEmail.map((c) => c.email).join(",");
  const asunto = encodeURIComponent("Krispy Kreme España — sobre tu candidatura");
  const cuerpo = encodeURIComponent(
    `Hola,\n\nTe escribimos sobre tu candidatura. ¿Podrías confirmarnos tu disponibilidad para una entrevista?\n\nUn saludo,\nEquipo RRHH`
  );
  window.location.href = `mailto:?bcc=${encodeURIComponent(destinatarios)}&subject=${asunto}&body=${cuerpo}`;
}

async function abrirEdicionCandidato(candidatoId) {
  const candidato = await fetch(`${AUTH_API_BASE}/reclutamiento/candidatos/${candidatoId}`).then((r) => r.json());
  candidatoEditando = candidato;
  renderForm();
}

function abrirNuevoCandidato() {
  candidatoEditando = null;
  renderForm();
}

async function revincularTests() {
  const btn = document.getElementById("btn-revincular-tests");
  btn.disabled = true;
  btn.textContent = "Buscando...";
  try {
    const res = await fetch(`${AUTH_API_BASE}/reclutamiento/candidatos/revincular-tests`, { method: "POST" });
    if (!res.ok) {
      alert("No se pudo completar la búsqueda (error " + res.status + ").");
      return;
    }
    const data = await res.json();
    alert(data.enlazados === 0
      ? "No se encontró ninguna coincidencia nueva."
      : `Se enlazaron ${data.enlazados} candidato${data.enlazados === 1 ? "" : "s"} con su test ya respondido.`);
    loadCandidatos();
  } finally {
    btn.disabled = false;
    btn.textContent = "🔗 Buscar tests ya respondidos";
  }
}

async function initBaseCandidatos(user) {
  const modulos = user.modulos || [];
  const tieneAcceso = modulos.includes("informes") || modulos.includes("saona_informes");
  const wrap = document.getElementById("reclu-candidatos-wrap");
  if (!tieneAcceso) {
    wrap.hidden = true;
    return;
  }
  wrap.hidden = false;
  document.getElementById("btn-nuevo-candidato").addEventListener("click", abrirNuevoCandidato);
  document.getElementById("btn-revincular-tests").addEventListener("click", revincularTests);
  document.getElementById("btn-nueva-vacante").addEventListener("click", abrirNuevaVacante);
  document.getElementById("btn-modo-seleccion").addEventListener("click", toggleModoSeleccion);
  document.getElementById("btn-seleccionar-todos-candidatos").addEventListener("click", seleccionarTodosCandidatos);
  document.getElementById("btn-deseleccionar-todos-candidatos").addEventListener("click", deseleccionarTodosCandidatos);
  document.getElementById("btn-whatsapp-seleccionados").addEventListener("click", abrirCampanaWhatsappSeleccionados);
  document.getElementById("btn-mailto-seleccionados").addEventListener("click", abrirMailtoSeleccionados);
  document.getElementById("btn-compartir-seleccionados").addEventListener("click", abrirModalCompartirCandidatos);
  document.getElementById("btn-compartir-candidatos-cancelar").addEventListener("click", cerrarModalCompartirCandidatos);
  document.getElementById("btn-compartir-candidatos-confirmar").addEventListener("click", confirmarCompartirCandidatos);
  document.getElementById("candidatos-estado-masivo").addEventListener("change", (e) => cambiarEstadoSeleccionados(e.target.value));
  document.getElementById("vacantes-filtro-estado").addEventListener("change", refreshVacantes);
  document.getElementById("candidatos-filtro-vacante").addEventListener("change", () => {
    renderVacantesGrid();
    loadCandidatos();
  });
  let buscarTimeout;
  document.getElementById("candidatos-buscar").addEventListener("input", () => {
    clearTimeout(buscarTimeout);
    buscarTimeout = setTimeout(loadCandidatos, 300);
  });
  await refreshVacantes();
  await loadCandidatos();
}

document.addEventListener("DOMContentLoaded", async () => {
  const user = await checkAuth("/compartidos.html");
  if (!user) return;
  wireUserBar(user);
  aplicarBrandingEmpresa();
  await Promise.all([loadCompartidos(), initBaseCandidatos(user)]);
});

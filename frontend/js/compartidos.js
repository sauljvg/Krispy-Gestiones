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
    const mensaje = plantilla.replaceAll("{nombre}", primerNombre);
    link.href = `https://wa.me/${soloDigitos(c.telefono)}?text=${encodeURIComponent(mensaje)}`;
  });
}

function cerrarCampanaWhatsapp() {
  campanaCandidatos = [];
  document.getElementById("campana-whatsapp-wrap").innerHTML = "";
}

function abrirCampanaWhatsapp(candidatos) {
  campanaCandidatos = candidatos;
  const conTelefono = candidatos.filter((c) => c.telefono).length;
  const wrap = document.getElementById("campana-whatsapp-wrap");
  wrap.innerHTML = `
    <div class="vacante-form">
      <h3>💬 Mensaje por WhatsApp</h3>
      <p class="staff-hint">
        Escribe el mensaje una sola vez — usa <code>{nombre}</code> para insertar el nombre de pila de cada candidato.
        Cada botón "Enviar" abre WhatsApp con el mensaje ya escrito para esa persona; tú confirmas el envío allí.
      </p>
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

function candidatoCardHTML(item) {
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
  return `
    <div class="candidato-card">
      <h3>${escapeHTML(nombreCandidato(item.datos))} ${estadoHTML}</h3>
      <p class="candidato-meta">${escapeHTML(item.tipo_nombre)} · hoja "${escapeHTML(item.hoja)}"</p>
      <div class="candidato-datos">
        ${entries.map(([k, v]) => `<div><div class="campo-nombre">${escapeHTML(k)}</div><div>${escapeHTML(v)}</div></div>`).join("")}
      </div>
      <div class="candidato-acciones">${cvBtn}${whatsappBtn}</div>
      ${notasHTML}
    </div>`;
}

// Cada tanda es un <details> desplegable. `etiquetaOtro` describe la relación
// ("Compartido por" / "Compartido con") y `abierta` deja la más reciente
// abierta por defecto para que no haya que hacer clic para ver lo último.
function grupoHTML(grupo, etiquetaOtro, abierta) {
  const n = grupo.items.length;
  return `
    <details class="tanda" ${abierta ? "open" : ""}>
      <summary class="tanda-summary">
        <span class="tanda-fecha">${escapeHTML(fmtFechaHora(grupo.compartido_en))}</span>
        <span class="tanda-meta">${n} candidato${n === 1 ? "" : "s"} · ${escapeHTML(etiquetaOtro)} <b>${escapeHTML(grupo.otro || "")}</b></span>
      </summary>
      <div class="tanda-body">
        ${grupo.items.map(candidatoCardHTML).join("")}
      </div>
    </details>`;
}

function seccionHTML(titulo, grupos, etiquetaOtro, vacioMsg) {
  if (grupos.length === 0) {
    return `<h2 class="reclu-seccion">${escapeHTML(titulo)}</h2><p class="staff-hint">${escapeHTML(vacioMsg)}</p>`;
  }
  return `<h2 class="reclu-seccion">${escapeHTML(titulo)}</h2>` +
    grupos.map((g, i) => grupoHTML(g, etiquetaOtro, i === 0)).join("");
}

function wireCompartidosInteractivos(wrap) {
  wrap.querySelectorAll(".candidato-estado-select").forEach((el) => {
    el.addEventListener("change", () => actualizarCandidatoInline(el.dataset.candidatoId, { estado: el.value }));
  });
  wrap.querySelectorAll(".candidato-notas-input").forEach((el) => {
    el.addEventListener("blur", () => actualizarCandidatoInline(el.dataset.candidatoId, { notas: el.value }));
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
    "Todavía no te han compartido ningún candidato."
  );

  // La sección "Compartidos por ti" solo tiene sentido enseñarla si esta
  // persona ha compartido algo alguna vez (a un gerente no le aparecerá).
  if (gruposPorMi.length > 0) {
    html += seccionHTML("Compartidos por ti", gruposPorMi, "compartido con", "");
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

function candidatoMiniCardHTML(c) {
  const linea2 = [c.telefono, c.email].filter(Boolean).join(" · ");
  const vacante = vacantesTodasCache.find((v) => v.id === c.vacante_id);
  const vacanteTxt = vacante ? `📁 ${vacante.puesto}${vacante.centro ? ` · ${vacante.centro}` : ""}` : "Sin vacante asignada";
  const seleccionada = modoSeleccionCandidatos && candidatosSeleccionadosIds.has(c.id);
  const checkbox = modoSeleccionCandidatos ? `<input type="checkbox" ${seleccionada ? "checked" : ""} style="margin-right:4px;">` : "";
  return `
    <div class="candidato-mini-card ${seleccionada ? "seleccionada" : ""}" data-candidato-id="${c.id}">
      <h4>${checkbox}${escapeHTML(c.nombre_completo || "(sin nombre)")} ${estadoBadgeHTML(c.estado)}</h4>
      <p>${escapeHTML(c.puesto_solicitado || "")}</p>
      <p>${escapeHTML(linea2)}</p>
      <p style="color:var(--text-muted);">${escapeHTML(vacanteTxt)}</p>
    </div>`;
}

function actualizarBotonWhatsappSeleccionados() {
  const btn = document.getElementById("btn-whatsapp-seleccionados");
  const n = candidatosSeleccionadosIds.size;
  btn.hidden = !modoSeleccionCandidatos || n === 0;
  btn.textContent = `💬 Mensaje por WhatsApp (${n})`;
}

function toggleModoSeleccion() {
  modoSeleccionCandidatos = !modoSeleccionCandidatos;
  candidatosSeleccionadosIds.clear();
  document.getElementById("btn-modo-seleccion").textContent = modoSeleccionCandidatos ? "✕ Cancelar selección" : "☑ Selección múltiple";
  actualizarBotonWhatsappSeleccionados();
  renderCandidatosGrid();
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
  const estado = document.getElementById("candidatos-filtro-estado").value;
  const vacanteFiltro = document.getElementById("candidatos-filtro-vacante").value;
  const params = new URLSearchParams({ empresa: EMPRESA });
  if (q) params.set("q", q);
  if (estado) params.set("estado", estado);
  if (vacanteFiltro === "sin_vacante") params.set("sin_vacante", "true");
  else if (vacanteFiltro) params.set("vacante_id", vacanteFiltro);
  ultimosCandidatosCargados = await fetch(`${AUTH_API_BASE}/reclutamiento/candidatos?${params}`).then((r) => (r.ok ? r.json() : []));
  renderCandidatosGrid();
}

function abrirCampanaWhatsappSeleccionados() {
  const candidatos = ultimosCandidatosCargados.filter((c) => candidatosSeleccionadosIds.has(c.id));
  abrirCampanaWhatsapp(candidatos);
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
  document.getElementById("btn-nueva-vacante").addEventListener("click", abrirNuevaVacante);
  document.getElementById("btn-modo-seleccion").addEventListener("click", toggleModoSeleccion);
  document.getElementById("btn-whatsapp-seleccionados").addEventListener("click", abrirCampanaWhatsappSeleccionados);
  document.getElementById("vacantes-filtro-estado").addEventListener("change", refreshVacantes);
  document.getElementById("candidatos-filtro-estado").addEventListener("change", loadCandidatos);
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

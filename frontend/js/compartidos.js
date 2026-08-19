function escapeHTML(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

// Iconos de marca en vez de emoji (💬/✉) -- se ven más cuidados y más
// compactos, para que la barra de selección quepa en una sola línea.
const ICONO_WHATSAPP = `<svg width="15" height="15" viewBox="0 0 32 32" fill="#25D366"><path d="M16.001 3C9.373 3 4 8.373 4 15c0 2.386.697 4.61 1.902 6.484L4 29l7.716-1.862A11.94 11.94 0 0 0 16.001 27C22.628 27 28 21.627 28 15S22.628 3 16.001 3zm6.586 16.2c-.28.784-1.62 1.5-2.24 1.58-.573.074-1.29.104-2.084-.13-.48-.14-1.098-.35-1.89-.686-3.33-1.437-5.5-4.79-5.67-5.014-.166-.224-1.354-1.8-1.354-3.432s.857-2.438 1.16-2.772c.303-.334.66-.418.88-.418.22 0 .44.002.632.012.203.01.475-.077.744.568.28.66.95 2.29 1.034 2.456.084.166.14.36.028.584-.112.224-.168.362-.334.556-.166.194-.35.434-.5.582-.166.166-.34.346-.146.68.194.334.862 1.42 1.85 2.3 1.272 1.132 2.344 1.484 2.678 1.65.334.166.53.14.726-.084.196-.224.836-.976 1.06-1.31.224-.334.448-.278.756-.166.308.112 1.958.924 2.294 1.092.336.168.56.252.644.392.084.14.084.812-.196 1.596z"/></svg>`;
const ICONO_MAILTO = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 6-10 7L2 6"/></svg>`;

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
let campanaTestIdSeleccionado = null;

// Marca "invitado al test" en el momento real de intentar el envío (clic en
// Enviar / Abrir correo) en vez de al elegir el test en el desplegable --
// así no depende de que el admin vuelva a tocar el select en cada tanda de
// envíos (si no lo toca, antes se quedaba sin marcar aunque sí mandara el
// mensaje con el enlace ya escrito de antes).
function marcarInvitadoTest(candidatoIds, encuestaId) {
  if (!encuestaId || !candidatoIds.length) return;
  fetch(`${AUTH_API_BASE}/reclutamiento/candidatos/marcar-invitados-test`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ candidato_ids: candidatoIds, encuesta_id: encuestaId }),
  });
}
let usuarioActual = null; // se fija en initBaseCandidatos -- para firmar el email con el nombre de quien lo envía

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
        ? `<a class="btn btn-ghost btn-whatsapp-campana" data-idx="${i}" data-candidato-id="${c.id}" target="_blank" rel="noopener">💬 Enviar</a>`
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
  campanaTestIdSeleccionado = select.value ? Number(select.value) : null;
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
  campanaTestIdSeleccionado = null;
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
  // El marcado de "invitado al test" se dispara en el clic real de Enviar
  // (no al elegir el test arriba) para que quede registrado sin importar
  // si el admin reselecciona el desplegable en cada tanda de envíos.
  wrap.querySelectorAll(".btn-whatsapp-campana").forEach((btn) => {
    btn.addEventListener("click", () => marcarInvitadoTest([Number(btn.dataset.candidatoId)], campanaTestIdSeleccionado));
  });
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

const MESES_CORTOS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];

// "2026-07-22 13:44:24" -> "22 jul 2026, 13:44"
function fmtFechaHora(iso) {
  if (!iso) return "";
  const [fecha, hora = ""] = iso.split(" ");
  const [y, m, d] = fecha.split("-");
  const hhmm = hora.slice(0, 5);
  return `${parseInt(d, 10)} ${MESES_CORTOS[parseInt(m, 10) - 1]} ${y}${hhmm ? `, ${hhmm}` : ""}`;
}

// Agrupa una lista (ya ordenada por fecha desc) en "tandas". Con
// porVacante=true (solo "Compartidos por ti"), si el candidato ya tiene
// vacante asignada, la tanda se identifica por esa vacante en vez de por la
// fecha exacta -- así, aunque se compartieran en momentos distintos, dos
// candidatos de la misma solicitud quedan bajo el mismo grupo (y ese grupo
// se llama como la vacante, ver tandaTituloHTML). Sin vacante (o en
// "Compartidos conmigo") se sigue agrupando por fecha+contraparte como
// antes. claveOtro = campo que identifica a la otra persona (quién lo
// compartió, o con quién se compartió).
let modoSeleccionCompartidos = false;
let compartidosSeleccionadosIds = new Set();
let compartidosPorMiCache = []; // items crudos de "Compartidos por ti" (para armar el payload de cambiar destinatario)
let gruposPorMiCache = []; // tandas ya agrupadas de "Compartidos por ti" (para el botón "Dejar de compartir todo el grupo")
let tandasAbiertas = new Set(); // claves de <details> que el usuario ha dejado abiertas -- se respeta entre re-renders
let tandasSeccionInicializada = new Set(); // qué secciones ("conmigo"/"por-mi") ya recibieron su apertura por defecto

function agruparPorTanda(items, claveOtro, porVacante) {
  const mapa = new Map();
  for (const it of items) {
    const otro = it[claveOtro] || "";
    const clave = porVacante && it.vacante_id ? `vacante-${it.vacante_id}|${otro}` : `fecha-${it.compartido_en}|${otro}`;
    if (!mapa.has(clave)) {
      mapa.set(clave, { clave, vacanteId: porVacante ? it.vacante_id || null : null, compartido_en: it.compartido_en, otro, items: [] });
    }
    const grupo = mapa.get(clave);
    grupo.items.push(it);
    if (it.compartido_en > grupo.compartido_en) grupo.compartido_en = it.compartido_en;
  }
  // Los items llegan ordenados por fecha desc, pero al agrupar por vacante
  // un grupo puede "moverse" en el tiempo -- se reordena por la fecha más
  // reciente de cada grupo para que el más nuevo siga arriba.
  return [...mapa.values()].sort((a, b) => (a.compartido_en < b.compartido_en ? 1 : a.compartido_en > b.compartido_en ? -1 : 0));
}

// Nombre que se muestra en la cabecera de la tanda: si está agrupada por
// vacante, el puesto/centro de esa vacante (se resuelve de
// vacantesTodasCache, ya cargada para el desplegable de filtro); si no, la
// fecha de siempre.
function tandaTituloHTML(grupo) {
  if (grupo.vacanteId) {
    const v = vacantesTodasCache.find((v) => v.id === grupo.vacanteId);
    const nombre = v ? `${v.puesto}${v.centro ? ` · ${v.centro}` : ""}` : "(vacante)";
    return `<span class="tanda-fecha">📁 ${escapeHTML(nombre)}</span>`;
  }
  return `<span class="tanda-fecha">${escapeHTML(fmtFechaHora(grupo.compartido_en))}</span>`;
}

async function actualizarCandidatoInline(candidatoId, campos) {
  await fetch(`${AUTH_API_BASE}/reclutamiento/candidatos/${candidatoId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(campos),
  });
}

// Misma tarjeta compacta que "Base de candidatos" (candidatoMiniCardHTML) --
// antes esta vista tenía su propia tarjeta grande con TODOS los campos del
// test volcados (candidatoCardHTML), muy distinta de cómo se ve el resto de
// Reclutamiento; ahora es la misma tarjeta en todos lados, con solo lo que
// esta vista necesita de más (Ver CV, Dejar de compartir) como botones
// pequeños al pie. El detalle completo del test se sigue viendo desde "Ver
// ficha completa" (📋 Respuestas del test), no hace falta duplicarlo aquí.
function candidatoCardHTML(item, permitirDejarDeCompartir, permitirSeleccion) {
  const candId = item.candidato_id;
  const nombre = nombreCandidato(item.datos);
  const vacante = vacantesTodasCache.find((v) => v.id === item.vacante_id);
  const vacanteTxt = vacante ? `📁 ${vacante.puesto}${vacante.centro ? ` · ${vacante.centro}` : ""}` : "Sin vacante asignada";
  const linea2 = [item.telefono, item.email].filter(Boolean).join(" · ");
  const checkboxHTML = permitirSeleccion && candId
    ? `<input type="checkbox" class="candidato-compartido-check" data-candidato-id="${candId}" ${compartidosSeleccionadosIds.has(candId) ? "checked" : ""} style="margin-right:4px;">`
    : "";
  const cvBtn = item.tiene_cv
    ? `<a href="${AUTH_API_BASE}/informes/respuestas/${item.respuesta_id}/cv" target="_blank" rel="noopener" class="btn-mini">📄 Ver CV</a>`
    : "";
  const whatsappBtn = item.telefono
    ? `<a class="btn-mini" href="https://wa.me/${soloDigitos(item.telefono)}" target="_blank" rel="noopener">💬 WhatsApp</a>`
    : "";
  const fichaBtn = candId
    ? `<button type="button" class="btn-mini candidato-abrir-ficha" data-candidato-id="${candId}">📋 Ver ficha completa</button>`
    : "";
  // Solo tiene sentido en "Compartidos por ti" -- deja de compartir ESTE
  // candidato con ESTE destinatario en concreto (no borra el candidato ni
  // afecta a otros a los que se lo hayas compartido). El origen del share
  // determina el endpoint: uno viene de Informes (informe_compartidos,
  // compartido_id numérico) y otro es un "compartir directo" desde
  // Reclutamiento (candidato_compartidos, compartido_id "candidato-N").
  const dejarDeCompartirBtn = permitirDejarDeCompartir
    ? `<button type="button" class="btn-mini btn-dejar-compartir"
         data-directo="${String(item.compartido_id).startsWith("candidato-") ? "1" : "0"}"
         data-candidato-id="${candId}" data-respuesta-id="${item.respuesta_id ?? ""}"
         data-destinatario-id="${item.destinatario_id ?? ""}">✕ Dejar de compartir</button>`
    : "";
  return `
    <div class="candidato-mini-card" data-candidato-id="${candId || ""}">
      <div class="candidato-mini-card-fila">
        <span class="candidato-mini-foto candidato-mini-foto-vacia">${escapeHTML((nombre || "?").trim()[0] || "?")}</span>
        <div class="candidato-mini-card-info">
          <h4>${checkboxHTML}${escapeHTML(nombre)} ${item.estado ? estadoBadgeHTML(item.estado) : ""} ${resultadoBadgeHTML(item.test_resultado)}</h4>
          <p>${escapeHTML(linea2)}</p>
          <p style="color:var(--text-muted);">${escapeHTML(vacanteTxt)}</p>
          <div class="candidato-mini-acciones">${fichaBtn}${cvBtn}${whatsappBtn}${dejarDeCompartirBtn}</div>
        </div>
      </div>
    </div>`;
}

// Cada tanda es un <details> desplegable, identificada por `grupo.clave`
// para poder recordar si el usuario la dejó abierta entre re-renders (ver
// tandasAbiertas) -- antes se perdía el estado en cuanto se marcaba un
// checkbox, porque cada cambio de selección repinta toda la lista.
function grupoHTML(grupo, etiquetaOtro, abierta, permitirDejarDeCompartir, permitirSeleccion) {
  const n = grupo.items.length;
  const eliminarGrupoBtn = permitirDejarDeCompartir
    ? `<button type="button" class="btn btn-ghost btn-eliminar-grupo" data-clave="${escapeHTML(grupo.clave)}">🗑 Dejar de compartir todo el grupo</button>`
    : "";
  return `
    <details class="tanda" data-clave="${escapeHTML(grupo.clave)}" ${abierta ? "open" : ""}>
      <summary class="tanda-summary">
        ${tandaTituloHTML(grupo)}
        <span class="tanda-meta">${n} candidato${n === 1 ? "" : "s"} · ${escapeHTML(etiquetaOtro)} <b>${escapeHTML(grupo.otro || "")}</b></span>
      </summary>
      <div class="tanda-body">
        ${eliminarGrupoBtn}
        ${grupo.items.map((it) => candidatoCardHTML(it, permitirDejarDeCompartir, permitirSeleccion)).join("")}
      </div>
    </details>`;
}

function seccionHTML(seccionId, titulo, grupos, etiquetaOtro, vacioMsg, permitirDejarDeCompartir, permitirSeleccion, abrirPorDefecto = true) {
  // "Unir a la misma solicitud" solo tiene sentido en "Compartidos por ti"
  // -- para el caso de compartir el mismo grupo de candidatos en tandas
  // distintas (p.ej. unos a las 8:46 y otros a las 8:59 al mismo gerente) y
  // querer agruparlos bajo un único proceso después.
  const barraSeleccion = permitirSeleccion ? `
    <div class="compartidos-seleccion-bar">
      <button type="button" id="btn-modo-seleccion-compartidos" class="btn btn-ghost">${modoSeleccionCompartidos ? "✕ Cancelar selección" : "☑ Seleccionar"}</button>
      ${modoSeleccionCompartidos ? `
        <span id="compartidos-seleccion-contador" class="staff-hint">${compartidosSeleccionadosIds.size} seleccionado(s)</span>
        <button type="button" id="btn-unir-compartidos" class="btn btn-primary" ${compartidosSeleccionadosIds.size === 0 ? "disabled" : ""}>🔗 Unir a la misma solicitud...</button>
        <button type="button" id="btn-cambiar-destinatario" class="btn btn-primary" ${compartidosSeleccionadosIds.size === 0 ? "disabled" : ""}>👤 Cambiar destinatario...</button>
      ` : ""}
    </div>` : "";
  if (grupos.length === 0) {
    return `<h2 class="reclu-seccion">${escapeHTML(titulo)}</h2>${barraSeleccion}<p class="staff-hint">${escapeHTML(vacioMsg)}</p>`;
  }
  // La primera vez que se pinta esta sección (por sesión de página), se
  // aplica su apertura por defecto -- a partir de ahí se respeta lo que el
  // usuario haya colapsado/expandido a mano. "Compartidos por ti" arranca
  // siempre colapsada (puede ser una lista muy larga, ruido para quien solo
  // quiere abrir una tanda concreta); "Compartidos conmigo" sigue abriendo
  // todo de entrada porque ya viene filtrada a solo aptos.
  if (!tandasSeccionInicializada.has(seccionId)) {
    if (abrirPorDefecto) grupos.forEach((g) => tandasAbiertas.add(g.clave));
    tandasSeccionInicializada.add(seccionId);
  }
  return `<h2 class="reclu-seccion">${escapeHTML(titulo)}</h2>${barraSeleccion}` +
    grupos.map((g) => grupoHTML(g, etiquetaOtro, tandasAbiertas.has(g.clave), permitirDejarDeCompartir, permitirSeleccion && modoSeleccionCompartidos)).join("");
}

async function dejarDeCompartirClick(btn) {
  if (!(await pedirConfirmacion("¿Dejar de compartir este candidato? La persona ya no lo verá en su Reclutamiento."))) return;
  const url = btn.dataset.directo === "1"
    ? `${AUTH_API_BASE}/reclutamiento/candidatos/${btn.dataset.candidatoId}/compartir/${btn.dataset.destinatarioId}`
    : `${AUTH_API_BASE}/informes/compartir/${btn.dataset.respuestaId}/${btn.dataset.destinatarioId}`;
  btn.disabled = true;
  const res = await fetch(url, { method: "DELETE" });
  if (!res.ok) {
    mostrarAviso("No se pudo dejar de compartir. Inténtalo de nuevo.");
    btn.disabled = false;
    return;
  }
  await loadCompartidos();
}

async function eliminarGrupoClick(btn, grupo) {
  const n = grupo.items.length;
  if (!(await pedirConfirmacion(`¿Dejar de compartir los ${n} candidato${n === 1 ? "" : "s"} de este grupo? La persona ya no los verá en su Reclutamiento.`))) return;
  btn.disabled = true;
  await Promise.all(grupo.items.map((it) => {
    const url = String(it.compartido_id).startsWith("candidato-")
      ? `${AUTH_API_BASE}/reclutamiento/candidatos/${it.candidato_id}/compartir/${it.destinatario_id}`
      : `${AUTH_API_BASE}/informes/compartir/${it.respuesta_id}/${it.destinatario_id}`;
    return fetch(url, { method: "DELETE" });
  }));
  tandasAbiertas.delete(grupo.clave);
  await loadCompartidos();
}

function wireCompartidosInteractivos(wrap) {
  wrap.querySelectorAll(".candidato-abrir-ficha").forEach((el) => {
    el.addEventListener("click", () => abrirEdicionCandidato(el.dataset.candidatoId));
  });
  wrap.querySelectorAll(".btn-dejar-compartir").forEach((el) => {
    el.addEventListener("click", () => dejarDeCompartirClick(el));
  });
  wrap.querySelectorAll(".candidato-compartido-check").forEach((el) => {
    el.addEventListener("change", () => {
      const id = Number(el.dataset.candidatoId);
      if (el.checked) compartidosSeleccionadosIds.add(id);
      else compartidosSeleccionadosIds.delete(id);
      loadCompartidos();
    });
  });
  const btnModo = document.getElementById("btn-modo-seleccion-compartidos");
  if (btnModo) {
    btnModo.addEventListener("click", () => {
      modoSeleccionCompartidos = !modoSeleccionCompartidos;
      compartidosSeleccionadosIds.clear();
      loadCompartidos();
    });
  }
  const btnUnir = document.getElementById("btn-unir-compartidos");
  if (btnUnir) {
    btnUnir.addEventListener("click", () => abrirModalAsignarVacante("compartidos"));
  }
  const btnCambiarDestinatario = document.getElementById("btn-cambiar-destinatario");
  if (btnCambiarDestinatario) {
    btnCambiarDestinatario.addEventListener("click", abrirModalCambiarDestinatario);
  }
  wrap.querySelectorAll(".btn-eliminar-grupo").forEach((el) => {
    el.addEventListener("click", () => {
      const grupo = gruposPorMiCache.find((g) => g.clave === el.dataset.clave);
      if (grupo) eliminarGrupoClick(el, grupo);
    });
  });
  // Recuerda qué tandas deja el usuario abiertas/cerradas a mano, para que
  // no se le cierren al marcar un checkbox (cada cambio de selección
  // repinta toda la lista -- ver el listener de .candidato-compartido-check).
  wrap.querySelectorAll(".tanda").forEach((det) => {
    det.addEventListener("toggle", () => {
      if (det.open) tandasAbiertas.add(det.dataset.clave);
      else tandasAbiertas.delete(det.dataset.clave);
    });
  });
}

// Una vacante compartida da acceso a TODOS sus candidatos de una vez
// (presentes y futuros) en vez de un "slot" suelto por cada candidato
// compartido individualmente -- ver reclutamiento.compartir_vacante. Se
// muestra como una sola tarjeta con todos sus candidatos dentro, reusando
// candidatoMiniCardHTML (mismo formato que la Base de candidatos).
// soloAptos: para "Solicitudes compartidas contigo" (vista del gerente) --
// no le interesa ver a quien ya quedó descartado, así que se oculta y solo
// queda el recuento real de a cuántos sigue teniendo que contactar.
// colapsable: para "Solicitudes que has compartido" (vista de quien
// comparte), cada tarjeta es un <details> que arranca cerrado -- ver
// abrirPorDefecto en seccionHTML, mismo motivo (evitar página infinita).
function vacanteCompartidaHTML(vacante, { soloAptos = false, colapsable = false } = {}) {
  const gerentesTxt = (vacante.gerentes || []).map((g) => escapeHTML(g.nombre)).join(", ") || "—";
  const candidatosVisibles = soloAptos
    ? vacante.candidatos.filter((c) => !(c.test_resultado && c.test_resultado.includes("No apto")))
    : vacante.candidatos;
  const ocultos = vacante.candidatos.length - candidatosVisibles.length;
  const ocultosTxt = soloAptos && ocultos > 0 ? ` (${ocultos} no apto${ocultos === 1 ? "" : "s"} oculto${ocultos === 1 ? "" : "s"})` : "";
  const n = candidatosVisibles.length;
  const titulo = `📁 ${escapeHTML(vacante.puesto)}${vacante.centro ? ` · ${escapeHTML(vacante.centro)}` : ""}`;
  const estadoBadge = `<span class="badge-vacante-estado badge-${vacante.estado}">${VACANTE_ESTADO_LABELS[vacante.estado]}</span>`;
  const meta = `👥 ${gerentesTxt} · ${n} candidato${n === 1 ? "" : "s"}${ocultosTxt}`;
  const cuerpo = candidatosVisibles.length
    ? `<div class="candidatos-grid candidatos-lista">${candidatosVisibles.map((c) => candidatoMiniCardHTML(c, { ocultarVacante: true })).join("")}</div>`
    : `<p class="staff-hint">Ningún candidato apto en esta solicitud todavía.</p>`;
  if (colapsable) {
    const clave = `vacsol-${vacante.id}`;
    return `
      <details class="tanda" data-clave="${clave}" ${tandasAbiertas.has(clave) ? "open" : ""}>
        <summary class="tanda-summary">
          <span class="tanda-fecha">${titulo}</span> ${estadoBadge}
          <span class="tanda-meta">${escapeHTML(meta)}</span>
        </summary>
        <div class="tanda-body">${cuerpo}</div>
      </details>`;
  }
  return `
    <div class="vacante-compartida-card">
      <h3>${titulo} ${estadoBadge}</h3>
      <p class="staff-hint">${escapeHTML(meta)}</p>
      ${cuerpo}
    </div>`;
}

function vacantesCompartidasSeccionHTML(titulo, vacantes, vacioMsg, opciones = {}) {
  if (vacantes.length === 0) {
    return vacioMsg ? `<h2 class="reclu-seccion">${escapeHTML(titulo)}</h2><p class="staff-hint">${escapeHTML(vacioMsg)}</p>` : "";
  }
  return `<h2 class="reclu-seccion">${escapeHTML(titulo)}</h2><div class="vacantes-compartidas-lista">${vacantes.map((v) => vacanteCompartidaHTML(v, opciones)).join("")}</div>`;
}

async function loadCompartidos() {
  const wrap = document.getElementById("compartidos-list");
  const [conmigo, porMi, vacantesConmigo, vacantesPorMi] = await Promise.all([
    fetch(`${AUTH_API_BASE}/informes/compartidos?empresa=${EMPRESA}`).then((r) => (r.ok ? r.json() : [])),
    fetch(`${AUTH_API_BASE}/informes/compartidos-por-mi?empresa=${EMPRESA}`).then((r) => (r.ok ? r.json() : [])),
    fetch(`${AUTH_API_BASE}/reclutamiento/vacantes-compartidas-conmigo?empresa=${EMPRESA}`).then((r) => (r.ok ? r.json() : [])),
    fetch(`${AUTH_API_BASE}/reclutamiento/vacantes-compartidas-por-mi?empresa=${EMPRESA}`).then((r) => (r.ok ? r.json() : [])),
  ]);

  // A quien le comparten candidatos (típicamente un gerente de tienda) no le
  // interesa ver a quien ya quedó descartado -- es ruido, lo que de verdad
  // importa es a quién debe poder contactar. Se oculta "No apto" solo en el
  // lado "conmigo" (recibido); en "por ti" (lo que tú compartiste) se sigue
  // viendo todo, porque ahí sí hace falta gestionar también a los descartados.
  const conmigoAptos = conmigo.filter((it) => !(it.test_resultado && it.test_resultado.includes("No apto")));
  const gruposConmigo = agruparPorTanda(conmigoAptos, "compartido_por", true);
  const gruposPorMi = agruparPorTanda(porMi, "destinatario_nombre", true);
  compartidosPorMiCache = porMi;
  gruposPorMiCache = gruposPorMi;

  // Las vacantes compartidas van primero -- es la forma recomendada de ver
  // todo agrupado; los "Compartidos" sueltos por candidato (tandas) quedan
  // debajo, para candidatos que aún no se asignaron a ninguna solicitud.
  let html = vacantesCompartidasSeccionHTML("Solicitudes compartidas contigo", vacantesConmigo, "", { soloAptos: true, colapsable: true });
  html += vacantesCompartidasSeccionHTML("Solicitudes que has compartido", vacantesPorMi, "", { colapsable: true });

  html += seccionHTML(
    "conmigo",
    "Compartidos conmigo",
    gruposConmigo,
    "compartido por",
    "Todavía no te han compartido ningún candidato.",
    false,
    false
  );

  // La sección "Compartidos por ti" solo tiene sentido enseñarla si esta
  // persona ha compartido algo alguna vez (a un gerente no le aparecerá).
  // Arranca colapsada -- para no convertir la pantalla en una página
  // infinita cuando hay muchas tandas acumuladas.
  if (gruposPorMi.length > 0) {
    html += seccionHTML("por-mi", "Compartidos por ti", gruposPorMi, "compartido con", "", true, true, false);
  }

  wrap.innerHTML = html;
  wireCompartidosInteractivos(wrap);
  wrap.querySelectorAll(".vacante-compartida-card .candidato-mini-card").forEach((card) => {
    card.addEventListener("click", (e) => {
      if (e.target.closest(".candidato-mini-contacto-select")) return;
      abrirEdicionCandidato(card.dataset.candidatoId);
    });
  });
  wrap.querySelectorAll(".vacante-compartida-card .candidato-mini-contacto-select").forEach((select) => {
    select.addEventListener("click", (e) => e.stopPropagation());
    select.addEventListener("change", async () => {
      await actualizarCandidatoInline(select.dataset.candidatoId, { contacto_estado: select.value });
    });
  });
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
      ${v ? `<p class="staff-hint">
        👥 Responsables: ${(v.gerentes || []).length
          ? v.gerentes.map((g) => `${escapeHTML(g.nombre)} <button type="button" class="btn-quitar-gerente" data-usuario-id="${g.usuario_id}" title="Quitar como responsable">✕</button>`).join(", ")
          : "(nadie todavía)"}
        <button type="button" id="btn-compartir-vacante" class="btn-mini">＋ Añadir</button>
      </p>
      <p class="staff-hint" style="margin-top:-8px;">Un responsable ve TODOS los candidatos de esta solicitud, aunque se añadan después -- no hace falta compartirlos uno a uno.</p>` : ""}
      <div class="form-actions">
        <button type="button" id="btn-guardar-vacante" class="btn btn-primary">Guardar</button>
        ${v && v.candidatos.length ? `<button type="button" id="btn-whatsapp-vacante" class="btn btn-ghost">💬 Mensaje a los candidatos de esta vacante</button>` : ""}
        ${v ? `<button type="button" id="btn-fusionar-vacante" class="btn btn-ghost">🔗 Fusionar con otra solicitud...</button>` : ""}
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
    document.getElementById("btn-fusionar-vacante").addEventListener("click", abrirModalFusionarVacante);
    document.getElementById("btn-compartir-vacante").addEventListener("click", abrirModalCompartirVacante);
    wrap.querySelectorAll(".btn-quitar-gerente").forEach((btn) => {
      btn.addEventListener("click", () => quitarGerenteVacante(Number(btn.dataset.usuarioId)));
    });
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
    mostrarAviso("Escribe el puesto de la vacante.");
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
    mostrarAviso(err.detail || `No se pudo guardar la vacante (error ${res.status}).`);
    return;
  }
  cerrarVacanteForm();
  await refreshVacantes();
}

async function eliminarVacanteActual() {
  if (!vacanteEditando) return;
  if (!(await pedirConfirmacion(`¿Eliminar la vacante "${vacanteEditando.puesto}"? Los candidatos ya creados no se borran, quedarán sin vacante asignada.`))) return;
  const res = await fetch(`${AUTH_API_BASE}/reclutamiento/vacantes/${vacanteEditando.id}`, { method: "DELETE" });
  if (!res.ok) {
    mostrarAviso(`No se pudo eliminar la vacante (error ${res.status}).`);
    return;
  }
  cerrarVacanteForm();
  await refreshVacantes();
  await loadCandidatos();
}

// Fusionar dos solicitudes que en realidad son el mismo proceso -- mueve
// todos los candidatos de la vacante actual a la elegida y borra la actual.
function abrirModalFusionarVacante() {
  if (!vacanteEditando) return;
  const select = document.getElementById("fusionar-vacante-select");
  select.innerHTML = vacantesTodasCache
    .filter((v) => v.id !== vacanteEditando.id)
    .map((v) => `<option value="${v.id}">${escapeHTML(v.puesto)}${v.centro ? ` · ${escapeHTML(v.centro)}` : ""}</option>`)
    .join("");
  if (!select.options.length) {
    mostrarAviso("No hay otra solicitud con la que fusionar esta.");
    return;
  }
  document.getElementById("fusionar-vacante-modal").classList.add("visible");
}

function cerrarModalFusionarVacante() {
  document.getElementById("fusionar-vacante-modal").classList.remove("visible");
}

async function confirmarFusionarVacante() {
  const destinoId = Number(document.getElementById("fusionar-vacante-select").value);
  if (!destinoId || !vacanteEditando) return;
  const destino = vacantesTodasCache.find((v) => v.id === destinoId);
  if (!(await pedirConfirmacion(`Se moverán todos los candidatos de "${vacanteEditando.puesto}" a "${destino ? destino.puesto : "la solicitud elegida"}" y se eliminará "${vacanteEditando.puesto}". ¿Continuar?`))) return;
  const res = await fetch(`${AUTH_API_BASE}/reclutamiento/vacantes/${vacanteEditando.id}/fusionar`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ destino_id: destinoId }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    mostrarAviso(err.detail || `No se pudo fusionar (error ${res.status}).`);
    return;
  }
  cerrarModalFusionarVacante();
  cerrarVacanteForm();
  await refreshVacantes();
  await loadCandidatos();
}

// Compartir la SOLICITUD completa con uno o más gerentes/responsables --
// distinto de compartir candidatos sueltos uno a uno: da acceso a toda la
// vacante de una vez, presentes y futuros (ver
// reclutamiento.compartir_vacante en el backend). Así, si comparto 5
// candidatos de la misma vacante a Heber, no quedan 5 "slots" sueltos --
// Heber ve la solicitud completa en un único sitio, igual que yo.
async function abrirModalCompartirVacante() {
  if (!vacanteEditando) return;
  if (usuariosParaCompartirCandidatos.length === 0) {
    usuariosParaCompartirCandidatos = await fetch(`${AUTH_API_BASE}/informes/usuarios-para-compartir`).then((r) => r.json());
  }
  const yaResponsables = new Set((vacanteEditando.gerentes || []).map((g) => g.usuario_id));
  const select = document.getElementById("compartir-vacante-select");
  select.innerHTML = usuariosParaCompartirCandidatos
    .filter((u) => !yaResponsables.has(u.id))
    .map((u) => `<option value="${u.id}">${escapeHTML(u.nombre)} (${escapeHTML(u.username)} · ${escapeHTML(u.rol)})</option>`)
    .join("");
  if (!select.options.length) {
    mostrarAviso("Ya todos los usuarios disponibles son responsables de esta solicitud.");
    return;
  }
  document.getElementById("compartir-vacante-modal").classList.add("visible");
}

function cerrarModalCompartirVacante() {
  document.getElementById("compartir-vacante-modal").classList.remove("visible");
}

async function confirmarCompartirVacante() {
  const usuarioId = Number(document.getElementById("compartir-vacante-select").value);
  if (!usuarioId || !vacanteEditando) return;
  await fetch(`${AUTH_API_BASE}/reclutamiento/vacantes/${vacanteEditando.id}/compartir`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ usuario_ids: [usuarioId] }),
  });
  cerrarModalCompartirVacante();
  vacanteEditando = await fetch(`${AUTH_API_BASE}/reclutamiento/vacantes/${vacanteEditando.id}`).then((r) => r.json());
  renderVacanteForm();
}

async function quitarGerenteVacante(usuarioId) {
  if (!vacanteEditando) return;
  if (!(await pedirConfirmacion("¿Quitar a esta persona como responsable de la solicitud? Dejará de ver sus candidatos (salvo que se los hayas compartido también uno a uno)."))) return;
  await fetch(`${AUTH_API_BASE}/reclutamiento/vacantes/${vacanteEditando.id}/compartir/${usuarioId}`, { method: "DELETE" });
  vacanteEditando = await fetch(`${AUTH_API_BASE}/reclutamiento/vacantes/${vacanteEditando.id}`).then((r) => r.json());
  renderVacanteForm();
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
];

let candidatoEditando = null; // null = alta nueva; objeto = editando existente
let extraFieldsState = {};
let formacionState = [];
let experienciaState = [];

function vacanteSelectHTML(selectedId, elementId, fallbackLabel) {
  const opciones = vacantesTodasCache
    .map((v) => {
      const sufijo = v.estado !== "abierta" ? ` (${VACANTE_ESTADO_LABELS[v.estado].toLowerCase()})` : "";
      return `<option value="${v.id}" ${v.id === selectedId ? "selected" : ""}>${escapeHTML(v.puesto)}${v.centro ? ` · ${escapeHTML(v.centro)}` : ""}${sufijo}</option>`;
    })
    .join("");
  // Quien abre una ficha sin tener cargada la lista completa de vacantes
  // (p.ej. un gerente sin el módulo completo, que solo ve lo que le
  // compartieron) no encontraría su vacante actual en `opciones` -- sin
  // este fallback, el <select> caería en "— Sin vacante —" y guardar
  // cualquier otro campo desasignaría la vacante sin querer.
  const yaEstaEnLaLista = vacantesTodasCache.some((v) => v.id === selectedId);
  const fallbackOption = selectedId && !yaEstaEnLaLista && fallbackLabel
    ? `<option value="${selectedId}" selected>${escapeHTML(fallbackLabel)}</option>`
    : "";
  return `<select id="${elementId}"><option value="">— Sin vacante —</option>${fallbackOption}${opciones}</select>`;
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

// Historial estructurado de Formación/Experiencia -- estilo InfoJobs (título/
// centro/fechas por estudio, puesto/empresa/fechas/descripción por puesto)
// en vez de un único bloque de texto libre. Mismo patrón de edición que
// extra_fields: filas en el DOM, se leen al guardar (leerFormacionDelForm/
// leerExperienciaDelForm), no hace falta mantener el array sincronizado en
// cada tecla.
function formacionEntryHTML(e, i) {
  const v = e || {};
  return `
    <div class="historial-entry-row" data-idx="${i}">
      <div class="historial-entry-grid">
        <input type="text" class="historial-titulo" placeholder="Título (p.ej. Grado en Derecho)" value="${escapeHTML(v.titulo || "")}">
        <input type="text" class="historial-centro" placeholder="Centro" value="${escapeHTML(v.centro || "")}">
        <input type="text" class="historial-fecha-inicio" placeholder="Desde (p.ej. sept. 2020)" value="${escapeHTML(v.fecha_inicio || "")}">
        <input type="text" class="historial-fecha-fin" placeholder="Hasta (o Actualmente)" value="${escapeHTML(v.fecha_fin || "")}">
      </div>
      <button type="button" class="btn-mini historial-quitar">✕</button>
    </div>`;
}

function experienciaEntryHTML(e, i) {
  const v = e || {};
  return `
    <div class="historial-entry-row" data-idx="${i}">
      <div class="historial-entry-grid">
        <input type="text" class="historial-puesto" placeholder="Puesto (p.ej. Camarero/a)" value="${escapeHTML(v.puesto || "")}">
        <input type="text" class="historial-empresa" placeholder="Empresa" value="${escapeHTML(v.empresa || "")}">
        <input type="text" class="historial-fecha-inicio" placeholder="Desde (p.ej. enero 2025)" value="${escapeHTML(v.fecha_inicio || "")}">
        <input type="text" class="historial-fecha-fin" placeholder="Hasta (o Actualmente)" value="${escapeHTML(v.fecha_fin || "")}">
        <textarea class="historial-descripcion form-field-full" placeholder="Tareas/funciones (opcional)" style="min-height:40px;">${escapeHTML(v.descripcion || "")}</textarea>
      </div>
      <button type="button" class="btn-mini historial-quitar">✕</button>
    </div>`;
}

function wireHistorialQuitar(cont) {
  cont.querySelectorAll(".historial-quitar").forEach((btn) => {
    btn.addEventListener("click", () => btn.closest(".historial-entry-row").remove());
  });
}

function renderFormacionEditor() {
  const cont = document.getElementById("formacion-editor-filas");
  if (!cont) return;
  cont.innerHTML = formacionState.map(formacionEntryHTML).join("");
  wireHistorialQuitar(cont);
}

function renderExperienciaEditor() {
  const cont = document.getElementById("experiencia-editor-filas");
  if (!cont) return;
  cont.innerHTML = experienciaState.map(experienciaEntryHTML).join("");
  wireHistorialQuitar(cont);
}

function leerFormacionDelForm() {
  return Array.from(document.querySelectorAll("#formacion-editor-filas .historial-entry-row")).map((row) => ({
    titulo: row.querySelector(".historial-titulo").value.trim(),
    centro: row.querySelector(".historial-centro").value.trim(),
    fecha_inicio: row.querySelector(".historial-fecha-inicio").value.trim(),
    fecha_fin: row.querySelector(".historial-fecha-fin").value.trim(),
  })).filter((e) => e.titulo || e.centro || e.fecha_inicio || e.fecha_fin);
}

function leerExperienciaDelForm() {
  return Array.from(document.querySelectorAll("#experiencia-editor-filas .historial-entry-row")).map((row) => ({
    puesto: row.querySelector(".historial-puesto").value.trim(),
    empresa: row.querySelector(".historial-empresa").value.trim(),
    fecha_inicio: row.querySelector(".historial-fecha-inicio").value.trim(),
    fecha_fin: row.querySelector(".historial-fecha-fin").value.trim(),
    descripcion: row.querySelector(".historial-descripcion").value.trim(),
  })).filter((e) => e.puesto || e.empresa || e.fecha_inicio || e.fecha_fin || e.descripcion);
}

// Ficha antigua sin historial estructurado todavía -- se sigue viendo (y
// pudiendo editar) el texto libre de siempre, para no perder lo que ya
// había, con un aviso de que es el formato antiguo.
function historialLegadoHTML(campo, etiqueta, valor) {
  if (!valor) return "";
  return `
    <div class="form-field form-field-full">
      <label>${escapeHTML(etiqueta)} (texto libre, dato antiguo)</label>
      <textarea class="candidato-input" data-campo="${campo}" style="min-height:60px;">${escapeHTML(valor)}</textarea>
      <p class="staff-hint">Formato antiguo -- si añades una entrada arriba, este texto deja de usarse.</p>
    </div>`;
}

function historialEditorHTML() {
  const formacionLegado = candidatoEditando ? historialLegadoHTML("formacion", "Formación", candidatoEditando.formacion) : "";
  const experienciaLegado = candidatoEditando ? historialLegadoHTML("experiencia", "Experiencia", candidatoEditando.experiencia) : "";
  return `
    <div class="form-field form-field-full" style="margin-bottom:12px;">
      <label>🎓 Formación</label>
      <div id="formacion-editor-filas"></div>
      <button type="button" id="btn-formacion-agregar" class="btn-mini" style="margin-top:6px;">＋ Añadir estudio</button>
      ${formacionLegado}
    </div>
    <div class="form-field form-field-full" style="margin-bottom:12px;">
      <label>💼 Experiencia</label>
      <div id="experiencia-editor-filas"></div>
      <button type="button" id="btn-experiencia-agregar" class="btn-mini" style="margin-top:6px;">＋ Añadir experiencia</button>
      ${experienciaLegado}
    </div>`;
}

function renderForm() {
  const wrap = document.getElementById("form-wrap");
  const esEdicion = !!candidatoEditando;
  extraFieldsState = esEdicion ? { ...(candidatoEditando.extra_fields || {}) } : {};
  formacionState = esEdicion ? [...(candidatoEditando.formacion_json || [])] : [];
  experienciaState = esEdicion ? [...(candidatoEditando.experiencia_json || [])] : [];

  const subirCvHTML = esEdicion ? "" : `
    <div class="subir-cv-row">
      <input type="file" id="input-cv-nuevo" accept=".pdf">
      <button type="button" id="btn-extraer-cv" class="btn btn-ghost">📄 Subir CV y rellenar automáticamente</button>
    </div>
    <p class="staff-hint" style="margin-top:-6px;">Puedes subir el CV de 1 candidato o un PDF con varios CVs juntos (hasta unos 50) — se detectan todos automáticamente.</p>
    <div id="extraccion-aviso-wrap"></div>
    <div id="revision-multiple-wrap"></div>`;

  const fotoFormHTML = esEdicion
    ? `<div id="candidato-foto-wrap-cont">${candidatoEditando.tiene_foto ? fotoPreviewHTML(candidatoEditando.id) : ""}</div>`
    : "";

  const compartidoFichaHTML = esEdicion && (candidatoEditando.compartidos || []).length > 0
    ? `<p class="staff-hint">🔗 Compartido con: ${escapeHTML(candidatoEditando.compartidos.map((x) => x.nombre).join(", "))}</p>`
    : "";

  const descargarCvHTML = esEdicion
    ? `<a class="btn btn-ghost" href="${AUTH_API_BASE}/reclutamiento/candidatos/${candidatoEditando.id}/cv.pdf" target="_blank" rel="noopener">📄 Descargar CV en PDF</a>`
    : "";

  const faltanDatos = esEdicion && !candidatoEditando.telefono && !candidatoEditando.email
    ? "Faltan el teléfono y el email"
    : esEdicion && !candidatoEditando.telefono
    ? "Falta el teléfono"
    : esEdicion && !candidatoEditando.email
    ? "Falta el email"
    : null;
  const avisoDatosHTML = faltanDatos ? `<p class="aviso-datos-faltantes">⚠️ ${faltanDatos} de este candidato.</p>` : "";

  const respuestaTestHTML = esEdicion && candidatoEditando.respuesta_datos
    ? `<details class="respuestas-test-detalle">
        <summary>📋 Respuestas del test</summary>
        <div class="respuestas-test-lista">
          ${Object.entries(candidatoEditando.respuesta_datos)
            .filter(([, valor]) => valor !== null && valor !== "")
            .map(([pregunta, valor]) => `<p><strong>${escapeHTML(pregunta)}:</strong> ${escapeHTML(valor)}</p>`)
            .join("")}
        </div>
      </details>`
    : "";

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
    ? `<div class="archivos-lista">${candidatoEditando.archivos.map((a) => `
        <div class="archivo-item-fila">
          <a href="${AUTH_API_BASE}/reclutamiento/candidatos/${candidatoEditando.id}/archivos/${a.id}" target="_blank" rel="noopener">📄 ${escapeHTML(a.nombre_original)}</a>
          ${a.nombre_original.toLowerCase().endsWith(".pdf") ? `<button type="button" class="btn-mini btn-reextraer-cv" data-archivo-id="${a.id}">🔄 Re-extraer con IA</button>` : ""}
        </div>`
      ).join("")}</div>
      <div id="extraccion-aviso-wrap-edicion"></div>`
    : "";

  const agregarArchivoHTML = esEdicion ? `
    <div class="subir-cv-row">
      <input type="file" id="input-archivo-extra">
      <button type="button" id="btn-agregar-archivo" class="btn btn-ghost">＋ Añadir fichero</button>
    </div>` : "";

  wrap.innerHTML = `
    <div class="candidato-form">
      <h3>${esEdicion ? "Editar candidato" : "Nuevo candidato"}</h3>
      ${descargarCvHTML}
      ${fotoFormHTML}
      ${compartidoFichaHTML}
      ${avisoDatosHTML}
      ${resultadoTestHTML}
      ${respuestaTestHTML}
      ${subirCvHTML}
      <div id="single-candidato-wrap">
        <div class="form-grid">
          <div class="form-field">
            <label>Vacante asociada</label>
            ${vacanteSelectHTML(
              esEdicion ? candidatoEditando.vacante_id : vacantePreseleccionada(),
              "candidato-vacante-form",
              esEdicion && candidatoEditando.vacante_puesto
                ? `${candidatoEditando.vacante_puesto}${candidatoEditando.vacante_centro ? ` · ${candidatoEditando.vacante_centro}` : ""}`
                : null
            )}
          </div>
          ${CAMPOS_FORM.map(campoFormHTML).join("")}
          ${esEdicion ? `
            <div class="form-field">
              <label>Estado</label>
              <select id="candidato-estado-form">
                ${ESTADOS.map((e) => `<option value="${e}" ${e === candidatoEditando.estado ? "selected" : ""}>${ESTADO_LABELS[e]}</option>`).join("")}
              </select>
            </div>
            <div class="form-field">
              <label>Estado del contacto ${testEstadoBadgeHTML(candidatoEditando)}</label>
              <select id="candidato-contacto-estado-form">
                ${Object.entries(CONTACTO_ESTADO_LABELS).map(([v, l]) => `<option value="${v}" ${(candidatoEditando.contacto_estado || "sin_contactar") === v ? "selected" : ""}>${l}</option>`).join("")}
              </select>
            </div>` : ""}
          <div class="form-field form-field-full">
            <label>Notas</label>
            <textarea id="candidato-notas-form" style="min-height:60px;">${esEdicion ? escapeHTML(candidatoEditando.notas || "") : ""}</textarea>
          </div>
        </div>
        ${historialEditorHTML()}
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
  renderFormacionEditor();
  document.getElementById("btn-formacion-agregar").addEventListener("click", () => {
    const cont = document.getElementById("formacion-editor-filas");
    cont.insertAdjacentHTML("beforeend", formacionEntryHTML({}, cont.children.length));
    wireHistorialQuitar(cont);
  });
  renderExperienciaEditor();
  document.getElementById("btn-experiencia-agregar").addEventListener("click", () => {
    const cont = document.getElementById("experiencia-editor-filas");
    cont.insertAdjacentHTML("beforeend", experienciaEntryHTML({}, cont.children.length));
    wireHistorialQuitar(cont);
  });
  document.getElementById("btn-cerrar-form").addEventListener("click", cerrarForm);
  document.getElementById("btn-guardar-candidato").addEventListener("click", guardarCandidato);
  if (esEdicion) {
    document.getElementById("btn-eliminar-candidato").addEventListener("click", eliminarCandidatoActual);
    wrap.querySelectorAll(".btn-reextraer-cv").forEach((btn) => {
      btn.addEventListener("click", () => reextraerCv(Number(btn.dataset.archivoId)));
    });
    const btnQuitarFoto = wrap.querySelector(".btn-quitar-foto");
    if (btnQuitarFoto) btnQuitarFoto.addEventListener("click", () => quitarFotoCandidato(candidatoEditando.id));
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

function avisoExtraccionHTML(metodo, n, motivoLocal) {
  const clase = metodo === "gemini" ? "gemini" : "local";
  const motivoTxt = motivoLocal ? ` Motivo: ${motivoLocal}` : "";
  const texto = metodo === "gemini"
    ? `✓ ${n} candidato${n === 1 ? "" : "s"} extraído${n === 1 ? "" : "s"} con IA. Revisa los datos antes de guardar.`
    : `Se usó el método local (sin IA) para leer el PDF${n > 1 ? ` (${n} candidatos detectados)` : ""}. Revisa los datos con más atención antes de guardar.${motivoTxt}`;
  return `<p class="extraccion-aviso ${clase}">${escapeHTML(texto)}</p>`;
}

function rellenarFormConCandidato(campos) {
  for (const [campo, valor] of Object.entries(campos)) {
    if (campo === "extra_fields" || campo === "formacion_json" || campo === "experiencia_json") continue;
    const el = document.querySelector(`.candidato-input[data-campo="${campo}"]`);
    if (el) el.value = valor;
  }
  extraFieldsState = { ...extraFieldsState, ...(campos.extra_fields || {}) };
  renderExtraEditor();
  if (campos.formacion_json?.length) {
    formacionState = campos.formacion_json;
    renderFormacionEditor();
  }
  if (campos.experiencia_json?.length) {
    experienciaState = campos.experiencia_json;
    renderExperienciaEditor();
  }
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
    mostrarAviso("Selecciona al menos un candidato.");
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
    mostrarAviso(`No se pudieron crear ${errores} de ${seleccionados.length} candidatos. Revisa la conexión e inténtalo de nuevo.`);
    btn.disabled = false;
    btn.textContent = "Crear candidatos seleccionados";
    return;
  }
  cerrarForm();
  await refreshVacantes();
  await loadCandidatos();
}

// Para el caso de "subí un PDF con 50 CVs, creé las 50 fichas desde la
// revisión múltiple, pero el PDF en sí nunca quedó adjunto a ninguna" (ver
// renderRevisionMultiple más arriba). Sube el PDF una vez para previsualizar
// contra qué ficha existente coincide cada nombre, y solo al confirmar
// vuelve a mandar ESE MISMO archivo (ya en memoria, sin pedirlo dos veces)
// al endpoint normal de adjuntar archivo -- una vez por cada coincidencia
// encontrada. Nunca crea candidatos nuevos.
let loteArchivoPendiente = null;

function abrirAdjuntarLote() {
  const wrap = document.getElementById("adjuntar-lote-wrap");
  if (wrap.innerHTML.trim()) {
    wrap.innerHTML = "";
    return;
  }
  loteArchivoPendiente = null;
  wrap.innerHTML = `
    <div class="candidato-form">
      <h3>Adjuntar PDF a fichas existentes</h3>
      <p class="staff-hint">
        Para cuando ya creaste varias fichas desde un PDF con varios CVs juntos, pero el PDF nunca quedó
        adjunto a ninguna. Sube aquí ese mismo PDF: se busca por nombre exacto entre tus candidatos ya
        creados y se adjunta a cada uno que coincida — no se crea ninguna ficha nueva.
      </p>
      <div class="subir-cv-row">
        <input type="file" id="input-lote-pdf" accept=".pdf">
        <button type="button" id="btn-previsualizar-lote" class="btn btn-ghost">Comprobar coincidencias</button>
      </div>
      <div id="lote-resultado-wrap"></div>
    </div>`;
  document.getElementById("btn-previsualizar-lote").addEventListener("click", previsualizarLote);
}

async function previsualizarLote() {
  const input = document.getElementById("input-lote-pdf");
  const resultadoWrap = document.getElementById("lote-resultado-wrap");
  if (!input.files.length) {
    resultadoWrap.innerHTML = `<p class="extraccion-aviso local">Selecciona primero el PDF.</p>`;
    return;
  }
  loteArchivoPendiente = input.files[0];
  resultadoWrap.innerHTML = `<p class="staff-hint">Leyendo el PDF y buscando coincidencias...</p>`;
  const formData = new FormData();
  formData.append("file", loteArchivoPendiente);
  const resp = await fetch(`${AUTH_API_BASE}/reclutamiento/candidatos/adjuntar-pdf-lote?empresa=${EMPRESA}`, { method: "POST", body: formData });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    resultadoWrap.innerHTML = `<p class="extraccion-aviso local">${escapeHTML(err.detail || "No se pudo leer el PDF.")}</p>`;
    return;
  }
  const data = await resp.json();
  const items = data.candidatos || [];
  const encontrados = items.filter((it) => it.candidato_id);
  const noEncontrados = items.length - encontrados.length;
  // Cuando la detección de páginas coincide en número con los candidatos
  // extraídos (division_disponible), a cada uno se le adjunta solo SU
  // rango de páginas en vez del PDF de lote entero -- el rango detectado se
  // muestra editable por si falla en algún caso concreto.
  resultadoWrap.innerHTML = `
    ${avisoExtraccionHTML(data.metodo, items.length, data.motivo_local)}
    <p class="staff-hint">${encontrados.length} coincidencia${encontrados.length === 1 ? "" : "s"} encontrada${encontrados.length === 1 ? "" : "s"} de ${items.length}${noEncontrados ? ` (${noEncontrados} sin ficha con ese nombre exacto -- no se les adjunta nada)` : ""}.
    ${data.division_disponible ? "Se ha detectado en qué páginas está cada uno -- se adjunta solo esa parte del PDF (puedes corregir el rango si hace falta)." : "No se pudo dividir el PDF de forma fiable -- se adjuntará el PDF completo a cada ficha encontrada, como antes."}</p>
    <ul class="lote-lista">
      ${items.map((it, i) => `
        <li class="${it.candidato_id ? "lote-ok" : "lote-sin-match"}">
          ${it.candidato_id ? "✓" : "✗"} ${escapeHTML(it.nombre)}
          ${it.candidato_id && data.division_disponible ? `
            <span class="lote-paginas">
              págs. <input type="number" min="1" class="lote-pagina-inicio" data-idx="${i}" value="${it.pagina_inicio}" style="width:44px;">
              a <input type="number" min="1" class="lote-pagina-fin" data-idx="${i}" value="${it.pagina_fin}" style="width:44px;">
            </span>` : ""}
        </li>`).join("")}
    </ul>
    ${encontrados.length ? `<button type="button" id="btn-confirmar-lote" class="btn btn-primary">Adjuntar PDF a las ${encontrados.length} fichas encontradas</button>` : ""}
    <div id="lote-progreso"></div>`;
  if (encontrados.length) {
    document.getElementById("btn-confirmar-lote").addEventListener("click", () => confirmarAdjuntarLote(items));
  }
}

async function confirmarAdjuntarLote(items) {
  const btn = document.getElementById("btn-confirmar-lote");
  const progreso = document.getElementById("lote-progreso");
  btn.disabled = true;
  progreso.textContent = "Recortando y adjuntando...";
  const mapeo = items
    .map((it, i) => {
      if (!it.candidato_id) return null;
      const inputInicio = document.querySelector(`.lote-pagina-inicio[data-idx="${i}"]`);
      const inputFin = document.querySelector(`.lote-pagina-fin[data-idx="${i}"]`);
      return {
        candidato_id: it.candidato_id,
        pagina_inicio: inputInicio ? Number(inputInicio.value) : it.pagina_inicio || null,
        pagina_fin: inputFin ? Number(inputFin.value) : it.pagina_fin || null,
      };
    })
    .filter(Boolean);
  const formData = new FormData();
  formData.append("file", loteArchivoPendiente);
  formData.append("mapeo", JSON.stringify(mapeo));
  const res = await fetch(`${AUTH_API_BASE}/reclutamiento/candidatos/adjuntar-pdf-lote/confirmar`, { method: "POST", body: formData });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    progreso.textContent = err.detail || "No se pudo adjuntar el PDF.";
    btn.disabled = false;
    return;
  }
  const data = await res.json();
  const motivoTxt = data.motivo_local ? ` Se usó el método local (sin IA) -- motivo: ${data.motivo_local}` : "";
  progreso.textContent = `Listo: PDF adjuntado a ${data.adjuntados} ficha(s), ${data.rellenados} con datos nuevos rellenados automáticamente (formación, experiencia y otros campos que estaban vacíos).${motivoTxt}`;
  btn.remove();
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
  avisoWrap.innerHTML = avisoExtraccionHTML(data.metodo, candidatos.length, data.motivo_local);
  if (candidatos.length === 1) {
    rellenarFormConCandidato(candidatos[0]);
    input.dataset.pendingUpload = "1";
  } else {
    renderRevisionMultiple(candidatos);
  }
}

// Re-lee un PDF que YA está adjunto a esta ficha con el extractor actual
// (Gemini si hay clave configurada) -- pensado para candidatos cuyo CV se
// procesó con el método local antes de tener Gemini disponible, o cuando
// falló puntualmente en su momento. Rellena el formulario para revisar,
// igual que al subir un CV nuevo -- no guarda nada por su cuenta.
async function reextraerCv(archivoId) {
  const avisoWrap = document.getElementById("extraccion-aviso-wrap-edicion");
  avisoWrap.innerHTML = `<p class="staff-hint">Volviendo a leer el CV...</p>`;
  const resp = await fetch(
    `${AUTH_API_BASE}/reclutamiento/candidatos/${candidatoEditando.id}/archivos/${archivoId}/reextraer`,
    { method: "POST" }
  );
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    avisoWrap.innerHTML = `<p class="extraccion-aviso local">${escapeHTML(err.detail || "No se pudo volver a leer el CV.")}</p>`;
    return;
  }
  const data = await resp.json();
  avisoWrap.innerHTML = avisoExtraccionHTML(data.metodo, 1, data.motivo_local);
  rellenarFormConCandidato(data.candidato);
  // Si el PDF adjunto es un lote con varias personas, la foto de la
  // "página 1" no tiene por qué ser la de esta ficha -- no se intenta sacar
  // ninguna en ese caso, mejor sin foto que con la de otro candidato.
  if (data.de_lote) return;
  // Aprovecha que ya estamos releyendo este PDF para intentar sacar también
  // la foto, por si el candidato no tenía (ej. ficha antigua sin foto).
  const fotoResp = await fetch(
    `${AUTH_API_BASE}/reclutamiento/candidatos/${candidatoEditando.id}/archivos/${archivoId}/extraer-foto`,
    { method: "POST" }
  ).then((r) => (r.ok ? r.json() : null)).catch(() => null);
  if (fotoResp?.foto_encontrada) mostrarFotoForm(candidatoEditando.id);
}

function fotoPreviewHTML(candidatoId) {
  return `<div class="candidato-foto-preview-wrap">
    <img src="${AUTH_API_BASE}/reclutamiento/candidatos/${candidatoId}/foto?t=${Date.now()}" alt="Foto del candidato" class="candidato-foto-preview">
    <button type="button" class="btn-mini btn-quitar-foto" data-candidato-id="${candidatoId}">🗑 Quitar foto</button>
  </div>`;
}

function mostrarFotoForm(candidatoId) {
  const wrap = document.getElementById("candidato-foto-wrap-cont");
  if (!wrap) return;
  wrap.innerHTML = fotoPreviewHTML(candidatoId);
  wrap.querySelector(".btn-quitar-foto").addEventListener("click", () => quitarFotoCandidato(candidatoId));
}

async function quitarFotoCandidato(candidatoId) {
  await fetch(`${AUTH_API_BASE}/reclutamiento/candidatos/${candidatoId}/foto`, { method: "DELETE" });
  const wrap = document.getElementById("candidato-foto-wrap-cont");
  if (wrap) wrap.innerHTML = "";
}

async function guardarCandidato() {
  const campos = {};
  document.querySelectorAll(".candidato-input").forEach((el) => {
    campos[el.dataset.campo] = el.value.trim() || null;
  });
  campos.notas = document.getElementById("candidato-notas-form").value.trim() || null;
  campos.extra_fields = leerExtraFieldsDelForm();
  campos.formacion_json = leerFormacionDelForm();
  campos.experiencia_json = leerExperienciaDelForm();
  const vacanteValor = document.getElementById("candidato-vacante-form").value;
  campos.vacante_id = vacanteValor ? Number(vacanteValor) : null;

  let candidatoId;
  if (candidatoEditando) {
    campos.estado = document.getElementById("candidato-estado-form").value;
    campos.contacto_estado = document.getElementById("candidato-contacto-estado-form").value;
    const res = await fetch(`${AUTH_API_BASE}/reclutamiento/candidatos/${candidatoEditando.id}`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(campos),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      mostrarAviso(err.detail || `No se pudo guardar el candidato (error ${res.status}).`);
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
      mostrarAviso(err.detail || `No se pudo crear el candidato (error ${resp.status}).`);
      return;
    }
    const data = await resp.json();
    candidatoId = data.id;
    const inputCv = document.getElementById("input-cv-nuevo");
    if (inputCv && inputCv.files.length) {
      const formData = new FormData();
      formData.append("file", inputCv.files[0]);
      const archivoResp = await fetch(`${AUTH_API_BASE}/reclutamiento/candidatos/${candidatoId}/archivos`, { method: "POST", body: formData })
        .then((r) => (r.ok ? r.json() : null)).catch(() => null);
      // Intenta sacar la foto de perfil del mismo PDF -- si no encuentra
      // ninguna razonable, sencillamente no pasa nada (queda sin foto).
      if (archivoResp?.id) {
        await fetch(`${AUTH_API_BASE}/reclutamiento/candidatos/${candidatoId}/archivos/${archivoResp.id}/extraer-foto`, { method: "POST" }).catch(() => {});
      }
    }
  }
  cerrarForm();
  await refreshVacantes();
  await loadCandidatos();
}

async function eliminarCandidatoActual() {
  if (!candidatoEditando) return;
  if (!(await pedirConfirmacion(`¿Seguro que quieres eliminar a ${candidatoEditando.nombre_completo || "este candidato"}? Esta acción no se puede deshacer.`))) return;
  const res = await fetch(`${AUTH_API_BASE}/reclutamiento/candidatos/${candidatoEditando.id}`, { method: "DELETE" });
  if (!res.ok) {
    mostrarAviso(`No se pudo eliminar el candidato (error ${res.status}).`);
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
// Paginación de "Base de candidatos" -- puramente en el cliente (ya se
// cargan todos los candidatos que cumplen el filtro del servidor de una
// vez), el tamaño de página elegido se recuerda entre sesiones.
let candidatosPagina = 1;
let candidatosPorPagina = Number(localStorage.getItem("kt-candidatos-por-pagina")) || 20;
// Distingue "el select muestra Personalizado mientras se escribe el número"
// de "candidatosPorPagina ya es un valor no estándar" -- si no, al elegir
// "Personalizado..." el primer repintado (con candidatosPorPagina todavía
// sin cambiar) volvía a mostrar el desplegable normal en vez del input.
let candidatosPorPaginaEditandoCustom = false;
let usuariosParaCompartirCandidatos = [];

const CONTACTO_ESTADO_LABELS = { sin_contactar: "Sin contactar", contactado: "Contactado", respondio: "Respondió" };

function contactoEstadoSelectHTML(candidatoId, contactoEstado) {
  const opciones = Object.entries(CONTACTO_ESTADO_LABELS)
    .map(([val, label]) => `<option value="${val}" ${(contactoEstado || "sin_contactar") === val ? "selected" : ""}>${label}</option>`)
    .join("");
  return `<select class="candidato-mini-contacto-select" data-candidato-id="${candidatoId}" title="Estado del contacto">${opciones}</select>`;
}

// Estado del TEST (no del contacto humano): invitado_test_en se marca al
// elegir un test en la campaña de WhatsApp (ver onCambiaTestCampana) --
// aproximación de "se intentó enviar", ya que no hay forma de confirmar el
// envío real (enlace wa.me manual). respuesta_id enlazado = ya respondió.
function testEstadoBadgeHTML(c) {
  if (c.respuesta_id) return `<span class="candidato-mini-test-estado test-respondido">✅ Respondió al test</span>`;
  if (c.invitado_test_en) return `<span class="candidato-mini-test-estado test-pendiente">⏳ Esperando respuesta al test</span>`;
  return "";
}

function candidatoMiniCardHTML(c, opts = {}) {
  const linea2 = [c.telefono, c.email].filter(Boolean).join(" · ");
  // ocultarVacante: dentro de una tarjeta de "vacante compartida" ya se ve
  // el puesto/centro en la cabecera del grupo, repetirlo en cada candidato
  // es ruido -- además, quien ve esta vista puede no tener vacantesTodasCache
  // cargada (gerente sin el módulo completo) y buscar ahí daría siempre
  // "Sin vacante asignada" aunque sí la tenga.
  const vacante = vacantesTodasCache.find((v) => v.id === c.vacante_id);
  const vacanteTxt = vacante ? `📁 ${vacante.puesto}${vacante.centro ? ` · ${vacante.centro}` : ""}` : "Sin vacante asignada";
  const seleccionada = modoSeleccionCandidatos && candidatosSeleccionadosIds.has(c.id);
  const checkbox = modoSeleccionCandidatos ? `<input type="checkbox" ${seleccionada ? "checked" : ""} style="margin-right:4px;">` : "";
  const fotoHTML = c.tiene_foto
    ? `<img class="candidato-mini-foto" src="${AUTH_API_BASE}/reclutamiento/candidatos/${c.id}/foto" alt="">`
    : `<span class="candidato-mini-foto candidato-mini-foto-vacia">${escapeHTML((c.nombre_completo || "?").trim()[0] || "?")}</span>`;
  const compartidos = c.compartidos || [];
  const compartidoHTML = compartidos.length > 0
    ? `<p class="candidato-mini-compartido">🔗 Compartido con: ${escapeHTML(compartidos.map((x) => x.nombre).join(", "))}</p>`
    : "";
  return `
    <div class="candidato-mini-card ${seleccionada ? "seleccionada" : ""}" data-candidato-id="${c.id}">
      <div class="candidato-mini-card-fila">
        ${fotoHTML}
        <div class="candidato-mini-card-info">
          <h4>${checkbox}${escapeHTML(c.nombre_completo || "(sin nombre)")} ${estadoBadgeHTML(c.estado)} ${resultadoBadgeHTML(c.test_resultado)} ${!c.telefono || !c.email ? `<span title="Faltan datos de contacto (${!c.telefono ? "teléfono" : ""}${!c.telefono && !c.email ? " y " : ""}${!c.email ? "email" : ""})">⚠️</span>` : ""}</h4>
          <p>${escapeHTML(c.puesto_solicitado || "")}</p>
          <p>${escapeHTML(linea2)}</p>
          ${opts.ocultarVacante ? "" : `<p style="color:var(--text-muted);">${escapeHTML(vacanteTxt)}</p>`}
          ${compartidoHTML}
          ${testEstadoBadgeHTML(c)}
          <div class="candidato-mini-contacto-fila">${contactoEstadoSelectHTML(c.id, c.contacto_estado)}</div>
        </div>
      </div>
    </div>`;
}

function actualizarBotonWhatsappSeleccionados() {
  const barra = document.getElementById("candidatos-seleccion-bar");
  const btnWhatsapp = document.getElementById("btn-whatsapp-seleccionados");
  const btnMailto = document.getElementById("btn-mailto-seleccionados");
  const btnCompartir = document.getElementById("btn-compartir-seleccionados");
  const btnAsignarVacante = document.getElementById("btn-asignar-vacante-seleccionados");
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
  btnWhatsapp.innerHTML = `${ICONO_WHATSAPP}WhatsApp (${n})`;
  btnMailto.hidden = sinSeleccion;
  btnMailto.innerHTML = `${ICONO_MAILTO}Email (${n})`;
  btnCompartir.disabled = sinSeleccion;
  btnAsignarVacante.disabled = sinSeleccion;
  estadoMasivo.disabled = sinSeleccion;
  // "Seleccionar todos" toma TODOS los candidatos cargados actualmente en la
  // pantalla (respetando el filtro de vacante/búsqueda aplicado), no solo
  // los que ya se hubieran marcado a mano uno a uno.
  btnSeleccionarTodos.hidden = n >= ultimosCandidatosCargados.length;
  btnQuitarSeleccion.hidden = sinSeleccion;
}

function seleccionarTodosCandidatos() {
  candidatosFiltradosPorApto().forEach((c) => candidatosSeleccionadosIds.add(c.id));
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
  const usuario = usuariosParaCompartirCandidatos.find((u) => u.id === usuarioId);
  if (usuario) {
    // Compartir es EXCLUSIVO (ver reclutamiento.compartir_candidatos_directo):
    // si ya estaba compartido con otra persona, esa persona pierde el
    // acceso y pasa a ser del nuevo destinatario -- se avisa antes de
    // hacerlo. Re-compartir con la MISMA persona no cambia nada, solo se
    // informa (probable duplicado sin querer).
    const mismoDestinatario = [];
    const otroDestinatario = [];
    ultimosCandidatosCargados.forEach((c) => {
      if (!ids.includes(c.id)) return;
      const compartidos = c.compartidos || [];
      if (compartidos.length === 0) return;
      const nombre = c.nombre_completo || `#${c.id}`;
      if (compartidos.some((x) => x.usuario_id === usuarioId)) mismoDestinatario.push(nombre);
      else otroDestinatario.push(`${nombre} (de ${compartidos.map((x) => x.nombre).join(", ")})`);
    });
    const partes = [];
    if (mismoDestinatario.length) {
      partes.push(`${mismoDestinatario.join(", ")} ya estaba(n) compartido(s) con ${usuario.nombre}.`);
    }
    if (otroDestinatario.length) {
      partes.push(`${otroDestinatario.join(", ")} pasará(n) a ser de ${usuario.nombre} (deja de verlo(s) quien lo(s) tenía antes).`);
    }
    if (partes.length && !(await pedirConfirmacion(`${partes.join(" ")}\n¿Continuar?`))) return;
  }
  await fetch(`${AUTH_API_BASE}/reclutamiento/candidatos/compartir`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ candidato_ids: ids, usuario_id: usuarioId }),
  });
  cerrarModalCompartirCandidatos();
  toggleModoSeleccion();
}

// Asignar en lote una solicitud (vacante) a los candidatos seleccionados --
// pensado para agrupar bajo el mismo proceso a gente que se fue
// compartiendo suelta en momentos distintos (p.ej. a Heber a las 16:22 y
// otros 3 a las 17:00) y que en realidad son la misma solicitud.
// origen "grid" = selección múltiple de "Base de candidatos"; "compartidos"
// = selección en "Compartidos por ti" (para unir bajo la misma solicitud
// candidatos compartidos al mismo gerente en tandas distintas).
let origenAsignarVacante = "grid";

async function abrirModalAsignarVacante(origen = "grid") {
  origenAsignarVacante = origen;
  const ids = origen === "compartidos" ? compartidosSeleccionadosIds : candidatosSeleccionadosIds;
  if (ids.size === 0) return;
  const select = document.getElementById("asignar-vacante-select");
  select.innerHTML =
    `<option value="">— Sin vacante —</option>` +
    vacantesTodasCache
      .map((v) => `<option value="${v.id}">${escapeHTML(v.puesto)}${v.centro ? ` · ${escapeHTML(v.centro)}` : ""}</option>`)
      .join("");
  document.getElementById("asignar-vacante-modal").classList.add("visible");
}

function cerrarModalAsignarVacante() {
  document.getElementById("asignar-vacante-modal").classList.remove("visible");
}

async function confirmarAsignarVacante() {
  const valor = document.getElementById("asignar-vacante-select").value;
  const vacanteId = valor ? Number(valor) : null;
  const ids = [...(origenAsignarVacante === "compartidos" ? compartidosSeleccionadosIds : candidatosSeleccionadosIds)];
  if (ids.length === 0) return;
  await fetch(`${AUTH_API_BASE}/reclutamiento/candidatos/vacante-multiple`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ candidato_ids: ids, vacante_id: vacanteId }),
  });
  cerrarModalAsignarVacante();
  if (origenAsignarVacante === "compartidos") {
    modoSeleccionCompartidos = false;
    compartidosSeleccionadosIds.clear();
    await loadCompartidos();
  } else {
    toggleModoSeleccion();
    await loadCandidatos();
  }
}

// Cambia a quién se compartieron los candidatos seleccionados (p.ej. se
// compartieron con Heber por error y en realidad eran para Adhara) Y, de
// paso, fusiona en una sola tanda cualquier selección que viniera de
// tandas/destinatarios sueltos distintos -- ver informes.cambiar_destinatario_compartidos
// en el backend, que re-estampa todo con el mismo timestamp.
async function abrirModalCambiarDestinatario() {
  if (compartidosSeleccionadosIds.size === 0) return;
  if (usuariosParaCompartirCandidatos.length === 0) {
    usuariosParaCompartirCandidatos = await fetch(`${AUTH_API_BASE}/informes/usuarios-para-compartir`).then((r) => r.json());
  }
  const select = document.getElementById("cambiar-destinatario-select");
  select.innerHTML = usuariosParaCompartirCandidatos
    .map((u) => `<option value="${u.id}">${escapeHTML(u.nombre)} (${escapeHTML(u.username)} · ${escapeHTML(u.rol)})</option>`)
    .join("");
  document.getElementById("cambiar-destinatario-modal").classList.add("visible");
}

function cerrarModalCambiarDestinatario() {
  document.getElementById("cambiar-destinatario-modal").classList.remove("visible");
}

async function confirmarCambiarDestinatario() {
  const nuevoUsuarioId = Number(document.getElementById("cambiar-destinatario-select").value);
  if (!nuevoUsuarioId) return;
  // Un mismo candidato puede aparecer en más de una tanda si se compartió
  // con varias personas a la vez -- se incluyen TODAS sus filas de
  // "Compartidos por ti" que estén seleccionadas, no solo una.
  const seleccionados = compartidosPorMiCache.filter((it) => compartidosSeleccionadosIds.has(it.candidato_id));
  const items = seleccionados.map((it) => ({
    tipo: String(it.compartido_id).startsWith("candidato-") ? "directo" : "informe",
    candidato_id: it.candidato_id,
    respuesta_id: it.respuesta_id,
    usuario_id_actual: it.destinatario_id,
  }));
  if (items.length === 0) return;
  const res = await fetch(`${AUTH_API_BASE}/informes/compartidos-por-mi/destinatario`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ items, nuevo_usuario_id: nuevoUsuarioId }),
  });
  if (!res.ok) {
    mostrarAviso("No se pudo cambiar el destinatario. Inténtalo de nuevo.");
    return;
  }
  cerrarModalCambiarDestinatario();
  modoSeleccionCompartidos = false;
  compartidosSeleccionadosIds.clear();
  await loadCompartidos();
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

function candidatosFiltradosPorApto() {
  const filtro = document.getElementById("candidatos-filtro-apto").value;
  if (!filtro) return ultimosCandidatosCargados;
  if (filtro === "apto") return ultimosCandidatosCargados.filter((c) => c.test_resultado && !c.test_resultado.includes("No apto"));
  return ultimosCandidatosCargados.filter((c) => c.test_resultado && c.test_resultado.includes("No apto"));
}

const TAMANOS_PAGINA_CANDIDATOS = [10, 20, 50, 100];

function candidatosPaginaSelectHTML() {
  const esPersonalizado = candidatosPorPaginaEditandoCustom || !TAMANOS_PAGINA_CANDIDATOS.includes(candidatosPorPagina);
  return `
    <label class="staff-hint" for="candidatos-por-pagina">Ver</label>
    <select id="candidatos-por-pagina">
      ${TAMANOS_PAGINA_CANDIDATOS.map((n) => `<option value="${n}" ${!esPersonalizado && n === candidatosPorPagina ? "selected" : ""}>${n}</option>`).join("")}
      <option value="personalizado" ${esPersonalizado ? "selected" : ""}>Personalizado...</option>
    </select>
    ${esPersonalizado ? `<input type="number" id="candidatos-por-pagina-custom" min="1" value="${candidatosPorPagina}">` : ""}
    <span class="staff-hint">candidatos por página</span>`;
}

function renderCandidatosPaginacion(total, totalPaginas) {
  const wrap = document.getElementById("candidatos-paginacion");
  if (total === 0) {
    wrap.innerHTML = "";
    return;
  }
  const desde = (candidatosPagina - 1) * candidatosPorPagina + 1;
  const hasta = Math.min(candidatosPagina * candidatosPorPagina, total);
  wrap.innerHTML = `
    ${candidatosPaginaSelectHTML()}
    <div class="candidatos-paginacion-botones">
      <span class="staff-hint">${desde}–${hasta} de ${total}</span>
      <button type="button" id="btn-candidatos-pagina-atras" class="btn btn-ghost" ${candidatosPagina <= 1 ? "disabled" : ""}>‹ Anterior</button>
      <span class="staff-hint">Página ${candidatosPagina} de ${totalPaginas}</span>
      <button type="button" id="btn-candidatos-pagina-adelante" class="btn btn-ghost" ${candidatosPagina >= totalPaginas ? "disabled" : ""}>Siguiente ›</button>
    </div>`;
  const selectTamano = document.getElementById("candidatos-por-pagina");
  selectTamano.addEventListener("change", () => {
    if (selectTamano.value === "personalizado") {
      candidatosPorPaginaEditandoCustom = true;
      renderCandidatosGrid();
      document.getElementById("candidatos-por-pagina-custom")?.focus();
      return;
    }
    candidatosPorPaginaEditandoCustom = false;
    candidatosPorPagina = Number(selectTamano.value);
    candidatosPagina = 1;
    localStorage.setItem("kt-candidatos-por-pagina", String(candidatosPorPagina));
    renderCandidatosGrid();
  });
  const inputCustom = document.getElementById("candidatos-por-pagina-custom");
  if (inputCustom) {
    const aplicarCustom = () => {
      const n = Math.max(1, Number(inputCustom.value) || 20);
      candidatosPorPaginaEditandoCustom = false;
      candidatosPorPagina = n;
      candidatosPagina = 1;
      localStorage.setItem("kt-candidatos-por-pagina", String(candidatosPorPagina));
      renderCandidatosGrid();
    };
    inputCustom.addEventListener("blur", aplicarCustom);
    inputCustom.addEventListener("keydown", (e) => { if (e.key === "Enter") aplicarCustom(); });
  }
  document.getElementById("btn-candidatos-pagina-atras").addEventListener("click", () => {
    candidatosPagina = Math.max(1, candidatosPagina - 1);
    renderCandidatosGrid();
  });
  document.getElementById("btn-candidatos-pagina-adelante").addEventListener("click", () => {
    candidatosPagina = Math.min(totalPaginas, candidatosPagina + 1);
    renderCandidatosGrid();
  });
}

function renderCandidatosGrid() {
  const grid = document.getElementById("candidatos-grid");
  const visibles = candidatosFiltradosPorApto();
  const totalPaginas = Math.max(1, Math.ceil(visibles.length / candidatosPorPagina));
  if (candidatosPagina > totalPaginas) candidatosPagina = totalPaginas;
  const inicio = (candidatosPagina - 1) * candidatosPorPagina;
  const pagina = visibles.slice(inicio, inicio + candidatosPorPagina);
  grid.innerHTML = pagina.length
    ? pagina.map(candidatoMiniCardHTML).join("")
    : `<p class="staff-hint">${ultimosCandidatosCargados.length ? "Ningún candidato coincide con el filtro de aptos." : "Todavía no hay candidatos en la base de datos."}</p>`;
  renderCandidatosPaginacion(visibles.length, totalPaginas);
  grid.querySelectorAll(".candidato-mini-card").forEach((card) => {
    card.addEventListener("click", (e) => {
      if (e.target.closest(".candidato-mini-contacto-select")) return;
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
  grid.querySelectorAll(".candidato-mini-contacto-select").forEach((select) => {
    select.addEventListener("click", (e) => e.stopPropagation());
    select.addEventListener("change", async () => {
      await actualizarCandidatoInline(select.dataset.candidatoId, { contacto_estado: select.value });
    });
  });
}

async function loadCandidatos() {
  candidatosPagina = 1;
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

// Toma a todos los candidatos cargados actualmente (según el filtro activo
// de vacante/búsqueda) que tienen un test invitado pero sin respuesta_id
// todavía, y abre la campaña de WhatsApp ya lista solo con ellos.
function abrirRecordatorioPendientes() {
  const pendientes = ultimosCandidatosCargados.filter((c) => c.invitado_test_en && !c.respuesta_id);
  if (pendientes.length === 0) {
    mostrarAviso("No hay candidatos con un test pendiente de respuesta en la lista actual.");
    return;
  }
  abrirCampanaWhatsapp(pendientes);
}

function abrirCampanaWhatsappSeleccionados() {
  const candidatos = ultimosCandidatosCargados.filter((c) => candidatosSeleccionadosIds.has(c.id));
  abrirCampanaWhatsapp(candidatos);
}

// Igual que el recordatorio de Entrevista de Salida: nunca se envía nada
// desde el servidor, se arma un enlace mailto: con todos los correos en
// copia oculta (bcc) y se abre el cliente de correo del propio usuario, que
// es quien de verdad manda el email desde su cuenta. A diferencia del
// mailto directo de antes, ahora pasa por un panel editable (igual que la
// campaña de WhatsApp) porque el asunto/cuerpo estándar de RRHH incluye el
// enlace a un test -- hace falta elegir cuál antes de mandarlo, y conviene
// poder revisar/ajustar el texto (p.ej. la ciudad) antes de que se abra el
// cliente de correo.
let campanaEmailCandidatos = [];
let campanaEmailTestsAbiertos = [];
let campanaEmailEnlaceTest = "";
let campanaEmailTestIdSeleccionado = null;

function asuntoEmailPorDefecto() {
  return EMPRESA === "saona" ? "Proceso de Selección - SAONA" : "Proceso de Selección - Krispy Kreme España";
}

function plantillaEmailPorDefecto() {
  const marca = EMPRESA === "saona" ? "SAONA" : "Krispy Kreme";
  const firmante = usuarioActual?.nombre || "";
  return `Hola, somos ${marca} y hemos considerado tu candidatura para nuestras tiendas.

Es muy importante que realices el siguiente Test (haciendo clic tienes el enlace): {enlace} — una vez finalizado, te enviaremos confirmación con todos los datos del día, hora y ubicación de la entrevista.

Si tienes alguna duda, escríbeme respondiendo este mail.
Muchas gracias, un saludo, espero verte pronto

${firmante}

Equipo RRHH ${marca}`;
}

function campanaEmailTestSelectHTML() {
  if (campanaEmailTestsAbiertos.length === 0) return "";
  return `
    <div class="form-field form-field-full" style="margin-bottom:10px;">
      <label>Adjuntar enlace de un test (opcional)</label>
      <select id="campana-email-test">
        <option value="">— Sin enlace de test —</option>
        ${campanaEmailTestsAbiertos.map((t) => `<option value="${String(t.id).padStart(4, "0")}">${escapeHTML(t.titulo)}</option>`).join("")}
      </select>
    </div>`;
}

function onCambiaTestCampanaEmail() {
  const select = document.getElementById("campana-email-test");
  campanaEmailEnlaceTest = select.value ? `${location.origin}/encuesta.html?slug=${select.value}` : "";
  campanaEmailTestIdSeleccionado = select.value ? Number(select.value) : null;
}

function cerrarCampanaEmail() {
  campanaEmailCandidatos = [];
  campanaEmailEnlaceTest = "";
  document.getElementById("campana-email-wrap").innerHTML = "";
}

function confirmarAbrirEmail() {
  const asunto = document.getElementById("campana-email-asunto").value.trim();
  const cuerpo = document.getElementById("campana-email-cuerpo").value.replaceAll("{enlace}", campanaEmailEnlaceTest);
  const destinatarios = campanaEmailCandidatos.map((c) => c.email).join(",");
  window.location.href = `mailto:?bcc=${encodeURIComponent(destinatarios)}&subject=${encodeURIComponent(asunto)}&body=${encodeURIComponent(cuerpo)}`;
  marcarInvitadoTest(campanaEmailCandidatos.map((c) => c.id), campanaEmailTestIdSeleccionado);
  cerrarCampanaEmail();
}

async function abrirCampanaEmail(candidatos) {
  const conEmail = candidatos.filter((c) => c.email);
  if (conEmail.length === 0) {
    mostrarAviso("Ninguno de los candidatos seleccionados tiene email guardado.");
    return;
  }
  if (conEmail.length < candidatos.length) {
    mostrarAviso(`${candidatos.length - conEmail.length} de ${candidatos.length} candidatos no tienen email guardado y se quedarán fuera del correo.`);
  }
  campanaEmailCandidatos = conEmail;
  campanaEmailEnlaceTest = "";
  campanaEmailTestIdSeleccionado = null;
  campanaEmailTestsAbiertos = await cargarTestsAbiertosCampana();
  const wrap = document.getElementById("campana-email-wrap");
  wrap.innerHTML = `
    <div class="vacante-form">
      <h3>${ICONO_MAILTO} Enviar email</h3>
      <p class="staff-hint">
        Se abrirá tu cliente de correo con estos ${conEmail.length} destinatario${conEmail.length === 1 ? "" : "s"} en copia oculta (BCC) — revisa/edita el asunto y el cuerpo antes de continuar.
        ${campanaEmailTestsAbiertos.length ? `Usa <code>{enlace}</code> donde quieras que vaya el enlace del test que elijas abajo.` : ""}
      </p>
      ${campanaEmailTestSelectHTML()}
      <div class="form-field form-field-full" style="margin-bottom:10px;">
        <label>Asunto</label>
        <input type="text" id="campana-email-asunto" value="${escapeHTML(asuntoEmailPorDefecto())}">
      </div>
      <div class="form-field form-field-full" style="margin-bottom:10px;">
        <label>Cuerpo</label>
        <textarea id="campana-email-cuerpo" style="min-height:200px;">${escapeHTML(plantillaEmailPorDefecto())}</textarea>
      </div>
      <div class="form-actions">
        <button type="button" id="btn-email-abrir" class="btn btn-primary">${ICONO_MAILTO} Abrir correo</button>
        <button type="button" id="btn-cerrar-campana-email" class="btn btn-ghost">Cerrar</button>
      </div>
    </div>`;
  document.getElementById("btn-cerrar-campana-email").addEventListener("click", cerrarCampanaEmail);
  document.getElementById("btn-email-abrir").addEventListener("click", confirmarAbrirEmail);
  const testSelect = document.getElementById("campana-email-test");
  if (testSelect) testSelect.addEventListener("change", onCambiaTestCampanaEmail);
  wrap.scrollIntoView({ behavior: "smooth", block: "start" });
}

function abrirMailtoSeleccionados() {
  const candidatos = ultimosCandidatosCargados.filter((c) => candidatosSeleccionadosIds.has(c.id));
  abrirCampanaEmail(candidatos);
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
      mostrarAviso("No se pudo completar la búsqueda (error " + res.status + ").");
      return;
    }
    const data = await res.json();
    mostrarAviso(data.enlazados === 0
      ? "No se encontró ninguna coincidencia nueva."
      : `Se enlazaron ${data.enlazados} candidato${data.enlazados === 1 ? "" : "s"} con su test ya respondido.`);
    loadCandidatos();
  } finally {
    btn.disabled = false;
    btn.textContent = "🔗 Buscar tests ya respondidos";
  }
}

async function initBaseCandidatos(user) {
  usuarioActual = user;
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
  document.getElementById("btn-adjuntar-lote").addEventListener("click", abrirAdjuntarLote);
  document.getElementById("btn-recordatorio-pendientes").addEventListener("click", abrirRecordatorioPendientes);
  document.getElementById("btn-nueva-vacante").addEventListener("click", abrirNuevaVacante);
  document.getElementById("btn-modo-seleccion").addEventListener("click", toggleModoSeleccion);
  document.getElementById("btn-seleccionar-todos-candidatos").addEventListener("click", seleccionarTodosCandidatos);
  document.getElementById("btn-deseleccionar-todos-candidatos").addEventListener("click", deseleccionarTodosCandidatos);
  document.getElementById("btn-whatsapp-seleccionados").addEventListener("click", abrirCampanaWhatsappSeleccionados);
  document.getElementById("btn-mailto-seleccionados").addEventListener("click", abrirMailtoSeleccionados);
  document.getElementById("btn-compartir-seleccionados").addEventListener("click", abrirModalCompartirCandidatos);
  document.getElementById("btn-compartir-candidatos-cancelar").addEventListener("click", cerrarModalCompartirCandidatos);
  document.getElementById("btn-compartir-candidatos-confirmar").addEventListener("click", confirmarCompartirCandidatos);
  document.getElementById("btn-asignar-vacante-seleccionados").addEventListener("click", () => abrirModalAsignarVacante("grid"));
  document.getElementById("btn-asignar-vacante-cancelar").addEventListener("click", cerrarModalAsignarVacante);
  document.getElementById("btn-asignar-vacante-confirmar").addEventListener("click", confirmarAsignarVacante);
  document.getElementById("btn-cambiar-destinatario-cancelar").addEventListener("click", cerrarModalCambiarDestinatario);
  document.getElementById("btn-cambiar-destinatario-confirmar").addEventListener("click", confirmarCambiarDestinatario);
  document.getElementById("btn-fusionar-vacante-cancelar").addEventListener("click", cerrarModalFusionarVacante);
  document.getElementById("btn-fusionar-vacante-confirmar").addEventListener("click", confirmarFusionarVacante);
  document.getElementById("btn-compartir-vacante-cancelar").addEventListener("click", cerrarModalCompartirVacante);
  document.getElementById("btn-compartir-vacante-confirmar").addEventListener("click", confirmarCompartirVacante);
  document.getElementById("candidatos-estado-masivo").addEventListener("change", (e) => cambiarEstadoSeleccionados(e.target.value));
  document.getElementById("vacantes-filtro-estado").addEventListener("change", refreshVacantes);
  document.getElementById("candidatos-filtro-vacante").addEventListener("change", () => {
    renderVacantesGrid();
    loadCandidatos();
  });
  document.getElementById("candidatos-filtro-apto").addEventListener("change", () => {
    candidatosPagina = 1;
    renderCandidatosGrid();
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
  // initBaseCandidatos primero (no en paralelo): carga vacantesTodasCache,
  // que loadCompartidos necesita para poner el nombre de la vacante en las
  // tandas de "Compartidos por ti" -- si fueran en paralelo, la primera
  // pintada podría no tener todavía los nombres.
  await initBaseCandidatos(user);
  await loadCompartidos();
});

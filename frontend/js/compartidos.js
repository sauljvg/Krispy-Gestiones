// escapeHTML ahora vive en common.js (cargado antes que este script en
// compartidos.html) -- ver ese archivo.

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

// wa.me necesita el número completo CON el código de país -- sin él,
// WhatsApp intenta adivinarlo a partir de los primeros dígitos y a veces
// acierta con el país equivocado: un móvil español de toda la vida como
// "617422547" se interpretaba como "+61 7422547" (Australia) en vez de
// España, y WhatsApp terminaba diciendo que el número "no existe". Si el
// teléfono guardado ya trae "+" delante (ver cv_extraction.PHONE_RE, que
// ahora reconoce el prefijo de cualquier país) se respeta tal cual; si es un
// número español sin prefijo (9 dígitos, empieza por 6/7/8/9) se le
// antepone 34. El resto de formatos se dejan tal cual (mejor un enlace que
// falle de la misma forma que fallaba antes que uno inventado a medias).
function numeroWhatsapp(tel) {
  const conPrefijo = (tel || "").trim().startsWith("+");
  const digitos = soloDigitos(tel);
  if (conPrefijo) return digitos;
  if (/^[6789]\d{8}$/.test(digitos)) return `34${digitos}`;
  return digitos;
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

// c.vacante_puesto/vacante_centro NO existen en los candidatos de esta lista
// (list_candidatos no hace ese join, a diferencia de get_candidato para una
// ficha suelta) -- hay que resolverlo por c.vacante_id contra
// vacantesTodasCache, igual que ya hace candidatoMiniCardHTML.
function vacanteTextosDe(candidato) {
  const v = vacantesTodasCache.find((v) => v.id === candidato.vacante_id);
  return { vacante: v ? `${v.puesto}${v.centro ? ` · ${v.centro}` : ""}` : "", centro: v?.centro || "" };
}

// Compartido entre la campaña de WhatsApp y la de email -- mismos
// placeholders en los dos sitios, para no tener que recordar cuáles
// funcionan en cada uno.
function sustituirPlaceholders(plantilla, candidato, enlaceTest) {
  const primerNombre = (candidato.nombre_completo || "").trim().split(/\s+/)[0] || "";
  const { vacante, centro } = vacanteTextosDe(candidato);
  return plantilla
    .replaceAll("{nombre}", primerNombre)
    .replaceAll("{nombre_completo}", candidato.nombre_completo || "")
    .replaceAll("{mail}", candidato.email || "")
    .replaceAll("{telefono}", candidato.telefono || "")
    .replaceAll("{vacante}", vacante)
    .replaceAll("{centro}", centro)
    .replaceAll("{enlace}", enlaceTest || "");
}

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
    const mensaje = sustituirPlaceholders(plantilla, c, campanaEnlaceTest);
    link.href = `https://wa.me/${numeroWhatsapp(c.telefono)}?text=${encodeURIComponent(mensaje)}`;
  });
}

function onCambiaTestCampana() {
  const select = document.getElementById("campana-test");
  // Si el test tiene un enlace corto configurado (Tests -> Ajustes del
  // test -- p.ej. un TinyURL), se manda ese en vez del nuestro largo
  // (origin + /encuesta.html?slug=NNNN) -- más limpio para quien lo recibe
  // por WhatsApp. Si no tiene uno configurado, se sigue usando el largo
  // como hasta ahora (siempre funciona, solo que no es tan corto).
  const testSeleccionado = campanaTestsAbiertos.find((t) => String(t.id).padStart(4, "0") === select.value);
  campanaEnlaceTest = select.value
    ? (testSeleccionado?.enlace_corto || `${location.origin}/encuesta.html?slug=${select.value}`)
    : "";
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
        Escribe el mensaje una sola vez — usa <code>{nombre}</code>, <code>{nombre_completo}</code>, <code>{mail}</code>,
        <code>{telefono}</code>, <code>{vacante}</code> o <code>{centro}</code> para insertar datos de cada candidato
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
// Selección independiente para "Compartidos conmigo" (ver seccionHTML) --
// separada de la de "Compartidos por ti" de arriba para que activar/marcar
// en una sección no mezcle ni active la otra.
let modoSeleccionCompartidosConmigo = false;
let compartidosConmigoSeleccionadosIds = new Set();
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
function candidatoCardHTML(item, permitirDejarDeCompartir, permitirSeleccion, contexto = "por_mi") {
  const candId = item.candidato_id;
  const nombre = nombreCandidato(item.datos);
  const vacante = vacantesTodasCache.find((v) => v.id === item.vacante_id);
  const vacanteTxt = vacante ? `📁 ${vacante.puesto}${vacante.centro ? ` · ${vacante.centro}` : ""}` : "Sin vacante asignada";
  const linea2 = [item.telefono, item.email].filter(Boolean).join(" · ");
  // "Conmigo" y "por ti" llevan cada uno su propia selección (ver
  // compartidosConmigoSeleccionadosIds) -- si compartieran el mismo Set,
  // marcar "Seleccionar" en una sección activaría también la otra, y un
  // candidato marcado en una se contaría como seleccionado en la otra
  // aunque ni siquiera aparezca ahí.
  const seleccionSet = contexto === "conmigo" ? compartidosConmigoSeleccionadosIds : compartidosSeleccionadosIds;
  const checkboxHTML = permitirSeleccion && candId
    ? `<input type="checkbox" class="candidato-compartido-check" data-contexto="${contexto}" data-candidato-id="${candId}" ${seleccionSet.has(candId) ? "checked" : ""} style="margin-right:4px;">`
    : "";
  const cvBtn = item.tiene_cv
    ? `<a href="${AUTH_API_BASE}/informes/respuestas/${item.respuesta_id}/cv" target="_blank" rel="noopener" class="btn-mini">📄 Ver CV</a>`
    : "";
  const whatsappBtn = item.telefono
    ? `<a class="btn-mini" href="https://wa.me/${numeroWhatsapp(item.telefono)}" target="_blank" rel="noopener">💬 WhatsApp</a>`
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
function grupoHTML(grupo, etiquetaOtro, abierta, permitirDejarDeCompartir, permitirSeleccion, contexto = "por_mi") {
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
        <div class="candidatos-grid ${candidatosVista !== "tarjetas" ? "candidatos-lista" : ""}">
          ${grupo.items.map((it) => candidatoCardHTML(it, permitirDejarDeCompartir, permitirSeleccion, contexto)).join("")}
        </div>
      </div>
    </details>`;
}

function seccionHTML(seccionId, titulo, grupos, etiquetaOtro, vacioMsg, permitirDejarDeCompartir, permitirSeleccion, abrirPorDefecto = true, contexto = "por_mi") {
  // "Unir a la misma solicitud" y "Cambiar destinatario" solo tienen
  // sentido en "Compartidos por ti" (quien comparte) -- para el caso de
  // compartir el mismo grupo de candidatos en tandas distintas (p.ej. unos
  // a las 8:46 y otros a las 8:59 al mismo gerente) y querer agruparlos
  // bajo un único proceso después, o corregir a quién se lo compartiste.
  // "Compartidos conmigo" (quien recibe, p.ej. un gerente al que solo le
  // comparten candidatos sueltos) no puede hacer ninguna de esas dos, pero
  // sí necesita poder exportar a Excel lo que le compartieron -- mismo
  // Excel que ya existe en "Base de candidatos" (ver
  // abrirModalExportarExcel), sin necesitar el módulo completo.
  const modoActivo = contexto === "conmigo" ? modoSeleccionCompartidosConmigo : modoSeleccionCompartidos;
  const seleccionSet = contexto === "conmigo" ? compartidosConmigoSeleccionadosIds : compartidosSeleccionadosIds;
  const idModo = contexto === "conmigo" ? "btn-modo-seleccion-compartidos-conmigo" : "btn-modo-seleccion-compartidos";
  const idContador = contexto === "conmigo" ? "compartidos-conmigo-seleccion-contador" : "compartidos-seleccion-contador";
  const accionesContexto = contexto === "conmigo"
    ? `<button type="button" id="btn-exportar-excel-compartidos" class="btn btn-primary" ${seleccionSet.size === 0 ? "disabled" : ""}>📊 Exportar a Excel...</button>`
    : `<button type="button" id="btn-unir-compartidos" class="btn btn-primary" ${seleccionSet.size === 0 ? "disabled" : ""}>🔗 Unir a la misma solicitud...</button>
       <button type="button" id="btn-cambiar-destinatario" class="btn btn-primary" ${seleccionSet.size === 0 ? "disabled" : ""}>👤 Cambiar destinatario...</button>`;
  const barraSeleccion = permitirSeleccion ? `
    <div class="compartidos-seleccion-bar">
      <button type="button" id="${idModo}" class="btn btn-ghost">${modoActivo ? "✕ Cancelar selección" : "☑ Seleccionar"}</button>
      ${modoActivo ? `
        <span id="${idContador}" class="staff-hint">${seleccionSet.size} seleccionado(s)</span>
        ${accionesContexto}
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
    grupos.map((g) => grupoHTML(g, etiquetaOtro, tandasAbiertas.has(g.clave), permitirDejarDeCompartir, permitirSeleccion && modoActivo, contexto)).join("");
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
      const set = el.dataset.contexto === "conmigo" ? compartidosConmigoSeleccionadosIds : compartidosSeleccionadosIds;
      if (el.checked) set.add(id);
      else set.delete(id);
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
  const btnModoConmigo = document.getElementById("btn-modo-seleccion-compartidos-conmigo");
  if (btnModoConmigo) {
    btnModoConmigo.addEventListener("click", () => {
      modoSeleccionCompartidosConmigo = !modoSeleccionCompartidosConmigo;
      compartidosConmigoSeleccionadosIds.clear();
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
  const btnExportarCompartidos = document.getElementById("btn-exportar-excel-compartidos");
  if (btnExportarCompartidos) {
    btnExportarCompartidos.addEventListener("click", () => abrirModalExportarExcel("compartidos-conmigo"));
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
  // vacante-compartida-candidatos: marca este grid en concreto (a
  // diferencia del de "Compartidos conmigo/por ti", que usa la misma clase
  // .candidato-mini-card pero dentro de .tanda-body con OTRO cableado --
  // ver candidato-abrir-ficha) para poder engancharle el clic que abre la
  // ficha y el botón de exportar sin pisar el otro.
  const exportarBtn = candidatosVisibles.length
    ? `<button type="button" class="btn-mini btn-exportar-excel-vacante-compartida" data-candidato-ids="${candidatosVisibles.map((c) => c.id).join(",")}">📊 Exportar a Excel...</button>`
    : "";
  const cuerpo = candidatosVisibles.length
    ? `<div class="candidatos-grid ${candidatosVista !== "tarjetas" ? "candidatos-lista" : ""} vacante-compartida-candidatos">${candidatosVisibles.map((c) => candidatoMiniCardHTML(c, { ocultarVacante: true })).join("")}</div>`
    : `<p class="staff-hint">Ningún candidato apto en esta solicitud todavía.</p>`;
  if (colapsable) {
    const clave = `vacsol-${vacante.id}`;
    return `
      <details class="tanda" data-clave="${clave}" ${tandasAbiertas.has(clave) ? "open" : ""}>
        <summary class="tanda-summary">
          <span class="tanda-fecha">${titulo}</span> ${estadoBadge}
          <span class="tanda-meta">${escapeHTML(meta)}</span>
        </summary>
        <div class="tanda-body">${exportarBtn}${cuerpo}</div>
      </details>`;
  }
  return `
    <div class="vacante-compartida-card">
      <h3>${titulo} ${estadoBadge}</h3>
      <p class="staff-hint">${escapeHTML(meta)}</p>
      ${exportarBtn}
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
  // Quien tiene el módulo completo (informes/saona_informes) está viendo
  // esta pantalla dentro del contexto de UNA marca (la de la URL, ver
  // EMPRESA), así que tiene sentido acotar "Compartidos" a esa marca. Pero
  // quien NO tiene ningún módulo completo (un gerente al que solo le
  // comparten candidatos sueltos, p.ej. Heber) no eligió ninguna marca --
  // simplemente entra a /compartidos.html a secas, que por defecto cae en
  // "kk". Si se le compartió un candidato de SAONA, con el filtro puesto
  // era invisible del todo (sin ningún aviso ni forma de cambiar de marca
  // en esta pantalla): por eso para esta gente se pide TODO, sin filtrar
  // por empresa (el backend ya lo permite -- empresa es opcional).
  // Sin el módulo completo, "Base de candidatos" (que ocupa el área "lista"
  // del grid en vista Lista + CV) ni siquiera se pinta -- ver la regla
  // .modo-restringido en compartidos.html, que hace que #compartidos-list
  // ocupe esa misma área en su lugar para esta gente.
  document.querySelector(".compartidos-wrap")?.classList.toggle("modo-restringido", esUsuarioRestringido);
  const filtroEmpresa = esUsuarioRestringido ? "" : `?empresa=${EMPRESA}`;
  const [conmigo, porMi, vacantesConmigo, vacantesPorMi] = await Promise.all([
    fetch(`${AUTH_API_BASE}/informes/compartidos${filtroEmpresa}`).then((r) => (r.ok ? r.json() : [])),
    fetch(`${AUTH_API_BASE}/informes/compartidos-por-mi${filtroEmpresa}`).then((r) => (r.ok ? r.json() : [])),
    fetch(`${AUTH_API_BASE}/reclutamiento/vacantes-compartidas-conmigo${filtroEmpresa}`).then((r) => (r.ok ? r.json() : [])),
    fetch(`${AUTH_API_BASE}/reclutamiento/vacantes-compartidas-por-mi${filtroEmpresa}`).then((r) => (r.ok ? r.json() : [])),
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

  // Toggle de vista propio para quien no ve "Base de candidatos" (donde
  // vive el otro) -- mismo candidatosVista compartido, ver wireVistaToggle/
  // aplicarVistaGlobal. Visible siempre (no solo para quien es restringido)
  // para no tener que distinguir aquí mismo quién lo necesita.
  const vistaToggleHTML = `
    <div class="vista-toggle" role="group" aria-label="Cómo ver la lista" style="margin-bottom:12px;">
      <button type="button" class="vista-toggle-btn" data-vista="lista" title="Lista">📃</button>
      <button type="button" class="vista-toggle-btn" data-vista="combinada" title="Lista + CV">📃➕</button>
      <button type="button" class="vista-toggle-btn" data-vista="tarjetas" title="Tarjetas">🗂️</button>
    </div>`;

  // Las vacantes compartidas van primero -- es la forma recomendada de ver
  // todo agrupado; los "Compartidos" sueltos por candidato (tandas) quedan
  // debajo, para candidatos que aún no se asignaron a ninguna solicitud.
  let html = vistaToggleHTML;
  html += vacantesCompartidasSeccionHTML("Solicitudes compartidas contigo", vacantesConmigo, "", { soloAptos: true, colapsable: true });
  html += vacantesCompartidasSeccionHTML("Solicitudes que has compartido", vacantesPorMi, "", { colapsable: true });

  html += seccionHTML(
    "conmigo",
    "Compartidos conmigo",
    gruposConmigo,
    "compartido por",
    "Todavía no te han compartido ningún candidato.",
    false,
    true,
    true,
    "conmigo"
  );

  // La sección "Compartidos por ti" solo tiene sentido enseñarla si esta
  // persona ha compartido algo alguna vez (a un gerente no le aparecerá).
  // Arranca colapsada -- para no convertir la pantalla en una página
  // infinita cuando hay muchas tandas acumuladas.
  if (gruposPorMi.length > 0) {
    html += seccionHTML("por-mi", "Compartidos por ti", gruposPorMi, "compartido con", "", true, true, false);
  }

  aparcarFormWrapEnSitio();
  wrap.innerHTML = html;
  wireCompartidosInteractivos(wrap);
  wireVistaToggle(wrap, aplicarVistaGlobal);
  aplicarVistaGlobal();
  // .vacante-compartida-candidatos (no .vacante-compartida-card) porque
  // "Solicitudes compartidas contigo" se pinta colapsable -- ahí el grid de
  // candidatos queda dentro de un <details class="tanda"> igual que
  // "Compartidos conmigo/por ti", NO dentro de .vacante-compartida-card
  // (esa clase solo se usa cuando colapsable=false). Con el selector viejo,
  // ningún clic abría la ficha en "Solicitudes compartidas contigo".
  wrap.querySelectorAll(".vacante-compartida-candidatos .candidato-mini-card").forEach((card) => {
    card.addEventListener("click", (e) => {
      // El checkbox no tiene cableado propio en esta vista (solo sirve para
      // marcar a quién exportar, ver btn-exportar-excel-vacante-compartida
      // más abajo) -- sin este corte, el clic se colaba hasta la tarjeta y
      // abría la ficha en vez de solo marcar la casilla.
      if (e.target.closest(".candidato-mini-checkbox-col") || e.target.closest(".candidato-mini-contacto-select")) return;
      abrirEdicionCandidato(card.dataset.candidatoId);
    });
  });
  wrap.querySelectorAll(".vacante-compartida-candidatos .candidato-mini-checkbox").forEach((check) => {
    check.addEventListener("click", (e) => e.stopPropagation());
  });
  wrap.querySelectorAll(".vacante-compartida-candidatos .candidato-mini-contacto-select").forEach((select) => {
    select.addEventListener("click", (e) => e.stopPropagation());
    select.addEventListener("change", async () => {
      await actualizarCandidatoInline(select.dataset.candidatoId, { contacto_estado: select.value });
    });
  });
  wrap.querySelectorAll(".btn-exportar-excel-vacante-compartida").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      // Si se marcó algún checkbox dentro de esta misma solicitud, exporta
      // solo esos -- si no se marcó ninguno, exporta la solicitud entera
      // (el comportamiento de siempre, para no obligar a marcar uno a uno
      // cuando se quieren todos).
      const marcados = Array.from(btn.parentElement.querySelectorAll(".candidato-mini-checkbox:checked"))
        .map((c) => Number(c.closest(".candidato-mini-card").dataset.candidatoId));
      const ids = marcados.length ? marcados : btn.dataset.candidatoIds.split(",").map(Number).filter(Boolean);
      abrirModalExportarExcel("vacante-compartida", ids);
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
  const verArchivadas = document.getElementById("vacantes-ver-archivadas").checked;
  const paramsFiltradas = new URLSearchParams({ empresa: EMPRESA });
  if (estado) paramsFiltradas.set("estado", estado);
  if (verArchivadas) paramsFiltradas.set("archivadas", "true");
  const [filtradas, todas] = await Promise.all([
    fetch(`${AUTH_API_BASE}/reclutamiento/vacantes?${paramsFiltradas}`).then((r) => (r.ok ? r.json() : [])),
    // vacantesTodasCache alimenta el desplegable de asignación y el filtro de
    // candidatos -- siempre las NO archivadas, sin importar el checkbox de
    // arriba (asignar candidatos a una vacante archivada no tendría sentido).
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
        ${!v ? `<div class="form-field form-field-full">
          <label>Subir CVs para esta vacante (opcional)</label>
          <input type="file" id="vacante-cv-lote" accept=".pdf">
          <p class="staff-hint" style="margin-top:4px;">El CV de una persona o un PDF con varios juntos -- las fichas se crean ya asignadas a esta vacante.</p>
        </div>` : ""}
      </div>
      ${v ? `<p class="staff-hint">Solicitada el ${escapeHTML(fmtFechaHora(v.fecha_solicitud))}${v.fecha_cierre ? ` · cerrada el ${escapeHTML(fmtFechaHora(v.fecha_cierre))}` : ""}</p>` : ""}
      ${v ? `<p class="staff-hint">
        👥 Responsables: ${(v.gerentes || []).length
          ? v.gerentes.map((g) => `${escapeHTML(g.nombre)} <button type="button" class="btn-quitar-gerente" data-usuario-id="${g.usuario_id}" title="Quitar como responsable">✕</button>`).join(", ")
          : "(nadie todavía)"}
        <button type="button" id="btn-compartir-vacante" class="btn-mini">＋ Añadir</button>
      </p>
      <p class="staff-hint" style="margin-top:-8px;">Un responsable ve TODOS los candidatos de esta solicitud, aunque se añadan después -- no hace falta compartirlos uno a uno.</p>` : ""}
      <div class="form-actions form-actions-compacta">
        <button type="button" id="btn-guardar-vacante" class="btn btn-primary">Guardar</button>
        ${v && v.candidatos.length ? `<button type="button" id="btn-whatsapp-vacante" class="btn btn-ghost" title="Mensaje a los candidatos de esta vacante">💬 Mensaje</button>` : ""}
        ${v ? `<button type="button" id="btn-fusionar-vacante" class="btn btn-ghost" title="Fusionar con otra solicitud...">🔗 Fusionar</button>` : ""}
        ${v ? `<button type="button" id="btn-archivar-vacante" class="btn btn-ghost">${v.archivada ? "📤 Desarchivar" : "🗄️ Archivar"}</button>` : ""}
        ${v ? `<button type="button" id="btn-eliminar-vacante" class="btn btn-ghost" title="Eliminar vacante">🗑 Eliminar</button>` : ""}
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
    document.getElementById("btn-archivar-vacante").addEventListener("click", archivarVacanteActual);
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
  const archivoInput = document.getElementById("vacante-cv-lote");
  const archivo = !vacanteEditando && archivoInput?.files.length ? archivoInput.files[0] : null;
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
  const data = await res.json();
  cerrarVacanteForm();
  await refreshVacantes();
  // Reutiliza el flujo de "Nuevo candidato" (local-first + IA en segundo
  // plano, ver procesarPdfNuevosCandidatos) con la vacante recién creada ya
  // preseleccionada, para no tener que ir asignando candidato a candidato.
  if (archivo && data.id) {
    abrirNuevoCandidato();
    await procesarPdfNuevosCandidatos(archivo, document.getElementById("extraccion-aviso-wrap"), {
      vacantePreseleccionadaId: data.id,
    });
  }
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

async function archivarVacanteActual() {
  if (!vacanteEditando) return;
  const archivar = !vacanteEditando.archivada;
  await fetch(`${AUTH_API_BASE}/reclutamiento/vacantes/${vacanteEditando.id}`, {
    method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ archivada: archivar }),
  });
  cerrarVacanteForm();
  await refreshVacantes();
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
  // Un <input> de una sola línea escondía los saltos de línea de verdad que
  // ya traía el valor (p.ej. "Preguntas de selección", un bloque largo con
  // una pregunta por línea) -- se veía como un único párrafo ilegible en
  // vez de una lista. A partir de cierto largo se usa un <textarea> en su
  // lugar, mismo campo .extra-value así que leerExtraFieldsDelForm no
  // necesita cambiar nada.
  // Algunos candidatos antiguos tienen un "otro dato" que no es texto (p.ej.
  // un número) -- sin este cast, .length/.includes rompían aquí y, al
  // propagarse el error, dejaban sin conectar TODOS los botones que se
  // cablean después en renderForm (Guardar, Cancelar, la X de cerrar...).
  value = value == null ? "" : String(value);
  const esLargo = value.length > 80 || value.includes("\n");
  const campoValor = esLargo
    ? `<textarea class="extra-value" placeholder="Valor" style="min-height:70px;">${escapeHTML(value)}</textarea>`
    : `<input type="text" class="extra-value" placeholder="Valor" value="${escapeHTML(value)}">`;
  return `
    <div class="extra-editor-row ${esLargo ? "extra-editor-row-largo" : ""}">
      <input type="text" class="extra-key" placeholder="Campo (p.ej. Idiomas)" value="${escapeHTML(key)}">
      ${campoValor}
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
// Duración aproximada entre dos fechas en texto libre (vienen de la IA en
// formatos muy variados: "sept. 2020", "2023", "enero 2025", "Actualmente"
// para el final...) -- se parsea lo mejor posible (año siempre, mes si se
// reconoce el nombre o un mm/aaaa, si no se asume mitad de año para no
// sesgar hacia principio/fin) y se devuelve null si no se puede calcular
// nada en vez de mostrar un dato inventado. 0 meses es un resultado válido
// (p.ej. entró y salió el mismo mes), no se oculta.
const MESES_TEXTO = {
  enero: 1, ene: 1, febrero: 2, feb: 2, marzo: 3, mar: 3, abril: 4, abr: 4, mayo: 5, may: 5,
  junio: 6, jun: 6, julio: 7, jul: 7, agosto: 8, ago: 8, septiembre: 9, setiembre: 9, sept: 9, sep: 9,
  octubre: 10, oct: 10, noviembre: 11, nov: 11, diciembre: 12, dic: 12,
};

function parsearFechaAproximada(texto) {
  if (!texto) return null;
  const t = texto.toLowerCase();
  const anioMatch = t.match(/\b(19|20)\d{2}\b/);
  if (!anioMatch) return null;
  const anio = Number(anioMatch[0]);
  let mes = null;
  for (const [nombre, num] of Object.entries(MESES_TEXTO)) {
    if (t.includes(nombre)) { mes = num; break; }
  }
  if (mes === null) {
    const numMatch = t.match(/\b(0?[1-9]|1[0-2])[/\-]\s*(19|20)\d{2}\b/);
    if (numMatch) mes = Number(numMatch[1]);
  }
  return { anio, mes: mes ?? 6 };
}

function calcularDuracion(fechaInicio, fechaFin) {
  const inicio = parsearFechaAproximada(fechaInicio);
  if (!inicio) return null;
  let fin;
  if (!fechaFin || /actual/i.test(fechaFin)) {
    const hoy = new Date();
    fin = { anio: hoy.getFullYear(), mes: hoy.getMonth() + 1 };
  } else {
    fin = parsearFechaAproximada(fechaFin);
    if (!fin) return null;
  }
  const totalMeses = (fin.anio - inicio.anio) * 12 + (fin.mes - inicio.mes);
  if (totalMeses < 0) return null;
  const anios = Math.floor(totalMeses / 12);
  const meses = totalMeses % 12;
  if (anios === 0) return `${meses} mes${meses === 1 ? "" : "es"}`;
  if (meses === 0) return `${anios} año${anios === 1 ? "" : "s"}`;
  return `${anios} año${anios === 1 ? "" : "s"} ${meses} mes${meses === 1 ? "" : "es"}`;
}

function formacionEntryHTML(e, i) {
  const v = e || {};
  const duracion = calcularDuracion(v.fecha_inicio, v.fecha_fin);
  return `
    <div class="historial-entry-row" data-idx="${i}">
      <div class="historial-entry-grid">
        <input type="text" class="historial-titulo" placeholder="Título (p.ej. Grado en Derecho)" value="${escapeHTML(v.titulo || "")}">
        <input type="text" class="historial-centro" placeholder="Centro" value="${escapeHTML(v.centro || "")}">
        <input type="text" class="historial-fecha-inicio" placeholder="Desde (p.ej. sept. 2020)" value="${escapeHTML(v.fecha_inicio || "")}">
        <input type="text" class="historial-fecha-fin" placeholder="Hasta (o Actualmente)" value="${escapeHTML(v.fecha_fin || "")}">
        <span class="historial-duracion">${duracion ? escapeHTML(duracion) : ""}</span>
      </div>
      <button type="button" class="btn-mini historial-quitar">✕</button>
    </div>`;
}

function experienciaEntryHTML(e, i) {
  const v = e || {};
  const duracion = calcularDuracion(v.fecha_inicio, v.fecha_fin);
  return `
    <div class="historial-entry-row" data-idx="${i}">
      <div class="historial-entry-grid">
        <input type="text" class="historial-puesto" placeholder="Puesto (p.ej. Camarero/a)" value="${escapeHTML(v.puesto || "")}">
        <input type="text" class="historial-empresa" placeholder="Empresa" value="${escapeHTML(v.empresa || "")}">
        <input type="text" class="historial-fecha-inicio" placeholder="Desde (p.ej. enero 2025)" value="${escapeHTML(v.fecha_inicio || "")}">
        <input type="text" class="historial-fecha-fin" placeholder="Hasta (o Actualmente)" value="${escapeHTML(v.fecha_fin || "")}">
        <span class="historial-duracion">${duracion ? escapeHTML(duracion) : ""}</span>
        <textarea class="historial-descripcion form-field-full" placeholder="Tareas/funciones (opcional)" style="min-height:40px;">${escapeHTML(v.descripcion || "")}</textarea>
      </div>
      <button type="button" class="btn-mini historial-quitar">✕</button>
    </div>`;
}

function wireHistorialQuitar(cont) {
  cont.querySelectorAll(".historial-quitar").forEach((btn) => {
    btn.addEventListener("click", () => btn.closest(".historial-entry-row").remove());
  });
  // Recalcula la duración mostrada al vuelo si el reclutador corrige una
  // fecha a mano, sin tener que guardar y reabrir la ficha para verla.
  cont.querySelectorAll(".historial-entry-row").forEach((row) => {
    const spanDuracion = row.querySelector(".historial-duracion");
    if (!spanDuracion) return;
    const actualizar = () => {
      const duracion = calcularDuracion(
        row.querySelector(".historial-fecha-inicio").value,
        row.querySelector(".historial-fecha-fin").value
      );
      spanDuracion.textContent = duracion || "";
    };
    row.querySelector(".historial-fecha-inicio").addEventListener("input", actualizar);
    row.querySelector(".historial-fecha-fin").addEventListener("input", actualizar);
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
      <p class="staff-hint">Formato antiguo -- si añades una entrada arriba, este texto deja de usarse. <button type="button" class="btn-mini btn-borrar-legado" data-campo="${campo}">🗑 Borrar este texto</button></p>
    </div>`;
}

function historialEditorHTML() {
  const formacionLegado = candidatoEditando ? historialLegadoHTML("formacion", "Formación", candidatoEditando.formacion) : "";
  const experienciaLegado = candidatoEditando ? historialLegadoHTML("experiencia", "Experiencia", candidatoEditando.experiencia) : "";
  // Desplegable y cerrado de por sí -- antes toda la Formación/Experiencia
  // se veía de golpe nada más abrir la ficha, aunque no hiciera falta
  // mirarla en ese momento.
  return `
    <details class="ficha-desplegable">
      <summary>🎓 Ver Formación</summary>
      <div class="form-field form-field-full" style="margin-bottom:12px;">
        <div id="formacion-editor-filas"></div>
        <button type="button" id="btn-formacion-agregar" class="btn-mini" style="margin-top:6px;">＋ Añadir estudio</button>
        ${formacionLegado}
      </div>
    </details>
    <details class="ficha-desplegable">
      <summary>💼 Ver Experiencia</summary>
      <div class="form-field form-field-full" style="margin-bottom:12px;">
        <div id="experiencia-editor-filas"></div>
        <button type="button" id="btn-experiencia-agregar" class="btn-mini" style="margin-top:6px;">＋ Añadir experiencia</button>
        ${experienciaLegado}
      </div>
    </details>`;
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

  // Quien no tiene el módulo completo no necesita gestionar ficheros
  // (agregar, re-extraer...) -- solo descargar el CV, así que ese botón se
  // mueve abajo del todo (ver descargarCvBotonHTML) en vez de ir aquí arriba
  // junto con el resto de acciones que esta gente no usa.
  const descargarCvHTML = esEdicion && !esUsuarioRestringido
    ? `<a class="btn btn-ghost" href="${AUTH_API_BASE}/reclutamiento/candidatos/${candidatoEditando.id}/cv.pdf" target="_blank" rel="noopener">📄 Descargar CV en PDF</a>`
    : "";
  const descargarCvBotonHTML = esEdicion && esUsuarioRestringido
    ? `<a class="btn btn-ghost btn-descargar-cv" href="${AUTH_API_BASE}/reclutamiento/candidatos/${candidatoEditando.id}/cv.pdf" target="_blank" rel="noopener">Descargar CV</a>`
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

  // Envuelto en un hueco de alto mínimo (ver .ficha-resultado-test-slot) y
  // SIEMPRE presente en el DOM, tenga o no tenga contenido -- sin esto, la
  // ficha de quien ya respondió el test salía más alta que la de quien no,
  // cambiando el tamaño del contenedor según el candidato.
  const resultadoTestSlotHTML = `<div class="ficha-resultado-test-slot">${resultadoTestHTML}${respuestaTestHTML}</div>`;

  // Ni la lista de ficheros ni "Añadir fichero"/"Re-extraer con IA" le
  // sirven a quien no tiene el módulo completo -- ver descargarCvBotonHTML,
  // el único botón que necesita.
  const archivosHTML = esEdicion && !esUsuarioRestringido && candidatoEditando.archivos.length
    ? `<div class="archivos-lista">${candidatoEditando.archivos.map((a) => `
        <div class="archivo-item-fila">
          <a href="${AUTH_API_BASE}/reclutamiento/candidatos/${candidatoEditando.id}/archivos/${a.id}" target="_blank" rel="noopener">📄 ${escapeHTML(a.nombre_original)}</a>
          ${a.nombre_original.toLowerCase().endsWith(".pdf") ? `<button type="button" class="btn-mini btn-reextraer-cv" data-archivo-id="${a.id}">🔄 Re-extraer</button>` : ""}
        </div>`
      ).join("")}</div>
      <div id="extraccion-aviso-wrap-edicion"></div>`
    : "";

  const agregarArchivoHTML = esEdicion && !esUsuarioRestringido ? `
    <div class="subir-cv-row">
      <input type="file" id="input-archivo-extra">
      <button type="button" id="btn-agregar-archivo" class="btn btn-ghost">＋ Añadir fichero</button>
    </div>` : "";

  wrap.innerHTML = `
    <div class="candidato-form">
      <button type="button" class="btn-cerrar-ficha-x" id="btn-cerrar-ficha-x" title="Cerrar ficha">✕</button>
      <h3>${esEdicion ? "Editar candidato" : "Nuevo candidato"}</h3>
      <div class="ficha-cabecera">
        ${descargarCvHTML}
        ${fotoFormHTML}
        ${compartidoFichaHTML}
        ${avisoDatosHTML}
        ${resultadoTestSlotHTML}
      </div>
      ${subirCvHTML}
      <div id="single-candidato-wrap">
        <div class="form-grid">
          <div class="form-field">
            <label>Vacante</label>
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
        <details class="ficha-desplegable">
          <summary>📎 Ver otros datos (idiomas, carnet de conducir, certificaciones...)</summary>
          <div class="form-field form-field-full" style="margin-bottom:12px;">
            <div class="extra-editor" id="extra-editor-filas"></div>
            <button type="button" id="btn-extra-agregar" class="btn-mini" style="margin-top:6px;">＋ Añadir campo</button>
          </div>
        </details>
        ${archivosHTML}
        ${agregarArchivoHTML}
        <div class="form-actions">
          <button type="button" id="btn-guardar-candidato" class="btn btn-primary">Guardar</button>
          ${descargarCvBotonHTML}
          ${esEdicion ? `<a class="btn btn-ghost" id="btn-whatsapp-candidato" href="https://wa.me/${numeroWhatsapp(candidatoEditando.telefono)}" target="_blank" rel="noopener" ${candidatoEditando.telefono ? "" : "hidden"}>💬 WhatsApp</a>` : ""}
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
  wrap.querySelectorAll(".btn-borrar-legado").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (!confirm("¿Borrar este texto antiguo? No se puede deshacer una vez que guardes la ficha.")) return;
      const campo = btn.dataset.campo;
      document.querySelector(`.candidato-input[data-campo="${campo}"]`).value = "";
      btn.closest(".form-field").remove();
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
  document.getElementById("btn-cerrar-ficha-x").addEventListener("click", cerrarForm);
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
  // En "Lista + CV" la ficha ya está fija (sticky) a la vista -- desplazar
  // la página entera solo haría perder el sitio en la lista de la izquierda.
  // En "Lista" y "Tarjetas" el scroll se hace después, en
  // reposicionarFormWrapYScroll (llamada tras esto por
  // refrescarResaltadoAbierta), una vez el formulario ya se movió justo
  // debajo de la tarjeta abierta -- si se hiciera aquí, desplazaría a la
  // posición vieja (al final de la página) un instante antes de reubicarse.
}

function cerrarForm() {
  candidatoEditando = null;
  loteRevisionContexto = null;
  document.getElementById("form-wrap").innerHTML = "";
  refrescarResaltadoAbierta();
}

function avisoExtraccionHTML(n) {
  const texto = `✓ ${n} candidato${n === 1 ? "" : "s"} extraído${n === 1 ? "" : "s"} del PDF. Revisa los datos antes de guardar.`;
  return `<p class="extraccion-aviso local">${escapeHTML(texto)}</p>`;
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
// Contexto del PDF que se leyó para llegar a candidatosPorRevisar -- si hay
// rangos de página fiables (uno por candidato), se reutilizan al crear para
// adjuntar el recorte de cada uno y lanzar el enriquecido con IA en segundo
// plano (ver crearCandidatosMultiples). null si no hay PDF que adjuntar
// (p.ej. viene de un alta manual sin CV) o si la detección de página no
// coincidió candidato a candidato.
let loteRevisionContexto = null;

// Cuando el PDF trae varios candidatos, no tiene sentido rellenar el
// formulario de "un candidato" — se oculta y se muestra en su lugar una
// lista de revisión con checkboxes para crear varias fichas de golpe.
function renderRevisionMultiple(candidatos, { file = null, rangosPaginas = null, vacantePreseleccionadaId = null } = {}) {
  candidatosPorRevisar = candidatos;
  loteRevisionContexto = file ? { file, rangosPaginas } : null;
  document.getElementById("single-candidato-wrap").hidden = true;
  const wrap = document.getElementById("revision-multiple-wrap");
  wrap.innerHTML = `
    <div class="form-field" style="margin-bottom:10px; max-width:340px;">
      <label>Asignar todos a la vacante</label>
      ${vacanteSelectHTML(vacantePreseleccionadaId ?? vacantePreseleccionada(), "revision-vacante-select")}
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
    .map((el) => ({ idx: Number(el.dataset.idx), campos: candidatosPorRevisar[Number(el.dataset.idx)] }));
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
  const mapeo = [];
  for (const { idx, campos } of seleccionados) {
    const res = await fetch(`${AUTH_API_BASE}/reclutamiento/candidatos`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...campos, empresa: EMPRESA, vacante_id }),
    });
    if (!res.ok) {
      errores++;
      continue;
    }
    const data = await res.json();
    const rango = loteRevisionContexto?.rangosPaginas?.[idx];
    if (rango) mapeo.push({ candidato_id: data.id, pagina_inicio: rango[0], pagina_fin: rango[1] });
  }
  if (errores > 0) {
    mostrarAviso(`No se pudieron crear ${errores} de ${seleccionados.length} candidatos. Revisa la conexión e inténtalo de nuevo.`);
    btn.disabled = false;
    btn.textContent = "Crear candidatos seleccionados";
    return;
  }
  // Adjunta a cada candidato nuevo su recorte del PDF y lanza el enriquecido
  // con IA en segundo plano -- mismo mecanismo que "Adjuntar PDF a fichas
  // existentes" (ver adjuntar_pdf_lote_confirmar_route), solo que aquí las
  // fichas se acaban de crear en vez de ya existir.
  if (mapeo.length && loteRevisionContexto?.file) {
    const vacante = vacante_id ? vacantesTodasCache.find((v) => v.id === vacante_id) : null;
    const titulo = vacante ? `${vacante.puesto}${vacante.centro ? ` · ${vacante.centro}` : ""}` : "Candidatos nuevos";
    const formData = new FormData();
    formData.append("file", loteRevisionContexto.file);
    formData.append("mapeo", JSON.stringify(mapeo));
    formData.append("titulo", titulo);
    await fetch(`${AUTH_API_BASE}/reclutamiento/candidatos/adjuntar-pdf-lote/confirmar`, { method: "POST", body: formData }).catch(() => null);
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
  // ya_enriquecido lo calcula el backend mirando si formacion_json/
  // experiencia_json ya tienen algo -- así el reclutador no tiene que
  // llevar la cuenta de a quién le tocó ya: se desmarcan solos.
  const yaListos = encontrados.filter((it) => it.ya_enriquecido).length;
  resultadoWrap.innerHTML = `
    ${avisoExtraccionHTML(items.length)}
    <p class="staff-hint">${encontrados.length} coincidencia${encontrados.length === 1 ? "" : "s"} encontrada${encontrados.length === 1 ? "" : "s"} de ${items.length}${noEncontrados ? ` (${noEncontrados} sin ficha con ese nombre exacto -- no se les adjunta nada)` : ""}.
    ${data.division_disponible ? "Se ha detectado en qué páginas está cada uno -- se adjunta solo esa parte del PDF (puedes corregir el rango si hace falta)." : "No se pudo dividir el PDF de forma fiable -- se adjuntará el PDF completo a cada ficha encontrada, como antes."}
    ${yaListos ? ` ${yaListos} ya tienen formación/experiencia extraída de una tanda anterior -- se han desmarcado solas, no se van a repasar salvo que las marques a mano.` : ""}</p>
    ${encontrados.length ? `<div class="lote-saltar-fila">
      <button type="button" id="btn-lote-marcar-todos" class="btn-mini">Marcar todos</button>
      <button type="button" id="btn-lote-desmarcar-todos" class="btn-mini">Desmarcar todos</button>
    </div>` : ""}
    <ul class="lote-lista">
      ${items.map((it, i) => {
        if (!it.candidato_id) return `<li class="lote-sin-match">✗ ${escapeHTML(it.nombre)}</li>`;
        return `
        <li class="lote-ok">
          <label class="lote-ok-label">
            <input type="checkbox" class="lote-check" data-idx="${i}" ${it.ya_enriquecido ? "" : "checked"}>
            ${escapeHTML(it.nombre)}
          </label>
          ${it.ya_enriquecido ? `<span class="lote-ya-listo">✓ ya extraído</span>` : ""}
          ${data.division_disponible ? `
            <span class="lote-paginas">
              págs. <input type="number" min="1" class="lote-pagina-inicio" data-idx="${i}" value="${it.pagina_inicio}" style="width:44px;">
              a <input type="number" min="1" class="lote-pagina-fin" data-idx="${i}" value="${it.pagina_fin}" style="width:44px;">
            </span>` : ""}
        </li>`;
      }).join("")}
    </ul>
    ${encontrados.length ? `<button type="button" id="btn-confirmar-lote" class="btn btn-primary">Adjuntar PDF a las fichas marcadas</button>` : ""}
    <div id="lote-progreso"></div>`;
  if (encontrados.length) {
    document.getElementById("btn-confirmar-lote").addEventListener("click", () => confirmarAdjuntarLote(items));
    document.getElementById("btn-lote-marcar-todos").addEventListener("click", () => {
      resultadoWrap.querySelectorAll(".lote-check").forEach((chk) => (chk.checked = true));
    });
    document.getElementById("btn-lote-desmarcar-todos").addEventListener("click", () => {
      resultadoWrap.querySelectorAll(".lote-check").forEach((chk) => (chk.checked = false));
    });
  }
}

async function confirmarAdjuntarLote(items) {
  const btn = document.getElementById("btn-confirmar-lote");
  const progreso = document.getElementById("lote-progreso");
  btn.disabled = true;
  progreso.textContent = "Recortando y adjuntando...";
  // Solo entran los marcados -- desmarcar a quien ya se reextrajo en una
  // tanda anterior (ver btn-lote-aplicar-desde) hace que ni se le vuelva a
  // adjuntar el PDF ni se gaste tiempo/cuota de IA repasándolo.
  const mapeo = items
    .map((it, i) => {
      if (!it.candidato_id) return null;
      const checkbox = document.querySelector(`.lote-check[data-idx="${i}"]`);
      if (checkbox && !checkbox.checked) return null;
      const inputInicio = document.querySelector(`.lote-pagina-inicio[data-idx="${i}"]`);
      const inputFin = document.querySelector(`.lote-pagina-fin[data-idx="${i}"]`);
      return {
        candidato_id: it.candidato_id,
        pagina_inicio: inputInicio ? Number(inputInicio.value) : it.pagina_inicio || null,
        pagina_fin: inputFin ? Number(inputFin.value) : it.pagina_fin || null,
      };
    })
    .filter(Boolean);
  if (mapeo.length === 0) {
    progreso.textContent = "No hay ninguna ficha marcada para adjuntar.";
    btn.disabled = false;
    return;
  }
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
  btn.remove();
  await loadCandidatos();
  // El relleno con IA (formación/experiencia y demás huecos) va en segundo
  // plano en el servidor -- no se espera aquí a que termine (eso fue lo que
  // tumbó el sitio antes), pero sí se puede sondear cada pocos segundos
  // cuántos lleva hechos para mostrar un contador real (3/37...).
  if (data.lote_id && data.procesando_relleno) {
    sondearProgresoLote(data.lote_id, data.adjuntados, data.procesando_relleno, progreso);
  } else {
    progreso.textContent = `Listo: PDF adjuntado a ${data.adjuntados} ficha(s).`;
  }
}

// Texto corto de "cuánto falta" -- null/0 significa que aún no hay datos
// suficientes para estimar (primer candidato del lote todavía en curso).
function formatEtaSegundos(segundos) {
  if (!segundos) return "";
  if (segundos < 60) return ` · ${segundos} s restantes`;
  const min = Math.round(segundos / 60);
  return ` · ~${min} min restante${min === 1 ? "" : "s"}`;
}

async function sondearProgresoLote(loteId, adjuntados, total, progresoEl) {
  progresoEl.textContent = `Listo: PDF adjuntado a ${adjuntados} ficha(s). Rellenando con IA: 0/${total}...`;
  const intervalo = setInterval(async () => {
    const res = await fetch(`${AUTH_API_BASE}/reclutamiento/candidatos/adjuntar-pdf-lote/progreso/${loteId}`);
    if (!res.ok) {
      clearInterval(intervalo);
      return;
    }
    const p = await res.json();
    progresoEl.textContent = `Listo: PDF adjuntado a ${adjuntados} ficha(s). Rellenando con IA: ${p.procesados}/${p.total}...${formatEtaSegundos(p.eta_segundos)}`;
    if (p.terminado) {
      clearInterval(intervalo);
      progresoEl.textContent = `Listo: PDF adjuntado a ${adjuntados} ficha(s). Relleno con IA terminado: ${p.procesados}/${p.total}.`;
      loadCandidatos();
    }
  }, 2000);
}

async function extraerCvYRellenar() {
  const input = document.getElementById("input-cv-nuevo");
  const avisoWrap = document.getElementById("extraccion-aviso-wrap");
  if (!input.files.length) {
    avisoWrap.innerHTML = `<p class="extraccion-aviso local">Selecciona primero un PDF.</p>`;
    return;
  }
  await procesarPdfNuevosCandidatos(input.files[0], avisoWrap, {});
}

// Lee el PDF con el método local -- instantáneo, sin esperas. Si trae un
// único candidato se mantiene la revisión de siempre antes de guardar; si
// son varios, no tiene sentido hacer esperar al reclutador por un PDF de
// 30-50 CVs: se crean ya con estos datos y se completan en segundo plano
// nada más crearlos (ver crearCandidatosMultiples).
async function procesarPdfNuevosCandidatos(file, avisoWrap, { vacantePreseleccionadaId = null } = {}) {
  avisoWrap.innerHTML = `<p class="staff-hint">Leyendo el CV...</p>`;
  const formData = new FormData();
  formData.append("file", file);
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

  if (candidatos.length === 1) {
    avisoWrap.innerHTML = avisoExtraccionHTML(candidatos.length);
    rellenarFormConCandidato(candidatos[0]);
    document.getElementById("input-cv-nuevo").dataset.pendingUpload = "1";
    const selectVacante = document.getElementById("candidato-vacante-form");
    if (vacantePreseleccionadaId && selectVacante) selectVacante.value = String(vacantePreseleccionadaId);
    return;
  }

  avisoWrap.innerHTML = `<p class="extraccion-aviso local">✓ ${candidatos.length} candidatos detectados.</p>`;
  renderRevisionMultiple(candidatos, {
    file,
    rangosPaginas: data.division_disponible ? data.rangos_paginas : null,
    vacantePreseleccionadaId,
  });
}

// Re-lee un PDF que YA está adjunto a esta ficha -- útil cuando una mejora
// del extractor deja desactualizada una ficha que se procesó antes del
// arreglo. Rellena el formulario para revisar, igual que al subir un CV
// nuevo -- no guarda nada por su cuenta.
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
  avisoWrap.innerHTML = avisoExtraccionHTML(1);
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
  await refreshVacantes();
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
let candidatosSeleccionadosIds = new Set();
let ultimosCandidatosCargados = [];
let candidatosFiltroEstado = "";
// Paginación de "Base de candidatos" -- puramente en el cliente (ya se
// cargan todos los candidatos que cumplen el filtro del servidor de una
// vez), el tamaño de página elegido se recuerda entre sesiones.
let candidatosPagina = 1;
let candidatosPorPagina = Number(localStorage.getItem("kt-candidatos-por-pagina")) || 20;
// "": recientes primero (orden del servidor, por última actualización).
let candidatosOrden = localStorage.getItem("kt-candidatos-orden") || "";
// tarjetas | lista | combinada (ver .vista-combinada en compartidos.html).
let candidatosVista = localStorage.getItem("kt-candidatos-vista") || "lista";
// true para quien no tiene el módulo completo (informes/saona_informes) --
// solo ve "Compartidos conmigo/por ti", así que en su ficha se ocultan las
// acciones de gestión de ficheros que no le sirven (ver renderForm). Se fija
// en initBaseCandidatos, ANTES de que loadCompartidos pueda pintar ninguna
// ficha, así que siempre está resuelto quien lo consulte.
let esUsuarioRestringido = false;
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
  const seleccionada = candidatosSeleccionadosIds.has(c.id);
  const abierta = candidatoEditando && candidatoEditando.id === c.id;
  const checkbox = `<input type="checkbox" class="candidato-mini-checkbox" ${seleccionada ? "checked" : ""}>`;
  const fotoHTML = c.tiene_foto
    ? `<img class="candidato-mini-foto" src="${AUTH_API_BASE}/reclutamiento/candidatos/${c.id}/foto" alt="">`
    : `<span class="candidato-mini-foto candidato-mini-foto-vacia">${escapeHTML((c.nombre_completo || "?").trim()[0] || "?")}</span>`;
  const compartidos = c.compartidos || [];
  const compartidoHTML = compartidos.length > 0
    ? `<p class="candidato-mini-compartido">🔗 Compartido con: ${escapeHTML(compartidos.map((x) => x.nombre).join(", "))}</p>`
    : "";
  return `
    <div class="candidato-mini-card ${seleccionada ? "seleccionada" : ""} ${abierta ? "abierta" : ""}" data-candidato-id="${c.id}">
      <div class="candidato-mini-card-fila">
        <span class="candidato-mini-checkbox-col">${checkbox}</span>
        ${fotoHTML}
        <div class="candidato-mini-card-info">
          <h4>${escapeHTML(c.nombre_completo || "(sin nombre)")} ${estadoBadgeHTML(c.estado)} ${resultadoBadgeHTML(c.test_resultado)} ${!c.telefono || !c.email ? `<span title="Faltan datos de contacto (${!c.telefono ? "teléfono" : ""}${!c.telefono && !c.email ? " y " : ""}${!c.email ? "email" : ""})">⚠️</span>` : ""}</h4>
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
  barra.hidden = n === 0;
  if (n === 0) return;
  contador.textContent = `${n} candidato${n === 1 ? "" : "s"} seleccionado${n === 1 ? "" : "s"}`;
  const sinSeleccion = n === 0;
  btnWhatsapp.hidden = sinSeleccion;
  btnWhatsapp.innerHTML = `${ICONO_WHATSAPP}WhatsApp (${n})`;
  btnMailto.hidden = sinSeleccion;
  btnMailto.innerHTML = `${ICONO_MAILTO}Email (${n})`;
  btnCompartir.disabled = sinSeleccion;
  btnAsignarVacante.disabled = sinSeleccion;
  document.getElementById("btn-exportar-excel-seleccionados").disabled = sinSeleccion;
  document.getElementById("btn-descargar-pdfs-seleccionados").disabled = sinSeleccion;
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

// Un único PDF con el CV de cada seleccionado, en el MISMO orden en que se
// fueron marcando (candidatosSeleccionadosIds es un Set -- conserva el orden
// de inserción, así que [...] ya da ese orden sin más) -- cada uno con el
// PDF que le tocaría en su ficha individual (diseño propio si ya está
// enriquecido, recorte original si no), fusionados por el backend (ver
// descargar_pdfs_lote_route).
async function descargarPdfsSeleccionados() {
  const ids = [...candidatosSeleccionadosIds];
  if (ids.length === 0) return;
  const btn = document.getElementById("btn-descargar-pdfs-seleccionados");
  const textoOriginal = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Generando PDF...";
  try {
    const res = await fetch(`${AUTH_API_BASE}/reclutamiento/candidatos/descargar-pdfs-lote`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ candidato_ids: ids }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      mostrarAviso(err.detail || "No se pudieron descargar los PDF.");
      return;
    }
    const omitidosHeader = res.headers.get("X-Omitidos");
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `CVs seleccionados (${ids.length}).pdf`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    if (omitidosHeader) {
      const omitidos = JSON.parse(omitidosHeader);
      mostrarAviso(`El PDF se descargó, pero no se pudo incluir el CV de: ${omitidos.join(", ")}.`);
    }
  } finally {
    btn.disabled = false;
    btn.textContent = textoOriginal;
  }
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
  deseleccionarTodosCandidatos();
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
  deseleccionarTodosCandidatos();
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
  // Mueve gente dentro/fuera de una vacante -- el contador de candidatos de
  // su tarjeta (vacanteMiniCardHTML) se quedaba con el número de cuando se
  // cargó la lista si no se refresca aquí (bug real: se quedaba "10
  // candidatos" aunque se hubieran ido añadiendo más).
  await refreshVacantes();
  if (origenAsignarVacante === "compartidos") {
    modoSeleccionCompartidos = false;
    compartidosSeleccionadosIds.clear();
    await loadCompartidos();
  } else {
    deseleccionarTodosCandidatos();
    await loadCandidatos();
  }
}

let columnasExportablesCache = null;
let origenExportarExcel = "grid";
let idsExportarExcelFijos = []; // para origen "vacante-compartida": lista ya cerrada, no un Set de selección
const COLUMNAS_EXPORTAR_POR_DEFECTO = ["nombre_completo", "telefono", "email", "vacante", "test_resultado"];

// idsFijos: solo se usa con origen "vacante-compartida" -- exporta TODOS
// los candidatos de esa solicitud de una vez (botón por tarjeta), sin pasar
// por una selección con checkboxes.
async function abrirModalExportarExcel(origen = "grid", idsFijos = []) {
  const ids = origen === "compartidos-conmigo" ? compartidosConmigoSeleccionadosIds
    : origen === "vacante-compartida" ? new Set(idsFijos)
    : candidatosSeleccionadosIds;
  if (ids.size === 0) return;
  origenExportarExcel = origen;
  idsExportarExcelFijos = idsFijos;
  if (!columnasExportablesCache) {
    columnasExportablesCache = await fetch(`${AUTH_API_BASE}/reclutamiento/candidatos/columnas-exportables`).then((r) => r.json());
  }
  document.getElementById("exportar-excel-columnas").innerHTML = Object.entries(columnasExportablesCache)
    .map(
      ([clave, etiqueta]) =>
        `<label><input type="checkbox" value="${clave}" ${COLUMNAS_EXPORTAR_POR_DEFECTO.includes(clave) ? "checked" : ""}> ${escapeHTML(etiqueta)}</label>`
    )
    .join("");
  document.getElementById("exportar-excel-modal").classList.add("visible");
}

function cerrarModalExportarExcel() {
  document.getElementById("exportar-excel-modal").classList.remove("visible");
}

async function confirmarExportarExcel() {
  const columnas = Array.from(document.querySelectorAll("#exportar-excel-columnas input:checked")).map((i) => i.value);
  if (columnas.length === 0) {
    mostrarAviso("Elige al menos un dato para exportar.");
    return;
  }
  const ids = origenExportarExcel === "compartidos-conmigo" ? [...compartidosConmigoSeleccionadosIds]
    : origenExportarExcel === "vacante-compartida" ? idsExportarExcelFijos
    : [...candidatosSeleccionadosIds];
  const res = await fetch(`${AUTH_API_BASE}/reclutamiento/candidatos/exportar-excel`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ candidato_ids: [...ids], columnas }),
  });
  if (!res.ok) {
    mostrarAviso("No se pudo generar el Excel.");
    return;
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "candidatos.xlsx";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  cerrarModalExportarExcel();
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
  let visibles = ultimosCandidatosCargados;
  if (filtro === "apto") visibles = visibles.filter((c) => c.test_resultado && !c.test_resultado.includes("No apto"));
  else if (filtro === "sin_test") visibles = visibles.filter((c) => !c.test_resultado);
  else if (filtro === "no_apto") visibles = visibles.filter((c) => c.test_resultado && c.test_resultado.includes("No apto"));
  if (candidatosOrden === "nombre_asc" || candidatosOrden === "nombre_desc") {
    visibles = [...visibles].sort((a, b) => (a.nombre_completo || "").localeCompare(b.nombre_completo || "", "es"));
    if (candidatosOrden === "nombre_desc") visibles.reverse();
  }
  return visibles;
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

// Cablea los botones ".vista-toggle-btn" que haya dentro de `container` en
// ESTE momento -- hay hasta dos grupos de estos botones en la página (uno
// fijo en la barra de Base de candidatos, otro que se repinta cada vez que
// se recarga Compartidos), y cada uno necesita su propio cableado porque
// wrap.innerHTML destruye los listeners de los botones viejos al repintar.
// `onChange` es lo que hace falta rehacer tras cambiar de vista -- para
// Base de candidatos hay que repaginar (renderCandidatosGrid), para
// Compartidos basta con reaplicar clases (aplicarVistaGlobal, que ya
// actualiza TODOS los .candidatos-grid de la página, no solo el de aquí).
function wireVistaToggle(container, onChange) {
  container.querySelectorAll(".vista-toggle-btn").forEach((b) => {
    b.addEventListener("click", () => {
      candidatosVista = b.dataset.vista;
      localStorage.setItem("kt-candidatos-vista", candidatosVista);
      onChange();
    });
  });
}

// candidatosVista (tarjetas/lista/combinada) es una preferencia PERSONAL
// compartida entre "Base de candidatos" y "Compartidos conmigo/por ti" --
// da igual desde qué toggle se cambie (puede haber dos, ver
// wireVistaToggle), y afecta a TODOS los .candidatos-grid de la página a la
// vez (el de Base de candidatos y los que van dentro de cada tanda/
// solicitud compartida en Compartidos), no solo al que originó el clic.
function aplicarVistaGlobal() {
  document.querySelectorAll(".vista-toggle-btn").forEach((b) => {
    b.classList.toggle("activo", b.dataset.vista === candidatosVista);
  });
  document.querySelectorAll(".candidatos-grid").forEach((g) => {
    g.classList.toggle("candidatos-lista", candidatosVista !== "tarjetas");
  });
  document.querySelector(".compartidos-wrap")?.classList.toggle("vista-combinada", candidatosVista === "combinada");
  // Sin scroll -- esto se llama en CADA repintado de la lista (marcar una
  // casilla, filtrar, paginar...), no solo al abrir una ficha. Si hiciera
  // scroll aquí, cualquier clic que repintara la lista desplazaría la
  // página sin que nadie lo pidiera (ver reposicionarFormWrapYScroll, que sí
  // hace scroll pero solo se llama justo después de abrir una ficha).
  reposicionarFormWrap();
}

// #form-wrap vive normalmente justo después de #reclu-candidatos-wrap (su
// sitio de siempre en el HTML). En vista Lista lo trasladamos dentro del
// grid, justo debajo de la tarjeta abierta (venga de Base de candidatos o
// de Compartidos, ver reposicionarFormWrap), para que la ficha aparezca
// "ahí mismo" en vez de al final de la página -- pero
// grid.innerHTML/wrap.innerHTML lo borrarían sin darse cuenta si se quedara
// dentro cuando se repinta la lista (buscar, filtrar, recargar
// Compartidos...), así que SIEMPRE se aparca de vuelta a su sitio antes de
// tocar esos contenedores, y se reubica después si toca (ver
// reposicionarFormWrap, llamada al final de cada repintado).
function aparcarFormWrapEnSitio() {
  const formWrap = document.getElementById("form-wrap");
  const home = document.getElementById("reclu-candidatos-wrap");
  if (formWrap && home && formWrap.previousElementSibling !== home) {
    home.insertAdjacentElement("afterend", formWrap);
  }
}

// Aparca primero (ver aparcarFormWrapEnSitio) y, en vista Lista con una
// ficha abierta, la reinserta justo debajo de la tarjeta correspondiente --
// buscándola en TODO el documento, no solo en #candidatos-grid, porque la
// ficha puede haberse abierto desde una tanda de Compartidos en vez de
// desde Base de candidatos.
// Mismo corte que la media query .compartidos-wrap.vista-combinada de
// compartidos.html -- por debajo de este ancho, Combinada deja de tener
// dos columnas de verdad (ver esa regla), así que la ficha ya no tiene
// ningún panel fijo al que ir: mejor tratarla como Lista (ver más abajo).
const ANCHO_COMBINADA_UNA_COLUMNA = "(max-width: 800px)";

// Reubica #form-wrap según la vista actual, SIN hacer scroll -- seguro de
// llamar en cualquier repintado incidental de la lista (marcar una casilla,
// filtrar, paginar...) para que una ficha ya abierta no se pierda ni quede
// mal colocada, sin mover la página bajo los pies de quien solo estaba
// marcando una casilla.
function reposicionarFormWrap() {
  aparcarFormWrapEnSitio();
  // Tarjetas se comporta igual que Lista (la ficha se abre pegada a la
  // tarjeta que se clicó -- ver el CSS .candidatos-grid:not(.candidatos-lista)
  // > #form-wrap para que ocupe la fila entera en vez de encajarse en una
  // sola columna). Combinada NO entra aquí en pantallas anchas -- #form-wrap
  // se queda aparcado como hijo directo del grid para que grid-area:ficha lo
  // posicione fijo al lado, no dentro de una tarjeta. En pantallas estrechas
  // SÍ entra (ver ANCHO_COMBINADA_UNA_COLUMNA): ahí Combinada ya no tiene
  // panel fijo al que ir (se apila en una columna, ver compartidos.html).
  const combinadaComoLista = candidatosVista === "combinada" && window.matchMedia(ANCHO_COMBINADA_UNA_COLUMNA).matches;
  if (candidatosVista === "combinada" && !combinadaComoLista) return;
  const formWrap = document.getElementById("form-wrap");
  if (!candidatoEditando) {
    // Alta nueva: si se deja aparcado (su sitio de siempre, al final de
    // TODA la lista tras la paginación) con muchos candidatos habría que
    // hacer scroll a través de todos ellos para llegar al formulario. Lo
    // colocamos en vez de eso justo debajo de la barra de herramientas
    // donde vive el botón "+ Nuevo candidato" (ese botón solo existe en
    // Base de candidatos, así que #candidatos-contador-filtro siempre
    // está disponible aquí).
    const contador = document.getElementById("candidatos-contador-filtro");
    if (formWrap && contador) {
      contador.insertAdjacentElement("afterend", formWrap);
    }
    return;
  }
  const cardAbierta = document.querySelector(`.candidato-mini-card[data-candidato-id="${candidatoEditando.id}"]`);
  if (formWrap && cardAbierta) {
    cardAbierta.insertAdjacentElement("afterend", formWrap);
  }
}

// Como reposicionarFormWrap, pero ADEMÁS hace scroll hasta el formulario --
// solo se llama justo después de abrir una ficha (editar o alta nueva), no
// desde repintados incidentales (eso es lo que reposicionarFormWrap ya
// cubre sin mover la página).
function reposicionarFormWrapYScroll() {
  reposicionarFormWrap();
  const combinadaComoLista = candidatosVista === "combinada" && window.matchMedia(ANCHO_COMBINADA_UNA_COLUMNA).matches;
  if (candidatosVista === "combinada" && !combinadaComoLista) return;
  const formWrap = document.getElementById("form-wrap");
  if (!formWrap) return;
  formWrap.scrollIntoView({ behavior: "smooth", block: candidatoEditando ? "nearest" : "start" });
}

function renderCandidatosGrid() {
  aparcarFormWrapEnSitio();
  const grid = document.getElementById("candidatos-grid");
  const visibles = candidatosFiltradosPorApto();
  // Los contadores de arriba (Todos/Pendiente/Entrevistado...) solo cuentan
  // por estado -- no se mueven al tocar "Solo aptos"/"Solo no aptos"/"Sin
  // responder test", así que no sirven para saber cuántos quedan con ESE
  // filtro puesto. Este de aquí sí se recalcula con cada filtro (incluida
  // la búsqueda y la vacante, ya aplicadas en ultimosCandidatosCargados).
  const contadorFiltro = document.getElementById("candidatos-contador-filtro");
  if (contadorFiltro) {
    const difiere = visibles.length !== ultimosCandidatosCargados.length;
    contadorFiltro.textContent = `${visibles.length} candidato${visibles.length === 1 ? "" : "s"} con este filtro` +
      (difiere ? ` (de ${ultimosCandidatosCargados.length} en esta pestaña)` : "");
  }
  const totalPaginas = Math.max(1, Math.ceil(visibles.length / candidatosPorPagina));
  if (candidatosPagina > totalPaginas) candidatosPagina = totalPaginas;
  const inicio = (candidatosPagina - 1) * candidatosPorPagina;
  const pagina = visibles.slice(inicio, inicio + candidatosPorPagina);
  grid.innerHTML = pagina.length
    ? pagina.map(candidatoMiniCardHTML).join("")
    : `<p class="staff-hint">${ultimosCandidatosCargados.length ? "Ningún candidato coincide con el filtro de aptos." : "Todavía no hay candidatos en la base de datos."}</p>`;
  renderCandidatosPaginacion(visibles.length, totalPaginas);
  aplicarVistaGlobal();
  grid.querySelectorAll(".candidato-mini-card").forEach((card) => {
    const id = Number(card.dataset.candidatoId);
    card.querySelector(".candidato-mini-checkbox").addEventListener("click", (e) => {
      e.stopPropagation();
      if (candidatosSeleccionadosIds.has(id)) candidatosSeleccionadosIds.delete(id);
      else candidatosSeleccionadosIds.add(id);
      actualizarBotonWhatsappSeleccionados();
      renderCandidatosGrid();
    });
    card.addEventListener("click", (e) => {
      if (e.target.closest(".candidato-mini-contacto-select")) return;
      abrirEdicionCandidato(card.dataset.candidatoId);
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

// Nunca se envía nada desde el servidor: se abre el cliente de correo del
// propio usuario, que es quien de verdad manda el email desde su cuenta.
// Antes esto era UN solo mailto: con todos los correos en copia oculta
// (bcc) -- con una plantilla compartida así, {nombre}/{centro}/etc. no se
// podían sustituir de verdad (todo el mundo recibía el mismo cuerpo, con
// los corchetes tal cual, literalmente "Hola {nombre}"). Ahora funciona
// igual que la campaña de WhatsApp: un enlace mailto: por candidato, cada
// uno con su propio "Enviar", así los placeholders sí se rellenan por
// persona (uno por uno, pero sin tener que redactar cada mensaje a mano).
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
  // Mismo criterio que onCambiaTestCampana (WhatsApp): si el test tiene un
  // enlace corto configurado, se usa ese en vez del nuestro largo.
  const testSeleccionado = campanaEmailTestsAbiertos.find((t) => String(t.id).padStart(4, "0") === select.value);
  campanaEmailEnlaceTest = select.value
    ? (testSeleccionado?.enlace_corto || `${location.origin}/encuesta.html?slug=${select.value}`)
    : "";
  campanaEmailTestIdSeleccionado = select.value ? Number(select.value) : null;
  const cuerpo = document.getElementById("campana-email-cuerpo");
  if (select.value && !cuerpo.value.includes("{enlace}")) {
    cuerpo.value = `${cuerpo.value}\n\n{enlace}`;
  }
  actualizarEnlacesCampanaEmail();
}

function candidatoEmailRowHTML(c, i) {
  return `
    <div class="candidato-mini-card candidato-whatsapp-row">
      <div>
        <h4>${escapeHTML(c.nombre_completo || `Candidato ${i + 1}`)}</h4>
        <p>${escapeHTML(c.email)}</p>
      </div>
      <a class="btn btn-ghost btn-email-campana" data-idx="${i}" data-candidato-id="${c.id}" target="_blank" rel="noopener">${ICONO_MAILTO} Enviar</a>
    </div>`;
}

function actualizarEnlacesCampanaEmail() {
  const asuntoPlantilla = document.getElementById("campana-email-asunto").value;
  const cuerpoPlantilla = document.getElementById("campana-email-cuerpo").value;
  campanaEmailCandidatos.forEach((c, i) => {
    const link = document.querySelector(`.btn-email-campana[data-idx="${i}"]`);
    if (!link) return;
    const asunto = sustituirPlaceholders(asuntoPlantilla, c, campanaEmailEnlaceTest);
    const cuerpo = sustituirPlaceholders(cuerpoPlantilla, c, campanaEmailEnlaceTest);
    link.href = `mailto:${encodeURIComponent(c.email)}?subject=${encodeURIComponent(asunto)}&body=${encodeURIComponent(cuerpo)}`;
  });
}

function cerrarCampanaEmail() {
  campanaEmailCandidatos = [];
  campanaEmailEnlaceTest = "";
  document.getElementById("campana-email-wrap").innerHTML = "";
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
        Escribe el asunto/cuerpo una sola vez — usa <code>{nombre}</code>, <code>{nombre_completo}</code>, <code>{mail}</code>,
        <code>{telefono}</code>, <code>{vacante}</code> o <code>{centro}</code> para insertar datos de cada candidato
        ${campanaEmailTestsAbiertos.length ? `y <code>{enlace}</code> para el enlace del test que elijas abajo` : ""}.
        Cada botón "Enviar" abre tu cliente de correo ya escrito para esa persona; tú confirmas el envío allí.
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
      <p class="staff-hint">${conEmail.length} de ${candidatos.length} candidatos tienen email guardado.</p>
      <div class="candidatos-grid">${conEmail.map(candidatoEmailRowHTML).join("")}</div>
      <div class="form-actions">
        <button type="button" id="btn-cerrar-campana-email" class="btn btn-ghost">Cerrar</button>
      </div>
    </div>`;
  document.getElementById("campana-email-asunto").addEventListener("input", actualizarEnlacesCampanaEmail);
  document.getElementById("campana-email-cuerpo").addEventListener("input", actualizarEnlacesCampanaEmail);
  document.getElementById("btn-cerrar-campana-email").addEventListener("click", cerrarCampanaEmail);
  const testSelect = document.getElementById("campana-email-test");
  if (testSelect) testSelect.addEventListener("change", onCambiaTestCampanaEmail);
  // El marcado de "invitado al test" se dispara en el clic real de Enviar
  // (no al elegir el test arriba), igual que en la campaña de WhatsApp.
  wrap.querySelectorAll(".btn-email-campana").forEach((btn) => {
    btn.addEventListener("click", () => marcarInvitadoTest([Number(btn.dataset.candidatoId)], campanaEmailTestIdSeleccionado));
  });
  actualizarEnlacesCampanaEmail();
  wrap.scrollIntoView({ behavior: "smooth", block: "start" });
}

function abrirMailtoSeleccionados() {
  const candidatos = ultimosCandidatosCargados.filter((c) => candidatosSeleccionadosIds.has(c.id));
  abrirCampanaEmail(candidatos);
}

// Repinta la lista de "Base de candidatos" para que la tarjeta abierta se
// resalte (ver .candidato-mini-card.abierta) -- se salta a sí misma cuando
// la lista ni siquiera está visible (usuario sin el módulo completo que
// solo abre fichas desde "Compartidos", ver reclu-candidatos-wrap).
// conScroll: solo true justo después de ABRIR una ficha (editar o alta
// nueva) -- con el valor por defecto (false), como al cerrar, se reposiciona
// sin mover la página.
function refrescarResaltadoAbierta(conScroll = false) {
  const wrap = document.getElementById("reclu-candidatos-wrap");
  if (wrap && !wrap.hidden) {
    renderCandidatosGrid(); // ya reposiciona sin scroll (ver aplicarVistaGlobal)
    if (conScroll) reposicionarFormWrapYScroll();
  } else if (conScroll) {
    // Sin el módulo completo no hay #candidatos-grid que repintar, pero la
    // ficha puede haberse abierto desde una tarjeta de Compartidos -- solo
    // hace falta reposicionar #form-wrap, no recargar toda la lista de
    // Compartidos (sería un viaje de red y un parpadeo innecesarios, los
    // datos no cambiaron).
    reposicionarFormWrapYScroll();
  } else {
    reposicionarFormWrap();
  }
}

async function abrirEdicionCandidato(candidatoId) {
  const candidato = await fetch(`${AUTH_API_BASE}/reclutamiento/candidatos/${candidatoId}`).then((r) => r.json());
  candidatoEditando = candidato;
  renderForm();
  refrescarResaltadoAbierta(true);
}

function abrirNuevoCandidato() {
  candidatoEditando = null;
  renderForm();
  refrescarResaltadoAbierta(true);
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

async function reextraerTodosLocal() {
  // Solo sobre quien está delante AHORA con el filtro puesto (búsqueda,
  // vacante, estado, apto...) -- no sobre la base entera: con miles de
  // candidatos, re-extraer a todo el mundo cada vez que hace falta corregir
  // solo un puñado recién importado sería carísimo en tiempo.
  const idsFiltrados = candidatosFiltradosPorApto().map((c) => c.id);
  if (!idsFiltrados.length) {
    await mostrarAviso("No hay ningún candidato con el filtro actual puesto.");
    return;
  }
  if (!confirm(`Esto vuelve a leer el CV ya guardado de los ${idsFiltrados.length} candidato(s) que coinciden con el filtro actual y sustituye formación/experiencia/idiomas por lo último que encuentre. ¿Continuar?`)) return;
  const btn = document.getElementById("btn-reextraer-todos");
  const textoOriginal = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Iniciando...";
  let res;
  try {
    res = await fetch(`${AUTH_API_BASE}/reclutamiento/candidatos/reextraer-todos?empresa=${EMPRESA}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ candidato_ids: idsFiltrados }),
    });
  } catch {
    res = null;
  }
  if (!res || !res.ok) {
    mostrarAviso("No se pudo iniciar la re-extracción.");
    btn.disabled = false;
    btn.textContent = textoOriginal;
    return;
  }
  const data = await res.json();
  if (!data.lote_id) {
    mostrarAviso("No hay ningún candidato con un PDF adjunto para re-extraer.");
    btn.disabled = false;
    btn.textContent = textoOriginal;
    return;
  }
  mostrarAviso(`Re-extrayendo ${data.total} candidato(s) en segundo plano...`);
  const intervalo = setInterval(async () => {
    const r = await fetch(`${AUTH_API_BASE}/reclutamiento/candidatos/adjuntar-pdf-lote/progreso/${data.lote_id}`);
    if (!r.ok) {
      clearInterval(intervalo);
      btn.disabled = false;
      btn.textContent = textoOriginal;
      return;
    }
    const p = await r.json();
    btn.textContent = `Reextrayendo ${p.procesados}/${p.total}...`;
    if (p.terminado) {
      clearInterval(intervalo);
      btn.disabled = false;
      btn.textContent = textoOriginal;
      mostrarAviso(`Listo: ${p.procesados}/${p.total} candidatos re-extraídos con el método local.`);
      loadCandidatos();
    }
  }, 2000);
}

async function initBaseCandidatos(user) {
  usuarioActual = user;
  const modulos = user.modulos || [];
  const tieneAcceso = modulos.includes("informes") || modulos.includes("saona_informes");
  esUsuarioRestringido = !tieneAcceso;
  const wrap = document.getElementById("reclu-candidatos-wrap");
  // El modal de exportar a Excel se usa tanto desde "Base de candidatos"
  // como desde "Compartidos conmigo" (ver btn-exportar-excel-compartidos en
  // wireCompartidosInteractivos) -- quien no tiene el módulo completo
  // también necesita esto, así que se cablea ANTES del return de abajo.
  document.getElementById("btn-exportar-excel-cancelar").addEventListener("click", cerrarModalExportarExcel);
  document.getElementById("btn-exportar-excel-confirmar").addEventListener("click", confirmarExportarExcel);
  if (!tieneAcceso) {
    wrap.hidden = true;
    return;
  }
  wrap.hidden = false;
  document.getElementById("btn-nuevo-candidato").addEventListener("click", abrirNuevoCandidato);
  document.getElementById("btn-revincular-tests").addEventListener("click", revincularTests);
  document.getElementById("btn-adjuntar-lote").addEventListener("click", abrirAdjuntarLote);
  document.getElementById("btn-reextraer-todos").addEventListener("click", reextraerTodosLocal);
  document.getElementById("btn-recordatorio-pendientes").addEventListener("click", abrirRecordatorioPendientes);
  document.getElementById("btn-nueva-vacante").addEventListener("click", abrirNuevaVacante);
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
  document.getElementById("btn-exportar-excel-seleccionados").addEventListener("click", () => abrirModalExportarExcel("grid"));
  document.getElementById("btn-descargar-pdfs-seleccionados").addEventListener("click", descargarPdfsSeleccionados);
  document.getElementById("btn-cambiar-destinatario-cancelar").addEventListener("click", cerrarModalCambiarDestinatario);
  document.getElementById("btn-cambiar-destinatario-confirmar").addEventListener("click", confirmarCambiarDestinatario);
  document.getElementById("btn-fusionar-vacante-cancelar").addEventListener("click", cerrarModalFusionarVacante);
  document.getElementById("btn-fusionar-vacante-confirmar").addEventListener("click", confirmarFusionarVacante);
  document.getElementById("btn-compartir-vacante-cancelar").addEventListener("click", cerrarModalCompartirVacante);
  document.getElementById("btn-compartir-vacante-confirmar").addEventListener("click", confirmarCompartirVacante);
  document.getElementById("candidatos-estado-masivo").addEventListener("change", (e) => cambiarEstadoSeleccionados(e.target.value));
  document.getElementById("vacantes-filtro-estado").addEventListener("change", refreshVacantes);
  document.getElementById("vacantes-ver-archivadas").addEventListener("change", refreshVacantes);
  document.getElementById("candidatos-filtro-vacante").addEventListener("change", () => {
    renderVacantesGrid();
    loadCandidatos();
  });
  document.getElementById("candidatos-filtro-apto").addEventListener("change", () => {
    candidatosPagina = 1;
    renderCandidatosGrid();
  });
  const selectOrden = document.getElementById("candidatos-orden");
  selectOrden.value = candidatosOrden;
  selectOrden.addEventListener("change", () => {
    candidatosOrden = selectOrden.value;
    localStorage.setItem("kt-candidatos-orden", candidatosOrden);
    candidatosPagina = 1;
    renderCandidatosGrid();
  });
  wireVistaToggle(document, renderCandidatosGrid);
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

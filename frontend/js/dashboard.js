// Igual que entrevistas.js: una sola constante leída de la URL una vez, que
// se propaga a cada llamada a la API — así el backend (ver require_resenas y
// el middleware de main.py) sabe si debe aplicar el módulo/las tiendas de
// Krispy Kreme o las de SAONA, sin tocar cada endpoint uno a uno.
const EMPRESA = new URLSearchParams(location.search).get("empresa") === "saona" ? "saona" : "kk";

function conEmpresaURL(url) {
  const separador = url.includes("?") ? "&" : "?";
  return `${url}${separador}empresa=${EMPRESA}`;
}

async function fetchJSON(url) {
  const res = await fetch(conEmpresaURL(url));
  if (!res.ok) throw new Error(`Error ${res.status} al llamar ${url}`);
  return res.json();
}


function escapeHTML(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

// Cuando el usuario (gerente) está restringido a una sola tienda, no tiene
// sentido ofrecerle "Todas" ni un desplegable — /api/stores ya viene filtrado
// por el middleware de permisos, así que aquí solo hace falta bloquear la UI.
let tiendasPermitidas = [];

function soloGoogleQS() {
  return state.soloGoogle ? "solo_google=true" : "";
}

async function loadStores() {
  const { stores } = await fetchJSON(`${API_BASE}/stores?${soloGoogleQS()}`);
  const select = document.getElementById("filter-tienda");
  const current = select.value;
  const restringidoAUna = tiendasPermitidas.length === 1;
  const opciones = stores.map((s) => `<option value="${escapeHTML(s.tienda)}">${escapeHTML(s.tienda)} (${s.total})</option>`).join("");
  select.innerHTML = restringidoAUna ? opciones : `<option value="">Todas</option>` + opciones;
  select.disabled = restringidoAUna;
  if (restringidoAUna) {
    select.value = stores[0]?.tienda ?? "";
    state.tienda = select.value;
  } else {
    select.value = current;
  }
}

function currentTransactionsMonth() {
  const input = document.getElementById("input-transactions-month");
  return input.value || new Date().toISOString().slice(0, 7);
}

function storeRankingRowHTML(s, mesValores) {
  const tasa = s.tasa === null || s.tasa === undefined ? "—" : `${s.tasa}%`;
  const mesValor = mesValores[s.tienda];
  return `
    <tr data-tienda="${escapeHTML(s.tienda)}">
      <td>${escapeHTML(s.tienda)}</td>
      <td>${s.total.toLocaleString("es-ES")}</td>
      <td>
        <input type="number" min="0" class="transacciones-input"
               value="${mesValor ?? ""}" placeholder="—" data-tienda="${escapeHTML(s.tienda)}">
      </td>
      <td>${tasa}</td>
    </tr>
  `;
}

function avgRatingRowHTML(s) {
  return `
    <tr>
      <td>${escapeHTML(s.tienda)}</td>
      <td>${s.promedio} ★</td>
    </tr>
  `;
}

async function loadStoreRanking() {
  const mes = currentTransactionsMonth();
  // Ranking por transacciones: reseñas y tasa acotadas AL MES seleccionado
  // (igual que ya hacían las transacciones). El de valoración media usa el
  // acumulado histórico (stores sin `mes`), ya que no tiene sentido acotarlo.
  const [{ stores: storesMes }, { stores: storesTotal }, { transacciones: mesValores }] = await Promise.all([
    fetchJSON(`${API_BASE}/stores?order_by=tasa&mes=${encodeURIComponent(mes)}&${soloGoogleQS()}`),
    fetchJSON(`${API_BASE}/stores?${soloGoogleQS()}`),
    fetchJSON(`${API_BASE}/transactions?mes=${encodeURIComponent(mes)}`),
  ]);
  document.getElementById("store-ranking-list").innerHTML =
    storesMes.map((s) => storeRankingRowHTML(s, mesValores)).join("") || `<tr><td colspan="4">Sin tiendas todavía.</td></tr>`;

  const byRating = [...storesTotal].sort((a, b) => b.promedio - a.promedio);
  document.getElementById("avg-rating-list").innerHTML =
    byRating.map(avgRatingRowHTML).join("") || `<tr><td colspan="2">Sin tiendas todavía.</td></tr>`;
}

async function saveTransacciones(tienda, transacciones) {
  const mes = currentTransactionsMonth();
  await fetch(conEmpresaURL(`${API_BASE}/transactions`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tienda, mes, transacciones }),
  });
  await loadStoreRanking();
}

async function uploadTransaccionesFile(file) {
  const mes = currentTransactionsMonth();
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch(conEmpresaURL(`${API_BASE}/transactions/upload?mes=${encodeURIComponent(mes)}`), { method: "POST", body: formData });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    mostrarAviso(`No se pudo procesar el Excel: ${body.detail || res.statusText}`);
    return;
  }
  await loadStoreRanking();
}

async function uploadTakeoutZip(file) {
  const btn = document.getElementById("btn-import-takeout-label");
  if (btn) btn.textContent = "⏳ Importando…";
  try {
    const formData = new FormData();
    formData.append("file", file);
    const res = await fetch(conEmpresaURL(`${API_BASE}/import/takeout`), { method: "POST", body: formData });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      mostrarAviso(`No se pudo importar el Takeout: ${body.detail || res.statusText || `error HTTP ${res.status}`}`);
      return;
    }
    const lineas = body.tiendas
      .map((t) => `${t.tienda}: +${t.nuevas} nuevas (total ${t.total_ahora}${t.total_google ? `/${t.total_google}` : ""})`)
      .join("\n");
    mostrarAviso(`Importación completa — ${body.total_nuevas} reseñas nuevas en total.\n\n${lineas}`);
    // Se actualiza primero y por separado: si loadStores/loadStoreRanking/
    // refreshAll fallan por lo que sea, no debe arrastrar consigo la fecha
    // de última importación (que sí se guardó bien en el servidor).
    await cargarUltimaImportacionTakeout().catch((err) => console.error("No se pudo refrescar la fecha de última importación", err));
    await loadStores();
    await loadStoreRanking();
    await refreshAll();
  } finally {
    if (btn) btn.textContent = "📥 Importar Takeout";
  }
}

// Fecha/hora de la última importación de Takeout, visible para cualquiera
// con acceso a Reseñas (no solo quien la ejecutó) — se guarda en el
// servidor (ver db.get_ultima_importacion_takeout), no en localStorage.
async function cargarUltimaImportacionTakeout() {
  const el = document.getElementById("ultima-importacion-takeout");
  if (!el) return;
  try {
    const res = await fetch(`${API_BASE}/import/takeout/ultima`);
    if (!res.ok) {
      console.error("No se pudo obtener la fecha de última importación:", res.status);
      return;
    }
    const data = await res.json();
    if (!data.ultima_importacion) return;
    const fecha = new Date(`${data.ultima_importacion}Z`);
    const texto = fecha.toLocaleString("es-ES", {
      day: "2-digit", month: "2-digit", year: "2-digit", hour: "2-digit", minute: "2-digit",
    });
    el.textContent = `🕒 Última actualización: ${texto}`;
    el.hidden = false;
  } catch (err) {
    // sin conexión: se deja oculto, no bloquea el resto de la página
    console.error("No se pudo cargar la fecha de última importación:", err);
  }
}

async function loadStats() {
  const params = currentQueryParams();
  const stats = await fetchJSON(`${API_BASE}/stats?${params.toString()}`);
  document.getElementById("stat-total").textContent = stats.total.toLocaleString("es-ES");
  document.getElementById("stat-promedio").textContent = `${stats.promedio_estrellas} ★`;
  document.getElementById("stat-positivas").textContent = `${stats.porcentaje_positivas}%`;
  document.getElementById("stat-recientes").textContent = stats.resenas_recientes.toLocaleString("es-ES");
  renderDistributionChart(stats.distribucion_estrellas, stats.distribucion_por_tienda);

  const checkEl = document.getElementById("stat-total-check");
  if (stats.completo) {
    checkEl.hidden = false;
    checkEl.title = stats.total_google
      ? `100% capturado (${stats.total.toLocaleString("es-ES")} de ${stats.total_google.toLocaleString("es-ES")} según Google)`
      : "100% capturado en todas las tiendas";
  } else {
    checkEl.hidden = true;
  }
}

function renderRatingProgress(p) {
  document.getElementById("rating-true-value").textContent = p.true_rating ? p.true_rating.toFixed(3) : "—";

  const hintEl = document.getElementById("rating-need-hint");
  if (p.resenas_necesarias > 0) {
    hintEl.innerHTML = `Se necesitan <b>${p.resenas_necesarias.toLocaleString("es-ES")}</b> reseñas de 5★ seguidas para llegar a ${p.tier_siguiente.toFixed(1)} estrellas.`;
  } else if (p.true_rating) {
    hintEl.textContent = "Ya está en el nivel máximo visible.";
  } else {
    hintEl.textContent = "";
  }

  document.getElementById("rating-tier-low").textContent = p.tier_actual ? p.tier_actual.toFixed(1) : "—";
  document.getElementById("rating-tier-mid").textContent = p.true_rating ? p.true_rating.toFixed(3) : "—";
  document.getElementById("rating-tier-high").textContent = p.tier_siguiente ? p.tier_siguiente.toFixed(1) : "—";

  document.getElementById("rating-progress-fill").style.width = `${p.progreso_pct || 0}%`;
  document.getElementById("rating-progress-pct").textContent = p.true_rating ? `${p.progreso_pct}%` : "—";

  const trendEl = document.getElementById("rating-trend");
  if (p.tendencia_90d === null || p.tendencia_90d === undefined) {
    trendEl.textContent = "";
  } else {
    const sign = p.tendencia_90d > 0 ? "+" : "";
    const cls = p.tendencia_90d > 0 ? "rating-trend-up" : p.tendencia_90d < 0 ? "rating-trend-down" : "";
    trendEl.innerHTML = `90 días: ${p.true_rating_90d.toFixed(3)} → <span class="${cls}">${sign}${p.tendencia_90d.toFixed(3)}</span>`;
  }
}

async function loadRatingProgress() {
  const params = currentQueryParams();
  const progress = await fetchJSON(`${API_BASE}/rating-progress?${params.toString()}`);
  renderRatingProgress(progress);
}

async function loadTimeline() {
  const params = currentQueryParams();
  const { timeline, por_tienda } = await fetchJSON(`${API_BASE}/timeline?${params.toString()}`);
  renderTimelineChart(timeline, por_tienda);
}

// Tabla de "cuánto cambió cada tienda" — a diferencia del gráfico (que
// siempre se ve, con o sin fechas), esta sí necesita un rango Desde/Hasta
// concreto para tener sentido (son solo 2 puntos: inicio y fin).
async function loadEvolucionTabla() {
  const detalle = document.getElementById("evolucion-detalle");
  if (state.tienda || !state.dateFrom || !state.dateTo) {
    detalle.hidden = true;
    return;
  }
  const params = new URLSearchParams({ date_from: state.dateFrom, date_to: state.dateTo });
  if (state.soloGoogle) params.set("solo_google", "true");
  const { evolucion } = await fetchJSON(`${API_BASE}/timeline-evolucion?${params.toString()}`);
  detalle.hidden = evolucion.length === 0;
  if (!evolucion.length) return;

  document.getElementById("evolucion-desde").textContent = formatFechaExacta(state.dateFrom);
  document.getElementById("evolucion-hasta").textContent = formatFechaExacta(state.dateTo);
  document.getElementById("evolucion-tabla-body").innerHTML = evolucion.map(evolucionFilaHTML).join("");
}

let horarioVisible = false;

async function loadHorario() {
  if (!horarioVisible) return;
  const params = currentQueryParams();
  const data = await fetchJSON(`${API_BASE}/timeline-horas?${params.toString()}`);
  renderHoraChart(data.por_hora, data.por_tienda?.por_hora);
  renderDiaSemanaChart(data.por_dia_semana, data.por_tienda?.por_dia_semana);
  const hintEl = document.getElementById("horario-hint");
  hintEl.hidden = false;
  hintEl.textContent = data.con_hora_exacta > 0
    ? `Basado en ${data.con_hora_exacta.toLocaleString("es-ES")} reseñas con hora exacta (las importadas desde Google Takeout; las scrapeadas de Maps no la traen).`
    : "Ninguna reseña en este filtro tiene hora exacta todavía (hace falta importar un export de Google Takeout).";
}

async function loadKeywords() {
  const params = currentQueryParams({ limit: 20 });
  const { keywords } = await fetchJSON(`${API_BASE}/keywords?${params.toString()}`);
  renderKeywords(keywords);
}

function staffRowHTML(s) {
  const active = state.staff === s.nombre && (!state.tienda || state.tienda === s.tienda) ? "active" : "";
  return `
    <tr class="${active}" data-name="${escapeHTML(s.nombre)}" data-tienda="${escapeHTML(s.tienda)}">
      <td>${escapeHTML(s.nombre)}</td>
      <td>${escapeHTML(s.tienda)}</td>
      <td>${s.menciones}</td>
      <td>${s.promedio_estrellas} ★</td>
      <td>${s.porcentaje_positivas}%</td>
    </tr>
  `;
}

async function loadStaffMentions() {
  const hintEl = document.getElementById("staff-select-hint");
  hintEl.hidden = !!state.tienda;

  // El ranking en sí NUNCA se filtra por empleado (si no, al hacer clic en
  // uno desaparecerían los demás); solo por tienda/estrellas/sentimiento/fecha/buscar.
  const params = currentQueryParams();
  params.delete("staff");
  const { actuales, anteriores } = await fetchJSON(`${API_BASE}/staff-mentions?${params.toString()}`);

  document.getElementById("staff-list").innerHTML =
    actuales.map(staffRowHTML).join("") || `<tr><td colspan="5">Sin menciones para estos filtros.</td></tr>`;
  document.getElementById("staff-former-list").innerHTML =
    anteriores.map(staffRowHTML).join("") || `<tr><td colspan="5">Sin menciones para estos filtros.</td></tr>`;

  const activeEl = document.getElementById("staff-active-filter");
  document.getElementById("staff-active-name").textContent = state.staff;
  activeEl.hidden = !state.staff;
}

function selectStaff(name, tienda) {
  const mismaPersona = state.staff === name && (!state.tienda || state.tienda === tienda);
  if (mismaPersona) {
    state.staff = "";
  } else {
    state.staff = name;
    // En modo "Todas", seleccionar a alguien acota también a su tienda —
    // si no, el filtro de reseñas no sabría a qué plantilla pertenece ese
    // nombre (el mismo nombre de pila puede ser otra persona en otro local).
    if (tienda && state.tienda !== tienda) {
      state.tienda = tienda;
      document.getElementById("filter-tienda").value = tienda;
    }
  }
  state.page = 1;
  return refreshAll();
}

function clearStaffFilter() {
  state.staff = "";
  state.page = 1;
  return refreshAll();
}

// ---- Gestionar personal (admin): alta manual, sugerencia de variantes con
// IA, y salida (baja definitiva o traslado a otra tienda) — sustituye a
// STORE_STAFF fijo por tablas editables desde aquí mismo (ver personal.py).
let personalModalCache = [];
let personalTiendasCache = [];
let personalEditandoAsignacionId = null;
let personalSalidaAsignacionId = null;
let personalFusionandoAsignacionId = null;
let personalVariantesSugeridas = [];
let personalVariantesSeleccionadas = new Set();

function personalSalidaFormHTML(p) {
  const destinoOpciones = personalTiendasCache
    .filter((t) => t !== p.tienda)
    .map((t) => `<option value="${escapeHTML(t)}">${escapeHTML(t)}</option>`)
    .join("");
  const hoy = new Date().toISOString().slice(0, 10);
  return `
    <div class="salida-form" data-asignacion-id="${p.asignacion_id}">
      <label><input type="radio" name="salida-tipo-${p.asignacion_id}" value="traslado" checked> Traslado a otra tienda</label>
      <select class="salida-tienda-destino">${destinoOpciones}</select>
      <label><input type="radio" name="salida-tipo-${p.asignacion_id}" value="baja"> Salida definitiva</label>
      <label>Fecha <input type="date" class="salida-fecha" value="${hoy}"></label>
      <div class="modal-actions" style="justify-content:flex-start;">
        <button type="button" class="btn btn-primary btn-sm btn-salida-confirmar" data-asignacion-id="${p.asignacion_id}">Confirmar</button>
        <button type="button" class="btn btn-ghost btn-sm btn-salida-cancelar">Cancelar</button>
      </div>
    </div>`;
}

function personalFusionFormHTML(p) {
  const otras = personalModalCache.filter(
    (o) => o.tienda === p.tienda && o.activo && o.personal_id !== p.personal_id
  );
  if (otras.length === 0) {
    return `
      <div class="salida-form" data-fusion-asignacion-id="${p.asignacion_id}">
        <p class="personal-hint" style="margin:0 0 8px;">No hay más personal activo en ${escapeHTML(p.tienda)} con quien fusionar.</p>
        <div class="modal-actions" style="justify-content:flex-start;">
          <button type="button" class="btn btn-ghost btn-sm btn-fusion-cancelar">Cerrar</button>
        </div>
      </div>`;
  }
  const opciones = otras.map((o) => `<option value="${o.personal_id}">${escapeHTML(o.nombre_canonico)}</option>`).join("");
  return `
    <div class="salida-form" data-fusion-asignacion-id="${p.asignacion_id}">
      <p class="personal-hint" style="margin:0 0 6px;">Es la misma persona que...</p>
      <select class="fusion-destino-select">${opciones}</select>
      <div class="modal-actions" style="justify-content:flex-start;">
        <button type="button" class="btn btn-primary btn-sm btn-fusion-confirmar" data-personal-id="${p.personal_id}">Fusionar</button>
        <button type="button" class="btn btn-ghost btn-sm btn-fusion-cancelar">Cancelar</button>
      </div>
    </div>`;
}

function personalFilaHTML(p) {
  if (personalEditandoAsignacionId === p.asignacion_id) {
    return `
      <div class="personal-fila-wrap">
        <div class="personal-fila" data-asignacion-id="${p.asignacion_id}">
          <div class="personal-fila-info" style="flex:1;">
            <input type="text" class="personal-editar-nombre" value="${escapeHTML(p.nombre_canonico)}">
            <input type="text" class="personal-editar-variantes" value="${escapeHTML(p.variantes.join(", "))}" placeholder="Variantes separadas por coma">
          </div>
          <div class="personal-fila-acciones">
            <button type="button" class="btn btn-primary btn-personal-guardar-edicion" data-personal-id="${p.personal_id}">Guardar</button>
            <button type="button" class="btn btn-ghost btn-personal-cancelar-edicion">Cancelar</button>
          </div>
        </div>
      </div>`;
  }

  const chips = p.variantes.map((v) => `<span class="personal-chip">${escapeHTML(v)}</span>`).join("");
  const fechas = p.activo
    ? (p.fecha_inicio ? `Desde ${p.fecha_inicio}` : "Fecha de entrada sin registrar")
    : `${p.fecha_inicio ? `${p.fecha_inicio} → ` : ""}${p.fecha_fin || "?"} · ${p.motivo_fin === "traslado" ? "trasladada" : "baja"}`;
  const acciones = p.activo
    ? `<button type="button" class="btn btn-ghost btn-personal-editar" data-asignacion-id="${p.asignacion_id}" title="Editar nombre/variantes">✏️</button>
       <button type="button" class="btn btn-ghost btn-personal-fusionar" data-asignacion-id="${p.asignacion_id}" title="Es la misma persona que otra ficha de esta tienda">🔗 Fusionar...</button>
       <button type="button" class="btn btn-ghost btn-personal-salida" data-asignacion-id="${p.asignacion_id}">Salida...</button>`
    : `<button type="button" class="btn btn-ghost btn-personal-eliminar" data-personal-id="${p.personal_id}" title="Borrar (solo si se dio de alta por error)">🗑</button>`;

  return `
    <div class="personal-fila-wrap">
      <div class="personal-fila ${p.activo ? "" : "former"}" data-asignacion-id="${p.asignacion_id}">
        <div class="personal-fila-info">
          <b>${escapeHTML(p.nombre_canonico)}</b>${p.activo ? "" : ` <span class="personal-badge-former">ya no está aquí</span>`}
          <p>${escapeHTML(fechas)}</p>
          <div class="personal-variantes-chips">${chips}</div>
        </div>
        <div class="personal-fila-acciones">${acciones}</div>
      </div>
      ${personalSalidaAsignacionId === p.asignacion_id ? personalSalidaFormHTML(p) : ""}
      ${personalFusionandoAsignacionId === p.asignacion_id ? personalFusionFormHTML(p) : ""}
    </div>`;
}

function wirePersonalSalidaRadios() {
  document.querySelectorAll(".salida-form").forEach((form) => {
    const select = form.querySelector(".salida-tienda-destino");
    const actualizar = () => {
      const tipo = form.querySelector('input[type="radio"]:checked').value;
      select.style.display = tipo === "traslado" ? "" : "none";
    };
    form.querySelectorAll('input[type="radio"]').forEach((r) => r.addEventListener("change", actualizar));
    actualizar();
  });
}

function renderPersonalListado() {
  const grupos = {};
  for (const p of personalModalCache) (grupos[p.tienda] ||= []).push(p);
  const tiendasOrdenadas = Object.keys(grupos).sort();
  document.getElementById("personal-listado").innerHTML = tiendasOrdenadas.length
    ? tiendasOrdenadas
        .map((tienda) => {
          const filas = grupos[tienda]
            .sort((a, b) => (a.activo === b.activo ? a.nombre_canonico.localeCompare(b.nombre_canonico) : a.activo ? -1 : 1))
            .map(personalFilaHTML)
            .join("");
          return `<div class="personal-tienda-grupo"><h4>${escapeHTML(tienda)}</h4>${filas}</div>`;
        })
        .join("")
    : `<p class="personal-hint">Sin personal registrado todavía.</p>`;
  wirePersonalSalidaRadios();
}

async function loadPersonalModal() {
  const [{ personal }, { stores }] = await Promise.all([
    fetchJSON(`${API_BASE}/personal`),
    fetchJSON(`${API_BASE}/stores`),
  ]);
  personalModalCache = personal;
  personalTiendasCache = stores.map((s) => s.tienda);
  document.getElementById("personal-nuevo-tienda").innerHTML = personalTiendasCache
    .map((t) => `<option value="${escapeHTML(t)}">${escapeHTML(t)}</option>`)
    .join("");
  renderPersonalListado();
}

function abrirModalPersonal() {
  personalEditandoAsignacionId = null;
  personalSalidaAsignacionId = null;
  personalFusionandoAsignacionId = null;
  personalVariantesSugeridas = [];
  personalVariantesSeleccionadas = new Set();
  document.getElementById("personal-nuevo-nombre").value = "";
  document.getElementById("personal-nuevo-variantes-extra").value = "";
  document.getElementById("personal-nuevo-fecha").value = new Date().toISOString().slice(0, 10);
  document.getElementById("personal-variantes-sugeridas").innerHTML = "";
  document.getElementById("personal-modal").classList.add("visible");
  loadPersonalModal().catch((err) => console.error("Fallo cargando personal:", err));
}

function cerrarModalPersonal() {
  document.getElementById("personal-modal").classList.remove("visible");
}

function renderVariantesSugeridas() {
  document.getElementById("personal-variantes-sugeridas").innerHTML = personalVariantesSugeridas
    .map((v) => {
      const activa = personalVariantesSeleccionadas.has(v);
      return `<button type="button" class="personal-variante-toggle ${activa ? "activa" : ""}" data-variante="${escapeHTML(v)}">${escapeHTML(v)}</button>`;
    })
    .join("");
}

async function sugerirVariantesPersonal() {
  const nombre = document.getElementById("personal-nuevo-nombre").value.trim();
  if (!nombre) {
    mostrarAviso("Escribe primero el nombre.");
    return;
  }
  const boton = document.getElementById("btn-sugerir-variantes");
  boton.disabled = true;
  boton.textContent = "Pensando...";
  try {
    const res = await fetch(`${API_BASE}/personal/sugerir-variantes`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nombre }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Error ${res.status}`);
    }
    const data = await res.json();
    personalVariantesSugeridas = data.variantes || [];
    personalVariantesSeleccionadas = new Set(personalVariantesSugeridas);
    renderVariantesSugeridas();
  } catch (err) {
    mostrarAviso(`No se pudieron sugerir variantes: ${err.message}\n\nPuedes escribirlas a mano en "Otras variantes".`);
  } finally {
    boton.disabled = false;
    boton.textContent = "✨ Sugerir variantes con IA";
  }
}

// Pregunta al confirmar un posible duplicado (misma persona en la misma
// tienda con nombre/variante repetida): OK = fusionar en una sola ficha,
// Cancelar = son personas distintas, seguir y crear/trasladar aparte.
function confirmarEsMismaPersona(duplicados) {
  const nombres = duplicados.map((d) => d.nombre_canonico).join(", ");
  return pedirConfirmacion(
    `Ya hay alguien con ese nombre en esa tienda (${nombres}). ¿Es la misma persona?\n\n` +
    `Aceptar = sí, fusionar en una sola ficha (sus reseñas se cuentan juntas).\n` +
    `Cancelar = no, son personas distintas, añadir aparte.`
  );
}

async function enviarCreacionPersonal(payload) {
  const res = await fetch(`${API_BASE}/personal`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (res.status === 409) {
    const err = await res.json().catch(() => ({}));
    const duplicados = err.detail?.duplicados || [];
    if (await confirmarEsMismaPersona(duplicados)) {
      return enviarCreacionPersonal({ ...payload, fusionar_con_personal_id: duplicados[0].personal_id });
    }
    return enviarCreacionPersonal({ ...payload, confirmar_duplicado: true });
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    mostrarAviso(`No se pudo añadir: ${err.detail || res.status}`);
    return false;
  }
  return true;
}

async function enviarSalidaPersonal(payload) {
  const res = await fetch(`${API_BASE}/personal/salida`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (res.status === 409) {
    const err = await res.json().catch(() => ({}));
    const duplicados = err.detail?.duplicados || [];
    if (await confirmarEsMismaPersona(duplicados)) {
      return enviarSalidaPersonal({ ...payload, fusionar_con_personal_id: duplicados[0].personal_id });
    }
    return enviarSalidaPersonal({ ...payload, confirmar_duplicado: true });
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    mostrarAviso(`No se pudo registrar la salida: ${err.detail || res.status}`);
    return false;
  }
  return true;
}

async function crearPersonalNuevo() {
  const tienda = document.getElementById("personal-nuevo-tienda").value;
  const nombre = document.getElementById("personal-nuevo-nombre").value.trim();
  if (!tienda || !nombre) {
    mostrarAviso("Elige la tienda y escribe el nombre de la persona.");
    return;
  }
  const extra = document.getElementById("personal-nuevo-variantes-extra").value
    .split(",").map((v) => v.trim()).filter(Boolean);
  const variantes = [...new Set([...personalVariantesSeleccionadas, ...extra])];
  const fecha_inicio = document.getElementById("personal-nuevo-fecha").value || null;

  const ok = await enviarCreacionPersonal({ tienda, nombre_canonico: nombre, variantes, fecha_inicio });
  if (!ok) return;

  document.getElementById("personal-nuevo-nombre").value = "";
  document.getElementById("personal-nuevo-variantes-extra").value = "";
  personalVariantesSugeridas = [];
  personalVariantesSeleccionadas = new Set();
  document.getElementById("personal-variantes-sugeridas").innerHTML = "";
  await loadPersonalModal();
  loadStaffMentions().catch((err) => console.error("Fallo refrescando ranking de personal:", err));
}

function wirePersonalListado() {
  document.getElementById("personal-listado").addEventListener("click", async (e) => {
    const btnEditar = e.target.closest(".btn-personal-editar");
    if (btnEditar) {
      personalEditandoAsignacionId = Number(btnEditar.dataset.asignacionId);
      personalSalidaAsignacionId = null;
      personalFusionandoAsignacionId = null;
      renderPersonalListado();
      return;
    }
    if (e.target.closest(".btn-personal-cancelar-edicion")) {
      personalEditandoAsignacionId = null;
      renderPersonalListado();
      return;
    }
    const btnGuardarEdicion = e.target.closest(".btn-personal-guardar-edicion");
    if (btnGuardarEdicion) {
      const fila = btnGuardarEdicion.closest(".personal-fila");
      const nombre = fila.querySelector(".personal-editar-nombre").value.trim();
      const variantes = fila.querySelector(".personal-editar-variantes").value.split(",").map((v) => v.trim()).filter(Boolean);
      if (!nombre) {
        mostrarAviso("El nombre no puede quedar vacío.");
        return;
      }
      const res = await fetch(`${API_BASE}/personal/${btnGuardarEdicion.dataset.personalId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ nombre_canonico: nombre, variantes }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        mostrarAviso(`No se pudo guardar: ${err.detail || res.status}`);
        return;
      }
      personalEditandoAsignacionId = null;
      await loadPersonalModal();
      loadStaffMentions().catch((err) => console.error("Fallo refrescando ranking de personal:", err));
      return;
    }
    const btnSalida = e.target.closest(".btn-personal-salida");
    if (btnSalida) {
      personalSalidaAsignacionId = Number(btnSalida.dataset.asignacionId);
      personalEditandoAsignacionId = null;
      personalFusionandoAsignacionId = null;
      renderPersonalListado();
      return;
    }
    if (e.target.closest(".btn-salida-cancelar")) {
      personalSalidaAsignacionId = null;
      renderPersonalListado();
      return;
    }
    const btnSalidaConfirmar = e.target.closest(".btn-salida-confirmar");
    if (btnSalidaConfirmar) {
      const form = btnSalidaConfirmar.closest(".salida-form");
      const tipo = form.querySelector('input[type="radio"]:checked').value;
      const fecha = form.querySelector(".salida-fecha").value;
      const tienda_destino = tipo === "traslado" ? form.querySelector(".salida-tienda-destino").value : null;
      if (!fecha) {
        mostrarAviso("Indica la fecha de salida.");
        return;
      }
      if (tipo === "traslado" && !tienda_destino) {
        mostrarAviso("Elige la tienda de destino del traslado.");
        return;
      }
      const ok = await enviarSalidaPersonal({
        asignacion_id: Number(btnSalidaConfirmar.dataset.asignacionId), fecha, tipo, tienda_destino,
      });
      if (!ok) return;
      personalSalidaAsignacionId = null;
      await loadPersonalModal();
      loadStaffMentions().catch((err) => console.error("Fallo refrescando ranking de personal:", err));
      return;
    }
    const btnFusionar = e.target.closest(".btn-personal-fusionar");
    if (btnFusionar) {
      personalFusionandoAsignacionId = Number(btnFusionar.dataset.asignacionId);
      personalEditandoAsignacionId = null;
      personalSalidaAsignacionId = null;
      renderPersonalListado();
      return;
    }
    if (e.target.closest(".btn-fusion-cancelar")) {
      personalFusionandoAsignacionId = null;
      renderPersonalListado();
      return;
    }
    const btnFusionConfirmar = e.target.closest(".btn-fusion-confirmar");
    if (btnFusionConfirmar) {
      const form = btnFusionConfirmar.closest(".salida-form");
      const personalIdDestino = Number(form.querySelector(".fusion-destino-select").value);
      const res = await fetch(`${API_BASE}/personal/fusionar`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          personal_id_origen: Number(btnFusionConfirmar.dataset.personalId),
          personal_id_destino: personalIdDestino,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        mostrarAviso(`No se pudo fusionar: ${err.detail || res.status}`);
        return;
      }
      personalFusionandoAsignacionId = null;
      await loadPersonalModal();
      loadStaffMentions().catch((err) => console.error("Fallo refrescando ranking de personal:", err));
      return;
    }
    const btnEliminar = e.target.closest(".btn-personal-eliminar");
    if (btnEliminar) {
      if (!(await pedirConfirmacion("¿Borrar a esta persona y todo su historial? Pensado solo para altas hechas por error."))) return;
      await fetch(`${API_BASE}/personal/${btnEliminar.dataset.personalId}`, { method: "DELETE" });
      await loadPersonalModal();
      loadStaffMentions().catch((err) => console.error("Fallo refrescando ranking de personal:", err));
    }
  });

  document.getElementById("personal-variantes-sugeridas").addEventListener("click", (e) => {
    const btn = e.target.closest(".personal-variante-toggle");
    if (!btn) return;
    const v = btn.dataset.variante;
    if (personalVariantesSeleccionadas.has(v)) personalVariantesSeleccionadas.delete(v);
    else personalVariantesSeleccionadas.add(v);
    renderVariantesSugeridas();
  });
}

const MESES_CORTOS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];

function formatFechaExacta(fechaDatetime) {
  if (!fechaDatetime) return "";
  const [y, m, d] = fechaDatetime.split("-");
  return `${parseInt(d, 10)} ${MESES_CORTOS[parseInt(m, 10) - 1]} ${y}`;
}

function formatHoraExacta(fechaHora) {
  if (!fechaHora) return "";
  const hora = fechaHora.split(" ")[1];
  return hora ? hora.slice(0, 5) : "";
}

function reviewCardHTML(r) {
  const stars = r.calificacion_num ? "★".repeat(r.calificacion_num) + "☆".repeat(5 - r.calificacion_num) : "—";
  const fechaExacta = formatFechaExacta(r.fecha_datetime) || escapeHTML(r.fecha_categoria || "");
  const horaExacta = formatHoraExacta(r.fecha_hora);
  // visible_en_google=0: la reconciliación manual (scraper --reconciliar) no
  // la encontró en una pasada completa en vivo — se muestra igual (en modo
  // "mostrar todo") pero marcada, para que quede claro por qué no suma en el
  // toggle "Solo Google".
  const noVisible = r.visible_en_google === 0
    ? `<span class="badge badge-no-google" title="La reconciliación manual no la encontró visible en Google la última vez que se revisó">🚫 no visible en Google</span>`
    : "";
  return `
    <div class="review-item">
      <div class="review-top">
        <span class="review-author">${escapeHTML(r.autor || "Anónimo")}</span>
        <span class="review-meta">
          <span class="review-stars">${stars}</span>
          <span${horaExacta ? ` title="${horaExacta} (hora de Madrid)"` : ""}>${fechaExacta}</span>
          <span class="badge badge-${r.sentiment}">${r.sentiment}</span>
          ${noVisible}
        </span>
      </div>
      <div class="review-text">${r.texto ? escapeHTML(r.texto) : '<i>Sin comentario, solo calificación.</i>'}</div>
    </div>
  `;
}

function renderPagination(total, totalPaginas) {
  const el = document.getElementById("pagination");
  document.getElementById("reviews-count").textContent = `${total.toLocaleString("es-ES")} resultados`;

  if (totalPaginas <= 1) { el.innerHTML = ""; return; }

  const current = state.page;
  const pages = [];
  const add = (p) => { if (!pages.includes(p) && p >= 1 && p <= totalPaginas) pages.push(p); };
  add(1); add(current - 1); add(current); add(current + 1); add(totalPaginas);
  pages.sort((a, b) => a - b);

  let html = `<button ${current === 1 ? "disabled" : ""} data-page="${current - 1}">‹</button>`;
  let prev = 0;
  for (const p of pages) {
    if (prev && p - prev > 1) html += `<span>…</span>`;
    html += `<button class="${p === current ? "active" : ""}" data-page="${p}">${p}</button>`;
    prev = p;
  }
  html += `<button ${current === totalPaginas ? "disabled" : ""} data-page="${current + 1}">›</button>`;
  el.innerHTML = html;

  el.querySelectorAll("button[data-page]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.page = parseInt(btn.dataset.page, 10);
      loadReviews();
      window.scrollTo({ top: document.getElementById("filters-row").offsetTop - 20, behavior: "smooth" });
    });
  });
}

async function loadReviews() {
  const params = currentQueryParams({ page: state.page, page_size: state.pageSize, sort: state.sort });
  const data = await fetchJSON(`${API_BASE}/reviews?${params.toString()}`);
  document.getElementById("reviews-list").innerHTML = data.reviews.map(reviewCardHTML).join("") || "<p>No hay reseñas para estos filtros.</p>";
  renderPagination(data.total, data.total_paginas);

  const activeEl = document.getElementById("horario-active-filter");
  const hayFiltroHorario = state.hora !== "" || state.diaSemana !== "";
  activeEl.hidden = !hayFiltroHorario;
  if (hayFiltroHorario) {
    document.getElementById("horario-active-label").textContent = state.hora !== ""
      ? `${state.hora}h`
      : state.diaSemana;
  }
}

function selectHoraFiltro(hora) {
  const mismaHora = state.hora === hora;
  state.hora = mismaHora ? "" : hora;
  state.diaSemana = "";
  state.page = 1;
  loadReviews().then(() => {
    document.getElementById("reviews-list").scrollIntoView({ behavior: "smooth", block: "start" });
  }).catch((err) => console.error("Fallo filtrando por hora:", err));
}

function selectDiaSemanaFiltro(dia) {
  const mismoDia = state.diaSemana === dia;
  state.diaSemana = mismoDia ? "" : dia;
  state.hora = "";
  state.page = 1;
  loadReviews().then(() => {
    document.getElementById("reviews-list").scrollIntoView({ behavior: "smooth", block: "start" });
  }).catch((err) => console.error("Fallo filtrando por día:", err));
}

function clearHorarioFiltro() {
  state.hora = "";
  state.diaSemana = "";
  state.page = 1;
  return loadReviews();
}

async function refreshAll() {
  const tasks = [
    ["stats", loadStats()],
    ["rating-progress", loadRatingProgress()],
    ["timeline", loadTimeline()],
    ["evolucion", loadEvolucionTabla()],
    ["horario", loadHorario()],
    ["keywords", loadKeywords()],
    ["staff", loadStaffMentions()],
    ["reviews", loadReviews()],
  ];
  const results = await Promise.allSettled(tasks.map(([, p]) => p));
  results.forEach((r, i) => {
    if (r.status === "rejected") console.error(`Fallo cargando ${tasks[i][0]}:`, r.reason);
  });
  if (results.every((r) => r.status === "rejected")) {
    throw results[0].reason;
  }
}

function exportExcel() {
  const params = currentQueryParams();
  window.open(conEmpresaURL(`${API_BASE}/reviews/export/xlsx?${params.toString()}`), "_blank");
}

function goToLatest() {
  state.page = 1;
  state.sort = "recientes";
  const sortEl = document.getElementById("filter-sort");
  if (sortEl) sortEl.value = "recientes";
  return refreshAll();
}

function clearFilters() {
  document.getElementById("filter-tienda").value = "";
  document.getElementById("filter-rating").value = "";
  document.getElementById("filter-sentiment").value = "";
  document.getElementById("filter-date-from").value = "";
  document.getElementById("filter-date-to").value = "";
  document.getElementById("filter-search").value = "";
  document.getElementById("filter-sort").value = "recientes";

  state.page = 1;
  state.tienda = "";
  state.rating = "";
  state.sentiment = "";
  state.dateFrom = "";
  state.dateTo = "";
  state.q = "";
  state.staff = "";
  state.hora = "";
  state.diaSemana = "";
  state.sort = "recientes";

  return refreshAll();
}

function aplicarBrandingEmpresa() {
  if (EMPRESA !== "saona") return;
  document.title = "Saona Track";
  const icon = document.getElementById("brand-icon");
  if (icon) icon.textContent = "🌿";
  const favicon = document.querySelector('link[rel="icon"]');
  if (favicon) favicon.href = "assets/favicon-saona.png";
  const title = document.getElementById("brand-title");
  if (title) title.textContent = "Saona Track";
  const rankingTitle = document.getElementById("staff-ranking-title");
  if (rankingTitle) rankingTitle.textContent = "Ranking de Saona Team";
  document.documentElement.dataset.empresa = "saona";
}

document.addEventListener("DOMContentLoaded", async () => {
  aplicarBrandingEmpresa();
  const user = await checkAuth();
  if (!user) return; // checkAuth ya redirigió a /login.html
  const moduloRequerido = EMPRESA === "saona" ? "saona_resenas" : "resenas";
  if (!(user.modulos || []).includes(moduloRequerido)) {
    window.location.href = "/";
    return;
  }
  wireUserBar(user);
  tiendasPermitidas = user.tiendas || [];

  cargarUltimaImportacionTakeout();

  wireFilters(() => refreshAll(), () => loadReviews());

  const soloGoogleEl = document.getElementById("filter-solo-google");
  state.soloGoogle = localStorage.getItem("kt-resenas-solo-google") === "1";
  soloGoogleEl.checked = state.soloGoogle;
  soloGoogleEl.addEventListener("change", () => {
    state.soloGoogle = soloGoogleEl.checked;
    localStorage.setItem("kt-resenas-solo-google", state.soloGoogle ? "1" : "0");
    state.page = 1;
    Promise.all([loadStores(), loadStoreRanking(), refreshAll()]).catch((err) =>
      console.error("Fallo aplicando el toggle Solo Google:", err)
    );
  });

  document.getElementById("btn-toggle-horario").addEventListener("click", (e) => {
    horarioVisible = !horarioVisible;
    document.getElementById("horario-charts").hidden = !horarioVisible;
    document.getElementById("horario-hint").hidden = !horarioVisible;
    e.target.textContent = horarioVisible ? "Ocultar" : "Mostrar";
    if (horarioVisible) loadHorario().catch((err) => console.error("Fallo cargando horario:", err));
  });
  document.getElementById("btn-export-csv").addEventListener("click", exportExcel);
  document.getElementById("input-transactions-month").value = new Date().toISOString().slice(0, 7);
  document.getElementById("input-transactions-month").addEventListener("change", () => {
    loadStoreRanking().catch((err) => console.error("Fallo recargando ranking de tiendas:", err));
  });
  document.getElementById("btn-clear-filters").addEventListener("click", clearFilters);
  document.getElementById("btn-clear-staff").addEventListener("click", clearStaffFilter);
  document.getElementById("btn-clear-horario").addEventListener("click", clearHorarioFiltro);

  const onStaffRowClick = (e) => {
    const row = e.target.closest("tr[data-name]");
    if (row) selectStaff(row.dataset.name, row.dataset.tienda);
  };
  document.getElementById("staff-list").addEventListener("click", onStaffRowClick);
  document.getElementById("staff-former-list").addEventListener("click", onStaffRowClick);

  document.getElementById("btn-toggle-former").addEventListener("click", (e) => {
    const table = document.getElementById("staff-former-table");
    table.hidden = !table.hidden;
    e.target.textContent = table.hidden ? "Mostrar anteriores" : "Ocultar anteriores";
  });

  if (user.rol === "admin") {
    const btnGestionarPersonal = document.getElementById("btn-gestionar-personal");
    btnGestionarPersonal.hidden = false;
    btnGestionarPersonal.addEventListener("click", abrirModalPersonal);
    document.getElementById("btn-personal-cerrar").addEventListener("click", cerrarModalPersonal);
    document.getElementById("btn-sugerir-variantes").addEventListener("click", sugerirVariantesPersonal);
    document.getElementById("btn-crear-personal").addEventListener("click", crearPersonalNuevo);
    wirePersonalListado();
  }

  loadStores().catch((err) => console.error("Fallo cargando tiendas:", err));
  loadStoreRanking().catch((err) => console.error("Fallo cargando ranking de tiendas:", err));

  document.getElementById("store-ranking-list").addEventListener("change", (e) => {
    const input = e.target.closest(".transacciones-input");
    if (!input) return;
    const value = parseInt(input.value, 10);
    if (Number.isNaN(value) || value < 0) return;
    saveTransacciones(input.dataset.tienda, value).catch((err) => console.error("Fallo guardando transacciones:", err));
  });

  document.getElementById("input-transactions-upload").addEventListener("change", (e) => {
    const file = e.target.files[0];
    if (!file) return;
    uploadTransaccionesFile(file).catch((err) => console.error("Fallo subiendo Excel:", err));
    e.target.value = "";
  });

  document.getElementById("input-import-takeout").addEventListener("change", (e) => {
    const file = e.target.files[0];
    if (!file) return;
    uploadTakeoutZip(file).catch((err) => {
      console.error("Fallo importando Takeout:", err);
      mostrarAviso("Fallo importando el Takeout — revisa la consola del navegador.");
    });
    e.target.value = "";
  });

  refreshAll().catch((err) => {
    console.error(err);
    document.getElementById("reviews-list").innerHTML =
      `<p>No se pudo conectar con la API (${escapeHTML(err.message)}). ¿Está corriendo <code>python main.py</code> en /backend?</p>`;
  });
});

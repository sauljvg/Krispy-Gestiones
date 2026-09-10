// Planificador de turnos -- línea de tiempo horizontal por horas de un día.
// Bloques (turnos) arrastrables y redimensionables por los bordes; el
// contador de la izquierda suma las horas de TODA la semana de cada
// trabajador contra su contrato. Ver backend/planificador.py.

const EMPRESA = new URLSearchParams(location.search).get("empresa") === "saona" ? "saona" : "kk";
const API = `${window.location.origin}/api/planificador`;
const PX_POR_MIN = 1.15; // ancho en px de cada minuto de la línea de tiempo
const SNAP = 15; // los bloques saltan de 15 en 15 minutos
const LS_CENTRO = `plan-centro-${EMPRESA}`;

const S = {
  centro: "",
  fecha: hoyISO(),
  config: { apertura_min: 480, cierre_min: 1500, objetivo_transacciones_hora: null },
  trabajadores: [],
  turnos: [],
  minutosSemana: {},
  proyeccion: {},
};

// ---------------------------------------------------------------- utilidades

function hoyISO() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function url(path, params = {}) {
  const p = new URLSearchParams({ empresa: EMPRESA, ...params });
  return `${API}/${path}?${p.toString()}`;
}
function minToX(min) {
  return (min - S.config.apertura_min) * PX_POR_MIN;
}
function xToMin(x) {
  return x / PX_POR_MIN + S.config.apertura_min;
}
function snap(min) {
  return Math.round(min / SNAP) * SNAP;
}
function clamp(v, a, b) {
  return Math.max(a, Math.min(b, v));
}
function fmtHHMM(min) {
  const m = ((Math.round(min) % 1440) + 1440) % 1440;
  return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
}
function fmtHoras(min) {
  return (Math.round((min / 60) * 100) / 100).toString().replace(".", ",") + " h";
}
function anchoTimeline() {
  return (S.config.cierre_min - S.config.apertura_min) * PX_POR_MIN;
}
function franjas() {
  const out = [];
  const ini = Math.floor(S.config.apertura_min / 60) * 60;
  for (let m = ini; m < S.config.cierre_min; m += 60) out.push(m);
  return out;
}
function fechaLarga(iso) {
  const d = new Date(iso + "T12:00:00");
  const dias = ["Domingo", "Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"];
  return `${dias[d.getDay()]} ${String(d.getDate()).padStart(2, "0")}/${String(d.getMonth() + 1).padStart(2, "0")}/${d.getFullYear()}`;
}
function sumarDias(iso, n) {
  const d = new Date(iso + "T12:00:00");
  d.setDate(d.getDate() + n);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

// ---------------------------------------------------------------- carga

async function cargarCentros() {
  const res = await fetch(url("centros"));
  const data = res.ok ? await res.json() : { centros: [] };
  const sel = document.getElementById("plan-centro");
  sel.innerHTML = data.centros.map((c) => `<option value="${escapeHTML(c)}">${escapeHTML(c)}</option>`).join("");
  if (data.centros.length === 0) {
    document.getElementById("plan-contenido").innerHTML =
      `<p class="plan-vacia">No hay centros disponibles. Abre <b>Plantilla</b> y carga trabajadores desde KPIs, importa el Excel de Odoo o añade a alguien a mano.</p>`;
    return false;
  }
  const guardado = localStorage.getItem(LS_CENTRO);
  S.centro = data.centros.includes(guardado) ? guardado : data.centros[0];
  sel.value = S.centro;
  return true;
}

async function cargarDia() {
  const cont = document.getElementById("plan-contenido");
  cont.innerHTML = `<p class="plan-vacia">Cargando…</p>`;
  const res = await fetch(url("dia", { centro: S.centro, fecha: S.fecha }));
  if (!res.ok) {
    cont.innerHTML = `<p class="plan-vacia">No se pudo cargar el día.</p>`;
    return;
  }
  const data = await res.json();
  S.config = data.config;
  S.trabajadores = data.trabajadores;
  S.turnos = data.turnos;
  S.minutosSemana = data.minutos_semana || {};
  S.proyeccion = normalizarProyeccion(data.proyeccion || {});
  document.getElementById("plan-fecha-txt").textContent = fechaLarga(S.fecha);
  document.getElementById("plan-fecha-input").value = S.fecha;
  renderTodo();
}

function normalizarProyeccion(obj) {
  // el backend devuelve las claves de franja como string -> a número
  const out = {};
  for (const k of Object.keys(obj)) out[Number(k)] = obj[k];
  return out;
}

// ---------------------------------------------------------------- render

function renderTodo() {
  const cont = document.getElementById("plan-contenido");
  const fr = franjas();
  const ancho = anchoTimeline();
  const anchoHora = 60 * PX_POR_MIN;

  const ticksHTML = fr
    .map((m) => `<div class="plan-hora-tick" style="left:${minToX(m)}px; width:${anchoHora}px;">${fmtHHMM(m)}</div>`)
    .join("");
  const lineasHTML = fr.map((m) => `<div class="plan-lane-linea hora" style="left:${minToX(m)}px;"></div>`).join("");

  const cabFila = (titulo, contenido) =>
    `<div class="plan-fila plan-fila-cabecera">
       <div class="plan-celda-izq"><span class="plan-cab-titulo">${titulo}</span></div>
       <div class="plan-lane"><div class="plan-lane-lineas">${lineasHTML}</div>${contenido}</div>
     </div>`;

  const celdasInput = (campo, paso) =>
    fr
      .map((m) => {
        const v = (S.proyeccion[m] || {})[campo];
        return `<div class="plan-cab-cell" style="left:${minToX(m)}px; width:${anchoHora}px;">
          <input type="number" step="${paso}" min="0" data-franja="${m}" data-campo="${campo}" value="${v ?? ""}">
        </div>`;
      })
      .join("");

  const celdasIdeal = () =>
    fr
      .map((m) => {
        const calc = idealCalculado(m);
        const manual = (S.proyeccion[m] || {}).personal_ideal_manual;
        return `<div class="plan-cab-cell" style="left:${minToX(m)}px; width:${anchoHora}px;">
          <input type="number" step="0.5" min="0" data-franja="${m}" data-campo="personal_ideal_manual"
            value="${manual ?? ""}" placeholder="${calc == null ? "" : calc}">
        </div>`;
      })
      .join("");

  cont.innerHTML = `
    <div class="plan-grid-scroll">
      <div class="plan-grid" style="--plan-ancho:${ancho}px;">
        <div class="plan-horas-fila">
          <div class="plan-esquina"></div>
          <div class="plan-horas">${ticksHTML}</div>
        </div>
        ${cabFila("Venta prevista (€)", celdasInput("venta_prevista", "any"))}
        ${cabFila("Transacciones prev.", celdasInput("transacciones_prevista", "1"))}
        ${cabFila("Personal ideal", celdasIdeal())}
        ${cabFila("Personal planificado", `<div id="plan-fila-planificado">${celdasPlanificado()}</div>`)}
        ${
          S.trabajadores.length === 0
            ? `<div class="plan-vacia">Este centro no tiene trabajadores en la plantilla. Ábrela con el botón <b>Plantilla</b>.</div>`
            : S.trabajadores.map(filaTrabajador).join("")
        }
      </div>
    </div>`;

  wireInputsProyeccion();
  S.trabajadores.forEach((t) => wireLane(cont.querySelector(`.plan-lane[data-trab="${t.id}"]`), t.id));
  cont.querySelectorAll(".plan-turno").forEach(wireTurno);
}

function celdasPlanificado() {
  const anchoHora = 60 * PX_POR_MIN;
  return franjas()
    .map((m) => {
      const n = planificadoEnFranja(m);
      const ideal = idealCalculado(m);
      const deficit = ideal != null && n < Math.round(ideal);
      return `<div class="plan-cab-cell calc ${deficit ? "deficit" : ""}" style="left:${minToX(m)}px; width:${anchoHora}px;">${n}</div>`;
    })
    .join("");
}

function idealCalculado(m) {
  const p = S.proyeccion[m] || {};
  if (p.personal_ideal_manual != null && p.personal_ideal_manual !== "") return Number(p.personal_ideal_manual);
  const obj = S.config.objetivo_transacciones_hora;
  if (!obj || p.transacciones_prevista == null) return null;
  return Math.round((p.transacciones_prevista / obj) * 10) / 10;
}

function planificadoEnFranja(m) {
  const ids = new Set();
  for (const t of S.turnos) {
    if (t.inicio_min < m + 60 && t.inicio_min + t.duracion_min > m) ids.add(t.trabajador_id);
  }
  return ids.size;
}

function textoHoras(min, contrato) {
  const h = (Math.round((min / 60) * 100) / 100).toString().replace(".", ",");
  return contrato ? `${h} h / ${contrato} h (${Math.round((min / 60 / contrato) * 100)}%)` : `${h} h / sin contrato`;
}

function filaTrabajador(t) {
  const min = S.minutosSemana[String(t.id)] || 0;
  const contrato = t.horas_contrato_semana;
  const pct = contrato ? min / 60 / contrato : 0;
  const clase = !contrato ? "" : pct >= 1 ? "rojo" : pct >= 0.85 ? "ambar" : "";
  const bloques = S.turnos.filter((x) => x.trabajador_id === t.id).map(turnoHTML).join("");
  const lineas = franjas().map((m) => `<div class="plan-lane-linea hora" style="left:${minToX(m)}px;"></div>`).join("");
  return `
    <div class="plan-fila">
      <div class="plan-celda-izq">
        <span class="plan-trab-nombre" title="${escapeHTML(t.nombre)}">${escapeHTML(t.nombre)}</span>
        <span class="plan-trab-horas">${textoHoras(min, contrato)}</span>
        <div class="plan-barra ${clase}"><i style="width:${Math.min(100, Math.round(pct * 100))}%;"></i></div>
      </div>
      <div class="plan-lane" data-trab="${t.id}">
        <div class="plan-lane-lineas">${lineas}</div>
        ${bloques}
      </div>
    </div>`;
}

function turnoHTML(t) {
  return `<div class="plan-turno" data-id="${t.id}" data-inicio="${t.inicio_min}" data-duracion="${t.duracion_min}"
    style="left:${minToX(t.inicio_min)}px; width:${t.duracion_min * PX_POR_MIN}px;">
    <span class="plan-turno-txt">${etiquetaTurno(t.inicio_min, t.duracion_min)}</span>
    <span class="plan-turno-x" title="Quitar">✕</span>
  </div>`;
}
function etiquetaTurno(inicio, dur) {
  return dur * PX_POR_MIN < 95 ? fmtHoras(dur) : `${fmtHHMM(inicio)}–${fmtHHMM(inicio + dur)} · ${fmtHoras(dur)}`;
}

// ---------------------------------------------------------------- proyección

function wireInputsProyeccion() {
  document.querySelectorAll(".plan-cab-cell input[data-campo]").forEach((inp) => {
    inp.addEventListener("change", async () => {
      const franja = Number(inp.dataset.franja);
      const campo = inp.dataset.campo;
      const valor = inp.value === "" ? null : Number(inp.value);
      const res = await fetch(url("proyeccion"), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ centro: S.centro, fecha: S.fecha, franja_min: franja, campo, valor }),
      });
      if (!res.ok) {
        mostrarAviso("No se pudo guardar. Inténtalo de nuevo.");
        return;
      }
      S.proyeccion[franja] = S.proyeccion[franja] || {};
      S.proyeccion[franja][campo] = valor;
      refrescarCalculadas();
    });
  });
}

function refrescarCalculadas() {
  document.querySelectorAll('.plan-cab-cell input[data-campo="personal_ideal_manual"]').forEach((inp) => {
    if (inp.value === "") {
      const calc = idealCalculado(Number(inp.dataset.franja));
      inp.placeholder = calc == null ? "" : String(calc);
    }
  });
  const cont = document.getElementById("plan-fila-planificado");
  if (cont) cont.innerHTML = celdasPlanificado();
}

// ---------------------------------------------------------------- arrastrar / crear

function wireTurno(el) {
  const btnX = el.querySelector(".plan-turno-x");
  btnX.addEventListener("pointerdown", (e) => e.stopPropagation());
  btnX.addEventListener("click", async (e) => {
    e.stopPropagation();
    if (!(await pedirConfirmacion("¿Quitar este turno?"))) return;
    const res = await fetch(url(`turnos/${el.dataset.id}`), { method: "DELETE" });
    if (!res.ok) {
      mostrarAviso("No se pudo quitar el turno.");
      return;
    }
    cargarDia();
  });

  el.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    e.preventDefault();
    const rect = el.getBoundingClientRect();
    const cerca = 10;
    const modo = e.clientX - rect.left < cerca ? "izq" : rect.right - e.clientX < cerca ? "der" : "mover";
    const startX = e.clientX;
    const iniOrig = Number(el.dataset.inicio);
    const durOrig = Number(el.dataset.duracion);
    let ini = iniOrig;
    let dur = durOrig;
    el.setPointerCapture(e.pointerId);
    el.style.cursor = modo === "mover" ? "grabbing" : "ew-resize";

    const onMove = (ev) => {
      const dMin = snap((ev.clientX - startX) / PX_POR_MIN);
      if (modo === "mover") {
        ini = clamp(iniOrig + dMin, S.config.apertura_min, S.config.cierre_min - durOrig);
        dur = durOrig;
      } else if (modo === "izq") {
        ini = clamp(iniOrig + dMin, S.config.apertura_min, iniOrig + durOrig - SNAP);
        dur = iniOrig + durOrig - ini;
      } else {
        dur = clamp(durOrig + dMin, SNAP, S.config.cierre_min - iniOrig);
        ini = iniOrig;
      }
      el.style.left = minToX(ini) + "px";
      el.style.width = dur * PX_POR_MIN + "px";
      el.querySelector(".plan-turno-txt").textContent = etiquetaTurno(ini, dur);
    };
    const onUp = async () => {
      el.releasePointerCapture(e.pointerId);
      el.removeEventListener("pointermove", onMove);
      el.removeEventListener("pointerup", onUp);
      el.style.cursor = "grab";
      if (ini === iniOrig && dur === durOrig) return;
      const res = await fetch(url(`turnos/${el.dataset.id}`), {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ inicio_min: ini, duracion_min: dur }),
      });
      if (!res.ok) mostrarAviso("No se pudo guardar el cambio.");
      cargarDia();
    };
    el.addEventListener("pointermove", onMove);
    el.addEventListener("pointerup", onUp);
  });
}

function wireLane(lane, trabajadorId) {
  if (!lane) return;
  lane.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || e.target.closest(".plan-turno")) return;
    e.preventDefault();
    const laneRect = lane.getBoundingClientRect();
    const startX = e.clientX;
    const iniClick = clamp(snap(xToMin(e.clientX - laneRect.left)), S.config.apertura_min, S.config.cierre_min - SNAP);
    const fantasma = document.createElement("div");
    fantasma.className = "plan-turno-fantasma";
    fantasma.style.left = minToX(iniClick) + "px";
    fantasma.style.width = SNAP * PX_POR_MIN + "px";
    lane.appendChild(fantasma);
    let ini = iniClick;
    let dur = SNAP;
    let arrastrado = false;

    const onMove = (ev) => {
      arrastrado = arrastrado || Math.abs(ev.clientX - startX) > 4;
      const cursorMin = clamp(snap(xToMin(ev.clientX - laneRect.left)), S.config.apertura_min, S.config.cierre_min);
      ini = Math.min(iniClick, cursorMin);
      dur = Math.max(SNAP, Math.abs(cursorMin - iniClick));
      if (ini + dur > S.config.cierre_min) dur = S.config.cierre_min - ini;
      fantasma.style.left = minToX(ini) + "px";
      fantasma.style.width = dur * PX_POR_MIN + "px";
    };
    const onUp = async () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      fantasma.remove();
      if (!arrastrado) {
        ini = iniClick;
        dur = Math.min(240, S.config.cierre_min - iniClick);
      }
      if (dur < SNAP) return;
      const res = await fetch(url("turnos"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ centro: S.centro, fecha: S.fecha, trabajador_id: trabajadorId, inicio_min: ini, duracion_min: dur }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        mostrarAviso(err.detail || "No se pudo crear el turno.");
        return;
      }
      cargarDia();
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  });
}

// ---------------------------------------------------------------- plantilla (roster)

async function pintarRoster() {
  const res = await fetch(url("roster", { centro: S.centro }));
  const data = res.ok ? await res.json() : { trabajadores: [] };
  const cont = document.getElementById("plan-roster-lista");
  if (data.trabajadores.length === 0) {
    cont.innerHTML = `<p class="staff-hint">Nadie todavía. Usa los botones de arriba.</p>`;
    return;
  }
  cont.innerHTML = data.trabajadores
    .map(
      (t) => `
    <div class="plan-roster-fila ${t.activo ? "" : "inactivo"}" data-id="${t.id}">
      <input type="text" class="pr-nombre" value="${escapeHTML(t.nombre)}">
      <input type="number" class="pr-horas" min="0" step="0.5" value="${t.horas_contrato_semana ?? ""}" placeholder="h/sem">
      <button type="button" class="btn btn-ghost pr-activo" style="font-size:11px; padding:4px 6px;">${t.activo ? "Activo" : "Inactivo"}</button>
      <button type="button" class="btn btn-ghost pr-borrar" title="Eliminar" style="font-size:12px; padding:4px 6px;">🗑</button>
    </div>`
    )
    .join("");
  cont.querySelectorAll(".plan-roster-fila").forEach((fila) => {
    const id = fila.dataset.id;
    const patch = async (body) => {
      const r = await fetch(url(`roster/${id}`), {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) mostrarAviso("No se pudo guardar el cambio.");
    };
    fila.querySelector(".pr-nombre").addEventListener("change", (e) => patch({ nombre: e.target.value }));
    fila.querySelector(".pr-horas").addEventListener("change", (e) =>
      patch({ horas_contrato_semana: e.target.value === "" ? null : Number(e.target.value) })
    );
    fila.querySelector(".pr-activo").addEventListener("click", async (e) => {
      const activar = fila.classList.contains("inactivo");
      await patch({ activo: activar });
      fila.classList.toggle("inactivo", !activar);
      e.target.textContent = activar ? "Activo" : "Inactivo";
    });
    fila.querySelector(".pr-borrar").addEventListener("click", async () => {
      if (!(await pedirConfirmacion("¿Eliminar a esta persona de la plantilla? Se borran también sus turnos."))) return;
      const r = await fetch(url(`roster/${id}`), { method: "DELETE" });
      if (!r.ok) {
        mostrarAviso("No se pudo eliminar.");
        return;
      }
      pintarRoster();
    });
  });
}

function wireRoster() {
  const dlg = document.getElementById("plan-dialog-roster");
  dlg.querySelector("[data-cerrar]").addEventListener("click", () => {
    dlg.close();
    cargarDia();
  });
  document.getElementById("plan-btn-plantilla").addEventListener("click", async () => {
    if (!S.centro) return;
    await pintarRoster();
    dlg.showModal();
  });
  document.getElementById("plan-roster-kpis").addEventListener("click", async () => {
    const aviso = document.getElementById("plan-roster-aviso");
    const r = await fetch(url("roster/cargar-kpis", { centro: S.centro }), { method: "POST" });
    if (!r.ok) {
      aviso.textContent = "No se pudo cargar de KPIs (¿es un centro de Krispy Kreme con datos en el Dashboard?).";
    } else {
      const d = await r.json();
      aviso.textContent = `Hecho: ${d.creados} nuevos, ${d.actualizados} actualizados.`;
    }
    aviso.hidden = false;
    pintarRoster();
  });
  document.getElementById("plan-roster-odoo").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    const r = await fetch(url("roster/importar-odoo"), { method: "POST", body: fd });
    const aviso = document.getElementById("plan-roster-aviso");
    const d = await r.json().catch(() => ({}));
    aviso.textContent = r.ok ? `Importado: ${d.creados} nuevos, ${d.actualizados} actualizados.` : d.detail || "No se pudo importar.";
    aviso.hidden = false;
    e.target.value = "";
    pintarRoster();
  });
  document.getElementById("plan-roster-nuevo").addEventListener("click", async () => {
    const nombre = await pedirTexto("Nombre de la persona:");
    if (!nombre || !nombre.trim()) return;
    const horasStr = await pedirTexto("Horas de contrato por semana (deja vacío si no aplica):", "20");
    const body = { centro: S.centro, nombre: nombre.trim() };
    if (horasStr && !isNaN(Number(horasStr))) body.horas_contrato_semana = Number(horasStr);
    const r = await fetch(url("roster"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      mostrarAviso("No se pudo añadir.");
      return;
    }
    pintarRoster();
  });
}

// ---------------------------------------------------------------- config

function wireConfig() {
  const dlg = document.getElementById("plan-dialog-config");
  dlg.querySelector("[data-cerrar]").addEventListener("click", () => dlg.close());
  document.getElementById("plan-btn-config").addEventListener("click", () => {
    if (!S.centro) return;
    document.getElementById("plan-cfg-apertura").value = fmtHHMM(S.config.apertura_min);
    document.getElementById("plan-cfg-cierre").value = fmtHHMM(S.config.cierre_min);
    document.getElementById("plan-cfg-cierre-siguiente").checked = S.config.cierre_min >= 1440;
    document.getElementById("plan-cfg-objetivo").value = S.config.objetivo_transacciones_hora ?? "";
    document.getElementById("plan-cfg-error").hidden = true;
    dlg.showModal();
  });
  document.getElementById("plan-cfg-guardar").addEventListener("click", async () => {
    const toMin = (v) => {
      const [h, m] = (v || "0:0").split(":").map(Number);
      return h * 60 + (m || 0);
    };
    const apertura = toMin(document.getElementById("plan-cfg-apertura").value || "08:00");
    let cierre = toMin(document.getElementById("plan-cfg-cierre").value || "23:00");
    if (document.getElementById("plan-cfg-cierre-siguiente").checked) cierre += 1440;
    const objStr = document.getElementById("plan-cfg-objetivo").value;
    const err = document.getElementById("plan-cfg-error");
    if (cierre <= apertura) {
      err.textContent = "El cierre debe ser posterior a la apertura (marca 'cierra al día siguiente' si cierra pasada la medianoche).";
      err.hidden = false;
      return;
    }
    const r = await fetch(url("config"), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        centro: S.centro,
        apertura_min: apertura,
        cierre_min: cierre,
        objetivo_transacciones_hora: objStr === "" ? null : Number(objStr),
      }),
    });
    if (!r.ok) {
      err.textContent = "No se pudo guardar.";
      err.hidden = false;
      return;
    }
    dlg.close();
    cargarDia();
  });
}

// ---------------------------------------------------------------- init

function aplicarBranding() {
  if (EMPRESA !== "saona") return;
  document.title = document.title.replace("Krispy Gestiones", "SAONA Gestiones");
  const icon = document.getElementById("brand-icon");
  if (icon) icon.textContent = "🌿";
  const title = document.getElementById("brand-title");
  if (title) title.textContent = "SAONA Gestiones";
  const fav = document.querySelector('link[rel="icon"]');
  if (fav) fav.href = "assets/favicon-saona.png";
  document.documentElement.dataset.empresa = "saona";
}

document.addEventListener("DOMContentLoaded", async () => {
  const user = await checkAuth("/planificador.html");
  if (!user) return;
  const modulo = EMPRESA === "saona" ? "saona_planificador" : "planificador";
  if (user.rol !== "admin" && !(user.modulos || []).includes(modulo)) {
    window.location.href = "/";
    return;
  }
  wireUserBar(user);
  aplicarBranding();
  wireRoster();
  wireConfig();

  document.getElementById("plan-centro").addEventListener("change", (e) => {
    S.centro = e.target.value;
    localStorage.setItem(LS_CENTRO, S.centro);
    cargarDia();
  });
  document.getElementById("plan-dia-prev").addEventListener("click", () => {
    S.fecha = sumarDias(S.fecha, -1);
    cargarDia();
  });
  document.getElementById("plan-dia-next").addEventListener("click", () => {
    S.fecha = sumarDias(S.fecha, 1);
    cargarDia();
  });
  document.getElementById("plan-fecha-input").addEventListener("change", (e) => {
    if (!e.target.value) return;
    S.fecha = e.target.value;
    cargarDia();
  });

  const hayCentros = await cargarCentros();
  if (hayCentros) await cargarDia();
});

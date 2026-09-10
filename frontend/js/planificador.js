// Planificador de turnos -- línea de tiempo horizontal por horas de un día.
// Bloques (turnos) arrastrables y redimensionables por los bordes; el
// contador de la izquierda suma las horas de TODA la semana de cada
// trabajador contra su contrato. Ver backend/planificador.py.

const EMPRESA = new URLSearchParams(location.search).get("empresa") === "saona" ? "saona" : "kk";
const API = `${window.location.origin}/api/planificador`;
const PX_POR_MIN = 1.15; // ancho en px de cada minuto de la línea de tiempo
const SNAP = 10; // los bloques saltan de 10 en 10 minutos
const LS_CENTRO = `plan-centro-${EMPRESA}`;
const LS_VISTA = `plan-vista-${EMPRESA}`;
const LS_MODO = `plan-modo-${EMPRESA}`;
const SIN_ASIGNAR = 0;

const S = {
  centro: "",
  fecha: hoyISO(),
  vista: localStorage.getItem(LS_VISTA) === "semana" ? "semana" : "dia",
  modo: localStorage.getItem(LS_MODO) === "slots" ? "slots" : "turnos",
  config: { apertura_min: 480, cierre_min: 1500, objetivo_transacciones_hora: null },
  trabajadores: [],
  turnos: [],
  minutosSemana: {},
  diasTrabajados: {},
  proyeccion: {},
  slots: [],
  slotActivo: null, // id del turno-slot seleccionado en modo Slots
  dias: [],
};

const DIAS_DESCANSO_MIN = 2; // 2 días de descanso semanales mínimo

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
  document.getElementById("plan-vista-dia").classList.toggle("activo", S.vista === "dia");
  document.getElementById("plan-vista-semana").classList.toggle("activo", S.vista === "semana");
  document.getElementById("plan-modo-turnos").classList.toggle("activo", S.modo === "turnos");
  document.getElementById("plan-modo-slots").classList.toggle("activo", S.modo === "slots");
  const endpoint = S.vista === "semana" ? "semana" : "dia";
  const res = await fetch(url(endpoint, { centro: S.centro, fecha: S.fecha }));
  if (!res.ok) {
    cont.innerHTML = `<p class="plan-vacia">No se pudo cargar.</p>`;
    return;
  }
  const data = await res.json();
  S.config = data.config;
  S.trabajadores = data.trabajadores;
  S.turnos = data.turnos;
  S.minutosSemana = data.minutos_semana || {};
  S.diasTrabajados = data.dias_trabajados || {};
  S.proyeccion = normalizarProyeccion(data.proyeccion || {});
  S.slots = data.slots || [];
  S.dias = data.dias || [];
  S.slotActivo = null;
  document.getElementById("plan-fecha-txt").textContent =
    S.vista === "semana" ? `Semana del ${fechaCorta(data.lunes || S.fecha)}` : fechaLarga(S.fecha);
  document.getElementById("plan-fecha-input").value = S.fecha;
  renderTodo();
}

function turnosDia(fecha) {
  // en vista día S.turnos ya es solo ese día; en semana es toda la semana
  return S.vista === "semana" ? S.turnos.filter((t) => t.fecha === fecha) : S.turnos;
}
function nombreTrabajador(id) {
  const w = S.trabajadores.find((x) => x.id === id);
  return w ? w.nombre : "";
}

function fechaCorta(iso) {
  const d = new Date(iso + "T12:00:00");
  return `${String(d.getDate()).padStart(2, "0")}/${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function normalizarProyeccion(obj) {
  // el backend devuelve las claves de franja como string -> a número
  const out = {};
  for (const k of Object.keys(obj)) out[Number(k)] = obj[k];
  return out;
}

// ---------------------------------------------------------------- render

function renderTodo() {
  document.querySelector(".plan-leyenda").hidden = S.modo === "slots";
  if (S.modo === "slots") {
    if (S.vista === "semana") renderSlotsSemana();
    else renderSlotsDia();
  } else if (S.vista === "semana") {
    renderSemana();
  } else {
    renderDia();
  }
}

function renderDia() {
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
        ${filaSinAsignar()}
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
  cont.querySelectorAll(".plan-libre-btn").forEach((btn) => {
    btn.addEventListener("click", () => toggleLibre(Number(btn.dataset.trab), S.fecha));
  });
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
    if (t.tipo === "libre") continue;
    if (t.inicio_min < m + 60 && t.inicio_min + t.duracion_min > m) ids.add(t.trabajador_id);
  }
  return ids.size;
}

function textoHoras(min, contrato) {
  const h = (Math.round((min / 60) * 100) / 100).toString().replace(".", ",");
  return contrato ? `${h} h / ${contrato} h (${Math.round((min / 60 / contrato) * 100)}%)` : `${h} h / sin contrato`;
}

// 🌙 con ✓ verde si el horario de la persona esta semana es correcto, o ✕
// rojo si hay conflicto: menos de 2 días de descanso, o más horas
// planificadas que las de su contrato.
function descansoIndicadorHTML(trabId, minSemana, contrato) {
  const descanso = 7 - (S.diasTrabajados[String(trabId)] || 0);
  const pocosDescansos = descanso < DIAS_DESCANSO_MIN;
  const sobreContrato = contrato && minSemana / 60 > contrato;
  const ok = !pocosDescansos && !sobreContrato;
  const motivos = [];
  if (pocosDescansos) motivos.push(`solo ${descanso} día${descanso === 1 ? "" : "s"} de descanso (mínimo ${DIAS_DESCANSO_MIN})`);
  if (sobreContrato) motivos.push(`${(minSemana / 60).toFixed(2).replace(/\.?0+$/, "").replace(".", ",")} h planificadas / ${contrato} h de contrato`);
  const titulo = ok
    ? `${descanso} días de descanso esta semana · dentro de contrato`
    : `Conflicto en el horario: ${motivos.join(" · ")} — revísalo`;
  return `<span class="plan-descanso ${ok ? "ok" : "mal"}" title="${titulo}">🌙<span class="plan-descanso-marca">${ok ? "✓" : "✕"}</span></span>`;
}

function filaTrabajador(t) {
  const min = S.minutosSemana[String(t.id)] || 0;
  const contrato = t.horas_contrato_semana;
  const pct = contrato ? min / 60 / contrato : 0;
  const clase = !contrato ? "" : pct >= 1 ? "rojo" : pct >= 0.85 ? "ambar" : "";
  const misTurnos = S.turnos.filter((x) => x.trabajador_id === t.id);
  const tieneLibre = misTurnos.some((x) => x.tipo === "libre");
  const bloques = misTurnos.map(turnoHTML).join("");
  const lineas = franjas().map((m) => `<div class="plan-lane-linea hora" style="left:${minToX(m)}px;"></div>`).join("");
  return `
    <div class="plan-fila">
      <div class="plan-celda-izq">
        <span class="plan-trab-nombre" title="${escapeHTML(t.nombre)}">${escapeHTML(t.nombre)}</span>
        <span class="plan-trab-horas">${textoHoras(min, contrato)}</span>
        <div class="plan-barra ${clase}"><i style="width:${Math.min(100, Math.round(pct * 100))}%;"></i></div>
        <div class="plan-fila-acciones">
          <button type="button" class="plan-libre-btn ${tieneLibre ? "activo" : ""}" data-trab="${t.id}">${tieneLibre ? "Quitar libre" : "Día libre"}</button>
          ${descansoIndicadorHTML(t.id, min, contrato)}
        </div>
      </div>
      <div class="plan-lane" data-trab="${t.id}">
        <div class="plan-lane-lineas">${lineas}</div>
        ${bloques}
      </div>
    </div>`;
}

function turnoHTML(t) {
  if (t.tipo === "libre") {
    return `<div class="plan-turno libre" data-id="${t.id}" data-tipo="libre">
      <span class="plan-turno-txt">Libre</span>
      <span class="plan-turno-x" title="Quitar día libre">✕</span>
    </div>`;
  }
  const sin = t.trabajador_id === SIN_ASIGNAR;
  return `<div class="plan-turno ${sin ? "sin-asignar" : ""}" data-id="${t.id}" data-trab="${t.trabajador_id}" data-inicio="${t.inicio_min}" data-duracion="${t.duracion_min}"
    style="left:${minToX(t.inicio_min)}px; width:${t.duracion_min * PX_POR_MIN}px;">
    <span class="plan-turno-txt">${sin ? `Sin asignar · ${fmtHoras(t.duracion_min)}` : etiquetaTurno(t.inicio_min, t.duracion_min)}</span>
    ${sin ? `<span class="plan-turno-asig" title="Asignar a alguien">👤</span>` : ""}
    <span class="plan-turno-x" title="Quitar">✕</span>
  </div>`;
}

// Los turnos de trabajo de una persona no se pueden solapar. `paredes`
// devuelve hasta dónde puede llegar un bloque por cada lado sin pisar a
// otro, tomando como referencia la posición original [refIni, refFin).
function paredes(trabId, excluirId, refIni, refFin) {
  let izq = S.config.apertura_min;
  let der = S.config.cierre_min;
  if (trabId === SIN_ASIGNAR) return { izq, der }; // los slots sin asignar pueden solaparse
  for (const o of S.turnos) {
    if (o.tipo === "libre" || o.trabajador_id !== trabId || String(o.id) === String(excluirId)) continue;
    const oFin = o.inicio_min + o.duracion_min;
    if (oFin <= refIni) izq = Math.max(izq, oFin);
    else if (o.inicio_min >= refFin) der = Math.min(der, o.inicio_min);
    else return { izq: refIni, der: refIni }; // el punto de referencia cae dentro de otro bloque
  }
  return { izq, der };
}

// Tras crear/mover/estirar un bloque: si queda pegado (borde con borde) a
// otro de la misma persona, ofrece unirlos en uno solo.
async function quizasUnir(turnoId, ini, fin, trabId) {
  if (trabId === SIN_ASIGNAR) return; // los slots sin asignar no se fusionan
  const vecino = S.turnos.find(
    (x) =>
      String(x.id) !== String(turnoId) &&
      x.trabajador_id === trabId &&
      x.tipo !== "libre" &&
      x.fecha === S.fecha &&
      (x.inicio_min + x.duracion_min === ini || x.inicio_min === fin)
  );
  if (!vecino) return;
  if (!(await pedirConfirmacion("Los dos turnos quedan pegados. ¿Unirlos en uno solo?"))) return;
  const res = await fetch(url(`turnos/${turnoId}/fusionar/${vecino.id}`), { method: "POST" });
  if (!res.ok) mostrarAviso("No se pudieron unir.");
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
  const esLibre = el.dataset.tipo === "libre";
  const btnAsig = el.querySelector(".plan-turno-asig");
  if (btnAsig) {
    btnAsig.addEventListener("pointerdown", (e) => e.stopPropagation());
    btnAsig.addEventListener("click", (e) => {
      e.stopPropagation();
      abrirPickerAsignar(Number(el.dataset.id));
    });
  }
  const btnX = el.querySelector(".plan-turno-x");
  btnX.addEventListener("pointerdown", (e) => e.stopPropagation());
  btnX.addEventListener("click", async (e) => {
    e.stopPropagation();
    if (!esLibre && !(await pedirConfirmacion("¿Quitar este turno?"))) return;
    const res = await fetch(url(`turnos/${el.dataset.id}`), { method: "DELETE" });
    if (!res.ok) {
      mostrarAviso("No se pudo quitar.");
      return;
    }
    cargarDia();
  });
  if (esLibre) return; // un día libre no se mueve ni se estira

  el.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    e.preventDefault();
    const rect = el.getBoundingClientRect();
    const cerca = 10;
    const modo = e.clientX - rect.left < cerca ? "izq" : rect.right - e.clientX < cerca ? "der" : "mover";
    const startX = e.clientX;
    const iniOrig = Number(el.dataset.inicio);
    const durOrig = Number(el.dataset.duracion);
    const trabId = Number(el.dataset.trab);
    const { izq, der } = paredes(trabId, el.dataset.id, iniOrig, iniOrig + durOrig);
    let ini = iniOrig;
    let dur = durOrig;
    try {
      el.setPointerCapture(e.pointerId);
    } catch {
      /* sin captura el arrastre sigue funcionando mientras el puntero no salga del bloque */
    }
    el.style.cursor = modo === "mover" ? "grabbing" : "ew-resize";

    const onMove = (ev) => {
      const dMin = snap((ev.clientX - startX) / PX_POR_MIN);
      if (modo === "mover") {
        ini = clamp(iniOrig + dMin, izq, der - durOrig);
        dur = durOrig;
      } else if (modo === "izq") {
        ini = clamp(iniOrig + dMin, izq, iniOrig + durOrig - SNAP);
        dur = iniOrig + durOrig - ini;
      } else {
        dur = clamp(durOrig + dMin, SNAP, der - iniOrig);
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
      if (!res.ok) {
        mostrarAviso("No se pudo guardar el cambio.");
        cargarDia();
        return;
      }
      await quizasUnir(el.dataset.id, ini, ini + dur, trabId);
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
    // el turno nuevo no puede pisar a otro de esa persona: se limita al
    // hueco libre alrededor del punto donde se ha pulsado.
    const { izq, der } = paredes(trabajadorId, null, iniClick, iniClick);
    if (der - izq < SNAP) return; // no cabe nada aquí
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
      const cursorMin = clamp(snap(xToMin(ev.clientX - laneRect.left)), izq, der);
      ini = clamp(Math.min(iniClick, cursorMin), izq, der - SNAP);
      dur = Math.max(SNAP, Math.abs(cursorMin - iniClick));
      if (ini + dur > der) dur = der - ini;
      fantasma.style.left = minToX(ini) + "px";
      fantasma.style.width = dur * PX_POR_MIN + "px";
    };
    const onUp = async () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      fantasma.remove();
      if (!arrastrado) {
        ini = clamp(iniClick, izq, der - SNAP);
        dur = Math.min(240, der - ini);
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
      const data = await res.json().catch(() => ({}));
      if (data.id) await quizasUnir(data.id, ini, ini + dur, trabajadorId);
      cargarDia();
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  });
}

// ---------------------------------------------------------------- sin asignar / slots

function filaSinAsignar() {
  const sin = turnosDia(S.fecha).filter((t) => t.trabajador_id === SIN_ASIGNAR && t.tipo === "trabajo");
  if (!sin.length) return "";
  const lineas = franjas().map((m) => `<div class="plan-lane-linea hora" style="left:${minToX(m)}px;"></div>`).join("");
  return `
    <div class="plan-fila">
      <div class="plan-celda-izq">
        <span class="plan-trab-nombre" style="color:var(--status-warning);">Sin asignar</span>
        <span class="plan-trab-horas">${sin.length} turno${sin.length === 1 ? "" : "s"} sin persona</span>
      </div>
      <div class="plan-lane" data-trab="0">
        <div class="plan-lane-lineas">${lineas}</div>
        ${sin.map(turnoHTML).join("")}
      </div>
    </div>`;
}

async function pintarSugeridos(container, turno, { drag = true } = {}) {
  container.innerHTML = `<h4>¿Quién en este turno?</h4><p class="staff-hint">Cargando…</p>`;
  const res = await fetch(
    url("sugerencias", {
      centro: S.centro,
      fecha: turno.fecha,
      inicio_min: turno.inicio_min,
      duracion_min: turno.duracion_min,
    })
  );
  const data = res.ok ? await res.json() : { sugerencias: [] };
  const filas = data.sugerencias
    .map((s) => {
      const h = (Math.round((s.minutos_semana / 60) * 100) / 100).toString().replace(".", ",");
      const detalle = s.disponible
        ? `<span class="plan-sug-h">${h} h${s.aviso ? ` · <span class="plan-sug-aviso">${s.aviso}</span>` : ""}</span>`
        : `<span class="plan-sug-h">${escapeHTML(s.motivo)}</span>`;
      return `<div class="plan-sug-fila ${s.disponible ? "" : "no-disp"}" data-trab="${s.trabajador_id}" ${
        s.disponible && drag ? 'draggable="true"' : ""
      }><span>${escapeHTML(s.nombre)}</span>${detalle}</div>`;
    })
    .join("");
  container.innerHTML = `<h4>¿Quién en ${fmtHHMM(turno.inicio_min)}–${fmtHHMM(turno.inicio_min + turno.duracion_min)}?</h4>${
    filas || `<p class="staff-hint">Nadie disponible.</p>`
  }`;
  container.querySelectorAll(".plan-sug-fila:not(.no-disp)").forEach((fila) => {
    fila.addEventListener("click", () => asignarTurno(turno.id, Number(fila.dataset.trab)));
    fila.addEventListener("dragstart", (e) => {
      e.dataTransfer.setData("text/plain", `trab:${fila.dataset.trab}`);
      e.dataTransfer.effectAllowed = "copy";
    });
  });
}

async function asignarTurno(turnoId, trabajadorId) {
  const res = await fetch(url(`turnos/${turnoId}/asignar`), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ trabajador_id: trabajadorId }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    mostrarAviso(err.detail || "No se pudo asignar.");
    return;
  }
  const dlg = document.getElementById("plan-dialog-asignar");
  if (dlg.open) dlg.close();
  cargarDia();
}

function abrirPickerAsignar(turnoId) {
  const turno = S.turnos.find((t) => String(t.id) === String(turnoId));
  if (!turno) return;
  const dlg = document.getElementById("plan-dialog-asignar");
  pintarSugeridos(dlg.querySelector(".plan-sugeridos"), turno, { drag: false });
  dlg.showModal();
}

async function crearSlotEnDia(slot, fecha) {
  const res = await fetch(url("turnos"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      centro: S.centro,
      fecha,
      trabajador_id: SIN_ASIGNAR,
      inicio_min: slot.inicio_min,
      duracion_min: slot.duracion_min,
    }),
  });
  if (!res.ok) {
    mostrarAviso("No se pudo colocar el slot.");
    return;
  }
  cargarDia();
}

function paletaHTML() {
  const chips = S.slots
    .map(
      (s) => `<div class="plan-slot-chip" draggable="true" data-slot="${s.id}">${escapeHTML(s.nombre)}
        <small>${fmtHHMM(s.inicio_min)}–${fmtHHMM(s.inicio_min + s.duracion_min)}</small></div>`
    )
    .join("");
  return `<div class="plan-paleta">${chips}<button type="button" class="plan-btn-icono" id="plan-slots-editar">＋ Editar slots</button></div>`;
}

function wirePaleta(root) {
  root.querySelectorAll(".plan-slot-chip").forEach((chip) => {
    chip.addEventListener("dragstart", (e) => {
      e.dataTransfer.setData("text/plain", `slot:${chip.dataset.slot}`);
      e.dataTransfer.effectAllowed = "copy";
    });
  });
  const btn = root.querySelector("#plan-slots-editar");
  if (btn) btn.addEventListener("click", abrirDialogoSlots);
}

// Maneja soltar en una zona: un chip de slot (crea turno sin asignar) o un
// nombre arrastrado (asigna, si el destino es un turno-slot con data-id).
function wireDrop(zona, fecha, turnoIdDestino = null) {
  zona.addEventListener("dragover", (e) => {
    e.preventDefault();
    zona.classList.add("drop-hover");
  });
  zona.addEventListener("dragleave", () => zona.classList.remove("drop-hover"));
  zona.addEventListener("drop", (e) => {
    e.preventDefault();
    zona.classList.remove("drop-hover");
    const dato = e.dataTransfer.getData("text/plain") || "";
    if (dato.startsWith("slot:")) {
      const slot = S.slots.find((s) => String(s.id) === dato.slice(5));
      if (slot) crearSlotEnDia(slot, fecha);
    } else if (dato.startsWith("trab:") && turnoIdDestino) {
      asignarTurno(turnoIdDestino, Number(dato.slice(5)));
    }
  });
}

function renderSlotsDia() {
  const cont = document.getElementById("plan-contenido");
  const fr = franjas();
  const ancho = anchoTimeline();
  const anchoHora = 60 * PX_POR_MIN;
  const ticksHTML = fr
    .map((m) => `<div class="plan-hora-tick" style="left:${minToX(m)}px; width:${anchoHora}px;">${fmtHHMM(m)}</div>`)
    .join("");
  const lineas = fr.map((m) => `<div class="plan-lane-linea hora" style="left:${minToX(m)}px;"></div>`).join("");
  const delDia = turnosDia(S.fecha)
    .filter((t) => t.tipo === "trabajo")
    .sort((a, b) => a.inicio_min - b.inicio_min || a.duracion_min - b.duracion_min);
  const lanes = delDia
    .map((t) => {
      const sin = t.trabajador_id === SIN_ASIGNAR;
      const activo = String(S.slotActivo) === String(t.id) ? "activo" : "";
      return `<div class="plan-slot-lane" data-linea>
        <div class="plan-lane-lineas">${lineas}</div>
        <div class="plan-slot-turno ${sin ? "sin-asignar" : ""} ${activo}" data-id="${t.id}"
          style="left:${minToX(t.inicio_min)}px; width:${t.duracion_min * PX_POR_MIN}px;">
          <span>${sin ? "Sin asignar" : escapeHTML(nombreTrabajador(t.trabajador_id))} · ${fmtHoras(t.duracion_min)}</span>
          <span class="plan-turno-x" title="Quitar">✕</span>
        </div>
      </div>`;
    })
    .join("");

  cont.innerHTML = `
    ${paletaHTML()}
    <div class="plan-slots-layout">
      <div class="plan-slots-main">
        <div class="plan-grid-scroll plan-slots-drop" id="plan-slots-zona">
          <div class="plan-grid" style="--plan-ancho:${ancho}px;">
            <div class="plan-horas-fila"><div class="plan-esquina"></div><div class="plan-horas">${ticksHTML}</div></div>
            ${lanes || `<div class="plan-vacia">Arrastra un slot de arriba aquí para empezar.</div>`}
          </div>
        </div>
      </div>
      <div class="plan-sugeridos"><h4>Elige un slot</h4><p class="staff-hint">Haz clic en un slot colocado para ver a quién puedes poner.</p></div>
    </div>`;

  wirePaleta(cont);
  wireDrop(cont.querySelector("#plan-slots-zona"), S.fecha);
  cont.querySelectorAll(".plan-slot-turno").forEach((el) => {
    wireDrop(el, S.fecha, Number(el.dataset.id));
    el.querySelector(".plan-turno-x").addEventListener("click", async (e) => {
      e.stopPropagation();
      if (!(await pedirConfirmacion("¿Quitar este slot?"))) return;
      const r = await fetch(url(`turnos/${el.dataset.id}`), { method: "DELETE" });
      if (!r.ok) return mostrarAviso("No se pudo quitar.");
      cargarDia();
    });
    el.addEventListener("click", () => {
      S.slotActivo = Number(el.dataset.id);
      cont.querySelectorAll(".plan-slot-turno").forEach((x) => x.classList.toggle("activo", x === el));
      const turno = delDia.find((t) => String(t.id) === el.dataset.id);
      pintarSugeridos(cont.querySelector(".plan-sugeridos"), turno);
    });
  });
}

function renderSlotsSemana() {
  const cont = document.getElementById("plan-contenido");
  const dias = S.dias.length ? S.dias : [S.fecha];
  const nombresDia = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"];
  const cols = dias
    .map((d, i) => {
      const slotsDia = S.turnos
        .filter((t) => t.fecha === d && t.tipo === "trabajo")
        .sort((a, b) => a.inicio_min - b.inicio_min);
      const items = slotsDia
        .map((t) => {
          const sin = t.trabajador_id === SIN_ASIGNAR;
          const activo = String(S.slotActivo) === String(t.id) ? "activo" : "";
          return `<div class="plan-sem-slot ${sin ? "sin-asignar" : ""} ${activo}" data-id="${t.id}" data-fecha="${d}">
            ${sin ? "Sin asignar" : escapeHTML(nombreTrabajador(t.trabajador_id))}
            <small>${fmtHHMM(t.inicio_min)}–${fmtHHMM(t.inicio_min + t.duracion_min)}</small>
          </div>`;
        })
        .join("");
      return `<div class="plan-slots-col" data-fecha="${d}">
        <h5 data-fecha="${d}">${nombresDia[i]} ${fechaCorta(d)}</h5>
        ${items}
      </div>`;
    })
    .join("");

  cont.innerHTML = `
    ${paletaHTML()}
    <div class="plan-slots-layout">
      <div class="plan-slots-main"><div class="plan-slots-sem">${cols}</div></div>
      <div class="plan-sugeridos"><h4>Elige un slot</h4><p class="staff-hint">Haz clic en un slot para ver a quién puedes poner.</p></div>
    </div>`;

  wirePaleta(cont);
  cont.querySelectorAll(".plan-slots-col").forEach((col) => wireDrop(col, col.dataset.fecha));
  cont.querySelectorAll(".plan-slots-col h5").forEach((h) => {
    h.addEventListener("click", () => {
      S.fecha = h.dataset.fecha;
      S.vista = "dia";
      localStorage.setItem(LS_VISTA, "dia");
      cargarDia();
    });
  });
  cont.querySelectorAll(".plan-sem-slot").forEach((el) => {
    wireDrop(el, el.dataset.fecha, Number(el.dataset.id));
    el.addEventListener("click", () => {
      S.slotActivo = Number(el.dataset.id);
      cont.querySelectorAll(".plan-sem-slot").forEach((x) => x.classList.toggle("activo", x === el));
      const turno = S.turnos.find((t) => String(t.id) === el.dataset.id);
      pintarSugeridos(cont.querySelector(".plan-sugeridos"), turno);
    });
  });
}

function abrirDialogoSlots() {
  const dlg = document.getElementById("plan-dialog-slots");
  pintarSlotsLista();
  dlg.showModal();
}

function pintarSlotsLista() {
  const cont = document.getElementById("plan-slots-lista");
  cont.innerHTML = S.slots
    .map(
      (s) => `<div class="plan-roster-fila" data-id="${s.id}" style="grid-template-columns:1fr 80px 80px 34px;">
        <input type="text" class="ps-nombre" value="${escapeHTML(s.nombre)}">
        <input type="time" class="ps-ini" step="600" value="${fmtHHMM(s.inicio_min)}">
        <input type="time" class="ps-fin" step="600" value="${fmtHHMM(s.inicio_min + s.duracion_min)}">
        <button type="button" class="btn btn-ghost ps-borrar" style="font-size:12px; padding:4px 6px;">🗑</button>
      </div>`
    )
    .join("");
  const toMin = (v) => {
    const [h, m] = (v || "0:0").split(":").map(Number);
    return h * 60 + (m || 0);
  };
  cont.querySelectorAll(".plan-roster-fila").forEach((fila) => {
    const id = fila.dataset.id;
    const guardar = async () => {
      const ini = toMin(fila.querySelector(".ps-ini").value);
      let fin = toMin(fila.querySelector(".ps-fin").value);
      if (fin <= ini) fin += 1440;
      const r = await fetch(url(`slots/${id}`), {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ nombre: fila.querySelector(".ps-nombre").value, inicio_min: ini, duracion_min: fin - ini }),
      });
      if (!r.ok) mostrarAviso("No se pudo guardar el slot.");
    };
    fila.querySelectorAll("input").forEach((inp) => inp.addEventListener("change", guardar));
    fila.querySelector(".ps-borrar").addEventListener("click", async () => {
      await fetch(url(`slots/${id}`), { method: "DELETE" });
      const s = S.slots.find((x) => String(x.id) === id);
      if (s) S.slots.splice(S.slots.indexOf(s), 1);
      pintarSlotsLista();
    });
  });
}

function wireSlots() {
  const dlg = document.getElementById("plan-dialog-slots");
  dlg.querySelector("[data-cerrar]").addEventListener("click", () => {
    dlg.close();
    cargarDia();
  });
  document.getElementById("plan-slots-nuevo").addEventListener("click", async () => {
    const nombre = await pedirTexto("Nombre del slot:", "Turno");
    if (!nombre || !nombre.trim()) return;
    const iniS = await pedirTexto("Hora de inicio (HH:MM):", "09:00");
    const finS = await pedirTexto("Hora de fin (HH:MM):", "17:00");
    const toMin = (v) => {
      const [h, m] = (v || "0:0").split(":").map(Number);
      return h * 60 + (m || 0);
    };
    let ini = toMin(iniS);
    let fin = toMin(finS);
    if (fin <= ini) fin += 1440;
    const r = await fetch(url("slots"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nombre: nombre.trim(), inicio_min: ini, duracion_min: fin - ini }),
    });
    if (!r.ok) return mostrarAviso("No se pudo crear el slot.");
    const d = await r.json();
    S.slots.push({ id: d.id, nombre: nombre.trim(), inicio_min: ini, duracion_min: fin - ini });
    pintarSlotsLista();
  });
}

async function toggleLibre(trabajadorId, fecha) {
  const existente = S.turnos.find(
    (t) => t.trabajador_id === trabajadorId && t.tipo === "libre" && t.fecha === fecha
  );
  let res;
  if (existente) {
    res = await fetch(url(`turnos/${existente.id}`), { method: "DELETE" });
  } else {
    res = await fetch(url("turnos"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        centro: S.centro,
        fecha,
        trabajador_id: trabajadorId,
        inicio_min: S.config.apertura_min,
        duracion_min: S.config.cierre_min - S.config.apertura_min,
        tipo: "libre",
      }),
    });
  }
  if (!res.ok) {
    mostrarAviso("No se pudo cambiar el día libre.");
    return;
  }
  cargarDia();
}

// ---------------------------------------------------------------- vista semana

function renderSemana() {
  const cont = document.getElementById("plan-contenido");
  const dias = S.dias.length ? S.dias : [S.fecha];
  const nombresDia = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"];
  const hoy = hoyISO();

  const cabecera = `
    <div class="plan-sem-fila plan-sem-cabecera">
      <div class="plan-sem-nombre"></div>
      ${dias
        .map(
          (d, i) =>
            `<div class="plan-sem-dia ${d === hoy ? "hoy" : ""}" data-fecha="${d}">${nombresDia[i]} ${fechaCorta(d)}</div>`
        )
        .join("")}
    </div>`;

  const hayeSin = S.turnos.some((t) => t.trabajador_id === SIN_ASIGNAR && t.tipo === "trabajo");
  const filaSin = !hayeSin
    ? ""
    : `<div class="plan-sem-fila">
        <div class="plan-sem-nombre"><span class="plan-trab-nombre" style="color:var(--status-warning);">Sin asignar</span></div>
        ${dias
          .map((d) => {
            const sin = S.turnos
              .filter((x) => x.trabajador_id === SIN_ASIGNAR && x.tipo === "trabajo" && x.fecha === d)
              .sort((a, b) => a.inicio_min - b.inicio_min);
            return `<div class="plan-sem-celda">${sin
              .map(
                (x) =>
                  `<span class="plan-sem-chip sin-asignar-chip" data-id="${x.id}" title="Asignar">${fmtHHMM(x.inicio_min)}–${fmtHHMM(x.inicio_min + x.duracion_min)}</span>`
              )
              .join("")}</div>`;
          })
          .join("")}
      </div>`;

  const filas = S.trabajadores
    .map((t) => {
      const min = S.minutosSemana[String(t.id)] || 0;
      const contrato = t.horas_contrato_semana;
      const pct = contrato ? min / 60 / contrato : 0;
      const claseBarra = !contrato ? "" : pct >= 1 ? "rojo" : pct >= 0.85 ? "ambar" : "";
      const celdas = dias
        .map((d) => {
          const delDia = S.turnos.filter((x) => x.trabajador_id === t.id && x.fecha === d);
          const libre = delDia.some((x) => x.tipo === "libre");
          const trabajo = delDia.filter((x) => x.tipo !== "libre").sort((a, b) => a.inicio_min - b.inicio_min);
          const chips = trabajo
            .map((x) => `<span class="plan-sem-chip">${fmtHHMM(x.inicio_min)}–${fmtHHMM(x.inicio_min + x.duracion_min)}</span>`)
            .join("");
          return `<div class="plan-sem-celda ${libre ? "libre" : ""}" data-trab="${t.id}" data-fecha="${d}">
            <span class="plan-sem-luna ${libre ? "activo" : ""}" data-trab="${t.id}" data-fecha="${d}" title="Día libre">🌙</span>
            ${libre ? `<span class="plan-sem-libre-txt">Libre</span>` : chips}
          </div>`;
        })
        .join("");
      return `
        <div class="plan-sem-fila">
          <div class="plan-sem-nombre">
            <span class="plan-trab-nombre" title="${escapeHTML(t.nombre)}">${escapeHTML(t.nombre)}</span>
            <span class="plan-trab-horas">${textoHoras(min, contrato)}</span>
            <div class="plan-barra ${claseBarra}"><i style="width:${Math.min(100, Math.round(pct * 100))}%;"></i></div>
            <div class="plan-fila-acciones">${descansoIndicadorHTML(t.id, min, contrato)}</div>
          </div>
          ${celdas}
        </div>`;
    })
    .join("");

  cont.innerHTML = `
    <div class="plan-grid-scroll">
      <div class="plan-semana">
        ${cabecera}
        ${filaSin}
        ${S.trabajadores.length === 0 ? `<div class="plan-vacia">Este centro no tiene trabajadores en la plantilla.</div>` : filas}
      </div>
    </div>`;

  cont.querySelectorAll(".sin-asignar-chip").forEach((el) => {
    el.addEventListener("click", (e) => {
      e.stopPropagation();
      abrirPickerAsignar(Number(el.dataset.id));
    });
  });
  cont.querySelectorAll(".plan-sem-dia").forEach((el) => {
    el.addEventListener("click", () => {
      S.fecha = el.dataset.fecha;
      S.vista = "dia";
      localStorage.setItem(LS_VISTA, "dia");
      cargarDia();
    });
  });
  cont.querySelectorAll(".plan-sem-luna").forEach((el) => {
    el.addEventListener("click", (e) => {
      e.stopPropagation();
      toggleLibre(Number(el.dataset.trab), el.dataset.fecha);
    });
  });
  cont.querySelectorAll(".plan-sem-celda").forEach((el) => {
    el.addEventListener("click", () => {
      S.fecha = el.dataset.fecha;
      S.vista = "dia";
      localStorage.setItem(LS_VISTA, "dia");
      cargarDia();
    });
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
    const horasStr = await pedirTexto("Horas de contrato por semana:", "40");
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
  wireSlots();
  document
    .getElementById("plan-dialog-asignar")
    .querySelector("[data-cerrar]")
    .addEventListener("click", () => document.getElementById("plan-dialog-asignar").close());

  document.getElementById("plan-centro").addEventListener("change", (e) => {
    S.centro = e.target.value;
    localStorage.setItem(LS_CENTRO, S.centro);
    cargarDia();
  });
  const setVista = (v) => {
    S.vista = v;
    localStorage.setItem(LS_VISTA, v);
    cargarDia();
  };
  document.getElementById("plan-vista-dia").addEventListener("click", () => setVista("dia"));
  document.getElementById("plan-vista-semana").addEventListener("click", () => setVista("semana"));
  const setModo = (m) => {
    S.modo = m;
    localStorage.setItem(LS_MODO, m);
    cargarDia();
  };
  document.getElementById("plan-modo-turnos").addEventListener("click", () => setModo("turnos"));
  document.getElementById("plan-modo-slots").addEventListener("click", () => setModo("slots"));
  const pasoDias = () => (S.vista === "semana" ? 7 : 1);
  document.getElementById("plan-dia-prev").addEventListener("click", () => {
    S.fecha = sumarDias(S.fecha, -pasoDias());
    cargarDia();
  });
  document.getElementById("plan-dia-next").addEventListener("click", () => {
    S.fecha = sumarDias(S.fecha, pasoDias());
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

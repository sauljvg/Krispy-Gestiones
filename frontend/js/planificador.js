// Planificador de turnos -- línea de tiempo horizontal por horas de un día.
// Bloques (turnos) arrastrables y redimensionables por los bordes; el
// contador de la izquierda suma las horas de TODA la semana de cada
// trabajador contra su contrato. Ver backend/planificador.py.

const EMPRESA = new URLSearchParams(location.search).get("empresa") === "saona" ? "saona" : "kk";
const API = `${window.location.origin}/api/planificador`;
const PX_POR_MIN = 1.15; // ancho en px de cada minuto de la línea de tiempo
const SNAP = 10; // los bloques saltan de 10 en 10 minutos
const MIN_DUR = 60; // un turno dura entre 1 h...
const MAX_DUR = 600; // ...y 10 h
const LS_CENTRO = `plan-centro-${EMPRESA}`;
const LS_VISTA = `plan-vista-${EMPRESA}`;
const LS_MODO = `plan-modo-${EMPRESA}`;
const SIN_ASIGNAR = 0;
// Convenio de Madrid: turnos de 6 h o más llevan 20 min de bocadillo que NO
// computan como trabajo -- se SUMAN a la presencia (la persona sale 20 min más
// tarde) pero no a las horas que cuentan contra el contrato.
const BOCADILLO_MIN = 20;
const BOCADILLO_DESDE = 360;

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
function fmtHMM(min) {
  const m = Math.max(0, Math.round(min));
  return `${Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")}`;
}
function fmtHoras(min) {
  // Horas en formato H:MM (8:20 h), no decimal.
  return fmtHMM(min) + " h";
}
function boc(dur) {
  return dur >= BOCADILLO_DESDE ? BOCADILLO_MIN : 0;
}
function presenciaMin(dur) {
  // Minutos que la persona está presente = horas efectivas + bocadillo.
  return dur + boc(dur);
}
// El bocadillo de un turno de 6 h+ va al FINAL (turnos de apertura / mañana)
// salvo que eso empujaría la presencia más allá del cierre -> entonces al
// PRINCIPIO (turnos de cierre).
function bocLado(inicioMin, dur) {
  if (!boc(dur)) return "";
  return inicioMin + dur + BOCADILLO_MIN > S.config.cierre_min ? "inicio" : "fin";
}
// Geometría del bloque en la línea de tiempo: inicio/fin de PRESENCIA (con
// bocadillo donde corresponda) y el lado en que va la franja rayada.
function bloqueGeom(inicioMin, dur) {
  const lado = bocLado(inicioMin, dur);
  const presIni = inicioMin - (lado === "inicio" ? BOCADILLO_MIN : 0);
  const presFin = inicioMin + dur + (lado === "fin" ? BOCADILLO_MIN : 0);
  return { lado, presIni, presFin, left: minToX(presIni), width: (presFin - presIni) * PX_POR_MIN };
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
function lunesDe(iso) {
  const d = new Date(iso + "T12:00:00");
  return sumarDias(iso, -((d.getDay() + 6) % 7));
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
  // Conserva la posición del scroll: al quitar un slot o un día libre no
  // debe saltar arriba ni recargar visualmente toda la página.
  const sy = window.scrollY;
  const sx = document.querySelector(".plan-grid-scroll")?.scrollLeft || 0;
  const primeraVez = !cont.querySelector(".plan-grid, .plan-semana, .plan-slots-layout");
  if (primeraVez) cont.innerHTML = `<p class="plan-vacia">Cargando…</p>`;
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
  window.scrollTo(0, sy);
  const gs = document.querySelector(".plan-grid-scroll");
  if (gs) gs.scrollLeft = sx;
}

function totalMinDia(fecha) {
  // Horas efectivas de ese día -- solo turnos de trabajo CON persona (un slot
  // sin asignar todavía no son horas trabajadas). El bocadillo no computa.
  return S.turnos
    .filter((t) => t.fecha === fecha && t.tipo === "trabajo" && t.trabajador_id !== SIN_ASIGNAR)
    .reduce((s, t) => s + t.duracion_min, 0);
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
    <p class="plan-dia-total">Total del día: <b>${fmtHMM(totalMinDia(S.fecha))}</b></p>
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
  cont.querySelectorAll(".plan-libre-btn:not(.plan-vac-btn)").forEach((btn) => {
    btn.addEventListener("click", () => toggleLibre(Number(btn.dataset.trab), S.fecha));
  });
  cont.querySelectorAll(".plan-vac-btn").forEach((btn) => {
    btn.addEventListener("click", () => abrirDialogoVacaciones(Number(btn.dataset.trab), btn.dataset.nombre));
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
    if (t.tipo !== "trabajo" || t.trabajador_id === SIN_ASIGNAR) continue;
    if (t.inicio_min < m + 60 && t.inicio_min + t.duracion_min > m) ids.add(t.trabajador_id);
  }
  return ids.size;
}

function textoHoras(min, contrato) {
  const h = fmtHMM(min);
  return contrato
    ? `${h} h / ${fmtHMM(contrato * 60)} h (${Math.round((min / 60 / contrato) * 100)}%)`
    : `${h} h / sin contrato`;
}

// --- Horas complementarias (convenio) ---
const COMP_TECHO = 1.45; // 145% del contrato: contrato + 30% pactadas + 15% voluntarias
const COMP_VOLUNTARIAS_DESDE = 1.3; // a partir del 130% ya son voluntarias
function admiteComplementarias(contrato) {
  // Solo tiempo parcial, salvo que el centro lo abra a jornada completa.
  if (!contrato) return false;
  return contrato < 40 || !!S.config.complementarias_jornada_completa;
}
function techoMinSemana(contrato) {
  return admiteComplementarias(contrato) ? Math.round(contrato * 60 * COMP_TECHO) : Infinity;
}
// Cuántos minutos más se le pueden planificar a alguien esta semana antes de
// tocar su tope de complementarias (Infinity si no aplica / no tiene tope).
function margenComplementariasMin(trabId, excluirDurMin = 0) {
  const w = S.trabajadores.find((x) => x.id === trabId);
  if (!w || !admiteComplementarias(w.horas_contrato_semana)) return Infinity;
  const ya = (S.minutosSemana[String(trabId)] || 0) - excluirDurMin;
  return Math.max(0, techoMinSemana(w.horas_contrato_semana) - ya);
}
// Pide confirmación si el resultado deja a la persona en horas complementarias
// (amarillo, >100%) o voluntarias (rojo, >130%). Devuelve true si sigue adelante.
async function confirmarComplementarias(contrato, prevMin, nuevoMin) {
  if (!admiteComplementarias(contrato) || nuevoMin <= prevMin) return true;
  const cont = contrato * 60;
  if (nuevoMin <= cont) return true;
  const hN = fmtHMM(nuevoMin);
  const hC = fmtHMM(cont);
  if (nuevoMin > cont * COMP_VOLUNTARIAS_DESDE) {
    return pedirConfirmacion(
      `Se pasaría a ${hN} h (contrato ${hC} h): entra en horas complementarias VOLUNTARIAS ` +
        `(requieren acuerdo del trabajador). Puede que no le queden 2 días de descanso. ¿Confirmas?`
    );
  }
  return pedirConfirmacion(
    `Se pasaría a ${hN} h (contrato ${hC} h): el resto serán horas complementarias. ` +
      `Puede que no le queden 2 días de descanso. ¿Confirmas?`
  );
}

// Barra de horas: 3 tramos (verde contrato / amarillo pactadas / rojo
// voluntarias) para tiempo parcial; barra simple para jornada completa.
function barraHorasHTML(min, contrato) {
  if (!contrato) return `<div class="plan-barra"><i style="width:0%;"></i></div>`;
  const pct = min / 60 / contrato;
  if (!admiteComplementarias(contrato)) {
    const clase = pct >= 1 ? "rojo" : pct >= 0.85 ? "ambar" : "";
    return `<div class="plan-barra ${clase}"><i style="width:${Math.min(100, Math.round(pct * 100))}%;"></i></div>`;
  }
  const esc = (p) => (Math.max(0, Math.min(p, COMP_TECHO)) / COMP_TECHO) * 100;
  const verde = esc(Math.min(pct, 1));
  const amar = esc(Math.min(pct, COMP_VOLUNTARIAS_DESDE)) - verde;
  const rojo = esc(Math.min(pct, COMP_TECHO)) - esc(Math.min(pct, COMP_VOLUNTARIAS_DESDE));
  return `<div class="plan-barra plan-barra-comp" title="${Math.round(pct * 100)}% del contrato (tope 145% con complementarias)">
    <i class="seg-verde" style="width:${verde}%;"></i>
    <i class="seg-amar" style="width:${amar}%;"></i>
    <i class="seg-rojo" style="width:${rojo}%;"></i>
    <span class="plan-barra-marca" style="left:${esc(1)}%;"></span>
    <span class="plan-barra-marca" style="left:${esc(COMP_VOLUNTARIAS_DESDE)}%;"></span>
  </div>`;
}

// 🛏 con ✓ verde si el horario de la persona esta semana es correcto, o ✕
// rojo si hay conflicto: menos de 2 días de descanso, o más horas
// planificadas que las de su contrato.
function descansoIndicadorHTML(trabId, minSemana, contrato) {
  const descanso = 7 - (S.diasTrabajados[String(trabId)] || 0);
  const pocosDescansos = descanso < DIAS_DESCANSO_MIN;
  // Para tiempo parcial, estar por encima del contrato es lo esperado con
  // complementarias; solo es conflicto pasar del 145%.
  const limite = admiteComplementarias(contrato) ? contrato * COMP_TECHO : contrato;
  const sobreContrato = contrato && minSemana / 60 > limite;
  const ok = !pocosDescansos && !sobreContrato;
  const motivos = [];
  if (pocosDescansos) motivos.push(`solo ${descanso} día${descanso === 1 ? "" : "s"} de descanso (mínimo ${DIAS_DESCANSO_MIN})`);
  if (sobreContrato) motivos.push(`${fmtHMM(minSemana)} h planificadas / ${fmtHMM(contrato * 60)} h de contrato`);
  const titulo = ok
    ? `${descanso} días de descanso esta semana · dentro de contrato`
    : `Conflicto en el horario: ${motivos.join(" · ")} — revísalo`;
  return `<span class="plan-descanso ${ok ? "ok" : "mal"}" title="${titulo}">🛏<span class="plan-descanso-marca">${ok ? "✓" : "✕"}</span></span>`;
}

function filaTrabajador(t) {
  const min = S.minutosSemana[String(t.id)] || 0;
  const contrato = t.horas_contrato_semana;
  const misTurnos = S.turnos.filter((x) => x.trabajador_id === t.id);
  const tieneLibre = misTurnos.some((x) => x.tipo === "libre");
  const bloques = misTurnos.map(turnoHTML).join("");
  const lineas = franjas().map((m) => `<div class="plan-lane-linea hora" style="left:${minToX(m)}px;"></div>`).join("");
  return `
    <div class="plan-fila">
      <div class="plan-celda-izq">
        <span class="plan-trab-nombre" title="${escapeHTML(t.nombre)}">${escapeHTML(t.nombre)}</span>
        <span class="plan-trab-horas">${textoHoras(min, contrato)}</span>
        ${barraHorasHTML(min, contrato)}
        <div class="plan-fila-acciones">
          <button type="button" class="plan-libre-btn ${tieneLibre ? "activo" : ""}" data-trab="${t.id}">${tieneLibre ? "Quitar libre" : "Día libre"}</button>
          <button type="button" class="plan-libre-btn plan-vac-btn" data-trab="${t.id}" data-nombre="${escapeHTML(t.nombre)}">🏖 Vacaciones</button>
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
  if (t.tipo === "libre" || t.tipo === "vacaciones") {
    const vac = t.tipo === "vacaciones";
    return `<div class="plan-turno libre ${vac ? "vacaciones" : ""}" data-id="${t.id}" data-tipo="${t.tipo}">
      <span class="plan-turno-txt">${vac ? "Vacaciones" : "Libre"}</span>
      <span class="plan-turno-x" title="${vac ? "Quitar vacaciones (solo este día)" : "Quitar día libre"}">✕</span>
    </div>`;
  }
  const sin = t.trabajador_id === SIN_ASIGNAR;
  const b = boc(t.duracion_min);
  const g = bloqueGeom(t.inicio_min, t.duracion_min);
  const titulo = b
    ? `${fmtHoras(t.duracion_min)} efectivas · 20 min de bocadillo al ${g.lado === "inicio" ? "principio" : "final"} (no computa)`
    : "";
  return `<div class="plan-turno ${sin ? "sin-asignar" : ""}" data-id="${t.id}" data-trab="${t.trabajador_id}" data-inicio="${t.inicio_min}" data-duracion="${t.duracion_min}"
    style="left:${g.left}px; width:${g.width}px;"${titulo ? ` title="${titulo}"` : ""}>
    <span class="plan-turno-txt">${sin ? `Sin asignar · ${fmtHoras(t.duracion_min)}` : etiquetaTurno(t.inicio_min, t.duracion_min)}</span>
    <i class="plan-turno-boc ${g.lado === "inicio" ? "boc-inicio" : ""}" style="width:${b * PX_POR_MIN}px;"></i>
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
  // El rango muestra la PRESENCIA (con bocadillo, al inicio o al fin); "· X h"
  // son las horas efectivas que sí computan.
  const g = bloqueGeom(inicio, dur);
  return presenciaMin(dur) * PX_POR_MIN < 95
    ? fmtHoras(dur)
    : `${fmtHHMM(g.presIni)}–${fmtHHMM(g.presFin)} · ${fmtHoras(dur)}`;
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
  // Día libre y vacaciones: bloque fijo a toda la franja -- no se mueve ni se
  // estira, y la ✕ lo quita sin preguntar (como el botón "Quitar libre").
  const esLibre = el.dataset.tipo === "libre" || el.dataset.tipo === "vacaciones";
  // Un "slot grupo" (varias personas en el mismo horario) lleva data-ids con
  // todos los turnos que representa; mover/estirar o quitar afecta a todos.
  const ids = el.dataset.ids ? el.dataset.ids.split(",").filter(Boolean) : [el.dataset.id];
  const esGrupo = !!el.dataset.ids;
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
    if (esGrupo) {
      const n = ids.length;
      if (!(await pedirConfirmacion(`¿Quitar este slot del día?${n > 1 ? ` (${n} personas)` : ""}`))) return;
    } else if (!esLibre && !(await pedirConfirmacion("¿Quitar este turno?"))) {
      return;
    }
    const rs = await Promise.all(ids.map((id) => fetch(url(`turnos/${id}`), { method: "DELETE" })));
    if (rs.some((r) => !r.ok)) mostrarAviso("No se pudo quitar todo.");
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
    // Tope duro: no dejar estirar más allá del 145% del contrato (complementarias).
    const maxDur = Math.min(MAX_DUR, margenComplementariasMin(trabId, durOrig));
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
        ini = clamp(iniOrig + dMin, Math.max(izq, iniOrig + durOrig - maxDur), iniOrig + durOrig - MIN_DUR);
        dur = iniOrig + durOrig - ini;
      } else {
        dur = clamp(durOrig + dMin, MIN_DUR, Math.min(der - iniOrig, maxDur));
        ini = iniOrig;
      }
      const g = bloqueGeom(ini, dur);
      el.style.left = g.left + "px";
      el.style.width = g.width + "px";
      const bocEl = el.querySelector(".plan-turno-boc");
      if (bocEl) {
        bocEl.style.width = boc(dur) * PX_POR_MIN + "px";
        bocEl.classList.toggle("boc-inicio", g.lado === "inicio");
      }
      el.querySelector(".plan-turno-txt").textContent = el.classList.contains("sin-asignar")
        ? `Sin asignar · ${fmtHoras(dur)}`
        : etiquetaTurno(ini, dur);
    };
    const onUp = async () => {
      el.releasePointerCapture(e.pointerId);
      el.removeEventListener("pointermove", onMove);
      el.removeEventListener("pointerup", onUp);
      el.style.cursor = "grab";
      if (ini === iniOrig && dur === durOrig) return;
      if (!esGrupo && dur > durOrig && trabId !== SIN_ASIGNAR) {
        const w = S.trabajadores.find((x) => x.id === trabId);
        const prev = S.minutosSemana[String(trabId)] || 0;
        if (w && !(await confirmarComplementarias(w.horas_contrato_semana, prev, prev - durOrig + dur))) {
          cargarDia();
          return;
        }
      }
      const rs = await Promise.all(
        ids.map((id) =>
          fetch(url(`turnos/${id}`), {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ inicio_min: ini, duracion_min: dur }),
          })
        )
      );
      if (rs.some((r) => !r.ok)) {
        mostrarAviso("No se pudo guardar el cambio.");
        cargarDia();
        return;
      }
      if (!esGrupo) await quizasUnir(el.dataset.id, ini, ini + dur, trabId);
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
    const maxNuevo = Math.min(MAX_DUR, margenComplementariasMin(trabajadorId, 0));
    if (der - izq < MIN_DUR) {
      mostrarAviso("No cabe un turno de 1 h en este hueco.");
      return;
    }
    if (maxNuevo < MIN_DUR) {
      mostrarAviso("Esa persona ya está en su tope de horas complementarias (145% del contrato).");
      return;
    }
    const fantasma = document.createElement("div");
    fantasma.className = "plan-turno-fantasma";
    fantasma.style.left = minToX(iniClick) + "px";
    fantasma.style.width = MIN_DUR * PX_POR_MIN + "px";
    lane.appendChild(fantasma);
    let ini = iniClick;
    let dur = MIN_DUR;
    let arrastrado = false;
    const topeDer = Math.min(der, izq + maxNuevo);

    const onMove = (ev) => {
      arrastrado = arrastrado || Math.abs(ev.clientX - startX) > 4;
      const cursorMin = clamp(snap(xToMin(ev.clientX - laneRect.left)), izq, topeDer);
      ini = clamp(Math.min(iniClick, cursorMin), izq, der - MIN_DUR);
      dur = clamp(Math.abs(cursorMin - iniClick), MIN_DUR, maxNuevo);
      if (ini + dur > der) dur = der - ini;
      fantasma.style.left = minToX(ini) + "px";
      fantasma.style.width = dur * PX_POR_MIN + "px";
    };
    const onUp = async () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      fantasma.remove();
      if (!arrastrado) {
        ini = clamp(iniClick, izq, der - MIN_DUR);
        dur = clamp(Math.min(240, der - ini), MIN_DUR, maxNuevo);
      }
      if (dur < MIN_DUR) return;
      const w = S.trabajadores.find((x) => x.id === trabajadorId);
      const prev = S.minutosSemana[String(trabajadorId)] || 0;
      if (w && !(await confirmarComplementarias(w.horas_contrato_semana, prev, prev + dur))) return;
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
      const h = fmtHMM(s.minutos_semana);
      const detalle = s.disponible
        ? `<span class="plan-sug-h">${h} h${s.aviso ? ` · <span class="plan-sug-aviso">${s.aviso}</span>` : ""}</span>`
        : `<span class="plan-sug-h">${escapeHTML(s.motivo)}</span>`;
      return `<div class="plan-sug-fila ${s.disponible ? "" : "no-disp"} ${
        s.complementaria ? "comp-" + s.complementaria : ""
      }" data-trab="${s.trabajador_id}" ${
        s.disponible && drag ? 'draggable="true"' : ""
      }><span>${escapeHTML(s.nombre)}</span>${detalle}</div>`;
    })
    .join("");
  container.innerHTML = `<h4>¿Quién en ${fmtHHMM(turno.inicio_min)}–${fmtHHMM(turno.inicio_min + presenciaMin(turno.duracion_min))}?</h4>${
    filas || `<p class="staff-hint">Nadie disponible.</p>`
  }`;
  container.querySelectorAll(".plan-sug-fila:not(.no-disp)").forEach((fila) => {
    fila.addEventListener("click", () =>
      turno._grupo
        ? asignarAGrupo(turno._grupo, Number(fila.dataset.trab))
        : asignarTurno(turno.id, Number(fila.dataset.trab))
    );
    fila.addEventListener("dragstart", (e) => {
      e.dataTransfer.setData("text/plain", `trab:${fila.dataset.trab}`);
      e.dataTransfer.effectAllowed = "copy";
    });
  });
}

async function asignarTurno(turnoId, trabajadorId) {
  if (trabajadorId !== SIN_ASIGNAR) {
    const turno = S.turnos.find((t) => String(t.id) === String(turnoId));
    const w = S.trabajadores.find((x) => x.id === trabajadorId);
    if (turno && w) {
      const prev = S.minutosSemana[String(trabajadorId)] || 0;
      if (!(await confirmarComplementarias(w.horas_contrato_semana, prev, prev + turno.duracion_min))) return;
    }
  }
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
    .map((s) => {
      const g = bloqueGeom(s.inicio_min, s.duracion_min);
      return `<div class="plan-slot-chip" draggable="true" data-slot="${s.id}">${escapeHTML(s.nombre)}
        <small>${fmtHHMM(g.presIni)}–${fmtHHMM(g.presFin)}</small></div>`;
    })
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
function wireDrop(zona, fecha, turnoIdDestino = null, grupoDestino = null) {
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
    } else if (dato.startsWith("trab:")) {
      if (grupoDestino) asignarAGrupo(grupoDestino, Number(dato.slice(5)));
      else if (turnoIdDestino) asignarTurno(turnoIdDestino, Number(dato.slice(5)));
    }
  });
}

// Un "slot" que hacen varias personas se guarda como varios turnos con el
// MISMO (inicio, duración). Aquí se agrupan para pintar un único bloque con
// un contador de personas.
function agruparSlots(turnos) {
  const map = new Map();
  for (const t of turnos) {
    if (t.tipo !== "trabajo") continue;
    const k = `${t.inicio_min}-${t.duracion_min}`;
    if (!map.has(k)) map.set(k, { key: k, fecha: t.fecha, ini: t.inicio_min, dur: t.duracion_min, turnos: [] });
    map.get(k).turnos.push(t);
  }
  return [...map.values()].sort((a, b) => a.ini - b.ini || a.dur - b.dur);
}

function grupoAsignados(g) {
  return g.turnos.filter((t) => t.trabajador_id !== SIN_ASIGNAR);
}
function grupoLibres(g) {
  return g.turnos.filter((t) => t.trabajador_id === SIN_ASIGNAR);
}

function slotGrupoHTML(g) {
  const asg = grupoAsignados(g);
  const lib = grupoLibres(g);
  const b = boc(g.dur);
  const gm = bloqueGeom(g.ini, g.dur);
  const activo = String(S.slotActivo) === g.key ? "slot-activo" : "";
  const num = `👥 ${asg.length}${lib.length ? ` +${lib.length}` : ""}`;
  return `<div class="plan-turno slot-grupo ${asg.length ? "" : "sin-asignar"} ${activo}"
      data-key="${g.key}" data-ids="${g.turnos.map((t) => t.id).join(",")}"
      data-inicio="${g.ini}" data-duracion="${g.dur}" data-trab="0"
      style="left:${gm.left}px; width:${gm.width}px;"
      title="${b ? `${fmtHoras(g.dur)} efectivas + 20 min de bocadillo al ${gm.lado === "inicio" ? "principio" : "final"} (no computa)` : ""}">
    <span class="plan-turno-txt">${etiquetaTurno(g.ini, g.dur)}</span>
    <i class="plan-turno-boc ${gm.lado === "inicio" ? "boc-inicio" : ""}" style="width:${b * PX_POR_MIN}px;"></i>
    <span class="plan-turno-num" title="Personas en este slot — clic para ver o quitar">${num}</span>
    <span class="plan-turno-x" title="Quitar el slot entero del día">✕</span>
  </div>`;
}

// Panel derecho: personas ya puestas en el slot (con ✕ para quitarlas -> la
// plaza queda "sin asignar") + las sugerencias para añadir a alguien más.
async function pintarSlotGrupo(container, g) {
  const asg = grupoAsignados(g);
  const listaPersonas = asg.length
    ? `<div class="plan-slot-personas"><h4>Ya en este slot (${asg.length})</h4>${asg
        .map(
          (t) =>
            `<div class="plan-sug-fila"><span>${escapeHTML(nombreTrabajador(t.trabajador_id))}</span>` +
            `<span class="plan-sp-quitar" data-turno="${t.id}" title="Quitar de este slot">✕</span></div>`
        )
        .join("")}</div>`
    : "";
  await pintarSugeridos(container, { fecha: g.fecha || S.fecha, inicio_min: g.ini, duracion_min: g.dur, _grupo: g });
  container.insertAdjacentHTML("afterbegin", listaPersonas);
  container.querySelectorAll(".plan-sp-quitar").forEach((x) => {
    x.addEventListener("click", async () => {
      const r = await fetch(url(`turnos/${x.dataset.turno}/asignar`), {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ trabajador_id: SIN_ASIGNAR }),
      });
      if (!r.ok) return mostrarAviso("No se pudo quitar a la persona.");
      cargarDia();
    });
  });
}

// Poner a alguien en un slot: si hay una plaza libre (turno sin asignar del
// grupo) se ocupa; si no, se crea otra plaza -- así entran varias personas.
async function asignarAGrupo(g, trabajadorId) {
  const w = S.trabajadores.find((x) => x.id === trabajadorId);
  if (w) {
    const prev = S.minutosSemana[String(trabajadorId)] || 0;
    if (!(await confirmarComplementarias(w.horas_contrato_semana, prev, prev + g.dur))) return;
  }
  const libre = grupoLibres(g)[0];
  let res;
  if (libre) {
    res = await fetch(url(`turnos/${libre.id}/asignar`), {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ trabajador_id: trabajadorId }),
    });
  } else {
    res = await fetch(url("turnos"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        centro: S.centro,
        fecha: g.fecha || S.fecha,
        trabajador_id: trabajadorId,
        inicio_min: g.ini,
        duracion_min: g.dur,
      }),
    });
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    mostrarAviso(err.detail || "No se pudo asignar.");
    return;
  }
  cargarDia();
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
  const grupos = agruparSlots(turnosDia(S.fecha));
  const lanes = grupos
    .map(
      (g) => `<div class="plan-slot-lane" data-linea>
        <div class="plan-lane-lineas">${lineas}</div>
        ${slotGrupoHTML(g)}
      </div>`
    )
    .join("");

  cont.innerHTML = `
    <p class="plan-dia-total">Total del día: <b>${fmtHMM(totalMinDia(S.fecha))}</b></p>
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
      <div class="plan-sugeridos"><h4>Elige un slot</h4><p class="staff-hint">Haz clic en un slot colocado para ver a quién puedes poner (varias personas pueden hacer el mismo). Estíralo por los bordes para ajustarlo.</p></div>
    </div>`;

  wirePaleta(cont);
  wireDrop(cont.querySelector("#plan-slots-zona"), S.fecha);
  cont.querySelectorAll(".plan-turno.slot-grupo").forEach((el) => {
    const g = grupos.find((x) => x.key === el.dataset.key);
    wireTurno(el);
    wireDrop(el, S.fecha, null, g);
    el.querySelector(".plan-turno-num").addEventListener("pointerdown", (e) => e.stopPropagation());
    el.querySelector(".plan-turno-num").addEventListener("click", (e) => {
      e.stopPropagation();
      S.slotActivo = g.key;
      cont.querySelectorAll(".plan-turno.slot-grupo").forEach((x) => x.classList.toggle("slot-activo", x === el));
      pintarSlotGrupo(cont.querySelector(".plan-sugeridos"), g);
    });
    el.addEventListener("click", (e) => {
      if (e.target.closest(".plan-turno-x, .plan-turno-num")) return;
      S.slotActivo = g.key;
      cont.querySelectorAll(".plan-turno.slot-grupo").forEach((x) => x.classList.toggle("slot-activo", x === el));
      pintarSlotGrupo(cont.querySelector(".plan-sugeridos"), g);
    });
  });
}

function renderSlotsSemana() {
  const cont = document.getElementById("plan-contenido");
  const dias = S.dias.length ? S.dias : [S.fecha];
  const nombresDia = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"];
  const gruposPorDia = {};
  const cols = dias
    .map((d, i) => {
      const grupos = agruparSlots(S.turnos.filter((t) => t.fecha === d));
      gruposPorDia[d] = grupos;
      const items = grupos
        .map((g) => {
          const asg = grupoAsignados(g);
          const lib = grupoLibres(g);
          const actkey = `${d}|${g.key}`;
          return `<div class="plan-sem-slot ${asg.length ? "" : "sin-asignar"} ${
            S.slotActivo === actkey ? "activo" : ""
          }" data-actkey="${actkey}" data-key="${g.key}" data-fecha="${d}">
            <span class="plan-sem-slot-num">👥 ${asg.length}${lib.length ? ` +${lib.length}` : ""}</span>
            <small>${fmtHHMM(bloqueGeom(g.ini, g.dur).presIni)}–${fmtHHMM(bloqueGeom(g.ini, g.dur).presFin)} · ${fmtHoras(g.dur)}</small>
          </div>`;
        })
        .join("");
      return `<div class="plan-slots-col" data-fecha="${d}">
        <h5 data-fecha="${d}">${nombresDia[i]} ${fechaCorta(d)}</h5>
        ${items}
        <div class="plan-slots-total">Total <b>${fmtHMM(totalMinDia(d))}</b></div>
      </div>`;
    })
    .join("");

  cont.innerHTML = `
    ${paletaHTML()}
    <div class="plan-slots-layout">
      <div class="plan-slots-main"><div class="plan-slots-sem">${cols}</div></div>
      <div class="plan-sugeridos"><h4>Elige un slot</h4><p class="staff-hint">Haz clic en un slot para ver o cambiar quién lo hace.</p></div>
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
    const g = (gruposPorDia[el.dataset.fecha] || []).find((x) => x.key === el.dataset.key);
    if (!g) return;
    wireDrop(el, el.dataset.fecha, null, g);
    el.addEventListener("click", () => {
      S.slotActivo = el.dataset.actkey;
      cont.querySelectorAll(".plan-sem-slot").forEach((x) => x.classList.toggle("activo", x === el));
      pintarSlotGrupo(cont.querySelector(".plan-sugeridos"), g);
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
      body: JSON.stringify({ centro: S.centro, nombre: nombre.trim(), inicio_min: ini, duracion_min: fin - ini }),
    });
    if (!r.ok) return mostrarAviso("No se pudo crear el slot.");
    const d = await r.json();
    S.slots.push({ id: d.id, nombre: nombre.trim(), inicio_min: ini, duracion_min: fin - ini });
    pintarSlotsLista();
  });
}

let _vacTrab = null;
function abrirDialogoVacaciones(trabajadorId, nombre) {
  _vacTrab = trabajadorId;
  const dlg = document.getElementById("plan-dialog-vacaciones");
  dlg.querySelector(".plan-vac-nombre").textContent = nombre || nombreTrabajador(trabajadorId);
  const d = new Date(S.fecha + "T12:00:00");
  const lun = new Date(d);
  lun.setDate(d.getDate() - ((d.getDay() + 6) % 7));
  const dom = new Date(lun);
  dom.setDate(lun.getDate() + 6);
  const iso = (x) => `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, "0")}-${String(x.getDate()).padStart(2, "0")}`;
  dlg.querySelector("#plan-vac-desde").value = iso(lun);
  dlg.querySelector("#plan-vac-hasta").value = iso(dom);
  dlg.showModal();
}

function wireVacaciones() {
  const dlg = document.getElementById("plan-dialog-vacaciones");
  dlg.querySelector("[data-cerrar]").addEventListener("click", () => dlg.close());
  const post = async (quitar) => {
    const desde = dlg.querySelector("#plan-vac-desde").value;
    const hasta = dlg.querySelector("#plan-vac-hasta").value;
    if (!desde || !hasta || _vacTrab == null) return;
    const r = await fetch(url("vacaciones"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ centro: S.centro, trabajador_id: _vacTrab, desde, hasta, quitar }),
    });
    if (!r.ok) {
      const e = await r.json().catch(() => ({}));
      mostrarAviso(e.detail || "No se pudo guardar las vacaciones.");
      return;
    }
    dlg.close();
    cargarDia();
  };
  dlg.querySelector("#plan-vac-guardar").addEventListener("click", () => post(false));
  dlg.querySelector("#plan-vac-quitar").addEventListener("click", () => post(true));
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
                  `<span class="plan-sem-chip sin-asignar-chip" data-id="${x.id}" title="Asignar">${fmtHHMM(x.inicio_min)}–${fmtHHMM(x.inicio_min + presenciaMin(x.duracion_min))}</span>`
              )
              .join("")}</div>`;
          })
          .join("")}
      </div>`;

  const filas = S.trabajadores
    .map((t) => {
      const min = S.minutosSemana[String(t.id)] || 0;
      const contrato = t.horas_contrato_semana;
      const celdas = dias
        .map((d) => {
          const delDia = S.turnos.filter((x) => x.trabajador_id === t.id && x.fecha === d);
          const libre = delDia.some((x) => x.tipo === "libre");
          const vac = delDia.some((x) => x.tipo === "vacaciones");
          const trabajo = delDia.filter((x) => x.tipo === "trabajo").sort((a, b) => a.inicio_min - b.inicio_min);
          const chips = trabajo
            .map((x) => `<span class="plan-sem-chip">${fmtHHMM(x.inicio_min)}–${fmtHHMM(x.inicio_min + presenciaMin(x.duracion_min))}</span>`)
            .join("");
          const fuera = vac ? "vacaciones" : libre ? "libre" : "";
          return `<div class="plan-sem-celda ${fuera}" data-trab="${t.id}" data-fecha="${d}">
            <span class="plan-sem-luna ${libre ? "activo" : ""}" data-trab="${t.id}" data-fecha="${d}" title="Día libre">🛏</span>
            ${fuera ? `<span class="plan-sem-libre-txt">${vac ? "Vacaciones" : "Libre"}</span>` : chips}
          </div>`;
        })
        .join("");
      return `
        <div class="plan-sem-fila">
          <div class="plan-sem-nombre">
            <span class="plan-trab-nombre" title="${escapeHTML(t.nombre)}">${escapeHTML(t.nombre)}</span>
            <span class="plan-trab-horas">${textoHoras(min, contrato)}</span>
            ${barraHorasHTML(min, contrato)}
            <div class="plan-fila-acciones">${descansoIndicadorHTML(t.id, min, contrato)}</div>
          </div>
          ${celdas}
        </div>`;
    })
    .join("");

  const filaTotal = `<div class="plan-sem-fila plan-sem-total">
    <div class="plan-sem-nombre"><b>Total</b></div>
    ${dias
      .map((d) => `<div class="plan-sem-celda" style="align-items:center; justify-content:center;"><b>${fmtHMM(totalMinDia(d))}</b></div>`)
      .join("")}
  </div>`;

  cont.innerHTML = `
    <div class="plan-grid-scroll">
      <div class="plan-semana">
        ${cabecera}
        ${filaSin}
        ${S.trabajadores.length === 0 ? `<div class="plan-vacia">Este centro no tiene trabajadores en la plantilla.</div>` : filas}
        ${S.trabajadores.length === 0 ? "" : filaTotal}
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
    document.getElementById("plan-cfg-direccion").value = S.config.direccion_odoo ?? "";
    document.getElementById("plan-cfg-rol").value = S.config.rol_odoo ?? "";
    document.getElementById("plan-cfg-complementarias-jc").checked = !!S.config.complementarias_jornada_completa;
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
        direccion_odoo: document.getElementById("plan-cfg-direccion").value.trim(),
        rol_odoo: document.getElementById("plan-cfg-rol").value.trim(),
        complementarias_jornada_completa: document.getElementById("plan-cfg-complementarias-jc").checked,
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
  wireVacaciones();
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
  document.getElementById("plan-btn-export").addEventListener("click", () => {
    if (!S.centro) return mostrarAviso("Elige un centro primero.");
    const desde = lunesDe(S.fecha);
    const hasta = sumarDias(desde, 6);
    window.location.href = url("exportar-odoo", { centro: S.centro, desde, hasta });
  });
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

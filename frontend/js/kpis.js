// Dashboard de KPIs de personal -- todo se calcula en vivo en el backend
// (ver backend/kpis.py) a partir de dos fuentes: la última importación del
// informe de plantilla (Excel de GO) y las bajas registradas en Entrevista
// de Salida (en vivo, se actualiza sola). Aquí solo se pinta. Importar es
// solo admin, ver el resto de módulos de hoy (Entrevistas/Clima/Agregadores)
// para el mismo criterio.
//
// El filtro Desde/Hasta afecta a TODO: las 7 tarjetas de arriba (se
// recalculan sumando el rango filtrado, ver renderTarjetas) y los 4
// gráficos de abajo, incluida "Horas por centro": el backend reconstruye
// la plantilla de cualquier mes pasado con la fecha de antigüedad/baja de
// cada empleado (ver _activos_a_fecha en kpis.py), no es una foto fija.
// "Plantilla activa" y "Horas contratadas" siempre son "a fecha de Hasta"
// (una foto en ese punto); el resto de tarjetas son sumas/porcentajes
// acumulados de todo el rango Desde-Hasta.

const MARCA_COLOR = "#006838";
const COLORES = ["#006838", "#c98a12", "#1d6fb8", "#c23a72", "#7b4fb0", "#0e8a86", "#e0641e", "#3d5a80"];

function colorTextoActual() {
  return getComputedStyle(document.documentElement).getPropertyValue("--text-primary").trim() || "#000";
}

function wrapLabel(texto, maxLen = 18) {
  const palabras = (texto || "").split(/\s+/);
  const lineas = [];
  let actual = "";
  for (const palabra of palabras) {
    const candidata = actual ? `${actual} ${palabra}` : palabra;
    if (candidata.length > maxLen && actual) {
      lineas.push(actual);
      actual = palabra;
    } else {
      actual = candidata;
    }
  }
  if (actual) lineas.push(actual);
  return lineas;
}

function formatMes(clave) {
  if (!clave) return "";
  const [anio, mes] = clave.split("-");
  const nombres = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
  return `${nombres[parseInt(mes, 10) - 1]} ${anio.slice(2)}`;
}

function formatMesLargo(clave) {
  if (!clave) return "";
  const [anio, mes] = clave.split("-");
  const nombres = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"];
  return `${nombres[parseInt(mes, 10) - 1]} ${anio}`;
}

function motivoCorto(motivo) {
  // Los motivos son textos largos tipo SEPE ("02 Despido por causas
  // objetivas. Amortización por causas económicas, técnicas..."). Para el
  // gráfico basta con la primera frase -- si no hay punto, se recorta a un
  // máximo razonable para que no se solape con las barras vecinas.
  if (!motivo) return motivo;
  const corte = motivo.indexOf(".");
  let corto = corte > 0 ? motivo.slice(0, corte) : motivo;
  if (corto.length > 45) corto = `${corto.slice(0, 42)}…`;
  return corto;
}

let chartRotacionMensual, chartRotacionCentro, chartHorasCentro, chartBajasMotivo;
let usuarioActual = null;
let ultimoResumen = null;
let unidadRotacionMensual = "numero"; // "numero" | "pct"

function lineChart(canvasId, labels, valores, { sufijo = "" } = {}) {
  const ctx = document.getElementById(canvasId).getContext("2d");
  const colorTexto = colorTextoActual();
  return new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [{
        data: valores,
        borderColor: MARCA_COLOR,
        backgroundColor: MARCA_COLOR,
        tension: 0.3,
        pointRadius: 4,
        pointBackgroundColor: MARCA_COLOR,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: { ticks: { color: colorTexto }, grid: { display: false } },
        y: { beginAtZero: true, ticks: { color: colorTexto, precision: 0, callback: (v) => `${v}${sufijo}` }, grid: { color: "rgba(128,128,128,0.2)" } },
      },
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: (ctx2) => `${ctx2.parsed.y}${sufijo}` } },
      },
    },
  });
}

function barChart(canvasId, pares, { horizontal = true, sufijo = "" } = {}) {
  const el = document.getElementById(canvasId);
  const ctx = el.getContext("2d");
  const colorTexto = colorTextoActual();
  const movil = window.innerWidth < 700;
  const labels = pares.map(([nombre]) => wrapLabel(nombre, movil ? 16 : 20));
  const valores = pares.map(([, n]) => n);
  const eje = horizontal || movil ? "y" : "x";
  const escalaValor = { beginAtZero: true, ticks: { color: colorTexto, precision: 0, callback: (v) => `${v}${sufijo}` }, grid: { color: "rgba(128,128,128,0.2)" } };
  const escalaCategoria = { ticks: { color: colorTexto, autoSkip: false }, grid: { display: false } };
  return new Chart(ctx, {
    type: "bar",
    data: { labels, datasets: [{ data: valores, backgroundColor: MARCA_COLOR, borderRadius: 4 }] },
    options: {
      indexAxis: eje,
      responsive: true,
      maintainAspectRatio: false,
      scales: eje === "y" ? { x: escalaValor, y: escalaCategoria } : { y: escalaValor, x: escalaCategoria },
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: (ctx2) => `${ctx2.parsed[eje === "y" ? "x" : "y"]}${sufijo}` } } },
    },
  });
}

function destruirCharts() {
  [chartRotacionMensual, chartRotacionCentro, chartHorasCentro, chartBajasMotivo].forEach((c) => c?.destroy());
}

async function cargarResumen() {
  const r = await fetch(`${AUTH_API_BASE}/kpis/resumen`);
  if (!r.ok) return;
  const d = await r.json();

  document.getElementById("kpi-sin-datos").hidden = !d.sin_datos_plantilla;
  document.getElementById("kpi-contenido").querySelectorAll(".kpi-stats-grid, .kpi-charts-grid, .kpi-chart-card").forEach((el) => {
    el.style.display = d.sin_datos_plantilla ? "none" : "";
  });
  if (d.sin_datos_plantilla) return;

  destruirCharts();

  ultimoResumen = d;
  configurarFiltroFechas(d);
  renderGraficosFiltrados();
}

// --- Selector de mes "tipo calendario" (año + rejilla de 12 meses) -------
// Con un <select> plano la lista crece para siempre (dentro de un par de
// años sería eterna) -- esto en cambio siempre son 12 botones + un año que
// se navega con flechas, sin importar cuántos años de datos haya.
const MESES_CORTOS = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"];

function crearMesPicker(idPrefix, onSeleccion) {
  const btn = document.getElementById(`${idPrefix}-btn`);
  const panel = document.getElementById(`${idPrefix}-panel`);
  const anioEl = panel.querySelector(".kpi-mespicker-anio-actual");
  const grid = panel.querySelector(".kpi-mespicker-grid");
  const navPrev = panel.querySelector('[data-dir="-1"]');
  const navNext = panel.querySelector('[data-dir="1"]');

  let mesesDisponibles = [];
  let valorActual = null;
  let anioMostrado = null;

  function anioMinMax() {
    const anios = mesesDisponibles.map((m) => parseInt(m.slice(0, 4), 10));
    return [Math.min(...anios), Math.max(...anios)];
  }

  function render() {
    anioEl.textContent = anioMostrado;
    const [anioMin, anioMax] = anioMinMax();
    navPrev.disabled = anioMostrado <= anioMin;
    navNext.disabled = anioMostrado >= anioMax;
    grid.innerHTML = "";
    for (let m = 1; m <= 12; m++) {
      const clave = `${anioMostrado}-${String(m).padStart(2, "0")}`;
      const b = document.createElement("button");
      b.type = "button";
      b.className = "kpi-mespicker-mes" + (clave === valorActual ? " active" : "");
      b.textContent = MESES_CORTOS[m - 1];
      b.disabled = !mesesDisponibles.includes(clave);
      b.addEventListener("click", () => {
        valorActual = clave;
        btn.textContent = formatMesLargo(clave);
        panel.hidden = true;
        onSeleccion(clave);
      });
      grid.appendChild(b);
    }
  }

  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    const abrir = panel.hidden;
    document.querySelectorAll(".kpi-mespicker-panel").forEach((p) => { p.hidden = true; });
    if (abrir) {
      anioMostrado = valorActual ? parseInt(valorActual.slice(0, 4), 10) : anioMostrado;
      render();
      panel.hidden = false;
    }
  });
  panel.addEventListener("click", (e) => e.stopPropagation());
  navPrev.addEventListener("click", () => { anioMostrado--; render(); });
  navNext.addEventListener("click", () => { anioMostrado++; render(); });

  return {
    set(meses, valorInicial) {
      mesesDisponibles = meses;
      valorActual = valorInicial;
      anioMostrado = parseInt(valorInicial.slice(0, 4), 10);
      btn.textContent = formatMesLargo(valorInicial);
    },
    get value() { return valorActual; },
    set value(v) {
      valorActual = v;
      anioMostrado = parseInt(v.slice(0, 4), 10);
      btn.textContent = formatMesLargo(v);
    },
  };
}

document.addEventListener("click", () => {
  document.querySelectorAll(".kpi-mespicker-panel").forEach((p) => { p.hidden = true; });
});

let mesPickerDesde, mesPickerHasta;

function configurarFiltroFechas(d) {
  const meses = d.meses_disponibles;
  if (!meses.length) return;

  const inicioDefault = meses[Math.max(0, meses.length - 12)];
  const finDefault = meses[meses.length - 1];
  const valorDesde = mesPickerDesde.value && meses.includes(mesPickerDesde.value) ? mesPickerDesde.value : inicioDefault;
  const valorHasta = mesPickerHasta.value && meses.includes(mesPickerHasta.value) ? mesPickerHasta.value : finDefault;
  mesPickerDesde.set(meses, valorDesde);
  mesPickerHasta.set(meses, valorHasta);
}

function pct1(n, base) {
  return base ? Math.round((n / base) * 1000) / 10 : 0;
}

function renderTarjetas(d, mesesFiltrados, hasta, etiquetaRango) {
  const serieHasta = d.serie_mensual[hasta] || d.serie_mensual[d.mes_actual];
  const headcountHasta = serieHasta.headcount_activo;

  let bajas = 0, nspp = 0, sinEmpresario = 0, promociones = 0;
  for (const m of mesesFiltrados) {
    const s = d.serie_mensual[m];
    bajas += s.bajas;
    nspp += s.nspp;
    sinEmpresario += s.sin_nspp_empresario;
    promociones += s.promociones;
  }

  document.getElementById("kpi-headcount").textContent = headcountHasta;

  const rotacionPeriodo = pct1(bajas, headcountHasta);
  document.getElementById("kpi-rotacion-anual").textContent = `${rotacionPeriodo}%`;
  const nMeses = mesesFiltrados.length;
  const anualizado = nMeses && nMeses !== 12 ? Math.round(rotacionPeriodo * (12 / nMeses) * 10) / 10 : null;
  document.getElementById("kpi-rotacion-anual-sub").textContent =
    `${bajas} bajas -- ${etiquetaRango}` + (anualizado !== null ? ` (≈${anualizado}% anualizado a 12 meses)` : "");

  const ultimoMes = mesesFiltrados[mesesFiltrados.length - 1];
  const sMes = ultimoMes ? d.serie_mensual[ultimoMes] : { bajas: 0, pct: 0 };
  document.getElementById("kpi-rotacion-mes").textContent = sMes.bajas;
  document.getElementById("kpi-rotacion-mes-sub").textContent = ultimoMes
    ? `${formatMes(ultimoMes)} -- ${sMes.pct}% sobre la plantilla activa`
    : "sin datos en ese rango";

  document.getElementById("kpi-nspp").textContent = bajas ? `${pct1(nspp, bajas)}%` : "--";

  document.getElementById("kpi-horas").textContent = `${serieHasta.horas_totales} h/sem`;

  document.getElementById("kpi-rotacion-sin-nspp").textContent = `${pct1(sinEmpresario, headcountHasta)}%`;
  document.getElementById("kpi-rotacion-sin-nspp-sub").textContent =
    `${sinEmpresario} de ${bajas} bajas -- sin los ceses en prueba a instancia del empresario`;

  document.getElementById("kpi-promocion").textContent = `${pct1(promociones, headcountHasta)}%`;
  document.getElementById("kpi-promocion-sub").textContent = promociones
    ? `${promociones} promociones -- ${etiquetaRango}`
    : "sin movimientos de puesto registrados en este periodo";
}

function renderGraficosFiltrados() {
  if (!ultimoResumen) return;
  const d = ultimoResumen;
  const desde = mesPickerDesde.value || d.meses_disponibles[0];
  const hasta = mesPickerHasta.value || d.meses_disponibles[d.meses_disponibles.length - 1];
  const mesesFiltrados = d.meses_disponibles.filter((m) => m >= desde && m <= hasta);
  const etiquetaRango = mesesFiltrados.length
    ? (mesesFiltrados.length === 1 ? formatMes(mesesFiltrados[0]) : `${formatMes(mesesFiltrados[0])} -- ${formatMes(mesesFiltrados[mesesFiltrados.length - 1])}`)
    : "sin datos en ese rango";

  renderTarjetas(d, mesesFiltrados, hasta, etiquetaRango);

  // --- Rotación mensual global (número o %, según el toggle) -------------
  chartRotacionMensual?.destroy();
  const esPct = unidadRotacionMensual === "pct";
  chartRotacionMensual = lineChart(
    "chart-rotacion-mensual",
    mesesFiltrados.map(formatMes),
    mesesFiltrados.map((m) => (esPct ? d.serie_mensual[m].pct : d.serie_mensual[m].bajas)),
    { sufijo: esPct ? "%" : "" }
  );
  document.getElementById("kpi-rotacion-mensual-sub").textContent =
    `${etiquetaRango} -- ${esPct ? "% sobre la plantilla activa" : "número de bajas por mes"}.`;

  // --- Rotación por centro (suma del rango / plantilla activa al final del rango) --
  const serieHasta = d.serie_mensual[hasta] || d.serie_mensual[d.mes_actual];
  const centroHc = Object.fromEntries(serieHasta.headcount_por_centro);
  const centroBajas = {};
  for (const m of mesesFiltrados) {
    for (const [centro, n] of d.serie_mensual[m].por_centro) {
      centroBajas[centro] = (centroBajas[centro] || 0) + n;
    }
  }
  const centros = new Set([...Object.keys(centroHc), ...Object.keys(centroBajas)]);
  const rotacionPorCentro = Array.from(centros)
    .map((c) => {
      const hc = centroHc[c] || 0;
      const n = centroBajas[c] || 0;
      return [c, hc ? Math.round((n / hc) * 1000) / 10 : 0];
    })
    .filter(([c]) => centroBajas[c] || centroHc[c])
    .sort((a, b) => b[1] - a[1]);
  chartRotacionCentro?.destroy();
  if (rotacionPorCentro.length) {
    chartRotacionCentro = barChart("chart-rotacion-centro", rotacionPorCentro, { sufijo: "%" });
  }
  document.getElementById("kpi-rotacion-centro-sub").textContent = `${etiquetaRango}.`;

  // --- Bajas por motivo (suma del rango) ----------------------------------
  const motivos = {};
  for (const m of mesesFiltrados) {
    for (const [motivo, n] of d.serie_mensual[m].por_motivo) {
      motivos[motivo] = (motivos[motivo] || 0) + n;
    }
  }
  const paresMotivo = Object.entries(motivos).sort((a, b) => b[1] - a[1]);
  document.getElementById("kpi-bajas-motivo-sub").textContent = `${etiquetaRango}, según Entrevista de Salida.`;
  const sinBajas = paresMotivo.length === 0;
  document.getElementById("kpi-bajas-motivo-aviso").hidden = !sinBajas;
  document.getElementById("chart-bajas-motivo").style.display = sinBajas ? "none" : "";
  chartBajasMotivo?.destroy();
  if (!sinBajas) {
    chartBajasMotivo = barChart("chart-bajas-motivo", paresMotivo.map(([m, n]) => [motivoCorto(m), n]));
  }

  // --- Horas contratadas por centro (reconstruida a fecha de "Hasta") ----
  chartHorasCentro?.destroy();
  if (serieHasta.horas_por_centro.length) {
    chartHorasCentro = barChart("chart-horas-centro", serieHasta.horas_por_centro, { sufijo: "h" });
  }
  document.getElementById("kpi-horas-centro-sub").textContent =
    hasta === d.mes_actual ? "A fecha de hoy." : `A fecha de fin de ${formatMes(hasta)}.`;
  document.getElementById("kpi-horas-centro-total").textContent = `Total: ${serieHasta.horas_totales} h/sem`;
}

// --- Movimientos internos (traslados de centro / promociones de puesto) ---
let tipoMovimientoActivo = "centro";

function poblarSelectMovimiento(tipo) {
  const d = ultimoResumen;
  if (!d) return;
  const opciones = tipo === "centro" ? (d.centros_disponibles || []) : (d.puestos_jerarquia || []);
  const optionsHtml = opciones.map((o) => `<option value="${o}">${o}</option>`).join("");
  document.getElementById("kpi-mov-origen").innerHTML = `<option value="">(sin dato)</option>${optionsHtml}`;
  document.getElementById("kpi-mov-destino").innerHTML = optionsHtml;
}

async function cargarMovimientos() {
  const r = await fetch(`${AUTH_API_BASE}/kpis/movimientos?tipo=${tipoMovimientoActivo}`);
  if (!r.ok) return;
  const movs = await r.json();
  const tbody = document.getElementById("kpi-mov-tbody");
  document.getElementById("kpi-mov-vacio").hidden = movs.length > 0;
  const esAdmin = usuarioActual?.rol === "admin";
  tbody.innerHTML = movs.map((m) => `
    <tr data-id="${m.id}">
      <td>${m.codigo_empleado}</td>
      <td>${m.origen || "--"}</td>
      <td>${m.destino}</td>
      <td>${m.fecha}</td>
      <td>${m.registrado_por || "--"}</td>
      <td>${esAdmin ? `<button type="button" class="btn btn-ghost btn-mini kpi-mov-borrar" data-id="${m.id}">✕</button>` : ""}</td>
    </tr>
  `).join("");
}

function cambiarTabMovimiento(tipo) {
  tipoMovimientoActivo = tipo;
  document.getElementById("kpi-mov-tab-centro").classList.toggle("active", tipo === "centro");
  document.getElementById("kpi-mov-tab-puesto").classList.toggle("active", tipo === "puesto");
  document.getElementById("kpi-mov-resultado").textContent = "";
  poblarSelectMovimiento(tipo);
  cargarMovimientos();
}

async function buscarEmpleadoMovimiento() {
  const codigo = document.getElementById("kpi-mov-codigo").value.trim();
  const resultado = document.getElementById("kpi-mov-resultado");
  if (!codigo) {
    resultado.textContent = "";
    return;
  }
  resultado.textContent = "Buscando...";
  const r = await fetch(`${AUTH_API_BASE}/kpis/empleados/${encodeURIComponent(codigo)}`);
  if (!r.ok) {
    resultado.textContent = "⚠️ No se encontró ningún empleado con ese código.";
    return;
  }
  const emp = await r.json();
  const campo = tipoMovimientoActivo === "centro" ? "centro" : "puesto";
  const actual = emp[campo];
  resultado.textContent =
    `✔ ${emp.nombre} -- ${campo} actual: ${actual || "(sin dato)"}${emp.fecha_baja ? " -- ya tiene baja registrada" : ""}`;
  const selectOrigen = document.getElementById("kpi-mov-origen");
  if (actual && Array.from(selectOrigen.options).some((o) => o.value === actual)) {
    selectOrigen.value = actual;
  }
}

function wireMovimientos() {
  document.getElementById("kpi-mov-tab-centro").addEventListener("click", () => cambiarTabMovimiento("centro"));
  document.getElementById("kpi-mov-tab-puesto").addEventListener("click", () => cambiarTabMovimiento("puesto"));

  document.getElementById("kpi-mov-buscar").addEventListener("click", buscarEmpleadoMovimiento);
  document.getElementById("kpi-mov-codigo").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      buscarEmpleadoMovimiento();
    }
  });

  document.getElementById("kpi-mov-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const codigo = document.getElementById("kpi-mov-codigo").value.trim();
    const origen = document.getElementById("kpi-mov-origen").value;
    const destino = document.getElementById("kpi-mov-destino").value;
    const fecha = document.getElementById("kpi-mov-fecha").value;
    if (!codigo || !destino || !fecha) return;
    const res = await fetch(`${AUTH_API_BASE}/kpis/movimientos`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ codigo_empleado: codigo, tipo: tipoMovimientoActivo, origen: origen || null, destino, fecha }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      mostrarAviso(err.detail || "No se pudo registrar el movimiento.");
      return;
    }
    document.getElementById("kpi-mov-form").reset();
    document.getElementById("kpi-mov-resultado").textContent = "";
    await cargarMovimientos();
    await cargarResumen();
  });

  document.getElementById("kpi-mov-tbody").addEventListener("click", async (e) => {
    const btn = e.target.closest(".kpi-mov-borrar");
    if (!btn) return;
    const ok = await pedirConfirmacion("¿Eliminar este movimiento?");
    if (!ok) return;
    const res = await fetch(`${AUTH_API_BASE}/kpis/movimientos/${btn.dataset.id}`, { method: "DELETE" });
    if (!res.ok) {
      mostrarAviso("No se pudo eliminar el movimiento.");
      return;
    }
    await cargarMovimientos();
    await cargarResumen();
  });
}

async function cargarUltimaImportacion() {
  const r = await fetch(`${AUTH_API_BASE}/kpis/ultima-importacion`);
  if (!r.ok) return;
  const info = await r.json();
  const el = document.getElementById("kpi-ultima-importacion");
  el.textContent = info ? `Última importación de plantilla: ${info.filas} empleados, ${info.importado_en}` : "";
}

async function importarExcel(file) {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch(`${AUTH_API_BASE}/kpis/importar`, { method: "POST", body: formData });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    mostrarAviso(err.detail || "No se pudo importar el archivo.");
    return;
  }
  await cargarUltimaImportacion();
  await cargarResumen();
}

document.addEventListener("DOMContentLoaded", async () => {
  const user = await checkAuth("/kpis.html");
  if (!user) return;
  if (!(user.modulos || []).includes("kpis")) {
    window.location.href = "/";
    return;
  }
  usuarioActual = user;
  wireUserBar(user);

  if (user.rol === "admin") {
    document.getElementById("kpi-import-wrap").hidden = false;
  }
  document.getElementById("kpi-input-importar").addEventListener("change", (e) => {
    const file = e.target.files[0];
    if (!file) return;
    importarExcel(file);
    e.target.value = "";
  });

  mesPickerDesde = crearMesPicker("kpi-filtro-desde", renderGraficosFiltrados);
  mesPickerHasta = crearMesPicker("kpi-filtro-hasta", renderGraficosFiltrados);
  document.getElementById("kpi-filtro-reset").addEventListener("click", () => {
    if (!ultimoResumen) return;
    const meses = ultimoResumen.meses_disponibles;
    mesPickerDesde.value = meses[Math.max(0, meses.length - 12)];
    mesPickerHasta.value = meses[meses.length - 1];
    renderGraficosFiltrados();
  });
  document.getElementById("kpi-filtro-anio-actual").addEventListener("click", () => {
    if (!ultimoResumen) return;
    const meses = ultimoResumen.meses_disponibles;
    const anio = ultimoResumen.mes_actual.slice(0, 4);
    const inicioAnio = `${anio}-01`;
    mesPickerDesde.value = meses.includes(inicioAnio) ? inicioAnio : meses[0];
    mesPickerHasta.value = ultimoResumen.mes_actual;
    renderGraficosFiltrados();
  });

  document.querySelectorAll("[data-unidad]").forEach((btn) => {
    btn.addEventListener("click", () => {
      unidadRotacionMensual = btn.dataset.unidad;
      document.querySelectorAll("[data-unidad]").forEach((b) => b.classList.toggle("active", b === btn));
      renderGraficosFiltrados();
    });
  });

  wireMovimientos();

  await cargarUltimaImportacion();
  await cargarResumen();
  poblarSelectMovimiento(tipoMovimientoActivo);
  await cargarMovimientos();
});

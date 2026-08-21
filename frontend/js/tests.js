let currentTestId = null;
let currentTest = null;

// Iconos SVG en vez de emoji (⠿ ✎ ↑ ↓) — algunos sistemas los renderizan
// como cuadros sin forma; el SVG con currentColor se ve igual en todos.
const ICONO_FLECHA_ARRIBA = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5M5 12l7-7 7 7"/></svg>`;
const ICONO_FLECHA_ABAJO = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M19 12l-7 7-7-7"/></svg>`;
const ICONO_LAPIZ = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>`;
const ICONO_ARRASTRAR = `<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><circle cx="9" cy="5" r="1.5"/><circle cx="15" cy="5" r="1.5"/><circle cx="9" cy="12" r="1.5"/><circle cx="15" cy="12" r="1.5"/><circle cx="9" cy="19" r="1.5"/><circle cx="15" cy="19" r="1.5"/></svg>`;

function escapeHTML(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

async function loadTiposInforme() {
  const [resInformes, resClima] = await Promise.all([
    fetch(`${AUTH_API_BASE}/encuestas/tipos-informe-disponibles`),
    fetch(`${AUTH_API_BASE}/encuestas/clima-oleadas-disponibles`),
  ]);
  const tipos = await resInformes.json();
  const oleadas = await resClima.json();
  const select = document.getElementById("test-tipo-informe");
  select.innerHTML =
    `<option value="">— No calcular puntuación —</option>` +
    `<optgroup label="Informes">` +
    tipos.map((t) => `<option value="informe:${escapeHTML(t.clave)}">${escapeHTML(t.nombre)}</option>`).join("") +
    `</optgroup>` +
    `<optgroup label="Entrevista de Salida">` +
    `<option value="entrevista:kk">Entrevista de Salida — Krispy Kreme</option>` +
    `<option value="entrevista:saona">Entrevista de Salida — SAONA</option>` +
    `</optgroup>` +
    `<optgroup label="Clima Laboral">` +
    oleadas
      .map((o) => `<option value="clima:${o.id}">${escapeHTML(o.etiqueta || `Oleada #${o.numero} sin nombre`)}</option>`)
      .join("") +
    `<option value="clima:nueva:kk">+ Nueva oleada de Clima Laboral — Krispy Kreme</option>` +
    `<option value="clima:nueva:saona">+ Nueva oleada de Clima Laboral — SAONA</option>` +
    `</optgroup>`;
}

// Clima Laboral es el único destino donde el test necesita configuración
// propia además de elegirlo en el desplegable (la plantilla de empleados
// esperados por centro, ver clima-plantilla-wrap en tests.html) -- se
// guarda aparte (no en el body de guardarTest) porque vive en su propia
// tabla (clima_plantilla), no en la fila de la encuesta.
let climaPlantillaOleadaId = null;

function filaClimaPlantillaHTML(centro = "", empleados = "") {
  return `
    <div class="clima-plantilla-fila">
      <input type="text" class="clima-plantilla-centro" placeholder="Centro de trabajo" value="${escapeHTML(centro)}">
      <input type="number" class="clima-plantilla-empleados" placeholder="Empleados esperados" min="1" value="${empleados || ""}">
      <button type="button" class="btn btn-ghost btn-clima-plantilla-quitar">✕</button>
    </div>`;
}

function wireClimaPlantillaFilas() {
  document.querySelectorAll(".btn-clima-plantilla-quitar").forEach((btn) => {
    btn.addEventListener("click", () => btn.closest(".clima-plantilla-fila").remove());
  });
}

function renderClimaPlantillaFilas(plantilla) {
  const cont = document.getElementById("clima-plantilla-filas");
  const entradas = Object.entries(plantilla || {});
  cont.innerHTML = (entradas.length ? entradas : [["", ""]]).map(([c, e]) => filaClimaPlantillaHTML(c, e)).join("");
  wireClimaPlantillaFilas();
}

function actualizarVisibilidadMensajeNoApto() {
  document.getElementById("test-mensaje-no-apto-wrap").hidden =
    !document.getElementById("test-usar-mensaje-no-apto").checked;
}

// Se llama cada vez que cambia el desplegable de destino (y al abrir un
// test ya guardado) -- muestra/oculta el bloque de plantilla y, si el
// destino es una oleada existente, precarga lo que ya se había guardado
// para esa oleada (puede venir de un Excel importado antes, no solo de
// este mismo test).
async function actualizarVistaClimaPlantilla() {
  const val = document.getElementById("test-tipo-informe").value;
  const wrap = document.getElementById("clima-plantilla-wrap");
  if (!val.startsWith("clima:") || val.startsWith("clima:nueva:")) {
    wrap.hidden = true;
    climaPlantillaOleadaId = null;
    document.getElementById("clima-plantilla-filas").innerHTML = "";
    return;
  }
  climaPlantillaOleadaId = Number(val.slice("clima:".length));
  wrap.hidden = false;
  const res = await fetch(`${AUTH_API_BASE}/clima/${climaPlantillaOleadaId}/plantilla`);
  renderClimaPlantillaFilas(res.ok ? await res.json() : {});
}

// El numero de respuestas en el listado enlaza al informe donde se acumulan
// (Informes para tests de Valores/Competencias, Entrevistas de Salida para
// los de ese tipo) — asi no hay que abrir el test y buscar "Ver respuestas"
// para llegar al mismo sitio. Sin tipo configurado (o sin respuestas aun) el
// numero se queda como texto plano.
function enlaceRespuestasTest(t) {
  if (!t.num_respuestas) return `${t.num_respuestas}`;
  if (t.tipo_informe_clave) {
    const empresa = t.tipo_informe_clave.startsWith("saona_") ? "saona" : "kk";
    const params = new URLSearchParams({ tipo: t.tipo_informe_clave, empresa });
    return `<a href="/informes.html?${params.toString()}" target="_blank">${t.num_respuestas}</a>`;
  }
  if (t.tipo_entrevista_empresa) {
    const params = new URLSearchParams({ empresa: t.tipo_entrevista_empresa });
    return `<a href="/entrevistas.html?${params.toString()}" target="_blank">${t.num_respuestas}</a>`;
  }
  if (t.clima_oleada_id) {
    return `<a href="/clima.html?oleada=${t.clima_oleada_id}" target="_blank">${t.num_respuestas}</a>`;
  }
  return `${t.num_respuestas}`;
}

async function loadTests() {
  const res = await fetch(`${AUTH_API_BASE}/encuestas/encuestas`);
  const tests = await res.json();
  const tbody = document.getElementById("tests-tbody");
  if (tests.length === 0) {
    tbody.innerHTML = `<tr><td colspan="4" class="staff-hint">Todavía no has creado ningún test.</td></tr>`;
    return;
  }
  tbody.innerHTML = tests
    .map(
      (t) => `
    <tr>
      <td>${escapeHTML(t.titulo)}</td>
      <td>
        <span class="badge ${t.estado === "abierta" ? "badge-abierta" : "badge-cerrada"}">${t.estado === "abierta" ? "Abierta" : "Cerrada"}</span>
        <span class="en-vivo-badge" data-id="${t.id}" hidden>🟢 <span class="en-vivo-n"></span> en vivo</span>
      </td>
      <td>${enlaceRespuestasTest(t)}</td>
      <td><button class="btn btn-ghost btn-editar-test" data-id="${t.id}" type="button">Editar</button></td>
    </tr>`
    )
    .join("");
  tbody.querySelectorAll(".btn-editar-test").forEach((btn) => {
    btn.addEventListener("click", () => abrirEditor(Number(btn.dataset.id)));
  });
  actualizarEnVivo();
}

// Cuántas personas están respondiendo cada test AHORA MISMO — se refresca
// solo (sin recargar la lista entera, que cortaría una edición en curso).
async function actualizarEnVivo() {
  const conteo = await fetch(`${AUTH_API_BASE}/encuestas/encuestas/en-vivo`).then((r) => (r.ok ? r.json() : {}));
  document.querySelectorAll(".en-vivo-badge").forEach((badge) => {
    const n = conteo[badge.dataset.id] || 0;
    badge.hidden = n === 0;
    badge.querySelector(".en-vivo-n").textContent = n;
  });
}
setInterval(() => {
  if (document.getElementById("tests-tbody")) actualizarEnVivo();
}, 20000);

// scroll=false se usa para refrescos "en el sitio" tras guardar algo dentro
// de un test que ya está abierto (guardar campos, mover/borrar una página o
// pregunta, etc.) — así el admin puede seguir editando sin que la pantalla
// salte arriba en cada acción, como si recargara toda la página. scroll=true
// (por defecto) se mantiene para abrir el editor por primera vez (desde la
// lista o "Nuevo test"), donde sí conviene llevar la vista hacia la tarjeta.
async function abrirEditor(testId, { scroll = true } = {}) {
  if (testId !== currentTestId) editandoPreguntas.clear();
  currentTestId = testId;
  const editorCard = document.getElementById("editor-card");
  editorCard.hidden = false;
  document.getElementById("respuestas-wrap").hidden = true;

  if (testId) {
    const res = await fetch(`${AUTH_API_BASE}/encuestas/encuestas/${testId}`);
    currentTest = await res.json();
    document.getElementById("editor-titulo-h2").textContent = "Editar test";
    document.getElementById("test-titulo").value = currentTest.titulo;
    document.getElementById("test-mensaje-final").value = currentTest.mensaje_final;
    document.getElementById("test-mensaje-no-apto").value = currentTest.mensaje_no_apto;
    document.getElementById("test-usar-mensaje-no-apto").checked = currentTest.usar_mensaje_no_apto !== false;
    actualizarVisibilidadMensajeNoApto();
    document.getElementById("test-color-boton").value = currentTest.color_boton;
    if (currentTest.tipo_entrevista_empresa) {
      document.getElementById("test-tipo-informe").value = `entrevista:${currentTest.tipo_entrevista_empresa}`;
    } else if (currentTest.tipo_informe_clave) {
      document.getElementById("test-tipo-informe").value = `informe:${currentTest.tipo_informe_clave}`;
    } else if (currentTest.clima_oleada_id) {
      document.getElementById("test-tipo-informe").value = `clima:${currentTest.clima_oleada_id}`;
    } else {
      document.getElementById("test-tipo-informe").value = "";
    }
    await actualizarVistaClimaPlantilla();
    // Código corto y correlativo (el propio id, con 4 cifras) en vez del
    // slug de texto — el backend acepta ambos, así que un enlace ya
    // compartido con el slug largo sigue funcionando igual.
    const codigoCorto = String(currentTest.id).padStart(4, "0");
    document.getElementById("test-enlace-publico").value = `${location.origin}/encuesta.html?slug=${codigoCorto}`;
    document.getElementById("test-enlace-corto").value = currentTest.enlace_corto || "";
    document.getElementById("test-evitar-duplicados").checked = !!currentTest.evitar_duplicados;
    document.getElementById("fondo-preview").hidden = !currentTest.tiene_fondo;
    if (currentTest.tiene_fondo) {
      document.getElementById("fondo-preview").src = `${AUTH_API_BASE}/encuestas/encuestas/${testId}/fondo?t=${Date.now()}`;
    }
    document.getElementById("btn-publicar-test").hidden = currentTest.estado === "abierta";
    document.getElementById("btn-despublicar-test").hidden = currentTest.estado !== "abierta";
    document.getElementById("btn-ver-respuestas").hidden = false;
    document.getElementById("btn-ver-embudo").hidden = false;
    document.getElementById("btn-eliminar-test").hidden = false;
    document.getElementById("btn-nueva-pagina").hidden = false;
    renderPaginas();
  } else {
    currentTest = null;
    document.getElementById("editor-titulo-h2").textContent = "Nuevo test";
    document.getElementById("test-titulo").value = "";
    document.getElementById("test-mensaje-final").value = "Gracias por completar el formulario.";
    document.getElementById("test-mensaje-no-apto").value = "Gracias por contestar nuestro test. En esta ocasión no has superado el proceso, pero te deseamos mucha suerte.";
    document.getElementById("test-usar-mensaje-no-apto").checked = true;
    actualizarVisibilidadMensajeNoApto();
    document.getElementById("test-color-boton").value = "#5b2a2a";
    document.getElementById("test-tipo-informe").value = "";
    await actualizarVistaClimaPlantilla();
    document.getElementById("test-enlace-publico").value = "";
    document.getElementById("test-enlace-corto").value = "";
    document.getElementById("test-evitar-duplicados").checked = false;
    document.getElementById("fondo-preview").hidden = true;
    document.getElementById("btn-publicar-test").hidden = true;
    document.getElementById("btn-despublicar-test").hidden = true;
    document.getElementById("btn-ver-respuestas").hidden = true;
    document.getElementById("btn-ver-embudo").hidden = true;
    document.getElementById("btn-eliminar-test").hidden = true;
    document.getElementById("btn-nueva-pagina").hidden = true;
    document.getElementById("paginas-wrap").innerHTML = "";
  }
  if (scroll) editorCard.scrollIntoView({ behavior: "smooth", block: "start" });
}

function cerrarEditor() {
  currentTestId = null;
  currentTest = null;
  document.getElementById("editor-card").hidden = true;
}

async function guardarTest() {
  const titulo = document.getElementById("test-titulo").value.trim();
  if (!titulo) {
    mostrarAviso("El título es obligatorio.");
    return;
  }
  if (!currentTestId) {
    const res = await fetch(`${AUTH_API_BASE}/encuestas/encuestas`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ titulo }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      mostrarAviso(err.detail || "No se pudo crear el test.");
      return;
    }
    const data = await res.json();
    currentTestId = data.id;
  }
  const destino = document.getElementById("test-tipo-informe").value;
  const body = {
    titulo,
    mensaje_final: document.getElementById("test-mensaje-final").value.trim(),
    mensaje_no_apto: document.getElementById("test-mensaje-no-apto").value.trim(),
    color_boton: document.getElementById("test-color-boton").value,
    tipo_informe_clave: destino.startsWith("informe:") ? destino.slice("informe:".length) : null,
    tipo_entrevista_empresa: destino.startsWith("entrevista:") ? destino.slice("entrevista:".length) : null,
    clima_oleada_id: destino.startsWith("clima:") ? Number(destino.slice("clima:".length)) : null,
    enlace_corto: document.getElementById("test-enlace-corto").value.trim() || null,
    evitar_duplicados: document.getElementById("test-evitar-duplicados").checked,
    usar_mensaje_no_apto: document.getElementById("test-usar-mensaje-no-apto").checked,
  };
  const res = await fetch(`${AUTH_API_BASE}/encuestas/encuestas/${currentTestId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    mostrarAviso(err.detail || "No se pudo guardar el test.");
    return;
  }
  if (climaPlantillaOleadaId) {
    const plantilla = {};
    document.querySelectorAll(".clima-plantilla-fila").forEach((fila) => {
      const centro = fila.querySelector(".clima-plantilla-centro").value.trim();
      const empleados = Number(fila.querySelector(".clima-plantilla-empleados").value);
      if (centro && empleados > 0) plantilla[centro] = empleados;
    });
    await fetch(`${AUTH_API_BASE}/clima/${climaPlantillaOleadaId}/plantilla`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plantilla }),
    });
  }
  await loadTests();
  await abrirEditor(currentTestId, { scroll: false });
}

async function publicarTest(publicar) {
  await fetch(`${AUTH_API_BASE}/encuestas/encuestas/${currentTestId}/${publicar ? "publicar" : "despublicar"}`, { method: "POST" });
  await loadTests();
  await abrirEditor(currentTestId, { scroll: false });
}

async function eliminarTest() {
  if (!(await pedirConfirmacion("¿Eliminar este test y todas sus respuestas? Esta acción no se puede deshacer."))) return;
  await fetch(`${AUTH_API_BASE}/encuestas/encuestas/${currentTestId}`, { method: "DELETE" });
  cerrarEditor();
  await loadTests();
}

async function subirFondo(file) {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch(`${AUTH_API_BASE}/encuestas/encuestas/${currentTestId}/fondo`, { method: "POST", body: formData });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    mostrarAviso(err.detail || "No se pudo subir la imagen.");
    return;
  }
  await abrirEditor(currentTestId, { scroll: false });
}

const TIPOS_PREGUNTA_LABELS = {
  texto: "Texto",
  email: "Email",
  numero: "Número",
  fecha: "Fecha",
  calificacion: "Calificación (estrellas)",
  likert: "Escala (1-5)",
  abierta: "Comentario abierto",
  opcion_simple: "Opción simple",
  opcion_multiple: "Opción múltiple",
  prioridad: "Ordenar prioridades",
};

// Tipos cuya respuesta es una lista de frases/opciones editable (en vez de
// un prompt() con comas, una fila por opción — como en Microsoft Forms).
const TIPOS_CON_OPCIONES = new Set(["opcion_simple", "opcion_multiple", "prioridad"]);

const LIKERT_DEFAULT_LABELS = [
  "Totalmente en desacuerdo", "En desacuerdo", "Ni de acuerdo ni en desacuerdo", "De acuerdo", "Totalmente de acuerdo",
];

// Preguntas que interesa ver de un vistazo en el dashboard de resultados
// (Scoring/Dashboard de Informes) vienen con esta casilla premarcada por
// defecto — el admin puede activarla o desactivarla para cualquier tipo.
function mostrarDashboardPorDefecto(tipo) {
  return tipo === "abierta" || tipo === "prioridad";
}

const editandoPreguntas = new Set();
let arrastrandoPreguntaId = null;

// Las preguntas de escala guardan la etiqueta completa "Categoria.Pregunta"
// (KK) o "Preámbulo: [Pregunta]" (Saona) porque entrevistas.py necesita ese
// formato exacto para agrupar por bloque en el informe — pero mostrar ese
// texto completo en cada fila de la lista repite el nombre del bloque en
// todas las preguntas. Aquí se deriva solo la parte "pregunta" para
// mostrarla en el listado; el valor guardado/editado no cambia.
function etiquetaVisible(q) {
  if (q.tipo !== "likert") return q.etiqueta;
  const mSaona = q.etiqueta.match(/^(.*?):\s*\[(.+)\]\s*$/);
  if (mSaona) return mSaona[2].trim();
  const punto = q.etiqueta.indexOf(".");
  if (punto !== -1 && q.etiqueta.slice(punto + 1).trim().length > 3) {
    return q.etiqueta.slice(punto + 1).trim();
  }
  return q.etiqueta;
}

function opcionesEditorHTML(tipo, opciones, opcionesDescarta) {
  if (tipo === "likert") {
    // El puntaje SIEMPRE es 1-5 según la posición (no el texto) — así el
    // admin puede cambiar la leyenda de cada nivel libremente sin arriesgar
    // que la puntuación se rompa. Por eso son exactamente 5 filas fijas,
    // sin poder añadir/quitar: no hay forma de dejarlo mal configurado.
    const lista = opciones && opciones.length === 5 ? opciones : LIKERT_DEFAULT_LABELS;
    return `<div class="opciones-editor" data-tipo="likert">
      <p class="opciones-editor-ayuda">El puntaje (1 a 5) lo fija la posición, no el texto — edita solo la leyenda de cada nivel. Se comparte con las demás preguntas de escala de esta página.</p>
      <div class="opciones-editor-filas">
        ${lista
          .map(
            (op, i) => `
          <div class="opcion-editor-row">
            <span class="opcion-editor-punto">${i + 1} pt</span>
            <input type="text" class="opcion-editor-input" value="${escapeHTML(op)}" placeholder="Nivel ${i + 1}">
          </div>`
          )
          .join("")}
      </div>
    </div>`;
  }
  if (!TIPOS_CON_OPCIONES.has(tipo)) return "";
  const lista = opciones && opciones.length ? opciones : ["", ""];
  // Solo tiene sentido marcar una opción como descalificatoria en opción
  // simple (una sola respuesta posible) -- en opción múltiple no habría
  // forma inequívoca de decidir si "descalifica" con una sola marcada entre
  // varias. Es la misma restricción que ya usa preguntasRamificablesAntesDe
  // para las ramificaciones condicionales.
  const permiteDescarta = tipo === "opcion_simple";
  const descarta = opcionesDescarta && opcionesDescarta.length === lista.length ? opcionesDescarta : lista.map(() => false);
  return `<div class="opciones-editor" data-permite-descarta="${permiteDescarta ? "1" : "0"}">
    <div class="opciones-editor-filas">
      ${lista
        .map(
          (op, i) => `
        <div class="opcion-editor-row">
          <input type="text" class="opcion-editor-input" value="${escapeHTML(op)}" placeholder="Opción ${i + 1}">
          ${opcionDescartaChkHTML(permiteDescarta, descarta[i])}
          <button type="button" class="btn-mini btn-opcion-quitar" title="Quitar esta opción"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg></button>
        </div>`
        )
        .join("")}
    </div>
    <button type="button" class="btn btn-ghost btn-mini btn-opcion-agregar">＋ Agregar opción</button>
  </div>`;
}

// Si quien responde elige esta opción, su respuesta se marca "No apto" en
// Informes (ver encuestas.guardar_respuesta) -- solo aparece en preguntas
// de opción simple.
function opcionDescartaChkHTML(permiteDescarta, marcada) {
  if (!permiteDescarta) return "";
  return `<label class="chk opcion-descarta-chk" title="Si eligen esta opción, la respuesta se marca como 'No apto' en Informes"><input type="checkbox" class="opcion-editor-descarta" ${marcada ? "checked" : ""}> No apto</label>`;
}

function bindOpcionesEditor(root) {
  root.querySelectorAll(".opciones-editor").forEach((editor) => {
    const filas = editor.querySelector(".opciones-editor-filas");
    const permiteDescarta = editor.dataset.permiteDescarta === "1";
    editor.querySelectorAll(".btn-opcion-quitar").forEach((btn) => {
      btn.addEventListener("click", () => {
        if (filas.children.length <= 2) return;
        btn.closest(".opcion-editor-row").remove();
      });
    });
    const btnAgregar = editor.querySelector(".btn-opcion-agregar");
    btnAgregar?.addEventListener("click", () => {
      const row = document.createElement("div");
      row.className = "opcion-editor-row";
      row.innerHTML = `<input type="text" class="opcion-editor-input" placeholder="Nueva opción">${opcionDescartaChkHTML(permiteDescarta, false)}<button type="button" class="btn-mini btn-opcion-quitar" title="Quitar esta opción"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg></button>`;
      filas.appendChild(row);
      row.querySelector(".btn-opcion-quitar").addEventListener("click", () => {
        if (filas.children.length <= 2) return;
        row.remove();
      });
    });
  });
}

function leerOpciones(editorRoot) {
  if (!editorRoot) return [];
  return Array.from(editorRoot.querySelectorAll(".opcion-editor-row"))
    .map((row) => row.querySelector(".opcion-editor-input").value.trim())
    .filter(Boolean);
}

// Paralelo a leerOpciones: misma posición = misma opción, filtrando igual
// las filas vacías para que las dos listas queden con la misma longitud.
function leerOpcionesDescarta(editorRoot) {
  if (!editorRoot) return [];
  return Array.from(editorRoot.querySelectorAll(".opcion-editor-row"))
    .filter((row) => row.querySelector(".opcion-editor-input").value.trim())
    .map((row) => row.querySelector(".opcion-editor-descarta")?.checked || false);
}

// Preguntas de opción SIMPLE (una sola respuesta) de páginas ANTERIORES a
// "pi" — únicas que tiene sentido usar como origen de una ramificación (un
// valor fijo entre varias opciones, no texto libre, escala ni una lista de
// varias marcadas a la vez).
function preguntasRamificablesAntesDe(pi) {
  const lista = [];
  currentTest.paginas.forEach((pagina, i) => {
    if (i >= pi) return;
    pagina.preguntas.forEach((q) => {
      if (q.tipo === "opcion_simple") lista.push(q);
    });
  });
  return lista;
}

function condicionEditorHTML(p, pi) {
  const opciones = preguntasRamificablesAntesDe(pi);
  if (opciones.length === 0) return "";
  const preguntaSeleccionada = opciones.find((q) => q.id === p.condicion_pregunta_id);
  return `
    <div class="pagina-condicion" data-pagina-id="${p.id}">
      <label>Mostrar esta página solo si...</label>
      <select class="pagina-condicion-pregunta" data-pagina-id="${p.id}">
        <option value="">— Siempre mostrar —</option>
        ${opciones
          .map((q) => `<option value="${q.id}" ${q.id === p.condicion_pregunta_id ? "selected" : ""}>${escapeHTML(q.etiqueta.slice(0, 60))}</option>`)
          .join("")}
      </select>
      <div class="pagina-condicion-valores" data-pagina-id="${p.id}">
        ${
          preguntaSeleccionada
            ? preguntaSeleccionada.opciones
                .map(
                  (op) => `<label class="chk"><input type="checkbox" class="pagina-condicion-valor" value="${escapeHTML(op)}" ${p.condicion_valores.includes(op) ? "checked" : ""}> ${escapeHTML(op)}</label>`
                )
                .join("")
            : ""
        }
      </div>
    </div>`;
}

async function guardarCondicionPagina(paginaId) {
  const card = document.querySelector(`.pagina-card[data-pagina-id="${paginaId}"]`);
  const instrucciones = card.querySelector(".pagina-instrucciones").value;
  const select = card.querySelector(".pagina-condicion-pregunta");
  const condicionPreguntaId = select && select.value ? Number(select.value) : null;
  const condicionValores = condicionPreguntaId
    ? Array.from(card.querySelectorAll(".pagina-condicion-valor:checked")).map((el) => el.value)
    : [];
  await fetch(`${AUTH_API_BASE}/encuestas/paginas/${paginaId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ instrucciones, condicion_pregunta_id: condicionPreguntaId, condicion_valores: condicionValores }),
  });
}

function renderPaginas() {
  const wrap = document.getElementById("paginas-wrap");
  wrap.innerHTML = currentTest.paginas
    .map(
      (p, pi) => `
    <div class="pagina-card" data-pagina-id="${p.id}">
      <div class="pagina-head">
        <textarea class="pagina-instrucciones" data-pagina-id="${p.id}" placeholder="Instrucciones de esta página (opcional)">${escapeHTML(p.instrucciones || "")}</textarea>
        <div class="pagina-acciones">
          <button type="button" class="btn-mini btn-pagina-subir" data-pagina-id="${p.id}" ${pi === 0 ? "disabled" : ""}>${ICONO_FLECHA_ARRIBA}</button>
          <button type="button" class="btn-mini btn-pagina-bajar" data-pagina-id="${p.id}" ${pi === currentTest.paginas.length - 1 ? "disabled" : ""}>${ICONO_FLECHA_ABAJO}</button>
          <button type="button" class="btn-mini btn-pagina-borrar" data-pagina-id="${p.id}"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg></button>
        </div>
      </div>
      ${condicionEditorHTML(p, pi)}
      <div class="preguntas-lista" data-pagina-id="${p.id}">
        ${p.preguntas
          .map((q, qi) => {
            if (editandoPreguntas.has(q.id)) {
              return `
          <div class="pregunta-item pregunta-editando" data-pregunta-id="${q.id}" data-tipo="${q.tipo}">
            <div class="pregunta-edit-form">
              <span class="tipo-badge">${TIPOS_PREGUNTA_LABELS[q.tipo] || q.tipo}</span>
              <input type="text" class="pregunta-edit-etiqueta" value="${escapeHTML(q.etiqueta)}" placeholder="Enunciado de la pregunta...">
              <div class="pregunta-edit-opciones">${opcionesEditorHTML(q.tipo, q.opciones, q.opciones_descarta)}</div>
              <div class="pregunta-edit-flags">
                <label class="chk"><input type="checkbox" class="pregunta-edit-obligatoria" ${q.obligatoria ? "checked" : ""}> Obligatoria</label>
                <label class="chk"><input type="checkbox" class="pregunta-edit-dashboard" ${q.mostrar_dashboard ? "checked" : ""}> Mostrar en el dashboard de resultados</label>
              </div>
              <div class="pregunta-edit-acciones">
                <button type="button" class="btn btn-primary btn-mini btn-pregunta-guardar" data-pregunta-id="${q.id}">Guardar</button>
                <button type="button" class="btn btn-ghost btn-mini btn-pregunta-cancelar" data-pregunta-id="${q.id}">Cancelar</button>
              </div>
            </div>
          </div>`;
            }
            return `
          <div class="pregunta-item" draggable="true" data-pregunta-id="${q.id}">
            <div class="pregunta-row" data-pregunta-id="${q.id}">
              <span class="pregunta-handle" title="Arrastra para mover (incluso a otra página)">${ICONO_ARRASTRAR}</span>
              <span class="tipo-badge">${TIPOS_PREGUNTA_LABELS[q.tipo] || q.tipo}</span>
              <span class="etiqueta-txt">${escapeHTML(etiquetaVisible(q))}</span>
              <span class="obligatoria-txt">${q.obligatoria ? "obligatoria" : "opcional"}</span>
              ${q.mostrar_dashboard ? `<span class="dashboard-badge" title="Esta respuesta aparece en el dashboard de resultados">📊 dashboard</span>` : ""}
              <span class="pregunta-acciones">
                <button type="button" class="btn-mini btn-pregunta-editar" data-pregunta-id="${q.id}">${ICONO_LAPIZ}</button>
                <button type="button" class="btn-mini btn-pregunta-subir" data-pregunta-id="${q.id}" ${qi === 0 ? "disabled" : ""}>${ICONO_FLECHA_ARRIBA}</button>
                <button type="button" class="btn-mini btn-pregunta-bajar" data-pregunta-id="${q.id}" ${qi === p.preguntas.length - 1 ? "disabled" : ""}>${ICONO_FLECHA_ABAJO}</button>
                <button type="button" class="btn-mini btn-pregunta-borrar" data-pregunta-id="${q.id}"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg></button>
              </span>
            </div>
          </div>`;
          })
          .join("")}
      </div>
      <div class="nueva-pregunta-form">
        <div class="nueva-pregunta-form-fila">
          <select class="nueva-pregunta-tipo" data-pagina-id="${p.id}">
            ${Object.entries(TIPOS_PREGUNTA_LABELS).map(([v, l]) => `<option value="${v}">${l}</option>`).join("")}
          </select>
          <input type="text" class="etiqueta nueva-pregunta-etiqueta" data-pagina-id="${p.id}" placeholder="Enunciado de la pregunta...">
        </div>
        <div class="nueva-pregunta-opciones" data-pagina-id="${p.id}"></div>
        <div class="nueva-pregunta-form-fila">
          <label class="chk"><input type="checkbox" class="nueva-pregunta-obligatoria" data-pagina-id="${p.id}" checked> Obligatoria</label>
          <label class="chk"><input type="checkbox" class="nueva-pregunta-dashboard" data-pagina-id="${p.id}"> Mostrar en el dashboard de resultados</label>
          <button type="button" class="btn btn-primary btn-agregar-pregunta" data-pagina-id="${p.id}">＋ Añadir pregunta</button>
        </div>
      </div>
    </div>`
    )
    .join("");

  bindOpcionesEditor(wrap);

  wrap.querySelectorAll(".pagina-instrucciones").forEach((el) => {
    el.addEventListener("blur", () => guardarCondicionPagina(el.dataset.paginaId));
  });
  wrap.querySelectorAll(".pagina-condicion-pregunta").forEach((select) => {
    select.addEventListener("change", async () => {
      await guardarCondicionPagina(select.dataset.paginaId);
      await abrirEditor(currentTestId, { scroll: false });
    });
  });
  wrap.querySelectorAll(".pagina-condicion-valor").forEach((chk) => {
    chk.addEventListener("change", () => {
      const paginaId = chk.closest(".pagina-condicion-valores").dataset.paginaId;
      guardarCondicionPagina(paginaId);
    });
  });
  wrap.querySelectorAll(".btn-pagina-subir").forEach((btn) =>
    btn.addEventListener("click", async () => {
      await fetch(`${AUTH_API_BASE}/encuestas/paginas/${btn.dataset.paginaId}/mover-arriba`, { method: "POST" });
      await abrirEditor(currentTestId, { scroll: false });
    })
  );
  wrap.querySelectorAll(".btn-pagina-bajar").forEach((btn) =>
    btn.addEventListener("click", async () => {
      await fetch(`${AUTH_API_BASE}/encuestas/paginas/${btn.dataset.paginaId}/mover-abajo`, { method: "POST" });
      await abrirEditor(currentTestId, { scroll: false });
    })
  );
  wrap.querySelectorAll(".btn-pagina-borrar").forEach((btn) =>
    btn.addEventListener("click", async () => {
      if (!(await pedirConfirmacion("¿Eliminar esta página y sus preguntas?"))) return;
      await fetch(`${AUTH_API_BASE}/encuestas/paginas/${btn.dataset.paginaId}`, { method: "DELETE" });
      await abrirEditor(currentTestId, { scroll: false });
    })
  );
  wrap.querySelectorAll(".btn-pregunta-subir").forEach((btn) =>
    btn.addEventListener("click", async () => {
      await fetch(`${AUTH_API_BASE}/encuestas/preguntas/${btn.dataset.preguntaId}/mover-arriba`, { method: "POST" });
      await abrirEditor(currentTestId, { scroll: false });
    })
  );
  wrap.querySelectorAll(".btn-pregunta-bajar").forEach((btn) =>
    btn.addEventListener("click", async () => {
      await fetch(`${AUTH_API_BASE}/encuestas/preguntas/${btn.dataset.preguntaId}/mover-abajo`, { method: "POST" });
      await abrirEditor(currentTestId, { scroll: false });
    })
  );
  wrap.querySelectorAll(".btn-pregunta-borrar").forEach((btn) =>
    btn.addEventListener("click", async () => {
      if (!(await pedirConfirmacion("¿Eliminar esta pregunta?"))) return;
      await fetch(`${AUTH_API_BASE}/encuestas/preguntas/${btn.dataset.preguntaId}`, { method: "DELETE" });
      await abrirEditor(currentTestId, { scroll: false });
    })
  );
  wrap.querySelectorAll(".btn-pregunta-editar").forEach((btn) =>
    btn.addEventListener("click", () => {
      editandoPreguntas.add(Number(btn.dataset.preguntaId));
      renderPaginas();
    })
  );
  wrap.querySelectorAll(".btn-pregunta-cancelar").forEach((btn) =>
    btn.addEventListener("click", () => {
      editandoPreguntas.delete(Number(btn.dataset.preguntaId));
      renderPaginas();
    })
  );
  wrap.querySelectorAll(".btn-pregunta-guardar").forEach((btn) =>
    btn.addEventListener("click", async () => {
      const preguntaId = Number(btn.dataset.preguntaId);
      const item = wrap.querySelector(`.pregunta-item[data-pregunta-id="${preguntaId}"]`);
      const etiqueta = item.querySelector(".pregunta-edit-etiqueta").value.trim();
      if (!etiqueta) {
        mostrarAviso("Escribe el enunciado de la pregunta.");
        return;
      }
      const obligatoria = item.querySelector(".pregunta-edit-obligatoria").checked;
      const mostrarDashboard = item.querySelector(".pregunta-edit-dashboard").checked;
      const editorOpciones = item.querySelector(".pregunta-edit-opciones .opciones-editor");
      const opciones = editorOpciones ? leerOpciones(editorOpciones) : [];
      const opcionesDescarta = editorOpciones ? leerOpcionesDescarta(editorOpciones) : [];
      if (editorOpciones && opciones.length < 2) {
        mostrarAviso("Escribe al menos 2 opciones.");
        return;
      }
      const res = await fetch(`${AUTH_API_BASE}/encuestas/preguntas/${preguntaId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tipo: item.dataset.tipo, etiqueta, obligatoria, opciones, mostrar_dashboard: mostrarDashboard,
          opciones_descarta: opcionesDescarta,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        mostrarAviso(err.detail || "No se pudo guardar la pregunta.");
        return;
      }
      editandoPreguntas.delete(preguntaId);
      await abrirEditor(currentTestId, { scroll: false });
    })
  );
  wrap.querySelectorAll(".nueva-pregunta-tipo").forEach((select) => {
    select.addEventListener("change", () => {
      const paginaId = select.dataset.paginaId;
      const slot = wrap.querySelector(`.nueva-pregunta-opciones[data-pagina-id="${paginaId}"]`);
      slot.innerHTML = opcionesEditorHTML(select.value, null);
      bindOpcionesEditor(slot);
      const dashboardChk = wrap.querySelector(`.nueva-pregunta-dashboard[data-pagina-id="${paginaId}"]`);
      dashboardChk.checked = mostrarDashboardPorDefecto(select.value);
    });
  });
  wrap.querySelectorAll(".btn-agregar-pregunta").forEach((btn) =>
    btn.addEventListener("click", async () => {
      const paginaId = btn.dataset.paginaId;
      const tipo = wrap.querySelector(`.nueva-pregunta-tipo[data-pagina-id="${paginaId}"]`).value;
      const etiqueta = wrap.querySelector(`.nueva-pregunta-etiqueta[data-pagina-id="${paginaId}"]`).value.trim();
      const obligatoria = wrap.querySelector(`.nueva-pregunta-obligatoria[data-pagina-id="${paginaId}"]`).checked;
      const mostrarDashboard = wrap.querySelector(`.nueva-pregunta-dashboard[data-pagina-id="${paginaId}"]`).checked;
      if (!etiqueta) {
        mostrarAviso("Escribe el enunciado de la pregunta.");
        return;
      }
      const slot = wrap.querySelector(`.nueva-pregunta-opciones[data-pagina-id="${paginaId}"]`);
      const editorOpciones = slot.querySelector(".opciones-editor");
      const opciones = editorOpciones ? leerOpciones(editorOpciones) : [];
      const opcionesDescarta = editorOpciones ? leerOpcionesDescarta(editorOpciones) : [];
      if (editorOpciones && opciones.length < 2) {
        mostrarAviso("Escribe al menos 2 opciones.");
        return;
      }
      const res = await fetch(`${AUTH_API_BASE}/encuestas/paginas/${paginaId}/preguntas`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tipo, etiqueta, obligatoria, opciones, mostrar_dashboard: mostrarDashboard,
          opciones_descarta: opcionesDescarta,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        mostrarAviso(err.detail || "No se pudo añadir la pregunta.");
        return;
      }
      await abrirEditor(currentTestId, { scroll: false });
    })
  );

  // Arrastrar preguntas (incluso entre páginas distintas): delegado en `wrap`
  // en vez de en cada `.pregunta-item`, porque `wrap` es el único nodo que
  // sobrevive entre llamadas a renderPaginas() (su innerHTML se reemplaza
  // entero en cada render) — de lo contrario cada render añadiría un
  // listener más y un solo drop dispararía varias peticiones.
  if (!wrap.dataset.dragWired) {
    wrap.dataset.dragWired = "1";
    wrap.addEventListener("dragstart", (e) => {
      const item = e.target.closest(".pregunta-item");
      if (!item || item.classList.contains("pregunta-editando")) return;
      arrastrandoPreguntaId = Number(item.dataset.preguntaId);
      e.dataTransfer.effectAllowed = "move";
      item.classList.add("arrastrando");
    });
    wrap.addEventListener("dragover", (e) => {
      if (arrastrandoPreguntaId == null) return;
      // Se usa `.pagina-card` (toda la tarjeta) en vez de `.preguntas-lista`
      // como zona de soltado: si solo la lista contara, arrastrar la ÚLTIMA
      // pregunta de una página hacia la siguiente sacaba el cursor de esa
      // lista (pasando por el formulario de "Añadir pregunta" o el hueco
      // entre tarjetas) antes de entrar en la lista destino, y el navegador
      // cancelaba el drop por completo.
      const card = e.target.closest(".pagina-card");
      if (!card) return;
      e.preventDefault();
      wrap.querySelectorAll(".drop-antes,.drop-despues").forEach((el) => el.classList.remove("drop-antes", "drop-despues"));
      const item = e.target.closest(".pregunta-item");
      if (item && Number(item.dataset.preguntaId) !== arrastrandoPreguntaId) {
        const rect = item.getBoundingClientRect();
        const antes = e.clientY - rect.top < rect.height / 2;
        item.classList.add(antes ? "drop-antes" : "drop-despues");
      }
    });
    wrap.addEventListener("drop", async (e) => {
      if (arrastrandoPreguntaId == null) return;
      const card = e.target.closest(".pagina-card");
      if (!card) return;
      e.preventDefault();
      const preguntaId = arrastrandoPreguntaId;
      const paginaDestinoId = Number(card.dataset.paginaId);
      const item = e.target.closest(".pregunta-item");
      let antesDeId = null;
      if (item && Number(item.dataset.preguntaId) !== preguntaId) {
        const rect = item.getBoundingClientRect();
        const antes = e.clientY - rect.top < rect.height / 2;
        if (antes) {
          antesDeId = Number(item.dataset.preguntaId);
        } else {
          let sib = item.nextElementSibling;
          while (sib && !sib.matches(".pregunta-item")) sib = sib.nextElementSibling;
          antesDeId = sib ? Number(sib.dataset.preguntaId) : null;
        }
      }
      arrastrandoPreguntaId = null;
      await fetch(`${AUTH_API_BASE}/encuestas/preguntas/${preguntaId}/mover-a-pagina`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pagina_destino_id: paginaDestinoId, antes_de_pregunta_id: antesDeId }),
      });
      await abrirEditor(currentTestId, { scroll: false });
    });
    wrap.addEventListener("dragend", () => {
      arrastrandoPreguntaId = null;
      wrap.querySelectorAll(".drop-antes,.drop-despues,.arrastrando").forEach((el) =>
        el.classList.remove("drop-antes", "drop-despues", "arrastrando")
      );
    });
  }
}

async function agregarPagina() {
  await fetch(`${AUTH_API_BASE}/encuestas/encuestas/${currentTestId}/paginas`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ instrucciones: "" }),
  });
  await abrirEditor(currentTestId, { scroll: false });
}

// creado_en llega como "YYYY-MM-DD HH:MM:SS" en UTC (datetime('now') de
// SQLite, sin sufijo de zona) — hay que decírselo explícitamente a Date
// (añadiendo "Z") para que el navegador la convierta a la hora local de
// quien lo está viendo; si no, se ve la hora UTC tal cual y parece 1-2h
// desfasada respecto a cuándo el candidato hizo el test en realidad.
function formatearValorRespuesta(valor) {
  if (Array.isArray(valor)) return valor.length ? valor.join(" → ") : "—";
  if (valor === null || valor === undefined || valor === "") return "—";
  return String(valor);
}

function formatearFechaHoraLocal(sqlUtc) {
  if (!sqlUtc) return "—";
  const fecha = new Date(sqlUtc.replace(" ", "T") + "Z");
  if (isNaN(fecha.getTime())) return sqlUtc;
  return fecha.toLocaleString("es-ES", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

async function actualizarEnVivoDetalle() {
  const enVivoP = document.getElementById("embudo-en-vivo");
  if (!currentTestId) return;
  const sesiones = await fetch(`${AUTH_API_BASE}/encuestas/encuestas/${currentTestId}/en-vivo-detalle`)
    .then((r) => (r.ok ? r.json() : []))
    .catch(() => []);
  if (sesiones.length === 0) {
    enVivoP.textContent = "Nadie está respondiendo este test ahora mismo.";
    return;
  }
  const paginas = sesiones.map((s) => `página ${s.pagina}`).join(", ");
  enVivoP.textContent = `🟢 ${sesiones.length} en vivo ahora mismo, en: ${paginas}.`;
}

async function reiniciarEmbudo() {
  if (!(await pedirConfirmacion("Esto borra todas las aperturas y abandonos registrados de este test (por ejemplo, pruebas que hayas hecho tú mismo). No afecta a las respuestas ya enviadas. ¿Continuar?"))) return;
  const res = await fetch(`${AUTH_API_BASE}/encuestas/encuestas/${currentTestId}/sesiones`, { method: "DELETE" });
  if (!res.ok) {
    mostrarAviso("No se pudo reiniciar (error " + res.status + ").");
    return;
  }
  await verEmbudo({ forzarRecarga: true });
}

async function verEmbudo({ forzarRecarga = false } = {}) {
  const wrap = document.getElementById("embudo-wrap");
  const visible = !wrap.hidden;
  if (visible && !forzarRecarga) {
    wrap.hidden = true;
    return;
  }
  const resumen = document.getElementById("embudo-resumen");
  const barras = document.getElementById("embudo-barras");
  actualizarEnVivoDetalle();
  let res;
  try {
    res = await fetch(`${AUTH_API_BASE}/encuestas/encuestas/${currentTestId}/embudo`);
  } catch (e) {
    resumen.textContent = `No se pudo conectar con el servidor: ${e.message}`;
    barras.innerHTML = "";
    wrap.hidden = false;
    return;
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    resumen.textContent = `No se pudieron cargar las estadísticas (error ${res.status}): ${body.detail || "sin detalle"}`;
    barras.innerHTML = "";
    wrap.hidden = false;
    return;
  }
  const datos = await res.json();
  if (datos.aperturas === 0) {
    resumen.textContent = "Todavía nadie ha abierto el enlace de este test.";
    barras.innerHTML = "";
  } else {
    const pct = Math.round((datos.completados / datos.aperturas) * 100);
    const abandonaron = datos.aperturas - datos.completados;
    const personas = datos.aperturas === 1 ? "1 persona abrió" : `${datos.aperturas} personas abrieron`;
    const completaron = datos.completados === 1 ? "1 lo completó" : `${datos.completados} lo completaron`;
    const abandonaronTxt = abandonaron === 1 ? "1 lo abandonó" : `${abandonaron} lo abandonaron`;
    resumen.textContent = `${personas} el enlace · ${completaron} (${pct}%) · ${abandonaronTxt} sin terminar.`;
    barras.innerHTML = datos.por_pagina
      .map((p) => {
        const pctPagina = Math.round((p.llegaron / datos.aperturas) * 100);
        return `
        <div class="embudo-fila">
          <span class="embudo-etiqueta">Página ${p.pagina}</span>
          <div class="embudo-barra-fondo"><div class="embudo-barra-relleno" style="width:${pctPagina}%"></div></div>
          <span class="embudo-valor">${p.llegaron} (${pctPagina}%)</span>
        </div>`;
      })
      .join("");
  }
  wrap.hidden = false;
  wrap.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function verRespuestas() {
  const wrap = document.getElementById("respuestas-wrap");
  const visible = !wrap.hidden;
  if (visible) {
    wrap.hidden = true;
    return;
  }
  const res = await fetch(`${AUTH_API_BASE}/encuestas/encuestas/${currentTestId}/respuestas`);
  const respuestas = await res.json();
  const tbody = document.getElementById("respuestas-tbody");
  if (respuestas.length === 0) {
    tbody.innerHTML = `<tr><td colspan="4" class="staff-hint">Todavía no hay respuestas.</td></tr>`;
  } else {
    tbody.innerHTML = respuestas
      .map((r) => {
        // Solo hay enlace al informe si el test alimenta un tipo de Informe
        // y esa fila concreta llegó a calcularse ahí (ver guardar_respuesta
        // en encuestas.py) — si no, solo queda el JSON crudo interno.
        const enlaceInforme = r.informe_respuesta_id
          ? (() => {
              const empresa = r.informe_tipo_clave.startsWith("saona_") ? "saona" : "kk";
              const params = new URLSearchParams({
                tipo: r.informe_tipo_clave, hoja: r.informe_hoja || "", respuesta: r.informe_respuesta_id, empresa,
              });
              return `<a href="/informes.html?${params.toString()}" target="_blank" class="btn btn-ghost btn-mini">Ver en Informes</a>`;
            })()
          : "";
        const filasDatos = Object.entries(r.datos)
          .map(
            ([pregunta, valor]) => `
              <tr>
                <td class="respuesta-detalle-pregunta">${escapeHTML(pregunta)}</td>
                <td class="respuesta-detalle-valor">${escapeHTML(formatearValorRespuesta(valor))}</td>
              </tr>`
          )
          .join("");
        return `
      <tr>
        <td>${formatearFechaHoraLocal(r.creado_en)}</td>
        <td>${escapeHTML(r.ip || "—")}</td>
        <td>${escapeHTML(r.dispositivo || "—")}</td>
        <td>
          ${enlaceInforme}
          <details>
            <summary>Ver respuestas (${Object.keys(r.datos).length})</summary>
            <table class="respuesta-detalle-tabla"><tbody>${filasDatos}</tbody></table>
          </details>
        </td>
        <td><button type="button" class="btn-mini btn-respuesta-borrar" data-respuesta-id="${r.id}"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg></button></td>
      </tr>`;
      })
      .join("");
    tbody.querySelectorAll(".btn-respuesta-borrar").forEach((btn) => {
      btn.addEventListener("click", () => borrarRespuesta(btn.dataset.respuestaId));
    });
  }
  wrap.hidden = false;
  // Este panel se pinta DESPUÉS de todas las páginas/preguntas del test, así
  // que en un test largo (20+ páginas) se abre muy por debajo del viewport
  // sin que se note — parecía que el botón no hacía nada.
  wrap.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function borrarRespuesta(respuestaId) {
  if (!(await pedirConfirmacion("¿Eliminar esta respuesta? No se puede deshacer."))) return;
  await fetch(`${AUTH_API_BASE}/encuestas/encuestas/respuestas/${respuestaId}`, { method: "DELETE" });
  document.getElementById("respuestas-wrap").hidden = true;
  await verRespuestas();
}

document.addEventListener("DOMContentLoaded", async () => {
  const user = await checkAuth("/tests.html");
  if (!user) return;
  if (!(user.modulos || []).includes("tests")) {
    window.location.href = "/";
    return;
  }
  wireUserBar(user);

  await loadTiposInforme();
  await loadTests();

  document.getElementById("btn-nuevo-test").addEventListener("click", () => abrirEditor(null));
  document.getElementById("btn-cerrar-editor").addEventListener("click", cerrarEditor);
  document.getElementById("btn-guardar-test").addEventListener("click", guardarTest);
  document.getElementById("btn-publicar-test").addEventListener("click", () => publicarTest(true));
  document.getElementById("btn-despublicar-test").addEventListener("click", () => publicarTest(false));
  document.getElementById("btn-eliminar-test").addEventListener("click", eliminarTest);
  document.getElementById("btn-nueva-pagina").addEventListener("click", agregarPagina);
  document.getElementById("btn-ver-respuestas").addEventListener("click", verRespuestas);
  document.getElementById("btn-ver-embudo").addEventListener("click", () => verEmbudo());
  document.getElementById("btn-reiniciar-embudo").addEventListener("click", reiniciarEmbudo);
  document.getElementById("input-fondo-upload").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    await subirFondo(file);
    e.target.value = "";
  });

  document.getElementById("test-tipo-informe").addEventListener("change", async (e) => {
    const val = e.target.value;
    if (val.startsWith("clima:nueva:")) {
      const empresa = val.slice("clima:nueva:".length);
      const etiqueta = prompt('Nombre de esta oleada de Clima Laboral (ej. "2026 · Encuesta completa"):');
      if (!etiqueta || !etiqueta.trim()) {
        e.target.value = currentTest?.clima_oleada_id ? `clima:${currentTest.clima_oleada_id}` : "";
        return;
      }
      const res = await fetch(`${AUTH_API_BASE}/clima/oleadas`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ etiqueta: etiqueta.trim(), empresa }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        mostrarAviso(err.detail || "No se pudo crear la oleada.");
        e.target.value = currentTest?.clima_oleada_id ? `clima:${currentTest.clima_oleada_id}` : "";
        return;
      }
      const data = await res.json();
      await loadTiposInforme();
      e.target.value = `clima:${data.id}`;
    }
    // Entrevista de Salida y Clima Laboral son solo respuestas (sin
    // resultado apto/no apto) -- se sugiere desactivar el mensaje de "No
    // apto" al elegir uno de esos destinos, pero sigue siendo un
    // interruptor manual: si el admin lo reactiva a mano, se respeta.
    if (val.startsWith("entrevista:") || val.startsWith("clima:")) {
      document.getElementById("test-usar-mensaje-no-apto").checked = false;
      actualizarVisibilidadMensajeNoApto();
    }
    await actualizarVistaClimaPlantilla();
  });
  document.getElementById("test-usar-mensaje-no-apto").addEventListener("change", actualizarVisibilidadMensajeNoApto);
  document.getElementById("btn-clima-plantilla-agregar").addEventListener("click", () => {
    document.getElementById("clima-plantilla-filas").insertAdjacentHTML("beforeend", filaClimaPlantillaHTML());
    wireClimaPlantillaFilas();
  });
});

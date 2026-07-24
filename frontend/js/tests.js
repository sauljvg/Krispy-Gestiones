let currentTestId = null;
let currentTest = null;

function escapeHTML(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

async function loadTiposInforme() {
  const res = await fetch(`${AUTH_API_BASE}/encuestas/tipos-informe-disponibles`);
  const tipos = await res.json();
  const select = document.getElementById("test-tipo-informe");
  select.innerHTML =
    `<option value="">— No calcular puntuación —</option>` +
    `<optgroup label="Informes">` +
    tipos.map((t) => `<option value="informe:${escapeHTML(t.clave)}">${escapeHTML(t.nombre)}</option>`).join("") +
    `</optgroup>` +
    `<optgroup label="Entrevista de Salida">` +
    `<option value="entrevista:kk">Entrevista de Salida — Krispy Kreme</option>` +
    `<option value="entrevista:saona">Entrevista de Salida — SAONA</option>` +
    `</optgroup>`;
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
      <td><span class="badge ${t.estado === "abierta" ? "badge-abierta" : "badge-cerrada"}">${t.estado === "abierta" ? "Abierta" : "Cerrada"}</span></td>
      <td>${t.num_respuestas}</td>
      <td><button class="btn btn-ghost btn-editar-test" data-id="${t.id}" type="button">Editar</button></td>
    </tr>`
    )
    .join("");
  tbody.querySelectorAll(".btn-editar-test").forEach((btn) => {
    btn.addEventListener("click", () => abrirEditor(Number(btn.dataset.id)));
  });
}

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
    document.getElementById("test-color-boton").value = currentTest.color_boton;
    if (currentTest.tipo_entrevista_empresa) {
      document.getElementById("test-tipo-informe").value = `entrevista:${currentTest.tipo_entrevista_empresa}`;
    } else if (currentTest.tipo_informe_clave) {
      document.getElementById("test-tipo-informe").value = `informe:${currentTest.tipo_informe_clave}`;
    } else {
      document.getElementById("test-tipo-informe").value = "";
    }
    document.getElementById("test-enlace-publico").value = `${location.origin}/encuesta.html?slug=${currentTest.slug}`;
    document.getElementById("fondo-preview").hidden = !currentTest.tiene_fondo;
    if (currentTest.tiene_fondo) {
      document.getElementById("fondo-preview").src = `${AUTH_API_BASE}/encuestas/encuestas/${testId}/fondo?t=${Date.now()}`;
    }
    document.getElementById("btn-publicar-test").hidden = currentTest.estado === "abierta";
    document.getElementById("btn-despublicar-test").hidden = currentTest.estado !== "abierta";
    document.getElementById("btn-ver-respuestas").hidden = false;
    document.getElementById("btn-eliminar-test").hidden = false;
    document.getElementById("btn-nueva-pagina").hidden = false;
    renderPaginas();
  } else {
    currentTest = null;
    document.getElementById("editor-titulo-h2").textContent = "Nuevo test";
    document.getElementById("test-titulo").value = "";
    document.getElementById("test-mensaje-final").value = "Gracias por completar el formulario.";
    document.getElementById("test-color-boton").value = "#5b2a2a";
    document.getElementById("test-tipo-informe").value = "";
    document.getElementById("test-enlace-publico").value = "";
    document.getElementById("fondo-preview").hidden = true;
    document.getElementById("btn-publicar-test").hidden = true;
    document.getElementById("btn-despublicar-test").hidden = true;
    document.getElementById("btn-ver-respuestas").hidden = true;
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
    alert("El título es obligatorio.");
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
      alert(err.detail || "No se pudo crear el test.");
      return;
    }
    const data = await res.json();
    currentTestId = data.id;
  }
  const destino = document.getElementById("test-tipo-informe").value;
  const body = {
    titulo,
    mensaje_final: document.getElementById("test-mensaje-final").value.trim(),
    color_boton: document.getElementById("test-color-boton").value,
    tipo_informe_clave: destino.startsWith("informe:") ? destino.slice("informe:".length) : null,
    tipo_entrevista_empresa: destino.startsWith("entrevista:") ? destino.slice("entrevista:".length) : null,
  };
  const res = await fetch(`${AUTH_API_BASE}/encuestas/encuestas/${currentTestId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    alert(err.detail || "No se pudo guardar el test.");
    return;
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
  if (!confirm("¿Eliminar este test y todas sus respuestas? Esta acción no se puede deshacer.")) return;
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
    alert(err.detail || "No se pudo subir la imagen.");
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
  opcion_multiple: "Opción múltiple",
  prioridad: "Ordenar prioridades",
};

// Tipos cuya respuesta es una lista de frases/opciones editable (en vez de
// un prompt() con comas, una fila por opción — como en Microsoft Forms).
const TIPOS_CON_OPCIONES = new Set(["opcion_multiple", "prioridad"]);

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

function opcionesEditorHTML(tipo, opciones) {
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
  return `<div class="opciones-editor">
    <div class="opciones-editor-filas">
      ${lista
        .map(
          (op, i) => `
        <div class="opcion-editor-row">
          <input type="text" class="opcion-editor-input" value="${escapeHTML(op)}" placeholder="Opción ${i + 1}">
          <button type="button" class="btn-mini btn-opcion-quitar" title="Quitar esta opción">🗑</button>
        </div>`
        )
        .join("")}
    </div>
    <button type="button" class="btn btn-ghost btn-mini btn-opcion-agregar">＋ Agregar opción</button>
  </div>`;
}

function bindOpcionesEditor(root) {
  root.querySelectorAll(".opciones-editor").forEach((editor) => {
    const filas = editor.querySelector(".opciones-editor-filas");
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
      row.innerHTML = `<input type="text" class="opcion-editor-input" placeholder="Nueva opción"><button type="button" class="btn-mini btn-opcion-quitar" title="Quitar esta opción">🗑</button>`;
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
  return Array.from(editorRoot.querySelectorAll(".opcion-editor-input"))
    .map((el) => el.value.trim())
    .filter(Boolean);
}

// Preguntas de opción múltiple de páginas ANTERIORES a "pi" — únicas que
// tiene sentido usar como origen de una ramificación (un valor fijo entre
// varias opciones, no texto libre ni escala).
function preguntasRamificablesAntesDe(pi) {
  const lista = [];
  currentTest.paginas.forEach((pagina, i) => {
    if (i >= pi) return;
    pagina.preguntas.forEach((q) => {
      if (q.tipo === "opcion_multiple") lista.push(q);
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
          <button type="button" class="btn-mini btn-pagina-subir" data-pagina-id="${p.id}" ${pi === 0 ? "disabled" : ""}>↑</button>
          <button type="button" class="btn-mini btn-pagina-bajar" data-pagina-id="${p.id}" ${pi === currentTest.paginas.length - 1 ? "disabled" : ""}>↓</button>
          <button type="button" class="btn-mini btn-pagina-borrar" data-pagina-id="${p.id}">🗑</button>
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
              <div class="pregunta-edit-opciones">${opcionesEditorHTML(q.tipo, q.opciones)}</div>
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
          <div class="pregunta-item" data-pregunta-id="${q.id}">
            <div class="pregunta-row" data-pregunta-id="${q.id}">
              <span class="tipo-badge">${TIPOS_PREGUNTA_LABELS[q.tipo] || q.tipo}</span>
              <span class="etiqueta-txt">${escapeHTML(etiquetaVisible(q))}</span>
              <span class="obligatoria-txt">${q.obligatoria ? "obligatoria" : "opcional"}</span>
              ${q.mostrar_dashboard ? `<span class="dashboard-badge" title="Esta respuesta aparece en el dashboard de resultados">📊 dashboard</span>` : ""}
              <span class="pregunta-acciones">
                <button type="button" class="btn-mini btn-pregunta-editar" data-pregunta-id="${q.id}">✎</button>
                <button type="button" class="btn-mini btn-pregunta-subir" data-pregunta-id="${q.id}" ${qi === 0 ? "disabled" : ""}>↑</button>
                <button type="button" class="btn-mini btn-pregunta-bajar" data-pregunta-id="${q.id}" ${qi === p.preguntas.length - 1 ? "disabled" : ""}>↓</button>
                <button type="button" class="btn-mini btn-pregunta-borrar" data-pregunta-id="${q.id}">🗑</button>
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
          <button type="button" class="btn btn-ghost btn-agregar-pregunta" data-pagina-id="${p.id}">＋ Añadir pregunta</button>
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
      if (!confirm("¿Eliminar esta página y sus preguntas?")) return;
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
      if (!confirm("¿Eliminar esta pregunta?")) return;
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
        alert("Escribe el enunciado de la pregunta.");
        return;
      }
      const obligatoria = item.querySelector(".pregunta-edit-obligatoria").checked;
      const mostrarDashboard = item.querySelector(".pregunta-edit-dashboard").checked;
      const editorOpciones = item.querySelector(".pregunta-edit-opciones .opciones-editor");
      const opciones = editorOpciones ? leerOpciones(editorOpciones) : [];
      if (editorOpciones && opciones.length < 2) {
        alert("Escribe al menos 2 opciones.");
        return;
      }
      const res = await fetch(`${AUTH_API_BASE}/encuestas/preguntas/${preguntaId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tipo: item.dataset.tipo, etiqueta, obligatoria, opciones, mostrar_dashboard: mostrarDashboard }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        alert(err.detail || "No se pudo guardar la pregunta.");
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
        alert("Escribe el enunciado de la pregunta.");
        return;
      }
      const slot = wrap.querySelector(`.nueva-pregunta-opciones[data-pagina-id="${paginaId}"]`);
      const editorOpciones = slot.querySelector(".opciones-editor");
      const opciones = editorOpciones ? leerOpciones(editorOpciones) : [];
      if (editorOpciones && opciones.length < 2) {
        alert("Escribe al menos 2 opciones.");
        return;
      }
      const res = await fetch(`${AUTH_API_BASE}/encuestas/paginas/${paginaId}/preguntas`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tipo, etiqueta, obligatoria, opciones, mostrar_dashboard: mostrarDashboard }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        alert(err.detail || "No se pudo añadir la pregunta.");
        return;
      }
      await abrirEditor(currentTestId, { scroll: false });
    })
  );
}

async function agregarPagina() {
  await fetch(`${AUTH_API_BASE}/encuestas/encuestas/${currentTestId}/paginas`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ instrucciones: "" }),
  });
  await abrirEditor(currentTestId, { scroll: false });
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
      .map(
        (r) => `
      <tr>
        <td>${(r.creado_en || "").slice(0, 16)}</td>
        <td>${escapeHTML(r.ip || "—")}</td>
        <td>${escapeHTML(r.dispositivo || "—")}</td>
        <td><details><summary>Ver</summary><pre style="white-space:pre-wrap;">${escapeHTML(JSON.stringify(r.datos, null, 2))}</pre></details></td>
      </tr>`
      )
      .join("");
  }
  wrap.hidden = false;
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
  document.getElementById("input-fondo-upload").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    await subirFondo(file);
    e.target.value = "";
  });
});

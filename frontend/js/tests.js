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
    tipos.map((t) => `<option value="${escapeHTML(t.clave)}">${escapeHTML(t.nombre)}</option>`).join("");
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

async function abrirEditor(testId) {
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
    document.getElementById("test-tipo-informe").value = currentTest.tipo_informe_clave || "";
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
  editorCard.scrollIntoView({ behavior: "smooth", block: "start" });
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
  const body = {
    titulo,
    mensaje_final: document.getElementById("test-mensaje-final").value.trim(),
    color_boton: document.getElementById("test-color-boton").value,
    tipo_informe_clave: document.getElementById("test-tipo-informe").value || null,
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
  await abrirEditor(currentTestId);
}

async function publicarTest(publicar) {
  await fetch(`${AUTH_API_BASE}/encuestas/encuestas/${currentTestId}/${publicar ? "publicar" : "despublicar"}`, { method: "POST" });
  await loadTests();
  await abrirEditor(currentTestId);
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
  await abrirEditor(currentTestId);
}

const TIPOS_PREGUNTA_LABELS = {
  texto: "Texto",
  email: "Email",
  numero: "Número",
  likert: "Escala (1-5)",
  abierta: "Comentario abierto",
  opcion_multiple: "Opción múltiple",
  prioridad: "Ordenar prioridades",
};

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
      <div class="preguntas-lista" data-pagina-id="${p.id}">
        ${p.preguntas
          .map(
            (q, qi) => `
          <div class="pregunta-row" data-pregunta-id="${q.id}">
            <span class="tipo-badge">${TIPOS_PREGUNTA_LABELS[q.tipo] || q.tipo}</span>
            <span class="etiqueta-txt">${escapeHTML(q.etiqueta)}</span>
            <span class="obligatoria-txt">${q.obligatoria ? "obligatoria" : "opcional"}</span>
            <span class="pregunta-acciones">
              <button type="button" class="btn-mini btn-pregunta-subir" data-pregunta-id="${q.id}" ${qi === 0 ? "disabled" : ""}>↑</button>
              <button type="button" class="btn-mini btn-pregunta-bajar" data-pregunta-id="${q.id}" ${qi === p.preguntas.length - 1 ? "disabled" : ""}>↓</button>
              <button type="button" class="btn-mini btn-pregunta-borrar" data-pregunta-id="${q.id}">🗑</button>
            </span>
          </div>`
          )
          .join("")}
      </div>
      <div class="nueva-pregunta-form">
        <select class="nueva-pregunta-tipo" data-pagina-id="${p.id}">
          ${Object.entries(TIPOS_PREGUNTA_LABELS).map(([v, l]) => `<option value="${v}">${l}</option>`).join("")}
        </select>
        <input type="text" class="etiqueta nueva-pregunta-etiqueta" data-pagina-id="${p.id}" placeholder="Enunciado de la pregunta...">
        <label class="chk"><input type="checkbox" class="nueva-pregunta-obligatoria" data-pagina-id="${p.id}" checked> Obligatoria</label>
        <button type="button" class="btn btn-ghost btn-agregar-pregunta" data-pagina-id="${p.id}">＋ Añadir pregunta</button>
      </div>
    </div>`
    )
    .join("");

  wrap.querySelectorAll(".pagina-instrucciones").forEach((el) => {
    el.addEventListener("blur", async () => {
      await fetch(`${AUTH_API_BASE}/encuestas/paginas/${el.dataset.paginaId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ instrucciones: el.value }),
      });
    });
  });
  wrap.querySelectorAll(".btn-pagina-subir").forEach((btn) =>
    btn.addEventListener("click", async () => {
      await fetch(`${AUTH_API_BASE}/encuestas/paginas/${btn.dataset.paginaId}/mover-arriba`, { method: "POST" });
      await abrirEditor(currentTestId);
    })
  );
  wrap.querySelectorAll(".btn-pagina-bajar").forEach((btn) =>
    btn.addEventListener("click", async () => {
      await fetch(`${AUTH_API_BASE}/encuestas/paginas/${btn.dataset.paginaId}/mover-abajo`, { method: "POST" });
      await abrirEditor(currentTestId);
    })
  );
  wrap.querySelectorAll(".btn-pagina-borrar").forEach((btn) =>
    btn.addEventListener("click", async () => {
      if (!confirm("¿Eliminar esta página y sus preguntas?")) return;
      await fetch(`${AUTH_API_BASE}/encuestas/paginas/${btn.dataset.paginaId}`, { method: "DELETE" });
      await abrirEditor(currentTestId);
    })
  );
  wrap.querySelectorAll(".btn-pregunta-subir").forEach((btn) =>
    btn.addEventListener("click", async () => {
      await fetch(`${AUTH_API_BASE}/encuestas/preguntas/${btn.dataset.preguntaId}/mover-arriba`, { method: "POST" });
      await abrirEditor(currentTestId);
    })
  );
  wrap.querySelectorAll(".btn-pregunta-bajar").forEach((btn) =>
    btn.addEventListener("click", async () => {
      await fetch(`${AUTH_API_BASE}/encuestas/preguntas/${btn.dataset.preguntaId}/mover-abajo`, { method: "POST" });
      await abrirEditor(currentTestId);
    })
  );
  wrap.querySelectorAll(".btn-pregunta-borrar").forEach((btn) =>
    btn.addEventListener("click", async () => {
      if (!confirm("¿Eliminar esta pregunta?")) return;
      await fetch(`${AUTH_API_BASE}/encuestas/preguntas/${btn.dataset.preguntaId}`, { method: "DELETE" });
      await abrirEditor(currentTestId);
    })
  );
  wrap.querySelectorAll(".btn-agregar-pregunta").forEach((btn) =>
    btn.addEventListener("click", async () => {
      const paginaId = btn.dataset.paginaId;
      const tipo = wrap.querySelector(`.nueva-pregunta-tipo[data-pagina-id="${paginaId}"]`).value;
      const etiqueta = wrap.querySelector(`.nueva-pregunta-etiqueta[data-pagina-id="${paginaId}"]`).value.trim();
      const obligatoria = wrap.querySelector(`.nueva-pregunta-obligatoria[data-pagina-id="${paginaId}"]`).checked;
      if (!etiqueta) {
        alert("Escribe el enunciado de la pregunta.");
        return;
      }
      let opciones = [];
      if (tipo === "opcion_multiple") {
        const texto = prompt("Escribe las opciones separadas por coma:");
        opciones = (texto || "").split(",").map((o) => o.trim()).filter(Boolean);
      } else if (tipo === "prioridad") {
        const texto = prompt("Escribe las afirmaciones a ordenar, separadas por coma (orden inicial = el que verá el candidato):");
        opciones = (texto || "").split(",").map((o) => o.trim()).filter(Boolean);
        if (opciones.length < 2) {
          alert("Escribe al menos 2 afirmaciones para poder ordenarlas.");
          return;
        }
      }
      const res = await fetch(`${AUTH_API_BASE}/encuestas/paginas/${paginaId}/preguntas`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tipo, etiqueta, obligatoria, opciones }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        alert(err.detail || "No se pudo añadir la pregunta.");
        return;
      }
      await abrirEditor(currentTestId);
    })
  );
}

async function agregarPagina() {
  await fetch(`${AUTH_API_BASE}/encuestas/encuestas/${currentTestId}/paginas`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ instrucciones: "" }),
  });
  await abrirEditor(currentTestId);
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

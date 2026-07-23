const API_BASE = `${window.location.origin}/api/public/encuestas`;

let encuesta = null;
let paginaActual = 0;
const respuestas = {}; // pregunta_id -> valor

function escapeHTML(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

function mostrarError(mensaje) {
  document.getElementById("encuesta-card").innerHTML = `<div class="encuesta-error"><p>${escapeHTML(mensaje)}</p></div>`;
}

function renderPregunta(q) {
  const req = q.obligatoria ? `<span class="req"> *</span>` : "";
  const valorActual = respuestas[q.id] ?? "";
  if (q.tipo === "texto") {
    return `<div class="pregunta-bloque" data-pregunta-id="${q.id}">
      <label class="pregunta-label">${escapeHTML(q.etiqueta)}${req}</label>
      <input type="text" data-pregunta-id="${q.id}" value="${escapeHTML(valorActual)}">
    </div>`;
  }
  if (q.tipo === "email") {
    return `<div class="pregunta-bloque" data-pregunta-id="${q.id}">
      <label class="pregunta-label">${escapeHTML(q.etiqueta)}${req}</label>
      <input type="email" data-pregunta-id="${q.id}" value="${escapeHTML(valorActual)}">
    </div>`;
  }
  if (q.tipo === "numero") {
    return `<div class="pregunta-bloque" data-pregunta-id="${q.id}">
      <label class="pregunta-label">${escapeHTML(q.etiqueta)}${req}</label>
      <input type="number" data-pregunta-id="${q.id}" value="${escapeHTML(valorActual)}">
    </div>`;
  }
  if (q.tipo === "abierta") {
    return `<div class="pregunta-bloque" data-pregunta-id="${q.id}">
      <label class="pregunta-label">${escapeHTML(q.etiqueta)}${req}</label>
      <textarea data-pregunta-id="${q.id}">${escapeHTML(valorActual)}</textarea>
    </div>`;
  }
  if (q.tipo === "opcion_multiple") {
    return `<div class="pregunta-bloque" data-pregunta-id="${q.id}">
      <label class="pregunta-label">${escapeHTML(q.etiqueta)}${req}</label>
      <div class="opcion-multiple-lista">
        ${q.opciones
          .map(
            (op) => `<label><input type="radio" name="pregunta-${q.id}" value="${escapeHTML(op)}" ${valorActual === op ? "checked" : ""}> ${escapeHTML(op)}</label>`
          )
          .join("")}
      </div>
    </div>`;
  }
  return "";
}

const LIKERT_OPCIONES = [
  "Totalmente en desacuerdo", "En desacuerdo", "Ni de acuerdo ni en desacuerdo", "De acuerdo", "Totalmente de acuerdo",
];

function renderGrupoLikert(preguntas) {
  const filas = preguntas
    .map(
      (q) => `
    <tr data-pregunta-id="${q.id}">
      <td class="likert-etiqueta">${escapeHTML(q.etiqueta)}${q.obligatoria ? ' <span class="req">*</span>' : ""}</td>
      ${LIKERT_OPCIONES.map(
        (op) => `<td><input type="radio" name="pregunta-${q.id}" value="${op}" ${respuestas[q.id] === op ? "checked" : ""}></td>`
      ).join("")}
    </tr>`
    )
    .join("");
  return `
    <table class="likert-tabla">
      <thead><tr><th></th>${LIKERT_OPCIONES.map((op) => `<th>${op}</th>`).join("")}</tr></thead>
      <tbody>${filas}</tbody>
    </table>`;
}

function renderPagina(index) {
  const pagina = encuesta.paginas[index];
  const totalPaginas = encuesta.paginas.length;
  let bloquesHtml = "";
  let i = 0;
  while (i < pagina.preguntas.length) {
    const q = pagina.preguntas[i];
    if (q.tipo === "likert") {
      const grupo = [];
      while (i < pagina.preguntas.length && pagina.preguntas[i].tipo === "likert") {
        grupo.push(pagina.preguntas[i]);
        i++;
      }
      bloquesHtml += renderGrupoLikert(grupo);
    } else {
      bloquesHtml += renderPregunta(q);
      i++;
    }
  }

  const esUltima = index === totalPaginas - 1;
  const card = document.getElementById("encuesta-card");
  card.innerHTML = `
    ${index === 0 ? `<h1 class="encuesta-titulo">${escapeHTML(encuesta.titulo)}</h1>` : ""}
    ${pagina.instrucciones ? `<p class="encuesta-instrucciones">${escapeHTML(pagina.instrucciones)}</p>` : ""}
    ${index === 0 ? `<p class="encuesta-obligatorio-nota">* Obligatorio</p>` : ""}
    <div id="pagina-contenido">${bloquesHtml}</div>
    <div class="encuesta-nav">
      ${index > 0 ? `<button type="button" class="encuesta-btn secundario" id="btn-atras">Atrás</button>` : `<span></span>`}
      <div class="spacer"></div>
      <div style="text-align:right;">
        <button type="button" class="encuesta-btn" id="btn-siguiente">${esUltima ? "Enviar" : "Siguiente"}</button>
        <div class="encuesta-progreso-txt">Página ${index + 1} de ${totalPaginas}</div>
      </div>
    </div>
    <div class="encuesta-progreso-barra"><div class="encuesta-progreso-fill" style="width:${((index + 1) / totalPaginas) * 100}%"></div></div>
  `;

  card.querySelectorAll("input[type='text'], input[type='email'], input[type='number'], textarea").forEach((el) => {
    el.addEventListener("input", () => {
      respuestas[el.dataset.preguntaId] = el.value;
    });
  });
  card.querySelectorAll("input[type='radio']").forEach((el) => {
    el.addEventListener("change", () => {
      const tr = el.closest("[data-pregunta-id]");
      respuestas[tr.dataset.preguntaId] = el.value;
    });
  });

  const btnAtras = document.getElementById("btn-atras");
  if (btnAtras) btnAtras.addEventListener("click", () => {
    paginaActual--;
    renderPagina(paginaActual);
    window.scrollTo({ top: 0 });
  });
  document.getElementById("btn-siguiente").addEventListener("click", () => {
    if (!validarPagina(pagina)) return;
    if (esUltima) {
      enviarRespuestas();
    } else {
      paginaActual++;
      renderPagina(paginaActual);
      window.scrollTo({ top: 0 });
    }
  });
}

function validarPagina(pagina) {
  for (const q of pagina.preguntas) {
    if (q.obligatoria && !respuestas[q.id]) {
      alert("Por favor, responde todas las preguntas obligatorias (*) antes de continuar.");
      return false;
    }
  }
  return true;
}

async function enviarRespuestas() {
  const btn = document.getElementById("btn-siguiente");
  btn.disabled = true;
  btn.textContent = "Enviando...";
  const res = await fetch(`${API_BASE}/${encuesta.slug}/enviar`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ respuestas }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    alert(err.detail || "No se pudo enviar el formulario. Inténtalo de nuevo.");
    btn.disabled = false;
    btn.textContent = "Enviar";
    return;
  }
  document.getElementById("encuesta-card").innerHTML = `
    <div class="encuesta-final">
      <div class="icono">✅</div>
      <p>${escapeHTML(encuesta.mensaje_final)}</p>
    </div>`;
}

async function init() {
  const slug = new URLSearchParams(location.search).get("slug");
  if (!slug) {
    mostrarError("Falta el enlace de la encuesta.");
    return;
  }
  const res = await fetch(`${API_BASE}/${slug}`);
  if (!res.ok) {
    mostrarError("Esta encuesta no está disponible en este momento.");
    return;
  }
  encuesta = await res.json();
  if (!encuesta.paginas || encuesta.paginas.length === 0) {
    mostrarError("Esta encuesta todavía no tiene preguntas.");
    return;
  }
  document.title = encuesta.titulo;
  document.documentElement.style.setProperty("--color-boton", encuesta.color_boton || "#5b2a2a");
  if (encuesta.tiene_fondo) {
    document.documentElement.style.setProperty("--fondo-url", `url("${API_BASE}/${slug}/fondo")`);
    document.body.classList.add("con-fondo");
  }
  renderPagina(0);
}

document.addEventListener("DOMContentLoaded", init);

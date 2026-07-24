const API_BASE = `${window.location.origin}/api/public/encuestas`;

let encuesta = null;
let paginaActual = 0;
const respuestas = {}; // pregunta_id -> valor

// Ramificación: una página con condicion_pregunta_id solo se muestra si la
// respuesta guardada para esa pregunta (de una página anterior) está dentro
// de condicion_valores — igual que las secciones condicionales de Forms.
// Se recalcula en cada render (no se cachea) porque el candidato puede
// volver atrás y cambiar la respuesta de la que depende la ramificación.
function paginaVisible(pagina) {
  if (!pagina.condicion_pregunta_id) return true;
  const valor = respuestas[pagina.condicion_pregunta_id];
  return Array.isArray(pagina.condicion_valores) && pagina.condicion_valores.includes(valor);
}

function indicesVisibles() {
  return encuesta.paginas.map((_, i) => i).filter((i) => paginaVisible(encuesta.paginas[i]));
}

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
  if (q.tipo === "opcion_simple") {
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
  if (q.tipo === "opcion_multiple") {
    const seleccionadas = Array.isArray(respuestas[q.id]) ? respuestas[q.id] : [];
    return `<div class="pregunta-bloque" data-pregunta-id="${q.id}">
      <label class="pregunta-label">${escapeHTML(q.etiqueta)}${req}</label>
      <div class="opcion-multiple-lista">
        ${q.opciones
          .map(
            (op) => `<label><input type="checkbox" name="pregunta-${q.id}" value="${escapeHTML(op)}" ${seleccionadas.includes(op) ? "checked" : ""}> ${escapeHTML(op)}</label>`
          )
          .join("")}
      </div>
    </div>`;
  }
  if (q.tipo === "fecha") {
    return `<div class="pregunta-bloque" data-pregunta-id="${q.id}">
      <label class="pregunta-label">${escapeHTML(q.etiqueta)}${req}</label>
      <input type="date" data-pregunta-id="${q.id}" value="${escapeHTML(valorActual)}">
    </div>`;
  }
  if (q.tipo === "calificacion") {
    const valor = Number(valorActual) || 0;
    return `<div class="pregunta-bloque" data-pregunta-id="${q.id}">
      <label class="pregunta-label">${escapeHTML(q.etiqueta)}${req}</label>
      <div class="calificacion-estrellas" data-pregunta-id="${q.id}">
        ${[1, 2, 3, 4, 5]
          .map((n) => `<button type="button" class="btn-estrella ${n <= valor ? "activa" : ""}" data-valor="${n}" aria-label="${n} estrellas">★</button>`)
          .join("")}
      </div>
    </div>`;
  }
  if (q.tipo === "prioridad") {
    if (!Array.isArray(respuestas[q.id])) {
      respuestas[q.id] = [...q.opciones];
    }
    return `<div class="pregunta-bloque prioridad-bloque" data-pregunta-id="${q.id}">
      <label class="pregunta-label">${escapeHTML(q.etiqueta)}${req}</label>
      <p class="prioridad-ayuda">Ordena de mayor (arriba) a menor prioridad usando las flechas.</p>
      <ol class="prioridad-lista" data-pregunta-id="${q.id}">${renderListaPrioridadHTML(q)}</ol>
    </div>`;
  }
  return "";
}

function renderListaPrioridadHTML(q) {
  const orden = respuestas[q.id];
  return orden
    .map(
      (texto, i) => `
    <li class="prioridad-item">
      <span class="prioridad-num">${i + 1}</span>
      <span class="prioridad-texto">${escapeHTML(texto)}</span>
      <span class="prioridad-flechas">
        <button type="button" class="btn-prioridad-subir" data-idx="${i}" ${i === 0 ? "disabled" : ""} aria-label="Subir prioridad">↑</button>
        <button type="button" class="btn-prioridad-bajar" data-idx="${i}" ${i === orden.length - 1 ? "disabled" : ""} aria-label="Bajar prioridad">↓</button>
      </span>
    </li>`
    )
    .join("");
}

function bindPrioridadBotones(ol) {
  ol.querySelectorAll(".btn-prioridad-subir").forEach((btn) => {
    btn.addEventListener("click", () => moverPrioridad(ol, Number(btn.dataset.idx), -1));
  });
  ol.querySelectorAll(".btn-prioridad-bajar").forEach((btn) => {
    btn.addEventListener("click", () => moverPrioridad(ol, Number(btn.dataset.idx), 1));
  });
}

function moverPrioridad(ol, idx, direccion) {
  const qid = ol.dataset.preguntaId;
  const orden = respuestas[qid];
  const j = idx + direccion;
  if (j < 0 || j >= orden.length) return;
  [orden[idx], orden[j]] = [orden[j], orden[idx]];
  ol.innerHTML = renderListaPrioridadHTML({ id: qid });
  bindPrioridadBotones(ol);
}

// Las preguntas de escala guardan la etiqueta completa "Categoria.Pregunta"
// (KK) o "Preámbulo: [Pregunta]" (Saona) porque entrevistas.py necesita ese
// formato exacto para agrupar por bloque en el informe — pero mostrarla tal
// cual en cada fila de la tabla repite el nombre del bloque en todas las
// preguntas. Aquí se deriva solo la parte "pregunta" para el candidato; lo
// que se envía al guardar sigue siendo el valor de la escala, no el texto.
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

const LIKERT_OPCIONES_DEFAULT = [
  "Totalmente en desacuerdo", "En desacuerdo", "Ni de acuerdo ni en desacuerdo", "De acuerdo", "Totalmente de acuerdo",
];

function renderGrupoLikert(preguntas) {
  // El puntaje enviado es SIEMPRE la posición ORIGINAL en `escala` (1-5),
  // nunca el texto de la leyenda — así cada pregunta de escala puede tener
  // sus propias etiquetas sin arriesgar la puntuación. Todas las preguntas
  // del grupo comparten la escala de la primera (es una sola tabla con un
  // encabezado compartido).
  const escala = preguntas[0].opciones && preguntas[0].opciones.length === 5 ? preguntas[0].opciones : LIKERT_OPCIONES_DEFAULT;
  // Orden visual: "Totalmente de acuerdo" a la izquierda, "Totalmente en
  // desacuerdo" a la derecha (ley general para todos los Likert) — se
  // invierte solo el ORDEN DE PINTADO de las columnas, nunca el valor que
  // viaja en cada radio (sigue siendo la posición original +1), para no
  // romper la puntuación ya calculada sobre respuestas anteriores a este
  // cambio.
  const ordenVisual = escala.map((_, i) => i).reverse();
  const filas = preguntas
    .map(
      (q) => `
    <tr data-pregunta-id="${q.id}">
      <td class="likert-etiqueta">${escapeHTML(etiquetaVisible(q))}${q.obligatoria ? ' <span class="req">*</span>' : ""}</td>
      ${ordenVisual.map(
        (i) => `<td><input type="radio" name="pregunta-${q.id}" value="${i + 1}" ${respuestas[q.id] === String(i + 1) ? "checked" : ""}></td>`
      ).join("")}
    </tr>`
    )
    .join("");
  return `
    <div class="likert-tabla-wrap">
      <table class="likert-tabla">
        <thead><tr><th></th>${ordenVisual.map((i) => `<th>${escapeHTML(escala[i])}</th>`).join("")}</tr></thead>
        <tbody>${filas}</tbody>
      </table>
    </div>`;
}

function renderPagina(index) {
  const pagina = encuesta.paginas[index];
  const visibles = indicesVisibles();
  const posActual = visibles.indexOf(index);
  const totalPaginas = visibles.length;
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

  const esUltima = posActual === totalPaginas - 1;
  const card = document.getElementById("encuesta-card");
  card.innerHTML = `
    ${index === 0 ? `<h1 class="encuesta-titulo">${escapeHTML(encuesta.titulo)}</h1>` : ""}
    ${pagina.instrucciones ? `<p class="encuesta-instrucciones">${escapeHTML(pagina.instrucciones)}</p>` : ""}
    ${index === 0 ? `<p class="encuesta-obligatorio-nota">* Obligatorio</p>` : ""}
    <div id="pagina-contenido">${bloquesHtml}</div>
    <div class="encuesta-nav">
      ${posActual > 0 ? `<button type="button" class="encuesta-btn secundario" id="btn-atras">Atrás</button>` : `<span></span>`}
      <div class="spacer"></div>
      <div style="text-align:right;">
        <button type="button" class="encuesta-btn" id="btn-siguiente">${esUltima ? "Enviar" : "Siguiente"}</button>
        <div class="encuesta-progreso-txt">Página ${posActual + 1} de ${totalPaginas}</div>
      </div>
    </div>
    <div class="encuesta-progreso-barra"><div class="encuesta-progreso-fill" style="width:${((posActual + 1) / totalPaginas) * 100}%"></div></div>
  `;

  card.querySelectorAll("input[type='text'], input[type='email'], input[type='number'], input[type='date'], textarea").forEach((el) => {
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
  card.querySelectorAll("input[type='checkbox']").forEach((el) => {
    el.addEventListener("change", () => {
      const bloque = el.closest("[data-pregunta-id]");
      const qid = bloque.dataset.preguntaId;
      const marcadas = Array.from(bloque.querySelectorAll("input[type='checkbox']:checked")).map((c) => c.value);
      respuestas[qid] = marcadas;
    });
  });
  card.querySelectorAll(".prioridad-lista").forEach((ol) => bindPrioridadBotones(ol));
  card.querySelectorAll(".calificacion-estrellas").forEach((wrap) => {
    wrap.querySelectorAll(".btn-estrella").forEach((btn) => {
      btn.addEventListener("click", () => {
        respuestas[wrap.dataset.preguntaId] = btn.dataset.valor;
        wrap.querySelectorAll(".btn-estrella").forEach((b) => {
          b.classList.toggle("activa", Number(b.dataset.valor) <= Number(btn.dataset.valor));
        });
      });
    });
  });

  const btnAtras = document.getElementById("btn-atras");
  if (btnAtras) btnAtras.addEventListener("click", () => {
    paginaActual = visibles[posActual - 1];
    renderPagina(paginaActual);
    window.scrollTo({ top: 0 });
  });
  document.getElementById("btn-siguiente").addEventListener("click", () => {
    if (!validarPagina(pagina)) return;
    if (esUltima) {
      enviarRespuestas();
    } else {
      // Se recalcula aquí (no se reutiliza "visibles") porque la respuesta
      // que se acaba de validar en esta misma página puede ser justo la que
      // decide qué página de ramificación toca mostrar a continuación.
      paginaActual = indicesVisibles()[posActual + 1];
      renderPagina(paginaActual);
      window.scrollTo({ top: 0 });
    }
  });
}

function validarPagina(pagina) {
  for (const q of pagina.preguntas) {
    const valor = respuestas[q.id];
    const sinResponder = Array.isArray(valor) && q.tipo !== "prioridad" ? valor.length === 0 : !valor;
    if (q.obligatoria && sinResponder) {
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
  const respuestasPlano = {};
  for (const [k, v] of Object.entries(respuestas)) {
    respuestasPlano[k] = Array.isArray(v) ? v.join(";") : v;
  }
  const res = await fetch(`${API_BASE}/${encuesta.slug}/enviar`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ respuestas: respuestasPlano }),
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

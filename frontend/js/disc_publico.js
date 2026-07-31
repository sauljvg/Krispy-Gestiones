const LETRAS_DISC_PUB = ["D", "I", "S", "C"];
const ICONO_FLECHA_ARRIBA_PUB = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="18 15 12 9 6 15"></polyline></svg>`;
const ICONO_FLECHA_ABAJO_PUB = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>`;
let PREGUNTAS_DISC_PUB = [];
let respondidasPub = new Set();

function escapeHTML(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

function shuffle(arr) {
  const a = arr.slice();
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

function leerRespuestasActualesPub() {
  return [...document.querySelectorAll(".disc-pub-opciones")].map((ul) =>
    [...ul.querySelectorAll("li")].map((li) => li.dataset.letra)
  );
}

function renderPreguntasPub() {
  const wrap = document.getElementById("disc-pub-preguntas-wrap");
  wrap.innerHTML = PREGUNTAS_DISC_PUB.map((p, i) => {
    const opciones = shuffle(LETRAS_DISC_PUB.map((letra) => ({ letra, texto: p[letra] })));
    const lis = opciones
      .map(
        (o) => `
      <li draggable="true" data-letra="${o.letra}">
        <span class="disc-pub-rank-badge"></span>
        <span class="disc-pub-opcion-texto">${escapeHTML(o.texto)}</span>
        <span class="disc-pub-opcion-flechas">
          <button type="button" class="btn-flecha-arriba-pub" aria-label="Subir">${ICONO_FLECHA_ARRIBA_PUB}</button>
          <button type="button" class="btn-flecha-abajo-pub" aria-label="Bajar">${ICONO_FLECHA_ABAJO_PUB}</button>
        </span>
      </li>`
      )
      .join("");
    return `
    <div class="disc-pub-pregunta" id="disc-pub-pregunta-${i}">
      <div class="disc-pub-pregunta-num">Pregunta ${i + 1} / ${PREGUNTAS_DISC_PUB.length}</div>
      <p class="disc-pub-hint">Ordena arrastrando o con las flechas: arriba = lo que más te describe, abajo = lo que menos.</p>
      <ul class="disc-pub-opciones" data-q="${i}">${lis}</ul>
    </div>`;
  }).join("");

  wrap.querySelectorAll(".disc-pub-opciones").forEach((ul) => {
    actualizarBadgesPub(ul);
    habilitarDragDropPub(ul);
    habilitarFlechasPub(ul);
    actualizarFlechasDisabledPub(ul);
  });
}

function habilitarFlechasPub(ul) {
  ul.querySelectorAll(".btn-flecha-arriba-pub").forEach((btn) => {
    btn.addEventListener("click", () => moverOpcionPub(btn.closest("li"), -1, ul));
  });
  ul.querySelectorAll(".btn-flecha-abajo-pub").forEach((btn) => {
    btn.addEventListener("click", () => moverOpcionPub(btn.closest("li"), 1, ul));
  });
}

function moverOpcionPub(li, direccion, ul) {
  const hermano = direccion === -1 ? li.previousElementSibling : li.nextElementSibling;
  if (!hermano) return;
  if (direccion === -1) ul.insertBefore(li, hermano);
  else ul.insertBefore(hermano, li);
  actualizarBadgesPub(ul);
  actualizarFlechasDisabledPub(ul);
  marcarRespondidaPub(ul);
}

function actualizarFlechasDisabledPub(ul) {
  const lis = [...ul.querySelectorAll("li")];
  lis.forEach((li, i) => {
    li.querySelector(".btn-flecha-arriba-pub").disabled = i === 0;
    li.querySelector(".btn-flecha-abajo-pub").disabled = i === lis.length - 1;
  });
}

function habilitarDragDropPub(ul) {
  ul.querySelectorAll("li").forEach((li) => {
    li.addEventListener("dragstart", () => li.classList.add("dragging"));
    li.addEventListener("dragend", () => {
      li.classList.remove("dragging");
      actualizarBadgesPub(ul);
      actualizarFlechasDisabledPub(ul);
      marcarRespondidaPub(ul);
    });
  });
  ul.addEventListener("dragover", (e) => {
    e.preventDefault();
    const dragging = ul.querySelector(".dragging");
    if (!dragging) return;
    const after = elementoTrasCursorPub(ul, e.clientY);
    if (after == null) ul.appendChild(dragging);
    else ul.insertBefore(dragging, after);
  });
}

function elementoTrasCursorPub(container, y) {
  const els = [...container.querySelectorAll("li:not(.dragging)")];
  return els.reduce(
    (closest, child) => {
      const box = child.getBoundingClientRect();
      const offset = y - box.top - box.height / 2;
      if (offset < 0 && offset > closest.offset) return { offset, element: child };
      return closest;
    },
    { offset: Number.NEGATIVE_INFINITY, element: null }
  ).element;
}

function actualizarBadgesPub(ul) {
  ul.querySelectorAll("li").forEach((li, i) => {
    li.querySelector(".disc-pub-rank-badge").textContent = i + 1;
  });
}

function marcarRespondidaPub(ul) {
  const idx = Number(ul.dataset.q);
  respondidasPub.add(idx);
  document.getElementById(`disc-pub-pregunta-${idx}`).classList.add("respondida");
  actualizarProgresoPub();
}

function actualizarProgresoPub() {
  document.getElementById("disc-pub-progreso").textContent = `${respondidasPub.size} / ${PREGUNTAS_DISC_PUB.length} respondidas`;
  const nombreOk = document.getElementById("input-nombre-pub").value.trim().length > 0;
  document.getElementById("btn-enviar-pub").disabled = !(nombreOk && respondidasPub.size === PREGUNTAS_DISC_PUB.length);
}

async function enviarRespuestasPub() {
  const nombre = document.getElementById("input-nombre-pub").value.trim();
  const respuestas = leerRespuestasActualesPub();
  const btn = document.getElementById("btn-enviar-pub");
  const errorEl = document.getElementById("disc-pub-error");
  errorEl.hidden = true;
  btn.disabled = true;
  btn.textContent = "Enviando...";
  try {
    const res = await fetch("/api/public/disc/calcular", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nombre, respuestas }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      errorEl.textContent = err.detail || "No se pudieron enviar las respuestas. Inténtalo de nuevo.";
      errorEl.hidden = false;
      btn.disabled = false;
      btn.textContent = "Enviar respuestas";
      return;
    }
    document.getElementById("vista-formulario").hidden = true;
    document.getElementById("vista-gracias").hidden = false;
    window.scrollTo({ top: 0, behavior: "smooth" });
  } catch {
    errorEl.textContent = "No se pudo conectar con el servidor. Comprueba tu conexión e inténtalo de nuevo.";
    errorEl.hidden = false;
    btn.disabled = false;
    btn.textContent = "Enviar respuestas";
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  const res = await fetch("/api/public/disc/preguntas");
  PREGUNTAS_DISC_PUB = await res.json();
  renderPreguntasPub();
  actualizarProgresoPub();

  document.getElementById("input-nombre-pub").addEventListener("input", actualizarProgresoPub);
  document.getElementById("btn-enviar-pub").addEventListener("click", enviarRespuestasPub);
});

// Manuales/instrucciones paso a paso -- catálogo agrupado por categoría +
// visor de un manual a la vez (una captura grande + una frase corta por
// paso, con Anterior/Siguiente, en vez de un documento largo para leer de
// corrido). Edición (crear/editar/eliminar manuales y pasos) solo para
// admin -- ver backend/manuales_routes.py.

let usuarioActual = null;
let manualesCache = [];
let pictogramasCache = {}; // { clave: "🖱️ Clic", ... }
let currentManual = null; // manual completo (con .pasos) actualmente abierto
let currentPasoIdx = 0;
let nuevoPasoMarca = null; // {x, y} fracciones 0-1, o null si no se marcó nada
let pasoMarcandoId = null; // id del paso existente que se está marcando ahora mismo (o null)

// Traduce un clic sobre la imagen a fracciones (x, y) 0-1 del tamaño
// RENDERIZADO de la imagen -- válido igual aunque la imagen se muestre más
// pequeña que su tamaño real, porque la marca se guarda como fracción, no
// en píxeles absolutos.
function clicAFraccion(e, imgEl) {
  const rect = imgEl.getBoundingClientRect();
  const x = (e.clientX - rect.left) / rect.width;
  const y = (e.clientY - rect.top) / rect.height;
  return { x: Math.min(1, Math.max(0, x)), y: Math.min(1, Math.max(0, y)) };
}

function mostrarPunto(puntoEl, x, y) {
  puntoEl.style.left = `${x * 100}%`;
  puntoEl.style.top = `${y * 100}%`;
  puntoEl.hidden = false;
}

function esAdmin() {
  return usuarioActual?.rol === "admin";
}

// ---------------------------------------------------------------- Catálogo

async function cargarCatalogo() {
  manualesCache = await fetch(`${AUTH_API_BASE}/manuales`).then((r) => (r.ok ? r.json() : []));
  renderCatalogo();
}

function manualCardHTML(m) {
  const portada = m.portada_paso_id
    ? `<img src="${AUTH_API_BASE}/manuales/${m.id}/pasos/${m.portada_paso_id}/imagen" alt="" loading="lazy">`
    : `<span class="sin-portada">📘</span>`;
  return `
    <div class="manual-card" data-manual-id="${m.id}">
      <div class="manual-card-portada">${portada}</div>
      <div class="manual-card-info">
        <h3>${escapeHTML(m.titulo)}</h3>
        <p>${m.pasos_count} paso${m.pasos_count === 1 ? "" : "s"}</p>
      </div>
    </div>`;
}

function renderCatalogo() {
  const cont = document.getElementById("catalogo-contenido");
  if (manualesCache.length === 0) {
    cont.innerHTML = `<p class="manuales-vacio">Todavía no hay manuales publicados.</p>`;
    return;
  }
  const grupos = new Map();
  for (const m of manualesCache) {
    const clave = m.categoria || "General";
    if (!grupos.has(clave)) grupos.set(clave, []);
    grupos.get(clave).push(m);
  }
  cont.innerHTML = [...grupos.entries()]
    .map(
      ([categoria, manuales]) => `
      <div class="categoria-grupo">
        <h2 class="categoria-titulo">${escapeHTML(categoria)}</h2>
        <div class="manuales-grid">${manuales.map(manualCardHTML).join("")}</div>
      </div>`
    )
    .join("");
  cont.querySelectorAll(".manual-card").forEach((card) => {
    card.addEventListener("click", () => abrirManual(Number(card.dataset.manualId)));
  });
}

// ------------------------------------------------------------ Ver manual

function mostrarVista(vista) {
  document.getElementById("catalogo-view").hidden = vista !== "catalogo";
  document.getElementById("manual-view").hidden = vista !== "manual";
}

async function abrirManual(id) {
  const manual = await fetch(`${AUTH_API_BASE}/manuales/${id}`).then((r) => (r.ok ? r.json() : null));
  if (!manual) {
    mostrarAviso("No se pudo abrir este manual.");
    return;
  }
  currentManual = manual;
  currentPasoIdx = 0;
  document.getElementById("manual-editor").hidden = true;
  document.getElementById("manual-titulo").textContent = manual.titulo;
  document.getElementById("manual-categoria").textContent = manual.categoria;
  mostrarVista("manual");
  renderPaso();
  history.replaceState(null, "", `manuales.html?id=${id}`);
}

function volverAlCatalogo() {
  currentManual = null;
  mostrarVista("catalogo");
  history.replaceState(null, "", "manuales.html");
  cargarCatalogo();
}

function renderPaso() {
  const pasos = currentManual.pasos;
  const btnAnterior = document.getElementById("btn-paso-anterior");
  const btnSiguiente = document.getElementById("btn-paso-siguiente");
  const contador = document.getElementById("paso-contador");
  const dotsWrap = document.getElementById("paso-dots");
  const imgEl = document.getElementById("paso-imagen");
  const sinImgEl = document.getElementById("paso-sin-imagen");
  const textoEl = document.getElementById("paso-texto");
  const pictoEl = document.getElementById("paso-pictograma");

  if (pasos.length === 0) {
    contador.textContent = "";
    dotsWrap.innerHTML = "";
    imgEl.hidden = true;
    sinImgEl.hidden = false;
    textoEl.textContent = esAdmin() ? "Este manual todavía no tiene pasos -- añade el primero abajo." : "Este manual todavía no tiene pasos.";
    pictoEl.hidden = true;
    btnAnterior.disabled = true;
    btnSiguiente.disabled = true;
    return;
  }

  const paso = pasos[currentPasoIdx];
  if (paso.tiene_imagen) {
    imgEl.src = `${AUTH_API_BASE}/manuales/${currentManual.id}/pasos/${paso.id}/imagen`;
    imgEl.hidden = false;
    sinImgEl.hidden = true;
  } else {
    imgEl.hidden = true;
    sinImgEl.hidden = false;
  }
  textoEl.textContent = paso.texto || "";
  if (paso.pictograma && pictogramasCache[paso.pictograma]) {
    pictoEl.textContent = pictogramasCache[paso.pictograma];
    pictoEl.hidden = false;
  } else {
    pictoEl.hidden = true;
  }
  contador.textContent = `Paso ${currentPasoIdx + 1} de ${pasos.length}`;
  btnAnterior.disabled = currentPasoIdx === 0;
  btnSiguiente.disabled = currentPasoIdx === pasos.length - 1;
  dotsWrap.innerHTML = pasos
    .map((_, i) => `<button type="button" class="paso-dot ${i === currentPasoIdx ? "activo" : ""}" data-idx="${i}" aria-label="Ir al paso ${i + 1}"></button>`)
    .join("");
  dotsWrap.querySelectorAll(".paso-dot").forEach((dot) => {
    dot.addEventListener("click", () => {
      currentPasoIdx = Number(dot.dataset.idx);
      renderPaso();
    });
  });

  if (esAdmin()) renderPasosAdminLista();
}

// --------------------------------------------------------- Edición (admin)

function renderPasosAdminLista() {
  const lista = document.getElementById("pasos-admin-lista");
  const pasos = currentManual.pasos;
  lista.innerHTML = pasos
    .map((p, i) => {
      const miniatura = p.tiene_imagen
        ? `<img src="${AUTH_API_BASE}/manuales/${currentManual.id}/pasos/${p.id}/imagen" alt="">`
        : `<span class="sin-imagen-mini">🖼️</span>`;
      return `
      <li data-paso-id="${p.id}">
        ${miniatura}
        <span class="paso-admin-texto">${escapeHTML(p.texto || "(sin texto)")}</span>
        <button type="button" class="btn-mini btn-paso-subir" title="Subir" ${i === 0 ? "disabled" : ""}>↑</button>
        <button type="button" class="btn-mini btn-paso-bajar" title="Bajar" ${i === pasos.length - 1 ? "disabled" : ""}>↓</button>
        ${p.tiene_imagen ? `<button type="button" class="btn-mini btn-paso-marcar" title="Marcar dónde mirar">${p.tiene_marca ? "🎯" : "⭕"}</button>` : ""}
        <button type="button" class="btn-mini btn-paso-eliminar" title="Eliminar paso">🗑</button>
      </li>`;
    })
    .join("");
  lista.querySelectorAll(".btn-paso-subir").forEach((btn) => {
    btn.addEventListener("click", (e) => moverPaso(Number(e.target.closest("li").dataset.pasoId), "arriba"));
  });
  lista.querySelectorAll(".btn-paso-bajar").forEach((btn) => {
    btn.addEventListener("click", (e) => moverPaso(Number(e.target.closest("li").dataset.pasoId), "abajo"));
  });
  lista.querySelectorAll(".btn-paso-eliminar").forEach((btn) => {
    btn.addEventListener("click", (e) => eliminarPaso(Number(e.target.closest("li").dataset.pasoId)));
  });
  lista.querySelectorAll(".btn-paso-marcar").forEach((btn) => {
    btn.addEventListener("click", (e) => abrirMarcaPasoExistente(Number(e.target.closest("li").dataset.pasoId)));
  });
}

// -------------------------------------------------- Marcar paso existente

function abrirMarcaPasoExistente(pasoId) {
  pasoMarcandoId = pasoId;
  const wrap = document.getElementById("marca-paso-existente-wrap");
  const img = document.getElementById("marca-existente-imagen");
  const punto = document.getElementById("marca-existente-punto");
  const paso = currentManual.pasos.find((p) => p.id === pasoId);
  img.src = `${AUTH_API_BASE}/manuales/${currentManual.id}/pasos/${pasoId}/imagen-original`;
  punto.hidden = !paso.tiene_marca;
  wrap.hidden = false;
  wrap.scrollIntoView({ behavior: "smooth", block: "center" });
}

async function guardarMarcaExistente(x, y) {
  const radio = Number(document.getElementById("marca-existente-radio").value);
  await fetch(`${AUTH_API_BASE}/manuales/${currentManual.id}/pasos/${pasoMarcandoId}/marca`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ x, y, radio }),
  });
  await recargarManualActual(true);
  abrirMarcaPasoExistente(pasoMarcandoId); // vuelve a abrir el mismo paso, ya con el punto puesto
}

async function quitarMarcaExistente() {
  await fetch(`${AUTH_API_BASE}/manuales/${currentManual.id}/pasos/${pasoMarcandoId}/marca`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ x: null, y: null }),
  });
  document.getElementById("marca-existente-punto").hidden = true;
  await recargarManualActual(true);
}

async function recargarManualActual(mantenerIdx) {
  const idxPrevio = mantenerIdx ? currentPasoIdx : 0;
  const manual = await fetch(`${AUTH_API_BASE}/manuales/${currentManual.id}`).then((r) => r.json());
  currentManual = manual;
  currentPasoIdx = Math.min(idxPrevio, Math.max(0, manual.pasos.length - 1));
  renderPaso();
}

async function moverPaso(pasoId, direccion) {
  await fetch(`${AUTH_API_BASE}/manuales/${currentManual.id}/pasos/${pasoId}/mover`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ direccion }),
  });
  await recargarManualActual(true);
}

async function eliminarPaso(pasoId) {
  if (!(await pedirConfirmacion("¿Eliminar este paso? No se puede deshacer."))) return;
  await fetch(`${AUTH_API_BASE}/manuales/${currentManual.id}/pasos/${pasoId}`, { method: "DELETE" });
  await recargarManualActual(false);
}

async function agregarPaso() {
  const fileInput = document.getElementById("nuevo-paso-imagen");
  const pictograma = document.getElementById("nuevo-paso-pictograma").value;
  const texto = document.getElementById("nuevo-paso-texto").value.trim();
  if (!texto && !fileInput.files[0]) {
    mostrarAviso("Escribe una frase o sube una captura -- al menos uno de los dos.");
    return;
  }
  const formData = new FormData();
  formData.append("texto", texto);
  if (pictograma) formData.append("pictograma", pictograma);
  if (fileInput.files[0]) formData.append("file", fileInput.files[0]);
  if (nuevoPasoMarca) {
    formData.append("marca_x", nuevoPasoMarca.x);
    formData.append("marca_y", nuevoPasoMarca.y);
    formData.append("marca_radio", document.getElementById("nuevo-paso-marca-radio").value);
  }
  const res = await fetch(`${AUTH_API_BASE}/manuales/${currentManual.id}/pasos`, { method: "POST", body: formData });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    mostrarAviso(err.detail || "No se pudo añadir el paso.");
    return;
  }
  fileInput.value = "";
  document.getElementById("nuevo-paso-pictograma").value = "";
  document.getElementById("nuevo-paso-texto").value = "";
  document.getElementById("nuevo-paso-marcar-wrap").hidden = true;
  document.getElementById("nuevo-paso-marca-punto").hidden = true;
  nuevoPasoMarca = null;
  const manual = await fetch(`${AUTH_API_BASE}/manuales/${currentManual.id}`).then((r) => r.json());
  currentManual = manual;
  currentPasoIdx = manual.pasos.length - 1; // salta al paso recién creado
  renderPaso();
}

async function guardarManual() {
  const titulo = document.getElementById("editor-titulo").value.trim();
  const categoria = document.getElementById("editor-categoria").value.trim();
  if (!titulo) {
    mostrarAviso("El título es obligatorio.");
    return;
  }
  const res = await fetch(`${AUTH_API_BASE}/manuales/${currentManual.id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ titulo, categoria: categoria || "General" }),
  });
  if (!res.ok) {
    mostrarAviso("No se pudo guardar.");
    return;
  }
  currentManual.titulo = titulo;
  currentManual.categoria = categoria || "General";
  document.getElementById("manual-titulo").textContent = currentManual.titulo;
  document.getElementById("manual-categoria").textContent = currentManual.categoria;
}

async function eliminarManualActual() {
  if (!(await pedirConfirmacion(`¿Eliminar por completo el manual "${currentManual.titulo}"? Se borran todos sus pasos y capturas. No se puede deshacer.`))) return;
  await fetch(`${AUTH_API_BASE}/manuales/${currentManual.id}`, { method: "DELETE" });
  volverAlCatalogo();
}

async function crearManual() {
  const titulo = await pedirTexto("Título del nuevo manual:");
  if (!titulo || !titulo.trim()) return;
  const categoria = await pedirTexto("Categoría (p.ej. Odoo, Reseñas...):", "General");
  const res = await fetch(`${AUTH_API_BASE}/manuales`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ titulo: titulo.trim(), categoria: (categoria || "General").trim() }),
  });
  if (!res.ok) {
    mostrarAviso("No se pudo crear el manual.");
    return;
  }
  const { id } = await res.json();
  await abrirManual(id);
  abrirEditor();
}

function abrirEditor() {
  document.getElementById("editor-titulo").value = currentManual.titulo;
  document.getElementById("editor-categoria").value = currentManual.categoria;
  document.getElementById("manual-editor").hidden = false;
  document.getElementById("marca-paso-existente-wrap").hidden = true;
  pasoMarcandoId = null;
  renderPasosAdminLista();
}

// ---------------------------------------------------------------- Init

document.addEventListener("DOMContentLoaded", async () => {
  const user = await checkAuth("/manuales.html");
  if (!user) return;
  if (!(user.modulos || []).includes("manuales")) {
    window.location.href = "/";
    return;
  }
  usuarioActual = user;
  wireUserBar(user);

  pictogramasCache = await fetch(`${AUTH_API_BASE}/manuales/pictogramas`).then((r) => (r.ok ? r.json() : {}));
  const selectPictograma = document.getElementById("nuevo-paso-pictograma");
  Object.entries(pictogramasCache).forEach(([clave, etiqueta]) => {
    selectPictograma.insertAdjacentHTML("beforeend", `<option value="${clave}">${escapeHTML(etiqueta)}</option>`);
  });

  if (esAdmin()) {
    document.getElementById("btn-nuevo-manual").hidden = false;
    document.getElementById("btn-editar-manual").hidden = false;
  }

  document.getElementById("btn-nuevo-manual").addEventListener("click", crearManual);
  document.getElementById("btn-volver-catalogo").addEventListener("click", volverAlCatalogo);
  document.getElementById("btn-editar-manual").addEventListener("click", () => {
    const editor = document.getElementById("manual-editor");
    if (editor.hidden) abrirEditor();
    else editor.hidden = true;
  });
  document.getElementById("btn-guardar-manual").addEventListener("click", guardarManual);
  document.getElementById("btn-eliminar-manual").addEventListener("click", eliminarManualActual);
  document.getElementById("btn-agregar-paso").addEventListener("click", agregarPaso);

  // Vista previa + marcado del "spotlight" para un paso NUEVO (aún sin
  // crear en el servidor -- la marca se guarda junto con el paso al pulsar
  // "＋ Añadir paso", ver agregarPaso).
  document.getElementById("nuevo-paso-imagen").addEventListener("change", (e) => {
    const file = e.target.files[0];
    const wrap = document.getElementById("nuevo-paso-marcar-wrap");
    const img = document.getElementById("nuevo-paso-marcar-imagen");
    nuevoPasoMarca = null;
    document.getElementById("nuevo-paso-marca-punto").hidden = true;
    if (!file) { wrap.hidden = true; return; }
    img.src = URL.createObjectURL(file);
    wrap.hidden = false;
  });
  document.getElementById("nuevo-paso-marcar-imagen-wrap").addEventListener("click", (e) => {
    const img = document.getElementById("nuevo-paso-marcar-imagen");
    nuevoPasoMarca = clicAFraccion(e, img);
    mostrarPunto(document.getElementById("nuevo-paso-marca-punto"), nuevoPasoMarca.x, nuevoPasoMarca.y);
    document.getElementById("btn-nuevo-paso-quitar-marca").hidden = false;
  });
  document.getElementById("btn-nuevo-paso-quitar-marca").addEventListener("click", () => {
    nuevoPasoMarca = null;
    document.getElementById("nuevo-paso-marca-punto").hidden = true;
    document.getElementById("btn-nuevo-paso-quitar-marca").hidden = true;
  });

  // Marcado de un paso YA EXISTENTE -- cada clic guarda al instante (ver
  // guardarMarcaExistente), no hace falta un botón "Guardar" aparte.
  document.getElementById("marca-existente-imagen-wrap").addEventListener("click", (e) => {
    const img = document.getElementById("marca-existente-imagen");
    const { x, y } = clicAFraccion(e, img);
    mostrarPunto(document.getElementById("marca-existente-punto"), x, y);
    guardarMarcaExistente(x, y);
  });
  document.getElementById("btn-marca-existente-quitar").addEventListener("click", quitarMarcaExistente);
  document.getElementById("btn-marca-existente-cerrar").addEventListener("click", () => {
    document.getElementById("marca-paso-existente-wrap").hidden = true;
    pasoMarcandoId = null;
  });

  document.getElementById("btn-paso-anterior").addEventListener("click", () => {
    if (currentPasoIdx > 0) { currentPasoIdx--; renderPaso(); }
  });
  document.getElementById("btn-paso-siguiente").addEventListener("click", () => {
    if (currentPasoIdx < currentManual.pasos.length - 1) { currentPasoIdx++; renderPaso(); }
  });
  document.addEventListener("keydown", (e) => {
    if (document.getElementById("manual-view").hidden) return;
    if (document.activeElement && ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)) return;
    if (e.key === "ArrowLeft") document.getElementById("btn-paso-anterior").click();
    if (e.key === "ArrowRight") document.getElementById("btn-paso-siguiente").click();
  });

  const idParam = new URLSearchParams(location.search).get("id");
  if (idParam) {
    await abrirManual(Number(idParam));
  } else {
    await cargarCatalogo();
  }
});

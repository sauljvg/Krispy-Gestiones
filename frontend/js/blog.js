const API_BASE = `${window.location.origin}/api/public/boletines`;

if (window.pdfjsLib) {
  window.pdfjsLib.GlobalWorkerOptions.workerSrc = "js/vendor/pdf.worker.min.js";
}

let todosPosts = [];
let ordenDescendente = true; // true = más recientes primero
let postIdActual = null; // null = viendo la lista
let indiceObserver = null;
let revealObserver = null;
let pdfRenderToken = 0; // se incrementa en cada mostrarPost para descartar renders de posts abandonados

function quitarIndiceCapitulos() {
  if (indiceObserver) { indiceObserver.disconnect(); indiceObserver = null; }
  const existente = document.getElementById("blog-indice-capitulos");
  if (existente) existente.remove();
}

// Construye el índice flotante a partir de los divisores de departamento
// ("capitulo" en boletin-builder.js), que llegan en el HTML como
// <div id="cap-N" data-capitulo-titulo="MARKETING">. Con 0 o 1 no compensa
// mostrar el índice.
function montarIndiceCapitulos(postEl) {
  quitarIndiceCapitulos();
  const capitulos = [...postEl.querySelectorAll(".contenido [data-capitulo-titulo]")];
  if (capitulos.length < 2) return;

  const nav = document.createElement("div");
  nav.id = "blog-indice-capitulos";
  nav.className = "blog-indice-capitulos";
  nav.innerHTML = `
    <div class="blog-indice-panel">
      ${capitulos.map((el) => `<a href="#${el.id}" data-ir="${el.id}">${escapeHTML(el.dataset.capituloTitulo)}</a>`).join("")}
    </div>
    <button type="button" class="blog-indice-toggle" title="Ir a una sección" aria-label="Ir a una sección">☰</button>
  `;
  document.body.appendChild(nav);

  nav.querySelector(".blog-indice-toggle").addEventListener("click", () => nav.classList.toggle("abierto"));
  nav.querySelectorAll("[data-ir]").forEach((a) => {
    a.addEventListener("click", (e) => {
      e.preventDefault();
      const destino = document.getElementById(a.dataset.ir);
      if (destino) destino.scrollIntoView({ behavior: "smooth", block: "start" });
      nav.classList.remove("abierto");
    });
  });

  indiceObserver = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return;
      nav.querySelectorAll("[data-ir]").forEach((a) => a.classList.toggle("activo", a.dataset.ir === entry.target.id));
    });
  }, { rootMargin: "-35% 0px -55% 0px" });
  capitulos.forEach((el) => indiceObserver.observe(el));
}

// Cada bloque del boletín entra con un fade/slide al llegar a la vista —
// solo en esta página; el HTML que se manda por email no ejecuta JS/CSS de
// ningún cliente de correo, así que ahí siempre se ve todo directamente.
function activarAnimacionesScroll(postEl) {
  if (revealObserver) { revealObserver.disconnect(); revealObserver = null; }
  const contenedor = postEl.querySelector(".contenido > div");
  if (!contenedor) return;
  const hijos = [...contenedor.children];
  if (hijos.length === 0) return;
  hijos.forEach((el) => el.classList.add("blog-reveal"));
  revealObserver = new IntersectionObserver((entries, obs) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return;
      entry.target.classList.add("blog-reveal-visible");
      obs.unobserve(entry.target);
    });
  }, { threshold: 0.12 });
  hijos.forEach((el) => revealObserver.observe(el));
}

// Renderiza cada página del PDF como <canvas> dentro de la página, en vez de
// un visor embebido en iframe — así el scroll es el scroll normal de la
// página web (funciona igual en móvil, donde el visor nativo anidado en un
// iframe solo dejaba ver la primera página).
async function renderPdfInline(url, contenedor) {
  const miToken = ++pdfRenderToken;
  if (!window.pdfjsLib) {
    contenedor.innerHTML = `<p class="blog-pdf-error">No se pudo cargar el visor de documentos. <a href="${url}" target="_blank" rel="noopener">Abrir el PDF en una pestaña nueva</a>.</p>`;
    return;
  }
  contenedor.innerHTML = `<p class="blog-pdf-cargando">Cargando documento…</p>`;
  try {
    const pdf = await window.pdfjsLib.getDocument(url).promise;
    if (miToken !== pdfRenderToken) return;
    contenedor.innerHTML = "";
    const anchoDisponible = contenedor.clientWidth || 600;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    for (let num = 1; num <= pdf.numPages; num++) {
      const page = await pdf.getPage(num);
      if (miToken !== pdfRenderToken) return;
      const viewportBase = page.getViewport({ scale: 1 });
      const escala = anchoDisponible / viewportBase.width;
      const viewport = page.getViewport({ scale: escala * dpr });
      const canvas = document.createElement("canvas");
      canvas.className = "blog-pdf-pagina";
      canvas.width = viewport.width;
      canvas.height = viewport.height;
      canvas.style.width = "100%";
      canvas.style.height = "auto";
      contenedor.appendChild(canvas);
      await page.render({ canvasContext: canvas.getContext("2d"), viewport }).promise;
      if (miToken !== pdfRenderToken) return;
    }
  } catch (err) {
    if (miToken !== pdfRenderToken) return;
    console.error("No se pudo renderizar el PDF", err);
    contenedor.innerHTML = `<p class="blog-pdf-error">No se pudo mostrar el documento aquí. <a href="${url}" target="_blank" rel="noopener">Ábrelo en una pestaña nueva</a>.</p>`;
  }
}

function escapeHTML(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

async function cargarTodosPosts() {
  const res = await fetch(`${API_BASE}/posts`);
  todosPosts = await res.json();
}

function postsOrdenados() {
  const copia = [...todosPosts];
  copia.sort((a, b) => {
    const fa = a.publicado_en || "";
    const fb = b.publicado_en || "";
    return ordenDescendente ? fb.localeCompare(fa) : fa.localeCompare(fb);
  });
  return copia;
}

function renderSidebar() {
  const cont = document.getElementById("blog-sidebar-lista");
  const posts = postsOrdenados();
  if (posts.length === 0) {
    cont.innerHTML = `<p class="staff-hint">Todavía no hay boletines publicados.</p>`;
    return;
  }
  cont.innerHTML = posts
    .map(
      (p) => `
    <div class="blog-sidebar-item ${p.id === postIdActual ? "activo" : ""}" data-id="${p.id}">
      <div class="titulo">${escapeHTML(p.titulo)}</div>
      <div class="fecha">${(p.publicado_en || "").slice(0, 10)}</div>
    </div>`
    )
    .join("");
  cont.querySelectorAll(".blog-sidebar-item").forEach((el) => {
    el.addEventListener("click", () => mostrarPost(Number(el.dataset.id)));
  });
}

function mostrarLista() {
  postIdActual = null;
  pdfRenderToken++; // descarta cualquier render de PDF en curso al volver a la lista
  quitarIndiceCapitulos();
  document.getElementById("blog-hero").hidden = false;
  document.getElementById("blog-post").hidden = true;
  const listaEl = document.getElementById("blog-lista");
  listaEl.hidden = false;
  const posts = postsOrdenados();
  if (posts.length === 0) {
    listaEl.innerHTML = `<p class="staff-hint">Todavía no hay boletines publicados.</p>`;
  } else {
    listaEl.innerHTML = `<div class="blog-lista-grid">${posts
      .map(
        (p) => `
      <div class="blog-lista-card" data-id="${p.id}">
        <h2>${escapeHTML(p.titulo)}</h2>
        <p>${escapeHTML(p.resumen || "")}</p>
        <div class="fecha">${(p.publicado_en || "").slice(0, 10)}</div>
        ${p.tiene_pdf ? `<a href="${API_BASE}/posts/${p.id}/pdf" download class="blog-lista-pdf" data-pdf-card>⬇ Descargar PDF</a>` : ""}
      </div>`
      )
      .join("")}</div>`;
    listaEl.querySelectorAll(".blog-lista-card").forEach((card) => {
      card.addEventListener("click", (e) => {
        if (e.target.closest("[data-pdf-card]")) return;
        mostrarPost(Number(card.dataset.id));
      });
    });
  }
  renderSidebar();
  history.pushState({}, "", "/blog.html");
}

// Un boletín publicado solo con PDF (sin bloques) trae contenido_html vacío
// o reducido a un <p></p> suelto — sin esto la página se ve completamente
// en blanco hasta llegar al visor del PDF.
function contenidoEstaVacio(html) {
  const texto = (html || "")
    .replace(/<style[\s\S]*?<\/style>/gi, "")
    .replace(/<script[\s\S]*?<\/script>/gi, "")
    .replace(/<[^>]*>/g, "")
    .replace(/&nbsp;/gi, "")
    .trim();
  return texto.length === 0;
}

async function mostrarPost(id) {
  const res = await fetch(`${API_BASE}/posts/${id}`);
  if (!res.ok) {
    mostrarLista();
    return;
  }
  const post = await res.json();
  postIdActual = id;
  document.getElementById("blog-hero").hidden = true;
  document.getElementById("blog-lista").hidden = true;
  const postEl = document.getElementById("blog-post");
  postEl.hidden = false;
  const pdfUrl = `${API_BASE}/posts/${id}/pdf`;
  const pdfHtml = post.tiene_pdf
    ? `
    <div class="blog-pdf-wrap">
      <div class="blog-pdf-toolbar">
        <span>📄 Documento adjunto</span>
        <span class="blog-pdf-toolbar-acciones">
          <a href="${pdfUrl}" target="_blank" rel="noopener">↗ Abrir en pestaña</a>
          <a href="${pdfUrl}" download>⬇ Descargar PDF</a>
        </span>
      </div>
      <div class="blog-pdf-paginas" id="blog-pdf-paginas"></div>
    </div>`
    : "";
  const sinContenido = contenidoEstaVacio(post.contenido_html);
  const introHtml = sinContenido && post.tiene_pdf
    ? `
    <div class="blog-post-intro">
      <img src="assets/la-receta-logo.png" alt="La Receta Semanal">
      <p>Este boletín se comparte como documento — tienes todo el contenido aquí abajo, sin salir de la página 👇</p>
    </div>`
    : "";
  postEl.innerHTML = `
    <button class="btn btn-ghost btn-volver-blog" type="button">← Volver</button>
    <div class="blog-post">
      <h1>${escapeHTML(post.titulo)}</h1>
      <div class="fecha">${(post.publicado_en || "").slice(0, 10)}</div>
      ${introHtml}
      ${sinContenido ? "" : `<div class="contenido">${post.contenido_html}</div>`}
      ${pdfHtml}
    </div>
  `;
  postEl.querySelector(".btn-volver-blog").addEventListener("click", mostrarLista);
  renderSidebar();
  montarIndiceCapitulos(postEl);
  activarAnimacionesScroll(postEl);
  if (post.tiene_pdf) {
    renderPdfInline(pdfUrl, document.getElementById("blog-pdf-paginas"));
  } else {
    pdfRenderToken++; // invalida cualquier render de PDF en curso de un post anterior
  }
  history.pushState({}, "", `/blog.html?post=${id}`);
}

document.addEventListener("DOMContentLoaded", async () => {
  await cargarTodosPosts();

  document.getElementById("btn-orden-sidebar").addEventListener("click", (e) => {
    ordenDescendente = !ordenDescendente;
    e.target.textContent = ordenDescendente ? "Más recientes" : "Más antiguas";
    renderSidebar();
  });

  const postId = new URLSearchParams(location.search).get("post");
  if (postId) {
    mostrarPost(Number(postId));
  } else {
    mostrarLista();
  }
});

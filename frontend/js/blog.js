const API_BASE = `${window.location.origin}/api/public/boletines`;

let todosPosts = [];
let ordenDescendente = true; // true = más recientes primero
let postIdActual = null; // null = viendo la lista
let indiceObserver = null;
let revealObserver = null;

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
  quitarIndiceCapitulos();
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

async function mostrarPost(id) {
  const res = await fetch(`${API_BASE}/posts/${id}`);
  if (!res.ok) {
    mostrarLista();
    return;
  }
  const post = await res.json();
  postIdActual = id;
  document.getElementById("blog-lista").hidden = true;
  const postEl = document.getElementById("blog-post");
  postEl.hidden = false;
  const pdfUrl = `${API_BASE}/posts/${id}/pdf`;
  const pdfHtml = post.tiene_pdf
    ? `
    <div class="blog-pdf-wrap">
      <div class="blog-pdf-toolbar">
        <span>📄 Documento adjunto</span>
        <a href="${pdfUrl}" download>⬇ Descargar PDF</a>
      </div>
      <iframe src="${pdfUrl}" class="blog-pdf-frame"></iframe>
    </div>`
    : "";
  postEl.innerHTML = `
    <button class="btn btn-ghost btn-volver-blog" type="button">← Volver</button>
    <div class="blog-post">
      <h1>${escapeHTML(post.titulo)}</h1>
      <div class="fecha">${(post.publicado_en || "").slice(0, 10)}</div>
      <div class="contenido">${post.contenido_html}</div>
      ${pdfHtml}
    </div>
  `;
  postEl.querySelector(".btn-volver-blog").addEventListener("click", mostrarLista);
  renderSidebar();
  montarIndiceCapitulos(postEl);
  activarAnimacionesScroll(postEl);
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

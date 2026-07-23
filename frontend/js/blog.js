const API_BASE = `${window.location.origin}/api/public/boletines`;

function escapeHTML(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

async function mostrarLista() {
  document.getElementById("blog-post").hidden = true;
  const listaEl = document.getElementById("blog-lista");
  listaEl.hidden = false;
  const res = await fetch(`${API_BASE}/posts`);
  const posts = await res.json();
  if (posts.length === 0) {
    listaEl.innerHTML = `<p class="staff-hint">Todavía no hay boletines publicados.</p>`;
    return;
  }
  listaEl.innerHTML = posts
    .map(
      (p) => `
    <div class="blog-lista-card" data-id="${p.id}">
      <h2>${escapeHTML(p.titulo)}</h2>
      <p>${escapeHTML(p.resumen || "")}</p>
      <div class="fecha">${(p.publicado_en || "").slice(0, 10)}</div>
    </div>`
    )
    .join("");
  listaEl.querySelectorAll(".blog-lista-card").forEach((card) => {
    card.addEventListener("click", () => mostrarPost(Number(card.dataset.id)));
  });
}

async function mostrarPost(id) {
  const res = await fetch(`${API_BASE}/posts/${id}`);
  if (!res.ok) {
    mostrarLista();
    return;
  }
  const post = await res.json();
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
  postEl.querySelector(".btn-volver-blog").addEventListener("click", () => {
    history.pushState({}, "", "/blog.html");
    mostrarLista();
  });
  history.pushState({}, "", `/blog.html?post=${id}`);
}

document.addEventListener("DOMContentLoaded", () => {
  const postId = new URLSearchParams(location.search).get("post");
  if (postId) {
    mostrarPost(Number(postId));
  } else {
    mostrarLista();
  }
});

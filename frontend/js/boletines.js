let currentPostId = null;
let contactosActuales = [];

function escapeHTML(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

async function loadPosts() {
  const res = await fetch(`${AUTH_API_BASE}/boletines/posts`);
  const posts = await res.json();
  const tbody = document.getElementById("posts-tbody");
  if (posts.length === 0) {
    tbody.innerHTML = `<tr><td colspan="4" class="staff-hint">Todavía no hay ningún boletín.</td></tr>`;
    return;
  }
  tbody.innerHTML = posts
    .map(
      (p) => `
    <tr>
      <td>${escapeHTML(p.titulo)}</td>
      <td><span class="badge ${p.publicado ? "badge-publicado" : "badge-draft"}">${p.publicado ? "Publicado" : "Borrador"}</span></td>
      <td>${(p.publicado_en || p.creado_en || "").slice(0, 10)}</td>
      <td class="acciones">
        <button class="btn btn-ghost btn-editar-post" data-id="${p.id}" type="button">Editar</button>
      </td>
    </tr>`
    )
    .join("");
  tbody.querySelectorAll(".btn-editar-post").forEach((btn) => {
    btn.addEventListener("click", () => abrirEditor(Number(btn.dataset.id)));
  });
}

async function abrirEditor(postId) {
  currentPostId = postId;
  const editorCard = document.getElementById("editor-card");
  editorCard.hidden = false;
  document.getElementById("envio-resultado").textContent = "";

  if (postId) {
    const res = await fetch(`${AUTH_API_BASE}/boletines/posts/${postId}`);
    const post = await res.json();
    document.getElementById("editor-titulo-h2").textContent = "Editar boletín";
    document.getElementById("post-titulo").value = post.titulo;
    document.getElementById("post-resumen").value = post.resumen || "";
    document.getElementById("post-contenido").value = post.contenido_html;
    document.getElementById("btn-publicar-post").hidden = post.publicado;
    document.getElementById("btn-despublicar-post").hidden = !post.publicado;
    document.getElementById("btn-eliminar-post").hidden = false;
    document.getElementById("envio-section").hidden = false;
    document.getElementById("pdf-section").hidden = false;
    document.getElementById("pdf-actual-txt").innerHTML = post.tiene_pdf
      ? `📄 <a href="${AUTH_API_BASE}/boletines/posts/${postId}/pdf" target="_blank">Ver PDF actual</a>`
      : "Este boletín no tiene PDF adjunto todavía.";
    renderDestinatarios();
  } else {
    document.getElementById("editor-titulo-h2").textContent = "Nuevo boletín";
    document.getElementById("post-titulo").value = "";
    document.getElementById("post-resumen").value = "";
    document.getElementById("post-contenido").value = "";
    document.getElementById("btn-publicar-post").hidden = true;
    document.getElementById("btn-despublicar-post").hidden = true;
    document.getElementById("btn-eliminar-post").hidden = true;
    document.getElementById("envio-section").hidden = true;
    document.getElementById("pdf-section").hidden = true;
  }
  editorCard.scrollIntoView({ behavior: "smooth", block: "start" });
}

function cerrarEditor() {
  currentPostId = null;
  document.getElementById("editor-card").hidden = true;
}

async function guardarPost() {
  const titulo = document.getElementById("post-titulo").value.trim();
  const resumen = document.getElementById("post-resumen").value.trim();
  const contenido_html = document.getElementById("post-contenido").value.trim();
  if (!titulo || !contenido_html) {
    alert("Título y contenido son obligatorios.");
    return;
  }
  const body = JSON.stringify({ titulo, resumen, contenido_html });
  const headers = { "Content-Type": "application/json" };
  let res;
  if (currentPostId) {
    res = await fetch(`${AUTH_API_BASE}/boletines/posts/${currentPostId}`, { method: "PUT", headers, body });
  } else {
    res = await fetch(`${AUTH_API_BASE}/boletines/posts`, { method: "POST", headers, body });
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    alert(err.detail || "No se pudo guardar el boletín.");
    return;
  }
  const data = await res.json();
  await loadPosts();
  await abrirEditor(currentPostId || data.id);
}

async function publicarPost() {
  await fetch(`${AUTH_API_BASE}/boletines/posts/${currentPostId}/publicar`, { method: "POST" });
  await loadPosts();
  await abrirEditor(currentPostId);
}

async function despublicarPost() {
  await fetch(`${AUTH_API_BASE}/boletines/posts/${currentPostId}/despublicar`, { method: "POST" });
  await loadPosts();
  await abrirEditor(currentPostId);
}

async function eliminarPost() {
  if (!confirm("¿Eliminar este boletín? Esta acción no se puede deshacer.")) return;
  await fetch(`${AUTH_API_BASE}/boletines/posts/${currentPostId}`, { method: "DELETE" });
  cerrarEditor();
  await loadPosts();
}

function renderDestinatarios() {
  const lista = document.getElementById("destinatarios-lista");
  if (contactosActuales.length === 0) {
    lista.innerHTML = `<li class="staff-hint">Añade contactos abajo para poder enviarles el boletín.</li>`;
    return;
  }
  lista.innerHTML = contactosActuales
    .map(
      (c) => `
    <li>
      <input type="checkbox" class="chk-destinatario" value="${c.id}">
      <span>${escapeHTML(c.nombre)} — ${escapeHTML(c.email)}</span>
    </li>`
    )
    .join("");
}

async function enviarBoletin() {
  const ids = Array.from(document.querySelectorAll(".chk-destinatario:checked")).map((chk) => Number(chk.value));
  if (ids.length === 0) {
    alert("Selecciona al menos un destinatario.");
    return;
  }
  const res = await fetch(`${AUTH_API_BASE}/boletines/posts/${currentPostId}/enviar`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ contacto_ids: ids }),
  });
  const resultadoEl = document.getElementById("envio-resultado");
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    resultadoEl.textContent = err.detail || "No se pudo enviar el boletín.";
    return;
  }
  const data = await res.json();
  let texto = `Enviado a ${data.enviados} de ${data.total} destinatarios.`;
  if (data.fallidos.length > 0) {
    texto += "\nFallos:\n" + data.fallidos.map((f) => `- ${f.nombre} (${f.email}): ${f.error}`).join("\n");
  }
  resultadoEl.textContent = texto;
}

async function loadContactos() {
  const res = await fetch(`${AUTH_API_BASE}/boletines/contactos`);
  contactosActuales = await res.json();
  const lista = document.getElementById("contactos-lista");
  if (contactosActuales.length === 0) {
    lista.innerHTML = `<li class="staff-hint">Todavía no has añadido ningún contacto.</li>`;
  } else {
    lista.innerHTML = contactosActuales
      .map(
        (c) => `
      <li>
        <span>${escapeHTML(c.nombre)} — ${escapeHTML(c.email)}</span>
        <button class="btn btn-ghost btn-borrar-contacto" data-id="${c.id}" type="button">Eliminar</button>
      </li>`
      )
      .join("");
    lista.querySelectorAll(".btn-borrar-contacto").forEach((btn) => {
      btn.addEventListener("click", async () => {
        await fetch(`${AUTH_API_BASE}/boletines/contactos/${btn.dataset.id}`, { method: "DELETE" });
        await loadContactos();
        if (currentPostId) renderDestinatarios();
      });
    });
  }
  if (currentPostId) renderDestinatarios();
}

async function agregarContacto() {
  const nombre = document.getElementById("contacto-nombre").value.trim();
  const email = document.getElementById("contacto-email").value.trim();
  if (!nombre || !email.includes("@")) {
    alert("Nombre y email válidos son obligatorios.");
    return;
  }
  const res = await fetch(`${AUTH_API_BASE}/boletines/contactos`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ nombre, email }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    alert(err.detail || "No se pudo agregar el contacto.");
    return;
  }
  document.getElementById("contacto-nombre").value = "";
  document.getElementById("contacto-email").value = "";
  await loadContactos();
}

async function subirPdf(file) {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch(`${AUTH_API_BASE}/boletines/posts/${currentPostId}/pdf`, { method: "POST", body: formData });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    alert(err.detail || "No se pudo subir el PDF.");
    return;
  }
  await abrirEditor(currentPostId);
}

async function importarContactosExcel(file) {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch(`${AUTH_API_BASE}/boletines/contactos/importar`, { method: "POST", body: formData });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    alert(err.detail || "No se pudo importar el Excel.");
    return;
  }
  const data = await res.json();
  alert(`Importación completa: ${data.nuevos} contactos nuevos, ${data.ya_existian} ya existían, ${data.invalidos} filas sin email válido.`);
  await loadContactos();
}

document.addEventListener("DOMContentLoaded", async () => {
  const user = await checkAuth("/boletines.html");
  if (!user) return;
  if (!(user.modulos || []).includes("boletines")) {
    window.location.href = "/";
    return;
  }
  wireUserBar(user);

  await loadPosts();
  await loadContactos();

  document.getElementById("btn-nuevo-post").addEventListener("click", () => abrirEditor(null));
  document.getElementById("btn-cerrar-editor").addEventListener("click", cerrarEditor);
  document.getElementById("btn-guardar-post").addEventListener("click", guardarPost);
  document.getElementById("btn-publicar-post").addEventListener("click", publicarPost);
  document.getElementById("btn-despublicar-post").addEventListener("click", despublicarPost);
  document.getElementById("btn-eliminar-post").addEventListener("click", eliminarPost);
  document.getElementById("btn-agregar-contacto").addEventListener("click", agregarContacto);
  document.getElementById("input-pdf-upload").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    await subirPdf(file);
    e.target.value = "";
  });
  document.getElementById("input-contactos-upload").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    await importarContactosExcel(file);
    e.target.value = "";
  });
  document.getElementById("btn-enviar").addEventListener("click", enviarBoletin);
  document.getElementById("btn-seleccionar-todos").addEventListener("click", () => {
    document.querySelectorAll(".chk-destinatario").forEach((chk) => (chk.checked = true));
  });
});

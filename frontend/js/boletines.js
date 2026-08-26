let currentPostId = null;
let contactosActuales = [];
let postTienePdf = false; // el PDF cuenta como contenido en sí mismo — no exige además un bloque

// Icono SVG en vez de 🔗 — se ve igual de nítido en cualquier sistema.
const ICONO_ENLACE = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>`;

// escapeHTML ahora vive en common.js (cargado antes que este script).

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
        <button class="btn btn-ghost btn-copiar-enlace" data-id="${p.id}" type="button">${ICONO_ENLACE} Enlace</button>
      </td>
    </tr>`
    )
    .join("");
  tbody.querySelectorAll(".btn-editar-post").forEach((btn) => {
    btn.addEventListener("click", () => abrirEditor(Number(btn.dataset.id)));
  });
  tbody.querySelectorAll(".btn-copiar-enlace").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const url = `${window.location.origin}/blog.html?post=${btn.dataset.id}`;
      const textoOriginal = btn.textContent;
      try {
        await navigator.clipboard.writeText(url);
        btn.textContent = "✓ Copiado";
      } catch (e) {
        prompt("Copia este enlace:", url);
        return;
      }
      setTimeout(() => { btn.textContent = textoOriginal; }, 1500);
    });
  });
}

async function nuevoPost() {
  // Se crea un borrador vacío de inmediato (en vez de esperar al primer
  // "Guardar") para que el builder ya tenga un post_id real y se puedan
  // subir imágenes desde el primer momento. Si el usuario cierra sin tocar
  // nada, queda un borrador suelto en la lista — se puede borrar como
  // cualquier otro boletín, igual que un "Sin título" de Google Docs.
  const res = await fetch(`${AUTH_API_BASE}/boletines/posts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ titulo: "Nuevo boletín", resumen: "", contenido_html: "<p></p>" }),
  });
  if (!res.ok) {
    mostrarAviso("No se pudo crear el boletín.");
    return;
  }
  const data = await res.json();
  await loadPosts();
  await abrirEditor(data.id, true);
}

async function abrirEditor(postId, esNuevo = false) {
  currentPostId = postId;
  const editorCard = document.getElementById("editor-card");
  editorCard.hidden = false;
  document.getElementById("envio-resultado").textContent = "";

  const res = await fetch(`${AUTH_API_BASE}/boletines/posts/${postId}`);
  const post = await res.json();
  document.getElementById("editor-titulo-h2").textContent = esNuevo ? "Nuevo boletín" : "Editar boletín";
  document.getElementById("post-titulo").value = esNuevo ? "" : post.titulo;
  document.getElementById("post-resumen").value = esNuevo ? "" : (post.resumen || "");
  document.getElementById("btn-publicar-post").hidden = post.publicado;
  document.getElementById("btn-despublicar-post").hidden = !post.publicado;
  document.getElementById("btn-eliminar-post").hidden = false;
  document.getElementById("envio-section").hidden = false;
  document.getElementById("pdf-section").hidden = false;
  postTienePdf = !!post.tiene_pdf;
  document.getElementById("pdf-actual-txt").innerHTML = post.tiene_pdf
    ? `📄 <a href="${AUTH_API_BASE}/boletines/posts/${postId}/pdf" target="_blank">Ver PDF actual</a>`
    : "Este boletín no tiene PDF adjunto todavía.";
  renderDestinatarios();

  BoletinBuilder.setPostId(postId);
  if (esNuevo) {
    BoletinBuilder.nuevoVacio();
  } else if (post.contenido_bloques) {
    await BoletinBuilder.cargarBloques(post.contenido_bloques);
  } else {
    // Boletín creado antes del builder visual: se abre como un único
    // bloque "HTML avanzado" con su contenido intacto, para no perder nada.
    BoletinBuilder.cargarComoAvanzado(post.contenido_html);
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
  if (!titulo) {
    mostrarAviso("El título es obligatorio.");
    return;
  }
  if (!BoletinBuilder.tieneBloques() && !postTienePdf) {
    mostrarAviso("Añade al menos un bloque de contenido o adjunta un PDF.");
    return;
  }
  const body = JSON.stringify({
    titulo,
    resumen,
    contenido_html: BoletinBuilder.getHtml(),
    contenido_bloques: BoletinBuilder.getBloquesJSON(),
  });
  const headers = { "Content-Type": "application/json" };
  const res = await fetch(`${AUTH_API_BASE}/boletines/posts/${currentPostId}`, { method: "PUT", headers, body });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    mostrarAviso(err.detail || "No se pudo guardar el boletín.");
    return;
  }
  await loadPosts();
  await abrirEditor(currentPostId);
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
  if (!(await pedirConfirmacion("¿Eliminar este boletín? Esta acción no se puede deshacer."))) return;
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
    mostrarAviso("Selecciona al menos un destinatario.");
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

// Alternativa a "Enviar a seleccionados" (que pasa por Resend, y necesita
// el dominio verificado) — arma un mailto: con los mismos seleccionados en
// bcc y abre el cliente de correo del propio usuario, que envía desde su
// cuenta real. No pasa por el servidor ni deja constancia en boletin_envios.
function generarMailtoBoletin() {
  const ids = Array.from(document.querySelectorAll(".chk-destinatario:checked")).map((chk) => Number(chk.value));
  if (ids.length === 0) {
    mostrarAviso("Selecciona al menos un destinatario.");
    return;
  }
  const emails = contactosActuales.filter((c) => ids.includes(c.id)).map((c) => c.email);
  const titulo = document.getElementById("post-titulo").value.trim() || "Boletín";
  const resumen = document.getElementById("post-resumen").value.trim();
  const url = `${window.location.origin}/blog.html?post=${currentPostId}`;
  const asunto = encodeURIComponent(titulo);
  const cuerpo = encodeURIComponent(`${resumen ? resumen + "\n\n" : ""}Léelo aquí: ${url}`);
  window.location.href = `mailto:?bcc=${encodeURIComponent(emails.join(","))}&subject=${asunto}&body=${cuerpo}`;
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

// Mismo formato mínimo que valida el backend (local@dominio.tld, sin
// espacios) — no cubre todo RFC 5322, solo descarta lo obviamente mal
// escrito, para no dejar pasar contactos que luego fallan al enviar.
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

async function agregarContacto() {
  const nombre = document.getElementById("contacto-nombre").value.trim();
  const email = document.getElementById("contacto-email").value.trim();
  if (!nombre || !EMAIL_RE.test(email)) {
    mostrarAviso("Nombre y email con formato válido (ej. nombre@dominio.com) son obligatorios.");
    return;
  }
  const res = await fetch(`${AUTH_API_BASE}/boletines/contactos`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ nombre, email }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    mostrarAviso(err.detail || "No se pudo agregar el contacto.");
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
    mostrarAviso(err.detail || "No se pudo subir el PDF.");
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
    mostrarAviso(err.detail || "No se pudo importar el Excel.");
    return;
  }
  const data = await res.json();
  mostrarAviso(`Importación completa: ${data.nuevos} contactos nuevos, ${data.ya_existian} ya existían, ${data.invalidos} filas sin email válido.`);
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
  BoletinBuilder.init(document.getElementById("builder-root"));

  await loadPosts();
  await loadContactos();

  document.getElementById("btn-nuevo-post").addEventListener("click", nuevoPost);
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
  document.getElementById("btn-generar-mailto").addEventListener("click", generarMailtoBoletin);
  document.getElementById("btn-seleccionar-todos").addEventListener("click", () => {
    document.querySelectorAll(".chk-destinatario").forEach((chk) => (chk.checked = true));
  });
});

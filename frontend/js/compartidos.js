function escapeHTML(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

function nombreCandidato(datos) {
  return datos["Nombre"] || datos["nombre"] || datos["Name"] || "(sin nombre)";
}

async function loadCompartidos() {
  const res = await fetch(`${AUTH_API_BASE}/informes/compartidos`);
  const items = await res.json();
  const wrap = document.getElementById("compartidos-list");

  if (items.length === 0) {
    wrap.innerHTML = `<p class="staff-hint">Todavía no te han compartido ningún resultado.</p>`;
    return;
  }

  wrap.innerHTML = items
    .map((item) => {
      const entries = Object.entries(item.datos).filter(([k]) => k.toLowerCase() !== "nombre");
      const cvBtn = item.tiene_cv
        ? `<a href="${AUTH_API_BASE}/informes/respuestas/${item.respuesta_id}/cv" target="_blank" class="btn btn-primary">📄 Ver / descargar CV</a>`
        : `<span class="staff-hint">Sin CV subido todavía.</span>`;
      return `
        <div class="candidato-card">
          <h3>${escapeHTML(nombreCandidato(item.datos))}</h3>
          <p class="candidato-meta">${escapeHTML(item.tipo_nombre)} · hoja "${escapeHTML(item.hoja)}" · compartido ${escapeHTML(item.compartido_en)} por ${escapeHTML(item.compartido_por || "")}</p>
          <div class="candidato-datos">
            ${entries.map(([k, v]) => `<div><div class="campo-nombre">${escapeHTML(k)}</div><div>${escapeHTML(v)}</div></div>`).join("")}
          </div>
          <div style="margin-top:12px;">${cvBtn}</div>
        </div>`;
    })
    .join("");
}

document.addEventListener("DOMContentLoaded", async () => {
  const user = await checkAuth("/compartidos.html");
  if (!user) return;
  wireUserBar(user);
  await loadCompartidos();
});

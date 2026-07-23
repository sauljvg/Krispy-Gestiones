function escapeHTML(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

const EMPRESA = new URLSearchParams(location.search).get("empresa") === "saona" ? "saona" : "kk";

function aplicarBrandingEmpresa() {
  if (EMPRESA !== "saona") return;
  document.title = document.title.replace("Krispy Gestiones", "SAONA Gestiones");
  const icon = document.getElementById("brand-icon");
  if (icon) icon.textContent = "🌿";
  const favicon = document.querySelector('link[rel="icon"]');
  if (favicon) favicon.href = "assets/favicon-saona.png";
  const title = document.getElementById("brand-title");
  if (title) title.textContent = "SAONA Gestiones";
  document.documentElement.dataset.empresa = "saona";
}

function nombreCandidato(datos) {
  return datos["Nombre"] || datos["nombre"] || datos["Name"] || "(sin nombre)";
}

const MESES_CORTOS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];

// "2026-07-22 13:44:24" -> "22 jul 2026, 13:44"
function fmtFechaHora(iso) {
  if (!iso) return "";
  const [fecha, hora = ""] = iso.split(" ");
  const [y, m, d] = fecha.split("-");
  const hhmm = hora.slice(0, 5);
  return `${parseInt(d, 10)} ${MESES_CORTOS[parseInt(m, 10) - 1]} ${y}${hhmm ? `, ${hhmm}` : ""}`;
}

// Agrupa una lista (ya ordenada por fecha desc) en "tandas": cada vez que se
// comparten varios candidatos de una sola acción comparten fecha exacta y
// contraparte, así que forman un grupo. claveOtro = campo que identifica a la
// otra persona (quién lo compartió, o con quién se compartió).
function agruparPorTanda(items, claveOtro) {
  const grupos = [];
  let actual = null;
  for (const it of items) {
    const clave = `${it.compartido_en}|${it[claveOtro] || ""}`;
    if (!actual || actual.clave !== clave) {
      actual = { clave, compartido_en: it.compartido_en, otro: it[claveOtro], items: [] };
      grupos.push(actual);
    }
    actual.items.push(it);
  }
  return grupos;
}

function candidatoCardHTML(item) {
  const entries = Object.entries(item.datos).filter(([k]) => k.toLowerCase() !== "nombre");
  const cvBtn = item.tiene_cv
    ? `<a href="${AUTH_API_BASE}/informes/respuestas/${item.respuesta_id}/cv" target="_blank" rel="noopener" class="btn btn-primary">📄 Ver CV</a>`
    : `<span class="staff-hint">Sin CV subido todavía.</span>`;
  return `
    <div class="candidato-card">
      <h3>${escapeHTML(nombreCandidato(item.datos))}</h3>
      <p class="candidato-meta">${escapeHTML(item.tipo_nombre)} · hoja "${escapeHTML(item.hoja)}"</p>
      <div class="candidato-datos">
        ${entries.map(([k, v]) => `<div><div class="campo-nombre">${escapeHTML(k)}</div><div>${escapeHTML(v)}</div></div>`).join("")}
      </div>
      <div style="margin-top:12px;">${cvBtn}</div>
    </div>`;
}

// Cada tanda es un <details> desplegable. `etiquetaOtro` describe la relación
// ("Compartido por" / "Compartido con") y `abierta` deja la más reciente
// abierta por defecto para que no haya que hacer clic para ver lo último.
function grupoHTML(grupo, etiquetaOtro, abierta) {
  const n = grupo.items.length;
  return `
    <details class="tanda" ${abierta ? "open" : ""}>
      <summary class="tanda-summary">
        <span class="tanda-fecha">${escapeHTML(fmtFechaHora(grupo.compartido_en))}</span>
        <span class="tanda-meta">${n} candidato${n === 1 ? "" : "s"} · ${escapeHTML(etiquetaOtro)} <b>${escapeHTML(grupo.otro || "")}</b></span>
      </summary>
      <div class="tanda-body">
        ${grupo.items.map(candidatoCardHTML).join("")}
      </div>
    </details>`;
}

function seccionHTML(titulo, grupos, etiquetaOtro, vacioMsg) {
  if (grupos.length === 0) {
    return `<h2 class="reclu-seccion">${escapeHTML(titulo)}</h2><p class="staff-hint">${escapeHTML(vacioMsg)}</p>`;
  }
  return `<h2 class="reclu-seccion">${escapeHTML(titulo)}</h2>` +
    grupos.map((g, i) => grupoHTML(g, etiquetaOtro, i === 0)).join("");
}

async function loadCompartidos() {
  const wrap = document.getElementById("compartidos-list");
  const [conmigo, porMi] = await Promise.all([
    fetch(`${AUTH_API_BASE}/informes/compartidos?empresa=${EMPRESA}`).then((r) => (r.ok ? r.json() : [])),
    fetch(`${AUTH_API_BASE}/informes/compartidos-por-mi?empresa=${EMPRESA}`).then((r) => (r.ok ? r.json() : [])),
  ]);

  const gruposConmigo = agruparPorTanda(conmigo, "compartido_por");
  const gruposPorMi = agruparPorTanda(porMi, "destinatario_nombre");

  let html = seccionHTML(
    "Compartidos conmigo",
    gruposConmigo,
    "compartido por",
    "Todavía no te han compartido ningún candidato."
  );

  // La sección "Compartidos por ti" solo tiene sentido enseñarla si esta
  // persona ha compartido algo alguna vez (a un gerente no le aparecerá).
  if (gruposPorMi.length > 0) {
    html += seccionHTML("Compartidos por ti", gruposPorMi, "compartido con", "");
  }

  wrap.innerHTML = html;
}

document.addEventListener("DOMContentLoaded", async () => {
  const user = await checkAuth("/compartidos.html");
  if (!user) return;
  wireUserBar(user);
  aplicarBrandingEmpresa();
  await loadCompartidos();
});

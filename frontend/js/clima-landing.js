// Landing de Clima Laboral -- solo elige entre los dos módulos (Test /
// Informes) y pasa el ?empresa= actual a donde corresponda. Deliberadamente
// NO carga clima.js entero aquí: ese script asume que existen los elementos
// del dashboard (select-oleada, centro-grid...) que esta página no tiene.
const EMPRESA_LANDING = new URLSearchParams(location.search).get("empresa") === "saona" ? "saona" : "kk";

function aplicarBrandingEmpresaLanding() {
  if (EMPRESA_LANDING !== "saona") return;
  document.title = document.title.replace("Krispy Gestiones", "SAONA Gestiones");
  const icon = document.getElementById("brand-icon");
  if (icon) icon.textContent = "🌿";
  const favicon = document.querySelector('link[rel="icon"]');
  if (favicon) favicon.href = "assets/favicon-saona.png";
  const title = document.getElementById("brand-title");
  if (title) title.textContent = "SAONA Gestiones";
  const logo = document.getElementById("clima-report-logo");
  if (logo) {
    logo.src = "assets/saona-logo.png";
    logo.alt = "Saona";
    logo.style.height = "90px";
  }
  document.documentElement.dataset.empresa = "saona";
}

document.addEventListener("DOMContentLoaded", async () => {
  const user = await checkAuth("/clima.html");
  if (!user) return;
  const moduloRequerido = EMPRESA_LANDING === "saona" ? "saona_clima" : "clima";
  if (!(user.modulos || []).includes(moduloRequerido)) {
    window.location.href = "/";
    return;
  }
  wireUserBar(user);
  aplicarBrandingEmpresaLanding();

  const sufijoEmpresa = EMPRESA_LANDING === "saona" ? "?empresa=saona" : "";
  document.getElementById("link-clima-tests").href = `clima-tests.html${sufijoEmpresa}`;
  document.getElementById("link-clima-informes").href = `clima-informes.html${sufijoEmpresa}`;
});

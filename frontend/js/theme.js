function temaActual() {
  return document.documentElement.dataset.theme
    || (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
}

function aplicarTema(tema) {
  document.documentElement.dataset.theme = tema;
  localStorage.setItem("kt-theme", tema);
  const btn = document.getElementById("btn-theme-toggle");
  if (btn) btn.textContent = tema === "dark" ? "☀️" : "🌙";
}

document.addEventListener("DOMContentLoaded", () => {
  aplicarTema(temaActual());
  const btn = document.getElementById("btn-theme-toggle");
  if (btn) {
    btn.addEventListener("click", () => aplicarTema(temaActual() === "dark" ? "light" : "dark"));
  }
});

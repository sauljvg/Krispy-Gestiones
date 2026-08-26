// Utilidades compartidas por (casi) todas las páginas -- antes cada archivo
// definía su propia copia de escapeHTML (14 copias idénticas, salvo la de
// evaluaciones360.js que había quedado con una implementación distinta).
// Cargar este script ANTES que el JS propio de cada página, para que la
// función ya exista en el ámbito global cuando el resto del código la use.

function escapeHTML(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

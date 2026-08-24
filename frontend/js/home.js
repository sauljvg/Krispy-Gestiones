// Apodos para el saludo de la home -- excepciones pedidas explícitamente,
// por nombre completo. Se compara normalizado (sin tildes, minúsculas) para
// no depender de que esté escrito con los acentos exactos en la ficha.
const APODOS_HOME = {
  "maria hovsepian": "Maru",
  "rafaela morales": "Rafa",
  "matias prada": "Mati",
  "ildara lorenzo": "Ildi",
  "elisabeth cachimaille": "Eli",
};

function saludoHome(nombreCompleto) {
  const normalizado = (nombreCompleto || "")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .trim();
  const apodo = APODOS_HOME[normalizado];
  if (apodo) return `Hola, ${apodo}`;
  const primerNombre = (nombreCompleto || "").trim().split(/\s+/)[0] || "";
  return primerNombre ? `Hola, ${primerNombre}` : "¿A dónde quieres ir?";
}

document.addEventListener("DOMContentLoaded", async () => {
  const user = await checkAuth("/");
  if (!user) return;
  wireUserBar(user);
  document.getElementById("home-titulo").textContent = saludoHome(user.nombre);

  const modulos = user.modulos || [];
  document.getElementById("card-resenas").hidden = !modulos.includes("resenas");
  document.getElementById("card-informes").hidden = !modulos.includes("informes");
  document.getElementById("card-clima").hidden = !modulos.includes("clima");
  document.getElementById("card-entrevistas").hidden = !modulos.includes("informes");
  document.getElementById("card-compartidos").hidden = !(modulos.includes("informes") || modulos.includes("reclutamiento"));
  // Boletines oculto de la home por ahora (no se va a usar) -- la página y
  // la API siguen intactas, solo se quita el acceso desde el menú principal.
  document.getElementById("card-tests").hidden = !modulos.includes("tests");
  document.getElementById("card-disc").hidden = !modulos.includes("disc");
  document.getElementById("card-agregadores").hidden = !modulos.includes("agregadores");
  aplicarVisibilidadEval360(document.getElementById("card-evaluaciones360"), user, modulos.includes("evaluaciones360"));
  const tieneModuloSaona = ["saona_resenas", "saona_informes", "saona_clima", "saona_evaluaciones360", "saona_reclutamiento"].some((m) => modulos.includes(m));
  document.getElementById("card-saona").hidden = !tieneModuloSaona;
  if (user.rol === "admin") {
    document.getElementById("menu-ajustes").hidden = false;
    document.getElementById("card-saona").hidden = false;
  }
});

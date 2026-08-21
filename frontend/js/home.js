document.addEventListener("DOMContentLoaded", async () => {
  const user = await checkAuth("/");
  if (!user) return;
  wireUserBar(user);

  const modulos = user.modulos || [];
  document.getElementById("card-resenas").hidden = !modulos.includes("resenas");
  document.getElementById("card-informes").hidden = !modulos.includes("informes");
  document.getElementById("card-clima").hidden = !modulos.includes("clima");
  document.getElementById("card-entrevistas").hidden = !modulos.includes("informes");
  // Boletines oculto de la home por ahora (no se va a usar) -- la página y
  // la API siguen intactas, solo se quita el acceso desde el menú principal.
  document.getElementById("card-tests").hidden = !modulos.includes("tests");
  document.getElementById("card-disc").hidden = !modulos.includes("disc");
  document.getElementById("card-agregadores").hidden = !modulos.includes("agregadores");
  document.getElementById("card-evaluaciones360").hidden = !modulos.includes("evaluaciones360");
  const tieneModuloSaona = ["saona_resenas", "saona_informes", "saona_clima", "saona_evaluaciones360"].some((m) => modulos.includes(m));
  document.getElementById("card-saona").hidden = !tieneModuloSaona;
  if (user.rol === "admin") {
    document.getElementById("menu-ajustes").hidden = false;
    document.getElementById("card-saona").hidden = false;
  }
});

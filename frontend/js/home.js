document.addEventListener("DOMContentLoaded", async () => {
  const user = await checkAuth("/");
  if (!user) return;
  wireUserBar(user);

  const modulos = user.modulos || [];
  document.getElementById("card-resenas").hidden = !modulos.includes("resenas");
  document.getElementById("card-informes").hidden = !modulos.includes("informes");
  document.getElementById("card-clima").hidden = !modulos.includes("clima");
  document.getElementById("card-entrevistas").hidden = !modulos.includes("informes");
  document.getElementById("card-boletines").hidden = !modulos.includes("boletines");
  document.getElementById("card-tests").hidden = !modulos.includes("tests");
  document.getElementById("card-disc").hidden = !modulos.includes("disc");
  const tieneModuloSaona = ["saona_resenas", "saona_informes", "saona_clima"].some((m) => modulos.includes(m));
  document.getElementById("card-saona").hidden = !tieneModuloSaona;
  if (user.rol === "admin") {
    document.getElementById("menu-ajustes").hidden = false;
    document.getElementById("card-saona").hidden = false;
  }
});

document.addEventListener("DOMContentLoaded", async () => {
  const user = await checkAuth("/saona.html");
  if (!user) return;

  const modulos = user.modulos || [];
  const tieneAlgunModuloSaona = ["saona_resenas", "saona_informes", "saona_clima"].some((m) => modulos.includes(m));
  if (!tieneAlgunModuloSaona) {
    window.location.href = "/";
    return;
  }
  wireUserBar(user);

  document.getElementById("card-saona-resenas").hidden = !modulos.includes("saona_resenas");
  document.getElementById("card-saona-informes").hidden = !modulos.includes("saona_informes");
  document.getElementById("card-saona-clima").hidden = !modulos.includes("saona_clima");
  document.getElementById("card-saona-entrevistas").hidden = !modulos.includes("saona_informes");
});

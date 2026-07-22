document.addEventListener("DOMContentLoaded", async () => {
  const user = await checkAuth("/");
  if (!user) return;
  wireUserBar(user);

  const modulos = user.modulos || [];
  document.getElementById("card-resenas").hidden = !modulos.includes("resenas");
  document.getElementById("card-informes").hidden = !modulos.includes("informes");
  document.getElementById("card-clima").hidden = !modulos.includes("clima");
  if (user.rol === "admin") {
    document.getElementById("card-usuarios").hidden = false;
  }
});

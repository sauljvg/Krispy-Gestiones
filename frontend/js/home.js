document.addEventListener("DOMContentLoaded", async () => {
  const user = await checkAuth("/");
  if (!user) return;
  wireUserBar(user);

  if (esRolTodo(user.rol)) {
    document.getElementById("card-informes").hidden = false;
    document.getElementById("card-clima").hidden = false;
  }
  if (user.rol === "admin") {
    document.getElementById("card-usuarios").hidden = false;
  }
});

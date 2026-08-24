const AUTH_API_BASE = `${window.location.origin}/api`;

async function checkAuth(nextPath) {
  const res = await fetch(`${AUTH_API_BASE}/auth/me`);
  if (!res.ok) {
    window.location.href = "/login.html?next=" + encodeURIComponent(nextPath || window.location.pathname);
    return null;
  }
  return res.json();
}

// Tarjeta de Evaluaciones 360 en la home (normal y SAONA): un admin la ve
// siempre (gestiona el módulo entero), a cualquier otra persona con el
// módulo concedido solo le interesa si tiene algo pendiente de responder
// ahora mismo -- así no se queda un acceso "muerto" en la home entre
// campaña y campaña. mis-pendientes no filtra por empresa (no hace falta:
// sin el módulo de esa empresa ni siquiera se puede abrir la página).
async function aplicarVisibilidadEval360(card, user, tieneModulo) {
  if (!card) return;
  if (!tieneModulo) {
    card.hidden = true;
    return;
  }
  if (user.rol === "admin") {
    card.hidden = false;
    return;
  }
  card.hidden = true;
  const pendientes = await fetch(`${AUTH_API_BASE}/evaluaciones360/mis-pendientes`).then((r) => (r.ok ? r.json() : [])).catch(() => []);
  card.hidden = !(pendientes && pendientes.length > 0);
}

function wireUserBar(user) {
  const userLabel = document.getElementById("topbar-user");
  if (userLabel) {
    userLabel.textContent = `${user.nombre} (${user.rol})`;
    userLabel.hidden = false;
  }
  const logoutBtn = document.getElementById("btn-logout");
  if (logoutBtn) {
    logoutBtn.hidden = false;
    logoutBtn.addEventListener("click", async () => {
      await fetch(`${AUTH_API_BASE}/auth/logout`, { method: "POST" });
      window.location.href = "/login.html";
    });
  }
}

const AUTH_API_BASE = `${window.location.origin}/api`;

async function checkAuth(nextPath) {
  const res = await fetch(`${AUTH_API_BASE}/auth/me`);
  if (!res.ok) {
    window.location.href = "/login.html?next=" + encodeURIComponent(nextPath || window.location.pathname);
    return null;
  }
  return res.json();
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

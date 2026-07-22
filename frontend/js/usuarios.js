let ROLES_CACHE = [];

function fmtFecha(iso) {
  if (!iso) return "";
  return iso.slice(0, 10);
}

async function loadRoles() {
  const res = await fetch(`${AUTH_API_BASE}/auth/roles`);
  ROLES_CACHE = await res.json();
  const select = document.getElementById("nu-rol");
  select.innerHTML = ROLES_CACHE.map((r) => `<option value="${r.value}">${r.label}</option>`).join("");
}

function rolSelectHTML(current) {
  return ROLES_CACHE.map(
    (r) => `<option value="${r.value}" ${r.value === current ? "selected" : ""}>${r.label}</option>`
  ).join("");
}

async function loadUsers(currentUserId) {
  const res = await fetch(`${AUTH_API_BASE}/auth/users`);
  const users = await res.json();
  const tbody = document.getElementById("users-list");
  tbody.innerHTML = users
    .map(
      (u) => `
      <tr data-id="${u.id}">
        <td>${u.username}</td>
        <td>${u.nombre}</td>
        <td><select class="rol-select" data-id="${u.id}" ${u.id === currentUserId ? "disabled" : ""}>${rolSelectHTML(u.rol)}</select></td>
        <td>
          <input type="text" class="pin-input" data-id="${u.id}" value="${u.pin || ""}" placeholder="sin PIN" maxlength="4" style="width:60px; text-align:center;">
        </td>
        <td>${fmtFecha(u.creado)}</td>
        <td>
          <button type="button" class="btn btn-ghost btn-guardar-pin" data-id="${u.id}">Guardar PIN</button>
          ${u.id === currentUserId ? "" : `<button type="button" class="btn btn-ghost btn-delete-user" data-id="${u.id}">Eliminar</button>`}
        </td>
      </tr>`
    )
    .join("");

  tbody.querySelectorAll(".rol-select").forEach((sel) => {
    sel.addEventListener("change", async () => {
      const id = sel.dataset.id;
      const res = await fetch(`${AUTH_API_BASE}/auth/users/${id}/rol`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rol: sel.value }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        alert(body.detail || "No se pudo cambiar el rol.");
        loadUsers(currentUserId);
      }
    });
  });

  tbody.querySelectorAll(".btn-guardar-pin").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.dataset.id;
      const input = tbody.querySelector(`.pin-input[data-id="${id}"]`);
      const pin = input.value.trim();
      if (!/^\d{4}$/.test(pin)) {
        alert("El PIN debe ser de 4 dígitos.");
        return;
      }
      const res = await fetch(`${AUTH_API_BASE}/auth/users/${id}/pin`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pin }),
      });
      if (!res.ok) {
        alert("No se pudo guardar el PIN.");
      } else {
        alert("PIN actualizado.");
      }
    });
  });

  tbody.querySelectorAll(".btn-delete-user").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm("¿Eliminar este usuario?")) return;
      const id = btn.dataset.id;
      const res = await fetch(`${AUTH_API_BASE}/auth/users/${id}`, { method: "DELETE" });
      if (!res.ok) {
        alert("No se pudo eliminar el usuario.");
      } else {
        loadUsers(currentUserId);
      }
    });
  });
}

document.addEventListener("DOMContentLoaded", async () => {
  const user = await checkAuth("/usuarios.html");
  if (!user) return;
  if (user.rol !== "admin") {
    window.location.href = "/";
    return;
  }
  wireUserBar(user);

  await loadRoles();
  await loadUsers(user.id);

  const errorEl = document.getElementById("new-user-error");
  const okEl = document.getElementById("new-user-ok");

  document.getElementById("new-user-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    errorEl.hidden = true;
    okEl.hidden = true;

    const body = {
      username: document.getElementById("nu-username").value.trim(),
      nombre: document.getElementById("nu-nombre").value.trim(),
      rol: document.getElementById("nu-rol").value,
    };

    const res = await fetch(`${AUTH_API_BASE}/auth/users`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      errorEl.textContent = err.detail || "No se pudo crear el usuario.";
      errorEl.hidden = false;
      return;
    }

    okEl.textContent = `Usuario "${body.username}" creado.`;
    okEl.hidden = false;
    document.getElementById("new-user-form").reset();
    loadUsers(user.id);
  });
});

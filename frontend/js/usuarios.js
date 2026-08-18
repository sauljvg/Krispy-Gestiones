let ROLES_CACHE = [];
let MODULOS_CACHE = [];
let TIPOS_INFORME_CACHE = null; // null = todavía no se ha pedido (se carga la primera vez que hace falta)
let CLIMA_CENTROS_CACHE = null; // idem, para el checklist de restricción por centro de Clima Laboral

function escapeHTML(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

// Mismas tiendas del selector de Reseñas (KK + SAONA) — ParqueSur es una
// sola ficha de Google (fábrica y tienda comparten la misma reseña pública),
// así que no hay forma de separarlas a nivel de datos. La restricción por
// tienda no distingue empresa: a un usuario con módulo saona_resenas se le
// puede limitar a "Saona Madnum" igual que a uno de Reseñas KK a "Caleido".
const TIENDAS_DISPONIBLES = [
  "Caleido", "Gran Plaza 2", "La Gavia", "ParqueSur", "Plenilunio", "Princesa",
  "Saona Madnum", "Saona Salamanca",
];

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

async function loadModulos() {
  const res = await fetch(`${AUTH_API_BASE}/auth/modulos`);
  MODULOS_CACHE = await res.json();
}

async function loadTiposInformeSiHaceFalta() {
  if (TIPOS_INFORME_CACHE !== null) return TIPOS_INFORME_CACHE;
  const res = await fetch(`${AUTH_API_BASE}/informes/tipos`);
  TIPOS_INFORME_CACHE = res.ok ? await res.json() : [];
  return TIPOS_INFORME_CACHE;
}

async function loadClimaCentrosSiHaceFalta() {
  if (CLIMA_CENTROS_CACHE !== null) return CLIMA_CENTROS_CACHE;
  const res = await fetch(`${AUTH_API_BASE}/clima/centros-conocidos`);
  CLIMA_CENTROS_CACHE = res.ok ? await res.json() : [];
  return CLIMA_CENTROS_CACHE;
}

function moduloLabel(clave) {
  return MODULOS_CACHE.find((m) => m.value === clave)?.label || clave;
}

// --- Formulario de creación ---

function renderNuModulosChecklist() {
  const wrap = document.getElementById("nu-modulos-checklist");
  wrap.innerHTML = MODULOS_CACHE.map(
    (m, i) => `
    <div class="checklist-row">
      <input type="checkbox" id="nu-modulo-${i}" class="nu-modulo-check" value="${m.value}">
      <label for="nu-modulo-${i}">${escapeHTML(m.label)}</label>
    </div>`
  ).join("");
  wrap.querySelectorAll(".nu-modulo-check").forEach((cb) => {
    cb.addEventListener("change", actualizarVisibilidadDependientesNuevoUsuario);
  });
}

function modulosSeleccionadosNuevoUsuario() {
  return [...document.querySelectorAll(".nu-modulo-check:checked")].map((cb) => cb.value);
}

async function actualizarVisibilidadDependientesNuevoUsuario() {
  const modulos = modulosSeleccionadosNuevoUsuario();
  document.getElementById("nu-tiendas-wrap").hidden = !modulos.includes("resenas");
  // "Tipos de informe" es el mismo checklist para las dos empresas (los
  // tipos de Saona ya vienen con el nombre prefijado "SAONA · " para
  // distinguirse) — se muestra si tiene cualquiera de los dos módulos.
  const tieneInformes = modulos.includes("informes") || modulos.includes("saona_informes");
  const tiposWrap = document.getElementById("nu-tipos-informe-wrap");
  tiposWrap.hidden = !tieneInformes;
  if (tieneInformes && !tiposWrap.dataset.cargado) {
    tiposWrap.dataset.cargado = "1";
    await renderNuTiposInformeChecklist();
  }
}

function actualizarVisibilidadPorRol() {
  const rol = document.getElementById("nu-rol").value;
  const esAdmin = rol === "admin";
  document.getElementById("nu-modulos-checklist").hidden = esAdmin;
  document.getElementById("nu-admin-hint").hidden = !esAdmin;
  if (esAdmin) {
    document.getElementById("nu-tiendas-wrap").hidden = true;
    document.getElementById("nu-tipos-informe-wrap").hidden = true;
  } else {
    actualizarVisibilidadDependientesNuevoUsuario();
  }
}

function renderNuTiendasChecklist() {
  const wrap = document.getElementById("nu-tiendas-checklist");
  wrap.innerHTML = TIENDAS_DISPONIBLES.map(
    (t, i) => `
    <div class="checklist-row">
      <input type="checkbox" id="nu-tienda-${i}" class="nu-tienda-check" value="${t}" disabled>
      <label for="nu-tienda-${i}">${t}</label>
    </div>`
  ).join("");
  const todas = document.getElementById("nu-tienda-todas");
  todas.addEventListener("change", () => {
    wrap.querySelectorAll(".nu-tienda-check").forEach((cb) => {
      cb.disabled = todas.checked;
      if (todas.checked) cb.checked = false;
    });
  });
}

function tiendasSeleccionadasNuevoUsuario() {
  if (document.getElementById("nu-tienda-todas").checked) return [];
  return [...document.querySelectorAll(".nu-tienda-check:checked")].map((cb) => cb.value);
}

async function renderNuTiposInformeChecklist() {
  const tipos = await loadTiposInformeSiHaceFalta();
  const wrap = document.getElementById("nu-tipos-informe-checklist");
  wrap.innerHTML = tipos.map(
    (t, i) => `
    <div class="checklist-row">
      <input type="checkbox" id="nu-tipo-informe-${i}" class="nu-tipo-informe-check" value="${t.clave}" disabled>
      <label for="nu-tipo-informe-${i}">${escapeHTML(t.nombre)}</label>
    </div>`
  ).join("");
  const todos = document.getElementById("nu-tipo-informe-todos");
  todos.onchange = () => {
    wrap.querySelectorAll(".nu-tipo-informe-check").forEach((cb) => {
      cb.disabled = todos.checked;
      if (todos.checked) cb.checked = false;
    });
  };
}

function tiposInformeSeleccionadosNuevoUsuario() {
  if (document.getElementById("nu-tipo-informe-todos").checked) return [];
  return [...document.querySelectorAll(".nu-tipo-informe-check:checked")].map((cb) => cb.value);
}

// --- Tabla de usuarios existentes ---

function rolSelectHTML(current) {
  return ROLES_CACHE.map(
    (r) => `<option value="${r.value}" ${r.value === current ? "selected" : ""}>${r.label}</option>`
  ).join("");
}

function tiendasResumenHTML(tiendas) {
  if (!tiendas || tiendas.length === 0) return `<span class="staff-hint">Todas</span>`;
  return escapeHTML(tiendas.join(", "));
}

function modulosResumenHTML(u) {
  if (u.rol === "admin") return `<span class="staff-hint">Todo (admin)</span>`;
  if (!u.modulos || u.modulos.length === 0) return `<span class="staff-hint">Ninguno</span>`;
  return escapeHTML(u.modulos.map(moduloLabel).join(", "));
}

function tiposInformeResumenHTML(u) {
  // Sin filas en tipos_informes normalmente significa "sin restricción, ve
  // todos los tipos" — pero eso solo tiene sentido si el usuario tiene
  // acceso al módulo Informes en primer lugar. Si no lo tiene, "Todos" es
  // engañoso (parece que ve de todo cuando en realidad no entra a Informes).
  const tieneInformes = u.rol === "admin" || (u.modulos || []).some((m) => m === "informes" || m === "saona_informes");
  if (!tieneInformes) return `<span class="staff-hint">Ninguno</span>`;
  const tipos = u.tipos_informes;
  if (!tipos || tipos.length === 0) return `<span class="staff-hint">Todos</span>`;
  const cache = TIPOS_INFORME_CACHE || [];
  const nombres = tipos.map((clave) => cache.find((t) => t.clave === clave)?.nombre || clave);
  return escapeHTML(nombres.join(", "));
}

function climaCentrosResumenHTML(u) {
  // Mismo razonamiento que tiposInformeResumenHTML: "Todos" solo tiene
  // sentido si el usuario tiene acceso al módulo Clima Laboral.
  const tieneClima = u.rol === "admin" || (u.modulos || []).some((m) => m === "clima" || m === "saona_clima");
  if (!tieneClima) return `<span class="staff-hint">Ninguno</span>`;
  const centros = u.clima_centros;
  if (!centros || centros.length === 0) return `<span class="staff-hint">Todos</span>`;
  return escapeHTML(centros.join(", "));
}

async function loadUsers(currentUserId) {
  await loadTiposInformeSiHaceFalta();
  await loadClimaCentrosSiHaceFalta();
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
          ${
            u.rol === "admin"
              ? modulosResumenHTML(u)
              : `
          <div class="checklist-wrap">
            <span class="modulos-resumen" data-id="${u.id}">${modulosResumenHTML(u)}</span>
            <button type="button" class="btn btn-ghost btn-editar-modulos" data-id="${u.id}" style="font-size:11px; padding:3px 8px; margin-left:6px;">Editar</button>
            <div class="checklist-popover" id="modulos-popover-${u.id}">
              <div class="checklist-popover-actions">
                <span style="font-size:11px; color:var(--text-secondary);">Módulos</span>
                <button type="button" class="btn-modulos-cerrar" data-id="${u.id}">Cerrar</button>
              </div>
              ${MODULOS_CACHE.map(
                (m, i) => `
                <div class="checklist-row">
                  <input type="checkbox" id="em-${u.id}-${i}" class="em-modulo" data-id="${u.id}" value="${m.value}"
                    ${(u.modulos || []).includes(m.value) ? "checked" : ""}>
                  <label for="em-${u.id}-${i}">${escapeHTML(m.label)}</label>
                </div>`
              ).join("")}
              <button type="button" class="btn btn-primary btn-guardar-modulos" data-id="${u.id}" style="width:100%; margin-top:8px; font-size:12px;">Guardar</button>
            </div>
          </div>`
          }
        </td>
        <td>
          <div class="checklist-wrap">
            <span class="tiendas-resumen" data-id="${u.id}">${tiendasResumenHTML(u.tiendas)}</span>
            <button type="button" class="btn btn-ghost btn-editar-tiendas" data-id="${u.id}" style="font-size:11px; padding:3px 8px; margin-left:6px;">Editar</button>
            <div class="checklist-popover" id="tiendas-popover-${u.id}">
              <div class="checklist-popover-actions">
                <span style="font-size:11px; color:var(--text-secondary);">Tiendas</span>
                <button type="button" class="btn-tiendas-cerrar" data-id="${u.id}">Cerrar</button>
              </div>
              <div class="checklist-row" style="border-bottom:1px solid var(--border); padding-bottom:6px; margin-bottom:4px;">
                <input type="checkbox" id="et-todas-${u.id}" class="et-todas" data-id="${u.id}" ${!u.tiendas || u.tiendas.length === 0 ? "checked" : ""}>
                <label for="et-todas-${u.id}">Todas las tiendas</label>
              </div>
              ${TIENDAS_DISPONIBLES.map(
                (t, i) => `
                <div class="checklist-row">
                  <input type="checkbox" id="et-${u.id}-${i}" class="et-tienda" data-id="${u.id}" value="${t}"
                    ${(u.tiendas || []).includes(t) ? "checked" : ""}
                    ${!u.tiendas || u.tiendas.length === 0 ? "disabled" : ""}>
                  <label for="et-${u.id}-${i}">${t}</label>
                </div>`
              ).join("")}
              <button type="button" class="btn btn-primary btn-guardar-tiendas" data-id="${u.id}" style="width:100%; margin-top:8px; font-size:12px;">Guardar</button>
            </div>
          </div>
        </td>
        <td>
          <div class="checklist-wrap">
            <span class="tipos-informe-resumen" data-id="${u.id}">${tiposInformeResumenHTML(u)}</span>
            <button type="button" class="btn btn-ghost btn-editar-tipos-informe" data-id="${u.id}" style="font-size:11px; padding:3px 8px; margin-left:6px;">Editar</button>
            <div class="checklist-popover" id="tipos-informe-popover-${u.id}">
              <div class="checklist-popover-actions">
                <span style="font-size:11px; color:var(--text-secondary);">Informes</span>
                <button type="button" class="btn-tipos-informe-cerrar" data-id="${u.id}">Cerrar</button>
              </div>
              <div class="checklist-row" style="border-bottom:1px solid var(--border); padding-bottom:6px; margin-bottom:4px;">
                <input type="checkbox" id="eti-todos-${u.id}" class="eti-todos" data-id="${u.id}" ${!u.tipos_informes || u.tipos_informes.length === 0 ? "checked" : ""}>
                <label for="eti-todos-${u.id}">Todos los tipos</label>
              </div>
              ${(TIPOS_INFORME_CACHE || []).map(
                (t, i) => `
                <div class="checklist-row">
                  <input type="checkbox" id="eti-${u.id}-${i}" class="eti-tipo" data-id="${u.id}" value="${t.clave}"
                    ${(u.tipos_informes || []).includes(t.clave) ? "checked" : ""}
                    ${!u.tipos_informes || u.tipos_informes.length === 0 ? "disabled" : ""}>
                  <label for="eti-${u.id}-${i}">${escapeHTML(t.nombre)}</label>
                </div>`
              ).join("")}
              <button type="button" class="btn btn-primary btn-guardar-tipos-informe" data-id="${u.id}" style="width:100%; margin-top:8px; font-size:12px;">Guardar</button>
            </div>
          </div>
        </td>
        <td>
          <div class="checklist-wrap">
            <span class="clima-centros-resumen" data-id="${u.id}">${climaCentrosResumenHTML(u)}</span>
            <button type="button" class="btn btn-ghost btn-editar-clima-centros" data-id="${u.id}" style="font-size:11px; padding:3px 8px; margin-left:6px;">Editar</button>
            <div class="checklist-popover" id="clima-centros-popover-${u.id}">
              <div class="checklist-popover-actions">
                <span style="font-size:11px; color:var(--text-secondary);">Clima Laboral</span>
                <button type="button" class="btn-clima-centros-cerrar" data-id="${u.id}">Cerrar</button>
              </div>
              <div class="checklist-row" style="border-bottom:1px solid var(--border); padding-bottom:6px; margin-bottom:4px;">
                <input type="checkbox" id="ecc-todos-${u.id}" class="ecc-todos" data-id="${u.id}" ${!u.clima_centros || u.clima_centros.length === 0 ? "checked" : ""}>
                <label for="ecc-todos-${u.id}">Todos los centros</label>
              </div>
              ${(CLIMA_CENTROS_CACHE || []).map(
                (c, i) => `
                <div class="checklist-row">
                  <input type="checkbox" id="ecc-${u.id}-${i}" class="ecc-centro" data-id="${u.id}" value="${escapeHTML(c)}"
                    ${(u.clima_centros || []).includes(c) ? "checked" : ""}
                    ${!u.clima_centros || u.clima_centros.length === 0 ? "disabled" : ""}>
                  <label for="ecc-${u.id}-${i}">${escapeHTML(c)}</label>
                </div>`
              ).join("")}
              <button type="button" class="btn btn-primary btn-guardar-clima-centros" data-id="${u.id}" style="width:100%; margin-top:8px; font-size:12px;">Guardar</button>
            </div>
          </div>
        </td>
        <td>
          <input type="text" class="pin-input" data-id="${u.id}" value="${u.pin || ""}" placeholder="sin PIN" maxlength="4" style="width:60px; text-align:center;">
        </td>
        <td>${fmtFecha(u.creado)}</td>
        <td>
          <button type="button" class="btn btn-ghost btn-guardar-pin" data-id="${u.id}">Guardar PIN</button>
          ${u.pin ? `<button type="button" class="btn btn-ghost btn-reset-pin" data-id="${u.id}" title="Borra el PIN — al volver a entrar, el usuario crea uno nuevo">Resetear PIN</button>` : ""}
          ${u.id === currentUserId ? "" : `<button type="button" class="btn btn-ghost btn-delete-user" data-id="${u.id}">Eliminar</button>`}
        </td>
      </tr>`
    )
    .join("");

  function wirePopoverToggle(btnClass, popoverPrefix) {
    tbody.querySelectorAll(btnClass).forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = btn.dataset.id;
        tbody.querySelectorAll(".checklist-popover").forEach((p) => {
          if (p.id !== `${popoverPrefix}-${id}`) p.classList.remove("visible");
        });
        document.getElementById(`${popoverPrefix}-${id}`).classList.toggle("visible");
      });
    });
  }
  function wirePopoverClose(btnClass, popoverPrefix) {
    tbody.querySelectorAll(btnClass).forEach((btn) => {
      btn.addEventListener("click", () => {
        document.getElementById(`${popoverPrefix}-${btn.dataset.id}`).classList.remove("visible");
      });
    });
  }

  wirePopoverToggle(".btn-editar-modulos", "modulos-popover");
  wirePopoverClose(".btn-modulos-cerrar", "modulos-popover");
  wirePopoverToggle(".btn-editar-tiendas", "tiendas-popover");
  wirePopoverClose(".btn-tiendas-cerrar", "tiendas-popover");
  wirePopoverToggle(".btn-editar-tipos-informe", "tipos-informe-popover");
  wirePopoverClose(".btn-tipos-informe-cerrar", "tipos-informe-popover");
  wirePopoverToggle(".btn-editar-clima-centros", "clima-centros-popover");
  wirePopoverClose(".btn-clima-centros-cerrar", "clima-centros-popover");

  tbody.querySelectorAll(".et-todas").forEach((cb) => {
    cb.addEventListener("change", () => {
      const id = cb.dataset.id;
      tbody.querySelectorAll(`.et-tienda[data-id="${id}"]`).forEach((tCb) => {
        tCb.disabled = cb.checked;
        if (cb.checked) tCb.checked = false;
      });
    });
  });
  tbody.querySelectorAll(".eti-todos").forEach((cb) => {
    cb.addEventListener("change", () => {
      const id = cb.dataset.id;
      tbody.querySelectorAll(`.eti-tipo[data-id="${id}"]`).forEach((tCb) => {
        tCb.disabled = cb.checked;
        if (cb.checked) tCb.checked = false;
      });
    });
  });
  tbody.querySelectorAll(".ecc-todos").forEach((cb) => {
    cb.addEventListener("change", () => {
      const id = cb.dataset.id;
      tbody.querySelectorAll(`.ecc-centro[data-id="${id}"]`).forEach((tCb) => {
        tCb.disabled = cb.checked;
        if (cb.checked) tCb.checked = false;
      });
    });
  });

  tbody.querySelectorAll(".btn-guardar-modulos").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.dataset.id;
      const modulos = [...tbody.querySelectorAll(`.em-modulo[data-id="${id}"]:checked`)].map((cb) => cb.value);
      const res = await fetch(`${AUTH_API_BASE}/auth/users/${id}/modulos`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ modulos }),
      });
      if (!res.ok) {
        mostrarAviso("No se pudieron guardar los módulos.");
        return;
      }
      loadUsers(currentUserId);
    });
  });

  tbody.querySelectorAll(".btn-guardar-tiendas").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.dataset.id;
      const todas = document.getElementById(`et-todas-${id}`).checked;
      const tiendas = todas
        ? []
        : [...tbody.querySelectorAll(`.et-tienda[data-id="${id}"]:checked`)].map((cb) => cb.value);
      const res = await fetch(`${AUTH_API_BASE}/auth/users/${id}/tiendas`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tiendas }),
      });
      if (!res.ok) {
        mostrarAviso("No se pudieron guardar las tiendas.");
        return;
      }
      loadUsers(currentUserId);
    });
  });

  tbody.querySelectorAll(".btn-guardar-tipos-informe").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.dataset.id;
      const todos = document.getElementById(`eti-todos-${id}`).checked;
      const tipos_informes = todos
        ? []
        : [...tbody.querySelectorAll(`.eti-tipo[data-id="${id}"]:checked`)].map((cb) => cb.value);
      const res = await fetch(`${AUTH_API_BASE}/auth/users/${id}/tipos-informes`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tipos_informes }),
      });
      if (!res.ok) {
        mostrarAviso("No se pudieron guardar los informes.");
        return;
      }
      loadUsers(currentUserId);
    });
  });

  tbody.querySelectorAll(".btn-guardar-clima-centros").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.dataset.id;
      const todos = document.getElementById(`ecc-todos-${id}`).checked;
      const centros = todos
        ? []
        : [...tbody.querySelectorAll(`.ecc-centro[data-id="${id}"]:checked`)].map((cb) => cb.value);
      const res = await fetch(`${AUTH_API_BASE}/auth/users/${id}/clima-centros`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ centros }),
      });
      if (!res.ok) {
        mostrarAviso("No se pudieron guardar los centros de Clima Laboral.");
        return;
      }
      loadUsers(currentUserId);
    });
  });

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
        mostrarAviso(body.detail || "No se pudo cambiar el rol.");
      }
      loadUsers(currentUserId);
    });
  });

  tbody.querySelectorAll(".btn-guardar-pin").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.dataset.id;
      const input = tbody.querySelector(`.pin-input[data-id="${id}"]`);
      const pin = input.value.trim();
      if (!/^\d{4}$/.test(pin)) {
        mostrarAviso("El PIN debe ser de 4 dígitos.");
        return;
      }
      const res = await fetch(`${AUTH_API_BASE}/auth/users/${id}/pin`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pin }),
      });
      if (!res.ok) {
        mostrarAviso("No se pudo guardar el PIN.");
      } else {
        mostrarAviso("PIN actualizado.");
      }
    });
  });

  tbody.querySelectorAll(".btn-reset-pin").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.dataset.id;
      if (!(await pedirConfirmacion("¿Borrar el PIN de este usuario? La próxima vez que entre, tendrá que crear uno nuevo."))) return;
      const res = await fetch(`${AUTH_API_BASE}/auth/users/${id}/reset-pin`, { method: "POST" });
      if (!res.ok) {
        mostrarAviso("No se pudo resetear el PIN.");
        return;
      }
      loadUsers(currentUserId);
    });
  });

  tbody.querySelectorAll(".btn-delete-user").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!(await pedirConfirmacion("¿Eliminar este usuario?"))) return;
      const id = btn.dataset.id;
      const res = await fetch(`${AUTH_API_BASE}/auth/users/${id}`, { method: "DELETE" });
      if (!res.ok) {
        mostrarAviso("No se pudo eliminar el usuario.");
      } else {
        loadUsers(currentUserId);
      }
    });
  });
}

function wireBackup() {
  const errorEl = document.getElementById("backup-error");
  const okEl = document.getElementById("backup-ok");

  document.getElementById("btn-descargar-backup").href = `${AUTH_API_BASE}/admin/backup/descargar`;

  const input = document.getElementById("input-restaurar-backup");
  input.addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    errorEl.hidden = true;
    okEl.hidden = true;
    if (!(await pedirConfirmacion(
      "Esto SOBREESCRIBE toda la base de datos actual (Test, Informes, Boletines, Reclutamiento, etc.) con el " +
      "contenido de este archivo. Todo lo que se haya recibido después de esta copia se perderá. ¿Continuar?"
    ))) {
      e.target.value = "";
      return;
    }
    const formData = new FormData();
    formData.append("file", file);
    const res = await fetch(`${AUTH_API_BASE}/admin/backup/restaurar`, { method: "POST", body: formData });
    e.target.value = "";
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      errorEl.textContent = err.detail || "No se pudo restaurar la copia.";
      errorEl.hidden = false;
      return;
    }
    okEl.textContent = "Base de datos restaurada. Recarga la página para ver los datos actualizados.";
    okEl.hidden = false;
  });
}

function wireRetencion() {
  const mesesInput = document.getElementById("retencion-meses");
  const resultadoEl = document.getElementById("retencion-resultado");
  const listaEl = document.getElementById("retencion-lista");
  const btnVer = document.getElementById("btn-ver-retencion");
  const btnPurgar = document.getElementById("btn-purgar-retencion");
  let ultimaLista = [];

  btnVer.addEventListener("click", async () => {
    const meses = Number(mesesInput.value) || 12;
    const res = await fetch(`${AUTH_API_BASE}/reclutamiento/candidatos/descartados-antiguos?meses=${meses}`);
    ultimaLista = res.ok ? await res.json() : [];
    if (ultimaLista.length === 0) {
      resultadoEl.textContent = "No hay ningún candidato descartado que lleve tanto tiempo sin actividad.";
      listaEl.innerHTML = "";
      btnPurgar.hidden = true;
      return;
    }
    resultadoEl.textContent = `${ultimaLista.length} candidato${ultimaLista.length === 1 ? "" : "s"} se borrarían:`;
    listaEl.innerHTML = ultimaLista.map((c) =>
      `<li>${escapeHTML(c.nombre_completo || "(sin nombre)")} — descartado el ${escapeHTML((c.actualizado_en || "").slice(0, 10))}</li>`
    ).join("");
    btnPurgar.hidden = false;
  });

  btnPurgar.addEventListener("click", async () => {
    const meses = Number(mesesInput.value) || 12;
    if (!(await pedirConfirmacion(`Esto borra PERMANENTEMENTE ${ultimaLista.length} ficha(s) de candidato, sus notas y archivos subidos. No se puede deshacer. ¿Continuar?`))) return;
    const res = await fetch(`${AUTH_API_BASE}/reclutamiento/candidatos/purgar-descartados?meses=${meses}`, { method: "POST" });
    if (!res.ok) {
      mostrarAviso("No se pudo completar el borrado.");
      return;
    }
    const data = await res.json();
    resultadoEl.textContent = `${data.borrados} candidato(s) borrados.`;
    listaEl.innerHTML = "";
    btnPurgar.hidden = true;
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
  wireBackup();
  wireRetencion();

  await loadRoles();
  await loadModulos();
  await loadUsers(user.id);
  renderNuModulosChecklist();
  renderNuTiendasChecklist();
  actualizarVisibilidadPorRol();
  document.getElementById("nu-rol").addEventListener("change", actualizarVisibilidadPorRol);

  document.addEventListener("click", (e) => {
    if (!e.target.closest(".checklist-wrap")) {
      document.querySelectorAll(".checklist-popover.visible").forEach((p) => p.classList.remove("visible"));
    }
  });

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
      tiendas: tiendasSeleccionadasNuevoUsuario(),
      modulos: modulosSeleccionadosNuevoUsuario(),
      tipos_informes: document.getElementById("nu-tipos-informe-wrap").hidden ? [] : tiposInformeSeleccionadosNuevoUsuario(),
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
    document.getElementById("nu-tienda-todas").checked = true;
    renderNuModulosChecklist();
    renderNuTiendasChecklist();
    actualizarVisibilidadPorRol();
    loadUsers(user.id);
  });
});

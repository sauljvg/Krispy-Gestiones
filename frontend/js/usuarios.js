let ROLES_CACHE = [];
let MODULOS_CACHE = [];
let USUARIOS_CACHE = []; // último fetch de /auth/users -- para poder re-filtrar por búsqueda sin volver a pedirlo
let CURRENT_USER_ID = null;
// Popover visible (checklist-popover) -> botón "Editar" que lo abrió -- con
// position:fixed el popover no se mueve solo con el scroll de la página, así
// que hay que reposicionarlo a mano en cada scroll (ver listener global).
const POPOVER_BOTON = new WeakMap();

function posicionarPopover(popover, btn) {
  const r = btn.getBoundingClientRect();
  const anchoPopover = popover.offsetWidth || 220;
  let left = r.left;
  if (left + anchoPopover > window.innerWidth - 8) left = window.innerWidth - anchoPopover - 8;
  if (left < 8) left = 8;
  let top = r.bottom + 6;
  const altoPopover = popover.offsetHeight || 300;
  if (top + altoPopover > window.innerHeight - 8) top = Math.max(8, r.top - altoPopover - 6);
  popover.style.left = `${left}px`;
  popover.style.top = `${top}px`;
}
let TIPOS_INFORME_CACHE = null; // null = todavía no se ha pedido (se carga la primera vez que hace falta)
let CLIMA_CENTROS_CACHE = null; // idem, para el checklist de restricción por centro de Clima Laboral

// escapeHTML ahora vive en common.js (cargado antes que este script).

// Mismas tiendas del selector de Reseñas (KK + SAONA) — ParqueSur es una
// sola ficha de Google (fábrica y tienda comparten la misma reseña pública),
// así que no hay forma de separarlas a nivel de datos. La restricción por
// tienda no distingue empresa: a un usuario con módulo saona_resenas se le
// puede limitar a "Saona Madnum" igual que a uno de Reseñas KK a "Caleido".
const TIENDAS_DISPONIBLES = [
  "Caleido", "Gran Plaza 2", "La Gavia", "ParqueSur", "Plenilunio", "Princesa",
  "Saona Madnum", "Saona Salamanca",
];

// Un centro/tienda es de Saona si su nombre empieza por "Saona"; el resto es
// Krispy Kreme. Se usa para dividir el checklist en dos grupos ("Todas KK" /
// "Todas Saona") en vez de un único "Todas" que mezcla las dos marcas
// (pedido explícito del usuario: quería poder dar "todas las de KK" a un
// gerente sin darle también las de Saona).
function esDeSaona(nombre) {
  return /^saona\b/i.test((nombre || "").trim());
}

// Genera el interior de un checklist-popover agrupado por marca. `prefix` es
// "et" (tiendas) o "ecc" (centros de Clima). El "Sin restricción" de arriba
// = array vacío = ve todo (comportamiento de siempre, además cubre tiendas
// futuras). Cada grupo tiene su propio "Todas las de <marca>" que solo
// marca/desmarca las casillas de ESE grupo.
function checklistAgrupadoHTML({ prefix, userId, items, seleccionados, masterLabel }) {
  const sinRestriccion = !seleccionados || seleccionados.length === 0;
  const sel = new Set(seleccionados || []);
  const grupos = [
    { clave: "kk", etiqueta: "Krispy Kreme", lista: items.filter((x) => !esDeSaona(x)) },
    { clave: "saona", etiqueta: "Saona", lista: items.filter(esDeSaona) },
  ].filter((g) => g.lista.length > 0);

  const master = `
    <div class="checklist-row" style="border-bottom:1px solid var(--border); padding-bottom:6px; margin-bottom:4px;">
      <input type="checkbox" id="${prefix}-todas-${userId}" class="${prefix}-todas" data-id="${userId}" ${sinRestriccion ? "checked" : ""}>
      <label for="${prefix}-todas-${userId}">${escapeHTML(masterLabel)}</label>
    </div>`;

  const gruposHTML = grupos.map((g) => {
    const todasGrupo = g.lista.every((x) => sel.has(x));
    const filas = g.lista.map((x) => {
      const idx = items.indexOf(x);
      return `
        <div class="checklist-row">
          <input type="checkbox" id="${prefix}-${userId}-${idx}" class="${prefix}-item" data-id="${userId}" data-grupo="${g.clave}" value="${escapeHTML(x)}"
            ${sel.has(x) ? "checked" : ""} ${sinRestriccion ? "disabled" : ""}>
          <label for="${prefix}-${userId}-${idx}">${escapeHTML(x)}</label>
        </div>`;
    }).join("");
    return `
      <div class="checklist-grupo-titulo" style="font-size:10px; text-transform:uppercase; letter-spacing:.04em; color:var(--text-secondary); margin:8px 0 2px;">${escapeHTML(g.etiqueta)}</div>
      <div class="checklist-row" style="font-weight:600;">
        <input type="checkbox" class="${prefix}-grupo" data-id="${userId}" data-grupo="${g.clave}" ${todasGrupo && !sinRestriccion ? "checked" : ""} ${sinRestriccion ? "disabled" : ""}>
        <label>Todas las de ${escapeHTML(g.etiqueta)}</label>
      </div>
      ${filas}`;
  }).join("");

  return master + gruposHTML;
}

function fmtFecha(iso) {
  if (!iso) return "";
  return iso.slice(0, 10);
}

async function loadRoles() {
  const res = await fetch(`${AUTH_API_BASE}/auth/roles`);
  ROLES_CACHE = await res.json();
  document.getElementById("roles-datalist").innerHTML = ROLES_CACHE.map((r) => `<option value="${escapeHTML(r.value)}">${escapeHTML(r.label)}</option>`).join("");
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
  document.getElementById("nu-tiendas-wrap").hidden = !(modulos.includes("resenas") || modulos.includes("saona_resenas"));
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
  // El mismo centro restringe Clima Laboral Y Planificador de turnos (ver
  // usuario_clima_centros, reutilizada por los dos módulos) -- se muestra
  // si tiene cualquiera de los cuatro.
  const tieneClima =
    modulos.includes("clima") || modulos.includes("saona_clima") ||
    modulos.includes("planificador") || modulos.includes("saona_planificador");
  const climaWrap = document.getElementById("nu-clima-centros-wrap");
  climaWrap.hidden = !tieneClima;
  if (tieneClima && !climaWrap.dataset.cargado) {
    climaWrap.dataset.cargado = "1";
    await renderNuClimaCentrosChecklist();
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
    document.getElementById("nu-clima-centros-wrap").hidden = true;
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

async function renderNuClimaCentrosChecklist() {
  const centros = await loadClimaCentrosSiHaceFalta();
  const wrap = document.getElementById("nu-clima-centros-checklist");
  wrap.innerHTML = centros
    .map(
      (c, i) => `
    <div class="checklist-row">
      <input type="checkbox" id="nu-clima-centro-${i}" class="nu-clima-centro-check" value="${escapeHTML(c)}" disabled>
      <label for="nu-clima-centro-${i}">${escapeHTML(c)}</label>
    </div>`
    )
    .join("");
  const todos = document.getElementById("nu-clima-centro-todos");
  todos.onchange = () => {
    wrap.querySelectorAll(".nu-clima-centro-check").forEach((cb) => {
      cb.disabled = todos.checked;
      if (todos.checked) cb.checked = false;
    });
  };
}

function climaCentrosSeleccionadosNuevoUsuario() {
  if (document.getElementById("nu-clima-centro-todos").checked) return [];
  return [...document.querySelectorAll(".nu-clima-centro-check:checked")].map((cb) => cb.value);
}

// --- Tabla de usuarios existentes ---

function filaUsuarioHTML(u, currentUserId) {
  return `
      <tr data-id="${u.id}">
        <td><input type="text" class="username-input" data-id="${u.id}" value="${escapeHTML(u.username)}" style="width:90%;"></td>
        <td><input type="text" class="nombre-input" data-id="${u.id}" value="${escapeHTML(u.nombre)}" style="width:90%;"></td>
        <td><input type="text" class="rol-input" list="roles-datalist" data-id="${u.id}" value="${escapeHTML(u.rol)}" style="width:90%;" ${u.id === currentUserId ? "disabled" : ""}></td>
        <td>
          ${
            u.rol === "admin"
              ? `<span class="staff-hint">Todo (admin)</span>`
              : `<button type="button" class="btn btn-ghost btn-editar-permisos" data-id="${u.id}">Editar</button>`
          }
        </td>
        <td>
          <input type="password" class="pin-input" data-id="${u.id}" value="${u.pin || ""}" placeholder="sin PIN" maxlength="4" style="width:60px; text-align:center;">
          <button type="button" class="btn-mini btn-mostrar-pin" data-id="${u.id}" title="Mostrar/ocultar PIN" aria-label="Mostrar u ocultar el PIN">👁</button>
        </td>
        <td>${fmtFecha(u.creado)}</td>
        <td>
          <div class="usr-acciones">
            <button type="button" class="btn btn-ghost btn-guardar-pin" data-id="${u.id}">Guardar PIN</button>
            ${u.pin ? `<button type="button" class="btn btn-ghost btn-reset-pin" data-id="${u.id}" title="Borra el PIN — al volver a entrar, el usuario crea uno nuevo">Resetear PIN</button>` : ""}
            ${u.id === currentUserId ? "" : `<button type="button" class="btn btn-ghost btn-delete-user" data-id="${u.id}">Eliminar</button>`}
          </div>
        </td>
      </tr>`;
}

// --- Modal "Editar permisos" (módulos + tiendas/informes/centros) ---
// Un único modal para toda la fila, en vez de 4 popovers por columna (uno
// por módulo restringible) -- así la tabla no tiene scroll horizontal y
// se guarda todo de una vez.

let EDITANDO_USUARIO = null; // el usuario que está abierto en el modal ahora mismo

// Marca/desmarca en bloque un checklist agrupado por marca (KK/Saona) --
// misma lógica que se usaba por fila, generalizada a cualquier `root` (aquí
// siempre el modal, que solo tiene una instancia en el DOM a la vez).
function wireChecklistAgrupadoEn(root, prefix) {
  root.querySelectorAll(`.${prefix}-todas`).forEach((cb) => {
    cb.addEventListener("change", () => {
      root.querySelectorAll(`.${prefix}-item, .${prefix}-grupo`).forEach((x) => {
        x.disabled = cb.checked;
        if (cb.checked) x.checked = false;
      });
    });
  });
  root.querySelectorAll(`.${prefix}-grupo`).forEach((cb) => {
    cb.addEventListener("change", () => {
      const grupo = cb.dataset.grupo;
      root.querySelectorAll(`.${prefix}-item[data-grupo="${grupo}"]`).forEach((x) => {
        x.checked = cb.checked;
      });
    });
  });
  root.querySelectorAll(`.${prefix}-item`).forEach((cb) => {
    cb.addEventListener("change", () => {
      const grupo = cb.dataset.grupo;
      const items = [...root.querySelectorAll(`.${prefix}-item[data-grupo="${grupo}"]`)];
      const grupoCb = root.querySelector(`.${prefix}-grupo[data-grupo="${grupo}"]`);
      if (grupoCb) grupoCb.checked = items.length > 0 && items.every((x) => x.checked);
    });
  });
}

function upModulosSeleccionados() {
  return [...document.querySelectorAll(".up-modulo-check:checked")].map((cb) => cb.value);
}

// Un módulo puede estar checkeado ahora mismo en el modal aunque el usuario
// no lo tuviera al abrirlo (el admin lo acaba de marcar) -- por eso mira el
// checkbox en vivo, no u.modulos.
function actualizarVisibilidadDependientesEditar() {
  const modulos = upModulosSeleccionados();
  document.getElementById("up-tiendas-wrap").hidden = !(modulos.includes("resenas") || modulos.includes("saona_resenas"));
  const tieneInformes = modulos.includes("informes") || modulos.includes("saona_informes");
  document.getElementById("up-tipos-informe-wrap").hidden = !tieneInformes;
  // El mismo centro restringe Clima Laboral Y Planificador de turnos (ver
  // usuario_clima_centros, reutilizada por los dos módulos) -- se muestra
  // si tiene cualquiera de los cuatro.
  const tieneClimaOPlanificador =
    modulos.includes("clima") || modulos.includes("saona_clima") ||
    modulos.includes("planificador") || modulos.includes("saona_planificador");
  document.getElementById("up-clima-centros-wrap").hidden = !tieneClimaOPlanificador;
}

function renderUpModulosChecklist(u) {
  const wrap = document.getElementById("up-modulos-checklist");
  wrap.innerHTML = MODULOS_CACHE.map(
    (m, i) => `
    <div class="checklist-row">
      <input type="checkbox" id="up-modulo-${i}" class="up-modulo-check" value="${m.value}" ${(u.modulos || []).includes(m.value) ? "checked" : ""}>
      <label for="up-modulo-${i}">${escapeHTML(m.label)}</label>
    </div>`
  ).join("");
  wrap.querySelectorAll(".up-modulo-check").forEach((cb) => {
    cb.addEventListener("change", actualizarVisibilidadDependientesEditar);
  });
}

function renderUpTiendasChecklist(u) {
  const wrap = document.getElementById("up-tiendas-wrap");
  wrap.querySelector("#up-tiendas-checklist").innerHTML = checklistAgrupadoHTML({
    prefix: "up-et", userId: "x", items: TIENDAS_DISPONIBLES, seleccionados: u.tiendas,
    masterLabel: "Todas las tiendas (sin restricción)",
  });
  wireChecklistAgrupadoEn(wrap, "up-et");
}

async function renderUpTiposInformeChecklist(u) {
  const tipos = await loadTiposInformeSiHaceFalta();
  const wrap = document.getElementById("up-tipos-informe-checklist");
  const sinRestriccion = !u.tipos_informes || u.tipos_informes.length === 0;
  const sel = new Set(u.tipos_informes || []);
  wrap.innerHTML = tipos.map(
    (t, i) => `
    <div class="checklist-row">
      <input type="checkbox" id="up-tipo-informe-${i}" class="up-tipo-informe-check" value="${t.clave}"
        ${sel.has(t.clave) ? "checked" : ""} ${sinRestriccion ? "disabled" : ""}>
      <label for="up-tipo-informe-${i}">${escapeHTML(t.nombre)}</label>
    </div>`
  ).join("");
  const todos = document.getElementById("up-tipo-informe-todos");
  todos.checked = sinRestriccion;
  todos.onchange = () => {
    wrap.querySelectorAll(".up-tipo-informe-check").forEach((cb) => {
      cb.disabled = todos.checked;
      if (todos.checked) cb.checked = false;
    });
  };
}

async function renderUpClimaCentrosChecklist(u) {
  const centros = await loadClimaCentrosSiHaceFalta();
  const wrap = document.getElementById("up-clima-centros-wrap");
  wrap.querySelector("#up-clima-centros-checklist").innerHTML = checklistAgrupadoHTML({
    prefix: "up-ecc", userId: "x", items: centros, seleccionados: u.clima_centros,
    masterLabel: "Todos los centros (sin restricción)",
  });
  wireChecklistAgrupadoEn(wrap, "up-ecc");
}

async function abrirDialogoPermisos(u) {
  EDITANDO_USUARIO = u;
  document.getElementById("up-nombre").textContent = `${u.nombre} (${u.username})`;
  document.getElementById("up-apodo").value = u.apodo || "";
  document.getElementById("up-error").hidden = true;
  document.getElementById("up-ok").hidden = true;
  renderUpModulosChecklist(u);
  renderUpTiendasChecklist(u);
  await renderUpTiposInformeChecklist(u);
  await renderUpClimaCentrosChecklist(u);
  actualizarVisibilidadDependientesEditar();
  document.getElementById("usr-dialog-permisos").showModal();
}

async function guardarPermisos() {
  if (!EDITANDO_USUARIO) return;
  const id = EDITANDO_USUARIO.id;
  const error = document.getElementById("up-error");
  const ok = document.getElementById("up-ok");
  error.hidden = true;
  ok.hidden = true;

  const modulos = upModulosSeleccionados();
  const tiendas = document.getElementById("up-et-todas-x").checked
    ? []
    : [...document.querySelectorAll(".up-et-item:checked")].map((cb) => cb.value);
  const tipos_informes = document.getElementById("up-tipo-informe-todos").checked
    ? []
    : [...document.querySelectorAll(".up-tipo-informe-check:checked")].map((cb) => cb.value);
  const centros = document.getElementById("up-ecc-todas-x").checked
    ? []
    : [...document.querySelectorAll(".up-ecc-item:checked")].map((cb) => cb.value);

  const peticiones = [
    fetch(`${AUTH_API_BASE}/auth/users/${id}/modulos`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ modulos }),
    }),
    fetch(`${AUTH_API_BASE}/auth/users/${id}/tiendas`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ tiendas }),
    }),
    fetch(`${AUTH_API_BASE}/auth/users/${id}/tipos-informes`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ tipos_informes }),
    }),
    fetch(`${AUTH_API_BASE}/auth/users/${id}/clima-centros`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ centros }),
    }),
    fetch(`${AUTH_API_BASE}/auth/users/${id}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ apodo: document.getElementById("up-apodo").value.trim() }),
    }),
  ];
  const resultados = await Promise.all(peticiones);
  if (resultados.some((r) => !r.ok)) {
    error.textContent = "No se pudieron guardar todos los cambios. Vuelve a intentarlo.";
    error.hidden = false;
    return;
  }
  document.getElementById("usr-dialog-permisos").close();
  loadUsers(CURRENT_USER_ID);
}

function wireDialogoPermisos() {
  document.getElementById("up-cerrar").addEventListener("click", () => document.getElementById("usr-dialog-permisos").close());
  document.getElementById("up-guardar").addEventListener("click", guardarPermisos);
}

const ORDEN_ROLES_AGRUPADO = ["admin", "director_operaciones", "area_manager", "rrhh", "gerente", "colaborador"];

function normalizarBusqueda(s) {
  return (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();
}

// Un usuario no tiene una columna "empresa" propia -- se deduce de sus
// módulos (cualquier "saona_*" lo marca como Saona). Alguien con módulos de
// las dos marcas a la vez cuenta como "Ambas" -- caso raro pero real (p.ej.
// admin-like sin serlo del todo), mejor mostrarlo así que forzarlo a una.
function empresaDeUsuario(u) {
  const modulos = u.modulos || [];
  const tieneSaona = modulos.some((m) => m.startsWith("saona_"));
  const tieneKK = modulos.some((m) => !m.startsWith("saona_"));
  if (tieneSaona && tieneKK) return "Ambas";
  if (tieneSaona) return "Saona";
  return "Krispy Kreme";
}

async function loadUsers(currentUserId) {
  CURRENT_USER_ID = currentUserId;
  await loadTiposInformeSiHaceFalta();
  await loadClimaCentrosSiHaceFalta();
  const res = await fetch(`${AUTH_API_BASE}/auth/users`);
  USUARIOS_CACHE = await res.json();
  renderUsuariosFiltrados();
}

// Agrupado por rol (desplegable por grupo, cada uno su propia tabla con
// cabecera) y filtrable por nombre/usuario -- antes era una única tabla
// plana, manejable con pocos usuarios pero que iba a volverse muy larga de
// recorrer a medida que crece la plantilla.
function renderUsuariosFiltrados() {
  const users = USUARIOS_CACHE;
  const currentUserId = CURRENT_USER_ID;
  const q = normalizarBusqueda(document.getElementById("users-buscar")?.value);
  const filtrados = q
    ? users.filter((u) => normalizarBusqueda(u.username).includes(q) || normalizarBusqueda(u.nombre).includes(q))
    : users;

  const cabecera = `<thead><tr><th>Usuario</th><th>Nombre</th><th>Rol</th><th>Accesos</th><th>PIN</th><th>Creado</th><th></th></tr></thead>`;

  const tbody = document.getElementById("users-list");
  if (filtrados.length === 0) {
    tbody.innerHTML = `<p class="staff-hint">Sin usuarios que coincidan con la búsqueda.</p>`;
    return;
  }

  function tablaHTML(usuariosGrupo) {
    return `
      <div class="store-ranking-wrap">
        <table class="staff-table staff-table-usuarios">
          ${cabecera}
          <tbody>${usuariosGrupo.map((u) => filaUsuarioHTML(u, currentUserId)).join("")}</tbody>
        </table>
      </div>`;
  }

  function detailsHTML(label, usuariosGrupo, { anidado = false } = {}) {
    const estilo = anidado
      ? 'style="margin:10px 0 10px 16px; border-left:2px solid var(--border); padding-left:12px;"'
      : 'style="margin-bottom:16px;"';
    const tamanoTexto = anidado ? "font-size:14px;" : "font-size:16px;";
    return `
        <details class="tabla-desplegable" open ${estilo}>
          <summary style="cursor:pointer; font-weight:600; padding:6px 0; ${tamanoTexto}">${escapeHTML(label)} (${usuariosGrupo.length})</summary>
          ${tablaHTML(usuariosGrupo)}
        </details>`;
  }

  function labelDeRol(rol) {
    return (ROLES_CACHE.find((r) => r.value === rol) || {}).label || rol;
  }

  // Orden dentro de cada marca: roles conocidos en el orden de
  // ORDEN_ROLES_AGRUPADO (sin admin, que va aparte arriba), luego cualquier
  // rol escrito a mano (p.ej. "Marketing") alfabéticamente, para que uno
  // nuevo no aparezca siempre al final sin criterio.
  function rolesOrdenadosDe(usuariosGrupo) {
    const porRol = new Map();
    usuariosGrupo.forEach((u) => {
      if (!porRol.has(u.rol)) porRol.set(u.rol, []);
      porRol.get(u.rol).push(u);
    });
    const conocidos = ORDEN_ROLES_AGRUPADO.filter((r) => r !== "admin" && porRol.has(r));
    const personalizados = [...porRol.keys()]
      .filter((r) => r !== "admin" && !ORDEN_ROLES_AGRUPADO.includes(r))
      .sort((a, b) => a.localeCompare(b));
    return [...conocidos, ...personalizados].map((rol) => ({ rol, usuarios: porRol.get(rol) }));
  }

  // Admin arriba de todo, sin dividir por marca (un admin gestiona las dos) --
  // luego Krispy Kreme y Saona, cada una con sus roles anidados dentro
  // (Area Manager, Director de Operaciones, Gerente, y cualquier rol
  // personalizado). "Ambas" (alguien con módulos de las dos marcas a la
  // vez) se deja igual que las otras dos, al final.
  const admins = filtrados.filter((u) => u.rol === "admin");
  const resto = filtrados.filter((u) => u.rol !== "admin");
  const porEmpresa = new Map();
  resto.forEach((u) => {
    const empresa = empresaDeUsuario(u);
    if (!porEmpresa.has(empresa)) porEmpresa.set(empresa, []);
    porEmpresa.get(empresa).push(u);
  });

  let html = "";
  if (admins.length > 0) html += detailsHTML("Admin", admins);
  for (const empresa of ["Krispy Kreme", "Saona", "Ambas"]) {
    if (!porEmpresa.has(empresa)) continue;
    const grupoEmpresa = porEmpresa.get(empresa);
    const subgrupos = rolesOrdenadosDe(grupoEmpresa)
      .map(({ rol, usuarios }) => detailsHTML(labelDeRol(rol), usuarios, { anidado: true }))
      .join("");
    html += `
        <details class="tabla-desplegable-empresa" open style="margin-bottom:20px;">
          <summary style="cursor:pointer; font-weight:700; font-size:17px; padding:8px 0;">${escapeHTML(empresa)} (${grupoEmpresa.length})</summary>
          ${subgrupos}
        </details>`;
  }
  tbody.innerHTML = html;

  // Editar módulos/tiendas/informes/centros de este usuario -- todo junto
  // en un único modal (antes eran 4 popovers, uno por columna, que hacían
  // la tabla larguísima con scroll horizontal infinito).
  tbody.querySelectorAll(".btn-editar-permisos").forEach((btn) => {
    btn.addEventListener("click", () => {
      const u = users.find((x) => String(x.id) === String(btn.dataset.id));
      if (u) abrirDialogoPermisos(u);
    });
  });

  // Texto libre (antes un <select> cerrado a los 6 roles de siempre) -- se
  // guarda solo al salir del campo (blur), igual que username-input, y solo
  // si de verdad cambió.
  tbody.querySelectorAll(".rol-input").forEach((input) => {
    input.addEventListener("blur", async () => {
      const id = input.dataset.id;
      const valor = input.value.trim();
      const original = users.find((u) => String(u.id) === String(id));
      if (!valor || (original && original.rol === valor)) {
        input.value = original ? original.rol : valor;
        return;
      }
      const res = await fetch(`${AUTH_API_BASE}/auth/users/${id}/rol`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rol: valor }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        mostrarAviso(body.detail || "No se pudo cambiar el rol.");
      }
      loadUsers(currentUserId);
    });
  });

  // Usuario y nombre se guardan solos al salir del campo (blur) -- si no
  // cambió, no llama a la API. Antes el nombre solo se podía editar desde la
  // ficha de la persona en Evaluaciones 360 (se sincronizaba hacia aquí);
  // ahora también se puede editar aquí directamente y se sincroniza hacia
  // allá (mismo endpoint, ver auth_routes.py) -- pedido explícito del
  // usuario 15/09 para poder sustituir a un gerente sin borrar y crear la
  // cuenta de cero (perdiendo módulos, tiendas, PIN...).
  tbody.querySelectorAll(".username-input, .nombre-input").forEach((input) => {
    const campo = input.classList.contains("username-input") ? "username" : "nombre";
    input.addEventListener("blur", async () => {
      const id = input.dataset.id;
      const valor = input.value.trim();
      const original = users.find((u) => String(u.id) === String(id));
      if (!valor || (original && original[campo] === valor)) {
        input.value = original ? original[campo] : valor;
        return;
      }
      const res = await fetch(`${AUTH_API_BASE}/auth/users/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ [campo]: valor }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        mostrarAviso(body.detail || "No se pudo guardar el cambio.");
        loadUsers(currentUserId);
        return;
      }
      loadUsers(currentUserId);
    });
  });

  tbody.querySelectorAll(".btn-mostrar-pin").forEach((btn) => {
    btn.addEventListener("click", () => {
      const input = tbody.querySelector(`.pin-input[data-id="${btn.dataset.id}"]`);
      input.type = input.type === "password" ? "text" : "password";
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
  document.getElementById("users-buscar").addEventListener("input", renderUsuariosFiltrados);
  wireDialogoPermisos();
  renderNuModulosChecklist();
  renderNuTiendasChecklist();
  actualizarVisibilidadPorRol();
  document.getElementById("nu-rol").addEventListener("input", actualizarVisibilidadPorRol);

  document.addEventListener("click", (e) => {
    if (!e.target.closest(".checklist-wrap")) {
      document.querySelectorAll(".checklist-popover.visible").forEach((p) => p.classList.remove("visible"));
    }
  });
  window.addEventListener("scroll", () => {
    document.querySelectorAll(".checklist-popover.visible").forEach((p) => {
      const btn = POPOVER_BOTON.get(p);
      if (btn && document.contains(btn)) posicionarPopover(p, btn);
      else p.classList.remove("visible");
    });
  }, true);

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
      clima_centros: document.getElementById("nu-clima-centros-wrap").hidden ? [] : climaCentrosSeleccionadosNuevoUsuario(),
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
    document.getElementById("nu-clima-centro-todos").checked = true;
    document.querySelectorAll(".nu-clima-centro-check").forEach((cb) => {
      cb.checked = false;
      cb.disabled = true;
    });
    renderNuModulosChecklist();
    renderNuTiendasChecklist();
    actualizarVisibilidadPorRol();
    loadUsers(user.id);
  });
});

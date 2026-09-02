document.addEventListener("DOMContentLoaded", () => {
  const btn = document.getElementById("btn-hamburger");
  const menu = document.getElementById("hamburger-menu");
  if (!btn || !menu) return;

  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    menu.hidden = !menu.hidden;
    btn.setAttribute("aria-expanded", String(!menu.hidden));
  });

  menu.addEventListener("click", (e) => e.stopPropagation());

  document.addEventListener("click", () => {
    if (!menu.hidden) {
      menu.hidden = true;
      btn.setAttribute("aria-expanded", "false");
    }
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !menu.hidden) {
      menu.hidden = true;
      btn.setAttribute("aria-expanded", "false");
    }
  });
});

// Una sola campanita para las dos fuentes de notificaciones -- antes cada
// una tenía su propio icono junto al menú hamburguesa (respuestas nuevas de
// Test por un lado, avisos puntuales de trabajos en segundo plano como el
// relleno de CVs por otro), lo que dejaba dos campanas casi idénticas una
// al lado de la otra. Se combinan en un único botón/panel: el contador
// suma los dos totales, y el panel desplegable muestra ambas secciones
// (solo la(s) que tengan algo). Si ninguna de las dos fuentes tiene nada
// que mostrar (o fallan los fetch, p.ej. sin acceso), no se crea nada.
document.addEventListener("DOMContentLoaded", async () => {
  const wrap = document.querySelector(".hamburger-wrap");
  if (!wrap) return;

  const escapeHTML = (str) => {
    const div = document.createElement("div");
    div.textContent = str ?? "";
    return div.innerHTML;
  };

  const formatFecha = (iso) => {
    if (!iso) return "";
    const d = new Date(iso.replace(" ", "T") + "Z");
    if (Number.isNaN(d.getTime())) return "";
    return d.toLocaleString("es-ES", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
  };

  async function fetchJSON(url) {
    try {
      const res = await fetch(`${window.location.origin}${url}`);
      if (!res.ok) return null;
      return await res.json();
    } catch {
      return null;
    }
  }

  const [datosTests, datosAvisos] = await Promise.all([
    fetchJSON("/api/encuestas/notificaciones"),
    fetchJSON("/api/notificaciones"),
  ]);

  const tests = (datosTests && datosTests.tests) || [];
  const avisos = (datosAvisos && datosAvisos.notificaciones) || [];
  const total = (datosTests?.total || 0) + (datosAvisos?.total || 0);
  if (tests.length === 0 && avisos.length === 0) return;

  const seccionTests = tests.length
    ? `<p class="notif-tests-titulo">Respuestas nuevas</p>
       <ul class="notif-tests-lista">
         ${tests
           .map((t) => `<li><a href="/tests.html">${escapeHTML(t.titulo)}<span class="notif-tests-n">${t.nuevas}</span></a></li>`)
           .join("")}
       </ul>`
    : "";
  const seccionAvisos = avisos.length
    ? `<p class="notif-tests-titulo">Avisos</p>
       <ul class="notif-tests-lista">
         ${avisos
           .map(
             (n) => `<li><a href="${escapeHTML(n.url || "#")}" class="notif-aviso-item ${n.vista_en ? "" : "notif-aviso-no-vista"}">
               <span>${escapeHTML(n.mensaje)}</span><span class="notif-aviso-fecha">${formatFecha(n.creada_en)}</span>
             </a></li>`
           )
           .join("")}
       </ul>`
    : "";

  const badgeWrap = document.createElement("div");
  badgeWrap.className = "notif-badge-wrap";
  badgeWrap.innerHTML = `
    <button type="button" id="btn-notif" class="btn btn-ghost notif-badge-btn" aria-label="Notificaciones" aria-haspopup="true" aria-expanded="false">
      🔔${total > 0 ? `<span class="notif-badge-count">${total}</span>` : ""}
    </button>
    <div id="notif-panel" class="notif-tests-panel" hidden>
      ${seccionTests}
      ${seccionAvisos}
    </div>`;
  wrap.parentElement.insertBefore(badgeWrap, wrap);

  const notifBtn = badgeWrap.querySelector("#btn-notif");
  const notifPanel = badgeWrap.querySelector("#notif-panel");
  notifBtn.addEventListener("click", async (e) => {
    e.stopPropagation();
    notifPanel.hidden = !notifPanel.hidden;
    notifBtn.setAttribute("aria-expanded", String(!notifPanel.hidden));
    if (!notifPanel.hidden) {
      notifBtn.querySelector(".notif-badge-count")?.remove();
      notifPanel.querySelectorAll(".notif-aviso-no-vista").forEach((a) => a.classList.remove("notif-aviso-no-vista"));
      await Promise.all([
        fetch(`${window.location.origin}/api/encuestas/notificaciones/marcar-vistas`, { method: "POST" }),
        fetch(`${window.location.origin}/api/notificaciones/marcar-vistas`, { method: "POST" }),
      ]);
    }
  });
  notifPanel.addEventListener("click", (e) => e.stopPropagation());
  document.addEventListener("click", () => {
    if (!notifPanel.hidden) {
      notifPanel.hidden = true;
      notifBtn.setAttribute("aria-expanded", "false");
    }
  });
});

// Indicador de "trabajos de IA en curso" -- relleno de CVs en segundo plano
// (ver _progreso_lotes / /candidatos/lotes-en-progreso en
// reclutamiento_routes.py). Mismo patrón visual que las campanitas de
// arriba (icono + globo de conteo + panel desplegable) en vez de una barra
// a todo lo ancho, para que quede junto al resto de iconos del topbar. Se
// crea siempre (oculto si no hay nada activo) porque un lote puede empezar
// mientras el usuario ya está mirando esta pantalla.
document.addEventListener("DOMContentLoaded", async () => {
  // Solo tiene sentido en Reclutamiento -- en el resto de páginas no hay
  // nada que esté rellenando con IA en segundo plano.
  if (!window.location.pathname.endsWith("compartidos.html")) return;

  const wrap = document.querySelector(".hamburger-wrap");
  if (!wrap) return;

  const escapeHTML = (str) => {
    const div = document.createElement("div");
    div.textContent = str ?? "";
    return div.innerHTML;
  };

  const formatEta = (segundos) => {
    if (!segundos) return "";
    if (segundos < 60) return ` · ${segundos} s`;
    return ` · ~${Math.round(segundos / 60)} min`;
  };

  const badgeWrap = document.createElement("div");
  badgeWrap.className = "notif-badge-wrap";
  badgeWrap.hidden = true;
  badgeWrap.innerHTML = `
    <button type="button" id="btn-lotes-progreso" class="btn btn-ghost notif-badge-btn" aria-label="Relleno de CVs con IA en curso" aria-haspopup="true" aria-expanded="false">
      🤖<span class="notif-badge-count"></span>
    </button>
    <div id="lotes-progreso-panel" class="notif-tests-panel" hidden>
      <p class="notif-tests-titulo">Relleno de CVs con IA en curso</p>
      <ul id="lotes-progreso-lista" class="notif-tests-lista"></ul>
    </div>`;
  wrap.parentElement.insertBefore(badgeWrap, wrap);

  const btn = badgeWrap.querySelector("#btn-lotes-progreso");
  const panel = badgeWrap.querySelector("#lotes-progreso-panel");
  const lista = badgeWrap.querySelector("#lotes-progreso-lista");
  const contador = badgeWrap.querySelector(".notif-badge-count");

  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    panel.hidden = !panel.hidden;
    btn.setAttribute("aria-expanded", String(!panel.hidden));
  });
  panel.addEventListener("click", (e) => e.stopPropagation());
  document.addEventListener("click", () => {
    if (!panel.hidden) {
      panel.hidden = true;
      btn.setAttribute("aria-expanded", "false");
    }
  });

  async function actualizar() {
    let lotes;
    try {
      const res = await fetch(`${window.location.origin}/api/reclutamiento/candidatos/lotes-en-progreso`);
      if (!res.ok) return;
      lotes = await res.json();
    } catch {
      return;
    }
    if (!lotes || lotes.length === 0) {
      badgeWrap.hidden = true;
      return;
    }
    badgeWrap.hidden = false;
    contador.textContent = String(lotes.length);
    lista.innerHTML = lotes
      .map((l) => `<li>🤖 ${escapeHTML(l.titulo)}: ${l.procesados}/${l.total}${formatEta(l.eta_segundos)}</li>`)
      .join("");
  }

  await actualizar();
  setInterval(actualizar, 8000);
});

// Indicador de "quién está en línea ahora mismo" — solo se activa para el
// usuario "saul" (el backend devuelve 403 para cualquier otro, así que aquí
// simplemente se deja de consultar si el primer intento falla, sin
// comprobar el usuario aparte). Se actualiza cada 20s mientras la pestaña
// esté abierta para que se sienta "en vivo".
document.addEventListener("DOMContentLoaded", async () => {
  const wrap = document.querySelector(".hamburger-wrap");
  if (!wrap) return;

  const escapeHTML = (str) => {
    const div = document.createElement("div");
    div.textContent = str ?? "";
    return div.innerHTML;
  };

  async function fetchEnLinea() {
    try {
      const res = await fetch(`${window.location.origin}/api/auth/usuarios-en-linea`);
      if (!res.ok) return null;
      return await res.json();
    } catch {
      return null;
    }
  }

  const primero = await fetchEnLinea();
  if (!primero) return; // no es "saul", o falló la petición — no se vuelve a intentar

  const badgeWrap = document.createElement("div");
  badgeWrap.className = "en-linea-badge-wrap";
  badgeWrap.hidden = true;
  badgeWrap.innerHTML = `
    <button type="button" id="btn-en-linea" class="btn btn-ghost en-linea-badge-btn" aria-label="Usuarios en línea ahora" aria-haspopup="true" aria-expanded="false">
      🟢<span class="en-linea-badge-count"></span>
    </button>
    <div id="en-linea-panel" class="en-linea-panel" hidden>
      <p class="en-linea-titulo">En línea ahora</p>
      <ul class="en-linea-lista"></ul>
    </div>`;
  wrap.parentElement.insertBefore(badgeWrap, wrap);

  const btnEnLinea = badgeWrap.querySelector("#btn-en-linea");
  const panelEnLinea = badgeWrap.querySelector("#en-linea-panel");
  const countEnLinea = badgeWrap.querySelector(".en-linea-badge-count");
  const listaEnLinea = badgeWrap.querySelector(".en-linea-lista");

  btnEnLinea.addEventListener("click", (e) => {
    e.stopPropagation();
    panelEnLinea.hidden = !panelEnLinea.hidden;
    btnEnLinea.setAttribute("aria-expanded", String(!panelEnLinea.hidden));
  });
  panelEnLinea.addEventListener("click", (e) => e.stopPropagation());
  document.addEventListener("click", () => {
    if (!panelEnLinea.hidden) {
      panelEnLinea.hidden = true;
      btnEnLinea.setAttribute("aria-expanded", "false");
    }
  });

  function renderEnLinea(data) {
    const usuarios = (data && data.usuarios) || [];
    badgeWrap.hidden = usuarios.length === 0;
    if (usuarios.length === 0) return;
    countEnLinea.textContent = usuarios.length;
    listaEnLinea.innerHTML = usuarios
      .map((u) => `<li>🟢 ${escapeHTML(u.nombre)}</li>`)
      .join("");
  }

  renderEnLinea(primero);
  setInterval(async () => {
    const data = await fetchEnLinea();
    if (data) renderEnLinea(data);
  }, 20000);

  // Historial de accesos (mismo criterio "solo saul" que el badge de arriba
  // -- si llegamos hasta aquí es porque el fetch de usuarios-en-linea ya
  // tuvo éxito, así que no hace falta comprobar el usuario aparte). Botón
  // aparte del badge de "en línea" porque es un historial, no algo "en
  // vivo" -- se pide bajo demanda, no se refresca solo.
  const btnHistorial = document.createElement("button");
  btnHistorial.type = "button";
  btnHistorial.className = "btn btn-ghost en-linea-badge-btn";
  btnHistorial.title = "Historial de accesos";
  btnHistorial.setAttribute("aria-label", "Historial de accesos");
  btnHistorial.textContent = "🕒";
  wrap.parentElement.insertBefore(btnHistorial, wrap);

  const overlay = document.createElement("div");
  overlay.className = "historial-accesos-overlay";
  overlay.hidden = true;
  overlay.innerHTML = `
    <div class="historial-accesos-modal">
      <div class="historial-accesos-cabecera">
        <h3>Historial de accesos</h3>
        <button type="button" class="btn-cerrar-ficha-x" id="btn-cerrar-historial-accesos" title="Cerrar">✕</button>
      </div>
      <p class="staff-hint">Últimos 30 días. Solo tú puedes ver esto.</p>
      <h4>Inicios de sesión</h4>
      <div class="table-scroll"><table class="cobertura-table">
        <thead><tr><th>Usuario</th><th>Entró</th><th>Última actividad</th></tr></thead>
        <tbody id="historial-sesiones-body"></tbody>
      </table></div>
      <h4 style="margin-top:16px;">Módulos tocados</h4>
      <div class="table-scroll"><table class="cobertura-table">
        <thead><tr><th>Usuario</th><th>Módulo</th><th>Día</th><th>Primera vez</th><th>Última vez</th><th>Veces</th></tr></thead>
        <tbody id="historial-modulos-body"></tbody>
      </table></div>
    </div>`;
  document.body.appendChild(overlay);
  overlay.querySelector("#btn-cerrar-historial-accesos").addEventListener("click", () => {
    overlay.hidden = true;
  });
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) overlay.hidden = true;
  });

  btnHistorial.addEventListener("click", async (e) => {
    e.stopPropagation();
    const res = await fetch(`${window.location.origin}/api/auth/historial-accesos`);
    if (!res.ok) return;
    const data = await res.json();
    overlay.querySelector("#historial-sesiones-body").innerHTML = (data.sesiones || [])
      .map((s) => `<tr><td>${escapeHTML(s.nombre)}</td><td>${escapeHTML(s.login_en)}</td><td>${escapeHTML(s.ultima_actividad || "—")}</td></tr>`)
      .join("") || `<tr><td colspan="3" class="staff-hint">Sin datos</td></tr>`;
    overlay.querySelector("#historial-modulos-body").innerHTML = (data.modulos || [])
      .map((m) => `<tr><td>${escapeHTML(m.nombre)}</td><td>${escapeHTML(m.modulo)}</td><td>${escapeHTML(m.fecha)}</td><td>${escapeHTML(m.primera_vez)}</td><td>${escapeHTML(m.ultima_vez)}</td><td>${m.veces}</td></tr>`)
      .join("") || `<tr><td colspan="6" class="staff-hint">Sin datos</td></tr>`;
    overlay.hidden = false;
  });
});

// Botones ⓘ genéricos (.info-tip-wrap): en desktop ya se ven con :hover, pero
// el móvil no dispara hover de forma fiable con un tap — esto añade el toggle
// por clic/tap en cualquier página que use el patrón, sin tener que cablear
// cada instancia a mano.
document.addEventListener("click", (e) => {
  const btn = e.target.closest(".info-tip-btn");
  document.querySelectorAll(".info-tip-wrap.open").forEach((w) => {
    if (!btn || w !== btn.closest(".info-tip-wrap")) w.classList.remove("open");
  });
  if (btn) {
    e.stopPropagation();
    btn.closest(".info-tip-wrap").classList.toggle("open");
  }
});

// "David" -- asistente de IA del portal (Gemini). Botón flotante disponible
// en cualquier página que cargue topbar-menu.js (todas las internas), igual
// que el resto de widgets de este archivo. El historial se guarda en
// sessionStorage (sobrevive a navegar entre páginas dentro de la misma
// pestaña/sesión del navegador; se pierde al cerrarla, o con "Vaciar
// conversación") -- a propósito no se guarda en el servidor.
document.addEventListener("DOMContentLoaded", () => {
  const STORAGE_KEY = "david_historial";
  // Genérico a propósito, sin ejemplos de secciones concretas (Clima, Entrevista de Salida...):
  // no todos los usuarios tienen acceso a todo, y nombrar una sección que alguien no puede ver
  // solo despierta curiosidad por algo a lo que no puede entrar.
  const MENSAJE_BIENVENIDA = "Hola, soy David. Pregúntame cómo hacer cualquier cosa en este portal y te ayudaré a hacerlo.";

  const escapeHTML = (str) => {
    const div = document.createElement("div");
    div.textContent = str ?? "";
    return div.innerHTML;
  };

  const fab = document.createElement("button");
  fab.type = "button";
  fab.id = "david-fab";
  fab.className = "david-fab";
  fab.setAttribute("aria-label", "Preguntarle a David");
  fab.textContent = "💬";
  document.body.appendChild(fab);

  const panel = document.createElement("div");
  panel.id = "david-panel";
  panel.className = "david-panel";
  panel.hidden = true;
  panel.innerHTML = `
    <div class="david-head">
      <span>💬 David</span>
      <div class="david-head-acciones">
        <button type="button" class="david-vaciar" title="Vaciar conversación" aria-label="Vaciar conversación">🗑</button>
        <button type="button" class="david-cerrar" aria-label="Cerrar">✕</button>
      </div>
    </div>
    <div class="david-mensajes" id="david-mensajes"></div>
    <form class="david-form" id="david-form">
      <textarea id="david-input" placeholder="Escribe tu pregunta..." rows="1"></textarea>
      <button type="submit" id="david-enviar">➤</button>
    </form>`;
  document.body.appendChild(panel);

  const mensajesWrap = panel.querySelector("#david-mensajes");
  const form = panel.querySelector("#david-form");
  const input = panel.querySelector("#david-input");
  const btnEnviar = panel.querySelector("#david-enviar");
  let enviando = false;

  function cargarHistorial() {
    try {
      return JSON.parse(sessionStorage.getItem(STORAGE_KEY) || "[]");
    } catch {
      return [];
    }
  }
  let historial = cargarHistorial();

  function guardarHistorial() {
    if (historial.length > 20) historial = historial.slice(-20);
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(historial));
  }

  function formatearTexto(texto) {
    // A David se le pide que no use markdown, pero por si se le escapa
    // algún **negrita** suelto, se convierte en vez de mostrar los asteriscos.
    return escapeHTML(texto)
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/\n/g, "<br>");
  }

  function agregarMensaje(rol, texto) {
    const div = document.createElement("div");
    div.className = `david-msg david-msg-${rol}`;
    div.innerHTML = formatearTexto(texto);
    mensajesWrap.appendChild(div);
    mensajesWrap.scrollTop = mensajesWrap.scrollHeight;
    return div;
  }

  function reconstruirMensajes() {
    mensajesWrap.innerHTML = "";
    agregarMensaje("david", MENSAJE_BIENVENIDA);
    historial.forEach((t) => agregarMensaje(t.rol === "david" ? "david" : "user", t.texto));
  }
  reconstruirMensajes();

  fab.addEventListener("click", () => {
    panel.hidden = !panel.hidden;
    if (!panel.hidden) input.focus();
  });
  panel.querySelector(".david-cerrar").addEventListener("click", () => {
    panel.hidden = true;
  });
  panel.querySelector(".david-vaciar").addEventListener("click", async () => {
    if (!(await pedirConfirmacion("¿Vaciar toda la conversación con David?"))) return;
    historial = [];
    sessionStorage.removeItem(STORAGE_KEY);
    reconstruirMensajes();
  });

  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 110)}px`;
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      form.requestSubmit();
    }
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const mensaje = input.value.trim();
    if (!mensaje || enviando) return;
    enviando = true;
    btnEnviar.disabled = true;
    agregarMensaje("user", mensaje);
    input.value = "";
    input.style.height = "auto";
    const pensando = agregarMensaje("david", "…");
    try {
      const res = await fetch(`${window.location.origin}/api/david/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mensaje, historial }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "Error al preguntarle a David");
      pensando.innerHTML = formatearTexto(data.respuesta);
      historial.push({ rol: "user", texto: mensaje });
      historial.push({ rol: "david", texto: data.respuesta });
      guardarHistorial();
    } catch (err) {
      pensando.classList.add("david-msg-error");
      pensando.textContent = err.message || "No se pudo contactar a David. Inténtalo de nuevo.";
    } finally {
      mensajesWrap.scrollTop = mensajesWrap.scrollHeight;
      enviando = false;
      btnEnviar.disabled = false;
    }
  });
});

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

// Notificación de "hay respuestas nuevas de Test" junto al menú hamburguesa
// — solo para quien tiene el módulo Test, así que se comprueba el usuario
// aquí en vez de depender de que cada página avise (topbar-menu.js se carga
// en todas por igual). Si falla el fetch (sin acceso, 401, etc.) no se
// muestra nada; no es un error visible para el usuario.
document.addEventListener("DOMContentLoaded", async () => {
  const wrap = document.querySelector(".hamburger-wrap");
  if (!wrap) return;
  let data;
  try {
    const res = await fetch(`${window.location.origin}/api/encuestas/notificaciones`);
    if (!res.ok) return;
    data = await res.json();
  } catch {
    return;
  }
  if (!data || data.total === 0) return;

  const escapeHTML = (str) => {
    const div = document.createElement("div");
    div.textContent = str ?? "";
    return div.innerHTML;
  };

  const badgeWrap = document.createElement("div");
  badgeWrap.className = "notif-badge-wrap";
  badgeWrap.innerHTML = `
    <button type="button" id="btn-notif-tests" class="btn btn-ghost notif-badge-btn" aria-label="Respuestas nuevas de Test" aria-haspopup="true" aria-expanded="false">
      🔔<span class="notif-badge-count">${data.total}</span>
    </button>
    <div id="notif-tests-panel" class="notif-tests-panel" hidden>
      <p class="notif-tests-titulo">Respuestas nuevas</p>
      <ul class="notif-tests-lista">
        ${data.tests
          .map((t) => `<li><a href="/tests.html">${escapeHTML(t.titulo)}<span class="notif-tests-n">${t.nuevas}</span></a></li>`)
          .join("")}
      </ul>
    </div>`;
  wrap.parentElement.insertBefore(badgeWrap, wrap);

  const notifBtn = badgeWrap.querySelector("#btn-notif-tests");
  const notifPanel = badgeWrap.querySelector("#notif-tests-panel");
  notifBtn.addEventListener("click", async (e) => {
    e.stopPropagation();
    notifPanel.hidden = !notifPanel.hidden;
    notifBtn.setAttribute("aria-expanded", String(!notifPanel.hidden));
    if (!notifPanel.hidden) {
      notifBtn.querySelector(".notif-badge-count")?.remove();
      await fetch(`${window.location.origin}/api/encuestas/notificaciones/marcar-vistas`, { method: "POST" });
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

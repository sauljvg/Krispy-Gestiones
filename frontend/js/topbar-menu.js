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

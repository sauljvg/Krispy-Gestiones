// Sustituye a los alert()/confirm() nativos del navegador (se veían
// anticuados, fuera del estilo del portal) por un modal centrado con el
// mismo lenguaje visual que el resto de modales del portal (compartir,
// asignar a vacante, etc.): tarjeta con borde redondeado, botones
// btn-primary/btn-ghost, y una "✕" para cerrar. Se inyecta su propio CSS
// (con las variables de tema de siempre) para funcionar en CUALQUIER
// página sin depender de que esa página ya tenga estilos de modal propios.
//
// Uso: await mostrarAviso("mensaje") en vez de alert("mensaje");
//      if (!(await pedirConfirmacion("mensaje"))) return; en vez de
//      if (!confirm("mensaje")) return;
(function () {
  const ESTILOS = `
    .kdialog-overlay {
      position: fixed; inset: 0; background: rgba(0,0,0,0.55); display: none;
      align-items: center; justify-content: center; z-index: 1000; padding: 20px;
    }
    .kdialog-overlay.visible { display: flex; }
    .kdialog-box {
      position: relative; background: var(--surface-1); border: 1px solid var(--border);
      border-radius: 12px; padding: 24px; width: 100%; max-width: 400px;
      box-shadow: 0 12px 32px rgba(0,0,0,0.3); font-family: inherit;
    }
    .kdialog-cerrar {
      position: absolute; top: 10px; right: 10px; background: none; border: none; cursor: pointer;
      color: var(--text-secondary); font-size: 15px; line-height: 1; padding: 6px; border-radius: 6px;
    }
    .kdialog-cerrar:hover { color: var(--text-primary); background: var(--surface-page); }
    .kdialog-mensaje {
      margin: 4px 22px 20px 0; color: var(--text-primary); font-size: 14px;
      white-space: pre-wrap; line-height: 1.5;
    }
    .kdialog-acciones { display: flex; justify-content: flex-end; gap: 8px; }
    .kdialog-acciones .btn { min-width: 84px; }
  `;

  let overlay = null;
  let mensajeEl = null;
  let accionesEl = null;

  function inyectarEstilos() {
    if (document.getElementById("kdialog-estilos")) return;
    const style = document.createElement("style");
    style.id = "kdialog-estilos";
    style.textContent = ESTILOS;
    document.head.appendChild(style);
  }

  function asegurarOverlay() {
    if (overlay) return;
    inyectarEstilos();
    overlay = document.createElement("div");
    overlay.className = "kdialog-overlay";
    overlay.innerHTML = `
      <div class="kdialog-box" role="alertdialog" aria-modal="true">
        <button type="button" class="kdialog-cerrar" aria-label="Cerrar">✕</button>
        <p class="kdialog-mensaje"></p>
        <div class="kdialog-acciones"></div>
      </div>`;
    document.body.appendChild(overlay);
    mensajeEl = overlay.querySelector(".kdialog-mensaje");
    accionesEl = overlay.querySelector(".kdialog-acciones");
  }

  function mostrar(mensaje, botones) {
    asegurarOverlay();
    return new Promise((resolve) => {
      mensajeEl.textContent = mensaje;
      accionesEl.innerHTML = "";
      let resuelto = false;
      const terminar = (valor) => {
        if (resuelto) return;
        resuelto = true;
        overlay.classList.remove("visible");
        document.removeEventListener("keydown", onKeydown);
        resolve(valor);
      };
      botones.forEach(({ texto, clase, valor }) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = `btn ${clase}`;
        btn.textContent = texto;
        btn.addEventListener("click", () => terminar(valor));
        accionesEl.appendChild(btn);
      });
      overlay.querySelector(".kdialog-cerrar").onclick = () => terminar(false);
      function onKeydown(e) {
        if (e.key === "Escape") terminar(false);
        else if (e.key === "Enter") terminar(botones[botones.length - 1].valor);
      }
      document.addEventListener("keydown", onKeydown);
      overlay.classList.add("visible");
      requestAnimationFrame(() => accionesEl.querySelector("button")?.focus());
    });
  }

  window.mostrarAviso = function (mensaje) {
    return mostrar(String(mensaje), [{ texto: "Aceptar", clase: "btn-primary", valor: true }]);
  };

  window.pedirConfirmacion = function (mensaje) {
    return mostrar(String(mensaje), [
      { texto: "Cancelar", clase: "btn-ghost", valor: false },
      { texto: "Aceptar", clase: "btn-primary", valor: true },
    ]);
  };
})();

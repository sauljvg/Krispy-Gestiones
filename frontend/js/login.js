const API_BASE = `${window.location.origin}/api`;

let usuarioActual = "";
let tienePinActual = false;

function irAPaso(paso) {
  document.getElementById("login-form-usuario").hidden = paso !== "usuario";
  document.getElementById("login-form-pin").hidden = paso !== "pin";
}

document.getElementById("login-form-usuario").addEventListener("submit", async (e) => {
  e.preventDefault();
  const errorEl = document.getElementById("login-error-usuario");
  errorEl.hidden = true;

  const username = document.getElementById("login-username").value.trim();
  if (!username) return;

  try {
    const res = await fetch(`${API_BASE}/auth/check-username`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username }),
    });
    if (!res.ok) {
      errorEl.textContent = "Usuario no encontrado.";
      errorEl.hidden = false;
      return;
    }
    const body = await res.json();
    usuarioActual = username;
    tienePinActual = body.tiene_pin;

    const hint = document.getElementById("login-pin-hint");
    const confirmWrap = document.getElementById("login-pin-confirm-wrap");
    const submitBtn = document.getElementById("btn-login-pin-submit");
    if (tienePinActual) {
      hint.textContent = `Hola ${username}, ingresa tu PIN de 4 dígitos.`;
      confirmWrap.hidden = true;
      submitBtn.textContent = "Entrar";
    } else {
      hint.textContent = `Hola ${username}, todavía no tienes un PIN. Crea uno de 4 dígitos.`;
      confirmWrap.hidden = false;
      submitBtn.textContent = "Crear PIN y entrar";
    }
    document.getElementById("login-pin").value = "";
    document.getElementById("login-pin-confirm").value = "";
    irAPaso("pin");
    document.getElementById("login-pin").focus();
  } catch (err) {
    errorEl.textContent = "No se pudo conectar con el servidor.";
    errorEl.hidden = false;
  }
});

document.getElementById("btn-login-back").addEventListener("click", () => {
  irAPaso("usuario");
});

document.getElementById("login-form-pin").addEventListener("submit", async (e) => {
  e.preventDefault();
  const errorEl = document.getElementById("login-error-pin");
  errorEl.hidden = true;

  const pin = document.getElementById("login-pin").value.trim();
  if (!/^\d{4}$/.test(pin)) {
    errorEl.textContent = "El PIN debe ser de 4 dígitos.";
    errorEl.hidden = false;
    return;
  }

  if (!tienePinActual) {
    const confirmPin = document.getElementById("login-pin-confirm").value.trim();
    if (pin !== confirmPin) {
      errorEl.textContent = "Los PIN no coinciden.";
      errorEl.hidden = false;
      return;
    }
    const resCrear = await fetch(`${API_BASE}/auth/set-pin`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: usuarioActual, pin }),
    });
    if (!resCrear.ok) {
      const body = await resCrear.json().catch(() => ({}));
      errorEl.textContent = body.detail || "No se pudo crear el PIN.";
      errorEl.hidden = false;
      return;
    }
  }

  const res = await fetch(`${API_BASE}/auth/login-pin`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: usuarioActual, pin }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    errorEl.textContent = body.detail || "PIN incorrecto.";
    errorEl.hidden = false;
    return;
  }
  const params = new URLSearchParams(window.location.search);
  window.location.href = params.get("next") || "/";
});

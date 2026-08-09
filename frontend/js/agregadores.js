const AGR_API = `${AUTH_API_BASE}/agregadores`;
const AGR_TODAS = "__todas__";
let agrTiendaActual = null;
let agrIntervalo = null;
let agrMap = null;
let agrDireccionMarkers = [];
let agrMarkersPorId = {};
let agrTiendaMarkers = []; // iconos de tienda en el mapa -- se limpian y recrean en cada render para no acumularse ahora que agrMap ya no se destruye/recrea cada 30s
let agrUltimaSeleccionMapa = null; // clave de qué tiendas estaban seleccionadas la última vez que se reencuadró el mapa -- ver agrCargarMapa
let agrChart = null;
let agrModoAnadir = false;
let agrTiendaCentro = null;
let agrCentrosPorTienda = {}; // slug -> {lat,lng}, usado en la vista "Todas"
let agrDireccionesPorTienda = {}; // slug -> direcciones[] (grid normal, con distancia_km/angulo_grados/detalle) -- para extender el polígono de límite con puntos ya conocidos más lejos de lo muestreado
let agrFiltroAgregador = null; // null = todos los agregadores a la vez
let agrEstadosOcultos = new Set();

// Tarjetas del "Resumen (24h)" ocultas a mano desde este navegador (ver
// agrToggleTarjetaOculta) -- solo afecta a lo que se pinta aquí, nunca se
// manda al backend ni borra nada de la DB. persiste en localStorage (no en
// memoria como agrEstadosOcultos) porque el objetivo es no volver a verlas
// cada vez que se recarga el dashboard, no solo mientras dura la pestaña.
const AGR_TARJETAS_OCULTAS_KEY = "agr_tarjetas_ocultas";
let agrTarjetasOcultas = new Set(JSON.parse(localStorage.getItem(AGR_TARJETAS_OCULTAS_KEY) || "[]"));
let agrUltimoReporte = null;

// Reinicios de contador por agregador (ver agrReiniciarContador) -- {agregador: iso_timestamp}.
// Solo cambia qué le pedimos al backend que cuente (chequeos posteriores al timestamp), nunca
// borra chequeos reales -- permite ver "cómo va desde que apliqué este fix" sin que los fallos
// de antes sigan mezclados en el % del día. Persiste en localStorage, solo en este navegador.
const AGR_REINICIOS_KEY = "agr_reinicios_contador";
let agrReinicios = JSON.parse(localStorage.getItem(AGR_REINICIOS_KEY) || "{}");

// Corte de "limpiar alertas" (ver agrLimpiarAlertas) -- oculta las alertas
// anteriores a este momento, solo en este navegador. No borra nada del
// backend: una alerta nueva de verdad (posterior al corte) sigue apareciendo.
const AGR_ALERTAS_LIMPIADAS_KEY = "agr_alertas_limpiadas_hasta";
let agrAlertasLimpiadasHasta = localStorage.getItem(AGR_ALERTAS_LIMPIADAS_KEY) || null;

// Mismo patrón que las alertas, para "Últimos chequeos".
const AGR_TABLA_LIMPIADA_KEY = "agr_tabla_limpiada_hasta";
let agrTablaLimpiadaHasta = localStorage.getItem(AGR_TABLA_LIMPIADA_KEY) || null;
const AGR_TABLA_COLAPSADA_KEY = "agr_tabla_colapsada";
let agrTablaColapsada = localStorage.getItem(AGR_TABLA_COLAPSADA_KEY) === "1";

// Mismo patrón, para "Dejaron de estar disponibles".
const AGR_TRANSICIONES_LIMPIADAS_KEY = "agr_transiciones_limpiadas_hasta";
let agrTransicionesLimpiadasHasta = localStorage.getItem(AGR_TRANSICIONES_LIMPIADAS_KEY) || null;

// JustEat era naranja claro (#ff8000) -- casi idéntico al amarillo de Glovo
// (#ffc244) y al naranja de la categoría "error" (#e8a33d), imposibles de
// distinguir de un vistazo en el mapa (confirmado 08/08). Se probó azul,
// pero el usuario prefirió mantener naranja (más fiel a la marca real) con
// un tono fuerte/rojizo que sí se separa bien del amarillo pálido de Glovo.
//
// El amarillo pálido de Glovo (#ffc244) también se perdía DIRECTAMENTE contra
// el propio mapa base (zonas residenciales de OpenStreetMap se pintan en un
// tono crema muy parecido) -- el polígono de Glovo era casi invisible incluso
// sin chocar con otro agregador. Se oscurece a un dorado más fuerte que sigue
// leyéndose como "amarillo/Glovo" pero contrasta con el fondo del mapa.
const AGR_COLOR_MARCA = { justeat: "#e8590c", glovo: "#c99a00", ubereats: "#06c167" };
const AGR_NOMBRE_AGREGADOR = { justeat: "JustEat", glovo: "Glovo", ubereats: "Uber Eats" };
let agrMostrarCorrectos = false;

async function agrFetchConTimeout(url, options = {}, ms = 15000) {
  // Sin esto, un fetch que se queda colgado (proxy que corta la conexión sin
  // devolver error, red caída a medias) deja "Buscando dirección..." para
  // siempre -- con AbortController al menos falla y se puede reintentar.
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), ms);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

const AGR_COLOR_CATEGORIA = {
  todos: "#0ca30c",
  disponible: "#0ca30c",
  algunos: "#fab219",
  ninguno: "#d03b3b",
  no_disponible: "#d03b3b",
  sin_datos: "#898781",
  error: "#e8a33d",
};

const AGR_LEYENDA_AGREGADO = [
  { cat: "todos", label: "Disponible en todos" },
  { cat: "algunos", label: "Disponible en algunos" },
  { cat: "ninguno", label: "No disponible (real)" },
  { cat: "sin_datos", label: "Sin datos válidos" },
];
const AGR_LEYENDA_AGREGADOR = [
  { cat: "disponible", label: "Disponible" },
  { cat: "no_disponible", label: "No disponible" },
  { cat: "error", label: "Error del scraper" },
  { cat: "sin_datos", label: "Sin datos" },
];

function agrCategoriaDireccion(dir) {
  if (agrFiltroAgregador) {
    const info = (dir.detalle || {})[agrFiltroAgregador];
    if (!info) return "sin_datos";
    if (info.estado === "error") return "error";
    return info.estado === "disponible" ? "disponible" : "no_disponible";
  }
  const validos = dir.disponible_count + dir.no_disponible_count;
  if (validos === 0) return "sin_datos";
  if (dir.disponible_count === 0) return "ninguno";
  if (dir.no_disponible_count === 0) return "todos";
  return "algunos";
}

function agrPasaFiltroNuevos(dir) {
  // "Solo nuevos" filtra por ID (antes/después de activar el checkbox) --
  // pero un dot manual no es "viejo" solo porque se añadiese antes de
  // activar el filtro: es una categoría aparte (origen=manual) que no
  // depende de la existencia de los dots de grid/límite y debe convivir
  // con ellos siempre, se active o no "solo nuevos" (pedido explícito del
  // usuario 09/08: antes "solo nuevos" ocultaba también los manuales viejos).
  const baseline = agrSoloNuevosBaseline();
  if (baseline != null && dir.origen !== "manual" && (dir.id || 0) <= baseline) return false;
  if (agrSoloManualesActivo() && dir.origen !== "manual") return false;
  return true;
}

const AGR_SOLO_MANUALES_KEY = "agr_solo_manuales";
function agrSoloManualesActivo() {
  return localStorage.getItem(AGR_SOLO_MANUALES_KEY) === "1";
}
function agrToggleSoloManuales() {
  const activo = document.getElementById("agr-solo-manuales")?.checked;
  localStorage.setItem(AGR_SOLO_MANUALES_KEY, activo ? "1" : "0");
  agrActualizarMarcadores();
  agrActualizarLeyenda();
  agrRecalcularContador();
}

function agrMarcadorVisible(dir) {
  if (agrEstadosOcultos.has(agrCategoriaDireccion(dir))) return false;
  return agrPasaFiltroNuevos(dir);
}

function agrInitMap(lat, lng) {
  // El refresco automático (cada 30s, ver agrIntervalo) llama a esto en
  // cada vuelta -- antes se destruía y recreaba el mapa entero cada vez
  // (agrMap.remove() + nuevo L.map con la vista fija de siempre), lo que
  // reiniciaba el zoom/pan del usuario cada 30 segundos ("parpadeo",
  // confirmado en vivo 09/08, hacía muy difícil hacer clic con precisión
  // para añadir puntos). Si el mapa ya existe, no se toca -- se conserva
  // el zoom/pan tal cual estaba.
  if (agrMap) return false;
  agrMap = L.map("agr-map").setView([lat, lng], 12);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap",
  }).addTo(agrMap);
  // Se registra una sola vez aquí (no en cada render) -- si se registrara en
  // agrRenderMapa/agrRenderMapaTodas, que ahora se llaman cada 30s sobre el
  // MISMO mapa persistente, cada vuelta añadiría un listener más y un clic
  // acabaría creando varios puntos duplicados a la vez.
  agrMap.on("click", (e) => {
    if (!agrModoAnadir) return;
    agrAnadirPunto(e.latlng.lat, e.latlng.lng);
  });
  return true;
}

function agrDistanciaKm(lat1, lng1, lat2, lng2) {
  const R = 6371;
  const dLat = ((lat2 - lat1) * Math.PI) / 180;
  const dLng = ((lng2 - lng1) * Math.PI) / 180;
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos((lat1 * Math.PI) / 180) * Math.cos((lat2 * Math.PI) / 180) * Math.sin(dLng / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function agrIconoDireccion(dir) {
  const color = AGR_COLOR_CATEGORIA[agrCategoriaDireccion(dir)] || "#898781";
  return L.divIcon({
    className: "agr-marker-dot",
    html: `<span style="background:${color}"></span>`,
    iconSize: [16, 16],
    iconAnchor: [8, 8],
  });
}

function agrIconoTienda(tienda) {
  // Parquesur ya lleva el letrero "Hot Now" (donuts recién hechos) en la
  // tienda real -- de ahí el icono especial en negro para ese centro.
  const esHotNow = tienda === "parquesur";
  const src = esHotNow ? "assets/hotnow-icon-white.png" : "assets/shop-icon-white.png";
  const tam = esHotNow ? 44 : 38;
  return L.divIcon({
    className: esHotNow ? "agr-marker-tienda agr-marker-tienda-hotnow" : "agr-marker-tienda",
    html: `<span><img src="${src}" alt=""></span>`,
    iconSize: [tam, tam],
    iconAnchor: [tam / 2, tam / 2],
  });
}

function agrPopupDireccion(dir, editable) {
  const iconos = { disponible: "✅", no_disponible: "❌", error: "⚠️" };
  const entradas = Object.entries(dir.detalle || {});
  const detalleHtml = (agrFiltroAgregador ? entradas.filter(([nombre]) => nombre === agrFiltroAgregador) : entradas)
    .map(([nombre, info]) => {
      const icono = iconos[info.estado] || "❔";
      const tiempo = info.tiempo_entrega_min ? ` (${info.tiempo_entrega_min} min)` : "";
      const nota = info.estado === "error" ? " — fallo del scraper" : "";
      const nombreMostrar = AGR_NOMBRE_AGREGADOR[nombre] || nombre;
      const hora = info.timestamp
        ? ` <span style="color:var(--text-muted);font-size:11px;">(${new Date(info.timestamp).toLocaleString("es-ES", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Madrid" })})</span>`
        : "";
      return `${icono} ${nombreMostrar}${tiempo}${nota}${hora}`;
    })
    .join("<br>");
  const tiendaLinea = dir.tienda_nombre ? `<b>${dir.tienda_nombre}</b><br>` : "";
  const pieEditable = editable
    ? `<i style="color:var(--text-muted);font-size:11px;">Arrastra el punto para reubicarlo</i><br>
       <button type="button" class="btn btn-ghost" style="margin-top:6px;font-size:12px;padding:3px 8px;" onclick="agrEliminarPunto(${dir.id})">🗑️ Eliminar punto</button>`
    : "";
  return `${tiendaLinea}<b>${dir.direccion_text || "Punto de test"}</b><br>${dir.distancia_km.toFixed(2)} km · ${dir.angulo_grados}°<br>${detalleHtml || "Sin datos aún"}<br>${pieEditable}`;
}

async function agrEliminarPunto(direccionId) {
  try {
    const res = await fetch(`${AGR_API}/direcciones/${direccionId}`, { method: "DELETE", credentials: "include" });
    if (!res.ok) throw new Error("No se pudo eliminar");
    const marker = agrMarkersPorId[direccionId];
    if (marker) {
      agrMap.removeLayer(marker);
      delete agrMarkersPorId[direccionId];
      agrDireccionMarkers = agrDireccionMarkers.filter((m) => m !== marker);
      agrRecalcularContador();
    }
  } catch (e) {
    alert("No se pudo eliminar el punto. Inténtalo de nuevo.");
  }
}

async function agrAnadirPunto(lat, lng) {
  // Con varias tiendas visibles (vista "Todas") no hay una sola tienda a la
  // que asignar el punto -- se asigna a la más cercana al clic, igual que la
  // reasignación automática de puntos contaminados de la búsqueda de límite.
  const tiendaDestino = agrTiendaActual === AGR_TODAS ? agrTiendaMasCercana(lat, lng) : agrTiendaActual;
  if (!tiendaDestino) return;
  const nombreDestino = agrCentrosPorTienda[tiendaDestino]?.nombre || tiendaDestino;

  // Marcador provisional mientras el servidor consulta la dirección de este
  // punto exacto (una sola llamada, sin desplazarlo -- se queda donde se
  // hizo clic aunque no tenga número de portal cerca).
  const provisional = L.marker([lat, lng], {
    icon: L.divIcon({ className: "agr-marker-dot", html: `<span style="background:#898781;opacity:0.6;"></span>`, iconSize: [16, 16], iconAnchor: [8, 8] }),
  }).addTo(agrMap).bindPopup(
    agrTiendaActual === AGR_TODAS ? `Buscando dirección… (asignado a ${nombreDestino})` : "Buscando dirección…"
  ).openPopup();

  try {
    const res = await agrFetchConTimeout(`${AGR_API}/direcciones`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tienda: tiendaDestino, lat, lng }),
      credentials: "include",
    });
    if (!res.ok) throw new Error("No se pudo añadir");
    const dir = await res.json();
    dir.detalle = {};
    dir.disponible_count = dir.no_disponible_count = dir.error_count = 0;
    if (agrTiendaActual === AGR_TODAS) dir.tienda_nombre = nombreDestino;
    agrMap.removeLayer(provisional);
    agrAgregarMarcador(dir, { editable: true });
    (agrDireccionesPorTienda[tiendaDestino] ||= []).push(dir);
    agrRecalcularContador();
  } catch (e) {
    agrMap.removeLayer(provisional);
    alert("No se pudo añadir el punto. Inténtalo de nuevo.");
  }
}

async function agrGuardarReubicacion(dir, marker, lat, lng) {
  marker.setPopupContent("Buscando dirección…").openPopup();
  try {
    const res = await agrFetchConTimeout(`${AGR_API}/direcciones/${dir.id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lat, lng }),
      credentials: "include",
    });
    if (!res.ok) throw new Error("No se pudo guardar");
    const actualizado = await res.json();
    dir.lat = actualizado.lat;
    dir.lng = actualizado.lng;
    dir.direccion_text = actualizado.direccion_text;
    marker.setLatLng([dir.lat, dir.lng]);
    marker.setPopupContent(agrPopupDireccion(dir, true));
  } catch (e) {
    alert("No se pudo guardar la reubicación. Inténtalo de nuevo.");
    marker.setLatLng([dir.lat, dir.lng]);
    marker.setPopupContent(agrPopupDireccion(dir, true));
  }
}

function agrAgregarMarcador(dir, opts = {}) {
  const editable = opts.editable !== false;
  const marker = L.marker([dir.lat, dir.lng], {
    icon: agrIconoDireccion(dir),
    draggable: editable,
  })
    // Función en vez de string fijo: Leaflet la vuelve a llamar cada vez que
    // se abre el popup, así que siempre refleja el agregador filtrado
    // actual. Antes se generaba una sola vez al crear el marcador -- si el
    // usuario cambiaba de agregador (JustEat/Glovo/Uber Eats) sin esperar al
    // refresco automático (cada 30s), el popup seguía mostrando el
    // agregador de cuando se creó el marcador, no el filtro activo
    // (confirmado en vivo 09/08 con capturas: filtro Uber Eats mostrando
    // datos de JustEat).
    .bindPopup(() => agrPopupDireccion(dir, editable))
    .bindTooltip("", { permanent: false, direction: "top", className: "agr-drag-tooltip" });

  marker._agrDir = dir;

  if (editable) {
    const centro = (dir.tienda && agrCentrosPorTienda[dir.tienda]) || agrTiendaCentro;
    marker.on("drag", (e) => {
      const { lat, lng } = e.target.getLatLng();
      const distKm = agrDistanciaKm(centro.lat, centro.lng, lat, lng);
      marker.setTooltipContent(`${distKm.toFixed(2)} km línea recta (objetivo ${dir.distancia_km.toFixed(2)} km)`);
      marker.openTooltip();
    });

    marker.on("dragend", (e) => {
      marker.closeTooltip();
      const { lat, lng } = e.target.getLatLng();
      agrGuardarReubicacion(dir, marker, lat, lng);
    });
  }

  agrDireccionMarkers.push(marker);
  agrMarkersPorId[dir.id] = marker;
  if (agrMarcadorVisible(dir)) marker.addTo(agrMap);
  return marker;
}

function agrActualizarMarcadores() {
  agrDireccionMarkers.forEach((marker) => {
    const dir = marker._agrDir;
    marker.setIcon(agrIconoDireccion(dir));
    const visible = agrMarcadorVisible(dir);
    const enMapa = agrMap.hasLayer(marker);
    if (visible && !enMapa) marker.addTo(agrMap);
    if (!visible && enMapa) agrMap.removeLayer(marker);
  });
}

function agrActualizarLeyenda() {
  const items = agrFiltroAgregador ? AGR_LEYENDA_AGREGADOR : AGR_LEYENDA_AGREGADO;
  const cont = document.getElementById("agr-leyenda");
  if (!cont) return;

  // Solo respeta "solo dots nuevos" (no las categorías ocultas -- la
  // leyenda tiene que seguir mostrando el total real de una categoría
  // aunque esté oculta, si no nunca sabrías cuántos hay para decidir si
  // mostrarla). Antes contaba TODOS los puntos siempre, así que con "solo
  // nuevos" activo la leyenda seguía dando el total de siempre mientras el
  // contador de arriba decía 0 -- números contradictorios en la misma
  // pantalla (confirmado en vivo 09/08).
  const conteos = {};
  agrDireccionMarkers.filter((m) => agrPasaFiltroNuevos(m._agrDir)).forEach((m) => {
    const cat = agrCategoriaDireccion(m._agrDir);
    conteos[cat] = (conteos[cat] || 0) + 1;
  });

  cont.innerHTML = items
    .map((it) => {
      const oculto = agrEstadosOcultos.has(it.cat);
      const n = conteos[it.cat] || 0;
      return `<span class="agr-leyenda-item${oculto ? " oculto" : ""}" data-cat="${it.cat}" title="Clic para ${oculto ? "mostrar" : "ocultar"}">
        <i class="agr-dot" style="background:${AGR_COLOR_CATEGORIA[it.cat]}"></i> ${it.label} <b class="agr-leyenda-n">${n}</b>
      </span>`;
    })
    .join("");
  cont.querySelectorAll(".agr-leyenda-item").forEach((el) => {
    el.addEventListener("click", () => {
      const cat = el.dataset.cat;
      if (agrEstadosOcultos.has(cat)) agrEstadosOcultos.delete(cat);
      else agrEstadosOcultos.add(cat);
      agrActualizarLeyenda();
      agrActualizarMarcadores();
      agrRecalcularContador();
    });
  });
}

const AGR_FILTRO_AGREGADOR_KEY = "agr_filtro_agregador";

function agrWireFiltroAgregador() {
  document.querySelectorAll(".agr-filtro-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".agr-filtro-btn").forEach((b) => b.classList.remove("activo"));
      btn.classList.add("activo");
      agrFiltroAgregador = btn.dataset.agregador || null;
      localStorage.setItem(AGR_FILTRO_AGREGADOR_KEY, agrFiltroAgregador || "");
      agrEstadosOcultos.clear(); // las categorías cambian de significado al cambiar de filtro
      agrActualizarLeyenda();
      agrActualizarMarcadores();
      agrRecalcularContador();
      agrActualizarPoligonoLimite();
    });
  });

  // Restaura el filtro elegido antes de recargar (persiste en localStorage).
  const guardado = localStorage.getItem(AGR_FILTRO_AGREGADOR_KEY);
  if (guardado) {
    const btn = document.querySelector(`.agr-filtro-btn[data-agregador="${guardado}"]`);
    if (btn) {
      document.querySelectorAll(".agr-filtro-btn").forEach((b) => b.classList.remove("activo"));
      btn.classList.add("activo");
      agrFiltroAgregador = guardado;
    }
  }
}

function agrToggleModoAnadir() {
  agrModoAnadir = !agrModoAnadir;
  const btn = document.getElementById("agr-btn-anadir");
  if (btn) {
    btn.classList.toggle("activo", agrModoAnadir);
    // Con varias tiendas visibles a la vez no hay "la tienda actual" a la
    // que asignar el punto -- se asigna sola a la más cercana al clic (ver
    // agrTiendaMasCercana), igual que ya se hace al reasignar puntos
    // contaminados de la búsqueda de límite. Antes este modo se
    // desactivaba directamente en vista "Todas" sin avisar por qué
    // (pedido explícito del usuario 09/08: poder añadir puntos viendo
    // varias tiendas para rellenar huecos entre ellas).
    btn.textContent = agrModoAnadir
      ? agrTiendaActual === AGR_TODAS
        ? "✓ Clic en el mapa (se asigna a la tienda más cercana)…"
        : "✓ Clic en el mapa para añadir…"
      : "➕ Añadir punto";
  }
  if (agrMap) {
    document.getElementById("agr-map").style.cursor = agrModoAnadir ? "crosshair" : "";
  }
}

function agrTiendaMasCercana(lat, lng) {
  let mejor = null, mejorDist = null;
  Object.entries(agrCentrosPorTienda).forEach(([slug, centro]) => {
    const d = agrDistanciaKm(centro.lat, centro.lng, lat, lng);
    if (mejorDist == null || d < mejorDist) { mejor = slug; mejorDist = d; }
  });
  return mejor;
}

let agrLineasGuiaAngulo = []; // líneas "compás" (cada 15°, con etiqueta) que salen del centro de la tienda mientras se está en modo añadir -- calcular a mano a qué ángulo cae un hueco en el mapa es poco práctico (pedido explícito del usuario 09/08), esto lo hace visual: solo hay que mirar entre qué dos líneas cae el hueco y hacer clic ahí.
const AGR_GUIA_ANGULO_PASO = 15;
const AGR_GUIA_ANGULO_RADIO_KM = 9; // cubre incluso el punto más lejano que prueba la búsqueda de límite (DISTANCIAS_EXPANSION llega a 9km)

function agrLimpiarGuiasAngulo() {
  agrLineasGuiaAngulo.forEach((l) => agrMap && agrMap.removeLayer(l));
  agrLineasGuiaAngulo = [];
}

const AGR_MOSTRAR_COMPAS_KEY = "agr_mostrar_compas_angulo";

function agrMostrarCompasActivo() {
  return localStorage.getItem(AGR_MOSTRAR_COMPAS_KEY) === "1";
}

function agrToggleCompas() {
  const activo = document.getElementById("agr-mostrar-compas")?.checked;
  localStorage.setItem(AGR_MOSTRAR_COMPAS_KEY, activo ? "1" : "0");
  agrActualizarGuiasAngulo();
}

function agrActualizarGuiasAngulo() {
  const checkbox = document.getElementById("agr-mostrar-compas");
  if (checkbox) checkbox.checked = agrMostrarCompasActivo();
  if (agrMostrarCompasActivo()) agrDibujarGuiasAngulo();
  else agrLimpiarGuiasAngulo();
}

function agrDibujarGuiasAngulo() {
  agrLimpiarGuiasAngulo();
  if (!agrMap || !agrMostrarCompasActivo()) return;
  // Un compás por cada tienda visible en el mapa ahora mismo -- con la
  // asignación al punto "más cercano" en vista con varias tiendas (ver
  // agrTiendaMasCercana), el caso más útil es justo comparar dos tiendas
  // vecinas a la vez (ej. Princesa/Caleido), así que restringir el compás a
  // una sola tienda seleccionada dejaba sin líneas guía justo ese caso
  // (confirmado en vivo 09/08). Con 3+ tiendas a la vez se puede ver
  // recargado, pero es una elección del usuario al activar el checkbox.
  Object.values(agrCentrosPorTienda).forEach((centro) => {
    for (let angulo = 0; angulo < 360; angulo += AGR_GUIA_ANGULO_PASO) {
      const destino = agrMoverPunto(centro.lat, centro.lng, angulo, AGR_GUIA_ANGULO_RADIO_KM);
      agrLineasGuiaAngulo.push(
        L.polyline([[centro.lat, centro.lng], destino], {
          // Más oscuro/visible que antes (pedido explícito del usuario
          // 09/08: se perdía en el mapa) pero fino y punteado -- para no
          // confundirse con el polígono de límite (línea gruesa sólida del
          // color del agregador) ni con el contorno de la unión (gruesa,
          // #1a1a1a, guiones largos "6 4").
          color: "#333", weight: 1.5, opacity: 0.75, dashArray: "2 6", interactive: false,
        }).addTo(agrMap)
      );
      agrLineasGuiaAngulo.push(
        L.marker(destino, {
          icon: L.divIcon({ className: "agr-guia-angulo-label", html: `${angulo}°`, iconSize: [34, 14], iconAnchor: [17, 7] }),
          interactive: false,
        }).addTo(agrMap)
      );
    }
  });
}

function agrLimpiarMapa() {
  agrDireccionMarkers.forEach((m) => agrMap.removeLayer(m));
  agrDireccionMarkers = [];
  agrMarkersPorId = {};
}

let agrContadorBase = ""; // texto de "N puntos..." sin el sufijo de vértices del polígono, para poder recombinar

function agrActualizarContador(texto) {
  agrContadorBase = texto;
  const el = document.getElementById("agr-contador-puntos");
  if (el) el.textContent = texto;
}

function agrActualizarContadorPoligono(n) {
  // El contador solo contaba los dots del grid normal -- los vértices del
  // polígono de límite son una capa totalmente distinta y nunca se
  // reflejaban ahí, así que con "solo dots nuevos" activo podía decir
  // "0 puntos" mientras el mapa mostraba un polígono lleno de datos reales
  // (confirmado en vivo 09/08). Se añade como sufijo sin pisar el texto base.
  const el = document.getElementById("agr-contador-puntos");
  if (!el) return;
  el.textContent = n > 0 ? `${agrContadorBase} · ${n} vértice${n === 1 ? "" : "s"} de límite` : agrContadorBase;
}

function agrRecalcularContador() {
  // Cuenta solo los puntos REALMENTE visibles ahora mismo (respeta "solo
  // dots nuevos" y las categorías de leyenda ocultas vía agrMarcadorVisible)
  // -- antes contaba siempre el total de puntos cargados, así que el número
  // no cambiaba nunca al tocar un filtro (confirmado en vivo 09/08).
  const visibles = agrDireccionMarkers.filter((m) => agrMarcadorVisible(m._agrDir));
  const n = visibles.length;
  const numTiendasMapa = Object.keys(agrCentrosPorTienda).length;
  const base = numTiendasMapa > 1
    ? `${n} puntos en ${numTiendasMapa} tiendas`
    : `${n} punto${n === 1 ? "" : "s"}`;

  if (!agrFiltroAgregador) {
    agrActualizarContador(base);
    return;
  }

  // Filtrado por un agregador concreto: de los N puntos VISIBLES, cuántos
  // tienen dato real de ese agregador (disponible/no disponible/error) --
  // "sin datos" no cuenta como un punto "que existe" para ese filtro.
  const conDatos = visibles.filter(
    (m) => ((m._agrDir.detalle || {})[agrFiltroAgregador])
  ).length;
  const nombre = AGR_NOMBRE_AGREGADOR[agrFiltroAgregador] || agrFiltroAgregador;
  agrActualizarContador(`${conDatos} de ${n} con dato de ${nombre}`);
}

function agrRenderMapa(data) {
  const { tienda, direcciones } = data;
  if (!tienda) return;
  agrTiendaCentro = tienda;
  agrDireccionesPorTienda = { [tienda.tienda]: direcciones };
  agrInitMap(tienda.lat, tienda.lng);

  L.marker([tienda.lat, tienda.lng], { icon: agrIconoTienda(tienda.tienda) }).addTo(agrMap).bindPopup(`<b>${tienda.nombre}</b>`);

  agrLimpiarMapa();
  direcciones.forEach((dir) => agrAgregarMarcador(dir, { editable: true }));

  agrMap.on("click", (e) => {
    if (!agrModoAnadir) return;
    agrAnadirPunto(e.latlng.lat, e.latlng.lng);
  });
  agrActualizarLeyenda();
  agrRecalcularContador();
}

function agrRenderMapaTodas(data, ajustarVista = true) {
  const { tiendas, direcciones } = data;
  if (!tiendas || !tiendas.length) return;
  agrTiendaCentro = null;
  agrCentrosPorTienda = {};
  tiendas.forEach((t) => { agrCentrosPorTienda[t.tienda] = t; });
  agrDireccionesPorTienda = {};
  direcciones.forEach((d) => { (agrDireccionesPorTienda[d.tienda] ||= []).push(d); });

  const lat0 = tiendas.reduce((s, t) => s + t.lat, 0) / tiendas.length;
  const lng0 = tiendas.reduce((s, t) => s + t.lng, 0) / tiendas.length;
  const esMapaNuevo = agrInitMap(lat0, lng0);

  // El refresco automático (cada 30s) vuelve a llamar a esto sobre el MISMO
  // mapa persistente -- sin limpiar antes, cada vuelta añadía otro icono de
  // tienda encima de los anteriores (no se notaba mientras el mapa entero se
  // destruía y recreaba cada vez, ver agrInitMap).
  agrTiendaMarkers.forEach((m) => agrMap.removeLayer(m));
  agrTiendaMarkers = tiendas.map((t) =>
    L.marker([t.lat, t.lng], { icon: agrIconoTienda(t.tienda) }).addTo(agrMap).bindPopup(`<b>${t.nombre}</b>`)
  );

  agrLimpiarMapa();
  direcciones.forEach((dir) => agrAgregarMarcador(dir, { editable: true }));

  // Solo se reencuadra el mapa la primera vez que se crea o cuando cambia de
  // verdad qué tiendas se están viendo (ver agrCargarMapa) -- el refresco
  // automático de cada 30s ya no toca el zoom/pan que el usuario haya puesto
  // a mano (pedido explícito del usuario 09/08: el reencuadre constante
  // hacía muy difícil hacer clic con precisión para añadir puntos).
  if (esMapaNuevo || ajustarVista) {
    const bounds = L.latLngBounds(tiendas.map((t) => [t.lat, t.lng]));
    agrMap.fitBounds(bounds.pad(0.25));
  }
  agrActualizarLeyenda();
  agrRecalcularContador();
}

function agrBadge(c) {
  if (c.error_texto) return '<span class="agr-badge error" title="Fallo del scraper, no del agregador">Error</span>';
  return c.disponible
    ? '<span class="agr-badge si">Sí</span>'
    : '<span class="agr-badge no">No</span>';
}

let agrMapaTiendasSeleccionadas = null; // Set de slugs -- qué tiendas se muestran. AHORA es el único selector de tienda de toda la página (antes había un <select> Y estas chips diciendo lo mismo dos veces, confirmado en vivo 09/08 -- se quitó el select).

async function agrCargarTiendas() {
  const res = await fetch(`${AGR_API}/tiendas`);
  const tiendas = await res.json();
  agrMapaTiendasSeleccionadas = new Set(tiendas.length ? [tiendas[0].tienda] : []);
  agrSincronizarTiendaActual();
  agrRenderChipsTiendasMapa(tiendas);
}

function agrSincronizarTiendaActual() {
  // El resto del dashboard (tabla, alertas, tarjetas, transiciones) solo
  // entiende "una tienda concreta" o AGR_TODAS -- con exactamente una chip
  // activa se usa esa tienda; con 2+ activas se cae al modo agregado
  // "Todas" que esas secciones ya sabían manejar.
  const seleccion = [...(agrMapaTiendasSeleccionadas || [])];
  agrTiendaActual = seleccion.length === 1 ? seleccion[0] : AGR_TODAS;
}

function agrRenderChipsTiendasMapa(tiendas) {
  const cont = document.getElementById("agr-tiendas-mapa-chips");
  if (!cont) return;
  const chips = [`<button type="button" class="agr-tienda-chip agr-tienda-chip-todas" data-todas="1">Todas</button>`].concat(
    tiendas.map((t) => `<button type="button" class="agr-tienda-chip" data-tienda="${t.tienda}">${t.nombre}</button>`)
  );
  cont.innerHTML = chips.join("");
  agrActualizarChipsTiendasMapa();
  cont.querySelectorAll(".agr-tienda-chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.dataset.todas) {
        agrMapaTiendasSeleccionadas = new Set(tiendas.map((t) => t.tienda));
      } else {
        const slug = btn.dataset.tienda;
        if (agrMapaTiendasSeleccionadas.has(slug)) {
          // Al menos una tienda tiene que quedar seleccionada -- no tiene
          // sentido un mapa vacío.
          if (agrMapaTiendasSeleccionadas.size > 1) agrMapaTiendasSeleccionadas.delete(slug);
        } else {
          agrMapaTiendasSeleccionadas.add(slug);
        }
      }
      agrActualizarChipsTiendasMapa();
      agrSincronizarTiendaActual();
      if (agrModoAnadir) agrToggleModoAnadir();
      agrCargarTodo();
    });
  });
}

function agrActualizarChipsTiendasMapa() {
  const cont = document.getElementById("agr-tiendas-mapa-chips");
  if (!cont || !agrMapaTiendasSeleccionadas) return;
  const totalTiendas = cont.querySelectorAll("[data-tienda]").length;
  cont.querySelectorAll(".agr-tienda-chip").forEach((btn) => {
    if (btn.dataset.todas) {
      btn.classList.toggle("activo", agrMapaTiendasSeleccionadas.size === totalTiendas);
    } else {
      btn.classList.toggle("activo", agrMapaTiendasSeleccionadas.has(btn.dataset.tienda));
    }
  });
}

async function agrCargarMapa() {
  if (!agrTiendaActual || !agrMapaTiendasSeleccionadas || agrMapaTiendasSeleccionadas.size === 0) return;

  // Bug confirmado en vivo 08/08: la casilla siempre arranca DESMARCADA al
  // recargar la página (no hay código que la marque), pero el filtro en sí
  // vive en localStorage y SÍ sobrevive a la recarga -- si se activó una vez
  // para esta tienda y nunca se desmarcó a mano antes de recargar, el filtro
  // seguía activo ocultando TODOS los puntos, con la casilla mintiendo que
  // estaba apagado. Se sincroniza la casilla con el estado real al cargar.
  const checkboxSoloNuevos = document.getElementById("agr-solo-nuevos");
  if (checkboxSoloNuevos) checkboxSoloNuevos.checked = agrSoloNuevosBaseline() != null;
  const checkboxSoloManuales = document.getElementById("agr-solo-manuales");
  if (checkboxSoloManuales) checkboxSoloManuales.checked = agrSoloManualesActivo();

  // Siempre se pide el dato de las 6 tiendas y se filtra en el cliente a las
  // chips activas -- así "Princesa y Caleido" o "todas menos una" es solo
  // cuestión de qué chips están marcadas, sin pedirle al backend un
  // endpoint nuevo por cada combinación posible (pedido explícito del
  // usuario 09/08: poder elegir qué tiendas ver en el mapa, no solo "una" o
  // "todas").
  const res = await fetch(`${AGR_API}/mapa-datos-todas`, { credentials: "include" });
  const data = await res.json();
  const seleccion = agrMapaTiendasSeleccionadas;
  const filtrado = {
    tiendas: (data.tiendas || []).filter((t) => seleccion.has(t.tienda)),
    direcciones: (data.direcciones || []).filter((d) => seleccion.has(d.tienda)),
  };
  // El refresco automático (cada 30s) llama a agrCargarMapa() con la MISMA
  // selección de tiendas de siempre -- solo se reencuadra el mapa si esa
  // selección cambió de verdad (o es la primera carga), para no pisar el
  // zoom/pan que el usuario haya puesto a mano cada 30 segundos (pedido
  // explícito del usuario 09/08).
  const seleccionClave = [...seleccion].sort().join(",");
  const ajustarVista = seleccionClave !== agrUltimaSeleccionMapa;
  agrUltimaSeleccionMapa = seleccionClave;
  agrRenderMapaTodas(filtrado, ajustarVista);
  await agrActualizarPoligonoLimite();
  agrActualizarGuiasAngulo();
}

function agrLimpiarTabla() {
  agrTablaLimpiadaHasta = new Date().toISOString();
  localStorage.setItem(AGR_TABLA_LIMPIADA_KEY, agrTablaLimpiadaHasta);
  agrCargarTabla();
}

function agrColapsarTabla() {
  agrTablaColapsada = !agrTablaColapsada;
  localStorage.setItem(AGR_TABLA_COLAPSADA_KEY, agrTablaColapsada ? "1" : "0");
  agrAplicarColapsoTabla();
}

function agrAplicarColapsoTabla() {
  document.getElementById("agr-tabla-scroll").classList.toggle("agr-colapsado", agrTablaColapsada);
  document.getElementById("agr-tabla-colapsar-icono").classList.toggle("agr-colapsado", agrTablaColapsada);
}

function agrFilaTabla(c) {
  const hora = new Date(c.timestamp).toLocaleString("es-ES", { timeZone: "Europe/Madrid" });
  const detalle = c.error_texto ? `⚠️ ${c.error_texto}` : c.mensaje_bloqueo || "-";
  const filaClase = c.error_texto ? "agr-fila-error" : "agr-fila-correcta";
  const nombre = AGR_NOMBRE_AGREGADOR[c.agregador] || c.agregador;
  return `<tr class="${filaClase}">
    <td>${hora}</td><td>${nombre}</td><td>${agrBadge(c)}</td>
    <td>${c.tiempo_entrega_min ? c.tiempo_entrega_min + " min" : "-"}</td>
    <td>${c.direccion_text || "-"}</td><td>${detalle}</td>
  </tr>`;
}

async function agrCargarTabla() {
  const tbody = document.querySelector("#agr-tabla tbody");
  const contador = document.getElementById("agr-tabla-contador");
  const toggle = document.getElementById("agr-tabla-toggle");
  if (!agrTiendaActual || agrTiendaActual === AGR_TODAS) {
    tbody.innerHTML = '<tr><td colspan="6" style="color:var(--text-muted);">Selecciona una tienda para ver el detalle.</td></tr>';
    contador.textContent = "";
    toggle.hidden = true;
    return;
  }
  const res = await fetch(`${AGR_API}/ultimos?tienda=${agrTiendaActual}&horas=24`, { credentials: "include" });
  let chequeos = await res.json();
  const totalSinLimpiar = chequeos.length;
  if (agrTablaLimpiadaHasta) {
    chequeos = chequeos.filter((c) => c.timestamp > agrTablaLimpiadaHasta);
  }
  const incorrectos = chequeos.filter((c) => c.error_texto);
  const correctos = chequeos.filter((c) => !c.error_texto);
  const notaLimpiados = totalSinLimpiar > chequeos.length ? ` -- ${totalSinLimpiar - chequeos.length} ocultos` : "";

  contador.textContent = `(${incorrectos.length} con fallo técnico / ${correctos.length} correctos${notaLimpiados})`;

  if (incorrectos.length === 0) {
    const motivo = totalSinLimpiar > 0 && chequeos.length === 0
      ? "Sin chequeos nuevos desde que limpiaste."
      : "Sin fallos técnicos en 24h. Todos los chequeos se completaron correctamente.";
    tbody.innerHTML = `<tr><td colspan="6" style="color:var(--text-muted);">${motivo}</td></tr>`;
  } else {
    tbody.innerHTML = incorrectos.slice(0, 30).map(agrFilaTabla).join("");
  }

  toggle.hidden = correctos.length === 0;
  toggle.textContent = agrMostrarCorrectos
    ? "Ocultar detalles correctos"
    : `Mostrar detalles correctos (${correctos.length})`;
  toggle.onclick = () => {
    agrMostrarCorrectos = !agrMostrarCorrectos;
    agrCargarTabla();
  };

  if (agrMostrarCorrectos && correctos.length > 0) {
    tbody.innerHTML += correctos.slice(0, 30).map(agrFilaTabla).join("");
  }
}

function agrRenderCards(reporte) {
  const cont = document.getElementById("agr-cards");
  const entradas = Object.entries(reporte.agregadores).filter(([nombre]) => !agrTarjetasOcultas.has(nombre));
  if (entradas.length === 0) {
    const motivo = Object.keys(reporte.agregadores).length === 0 ? "Sin chequeos en 24h." : "Todas las tarjetas están ocultas -- usa el icono 🗑 para volver a mostrarlas.";
    cont.innerHTML = `<p style="color:var(--text-muted);font-size:0.85rem;grid-column:1/-1;">${motivo}</p>`;
    return;
  }
  cont.innerHTML = entradas
    .map(([nombre, datos]) => {
      const etiqueta = AGR_NOMBRE_AGREGADOR[nombre] || nombre;
      const notaReinicio = datos.reiniciado_desde
        ? ` <span class="agr-card-reinicio">· contador reiniciado ${new Date(datos.reiniciado_desde).toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Madrid" })}</span>`
        : "";
      return `<div class="agr-card">
        <div class="etiqueta">${etiqueta}</div>
        <div class="agr-card-total">${datos.total_chequeos} intentos en total${notaReinicio}</div>
        <div class="agr-card-desglose">
          <div class="agr-card-fila ok agr-clicable" onclick="agrMostrarDrill('${nombre}', 'disponible')"><span class="agr-card-pct">${datos.disponible_pct}%</span> disponible <span class="agr-card-n">(${datos.disponibles})</span></div>
          <div class="agr-card-fila no agr-clicable" onclick="agrMostrarDrill('${nombre}', 'no_disponible')"><span class="agr-card-pct">${datos.no_disponible_pct}%</span> no disponible <span class="agr-card-n">(${datos.no_disponibles})</span></div>
          <div class="agr-card-fila fallo agr-clicable" onclick="agrMostrarDrill('${nombre}', 'error')"><span class="agr-card-pct">${datos.error_pct}%</span> fallo técnico <span class="agr-card-n">(${datos.errores})</span></div>
        </div>
        <div class="agr-card-barra">
          <span style="width:${datos.disponible_pct}%;background:var(--status-good);"></span><span style="width:${datos.no_disponible_pct}%;background:var(--status-critical);"></span><span style="width:${datos.error_pct}%;background:var(--status-warning);"></span>
        </div>
      </div>`;
    })
    .join("");
}

async function agrMostrarDrill(agregador, estado) {
  const overlay = document.getElementById("agr-drill-overlay");
  const titulo = document.getElementById("agr-drill-titulo");
  const lista = document.getElementById("agr-drill-lista");
  const etiquetaEstado = estado === "disponible" ? "Disponibles" : estado === "error" ? "Fallo técnico" : "No disponibles";

  titulo.textContent = `${AGR_NOMBRE_AGREGADOR[agregador] || agregador} — ${etiquetaEstado}`;
  lista.innerHTML = '<li style="color:var(--text-muted);">Cargando...</li>';
  overlay.classList.add("visible");

  let direcciones;
  try {
    const url = agrTiendaActual === AGR_TODAS
      ? `${AGR_API}/mapa-datos-todas`
      : `${AGR_API}/mapa-datos?tienda=${agrTiendaActual}`;
    const res = await agrFetchConTimeout(url, { credentials: "include" });
    direcciones = (await res.json()).direcciones;
  } catch (err) {
    lista.innerHTML = '<li style="color:var(--status-critical);">No se pudo cargar. Inténtalo de nuevo.</li>';
    return;
  }

  const filtradas = direcciones
    .filter((d) => d.detalle[agregador]?.estado === estado)
    .sort((a, b) => new Date(b.detalle[agregador].timestamp) - new Date(a.detalle[agregador].timestamp));
  if (filtradas.length === 0) {
    lista.innerHTML = '<li style="color:var(--text-muted);">Sin puntos en este estado ahora mismo.</li>';
    return;
  }

  // Construcción vía DOM (no innerHTML con interpolación) porque el texto de
  // dirección viene de geocoding externo (Nominatim) -- así no hace falta
  // escapar nada a mano para que sea seguro meterlo en el atributo/HTML.
  lista.innerHTML = "";
  for (const d of filtradas) {
    const texto = d.direccion_text || `${d.lat.toFixed(5)}, ${d.lng.toFixed(5)}`;
    const li = document.createElement("li");

    const span = document.createElement("span");
    span.className = "agr-drill-direccion";
    if (d.tienda) {
      const tag = document.createElement("span");
      tag.style.color = "var(--text-muted)";
      tag.style.fontSize = "0.68rem";
      tag.textContent = `[${d.tienda}] `;
      span.appendChild(tag);
    }
    span.appendChild(document.createTextNode(texto));

    const info = d.detalle[agregador];
    if (info?.timestamp) {
      const hora = document.createElement("span");
      hora.className = "agr-drill-hora";
      hora.textContent = ` (${new Date(info.timestamp).toLocaleString("es-ES", {
        day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Madrid",
      })})`;
      span.appendChild(hora);
    }

    const boton = document.createElement("button");
    boton.type = "button";
    boton.className = "agr-drill-copiar";
    boton.textContent = "📋 Copiar";
    boton.onclick = () => agrCopiarDireccionDrill(boton, texto);

    li.appendChild(span);
    li.appendChild(boton);
    lista.appendChild(li);
  }
}

function agrCerrarDrill() {
  document.getElementById("agr-drill-overlay").classList.remove("visible");
}

async function agrCopiarDireccionDrill(boton, texto) {
  try {
    await navigator.clipboard.writeText(texto);
    const original = boton.textContent;
    boton.textContent = "✓ Copiado";
    setTimeout(() => { boton.textContent = original; }, 1500);
  } catch (err) {
    // Clipboard API puede fallar sin HTTPS/permisos -- el texto sigue
    // siendo seleccionable a mano (user-select:text en .agr-drill-direccion).
  }
}

function agrRenderChart(reporte) {
  const ctx = document.getElementById("agr-chart");
  const claves = Object.keys(reporte.agregadores).filter((nombre) => !agrTarjetasOcultas.has(nombre));
  const labels = claves.map((n) => AGR_NOMBRE_AGREGADOR[n] || n);
  const valores = claves.map((n) => reporte.agregadores[n].disponible_pct);
  const colores = claves.map((n) => AGR_COLOR_MARCA[n] || "#e07b00");
  if (agrChart) agrChart.destroy();
  agrChart = new Chart(ctx, {
    type: "bar",
    data: { labels, datasets: [{ label: "% Disponible (24h, sobre el total de intentos)", data: valores, backgroundColor: colores, borderRadius: 6 }] },
    options: {
      responsive: true,
      scales: { y: { beginAtZero: true, max: 100 } },
      plugins: { legend: { display: false } },
    },
  });
}

async function agrCargarResumen() {
  const cont = document.getElementById("agr-cards");
  if (!agrTiendaActual) {
    cont.innerHTML = '<p style="color:var(--text-muted);font-size:0.85rem;grid-column:1/-1;">Selecciona una tienda para ver el resumen.</p>';
    if (agrChart) { agrChart.destroy(); agrChart = null; }
    return;
  }
  const params = new URLSearchParams();
  if (agrTiendaActual !== AGR_TODAS) params.set("tienda", agrTiendaActual);
  if (Object.keys(agrReinicios).length > 0) params.set("resets", JSON.stringify(agrReinicios));
  const url = `${AGR_API}/reportes/diario${params.toString() ? "?" + params.toString() : ""}`;
  const res = await fetch(url, { credentials: "include" });
  const reporte = await res.json();
  agrUltimoReporte = reporte;
  agrRenderCards(reporte);
  agrRenderChart(reporte);
}

function agrGuardarTarjetasOcultas() {
  localStorage.setItem(AGR_TARJETAS_OCULTAS_KEY, JSON.stringify([...agrTarjetasOcultas]));
}

function agrGuardarReinicios() {
  localStorage.setItem(AGR_REINICIOS_KEY, JSON.stringify(agrReinicios));
}

function agrPoblarMenuBorrar() {
  const menu = document.getElementById("agr-borrar-menu");
  const disponibles = agrUltimoReporte ? Object.keys(agrUltimoReporte.agregadores) : Object.keys(AGR_NOMBRE_AGREGADOR);
  const items = disponibles
    .map((nombre) => {
      const oculta = agrTarjetasOcultas.has(nombre);
      const reiniciado = !!agrReinicios[nombre];
      const tituloReset = reiniciado
        ? "El % de este agregador solo cuenta desde el reinicio -- clic para volver a contar todo el día"
        : "Recalcula el % de este agregador solo con chequeos a partir de ahora (no borra nada)";
      return `<div class="agr-borrar-menu-fila">
        <label class="agr-borrar-menu-item">
          <input type="checkbox" data-agregador="${nombre}" ${oculta ? "checked" : ""} onchange="agrToggleTarjetaOculta('${nombre}', this.checked)">
          Ocultar ${AGR_NOMBRE_AGREGADOR[nombre] || nombre}
        </label>
        <button type="button" class="agr-borrar-menu-reset${reiniciado ? " activo" : ""}" onclick="agrToggleReinicioContador('${nombre}')" title="${tituloReset}">${reiniciado ? "✕ Quitar reinicio" : "↺ Reiniciar"}</button>
      </div>`;
    })
    .join("");
  menu.innerHTML = items + '<div class="agr-borrar-menu-nota">Solo en este navegador -- no borra nada en el servidor ni en la base de datos.</div>';
}

function agrToggleReinicioContador(agregador) {
  if (agrReinicios[agregador]) {
    delete agrReinicios[agregador];
  } else {
    agrReinicios[agregador] = new Date().toISOString();
  }
  agrGuardarReinicios();
  agrPoblarMenuBorrar();
  agrCargarResumen();
}

function agrToggleMenuBorrar(evt) {
  evt.stopPropagation();
  const menu = document.getElementById("agr-borrar-menu");
  const abrir = menu.hidden;
  if (abrir) agrPoblarMenuBorrar();
  menu.hidden = !abrir;
}

function agrToggleTarjetaOculta(agregador, oculta) {
  if (oculta) agrTarjetasOcultas.add(agregador);
  else agrTarjetasOcultas.delete(agregador);
  agrGuardarTarjetasOcultas();
  if (agrUltimoReporte) {
    agrRenderCards(agrUltimoReporte);
    agrRenderChart(agrUltimoReporte);
  }
}

document.addEventListener("click", (evt) => {
  const menu = document.getElementById("agr-borrar-menu");
  if (menu && !menu.hidden && !menu.contains(evt.target) && evt.target.id !== "agr-btn-borrar-stats") {
    menu.hidden = true;
  }
});

function agrLimpiarAlertas() {
  agrAlertasLimpiadasHasta = new Date().toISOString();
  localStorage.setItem(AGR_ALERTAS_LIMPIADAS_KEY, agrAlertasLimpiadasHasta);
  agrCargarAlertas();
}

async function agrCargarAlertas() {
  const lista = document.getElementById("agr-alertas");
  const resumen = document.getElementById("agr-alertas-resumen");
  if (agrTiendaActual === AGR_TODAS) {
    const res = await fetch(`${AGR_API}/alertas?horas=24`, { credentials: "include" });
    var alertas = await res.json();
  } else {
    if (!agrTiendaActual) return;
    const res = await fetch(`${AGR_API}/alertas?tienda=${agrTiendaActual}&horas=24`, { credentials: "include" });
    var alertas = await res.json();
  }

  const totalSinLimpiar = alertas.length;
  if (agrAlertasLimpiadasHasta) {
    alertas = alertas.filter((a) => a.timestamp > agrAlertasLimpiadasHasta);
  }

  const nuestras = alertas.filter((a) => a.tipo === "scraper_error").length;
  const otras = alertas.length - nuestras;
  const notaLimpiadas = totalSinLimpiar > alertas.length
    ? ` (${totalSinLimpiar - alertas.length} ocultas)`
    : "";
  resumen.textContent = alertas.length === 0
    ? (notaLimpiadas ? `Todo limpio${notaLimpiadas}` : "")
    : `${alertas.length} total — ${nuestras} nuestras (scraper) / ${otras} de agregadores${notaLimpiadas}`;

  if (alertas.length === 0) {
    lista.innerHTML = `<li style="color:var(--text-muted);">Sin alertas nuevas${totalSinLimpiar > 0 ? " desde que limpiaste" : " en 24h"}.</li>`;
    return;
  }
  lista.innerHTML = alertas
    .map((a) => {
      const hora = new Date(a.timestamp).toLocaleString("es-ES", { timeZone: "Europe/Madrid" });
      const claseTipo = a.tipo === "scraper_error" ? "tipo nuestro" : "tipo";
      const etiquetaTipo = a.tipo === "scraper_error" ? "Nuestro" : a.tipo;
      return `<li><span class="hora">${hora}</span><span class="${claseTipo}">${etiquetaTipo}</span>${a.mensaje}</li>`;
    })
    .join("");
}

async function agrEliminarTransicion(chequeoId, boton) {
  if (!confirm("¿Borrar este registro? Es para casos confirmados como error (p.ej. dirección o captura equivocada) -- no se puede deshacer.")) {
    return;
  }
  boton.disabled = true;
  boton.textContent = "Borrando...";
  try {
    const res = await fetch(`${AGR_API}/chequeo/${chequeoId}`, { method: "DELETE", credentials: "include" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    boton.closest("li").remove();
  } catch (err) {
    boton.disabled = false;
    boton.textContent = "🗑 Es un error, borrar";
    alert("No se pudo borrar. Inténtalo de nuevo.");
  }
}

function agrLimpiarTransiciones() {
  agrTransicionesLimpiadasHasta = new Date().toISOString();
  localStorage.setItem(AGR_TRANSICIONES_LIMPIADAS_KEY, agrTransicionesLimpiadasHasta);
  agrCargarTransiciones();
}

async function agrCargarTransiciones() {
  const lista = document.getElementById("agr-transiciones");
  const resumen = document.getElementById("agr-transiciones-resumen");
  if (!lista) return;
  const url = agrTiendaActual === AGR_TODAS
    ? `${AGR_API}/transiciones?horas=24`
    : `${AGR_API}/transiciones?tienda=${agrTiendaActual}&horas=24`;
  if (!agrTiendaActual) return;
  const res = await fetch(url, { credentials: "include" });
  let transiciones = await res.json();

  const totalSinLimpiar = transiciones.length;
  if (agrTransicionesLimpiadasHasta) {
    transiciones = transiciones.filter((t) => t.timestamp > agrTransicionesLimpiadasHasta);
  }
  if (resumen) {
    resumen.textContent = totalSinLimpiar > transiciones.length
      ? `(${totalSinLimpiar - transiciones.length} ocultas)`
      : "";
  }

  if (transiciones.length === 0) {
    const motivo = totalSinLimpiar > 0
      ? "Sin transiciones nuevas desde que limpiaste."
      : "Ningún punto ha pasado de disponible a no disponible en las últimas 24h.";
    lista.innerHTML = `<li style="color:var(--text-muted);">${motivo}</li>`;
    return;
  }
  lista.innerHTML = transiciones
    .map((t) => {
      const opcionesHora = { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Madrid" };
      const hora = new Date(t.timestamp).toLocaleString("es-ES", opcionesHora);
      const nombre = AGR_NOMBRE_AGREGADOR[t.agregador] || t.agregador;
      const direccion = t.direccion_text || `${t.lat?.toFixed(5)}, ${t.lng?.toFixed(5)}`;
      const tiendaLinea = agrTiendaActual === AGR_TODAS && t.nombre_tienda ? `${t.nombre_tienda} — ` : "";
      const horaAnterior = t.timestamp_anterior
        ? new Date(t.timestamp_anterior).toLocaleString("es-ES", opcionesHora)
        : null;
      const duracionHtml = horaAnterior
        ? `<div class="agr-trans-duracion">✅ Disponible hasta las ${horaAnterior} · ❌ ya no desde las ${hora}${t.duracion_disponible ? ` (${t.duracion_disponible})` : ""}</div>`
        : "";
      const captura = t.tiene_captura
        ? `<a href="${AGR_API}/capturas/${t.id}" target="_blank" rel="noopener" class="agr-trans-link">📷 Ver captura</a>`
        : '<span style="color:var(--text-muted);font-size:0.72rem;">Sin captura</span>';
      return `<li>
        <div class="agr-trans-meta">
          <span class="agr-trans-hora">${hora}</span>
          <span class="agr-trans-agregador ${t.agregador}">${nombre}</span>
        </div>
        <div>
          <div class="agr-trans-direccion">${tiendaLinea}${direccion}</div>
          <div class="agr-trans-bloqueo">${t.mensaje_bloqueo || "No disponible"}</div>
          ${duracionHtml}
        </div>
        <div class="agr-trans-acciones">
          ${captura}
          <button type="button" class="agr-trans-link agr-trans-borrar" onclick="agrEliminarTransicion(${t.id}, this)">🗑 Es un error, borrar</button>
        </div>
      </li>`;
    })
    .join("");
}

let agrPoligonoLayers = []; // polígono(s) de límite real + sus puntos de vértice, sobre agrMap
let agrUnionLayers = []; // contorno(s) de la unión de cobertura (turf.union), uno por agregador cuando "mostrar cobertura combinada" está activo

// "Solo dots nuevos": guarda el id más alto ya visto al activar el filtro,
// así el mapa solo dibuja los puntos del grid creados DESPUÉS de ese
// momento -- para ver en vivo dónde va cayendo la búsqueda de límite de
// cobertura sin el ruido de todo el grid ya existente. Por tienda, en
// localStorage, para que sobreviva a los refrescos automáticos (cada 30s)
// y a recargar la página.
function agrSoloNuevosKey(tienda) {
  return `agr_solo_nuevos_baseline_${tienda}`;
}

function agrSoloNuevosBaseline() {
  if (!agrTiendaActual) return null;
  const v = localStorage.getItem(agrSoloNuevosKey(agrTiendaActual));
  return v == null ? null : parseInt(v, 10);
}

function agrToggleSoloNuevos() {
  const activo = document.getElementById("agr-solo-nuevos")?.checked;
  if (!agrTiendaActual) return;
  if (activo) {
    // El máximo id ya cargado en el mapa ahora mismo -- todo lo que se cree
    // a partir de aquí tendrá un id mayor. Se excluyen los manuales del
    // cálculo: sus ids son de una tanda aparte y normalmente más alta (se
    // añaden después, a mano), así que si se contasen aquí, el baseline
    // quedaría por encima de TODOS los ids de grid/límite -- el filtro
    // acabaría ocultándolos todos y "solo nuevos" pasaría a comportarse
    // exactamente igual que "solo manuales" (confirmado por el usuario
    // 09/08: los dos primeros checkboxes hacían lo mismo).
    const maxId = agrDireccionMarkers.reduce(
      (max, m) => (m._agrDir && m._agrDir.origen !== "manual" ? Math.max(max, m._agrDir.id || 0) : max),
      0
    );
    localStorage.setItem(agrSoloNuevosKey(agrTiendaActual), String(maxId));
  } else {
    localStorage.removeItem(agrSoloNuevosKey(agrTiendaActual));
  }
  agrActualizarMarcadores();
  agrRecalcularContador();
}

// Mostrar/ocultar el polígono de límite real (y sus puntos de vértice) --
// preferencia general, no por tienda (a diferencia de "solo nuevos"), y
// activada por defecto si nunca se ha tocado.
const AGR_MOSTRAR_POLIGONO_KEY = "agr_mostrar_poligono_limite";

function agrMostrarPoligonoActivo() {
  const v = localStorage.getItem(AGR_MOSTRAR_POLIGONO_KEY);
  return v == null ? true : v === "1";
}

function agrToggleMostrarPoligono() {
  const activo = document.getElementById("agr-mostrar-poligono")?.checked;
  localStorage.setItem(AGR_MOSTRAR_POLIGONO_KEY, activo ? "1" : "0");
  agrActualizarPoligonoLimite();
}

function agrMoverPunto(lat, lng, bearingDeg, distanciaKm) {
  // Igual que _mover_punto en el backend: punto de destino a una distancia
  // y rumbo dados desde (lat, lng), sobre la esfera terrestre.
  const R = 6371;
  const bearing = (bearingDeg * Math.PI) / 180;
  const lat1 = (lat * Math.PI) / 180;
  const lng1 = (lng * Math.PI) / 180;
  const lat2 = Math.asin(
    Math.sin(lat1) * Math.cos(distanciaKm / R) + Math.cos(lat1) * Math.sin(distanciaKm / R) * Math.cos(bearing)
  );
  const lng2 = lng1 + Math.atan2(
    Math.sin(bearing) * Math.sin(distanciaKm / R) * Math.cos(lat1),
    Math.cos(distanciaKm / R) - Math.sin(lat1) * Math.sin(lat2)
  );
  return [(lat2 * 180) / Math.PI, (lng2 * 180) / Math.PI];
}

function agrAnguloDesde(centro, latlng) {
  // Inverso de agrMoverPunto: rumbo real (0-360°) desde el centro hasta un
  // punto -- para ordenar los vértices del polígono por su posición REAL en
  // vez del ángulo que se pidió al muestrear (que puede no coincidir si el
  // punto se desplazó a la calle numerada más cercana).
  const lat1 = (centro.lat * Math.PI) / 180, lng1 = (centro.lng * Math.PI) / 180;
  const lat2 = (latlng[0] * Math.PI) / 180, lng2 = (latlng[1] * Math.PI) / 180;
  const y = Math.sin(lng2 - lng1) * Math.cos(lat2);
  const x = Math.cos(lat1) * Math.sin(lat2) - Math.sin(lat1) * Math.cos(lat2) * Math.cos(lng2 - lng1);
  return ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360;
}

function agrRadioDeLimite(limite) {
  // limite_km es el dato bueno; si es null, el "nota" casi siempre trae un
  // número aprovechable ("no disponible incluso a 0.77km" -> cierre real
  // cerca de la tienda, ">= 5.0km" -> cota inferior porque no se encontró
  // el borde) -- mejor esa aproximación que dejar un hueco en el polígono.
  // "sin datos (todo falló)" NO trae número -- antes caía a 0.05km por
  // defecto, dibujando el vértice literalmente ENCIMA de la tienda y
  // creando una "pincelada" recta hacia el centro y de vuelta que parecía
  // decir "aquí no hay cobertura" cuando en realidad es que no hay NINGÚN
  // dato en esa dirección (confirmado en vivo 09/08 con La Gavia). Devolver
  // null aquí hace que ese ángulo se salte del polígono en vez de mentir.
  if (limite.limite_km != null) return limite.limite_km;
  const m = (limite.nota || "").match(/(\d+\.?\d*)\s*km/);
  return m ? parseFloat(m[1]) : null;
}

function agrLimpiarPoligonoLimite() {
  agrPoligonoLayers.forEach((l) => agrMap && agrMap.removeLayer(l));
  agrPoligonoLayers = [];
  agrUnionLayers.forEach((l) => agrMap && agrMap.removeLayer(l));
  agrUnionLayers = [];
}

const AGR_MOSTRAR_UNION_KEY = "agr_mostrar_union";

function agrMostrarUnionActivo() {
  return localStorage.getItem(AGR_MOSTRAR_UNION_KEY) === "1";
}

function agrToggleMostrarUnion() {
  const activo = document.getElementById("agr-mostrar-union")?.checked;
  localStorage.setItem(AGR_MOSTRAR_UNION_KEY, activo ? "1" : "0");
  agrActualizarPoligonoLimite();
}

function agrDibujarUnionCobertura(anillosPorAgregador) {
  if (!agrMostrarUnionActivo() || !agrMap) return;
  Object.entries(anillosPorAgregador).forEach(([agregador, anillos]) => {
    // La unión solo aporta algo con 2+ tiendas -- con una sola, la unión
    // ES ese mismo polígono, ya visible.
    if (anillos.length < 2) return;
    let poligonos = anillos.map((anillo) => turf.polygon([anillo]));
    let union = poligonos[0];
    for (let i = 1; i < poligonos.length; i++) {
      try {
        // API de turf@6: union(poly1, poly2) toma dos Features directos,
        // no una FeatureCollection (eso es turf@7).
        const combinado = turf.union(union, poligonos[i]);
        if (combinado) union = combinado;
      } catch (err) {
        // turf.union puede fallar con geometrías inválidas (auto-
        // intersecciones del propio polígono araña) -- mejor omitir la
        // unión de ese agregador que romper el mapa entero.
        console.warn("No se pudo unir el polígono de", agregador, err);
        return;
      }
    }
    const color = AGR_COLOR_MARCA[agregador] || "#333";
    // Turf/GeoJSON puede devolver Polygon o MultiPolygon (si hay tiendas
    // sin solape real entre sí, quedan como piezas separadas) -- Leaflet
    // entiende ambos directamente vía geoJSON().
    const capa = L.geoJSON(union, {
      style: { color: "#1a1a1a", weight: 3, dashArray: "6 4", fillColor: color, fillOpacity: 0.12 },
    }).addTo(agrMap);
    agrUnionLayers.push(capa);
  });
}

function agrProyeccionLocal(centro, latlng) {
  // Coordenadas planas locales en km (x=Este, y=Norte), aproximación
  // equirectangular centrada en la tienda -- suficiente a esta escala
  // (unos pocos km) y necesaria para poder hacer geometría de segmentos
  // rectos de verdad (intersección rayo-segmento), no aproximaciones.
  const kmPorGradoLat = 111.32;
  const kmPorGradoLng = 111.32 * Math.cos((centro.lat * Math.PI) / 180);
  return [(latlng[1] - centro.lng) * kmPorGradoLng, (latlng[0] - centro.lat) * kmPorGradoLat];
}

function agrCruceConBorde(a, b, bearingDeg) {
  // Distancia (km) desde el centro hasta donde el rayo en ese rumbo cruza
  // el segmento recto a-b (coordenadas locales planas) -- la prueba
  // GEOMÉTRICA real de si un punto cae dentro o fuera del borde que
  // Leaflet dibuja entre dos vértices consecutivos. Interpolar el radio
  // linealmente por ángulo (lo que hacía antes) se desvía mucho de la
  // recta real cuando el hueco angular entre vértices es grande, dejando
  // fuera puntos disponibles que en el mapa se ven claramente más lejos
  // que el borde (confirmado en vivo 09/08). Null si el rayo no cruza el
  // segmento (no debería pasar si el ángulo cae entre los dos vértices).
  const dx = b[0] - a[0], dy = b[1] - a[1];
  const rad = (bearingDeg * Math.PI) / 180;
  const dirX = Math.sin(rad), dirY = Math.cos(rad);
  const D = dx * dirY - dy * dirX;
  if (Math.abs(D) < 1e-9) return null;
  const t = (dx * a[1] - dy * a[0]) / D;
  const s = (dirX * a[1] - dirY * a[0]) / D;
  if (t < 0 || s < -0.01 || s > 1.01) return null;
  return t;
}

function agrDibujarPoligonoLimite(limites, centro, color, direccionesTienda) {
  // Polígono "araña/radar": un vértice por ángulo, a la distancia real del
  // límite de cobertura en esa dirección concreta -- a diferencia del
  // envolvente convexo, esto SÍ puede representar huecos de cobertura (ej.
  // cerrado al norte, abierto al sur), porque conecta los vértices en orden
  // angular en vez de "abombar hacia fuera". Además marca cada vértice con
  // un punto clicable (ángulo + límite exacto de esa dirección).
  if (!limites || limites.length === 0) return null;
  const agregador = limites[0].agregador;
  const base = [...limites]
    // "sin datos (todo falló)" no aporta ni siquiera una cota aproximada --
    // se salta ese ángulo del polígono en vez de inventar un radio (ver
    // agrRadioDeLimite). Deja un hueco angular más ancho, pero eso es
    // honesto: no sabemos qué pasa ahí, en vez de fingir que la cobertura
    // colapsa a cero justo en ese punto.
    .filter((l) => agrRadioDeLimite(l) != null)
    .map((l) => {
      const radio = Math.max(agrRadioDeLimite(l), 0.05);
      // Filas guardadas antes de este cambio no tienen lat/lng reales -- se
      // cae de vuelta al punto geométrico puro (recta centro-ángulo-
      // distancia) hasta que ese ángulo se vuelva a calcular.
      const latlngReal = l.lat != null && l.lng != null ? [l.lat, l.lng] : null;
      const latlng = latlngReal || agrMoverPunto(centro.lat, centro.lng, l.angulo_grados, radio);
      return {
        angulo: l.angulo_grados,
        radio,
        limite: l,
        latlngReal,
        latlng,
        bearingReal: agrAnguloDesde(centro, latlng),
        local: agrProyeccionLocal(centro, latlng),
        extendidoPor: null,
      };
    })
    // Se ordena por el ángulo REAL de cada posición (no el pedido) -- dibujar
    // en la dirección REAL comprobada puede desplazar un vértice de su
    // ángulo nominal (zonas con pocas calles numeradas geocodifican varios
    // ángulos pedidos a la misma calle o a calles muy próximas). Conectar
    // por el ángulo pedido cruzaba las líneas del polígono en esos casos
    // (confirmado en vivo 09/08 con La Gavia).
    .sort((a, b) => a.bearingReal - b.bearingReal);

  // El muestreo por ángulos fijos (cada 45°/22.5°) puede dejar huecos donde
  // un punto ya comprobado y disponible (grid normal) queda fuera del borde
  // recto que conecta dos vértices vecinos -- es más importante reflejar la
  // cobertura real ya conocida que ceñirse a los ángulos exactos del
  // muestreo (pedido explícito del usuario 09/08, con un caso real: un dot
  // verde disponible quedaba fuera del polígono aunque el radio
  // "interpolado" dijera que no -- por eso se usa la intersección
  // geométrica real con el segmento, no una interpolación lineal).
  const TOLERANCIA_ANGULO_GRADOS = 3; // por debajo de esto es "la misma dirección ya muestreada", no un hueco distinto
  const puntosLejanos = [];
  (direccionesTienda || [])
    .filter((d) => (d.detalle || {})[agregador]?.estado === "disponible" && d.lat != null && d.lng != null && d.distancia_km != null)
    .forEach((d) => {
      const latlng = [d.lat, d.lng];
      const bearing = agrAnguloDesde(centro, latlng);
      const vecino = base.find((b) => {
        const diff = Math.abs(b.bearingReal - bearing);
        return Math.min(diff, 360 - diff) < TOLERANCIA_ANGULO_GRADOS;
      });
      if (vecino) {
        // Misma dirección que un vértice ya muestreado (dentro de la
        // tolerancia) -- se EXTIENDE ese vértice en vez de dibujar un punto
        // nuevo pegado al lado. Dos dots casi encima el uno del otro
        // confundían más de lo que ayudaban (confirmado en vivo 09/08).
        if (d.distancia_km > vecino.radio) {
          vecino.radio = d.distancia_km;
          vecino.latlngReal = latlng;
          vecino.latlng = latlng;
          vecino.bearingReal = bearing;
          vecino.local = agrProyeccionLocal(centro, latlng);
          vecino.extendidoPor = d;
        }
        return;
      }
      if (base.length < 2) return; // no hay borde todavía con el que comparar
      let borde = null;
      for (let i = 0; i < base.length; i++) {
        const a = base[i], b = base[(i + 1) % base.length];
        let a0 = a.bearingReal, a1 = b.bearingReal;
        if (a1 <= a0) a1 += 360;
        let ang = bearing;
        if (ang < a0) ang += 360;
        if (ang >= a0 && ang <= a1) { borde = [a, b]; break; }
      }
      if (!borde) return;
      const cruce = agrCruceConBorde(borde[0].local, borde[1].local, bearing);
      if (cruce == null || d.distancia_km > cruce + 0.05) {
        puntosLejanos.push({ angulo: d.angulo_grados, radio: d.distancia_km, dir: d, latlng, bearingReal: bearing });
      }
    });

  // Espejo de puntosLejanos, pero hacia dentro: un punto NO disponible que
  // cae dentro del borde recto entre dos vértices vecinos es la misma
  // situación que un disponible que cae fuera, solo que el hueco angular del
  // muestreo esconde una zona SIN cobertura en vez de una CON cobertura no
  // detectada. Sin esto el polígono nunca se corrige hacia dentro -- solo se
  // ensancha (ver el bloque anterior) -- y deja rojos claramente dentro del
  // área sombreada, que es justo lo que se ve mal en el mapa (confirmado por
  // el usuario 09/08: rojos dentro del polígono en varios agregadores).
  const puntosCercanos = [];
  (direccionesTienda || [])
    .filter((d) => (d.detalle || {})[agregador]?.estado === "no_disponible" && d.lat != null && d.lng != null && d.distancia_km != null)
    .forEach((d) => {
      if (base.length < 2) return; // no hay borde todavía con el que comparar
      const latlng = [d.lat, d.lng];
      const bearing = agrAnguloDesde(centro, latlng);
      const yaMuestreado = base.some((b) => {
        const diff = Math.abs(b.bearingReal - bearing);
        return Math.min(diff, 360 - diff) < TOLERANCIA_ANGULO_GRADOS;
      });
      // Si ya hay un vértice medido (búsqueda de límite) casi en la misma
      // dirección, se respeta ese dato -- viene de una búsqueda binaria
      // real, más fiable que un único punto de grid.
      if (yaMuestreado) return;
      let borde = null;
      for (let i = 0; i < base.length; i++) {
        const a = base[i], b = base[(i + 1) % base.length];
        let a0 = a.bearingReal, a1 = b.bearingReal;
        if (a1 <= a0) a1 += 360;
        let ang = bearing;
        if (ang < a0) ang += 360;
        if (ang >= a0 && ang <= a1) { borde = [a, b]; break; }
      }
      if (!borde) return;
      const cruce = agrCruceConBorde(borde[0].local, borde[1].local, bearing);
      if (cruce != null && d.distancia_km < cruce - 0.05) {
        puntosCercanos.push({ angulo: d.angulo_grados, radio: d.distancia_km, dir: d, latlng, bearingReal: bearing });
      }
    });

  const ordenados = [...base, ...puntosLejanos, ...puntosCercanos].sort((a, b) => a.bearingReal - b.bearingReal);
  if (ordenados.length === 0) return null;

  const vertices = ordenados.map((p) => ({ latlng: p.latlng, punto: p }));
  // Con la "cobertura combinada" activa, el polígono y los vértices de CADA
  // tienda por separado son puro ruido -- varias estrellas solapadas se ven
  // como una maraña de líneas cruzadas y puntos por dentro (pedido explícito
  // del usuario 09/08: "que no veamos nada dentro", comparando con lo limpio
  // que se ve una tienda sola). En ese modo solo interesa el contorno de la
  // unión (agrDibujarUnionCobertura), así que aquí nos saltamos el dibujado
  // individual pero seguimos calculando el anillo más abajo para la unión.
  const ocultarDetalle = agrMostrarUnionActivo();

  // Con menos de 3 vértices no hay figura que cerrar (un polígono real
  // necesita al menos un triángulo) -- pero los puntos ya comprobados SÍ se
  // muestran igual, para no dejar la tienda "en blanco" mientras la
  // búsqueda de límite todavía va por su segundo o tercer ángulo (visto en
  // vivo 09/08: con 2 de 8 ángulos guardados no aparecía nada en el mapa).
  let poligono = null;
  if (vertices.length >= 3 && !ocultarDetalle) {
    poligono = L.polygon(vertices.map((v) => v.latlng), {
      color, weight: 4, opacity: 1, fillColor: color, fillOpacity: 0.28,
    }).addTo(agrMap);
    agrPoligonoLayers.push(poligono);
  }

  (ocultarDetalle ? [] : vertices).forEach(({ latlng, punto }) => {
    if (punto.limite) {
      const limite = punto.limite;
      const etiqueta = punto.extendidoPor
        ? `${punto.radio.toFixed(2)}km (extendido -- un punto ya conocido llega más lejos que el ${limite.limite_km != null ? limite.limite_km.toFixed(2) + "km" : "~" + agrRadioDeLimite(limite).toFixed(2) + "km"} de la búsqueda de límite en esta misma dirección)`
        : limite.limite_km != null
        ? `${limite.limite_km.toFixed(2)}km`
        : `~${punto.radio.toFixed(2)}km (${limite.nota || "sin dato exacto"})`;
      const direccionMostrar = punto.extendidoPor?.direccion_text || limite.direccion_text;
      const marker = L.circleMarker(latlng, {
        radius: 6, color: "#1a1a1a", weight: 1.5, fillColor: color, fillOpacity: 1,
      })
        .bindPopup(`<b>${AGR_NOMBRE_AGREGADOR[limite.agregador] || limite.agregador}</b><br>Ángulo: ${limite.angulo_grados}°<br>Límite: ${etiqueta}<br>Dirección: <span class="agr-poligono-dir">${direccionMostrar || "cargando..."}</span>`)
        .addTo(agrMap);
      // Filas nuevas ya traen la dirección real que se probó de verdad
      // (guardada por buscar_limite_cobertura.py), y los vértices extendidos
      // ya traen la del punto del grid que los extendió -- filas viejas sin
      // ninguno de los dos caen de vuelta al reverse geocoding del punto
      // geométrico, solo al abrir el popup (no al dibujar el polígono
      // entero) para no disparar de golpe una llamada a Nominatim por
      // vértice, que va limitado a 1 petición/segundo.
      if (!direccionMostrar) {
        marker.on("popupopen", async () => {
          const span = marker.getPopup().getElement()?.querySelector(".agr-poligono-dir");
          if (!span || span.dataset.cargado) return;
          span.dataset.cargado = "1";
          try {
            const res = await fetch(`${AGR_API}/geocodificar-inverso?lat=${latlng[0]}&lng=${latlng[1]}`, { credentials: "include" });
            const datos = res.ok ? await res.json() : null;
            span.textContent = datos?.direccion || "no disponible";
          } catch {
            span.textContent = "no disponible";
          }
        });
      }
      agrPoligonoLayers.push(marker);
    } else {
      // Vértice extra: punto del grid normal, más lejos (disponible,
      // puntosLejanos) o más cerca (no disponible, puntosCercanos) de lo que
      // el muestreo por ángulos alcanzó -- la dirección ya se conoce (no
      // hace falta reverse geocoding).
      const esCercano = (punto.dir.detalle || {})[agregador]?.estado === "no_disponible";
      const marker = L.circleMarker(latlng, {
        radius: 6, color: "#ffffff", weight: 2, fillColor: esCercano ? "#d03b3b" : color, fillOpacity: 1,
      })
        .bindPopup(
          `<b>${AGR_NOMBRE_AGREGADOR[agregador] || agregador}</b><br>` +
            (esCercano
              ? `Punto ya NO disponible, más cerca de lo muestreado por ángulo`
              : `Punto ya disponible, más lejos de lo muestreado por ángulo`) +
            `<br>Distancia: ${punto.radio.toFixed(2)}km<br>Dirección: ${punto.dir.direccion_text || "?"}`
        )
        .addTo(agrMap);
      agrPoligonoLayers.push(marker);
    }
  });

  // anillo GeoJSON [lng,lat] (Turf/GeoJSON van al revés que Leaflet) para
  // poder calcular la unión real de varias tiendas con turf.union -- solo
  // tiene sentido si hay polígono de verdad (3+ vértices) y cerrado (el
  // primer punto repetido al final).
  const anillo = vertices.length >= 3
    ? [...vertices.map((v) => [v.latlng[1], v.latlng[0]]), [vertices[0].latlng[1], vertices[0].latlng[0]]]
    : null;

  return { n: vertices.length, anillo, agregador };
}

async function agrActualizarPoligonoLimite() {
  agrLimpiarPoligonoLimite();
  const nota = document.getElementById("agr-cobertura-nota");
  const checkboxPoligono = document.getElementById("agr-mostrar-poligono");
  if (checkboxPoligono) checkboxPoligono.checked = agrMostrarPoligonoActivo();
  const checkboxUnion = document.getElementById("agr-mostrar-union");
  if (checkboxUnion) checkboxUnion.checked = agrMostrarUnionActivo();

  if (!agrMap || !agrTiendaActual || !agrMostrarPoligonoActivo()) {
    if (nota) nota.textContent = "";
    agrActualizarContadorPoligono(0);
    return;
  }

  // El mapa siempre renderiza vía agrRenderMapaTodas (aunque sea una sola
  // tienda), así que agrCentrosPorTienda ya refleja exactamente las chips
  // activas -- se dibuja el polígono de cada una de esas, en paralelo.
  const tiendas = Object.keys(agrCentrosPorTienda);
  const porTienda = await Promise.all(
    tiendas.map((tienda) =>
      fetch(`${AGR_API}/limites/${tienda}`, { credentials: "include" }).then((r) => (r.ok ? r.json() : []))
    )
  );

  let totalVertices = 0;
  const anillosPorAgregador = {}; // nombre -> [anillo, anillo, ...] (uno por tienda con polígono cerrado) -- para la unión
  const agregarAnillo = (resultado) => {
    totalVertices += resultado.n;
    if (resultado.anillo) {
      (anillosPorAgregador[resultado.agregador] ||= []).push(resultado.anillo);
    }
  };
  tiendas.forEach((tienda, i) => {
    const centro = agrCentrosPorTienda[tienda] || agrTiendaCentro;
    if (!centro) return;
    const limites = porTienda[i];
    const direccionesTienda = agrDireccionesPorTienda[tienda];
    if (agrFiltroAgregador) {
      const limitesAgregador = limites.filter((l) => l.agregador === agrFiltroAgregador);
      agregarAnillo(agrDibujarPoligonoLimite(limitesAgregador, centro, AGR_COLOR_MARCA[agrFiltroAgregador] || "#0ca30c", direccionesTienda));
    } else {
      Object.keys(AGR_NOMBRE_AGREGADOR).forEach((nombre) => {
        const limitesAgregador = limites.filter((l) => l.agregador === nombre);
        agregarAnillo(agrDibujarPoligonoLimite(limitesAgregador, centro, AGR_COLOR_MARCA[nombre] || "#888", direccionesTienda));
      });
    }
  });
  const algunoDibujado = totalVertices > 0;
  agrActualizarContadorPoligono(totalVertices);
  agrDibujarUnionCobertura(anillosPorAgregador);

  if (nota) {
    nota.textContent = algunoDibujado
      ? (agrFiltroAgregador
          ? "Polígono con la forma real de cobertura de este agregador -- un vértice por dirección comprobada, a su límite real (puede tener huecos: cerrado en una dirección, abierto en otra)."
          : "Un polígono por agregador (JustEat naranja, Glovo amarillo, Uber Eats verde) con la forma real de cobertura (límite comprobado en cada dirección, no un envolvente aproximado).")
      : "";
  }
}

async function agrCargarEstado() {
  const pill = document.getElementById("agr-estado");
  try {
    const res = await fetch(`${AGR_API}/estado`, { credentials: "include" });
    const estado = await res.json();
    if (!estado.es_horario_apertura) {
      pill.textContent = "⏸ Fuera de horario";
      pill.className = "agr-estado-pill neutro";
      return;
    }
    if (estado.cercano.retrasado || estado.completo.retrasado) {
      pill.textContent = "⚠ Scraper retrasado";
      pill.className = "agr-estado-pill alerta";
      return;
    }
    pill.textContent = "● Scraper OK";
    pill.className = "agr-estado-pill ok";
  } catch {
    pill.textContent = "? Estado desconocido";
    pill.className = "agr-estado-pill neutro";
  }
}

async function agrCargarTodo() {
  // agrCargarMapa() debe ir primero: fija agrTiendaCentro/agrCentrosPorTienda,
  // que agrActualizarPoligonoLimite() usa para calcular los vértices del polígono.
  await agrCargarMapa();
  await Promise.all([agrCargarTabla(), agrCargarResumen(), agrCargarAlertas(), agrCargarTransiciones(), agrCargarEstado()]);
  document.getElementById("agr-actualizado").textContent = "Actualizado: " + new Date().toLocaleTimeString("es-ES", { timeZone: "Europe/Madrid" });
}

document.addEventListener("DOMContentLoaded", async () => {
  const user = await checkAuth("/agregadores.html");
  if (!user) return;
  if (!(user.modulos || []).includes("agregadores")) {
    window.location.href = "/";
    return;
  }
  wireUserBar(user);
  agrWireFiltroAgregador();
  agrAplicarColapsoTabla();

  await agrCargarTiendas();
  await agrCargarTodo();

  if (agrIntervalo) clearInterval(agrIntervalo);
  agrIntervalo = setInterval(agrCargarTodo, 30000);
});

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
let agrUsuarioActual = null;
let agrModoAnadir = false;
let agrModoUnir = false;
let agrUnionPendiente = null; // dir elegida como primer punto del puente, en espera del segundo clic
let agrModoPincel = false;
let agrPincelPuntos = []; // [[lat,lng], ...] trazo en curso, se convierte en agregadores_rellenos al terminar
let agrPincelPreview = null; // L.polygon de vista previa mientras se dibuja
let agrPincelMarkers = []; // circleMarkers de cada punto clicado del trazo
let agrTiendaCentro = null;
let agrCentrosPorTienda = {}; // slug -> {lat,lng}, usado en la vista "Todas"
// Las 6 tiendas SIEMPRE, sin filtrar por chips activas -- agrCentrosPorTienda
// solo trae las seleccionadas, así que con una sola tienda vista, "cuál está
// más cerca" no tenía con qué comparar y siempre ganaba esa única tienda por
// defecto (bug confirmado en vivo 10/08 con Caleido: dots a 8km realmente
// más cercanos a Princesa/Plenilunio se seguían contando como de Caleido).
let agrCentrosTodos = {};
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
// sin chocar con otro agregador. Se oscureció a un dorado (#c99a00) para
// contrastar, pero eso lo acercaba demasiado al naranja de JustEat, difíciles
// de diferenciar de un vistazo (pedido explícito del usuario 26/08: "amarillo
// pollito" -- un amarillo vivo, claramente distinto del naranja). Los dots
// llevan borde negro (ver .agr-marker-dot span en agregadores.html), así que
// no deberían perder legibilidad como los polígonos de antes; si el polígono
// de Glovo vuelve a perderse contra el mapa, hace falta separar el color de
// dots del de polígonos en vez de compartir esta misma constante.
const AGR_COLOR_MARCA = { justeat: "#e8590c", glovo: "#ffd500", ubereats: "#06c167" };
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

function agrPuntoVisiblePorCapa(dir) {
  // Cada agregador es una capa independiente (ver agregadores_direcciones_estado
  // en el backend): un punto desactivado en JustEat sigue vivo para Glovo y
  // Uber Eats. Con un agregador filtrado, se oculta si está desactivado en
  // ESE. En "Todos" solo se oculta si está desactivado en los 3 -- si no,
  // seguiría contando como visible para el/los agregador(es) donde sigue
  // activo (pedido explícito del usuario 10/08).
  const inactivo = dir.inactivo_para || [];
  if (agrFiltroAgregador) return !inactivo.includes(agrFiltroAgregador);
  return inactivo.length < Object.keys(AGR_NOMBRE_AGREGADOR).length;
}

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

function agrMarcadorVisible(dir) {
  if (!agrPuntoVisiblePorCapa(dir)) return false;
  if (agrEstadosOcultos.has(agrCategoriaDireccion(dir))) return false;
  return true;
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
    if (agrModoPincel) { agrPincelClick(e.latlng.lat, e.latlng.lng); return; }
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

function agrEsTiendaMasCercana(centro, lat, lng) {
  const candidatas = Object.keys(agrCentrosTodos).length ? agrCentrosTodos : agrCentrosPorTienda;
  let mejorSlug = null, mejorDist = Infinity;
  Object.entries(candidatas).forEach(([slug, c]) => {
    const d = agrDistanciaKm(c.lat, c.lng, lat, lng);
    if (d < mejorDist) { mejorDist = d; mejorSlug = slug; }
  });
  return mejorSlug == null || mejorSlug === centro.tienda;
}

function agrIconoDireccion(dir) {
  const categoria = agrCategoriaDireccion(dir);
  // Vista "Todos" con disponibilidad mixta ("algunos"): en vez de un amarillo
  // genérico, el círculo se reparte en franjas del color de MARCA de cada
  // agregador que sí tiene disponible ahí (pedido explícito del usuario 26/08:
  // "si está uber y glovo se pinta mitad verde mitad amarillo"). Con uno solo
  // disponible sale sólido de su color; con los tres disponibles ya cae en la
  // categoría "todos" (verde sólido, sin cambios -- "si están los 3 pues es un
  // verde completamente"). Solo aplica en "Todos": con un agregador filtrado ya
  // solo hay un color posible (el suyo), no tiene sentido partir el círculo.
  if (!agrFiltroAgregador && categoria === "algunos") {
    const disponibles = Object.entries(dir.detalle || {})
      .filter(([, info]) => info.estado === "disponible")
      .map(([nombre]) => AGR_COLOR_MARCA[nombre] || "#0ca30c");
    if (disponibles.length > 0) {
      const paso = 100 / disponibles.length;
      const franjas = disponibles
        .map((color, i) => `${color} ${(i * paso).toFixed(2)}% ${((i + 1) * paso).toFixed(2)}%`)
        .join(", ");
      return L.divIcon({
        className: "agr-marker-dot",
        html: `<span style="background:conic-gradient(${franjas});"></span>`,
        iconSize: [16, 16],
        iconAnchor: [8, 8],
      });
    }
  }
  const color = AGR_COLOR_CATEGORIA[categoria] || "#898781";
  return L.divIcon({
    className: "agr-marker-dot",
    html: `<span style="background:${color}"></span>`,
    iconSize: [16, 16],
    iconAnchor: [8, 8],
  });
}

function agrIconoVerticePoligono(colorBorde, colorRelleno, diametroPx, punteado, opacidadRelleno) {
  // Vértice del polígono (límite real o "extra") como L.marker arrastrable
  // -- antes eran L.circleMarker, que en Leaflet NO se puede arrastrar
  // (draggable solo existe en L.marker). Se replica el mismo look con un
  // divIcon: circulo con borde de color, mismo tamaño/estilo que antes
  // (pedido explícito del usuario 10/08: "no quiero quitarlos quiero
  // moverlos para ajustar el polígono").
  const estiloBorde = punteado ? "dashed" : "solid";
  return L.divIcon({
    className: "agr-marker-vertice",
    html: `<span style="display:block;width:${diametroPx}px;height:${diametroPx}px;border-radius:50%;background:${colorRelleno};opacity:${opacidadRelleno};border:2px ${estiloBorde} ${colorBorde};box-sizing:border-box;"></span>`,
    iconSize: [diametroPx, diametroPx],
    iconAnchor: [diametroPx / 2, diametroPx / 2],
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
      const manual = info.verificado_por
        ? ` <span style="color:var(--text-muted);font-size:11px;">(👤 ${info.verificado_por})</span>`
        : "";
      return `${icono} ${nombreMostrar}${tiempo}${nota}${hora}${manual}`;
    })
    .join("<br>");
  const tiendaLinea = dir.tienda_nombre ? `<b>${dir.tienda_nombre}</b><br>` : "";
  // Botones de verificación manual: solo tienen sentido con UN agregador
  // filtrado (JustEat/Glovo/Uber Eats) -- si seleccionas ese agregador es
  // justamente porque vas a confirmar tú mismo el estado de sus puntos, no
  // tendría sentido escribir "disponible" a la vez en los 3 agregadores de
  // golpe con un solo clic (pedido explícito del usuario 10/08: quiere
  // poder priorizar y verificar puntos concretos a mano, sin esperar al
  // scraper -- "si clico en Uber Eats es porque voy a cambiar el estado de
  // los dots en Uber Eats").
  const verificarHtml = editable && agrFiltroAgregador
    ? `<div style="margin-top:6px;">
         <button type="button" class="btn btn-ghost" style="font-size:12px;padding:3px 8px;" onclick="agrVerificarManual(${dir.id}, '${agrFiltroAgregador}', true)">✅ Marcar disponible</button>
         <button type="button" class="btn btn-ghost" style="font-size:12px;padding:3px 8px;" onclick="agrVerificarManual(${dir.id}, '${agrFiltroAgregador}', false)">❌ Marcar no disponible</button>
       </div>`
    : "";
  // Herramienta "unir puntos" (ver agregadores_uniones): con el modo activo
  // y un agregador filtrado, el primer clic marca el punto de partida y el
  // segundo clic en otro dot los une -- pensada para cuando el usuario ve a
  // ojo dos dots disponibles con un hueco raro entre medias en el polígono
  // (pedido explícito del usuario 10/08).
  const unirHtml = editable && agrModoUnir && agrFiltroAgregador
    ? agrUnionPendiente && agrUnionPendiente.lat === dir.lat && agrUnionPendiente.lng === dir.lng
      ? `<div style="margin-top:6px;color:var(--acento-calido);font-size:12px;">🔗 Punto de partida -- haz clic en el segundo</div>`
      : `<div style="margin-top:6px;"><button type="button" class="btn btn-ghost" style="font-size:12px;padding:3px 8px;" onclick="agrUnionElegirPunto(${dir.lat}, ${dir.lng}, '${dir.tienda}', '${(dir.direccion_text || "punto").replace(/'/g, "\\'")}', ${dir.id})">🔗 ${agrUnionPendiente ? `Unir aquí (con ${agrUnionPendiente.etiqueta})` : "Unir con otro punto"}</button></div>`
    : "";
  const textoEliminar = agrFiltroAgregador
    ? `🗑️ Eliminar solo en ${AGR_NOMBRE_AGREGADOR[agrFiltroAgregador] || agrFiltroAgregador}`
    : "🗑️ Eliminar punto (los 3 agregadores)";
  const pieEditable = editable
    ? `<i style="color:var(--text-muted);font-size:11px;">Arrastra el punto para reubicarlo</i><br>
       <button type="button" class="btn btn-ghost" style="margin-top:6px;font-size:12px;padding:3px 8px;" onclick="agrEliminarPunto(${dir.id})">${textoEliminar}</button>`
    : "";
  return `${tiendaLinea}<b>${dir.direccion_text || "Punto de test"}</b><br>${dir.distancia_km.toFixed(2)} km · ${dir.angulo_grados}°<br>${detalleHtml || "Sin datos aún"}<br>${verificarHtml}${unirHtml}${pieEditable}`;
}

async function agrVerificarManual(direccionId, agregador, disponible) {
  const dir = agrMarkersPorId[direccionId]?._agrDir;
  const tienda = (dir && dir.tienda) || agrTiendaActual;
  if (!tienda || tienda === AGR_TODAS) {
    mostrarAviso("Selecciona una tienda concreta (no \"Todas\") para verificar un punto a mano.");
    return;
  }
  try {
    const res = await agrFetchConTimeout(`${AGR_API}/chequeo-manual`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tienda, agregador, direccion_id: direccionId, disponible }),
      credentials: "include",
    });
    if (!res.ok) throw new Error("No se pudo guardar la verificación");
    if (dir) {
      dir.detalle = dir.detalle || {};
      dir.detalle[agregador] = { estado: disponible ? "disponible" : "no_disponible", disponible, tiempo_entrega_min: null, timestamp: new Date().toISOString(), verificado_por: "tú" };
      if (disponible) dir.disponible_count = (dir.disponible_count || 0) + 1;
      else dir.no_disponible_count = (dir.no_disponible_count || 0) + 1;
    }
    agrActualizarMarcadores();
    agrActualizarLeyenda();
    agrRecalcularContador();
    // `dir` es el mismo objeto que agrDireccionesPorTienda[tienda] guarda
    // (misma referencia, no una copia -- ver agrRenderMapa/agrRenderMapaTodas),
    // así que mutar dir.detalle arriba ya es visible aquí: redibujar el
    // polígono ahora mismo hace que puntosLejanos/puntosCercanos (ver
    // agrDibujarPoligonoLimite) estiren o recorten el borde hasta este punto
    // al instante, sin esperar al refresco de 30s (pedido explícito del
    // usuario 10/08: "si lo doy como disponible el borde alcanza ese dot").
    agrActualizarPoligonoLimite();
    const marker = agrMarkersPorId[direccionId];
    if (marker && marker.isPopupOpen()) marker.closePopup();
  } catch (e) {
    mostrarAviso("No se pudo guardar la verificación manual. Inténtalo de nuevo.");
  }
}

async function agrMoverVerticeLimite(tienda, agregador, anguloGrados, lat, lng) {
  // Arrastrar un vértice negro (agregadores_limites) -- recalcula el límite
  // desde la nueva posición, en vez de solo poder borrarlo (pedido
  // explícito del usuario 10/08: "no quiero quitarlos quiero moverlos").
  try {
    const url = `${AGR_API}/limites/${tienda}?${new URLSearchParams({ agregador, angulo_grados: anguloGrados })}`;
    const res = await agrFetchConTimeout(url, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lat, lng }),
      credentials: "include",
    });
    if (!res.ok) throw new Error("No se pudo mover el vértice");
    agrActualizarPoligonoLimite();
  } catch (e) {
    mostrarAviso("No se pudo mover el vértice del borde. Inténtalo de nuevo.");
    agrActualizarPoligonoLimite(); // vuelve a la posición guardada de verdad
  }
}

async function agrMoverVerticeDireccion(dir, lat, lng) {
  // Arrastrar un vértice blanco (una dirección real, extendida/recortada
  // por puntosLejanos/Cercanos) -- reubica el punto de verdad, mismo
  // endpoint que el drag normal de un dot del mapa.
  try {
    const res = await agrFetchConTimeout(`${AGR_API}/direcciones/${dir.id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lat, lng }),
      credentials: "include",
    });
    if (!res.ok) throw new Error("No se pudo mover el punto");
    const actualizado = await res.json();
    dir.lat = actualizado.lat;
    dir.lng = actualizado.lng;
    dir.direccion_text = actualizado.direccion_text;
    agrActualizarPoligonoLimite();
  } catch (e) {
    mostrarAviso("No se pudo mover el punto. Inténtalo de nuevo.");
    agrActualizarPoligonoLimite();
  }
}

async function agrEliminarLimite(tienda, agregador, anguloGrados) {
  // Los vértices del borde (agregadores_limites) no son direcciones -- los
  // generó buscar_limite_cobertura.py con una búsqueda binaria, no vienen
  // del grid normal. No había forma de tocarlos desde el dashboard; esto
  // permite quitar uno puntual que se vea claramente mal (contaminado, muy
  // alejado del resto) sin tener que usar la API key a mano (pedido
  // explícito del usuario 10/08).
  if (!(await pedirConfirmacion("¿Quitar este vértice del borde? No es una dirección normal -- esto borra la medición de límite de ese ángulo, no un punto del mapa."))) return;
  try {
    const url = `${AGR_API}/limites/${tienda}?${new URLSearchParams({ agregador, angulo_grados: anguloGrados })}`;
    const res = await fetch(url, { method: "DELETE", credentials: "include" });
    if (!res.ok) throw new Error("No se pudo eliminar el vértice");
    agrActualizarPoligonoLimite();
  } catch (e) {
    mostrarAviso("No se pudo quitar el vértice. Inténtalo de nuevo.");
  }
}

async function agrEliminarPunto(direccionId) {
  try {
    // Con un agregador filtrado, borrar solo apaga esa capa (el punto sigue
    // vivo para los otros dos) -- sin filtro ("Todos"), es la baja global de
    // siempre (pedido explícito del usuario 10/08: cada agregador es una
    // capa independiente, borrar en uno no debe borrar en los demás).
    const url = agrFiltroAgregador
      ? `${AGR_API}/direcciones/${direccionId}?agregador=${encodeURIComponent(agrFiltroAgregador)}`
      : `${AGR_API}/direcciones/${direccionId}`;
    const res = await fetch(url, { method: "DELETE", credentials: "include" });
    if (!res.ok) throw new Error("No se pudo eliminar");
    const marker = agrMarkersPorId[direccionId];
    if (!marker) return;
    if (!agrFiltroAgregador) {
      agrMap.removeLayer(marker);
      delete agrMarkersPorId[direccionId];
      agrDireccionMarkers = agrDireccionMarkers.filter((m) => m !== marker);
    } else {
      const dir = marker._agrDir;
      dir.inactivo_para = [...new Set([...(dir.inactivo_para || []), agrFiltroAgregador])];
      marker.setIcon(agrIconoDireccion(dir));
      if (!agrMarcadorVisible(dir) && agrMap.hasLayer(marker)) agrMap.removeLayer(marker);
    }
    agrActualizarLeyenda();
    agrRecalcularContador();
    agrActualizarPoligonoLimite(); // si este punto estiraba/recortaba el borde (puntosLejanos/Cercanos), se recalcula ya
  } catch (e) {
    mostrarAviso("No se pudo eliminar el punto. Inténtalo de nuevo.");
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
    mostrarAviso("No se pudo añadir el punto. Inténtalo de nuevo.");
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
    mostrarAviso("No se pudo guardar la reubicación. Inténtalo de nuevo.");
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

  // Respeta "solo dots nuevos" Y "visible por capa" (no las categorías
  // ocultas -- la leyenda tiene que seguir mostrando el total real de una
  // categoría aunque esté oculta, si no nunca sabrías cuántos hay para
  // decidir si mostrarla). Antes contaba TODOS los puntos siempre, así que
  // con "solo nuevos" activo la leyenda seguía dando el total de siempre
  // mientras el contador de arriba decía 0 -- números contradictorios en la
  // misma pantalla (confirmado en vivo 09/08).
  //
  // agrPuntoVisiblePorCapa faltaba aquí: un punto desactivado para ESTE
  // agregador (inactivo_para) conserva su último chequeo real (p.ej. un
  // error viejo) en dir.detalle, así que sin este filtro la leyenda seguía
  // contándolo en su categoría aunque el mapa ya no lo dibuje -- confirmado
  // en vivo 26/08 con Uber Eats: leyenda decía "19 errores", el mapa solo
  // mostraba 3 puntos naranjas.
  const conteos = {};
  agrDireccionMarkers
    .filter((m) => agrPuntoVisiblePorCapa(m._agrDir))
    .forEach((m) => {
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
      const nuevoFiltro = btn.dataset.agregador || null;
      // Solo se resetea al cruzar la frontera "Todos" <-> un agregador
      // concreto (esos sí usan categorías distintas, ver AGR_LEYENDA_*).
      // Entre JustEat/Glovo/Uber Eats las categorías son las mismas
      // (disponible/no_disponible/error/sin_datos), así que mantener oculto
      // lo mismo sigue teniendo sentido (pedido explícito del usuario 10/08).
      if (!agrFiltroAgregador !== !nuevoFiltro) agrEstadosOcultos.clear();
      agrFiltroAgregador = nuevoFiltro;
      localStorage.setItem(AGR_FILTRO_AGREGADOR_KEY, agrFiltroAgregador || "");
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

function agrToggleModoUnir() {
  agrModoUnir = !agrModoUnir;
  agrUnionPendiente = null;
  const btn = document.getElementById("agr-btn-unir");
  if (btn) {
    btn.classList.toggle("activo", agrModoUnir);
    btn.textContent = agrModoUnir ? "✓ Clic en dos puntos para unir…" : "🔗 Unir puntos";
  }
  // El popup de los vértices del borde se genera como texto fijo al dibujar
  // el polígono (a diferencia del de los dots, que es una función y se
  // regenera solo) -- sin este redibujado, activar/desactivar el modo no se
  // reflejaba en los vértices ya dibujados hasta el próximo refresco de 30s
  // (confirmado por el usuario 10/08: "lo sigo viendo solo en los dots").
  agrActualizarPoligonoLimite();
}

// Punto genérico para la herramienta de unir -- sirve igual para un dot del
// grid que para un vértice ya calculado del borde (límite o extendido), que
// no siempre tiene una dirección real detrás y suele estar tapando al dot
// que hay justo debajo en el mapa (pedido explícito del usuario 10/08: "los
// dots ahora están justo debajo del vértice, no puedo acceder a ellos").
async function agrUnionElegirPunto(lat, lng, tienda, etiqueta, direccionId) {
  if (!agrModoUnir || !agrFiltroAgregador) return;
  if (!agrUnionPendiente) {
    agrUnionPendiente = { lat, lng, tienda, etiqueta, direccionId };
    if (agrMap) agrMap.closePopup();
    mostrarAviso(`Punto de partida marcado: ${etiqueta}.\nAhora haz clic en "🔗 Unir aquí" en el segundo punto.`);
    return;
  }
  if (agrUnionPendiente.lat === lat && agrUnionPendiente.lng === lng) return; // el mismo punto
  try {
    const res = await agrFetchConTimeout(`${AGR_API}/uniones`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        tienda: agrUnionPendiente.tienda || tienda,
        agregador: agrFiltroAgregador,
        lat_a: agrUnionPendiente.lat, lng_a: agrUnionPendiente.lng,
        lat_b: lat, lng_b: lng,
        direccion_id_a: agrUnionPendiente.direccionId ?? null,
        direccion_id_b: direccionId ?? null,
      }),
      credentials: "include",
    });
    if (!res.ok) throw new Error("No se pudo guardar la unión");
    if (agrMap) agrMap.closePopup();
    agrActualizarPoligonoLimite();
  } catch (e) {
    mostrarAviso("No se pudo unir los dos puntos. Inténtalo de nuevo.");
  } finally {
    agrUnionPendiente = null;
  }
}

function agrToggleModoPincel() {
  agrModoPincel = !agrModoPincel;
  agrPincelCancelar(); // limpia cualquier trazo a medio dibujar del uso anterior
  const btn = document.getElementById("agr-btn-pincel");
  if (btn) {
    btn.classList.toggle("activo", agrModoPincel);
    btn.textContent = agrModoPincel ? "✓ Clic para pintar el hueco…" : "🖌️ Pincel: rellenar hueco";
  }
  if (document.getElementById("agr-map")) {
    document.getElementById("agr-map").style.cursor = agrModoPincel ? "crosshair" : "";
  }
  if (agrModoPincel && !agrFiltroAgregador) {
    mostrarAviso("Elige primero un agregador concreto (JustEat/Glovo/Uber Eats) arriba -- el relleno se guarda por agregador.");
  }
}

// Cada clic en el mapa (con el pincel activo) añade un vértice al trazo --
// no hace falta que caiga sobre un dot o vértice existente, a diferencia de
// "unir puntos": el pincel pinta un ÁREA libre para tapar huecos que están
// DENTRO del polígono, no en el borde (pedido explícito del usuario 10/08:
// "hay unas zonas que debemos poder rellenar dentro del mismo polígono...
// pero no se como unirlas con los mismos puntos").
function agrPincelClick(lat, lng) {
  if (!agrFiltroAgregador) return;
  agrPincelPuntos.push([lat, lng]);
  const marker = L.circleMarker([lat, lng], { radius: 4, color: "#1a1a1a", weight: 1, fillColor: "#ffcc00", fillOpacity: 1 }).addTo(agrMap);
  agrPincelMarkers.push(marker);
  if (agrPincelPreview) { agrMap.removeLayer(agrPincelPreview); agrPincelPreview = null; }
  if (agrPincelPuntos.length >= 2) {
    agrPincelPreview = L.polygon(agrPincelPuntos, {
      color: "#ffcc00", weight: 2, dashArray: "6,6", fillColor: "#ffcc00", fillOpacity: 0.15,
    }).addTo(agrMap);
  }
  const span = document.getElementById("agr-pincel-n");
  if (span) span.textContent = agrPincelPuntos.length;
  const controles = document.getElementById("agr-pincel-controles");
  if (controles) controles.hidden = agrPincelPuntos.length < 3;
}

function agrPincelCancelar() {
  agrPincelPuntos = [];
  agrPincelMarkers.forEach((m) => agrMap && agrMap.removeLayer(m));
  agrPincelMarkers = [];
  if (agrPincelPreview) { agrMap && agrMap.removeLayer(agrPincelPreview); agrPincelPreview = null; }
  const controles = document.getElementById("agr-pincel-controles");
  if (controles) controles.hidden = true;
  const span = document.getElementById("agr-pincel-n");
  if (span) span.textContent = "0";
}

async function agrPincelTerminar() {
  if (agrPincelPuntos.length < 3 || !agrFiltroAgregador) return;
  const tienda = agrTiendaMasCercana(agrPincelPuntos[0][0], agrPincelPuntos[0][1]) || agrTiendaActual;
  if (!tienda || tienda === AGR_TODAS) {
    mostrarAviso("No se pudo determinar a qué tienda pertenece esta zona. Selecciona una sola tienda en los chips de arriba y vuelve a intentarlo.");
    return;
  }
  try {
    const res = await agrFetchConTimeout(`${AGR_API}/rellenos`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tienda, agregador: agrFiltroAgregador, puntos: agrPincelPuntos }),
      credentials: "include",
    });
    if (!res.ok) throw new Error("No se pudo guardar el relleno");
    agrPincelCancelar();
    agrActualizarPoligonoLimite();
  } catch (e) {
    mostrarAviso("No se pudo guardar el relleno. Inténtalo de nuevo.");
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

  L.marker([tienda.lat, tienda.lng], { icon: agrIconoTienda(tienda.tienda) }).addTo(agrMap).bindPopup(`<b>${escapeHTML(tienda.nombre)}</b>`);

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
  direcciones.forEach((d) => { (agrDireccionesPorTienda[d._tiendaVisual || d.tienda] ||= []).push(d); });

  const lat0 = tiendas.reduce((s, t) => s + t.lat, 0) / tiendas.length;
  const lng0 = tiendas.reduce((s, t) => s + t.lng, 0) / tiendas.length;
  const esMapaNuevo = agrInitMap(lat0, lng0);

  // El refresco automático (cada 30s) vuelve a llamar a esto sobre el MISMO
  // mapa persistente -- sin limpiar antes, cada vuelta añadía otro icono de
  // tienda encima de los anteriores (no se notaba mientras el mapa entero se
  // destruía y recreaba cada vez, ver agrInitMap).
  agrTiendaMarkers.forEach((m) => agrMap.removeLayer(m));
  agrTiendaMarkers = tiendas.map((t) =>
    L.marker([t.lat, t.lng], { icon: agrIconoTienda(t.tienda) }).addTo(agrMap).bindPopup(`<b>${escapeHTML(t.nombre)}</b>`)
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
    tiendas.map((t) => `<button type="button" class="agr-tienda-chip" data-tienda="${escapeHTML(t.tienda)}">${escapeHTML(t.nombre)}</button>`)
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

  // Siempre se pide el dato de las 6 tiendas y se filtra en el cliente a las
  // chips activas -- así "Princesa y Caleido" o "todas menos una" es solo
  // cuestión de qué chips están marcadas, sin pedirle al backend un
  // endpoint nuevo por cada combinación posible (pedido explícito del
  // usuario 09/08: poder elegir qué tiendas ver en el mapa, no solo "una" o
  // "todas").
  // Con filtro de fecha activo (ver agrAplicarFiltroFecha), el mapa deja de
  // mostrar el estado ACTUAL de cada punto y pasa a mostrar cómo estaba ese
  // día concreto (el último chequeo real de cada uno hasta esa hora) --
  // pedido explícito del usuario 28/08: "lo que queremos ver por fechas
  // realmente es una fecha vs otra, cómo estaba el mapa con los dots".
  const urlMapa = agrFiltroFechaActivo
    ? `${AGR_API}/mapa-datos-todas?hasta=${encodeURIComponent(agrFiltroFechaActivo.hasta)}`
    : `${AGR_API}/mapa-datos-todas`;
  const res = await fetch(urlMapa, { credentials: "include" });
  const data = await res.json();

  // Un punto guardado con tienda=X en la BD puede en realidad estar pegado a
  // OTRA sucursal (grids solapados en zonas densas, ej. Princesa/Caleido o
  // La Gavia/Plenilunio) -- para agrupar/filtrar en el mapa se usa la tienda
  // REALMENTE más cercana (entre las 6, no solo las seleccionadas), no el
  // campo `tienda` de la fila. No se toca `d.tienda` en sí (lo usan las
  // llamadas al backend -- borrar, mover, chequeo manual -- que deben seguir
  // apuntando a la fila real de la BD), solo esta agrupación visual.
  const centrosTodos = {};
  (data.tiendas || []).forEach((t) => { centrosTodos[t.tienda] = t; });
  agrCentrosTodos = centrosTodos; // ver agrEsTiendaMasCercana -- siempre las 6, no solo las chips activas
  (data.direcciones || []).forEach((d) => {
    d._tiendaVisual = d.tienda;
    if (d.lat == null || d.lng == null) return;
    let mejor = d.tienda, mejorDist = Infinity;
    Object.entries(centrosTodos).forEach(([slug, c]) => {
      const dist = agrDistanciaKm(c.lat, c.lng, d.lat, d.lng);
      if (dist < mejorDist) { mejorDist = dist; mejor = slug; }
    });
    d._tiendaVisual = mejor;
  });

  const seleccion = agrMapaTiendasSeleccionadas;
  const filtrado = {
    tiendas: (data.tiendas || []).filter((t) => seleccion.has(t.tienda)),
    direcciones: (data.direcciones || []).filter((d) => seleccion.has(d._tiendaVisual)),
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

let agrFiltroFechaActivo = null; // null = últimas 24h (de siempre) -- si no, {desde, hasta} ISO UTC

// Los selects de fecha/hora del filtro del mapa solo ofrecen días y horas en
// los que de verdad hubo scraping -- pedido explícito del usuario 28/08:
// "me va a dejar seleccionar solo las fechas que tengamos información
// disponible... al seleccionar la fecha me dejará escoger entre las horas
// que tengamos disponible la info de ese día". Un <select> con solo las
// opciones válidas logra el mismo efecto que "desactivar" el resto del
// calendario, sin necesitar un date-picker a medida (el <input type="date">
// nativo no permite deshabilitar días sueltos).
async function agrCargarFechasFiltroFecha() {
  const select = document.getElementById("agr-filtro-fecha");
  if (!select) return;
  try {
    const res = await fetch(`${AGR_API}/mapa-datos-fechas`, { credentials: "include" });
    const data = await res.json();
    const fechas = data.fechas || [];
    select.innerHTML = fechas.length
      ? `<option value="">— elige un día con datos —</option>` + fechas.map((f) => `<option value="${f}">${agrFormatearFechaCorta(f)}</option>`).join("")
      : `<option value="">Sin datos todavía</option>`;
  } catch {
    select.innerHTML = `<option value="">No se pudo cargar</option>`;
  }
}

function agrFormatearFechaCorta(fechaISO) {
  const [y, m, d] = fechaISO.split("-");
  return `${d}/${m}/${y}`;
}

async function agrCargarHorasFiltroFecha() {
  const fecha = document.getElementById("agr-filtro-fecha").value;
  const selectHora = document.getElementById("agr-filtro-hora-hasta");
  if (!fecha) {
    selectHora.innerHTML = `<option value="">—</option>`;
    selectHora.disabled = true;
    return;
  }
  selectHora.disabled = true;
  selectHora.innerHTML = `<option value="">Cargando…</option>`;
  try {
    const res = await fetch(`${AGR_API}/mapa-datos-horas?fecha=${encodeURIComponent(fecha)}`, { credentials: "include" });
    const data = await res.json();
    const horas = data.horas || [];
    if (horas.length === 0) {
      selectHora.innerHTML = `<option value="">Sin horas con datos</option>`;
      return;
    }
    // Última hora del día primero -- es la vista más probable ("¿cómo quedó
    // el día?"), aunque siguen disponibles todas las demás horas del select.
    selectHora.innerHTML = [...horas].reverse().map((h) => `<option value="${h}">${h}</option>`).join("");
    selectHora.disabled = false;
  } catch {
    selectHora.innerHTML = `<option value="">No se pudo cargar</option>`;
  }
}

function agrAplicarFiltroFecha() {
  const fecha = document.getElementById("agr-filtro-fecha").value;
  if (!fecha) { mostrarAviso("Elige un día primero."); return; }
  const horaHasta = document.getElementById("agr-filtro-hora-hasta").value;
  if (!horaHasta) { mostrarAviso("Elige una hora con datos primero."); return; }
  // "Desde" ya no es un campo aparte (se quitó al mover este bloque al mapa,
  // pedido explícito del usuario 28/08) -- para el mapa lo que importa es un
  // único corte ("cómo estaba TODO hasta este momento"), no un rango; para
  // la tabla de abajo, que sigue siendo un rango, se asume el día entero
  // hasta esa hora.
  // new Date("YYYY-MM-DDTHH:MM") se interpreta en la zona horaria del navegador (Madrid,
  // ya que es donde trabaja el equipo) -- toISOString() lo pasa a UTC para el backend,
  // que guarda todos los timestamps en UTC.
  const desde = new Date(`${fecha}T00:00:00`).toISOString();
  const hasta = new Date(`${fecha}T${horaHasta}:59`).toISOString();
  agrFiltroFechaActivo = { desde, hasta };
  document.getElementById("agr-filtro-fecha-activo").textContent = `Mostrando cómo estaba el ${agrFormatearFechaCorta(fecha)} hasta las ${horaHasta}`;
  agrActualizarTituloResumen();
  agrCargarTabla();
  agrCargarResumen();
  agrCargarMapa();
}

function agrQuitarFiltroFecha() {
  agrFiltroFechaActivo = null;
  document.getElementById("agr-filtro-fecha-activo").textContent = "";
  agrActualizarTituloResumen();
  agrCargarTabla();
  agrCargarResumen();
  agrCargarMapa();
}

function agrActualizarTituloResumen() {
  const titulo = document.getElementById("agr-resumen-titulo-texto");
  if (titulo) titulo.textContent = agrFiltroFechaActivo ? "Resumen (periodo filtrado)" : "Resumen (24h)";
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
  const url = agrFiltroFechaActivo
    ? `${AGR_API}/ultimos?tienda=${agrTiendaActual}&desde=${encodeURIComponent(agrFiltroFechaActivo.desde)}&hasta=${encodeURIComponent(agrFiltroFechaActivo.hasta)}`
    : `${AGR_API}/ultimos?tienda=${agrTiendaActual}&horas=24`;
  const res = await fetch(url, { credentials: "include" });
  let chequeos = await res.json();
  const totalSinLimpiar = chequeos.length;
  // El filtro de "limpiado" (ocultar lo ya visto) es para el uso normal de vigilar
  // las últimas 24h -- no tiene sentido al bucear en una fecha concreta del pasado.
  if (agrTablaLimpiadaHasta && !agrFiltroFechaActivo) {
    chequeos = chequeos.filter((c) => c.timestamp > agrTablaLimpiadaHasta);
  }
  const incorrectos = chequeos.filter((c) => c.error_texto);
  const correctos = chequeos.filter((c) => !c.error_texto);
  const notaLimpiados = totalSinLimpiar > chequeos.length ? ` -- ${totalSinLimpiar - chequeos.length} ocultos` : "";

  contador.textContent = `(${incorrectos.length} con fallo técnico / ${correctos.length} correctos${notaLimpiados})`;

  if (incorrectos.length === 0) {
    const periodo = agrFiltroFechaActivo ? "en ese periodo" : "en 24h";
    const motivo = totalSinLimpiar > 0 && chequeos.length === 0
      ? "Sin chequeos nuevos desde que limpiaste."
      : `Sin fallos técnicos ${periodo}. Todos los chequeos se completaron correctamente.`;
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
    const periodo = agrFiltroFechaActivo ? "en ese periodo" : "en 24h";
    const motivo = Object.keys(reporte.agregadores).length === 0 ? `Sin chequeos ${periodo}.` : "Todas las tarjetas están ocultas -- usa el icono 🗑 para volver a mostrarlas.";
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
  // El filtro de fecha/hora de "Últimos chequeos" también manda aquí -- el usuario
  // quiere buscar por un scrap concreto y ver de un vistazo cuántos fallos hubo,
  // disponible/no disponible, no solo la lista cruda de filas (pedido explícito
  // 26/08). Mismo periodo para las dos secciones, un único filtro.
  if (agrFiltroFechaActivo) {
    params.set("desde", agrFiltroFechaActivo.desde);
    params.set("hasta", agrFiltroFechaActivo.hasta);
  }
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
      return `<li><span class="hora">${hora}</span><span class="${claseTipo}">${escapeHTML(etiquetaTipo)}</span>${escapeHTML(a.mensaje)}</li>`;
    })
    .join("");
}

async function agrEliminarTransicion(chequeoId, boton) {
  if (!(await pedirConfirmacion("¿Borrar este registro? Es para casos confirmados como error (p.ej. dirección o captura equivocada) -- no se puede deshacer."))) {
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
    mostrarAviso("No se pudo borrar. Inténtalo de nuevo.");
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

function agrDibujarPoligonoLimite(limites, centro, color, direccionesTienda, uniones, rellenos) {
  // Polígono "araña/radar": un vértice por ángulo, a la distancia real del
  // límite de cobertura en esa dirección concreta -- a diferencia del
  // envolvente convexo, esto SÍ puede representar huecos de cobertura (ej.
  // cerrado al norte, abierto al sur), porque conecta los vértices en orden
  // angular en vez de "abombar hacia fuera". Además marca cada vértice con
  // un punto clicable (ángulo + límite exacto de esa dirección).
  if (!limites || limites.length === 0) return null;
  const agregador = limites[0].agregador;

  // Todos los dots de esta tienda contribuyen al polígono -- se restauró el
  // algoritmo del 10/08 09:00 que no filtraba por tienda más cercana
  // (pedido explícito del usuario 10/08 tarde).
  const direccionesPropias = (direccionesTienda || []);

  const base = [...limites]
    // "sin datos (todo falló)" no aporta ni siquiera una cota aproximada --
    // se salta ese ángulo del polígono en vez de inventar un radio (ver
    // agrRadioDeLimite). Deja un hueco angular más ancho, pero eso es
    // honesto: no sabemos qué pasa ahí, en vez de fingir que la cobertura
    // colapsa a cero justo en ese punto.
    .filter((l) => agrRadioDeLimite(l) != null)
    // Se restauró el algoritmo del 10/08 09:00: todos los vértices base
    // cuentan, incluidos los sin lat/lng guardado (se reconstruyen
    // geométricamente desde el ángulo nominal) -- pedido explícito del
    // usuario 10/08 tarde.
    .map((l) => {
      const radio = Math.max(agrRadioDeLimite(l), 0.05);
      const latlngReal = l.lat != null && l.lng != null ? [l.lat, l.lng] : null;
      const latlng = latlngReal || agrMoverPunto(centro.lat, centro.lng, l.angulo_grados, radio);
      const bearingReal = agrAnguloDesde(centro, latlng);
      return {
        angulo: l.angulo_grados,
        radio,
        limite: l,
        latlngReal,
        latlng,
        bearingReal,
        local: agrProyeccionLocal(centro, latlng),
        extendidoPor: null,
        confirmado: l.limite_km != null,
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
  // Tolerancia restaurada a 3° (algoritmo de las 9:00 del 10/08) --
  // pedido explícito del usuario 10/08 tarde: volver al mapa de las 9am
  // como principal.
  const TOLERANCIA_ANGULO_GRADOS = 3;
  // direccionesPropias ya se calculó arriba (se reutiliza también para
  // contrastar los vértices base contra dots reales).
  const puntosLejanos = [];
  direccionesPropias
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
          vecino.confirmado = true; // ya no es una estimación, es un chequeo real
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
        puntosLejanos.push({ angulo: d.angulo_grados, radio: d.distancia_km, dir: d, latlng, bearingReal: bearing, confirmado: true });
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
  direccionesPropias
    .filter((d) => (d.detalle || {})[agregador]?.estado === "no_disponible" && d.lat != null && d.lng != null && d.distancia_km != null)
    .forEach((d) => {
      if (base.length < 2) return; // no hay borde todavía con el que comparar
      const latlng = [d.lat, d.lng];
      const bearing = agrAnguloDesde(centro, latlng);
      const vecino = base.find((b) => {
        const diff = Math.abs(b.bearingReal - bearing);
        return Math.min(diff, 360 - diff) < TOLERANCIA_ANGULO_GRADOS;
      });
      if (vecino) {
        // Espejo del vecino-extiende de puntosLejanos, pero encogiendo. Antes
        // esto simplemente "respetaba" el vértice medido y descartaba el
        // punto -- pero los puntos origen=limite (los que probó de verdad
        // buscar_limite_cobertura.py) caen SIEMPRE dentro de esta tolerancia
        // del vértice que ellos mismos ayudaron a medir, así que un
        // no_disponible real en uno de esos puntos se ignoraba en vez de
        // corregir el vértice -- justo el caso más común y más grave
        // (confirmado en vivo 10/08 con turf.booleanPointInPolygon: 31
        // puntos "no_disponible DENTRO", la mayoría origen=limite).
        if (d.distancia_km < vecino.radio) {
          vecino.radio = d.distancia_km;
          vecino.latlngReal = latlng;
          vecino.latlng = latlng;
          vecino.bearingReal = bearing;
          vecino.local = agrProyeccionLocal(centro, latlng);
          vecino.extendidoPor = d;
        }
        vecino.confirmado = true;
        vecino.esNoDisponible = true; // dato real de "no reparte" -- nunca lo sube el relleno agresivo
        return;
      }
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
        puntosCercanos.push({ angulo: d.angulo_grados, radio: d.distancia_km, dir: d, latlng, bearingReal: bearing, confirmado: true, esNoDisponible: true });
      }
    });

  const ordenados = [...base, ...puntosLejanos, ...puntosCercanos].sort((a, b) => a.bearingReal - b.bearingReal);

  // Puentes manuales (ver agregadores_uniones en el backend): el usuario vio
  // a ojo dos direcciones disponibles con un hueco/pico raro entre medias y
  // decidió que ahí también hay cobertura -- se conectan en línea recta,
  // quitando cualquier vértice intermedio en ese arco corto (nunca uno con
  // esNoDisponible real: eso sí es evidencia directa de que no reparte, un
  // puente manual no la puede pisar). Pedido explícito del usuario 10/08:
  // "haré clic sobre un punto y sobre un segundo punto y eso va a unir el
  // borde límite".
  (uniones || []).forEach((u) => {
    const latlngA = [u.lat_a, u.lng_a], latlngB = [u.lat_b, u.lng_b];
    const bearingA = agrAnguloDesde(centro, latlngA);
    const bearingB = agrAnguloDesde(centro, latlngB);
    let diff = bearingB - bearingA;
    if (diff > 180) diff -= 360;
    if (diff < -180) diff += 360;
    const desde = diff >= 0 ? bearingA : bearingB;
    const hasta = diff >= 0 ? bearingB : bearingA;
    for (let i = ordenados.length - 1; i >= 0; i--) {
      const v = ordenados[i];
      if (v.esNoDisponible) continue;
      const ang = v.bearingReal;
      const enArco = desde <= hasta ? (ang > desde && ang < hasta) : (ang > desde || ang < hasta);
      if (enArco) ordenados.splice(i, 1);
    }
    [[latlngA, bearingA, u.direccion_id_a], [latlngB, bearingB, u.direccion_id_b]].forEach(([latlng, bearing, direccionId]) => {
      if (ordenados.some((v) => Math.abs(v.latlng[0] - latlng[0]) < 1e-7 && Math.abs(v.latlng[1] - latlng[1]) < 1e-7)) return;
      ordenados.push({
        radio: agrDistanciaKm(centro.lat, centro.lng, latlng[0], latlng[1]),
        latlng, latlngReal: latlng, bearingReal: bearing,
        local: agrProyeccionLocal(centro, latlng),
        confirmado: true, union: true,
        // El vértice del renderizado (rama "else" más abajo) siempre espera
        // un punto.dir con .detalle/.direccion_text -- un puente puede venir
        // de un vértice del borde sin dirección real detrás, así que cuando
        // no hay direccion_id se rellena un dir mínimo en vez de null.
        dir: (direccionId != null && (direccionesTienda || []).find((d) => d.id === direccionId)) || { id: direccionId, detalle: {}, direccion_text: null },
      });
    });
  });
  ordenados.sort((a, b) => a.bearingReal - b.bearingReal);

  if (ordenados.length === 0) return null;

  // Relleno agresivo: un tramo de vértices SIN confirmar (solo una cota
  // aproximada, ni búsqueda binaria real ni un chequeo propio) que queda
  // entre dos vértices confirmados disponibles, sin ningún no_disponible
  // real de por medio, se sube hasta el menor de esos dos extremos -- si
  // reparte en un punto de la calle y en otro más lejos, es razonable
  // asumir que también reparte en medio, en vez de dejar el hueco sin
  // datos tirando el borde hacia el centro y dibujando "picos" finos que no
  // reflejan que en realidad toda esa calle está cubierta (pedido explícito
  // del usuario 10/08, modo agresivo elegido a propósito: mejor un mapa
  // "lleno" con inferencia razonable que uno lleno de agujeros sin probar).
  // Nunca sube un tramo que toque un no_disponible real -- ese sí es tope.
  // v1 de esto solo trataba como "rellenable" un vértice sin limite_km real
  // (solo estimación de la nota) -- pero en la práctica casi todos los
  // vértices de agregadores_limites SÍ tienen limite_km (venían de una
  // búsqueda binaria real), así que casi nada calificaba como "sin
  // confirmar" y el relleno no se veía (confirmado en vivo 10/08: "vertices
  // totales: 69 | limites guardados: 31" -- se insertaron 38 vértices
  // nuevos por puntosLejanos/Cercanos y aun así el relleno seguía sin
  // disparar). En modo agresivo lo que de verdad importa no es si ESE
  // vértice concreto tiene un número guardado, sino si hay una prueba
  // DIRECTA de que ahí no reparte (un chequeo real no_disponible,
  // puntosCercanos) -- eso es el único tope de verdad. Cualquier otro
  // vértice (con limite_km real pero corto, con solo una estimación, o sin
  // dato) se puede subir si queda flanqueado por vértices sin ese tope.
  // DESACTIVADO 10/08: subir todo un tramo hasta su radio máximo asumía que
  // ese máximo era un dato fiable -- con chequeos "disponible" contaminados
  // por sucursales de Krispy Kreme reales pero no rastreadas, ese máximo
  // podía venir de un punto que no es cobertura real de esta tienda, y el
  // relleno lo esparcía igual por todo el tramo (confirmado en vivo con
  // Caleido: el polígono entero se igualaba a un círculo perfecto). Sin una
  // forma fiable de distinguir cobertura real de contaminación lejana, cada
  // vértice se queda con SU PROPIO dato (base + puntosLejanos/Cercanos), sin
  // suavizar contra los vecinos. No hay tope duro de distancia -- si un
  // punto es de verdad el más cercano de las 6 tiendas rastreadas (ver
  // agrEsTiendaMasCercana), su distancia real cuenta tal cual, aunque sean
  // 9km: "si de verdad reparte hasta ahí, hay que tomarlo en cuenta" (pedido
  // explícito del usuario 10/08).

  const vertices = ordenados.map((p) => ({ latlng: p.latlng, punto: p }));
  // Con la "cobertura combinada" activa, el polígono y los vértices de CADA
  // tienda por separado son puro ruido -- varias estrellas solapadas se ven
  // como una maraña de líneas cruzadas y puntos por dentro (pedido explícito
  // del usuario 09/08: "que no veamos nada dentro", comparando con lo limpio
  // que se ve una tienda sola). En ese modo solo interesa el contorno de la
  // unión (agrDibujarUnionCobertura), así que aquí nos saltamos el dibujado
  // individual pero seguimos calculando el anillo más abajo para la unión.
  const ocultarDetalle = agrMostrarUnionActivo();

  // Pincel (ver agregadores_rellenos): el usuario pintó a mano una o varias
  // zonas DENTRO del polígono que "unir puntos" no puede tapar (un puente
  // solo conecta dos vértices del borde en línea recta -- un hueco en medio
  // de la figura no está en el borde). Se fusiona cada zona pintada con el
  // contorno calculado vía turf.union, así el hueco desaparece del dibujo
  // sin tocar ningún vértice/dato real (pedido explícito del usuario 10/08:
  // "hay unas zonas que debemos poder rellenar dentro del mismo polígono").
  let coordenadasPoligono = vertices.map((v) => v.latlng);
  if ((rellenos || []).length > 0 && coordenadasPoligono.length >= 3) {
    try {
      let base = turf.polygon([[
        ...coordenadasPoligono.map(([lat, lng]) => [lng, lat]),
        [coordenadasPoligono[0][1], coordenadasPoligono[0][0]],
      ]]);
      rellenos.forEach((r) => {
        if (!r.puntos || r.puntos.length < 3) return;
        try {
          const anilloParche = r.puntos.map(([lat, lng]) => [lng, lat]);
          anilloParche.push(anilloParche[0]);
          const combinado = turf.union(base, turf.polygon([anilloParche]));
          if (combinado) base = combinado;
        } catch (e) {
          // Geometría del parche inválida (auto-intersección, etc.) -- se
          // ignora ese relleno concreto en vez de romper todo el polígono.
        }
      });
      const geom = base.geometry.type === "Polygon" ? base.geometry.coordinates[0] : base.geometry.coordinates[0][0];
      coordenadasPoligono = geom.slice(0, -1).map(([lng, lat]) => [lat, lng]);
    } catch (e) {
      // Si turf falla por completo, se dibuja el polígono sin rellenos.
    }
  }

  // Con menos de 3 vértices no hay figura que cerrar (un polígono real
  // necesita al menos un triángulo) -- pero los puntos ya comprobados SÍ se
  // muestran igual, para no dejar la tienda "en blanco" mientras la
  // búsqueda de límite todavía va por su segundo o tercer ángulo (visto en
  // vivo 09/08: con 2 de 8 ángulos guardados no aparecía nada en el mapa).
  let poligono = null;
  if (coordenadasPoligono.length >= 3 && !ocultarDetalle) {
    // weight bajado de 4 a 2: con cientos de vértices y picos finos, un
    // trazo grueso hacía el borde ilegible ("picos gordos", pedido
    // explícito del usuario 10/08).
    poligono = L.polygon(coordenadasPoligono, {
      color, weight: 2, opacity: 1, fillColor: color, fillOpacity: 0.28,
    }).addTo(agrMap);
    agrPoligonoLayers.push(poligono);
  }

  (ocultarDetalle ? [] : vertices).forEach(({ latlng, punto }) => {
    if (punto.limite) {
      const limite = punto.limite;
      const etiqueta = punto.rellenoAgresivo
        ? `~${punto.radio.toFixed(2)}km (inferido -- sin comprobar directamente, relleno entre dos puntos disponibles cercanos)`
        : punto.extendidoPor
        ? `${punto.radio.toFixed(2)}km (extendido -- un punto ya conocido llega más lejos que el ${limite.limite_km != null ? limite.limite_km.toFixed(2) + "km" : "~" + agrRadioDeLimite(limite).toFixed(2) + "km"} de la búsqueda de límite en esta misma dirección)`
        : limite.limite_km != null
        ? `${limite.limite_km.toFixed(2)}km`
        : `~${punto.radio.toFixed(2)}km (${limite.nota || "sin dato exacto"})`;
      const direccionMostrar = punto.extendidoPor?.direccion_text || limite.direccion_text;
      // Los vértices ya calculados tapan al dot que hay justo debajo en el
      // mapa, así que la herramienta de unir también tiene que poder
      // elegirlos directamente aquí, no solo desde el popup del dot (pedido
      // explícito del usuario 10/08: "los dots están justo debajo del
      // vértice, no puedo acceder a ellos").
      const unirVerticeHtml = agrModoUnir && agrFiltroAgregador
        ? `<button type="button" class="btn btn-ghost" style="margin-top:6px;font-size:12px;padding:3px 8px;" onclick="agrUnionElegirPunto(${latlng[0]}, ${latlng[1]}, '${centro.tienda}', 'vértice a ${punto.radio.toFixed(2)}km')">🔗 ${agrUnionPendiente ? "Unir aquí" : "Unir con otro punto"}</button><br>`
        : "";
      // Los rellenados agresivamente se marcan con un borde punteado en vez
      // de sólido -- de un vistazo, cuál es dato real y cuál es inferencia
      // (pedido explícito del usuario 10/08: poder "estilizar" el borde).
      const marker = L.marker(latlng, {
        icon: agrIconoVerticePoligono("#1a1a1a", color, punto.rellenoAgresivo ? 8 : 12, !!punto.rellenoAgresivo, punto.rellenoAgresivo ? 0.55 : 1),
        draggable: true,
      })
        .bindPopup(
          `<b>${AGR_NOMBRE_AGREGADOR[limite.agregador] || limite.agregador}</b><br>Ángulo: ${limite.angulo_grados}°<br>Límite: ${etiqueta}<br>Dirección: <span class="agr-poligono-dir">${direccionMostrar || "cargando..."}</span><br>` +
            `<i style="color:var(--text-muted);font-size:11px;">Arrastra para ajustar el borde</i><br>` +
            unirVerticeHtml +
            `<button type="button" class="btn btn-ghost" style="margin-top:6px;font-size:12px;padding:3px 8px;" onclick="agrEliminarLimite('${limite.tienda.replace(/'/g, "\\'")}', '${limite.agregador.replace(/'/g, "\\'")}', ${limite.angulo_grados})">🗑️ Quitar este vértice del borde</button>`
        )
        .addTo(agrMap);
      marker.on("dragend", (e) => {
        const { lat, lng } = e.target.getLatLng();
        agrMoverVerticeLimite(limite.tienda, limite.agregador, limite.angulo_grados, lat, lng);
      });
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
      // hace falta reverse geocoding). Este SÍ es una dirección real
      // (punto.dir.id), así que arrastrarlo reubica el punto de verdad, con
      // el mismo endpoint que usa el drag normal de un dot.
      const esCercano = (punto.dir.detalle || {})[agregador]?.estado === "no_disponible";
      const unirVerticeHtml2 = agrModoUnir && agrFiltroAgregador
        ? `<br><button type="button" class="btn btn-ghost" style="margin-top:6px;font-size:12px;padding:3px 8px;" onclick="agrUnionElegirPunto(${latlng[0]}, ${latlng[1]}, '${centro.tienda}', '${(punto.dir.direccion_text || "punto").replace(/'/g, "\\'")}', ${punto.dir.id})">🔗 ${agrUnionPendiente ? "Unir aquí" : "Unir con otro punto"}</button>`
        : "";
      const marker = L.marker(latlng, {
        icon: agrIconoVerticePoligono("#ffffff", esCercano ? "#d03b3b" : color, punto.rellenoAgresivo ? 8 : 12, !!punto.rellenoAgresivo, punto.rellenoAgresivo ? 0.55 : 1),
        draggable: true,
      })
        .bindPopup(
          `<b>${AGR_NOMBRE_AGREGADOR[agregador] || agregador}</b><br>` +
            (esCercano
              ? `Punto ya NO disponible, más cerca de lo muestreado por ángulo`
              : `Punto ya disponible, más lejos de lo muestreado por ángulo`) +
            `<br>Distancia: ${punto.radio.toFixed(2)}km<br>Dirección: ${punto.dir.direccion_text || "?"}<br>` +
            `<i style="color:var(--text-muted);font-size:11px;">Arrastra para reubicar este punto</i>` +
            unirVerticeHtml2
        )
        .addTo(agrMap);
      marker.on("dragend", (e) => {
        const { lat, lng } = e.target.getLatLng();
        agrMoverVerticeDireccion(punto.dir, lat, lng);
      });
      agrPoligonoLayers.push(marker);
    }
  });

  // anillo GeoJSON [lng,lat] (Turf/GeoJSON van al revés que Leaflet) para
  // poder calcular la unión real de varias tiendas con turf.union -- solo
  // tiene sentido si hay polígono de verdad (3+ vértices) y cerrado (el
  // primer punto repetido al final).
  const anillo = coordenadasPoligono.length >= 3
    ? [...coordenadasPoligono.map(([lat, lng]) => [lng, lat]), [coordenadasPoligono[0][1], coordenadasPoligono[0][0]]]
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
  const [porTienda, unionesPorTienda, rellenosPorTienda] = await Promise.all([
    Promise.all(
      tiendas.map((tienda) =>
        fetch(`${AGR_API}/limites/${tienda}`, { credentials: "include" }).then((r) => (r.ok ? r.json() : []))
      )
    ),
    Promise.all(
      tiendas.map((tienda) =>
        fetch(`${AGR_API}/uniones/${tienda}`, { credentials: "include" }).then((r) => (r.ok ? r.json() : []))
      )
    ),
    Promise.all(
      tiendas.map((tienda) =>
        fetch(`${AGR_API}/rellenos/${tienda}`, { credentials: "include" }).then((r) => (r.ok ? r.json() : []))
      )
    ),
  ]);

  let totalVertices = 0;
  const anillosPorAgregador = {}; // nombre -> [anillo, anillo, ...] (uno por tienda con polígono cerrado) -- para la unión
  const agregarAnillo = (resultado) => {
    // agrDibujarPoligonoLimite() devuelve null cuando esa tienda todavía no
    // tiene ningún límite dibujado para ese agregador concreto (algo normal
    // en una tienda recién dada de alta, o si solo se ha dibujado el radar
    // de un agregador y no de los demás) -- sin este guard, cargar el mapa
    // entero fallaba en cuanto CUALQUIER combinación tienda/agregador no
    // tuviera datos todavía.
    if (!resultado) return;
    totalVertices += resultado.n;
    if (resultado.anillo) {
      (anillosPorAgregador[resultado.agregador] ||= []).push(resultado.anillo);
    }
  };
  tiendas.forEach((tienda, i) => {
    const centro = agrCentrosPorTienda[tienda] || agrTiendaCentro;
    if (!centro) return;
    const limites = porTienda[i];
    const uniones = unionesPorTienda[i];
    const rellenos = rellenosPorTienda[i];
    const direccionesTienda = agrDireccionesPorTienda[tienda];
    if (agrFiltroAgregador) {
      const limitesAgregador = limites.filter((l) => l.agregador === agrFiltroAgregador);
      const unionesAgregador = uniones.filter((u) => u.agregador === agrFiltroAgregador);
      const rellenosAgregador = rellenos.filter((r) => r.agregador === agrFiltroAgregador);
      agregarAnillo(agrDibujarPoligonoLimite(limitesAgregador, centro, AGR_COLOR_MARCA[agrFiltroAgregador] || "#0ca30c", direccionesTienda, unionesAgregador, rellenosAgregador));
    } else {
      Object.keys(AGR_NOMBRE_AGREGADOR).forEach((nombre) => {
        const limitesAgregador = limites.filter((l) => l.agregador === nombre);
        const unionesAgregador = uniones.filter((u) => u.agregador === nombre);
        const rellenosAgregador = rellenos.filter((r) => r.agregador === nombre);
        agregarAnillo(agrDibujarPoligonoLimite(limitesAgregador, centro, AGR_COLOR_MARCA[nombre] || "#888", direccionesTienda, unionesAgregador, rellenosAgregador));
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

function agrTextoProgreso(estado) {
  // La pasada "en curso" con más avance manda -- si las dos (cercano y
  // completo) están en curso a la vez (no debería, pero por si acaso) se
  // muestra la que lleve más hechos, que es la más informativa.
  const enCurso = [estado.cercano, estado.completo].filter((m) => m.en_curso && m.progreso_hechos != null);
  if (enCurso.length === 0) return "";
  const modo = enCurso.sort((a, b) => (b.progreso_hechos || 0) - (a.progreso_hechos || 0))[0];
  return modo.progreso_total ? ` (${modo.progreso_hechos}/${modo.progreso_total})` : ` (${modo.progreso_hechos})`;
}

async function agrCargarEstado() {
  const pill = document.getElementById("agr-estado");
  try {
    const res = await fetch(`${AGR_API}/estado`, { credentials: "include" });
    const estado = await res.json();
    const progreso = agrTextoProgreso(estado);
    if (!estado.es_horario_apertura) {
      pill.textContent = "⏸ Fuera de horario";
      pill.className = "agr-estado-pill neutro";
      return;
    }
    pill.textContent = "● Scraper OK" + progreso;
    pill.className = "agr-estado-pill ok";
  } catch {
    pill.textContent = "? Estado desconocido";
    pill.className = "agr-estado-pill neutro";
  }
}

// Panel "Dashboard del scraper" -- mismos datos que el mini dashboard local
// (scraper_agregadores/status_server.py), pero servido desde el propio backend con
// sesión de staff (rol admin) en vez de tener que levantar un servidor aparte en el
// portátil del scraper. Pedido explícito del usuario 26/08. Reutiliza AGR_API pero
// con las rutas /panel/... (auth de sesión), no /admin/... (esas piden la X-API-Key
// del scraper, que no debe vivir en el frontend).
const AGR_CATEGORIAS_ESTADO = ["disponible", "no_disponible", "error", "sin_datos"];
const AGR_CATEGORIA_LABEL = { disponible: "Disponibles", no_disponible: "No disponibles", error: "Error", sin_datos: "Sin datos" };

let agrDashboardScraperIntervalo = null;

function agrAbrirDashboardScraper() {
  document.getElementById("agr-scraper-overlay").classList.add("visible");
  agrCargarDashboardScraper();
  // Refresco cada 15s mientras el panel esté abierto -- para ver avanzar en vivo
  // "hechos/faltan" de una vuelta completa (revalidar_completo.py) sin tener que
  // cerrar y volver a abrir. Se para al cerrar (agrCerrarDashboardScraper) para no
  // seguir pidiendo datos de fondo sin necesidad.
  if (agrDashboardScraperIntervalo) clearInterval(agrDashboardScraperIntervalo);
  agrDashboardScraperIntervalo = setInterval(agrCargarDashboardScraper, 15000);
}

function agrCerrarDashboardScraper() {
  document.getElementById("agr-scraper-overlay").classList.remove("visible");
  if (agrDashboardScraperIntervalo) {
    clearInterval(agrDashboardScraperIntervalo);
    agrDashboardScraperIntervalo = null;
  }
}

// Disponible/no disponible/error de ESTA ronda -- arranca en 0 con cada vuelta
// nueva (pedido explícito del usuario 27/08), distinto del desglose bruto
// histórico que se ve en "Por tienda" cuando no hay ronda. Sin "sin datos": estar
// contado aquí YA significa que se comprobó en esta ronda.
const AGR_CATEGORIAS_RONDA = ["disponible", "no_disponible", "error"];

function agrDesgloseHtml(desglose, categorias = AGR_CATEGORIAS_RONDA) {
  return categorias.map((c) => `${AGR_CATEGORIA_LABEL[c]}: <b>${desglose?.[c] || 0}</b>`).join(" · ");
}

function agrRondaHtml(agregador, ronda) {
  const nombre = AGR_NOMBRE_AGREGADOR[agregador];
  if (!ronda) {
    return `<div class="agr-scraper-desglose" style="margin-bottom:6px;"><b>${nombre}</b>: nunca se ha lanzado una vuelta completa</div>`;
  }
  const pct = ronda.total_objetivo > 0 ? Math.round((ronda.hechos / ronda.total_objetivo) * 100) : 0;
  const inicio = new Date(ronda.iniciada_en).toLocaleTimeString("es-ES", { timeZone: "Europe/Madrid" });
  const desglose = agrDesgloseHtml(ronda.desglose);
  if (!ronda.en_curso) {
    const fin = new Date(ronda.finalizada_en).toLocaleTimeString("es-ES", { timeZone: "Europe/Madrid" });
    const duracionMin = Math.max(1, Math.round((new Date(ronda.finalizada_en) - new Date(ronda.iniciada_en)) / 60000));
    return `<div class="agr-scraper-desglose" style="margin-bottom:6px;">
      <b>${nombre}</b>: ✅ completado -- ${ronda.hechos}/${ronda.total_objetivo} (${pct}%) · de ${inicio} a ${fin} (${duracionMin} min)
      <div class="agr-scraper-desglose" style="margin-top:2px;">${desglose}</div>
    </div>`;
  }
  // Desglose por tienda (aquí y en "faltan") vive en la tabla "Por tienda" de abajo
  // -- no se repite aquí para no duplicar el mismo dato dos veces en el panel.
  return `<div style="margin-bottom:10px;">
    <b>${nombre}</b>: ${ronda.hechos}/${ronda.total_objetivo} hechos (${pct}%) · faltan ${ronda.faltan} · empezó a las ${inicio}
    <div class="agr-card-barra"><span style="width:${pct}%; background:${AGR_COLOR_MARCA[agregador]};"></span></div>
    <div class="agr-scraper-desglose" style="margin-top:4px;">${desglose}</div>
  </div>`;
}

// conteosBruto: histórico completo de esta tienda/agregador (de /panel/resumen-estados)
// -- SIEMPRE se usa para el total de "X/Y" (el tamaño real del grid no cambia con
// la ronda). hechoRonda (opcional): puntos ya cubiertos en la vuelta en curso, para
// el "X/" delante. desgloseRonda (opcional): si hay ronda para este agregador, el
// detalle de abajo (Disponible/No disponible/Error) es el de ESTA ronda (arranca en
// 0 cada vuelta nueva, pedido explícito del usuario 27/08) en vez del histórico.
function agrCeldaEstadoHtml(conteosBruto, hechoRonda, desgloseRonda) {
  const total = AGR_CATEGORIAS_ESTADO.reduce((s, c) => s + (conteosBruto?.[c] || 0), 0);
  const detalle = desgloseRonda
    ? agrDesgloseHtml(desgloseRonda)
    : agrDesgloseHtml(conteosBruto, AGR_CATEGORIAS_ESTADO);
  const cabecera = hechoRonda != null ? `<b>${hechoRonda}</b>/${total}` : `<b>${total}</b> total`;
  return `<td>${cabecera}<div class="agr-scraper-desglose">${detalle}</div></td>`;
}

async function agrCargarDashboardScraper() {
  const contenido = document.getElementById("agr-scraper-contenido");
  const actualizado = document.getElementById("agr-scraper-actualizado");
  try {
    const [resEstados, resRondas] = await Promise.all([
      fetch(`${AGR_API}/panel/resumen-estados`, { credentials: "include" }),
      fetch(`${AGR_API}/panel/rondas-actuales`, { credentials: "include" }),
    ]);
    if (!resEstados.ok || !resRondas.ok) throw new Error("fetch falló");
    const estados = await resEstados.json();
    const rondas = await resRondas.json();

    const agregadores = Object.keys(AGR_NOMBRE_AGREGADOR);
    const tiendas = Object.keys(estados).filter((t) => agrCentrosPorTienda[t]);
    const cabeceras = agregadores.map((a) => `<th>${AGR_NOMBRE_AGREGADOR[a]}</th>`).join("");

    const totales = {};
    const totalesHechoRonda = {};
    const totalesDesgloseRonda = {};
    agregadores.forEach((a) => {
      totales[a] = { disponible: 0, no_disponible: 0, error: 0, sin_datos: 0 };
      totalesHechoRonda[a] = rondas[a] ? 0 : null;
      totalesDesgloseRonda[a] = rondas[a] ? { disponible: 0, no_disponible: 0, error: 0 } : null;
    });
    tiendas.forEach((t) => {
      agregadores.forEach((a) => {
        AGR_CATEGORIAS_ESTADO.forEach((c) => { totales[a][c] += estados[t]?.[a]?.[c] || 0; });
        if (rondas[a]) {
          totalesHechoRonda[a] += (rondas[a].por_tienda || {})[t] || 0;
          const d = (rondas[a].por_tienda_desglose || {})[t];
          if (d) AGR_CATEGORIAS_RONDA.forEach((c) => { totalesDesgloseRonda[a][c] += d[c] || 0; });
        }
      });
    });

    const filasTienda = tiendas.map((t) => {
      const nombre = agrCentrosPorTienda[t]?.nombre || t;
      const celdas = agregadores.map((a) => {
        const hechoRonda = rondas[a] ? ((rondas[a].por_tienda || {})[t] || 0) : null;
        const desgloseRonda = rondas[a] ? (rondas[a].por_tienda_desglose || {})[t] : null;
        return agrCeldaEstadoHtml(estados[t]?.[a], hechoRonda, desgloseRonda);
      }).join("");
      return `<tr><td>${nombre}</td>${celdas}</tr>`;
    }).join("");
    const filaTotales = agregadores.map((a) => agrCeldaEstadoHtml(totales[a], totalesHechoRonda[a], totalesDesgloseRonda[a])).join("");

    // "Total único": mismo hechos/total_objetivo de la sección de arriba, en tabla
    // para comparar los 3 agregadores de un vistazo -- ya viene deduplicado (cada
    // dirección cuenta una sola vez), no hace falta pedir /panel/resumen-deduplicado
    // aparte.
    const filaTotalUnico = agregadores.map((a) => {
      const ronda = rondas[a];
      if (!ronda) return `<td>—</td>`;
      return `<td><b>${ronda.hechos}</b>/${ronda.total_objetivo} · faltan ${ronda.faltan}</td>`;
    }).join("");

    const seccionRondas = agregadores.map((a) => agrRondaHtml(a, rondas[a])).join("");

    contenido.innerHTML = `
      <h4 class="agr-scraper-titulo-seccion">Vuelta completa en curso</h4>
      <p class="agr-drill-nota">Solo cuenta lo revalidado DESDE que empezó esta pasada -- si un sitio ya tenía dato de antes (aunque sea viejo), no cuenta aquí como "hecho" hasta que se vuelva a comprobar de verdad en esta ronda.</p>
      ${seccionRondas}
      <h4 class="agr-scraper-titulo-seccion">Total único</h4>
      <div class="agr-scraper-tabla-wrap">
        <table class="agr-scraper-tabla">
          <thead><tr><th></th>${cabeceras}</tr></thead>
          <tbody><tr><td><b>Hechos/total</b></td>${filaTotalUnico}</tr></tbody>
        </table>
      </div>
      <h4 class="agr-scraper-titulo-seccion">Por tienda</h4>
      <p class="agr-drill-nota">"Hechos en esta ronda / total bruto" por tienda -- el total bruto puede tener solape entre tiendas vecinas (un mismo sitio real en más de una fila).</p>
      <div class="agr-scraper-tabla-wrap">
        <table class="agr-scraper-tabla">
          <thead><tr><th>Tienda</th>${cabeceras}</tr></thead>
          <tbody>${filasTienda}</tbody>
          <tfoot><tr><td>TOTAL</td>${filaTotales}</tr></tfoot>
        </table>
      </div>
    `;
    actualizado.textContent = "Actualizado: " + new Date().toLocaleTimeString("es-ES", { timeZone: "Europe/Madrid" });
  } catch {
    contenido.innerHTML = `<p class="agr-drill-nota">No se pudo cargar el dashboard del scraper. Inténtalo de nuevo.</p>`;
    actualizado.textContent = "";
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
  agrUsuarioActual = user;
  wireUserBar(user);
  const btnDashboardScraper = document.getElementById("agr-btn-dashboard-scraper");
  if (btnDashboardScraper) btnDashboardScraper.hidden = user.rol !== "admin";
  agrWireFiltroAgregador();
  agrAplicarColapsoTabla();

  await agrCargarTiendas();
  await agrCargarTodo();
  agrCargarFechasFiltroFecha(); // no bloquea el resto -- solo llena el <select> del filtro del mapa

  if (agrIntervalo) clearInterval(agrIntervalo);
  agrIntervalo = setInterval(agrCargarTodo, 30000);
});

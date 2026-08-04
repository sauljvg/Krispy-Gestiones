// Constructor visual de boletines por bloques. Sustituye al textarea de HTML
// crudo: cada bloque se edita con controles simples y el HTML final (el que
// se manda por email y se muestra en /blog.html) se genera aquí mismo, con
// estilos inline y colores en hex literal porque los clientes de correo no
// cargan hojas de estilo externas ni variables CSS.
const BoletinBuilder = (function () {
  // Presets antiguos de tamaño de imagen/espaciador — solo se usan para
  // traducir boletines guardados antes de que el tamaño fuera libre (número).
  const TAMANOS_IMAGEN = { pequena: 220, mediana: 380, grande: 560 };
  const TAMANOS_ESPACIADOR = { chico: 12, mediano: 28, grande: 52 };
  const BOTON_PADDING = { pequeno: "8px 18px", mediano: "13px 30px", grande: "18px 44px" };
  // Boletines guardados antes de que el color fuera libre (hex) usaban estas
  // 4 claves fijas — se traducen al vuelo para no romper contenido antiguo.
  const PRESETS_ANTIGUOS = { verde: "#0b6b3a", naranja: "#e07b00", azul: "#2454a6", gris: "#5a5a5a" };
  const ALINEACIONES = { izquierda: "left", centro: "center", derecha: "right", justificado: "justify" };

  // Iconos SVG en vez de ⠿ ▲ ▼ 🔗 — se ven igual de nítidos en cualquier
  // sistema, a diferencia de esos glifos que algunas fuentes no traen.
  const ICONO_FLECHA_ARRIBA = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5M5 12l7-7 7 7"/></svg>`;
  const ICONO_FLECHA_ABAJO = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M19 12l-7 7-7-7"/></svg>`;
  const ICONO_ARRASTRAR = `<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><circle cx="9" cy="5" r="1.5"/><circle cx="15" cy="5" r="1.5"/><circle cx="9" cy="12" r="1.5"/><circle cx="15" cy="12" r="1.5"/><circle cx="9" cy="19" r="1.5"/><circle cx="15" cy="19" r="1.5"/></svg>`;
  const ICONO_ENLACE = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>`;
  // Las 3 primeras son las fuentes de marca ya cargadas en styles.css
  // (@font-face con archivos propios); Fraunces viene de Google Fonts. Se
  // listan con su pila de resguardo por si el cliente de correo no las carga.
  // Comillas SIMPLES a propósito: la pila se inserta dentro de un atributo
  // style="..." con comillas dobles — un nombre de fuente con comillas
  // dobles rompe el atributo a la mitad (nos pasó y se ve como un bug
  // rarísimo: el resto del bloque desaparece). CSS acepta comillas simples
  // igual de bien para font-family.
  const FUENTES = {
    brandon: { etiqueta: "Brandon Grotesque (texto)", pila: "'Brandon Grotesque', Arial, Helvetica, sans-serif" },
    gelica: { etiqueta: "Gelica (títulos)", pila: "'Gelica', Arial, Helvetica, sans-serif" },
    brandon_printed: { etiqueta: "Brandon Printed (llamativa)", pila: "'Brandon Printed', Arial, Helvetica, sans-serif" },
    fraunces: { etiqueta: "Fraunces (serif editorial)", pila: "'Fraunces', Georgia, serif" },
    georgia: { etiqueta: "Georgia (serif clásica)", pila: "Georgia, 'Times New Roman', serif" },
    arial: { etiqueta: "Arial (predeterminada)", pila: "Arial, Helvetica, sans-serif" },
  };
  // Se antepone una vez al HTML final para que los clientes que sí soportan
  // @font-face en el cuerpo del correo (Apple Mail, y el propio /blog.html)
  // muestren la tipografía de marca real; el resto cae a la pila de resguardo.
  function fontFaceHtml() {
    const base = window.location.origin;
    return `<style>
      @import url('https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,600;0,9..144,700&display=swap');
      @font-face { font-family: "Gelica"; src: url("${base}/assets/fonts/Gelica-SemiBold.otf") format("opentype"); font-weight: 600; }
      @font-face { font-family: "Brandon Grotesque"; src: url("${base}/assets/fonts/BrandonGrotesque-Regular.otf") format("opentype"); font-weight: 400; }
      @font-face { font-family: "Brandon Printed"; src: url("${base}/assets/fonts/BrandonPrinted-One.ttf") format("truetype"); font-weight: 400; }
    </style>`;
  }
  function colorHex(valor, porDefecto) {
    if (valor && PRESETS_ANTIGUOS[valor]) return PRESETS_ANTIGUOS[valor];
    return /^#[0-9a-fA-F]{6}$/.test(valor || "") ? valor : porDefecto;
  }
  function fuentePila(clave, porDefecto) {
    return (FUENTES[clave] || FUENTES[porDefecto]).pila;
  }
  // Devuelve el número si es válido (>0), si no el valor por defecto. Sirve
  // para todos los campos numéricos (tamaño de letra, grosor, alto, radio...)
  // y de paso traduce presets antiguos tipo "mediano" -> px vía el mapa dado.
  function numOr(valor, porDefecto, mapaPresets) {
    if (mapaPresets && typeof valor === "string" && mapaPresets[valor] != null) return mapaPresets[valor];
    const n = Number(valor);
    // Se admite 0 (esquinas rectas = radio 0); solo se rechaza NaN/negativo.
    return Number.isFinite(n) && n >= 0 ? n : porDefecto;
  }

  const DEFINICIONES = {
    encabezado: { etiqueta: "Encabezado", icono: "🏷️" },
    titulo: { etiqueta: "Título de sección", icono: "🔠" },
    callout: { etiqueta: "Aviso destacado", icono: "📣" },
    texto: { etiqueta: "Texto", icono: "📝" },
    imagen: { etiqueta: "Imagen", icono: "🖼️" },
    galeria: { etiqueta: "Galería de fotos", icono: "🖼️🖼️" },
    video: { etiqueta: "Vídeo (YouTube)", icono: "🎬" },
    boton: { etiqueta: "Botón", icono: "🔘" },
    divisor: { etiqueta: "Divisor", icono: "➖" },
    espaciador: { etiqueta: "Espacio", icono: "↕️" },
    columnas: { etiqueta: "Dos columnas", icono: "▥" },
    capitulo: { etiqueta: "Divisor de departamento", icono: "🏢" },
    html_avanzado: { etiqueta: "HTML avanzado", icono: "💻" },
  };

  let postId = null;
  let bloques = [];
  let contador = 1;
  let elToolbar, elLista, elPreview;
  let arrastrandoId = null;

  // ------------------------------- utilidades -------------------------------

  function escapeHTML(str) {
    const div = document.createElement("div");
    div.textContent = str ?? "";
    return div.innerHTML;
  }

  function escapeAttr(str) {
    return escapeHTML(str).replaceAll('"', "&quot;").replaceAll("'", "&#39;");
  }

  // Acepta la URL completa (youtube.com/watch?v=, youtu.be/, /shorts/) o un
  // ID de 11 caracteres pegado directamente -- lo que sea más cómodo copiar
  // desde YouTube.
  function extraerYoutubeId(texto) {
    const t = (texto || "").trim();
    const m = t.match(/(?:youtu\.be\/|youtube\.com\/(?:watch\?v=|shorts\/|embed\/))([\w-]{11})/);
    if (m) return m[1];
    return /^[\w-]{11}$/.test(t) ? t : "";
  }

  // Convierte las miniaturas .boletin-video-thumb (ver htmlVideo) en el
  // reproductor embebido real -- se llama tras pintar la vista previa aquí,
  // y de forma independiente en blog.js tras pintar /blog.html (ese archivo
  // no carga este módulo entero solo para esto, por eso está duplicada: es
  // una función de 10 líneas, no vale la pena una dependencia nueva).
  function activarVideosBoletin(root) {
    root.querySelectorAll(".boletin-video-thumb[data-video-id]").forEach((a) => {
      const id = a.dataset.videoId;
      const wrap = document.createElement("div");
      wrap.className = "boletin-video-embed";
      wrap.innerHTML = `<iframe src="https://www.youtube-nocookie.com/embed/${id}?modestbranding=1&rel=0" title="Vídeo" loading="lazy" allow="autoplay; encrypted-media; picture-in-picture" allowfullscreen></iframe>`;
      a.replaceWith(wrap);
    });
  }

  function sanitizarHTML(html) {
    const PERMITIDOS = ["b", "strong", "i", "em", "u", "a", "ul", "ol", "li", "br", "p", "div", "span"];
    const tmp = document.createElement("div");
    tmp.innerHTML = html || "";
    for (let pasada = 0; pasada < 6; pasada++) {
      const malos = tmp.querySelectorAll(`*:not(${PERMITIDOS.join(",")})`);
      if (malos.length === 0) break;
      malos.forEach((el) => {
        while (el.firstChild) el.parentNode.insertBefore(el.firstChild, el);
        el.remove();
      });
    }
    tmp.querySelectorAll("*").forEach((el) => {
      [...el.attributes].forEach((attr) => {
        if (el.tagName === "A" && attr.name === "href") {
          const val = attr.value.trim();
          if (!/^https?:\/\//i.test(val) && !/^mailto:/i.test(val)) el.removeAttribute("href");
        } else {
          el.removeAttribute(attr.name);
        }
      });
    });
    return tmp.innerHTML;
  }

  // El editor de texto rico guarda <p> tal cual los deja el navegador, que
  // por defecto llevan su propio margen (~1em) — invisible mientras se
  // edita, pero produce huecos raros al lado del padding del bloque. Se
  // sustituye por un margen inferior controlado (espaciadoParrafos) para
  // que el usuario pueda quitarlo sin que el texto se pegue todo junto.
  function aplicarEspaciadoParrafos(html, espaciado) {
    const tmp = document.createElement("div");
    tmp.innerHTML = html || "";
    tmp.querySelectorAll("p").forEach((p) => { p.style.margin = `0 0 ${espaciado}px`; });
    return tmp.innerHTML;
  }

  function fileToDataURL(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
  }

  function blobToDataURL(blob) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = reject;
      reader.readAsDataURL(blob);
    });
  }

  function nuevoId() {
    return contador++;
  }

  // ------------------------------- modelo de bloques -------------------------------

  function crearBloque(tipo) {
    switch (tipo) {
      case "encabezado":
        return { id: nuevoId(), tipo, titulo: "Título del boletín", subtitulo: "", imagenId: null, imagenDataUrl: null,
                 color: "#0b6b3a", fuente: "gelica", colorTitulo: "#ffffff", tamanoTitulo: 26,
                 fuenteSubtitulo: "brandon", colorSubtitulo: "#ffffff", tamanoSubtitulo: 15,
                 modoImagen: "logo", tamanoLogo: 56, altura: 240 };
      case "titulo":
        return { id: nuevoId(), tipo, texto: "Título de sección", fuente: "brandon", alineacion: "izquierda",
                 colorTexto: "#1a1a1a", tamanoFuente: 19, fondo: "", interlineado: 1.3, espaciadoLetras: 0,
                 margenSup: 22, margenInf: 8 };
      case "callout":
        // Crema de glaseado (no rosa genérico) para que combine con la
        // identidad Krispy Kreme del resto de la plantilla.
        return { id: nuevoId(), tipo, texto: "Recuerda compartir este boletín con todo tu equipo", fuente: "brandon",
                 colorTexto: "#1a1a1a", tamanoFuente: 16, interlineado: 1.4, espaciadoLetras: 0.5,
                 paddingSup: 18, paddingInf: 18, radio: 0, fondo: "#fdeecb" };
      case "capitulo":
        return { id: nuevoId(), tipo, texto: "MARKETING", fuente: "gelica", alineacion: "izquierda",
                 colorTexto: "#ffffff", tamanoFuente: 22, interlineado: 1.2, espaciadoLetras: 1,
                 paddingSup: 16, paddingInf: 16, fondo: "#0b6b3a",
                 email: "", emailFuente: "brandon", emailColorTexto: "#ffffff", emailTamanoFuente: 12 };
      case "texto":
        return { id: nuevoId(), tipo, html: "<p>Escribe aquí el contenido...</p>", fuente: "brandon", alineacion: "izquierda",
                 fondo: "", colorTexto: "#1a1a1a", tamanoFuente: 15, interlineado: 1.6, espaciadoLetras: 0,
                 espaciadoParrafos: 10, paddingSup: 6, paddingInf: 6 };
      case "imagen":
        return { id: nuevoId(), tipo, imagenId: null, imagenDataUrl: null, anchoModo: "mediana", ancho: 380,
                 alineacion: "centro", radio: 8, pie: "", enlace: "", fondo: "" };
      case "galeria":
        return { id: nuevoId(), tipo,
                 imagenId1: null, imagenDataUrl1: null, pie1: "",
                 imagenId2: null, imagenDataUrl2: null, pie2: "",
                 imagenId3: null, imagenDataUrl3: null, pie3: "",
                 imagenId4: null, imagenDataUrl4: null, pie4: "",
                 espacio: 8, radio: 8, fondo: "", colorPie: "#666666", tamanoPie: 11 };
      case "video":
        return { id: nuevoId(), tipo, url: "", radio: 8, fondo: "" };
      case "boton":
        return { id: nuevoId(), tipo, texto: "Más información", url: "", color: "#0b6b3a", fuente: "brandon",
                 colorTexto: "#ffffff", tamanoFuente: 15, interlineado: 1.2, espaciadoLetras: 0,
                 alineacion: "centro", tamano: "mediano", radio: 8, fondo: "" };
      case "divisor":
        return { id: nuevoId(), tipo, color: "#dddddd", grosor: 1, estilo: "solid", fondo: "" };
      case "espaciador":
        return { id: nuevoId(), tipo, altura: 28, fondo: "" };
      case "columnas":
        return { id: nuevoId(), tipo, tipoColumnas: "imagen_texto",
                 imagenId: null, imagenDataUrl: null, imagenLado: "izquierda",
                 imagenId2: null, imagenDataUrl2: null,
                 tituloColumna: "", anchoImagen: 200,
                 texto: "<p>Escribe aquí...</p>", texto2: "<p>Escribe aquí...</p>",
                 fuente: "brandon", alineacion: "izquierda", fondo: "",
                 colorTexto: "#1a1a1a", tamanoFuente: 14, interlineado: 1.6, espaciadoLetras: 0, espaciadoParrafos: 10,
                 paddingSup: 14, paddingInf: 14 };
      case "html_avanzado":
        return { id: nuevoId(), tipo, html: "" };
      default:
        return null;
    }
  }

  // Todos los divisores de departamento en el mismo verde de marca — el
  // usuario prefirió esto a la paleta rotativa por color.
  function capituloDepartamento(texto) {
    return { ...crearBloque("capitulo"), texto, fondo: "#0b6b3a" };
  }

  const PLANTILLAS = {
    aviso_simple: () => [
      { ...crearBloque("encabezado"), titulo: "Aviso importante" },
      crearBloque("texto"),
      crearBloque("boton"),
    ],
    aviso_imagen: () => [
      { ...crearBloque("encabezado"), titulo: "Aviso importante" },
      crearBloque("imagen"),
      crearBloque("texto"),
    ],
    // Estructura tipo "El Coronel" (KFC/Sway): encabezado + identificación del
    // boletín, aviso de "compártelo con tu equipo", y un capítulo por
    // departamento — cada uno con un bloque de texto vacío listo para
    // rellenar. El usuario puede borrar los departamentos que no necesite.
    boletin_departamentos: () => [
      { ...crearBloque("encabezado"), titulo: "EL BOLETÍN", color: "#006838",
        subtitulo: "Boletín número 1 · " + new Date().toLocaleDateString("es-ES", { day: "numeric", month: "long", year: "numeric" }) },
      { ...crearBloque("callout"), texto: "RECUERDA COMPARTIR ESTE BOLETÍN CON TODO TU EQUIPO" },
      capituloDepartamento("MARKETING"), crearBloque("texto"),
      capituloDepartamento("COMPRAS (SUPPLY CHAIN)"), crearBloque("texto"),
      capituloDepartamento("CALIDAD"), crearBloque("texto"),
      capituloDepartamento("FORMACIÓN"), crearBloque("texto"),
      capituloDepartamento("OPERACIONES"), crearBloque("texto"),
      capituloDepartamento("PEOPLE & CULTURE (RRHH)"), crearBloque("texto"),
    ],
  };

  // ------------------------------- conversor bloques -> HTML -------------------------------

  function htmlEncabezado(b) {
    const color = colorHex(b.color, "#0b6b3a");
    const fuente = fuentePila(b.fuente, "gelica");
    const colorTitulo = colorHex(b.colorTitulo, "#ffffff");
    const tamTitulo = numOr(b.tamanoTitulo, 26);
    const titulo = `<h1 style="margin:0;color:${colorTitulo};font-family:${fuente};font-size:${tamTitulo}px;font-weight:700;line-height:1.2;">${escapeHTML(b.titulo || "")}</h1>`;
    const fuenteSub = fuentePila(b.fuenteSubtitulo, "brandon");
    const colorSub = colorHex(b.colorSubtitulo, colorTitulo);
    const tamSub = numOr(b.tamanoSubtitulo, Math.max(12, Math.round(tamTitulo * 0.58)));
    const sub = b.subtitulo
      ? `<p style="margin:8px 0 0;color:${colorSub};font-family:${fuenteSub};font-size:${tamSub}px;opacity:0.92;">${escapeHTML(b.subtitulo)}</p>`
      : "";

    // Modo "fondo": la imagen cubre todo el encabezado y el texto va
    // superpuesto encima, sobre una capa oscura semitransparente para que se
    // lea. Se hace con una tabla (background en la celda) porque es lo único
    // que respetan también los clientes de correo antiguos.
    if (b.modoImagen === "fondo" && b.imagenDataUrl) {
      const altura = numOr(b.altura, 240);
      return `<table role="presentation" width="100%" style="border-collapse:collapse;background-color:${color};background-image:url('${b.imagenDataUrl}');background-size:cover;background-position:center;">
        <tr><td height="${altura}" valign="middle" style="padding:32px 24px;text-align:center;background:rgba(0,0,0,0.4);">${titulo}${sub}</td></tr>
      </table>`;
    }

    const tamLogo = numOr(b.tamanoLogo, 56);
    const logo = b.imagenDataUrl
      ? `<img src="${b.imagenDataUrl}" alt="" style="max-height:${tamLogo}px;display:block;margin:0 auto 14px;">`
      : "";
    return `<div style="text-align:center;padding:32px 24px;background:${color};">${logo}${titulo}${sub}</div>`;
  }

  function htmlTitulo(b) {
    const fuente = fuentePila(b.fuente, "brandon");
    const align = ALINEACIONES[b.alineacion] || "left";
    const colorTexto = colorHex(b.colorTexto, "#1a1a1a");
    const tam = numOr(b.tamanoFuente, 19);
    const interlineado = numOr(b.interlineado, 1.3);
    const espLetras = numOr(b.espaciadoLetras, 0);
    const mSup = numOr(b.margenSup, 22);
    const mInf = numOr(b.margenInf, 8);
    // El fondo va en un envoltorio a todo el ancho, con el margen vertical
    // FUERA de la zona coloreada y el padding horizontal DENTRO — antes el
    // margen de 20px a cada lado estaba en el propio <h2> (que también
    // llevaba el fondo), así que la franja de color se quedaba corta por
    // ambos lados en vez de llegar a los bordes del bloque.
    const conFondo = b.fondo && /^#[0-9a-fA-F]{6}$/.test(b.fondo);
    const fondoCss = conFondo ? `background:${b.fondo};` : "";
    return `<div style="margin:${mSup}px 0 ${mInf}px;padding:0 20px;${fondoCss}"><h2 style="margin:0;padding:${conFondo ? "10px 0" : "0"};font-family:${fuente};font-size:${tam}px;font-weight:700;color:${colorTexto};text-align:${align};line-height:${interlineado};letter-spacing:${espLetras}px;">${escapeHTML(b.texto || "")}</h2></div>`;
  }

  function htmlCallout(b) {
    if (!b.texto || !b.texto.trim()) return "";
    const fuente = fuentePila(b.fuente, "brandon");
    const colorTexto = colorHex(b.colorTexto, "#1a1a1a");
    const tam = numOr(b.tamanoFuente, 16);
    const interlineado = numOr(b.interlineado, 1.4);
    const espLetras = numOr(b.espaciadoLetras, 0.5);
    const pSup = numOr(b.paddingSup, 18);
    const pInf = numOr(b.paddingInf, 18);
    const radio = numOr(b.radio, 0, { "": 0 });
    const fondo = colorHex(b.fondo, "#ffd9e6");
    // Mayúsculas vía CSS (no se muta el texto guardado) para que se lea como
    // un aviso destacado, igual que en la referencia de "El Coronel".
    const texto = escapeHTML(b.texto).replace(/\n/g, "<br>");
    return `<div style="background:${fondo};padding:${pSup}px 24px ${pInf}px;text-align:center;border-radius:${radio}px;"><p style="margin:0;font-family:${fuente};font-size:${tam}px;font-weight:700;color:${colorTexto};line-height:${interlineado};letter-spacing:${espLetras}px;text-transform:uppercase;">${texto}</p></div>`;
  }

  // El id/atributo estable aquí es lo que engancha con blog.js: cada
  // capítulo se convierte en un ancla navegable del índice flotante, y en un
  // punto de anclaje para el scroll suave. b.id ya es único dentro de un
  // mismo boletín (contador incremental por post), así que sirve tal cual.
  function htmlCapitulo(b) {
    if (!b.texto || !b.texto.trim()) return "";
    const fuente = fuentePila(b.fuente, "gelica");
    const colorTexto = colorHex(b.colorTexto, "#ffffff");
    const tam = numOr(b.tamanoFuente, 22);
    const interlineado = numOr(b.interlineado, 1.2);
    const espLetras = numOr(b.espaciadoLetras, 1);
    const align = ALINEACIONES[b.alineacion] || "left";
    const pSup = numOr(b.paddingSup, 16);
    const pInf = numOr(b.paddingInf, 16);
    const fondo = colorHex(b.fondo, "#0b6b3a");
    // El email va como <a> inline justo después del <h2> (también puesto en
    // inline) para que quede en la misma línea que el título — nada de
    // flexbox/grid, que los clientes de correo no soportan de forma fiable;
    // el flujo de texto normal ya los sienta juntos y envuelve solo si hace
    // falta en pantallas pequeñas.
    const email = (b.email || "").trim();
    const emailHtml = email
      ? (() => {
          const fuenteEmail = fuentePila(b.emailFuente, "brandon");
          const colorEmail = colorHex(b.emailColorTexto, "#ffffff");
          const tamEmail = numOr(b.emailTamanoFuente, 12);
          return ` <a href="mailto:${escapeAttr(email)}" style="margin-left:10px;font-family:${fuenteEmail};font-size:${tamEmail}px;font-weight:400;color:${colorEmail};text-decoration:underline;text-transform:none;">${escapeHTML(email)}</a>`;
        })()
      : "";
    return `<div id="cap-${b.id}" data-capitulo-titulo="${escapeAttr(b.texto)}" style="background:${fondo};padding:${pSup}px 24px ${pInf}px;text-align:${align};"><h2 style="display:inline;margin:0;font-family:${fuente};font-size:${tam}px;font-weight:700;color:${colorTexto};letter-spacing:${espLetras}px;line-height:${interlineado};text-transform:uppercase;">${escapeHTML(b.texto)}</h2>${emailHtml}</div>`;
  }

  function htmlGaleria(b) {
    const slots = [1, 2, 3, 4].map((n) => ({ url: b["imagenDataUrl" + n], pie: b["pie" + n] })).filter((s) => s.url);
    if (slots.length === 0) return "";
    const radio = numOr(b.radio, 8, { "": 0 });
    const espacio = numOr(b.espacio, 8);
    const colorPie = colorHex(b.colorPie, "#666666");
    const tamanoPie = numOr(b.tamanoPie, 11);
    const fondo = b.fondo && /^#[0-9a-fA-F]{6}$/.test(b.fondo) ? `background:${b.fondo};` : "";
    const anchoCelda = Math.floor(100 / slots.length);
    const celdas = slots.map((s) => `<td style="width:${anchoCelda}%;padding:0 ${espacio / 2}px;vertical-align:top;">
        <img src="${s.url}" alt="${escapeAttr(s.pie || "")}" style="max-width:100%;width:100%;border-radius:${radio}px;display:block;">
        ${s.pie ? `<div style="font-size:${tamanoPie}px;color:${colorPie};margin-top:4px;text-align:center;font-family:Arial,Helvetica,sans-serif;">${escapeHTML(s.pie)}</div>` : ""}
      </td>`).join("");
    return `<div style="padding:12px 20px;${fondo}"><table role="presentation" width="100%" style="border-collapse:collapse;"><tr>${celdas}</tr></table></div>`;
  }

  function htmlTexto(b) {
    const limpio = aplicarEspaciadoParrafos(sanitizarHTML(b.html || ""), numOr(b.espaciadoParrafos, 10));
    if (!limpio.replace(/<[^>]+>/g, "").trim()) return "";
    const fuente = fuentePila(b.fuente, "brandon");
    const align = ALINEACIONES[b.alineacion] || "left";
    const colorTexto = colorHex(b.colorTexto, "#1a1a1a");
    const tam = numOr(b.tamanoFuente, 15);
    const interlineado = numOr(b.interlineado, 1.6);
    const espLetras = numOr(b.espaciadoLetras, 0);
    const pSup = numOr(b.paddingSup, 6);
    const pInf = numOr(b.paddingInf, 6);
    const fondo = b.fondo && /^#[0-9a-fA-F]{6}$/.test(b.fondo) ? `background:${b.fondo};` : "";
    return `<div style="font-family:${fuente};font-size:${tam}px;line-height:${interlineado};letter-spacing:${espLetras}px;color:${colorTexto};padding:${pSup}px 20px ${pInf}px;text-align:${align};${fondo}">${limpio}</div>`;
  }

  function htmlImagen(b) {
    if (!b.imagenDataUrl) return "";
    const radio = numOr(b.radio, 8, { "": 0 });
    const align = ALINEACIONES[b.alineacion] || "center";
    // Ancho: si es "completa" ocupa todo el ancho disponible; si no, el
    // número de píxeles elegido (con presets antiguos traducidos).
    const anchoCss = b.anchoModo === "completa"
      ? "width:100%;"
      : `width:${numOr(b.ancho, 380, TAMANOS_IMAGEN)}px;`;
    const img = `<img src="${b.imagenDataUrl}" alt="${escapeAttr(b.pie || "")}" style="max-width:100%;${anchoCss}border-radius:${radio}px;display:inline-block;">`;
    const conEnlace = b.enlace ? `<a href="${escapeAttr(b.enlace)}">${img}</a>` : img;
    const pie = b.pie
      ? `<div style="font-size:12px;color:#666666;margin-top:6px;font-family:Arial,Helvetica,sans-serif;">${escapeHTML(b.pie)}</div>`
      : "";
    const fondo = b.fondo && /^#[0-9a-fA-F]{6}$/.test(b.fondo) ? `background:${b.fondo};` : "";
    return `<div style="text-align:${align};padding:12px 20px;${fondo}">${conEnlace}${pie}</div>`;
  }

  // El HTML guardado (contenido_html) se reutiliza TAL CUAL tanto en
  // /blog.html como en el correo que se envía por Resend -- un <iframe> de
  // YouTube ahí no funcionaría en el correo (los clientes de email lo
  // bloquean) y además dejaría descargar/seguir el enlace al canal. Por eso
  // el bloque se guarda siempre como una miniatura con botón de "play" que
  // enlaza al propio /blog.html del boletín (nunca a YouTube) -- en el
  // correo se queda así (funciona igual que una imagen normal) y en
  // /blog.html, boletin-video.js la sustituye por el reproductor embebido
  // real en cuanto carga la página (ver activarVideosBoletin más abajo).
  function htmlVideo(b) {
    const id = extraerYoutubeId(b.url);
    if (!id) return "";
    const radio = numOr(b.radio, 8, { "": 0 });
    const fondo = b.fondo && /^#[0-9a-fA-F]{6}$/.test(b.fondo) ? `background:${b.fondo};` : "";
    const destino = postId ? `${window.location.origin}/blog.html?post=${postId}` : "#";
    return `<div style="text-align:center;padding:12px 20px;${fondo}">
      <a href="${escapeAttr(destino)}" class="boletin-video-thumb" data-video-id="${escapeAttr(id)}"
         style="display:inline-block;position:relative;max-width:100%;text-decoration:none;line-height:0;">
        <img src="https://img.youtube.com/vi/${id}/hqdefault.jpg" alt="Ver vídeo" style="max-width:100%;width:100%;border-radius:${radio}px;display:block;">
        <span style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:60px;height:60px;background:rgba(0,0,0,0.65);border-radius:50%;">
          <span style="position:absolute;top:50%;left:54%;transform:translate(-50%,-50%);width:0;height:0;border-style:solid;border-width:11px 0 11px 18px;border-color:transparent transparent transparent #ffffff;"></span>
        </span>
      </a>
    </div>`;
  }

  function htmlBoton(b) {
    if (!b.texto || !b.texto.trim()) return "";
    const color = colorHex(b.color, "#0b6b3a");
    const colorTexto = colorHex(b.colorTexto, "#ffffff");
    const fuente = fuentePila(b.fuente, "brandon");
    const tam = numOr(b.tamanoFuente, 15);
    const interlineado = numOr(b.interlineado, 1.2);
    const espLetras = numOr(b.espaciadoLetras, 0);
    const radio = numOr(b.radio, 8, { "": 0 });
    const padding = BOTON_PADDING[b.tamano] || BOTON_PADDING.mediano;
    const align = ALINEACIONES[b.alineacion] || "center";
    // "fondo" es la franja detrás del botón (todo el ancho del bloque), no
    // el color del propio botón (ese es "color") — así se puede resaltar la
    // sección completa donde vive el botón, no solo la pastilla.
    const fondoFranja = b.fondo && /^#[0-9a-fA-F]{6}$/.test(b.fondo) ? `background:${b.fondo};` : "";
    // Un botón sin URL todavía es válido mientras se está montando el
    // boletín — se muestra igual (con "#" de relleno) para que la vista
    // previa no lo esconda; conviene rellenar la URL antes de enviar.
    return `<div style="text-align:${align};padding:16px 20px;${fondoFranja}"><a href="${escapeAttr(b.url || "#")}" style="display:inline-block;background:${color};color:${colorTexto};text-decoration:none;font-family:${fuente};font-size:${tam}px;line-height:${interlineado};letter-spacing:${espLetras}px;font-weight:700;padding:${padding};border-radius:${radio}px;">${escapeHTML(b.texto)}</a></div>`;
  }

  function htmlDivisor(b) {
    const color = colorHex(b.color, "#dddddd");
    const grosor = numOr(b.grosor, 1);
    const estilo = ["solid", "dashed", "dotted", "double"].includes(b.estilo) ? b.estilo : "solid";
    // El espacio vertical alrededor de la línea vive en el envoltorio (no en
    // el <hr>), para que el fondo -si se pone- cubra también ese aire y no
    // solo la línea misma.
    const fondo = b.fondo && /^#[0-9a-fA-F]{6}$/.test(b.fondo) ? `background:${b.fondo};` : "";
    return `<div style="padding:14px 20px;${fondo}"><hr style="border:none;border-top:${grosor}px ${estilo} ${color};margin:0;"></div>`;
  }

  function htmlEspaciador(b) {
    const alto = numOr(b.altura, 28, TAMANOS_ESPACIADOR);
    const fondo = b.fondo && /^#[0-9a-fA-F]{6}$/.test(b.fondo) ? `background:${b.fondo};` : "";
    return `<div style="height:${alto}px;line-height:${alto}px;font-size:1px;${fondo}">&nbsp;</div>`;
  }

  function htmlColumnas(b) {
    const tipoColumnas = b.tipoColumnas || "imagen_texto";
    const fondo = b.fondo && /^#[0-9a-fA-F]{6}$/.test(b.fondo) ? ` background:${b.fondo};` : "";

    if (tipoColumnas === "imagen_imagen") {
      const anchoImg = numOr(b.anchoImagen, 200);
      const celdaImg = (url) => `<td style="width:50%;padding:14px 10px;vertical-align:top;text-align:center;">${url ? `<img src="${url}" style="max-width:${anchoImg}px;width:100%;border-radius:8px;display:inline-block;">` : ""}</td>`;
      return `<table role="presentation" width="100%" style="border-collapse:collapse;${fondo}"><tr>${celdaImg(b.imagenDataUrl)}${celdaImg(b.imagenDataUrl2)}</tr></table>`;
    }

    const fuente = fuentePila(b.fuente, "brandon");
    const align = ALINEACIONES[b.alineacion] || "left";
    const colorTexto = colorHex(b.colorTexto, "#1a1a1a");
    const tam = numOr(b.tamanoFuente, 14);
    const interlineado = numOr(b.interlineado, 1.6);
    const espLetras = numOr(b.espaciadoLetras, 0);
    const pSup = numOr(b.paddingSup, 14);
    const pInf = numOr(b.paddingInf, 14);
    const espParrafos = numOr(b.espaciadoParrafos, 10);

    if (tipoColumnas === "texto_texto") {
      const limpio1 = aplicarEspaciadoParrafos(sanitizarHTML(b.texto || ""), espParrafos);
      const limpio2 = aplicarEspaciadoParrafos(sanitizarHTML(b.texto2 || ""), espParrafos);
      const estiloTd = `width:50%;padding:${pSup}px 10px ${pInf}px;vertical-align:top;font-family:${fuente};font-size:${tam}px;line-height:${interlineado};letter-spacing:${espLetras}px;color:${colorTexto};text-align:${align};`;
      return `<table role="presentation" width="100%" style="border-collapse:collapse;${fondo}"><tr><td style="${estiloTd}">${limpio1}</td><td style="${estiloTd}">${limpio2}</td></tr></table>`;
    }

    // imagen_texto (comportamiento original)
    const limpio = aplicarEspaciadoParrafos(sanitizarHTML(b.texto || ""), espParrafos);
    const anchoImg = numOr(b.anchoImagen, 200);
    const colImg = `<td style="width:${anchoImg}px;padding:14px 10px;vertical-align:top;">${b.imagenDataUrl ? `<img src="${b.imagenDataUrl}" style="max-width:100%;border-radius:8px;display:block;">` : ""}</td>`;
    const colTxt = `<td style="padding:${pSup}px 10px ${pInf}px;vertical-align:top;font-family:${fuente};font-size:${tam}px;line-height:${interlineado};letter-spacing:${espLetras}px;color:${colorTexto};text-align:${align};">${b.tituloColumna ? `<b style="display:block;margin-bottom:6px;">${escapeHTML(b.tituloColumna)}</b>` : ""}${limpio}</td>`;
    const celdas = b.imagenLado === "derecha" ? colTxt + colImg : colImg + colTxt;
    return `<table role="presentation" width="100%" style="border-collapse:collapse;${fondo}"><tr>${celdas}</tr></table>`;
  }

  function htmlAvanzado(b) {
    return `<div style="padding:10px 20px;">${b.html || ""}</div>`;
  }

  function renderBloque(b) {
    switch (b.tipo) {
      case "encabezado": return htmlEncabezado(b);
      case "titulo": return htmlTitulo(b);
      case "callout": return htmlCallout(b);
      case "texto": return htmlTexto(b);
      case "imagen": return htmlImagen(b);
      case "galeria": return htmlGaleria(b);
      case "video": return htmlVideo(b);
      case "boton": return htmlBoton(b);
      case "divisor": return htmlDivisor(b);
      case "espaciador": return htmlEspaciador(b);
      case "columnas": return htmlColumnas(b);
      case "capitulo": return htmlCapitulo(b);
      case "html_avanzado": return htmlAvanzado(b);
      default: return "";
    }
  }

  function getHtml() {
    const cuerpo = bloques.map(renderBloque).join("\n");
    return `${fontFaceHtml()}<div style="max-width:600px;margin:0 auto;background:#ffffff;font-family:Arial,Helvetica,sans-serif;">${cuerpo}</div>`;
  }

  // ------------------------------- formularios de edición -------------------------------

  function campoTexto(label, campo, valor, placeholder) {
    return `<div class="bloque-campo">
      <label>${escapeHTML(label)}</label>
      <input type="text" data-campo="${campo}" value="${escapeAttr(valor || "")}" placeholder="${escapeAttr(placeholder || "")}">
    </div>`;
  }

  function campoTextoLargo(label, campo, valor, placeholder) {
    return `<div class="bloque-campo">
      <label>${escapeHTML(label)}</label>
      <textarea data-campo="${campo}" rows="3" placeholder="${escapeAttr(placeholder || "")}">${escapeHTML(valor || "")}</textarea>
    </div>`;
  }

  function campoUrl(label, campo, valor) {
    return `<div class="bloque-campo">
      <label>${escapeHTML(label)}</label>
      <input type="url" data-campo="${campo}" value="${escapeAttr(valor || "")}" placeholder="https://">
    </div>`;
  }

  function campoSelect(label, campo, valor, opciones, recargar) {
    // recargar=true -> al cambiar se redibuja el formulario entero del bloque
    // (para mostrar/ocultar campos que dependen de esta opción, p.ej. el
    // modo de imagen del encabezado cambia entre "tamaño del logo" y "alto").
    return `<div class="bloque-campo">
      <label>${escapeHTML(label)}</label>
      <select data-campo="${campo}" ${recargar ? 'data-reload="1"' : ""}>
        ${opciones.map(([v, l]) => `<option value="${escapeAttr(v)}" ${v === valor ? "selected" : ""}>${escapeHTML(l)}</option>`).join("")}
      </select>
    </div>`;
  }

  function campoNumero(label, campo, valor, min, max, sufijo) {
    // Slider + número sincronizados, para que se pueda arrastrar rápido o
    // teclear un valor exacto. Ambos comparten data-campo-num.
    return `<div class="bloque-campo campo-numero">
      <label>${escapeHTML(label)}</label>
      <div class="numero-row">
        <input type="range" class="numero-range" data-campo-num="${campo}" min="${min}" max="${max}" value="${valor}">
        <input type="number" class="numero-input" data-campo-num="${campo}" min="${min}" max="${max}" value="${valor}">
        <span class="numero-sufijo">${escapeHTML(sufijo || "px")}</span>
      </div>
    </div>`;
  }

  function campoFuente(label, campo, valor) {
    return campoSelect(label, campo, valor, Object.entries(FUENTES).map(([v, def]) => [v, def.etiqueta]));
  }

  function campoAlineacion(label, campo, valor) {
    return campoSelect(label, campo, valor, [["izquierda", "Izquierda"], ["centro", "Centro"], ["derecha", "Derecha"], ["justificado", "Justificado"]]);
  }

  function campoColor(label, campo, valor, porDefecto, permitirVacio) {
    const hex = colorHex(valor, porDefecto);
    const quitar = permitirVacio
      ? `<button type="button" class="btn btn-ghost btn-mini btn-quitar-color" data-campo="${campo}">✕ Sin color</button>`
      : "";
    return `<div class="bloque-campo campo-color">
      <label>${escapeHTML(label)}</label>
      <div class="color-picker-row">
        <input type="color" class="color-swatch" data-campo="${campo}" value="${escapeAttr(hex)}">
        <input type="text" class="color-hex" data-campo-hex="${campo}" value="${escapeAttr(hex)}" placeholder="#0b6b3a" maxlength="7">
        ${quitar}
      </div>
    </div>`;
  }

  // --- Barra de estilo de texto: agrupa fuente/tamaño/color/alineación/
  // interlineado/espaciado en una sola fila compacta en vez de un campo por
  // fila (que era una lista larguísima). Los steppers (–/+) y los botones de
  // alineación reusan el mismo data-campo-num / data-campo que ya procesan
  // los listeners de input y click — no hace falta wiring nuevo aparte de
  // los propios botones de stepper/alineación.

  function ctrlFuenteCompacta(campo, valor) {
    return `<select class="mini-select" data-campo="${campo}" title="Tipo de letra">
      ${Object.entries(FUENTES).map(([v, def]) => `<option value="${v}" ${v === valor ? "selected" : ""}>${escapeHTML(def.etiqueta)}</option>`).join("")}
    </select>`;
  }

  function ctrlNumeroChico(campo, valor, min, max, step, etiqueta, conStepper) {
    const stepperMenos = conStepper ? `<button type="button" class="btn-stepper" data-delta="-1">–</button>` : "";
    const stepperMas = conStepper ? `<button type="button" class="btn-stepper" data-delta="1">+</button>` : "";
    return `<span class="mini-campo-num" title="${escapeAttr(etiqueta)}">
      <span class="mini-etiqueta">${escapeHTML(etiqueta)}</span>
      ${stepperMenos}
      <input type="number" class="mini-num-chico" data-campo-num="${campo}" min="${min}" max="${max}" step="${step}" value="${valor}">
      ${stepperMas}
    </span>`;
  }

  function ctrlColorCompacto(campo, valor, porDefecto, etiqueta) {
    const hex = colorHex(valor, porDefecto);
    return `<span class="mini-campo-num" title="${escapeAttr(etiqueta)}">
      <span class="mini-etiqueta">${escapeHTML(etiqueta)}</span>
      <input type="color" class="mini-color-swatch" data-campo="${campo}" value="${escapeAttr(hex)}">
    </span>`;
  }

  function ctrlAlineacionCompacta(campo, valor) {
    const opciones = [["izquierda", "⬅", "Izquierda"], ["centro", "↔", "Centro"], ["derecha", "➡", "Derecha"], ["justificado", "☰", "Justificar"]];
    return `<span class="mini-align-grupo" title="Alineación">
      ${opciones.map(([v, icono, tit]) => `<button type="button" class="btn-align ${v === (valor || "izquierda") ? "activo" : ""}" data-campo-valor="${campo}" data-valor="${v}" title="${tit}">${icono}</button>`).join("")}
    </span>`;
  }

  // opciones: { alineacion, parrafos, padding, margen, tamanoDefecto, colorDefecto }
  function barraEstiloTexto(b, opciones) {
    opciones = opciones || {};
    const partes = [
      ctrlFuenteCompacta("fuente", b.fuente),
      ctrlNumeroChico("tamanoFuente", numOr(b.tamanoFuente, opciones.tamanoDefecto || 15), opciones.tamanoMin || 10, opciones.tamanoMax || 60, 1, "Tamaño", true),
      ctrlColorCompacto("colorTexto", b.colorTexto, opciones.colorDefecto || "#1a1a1a", "Color"),
    ];
    if (opciones.alineacion !== false) partes.push(ctrlAlineacionCompacta("alineacion", b.alineacion));
    partes.push(ctrlNumeroChico("interlineado", numOr(b.interlineado, opciones.interlineadoDefecto || 1.4), 0.9, 3, 0.1, "Interlineado", true));
    partes.push(ctrlNumeroChico("espaciadoLetras", numOr(b.espaciadoLetras, 0), -1, 6, 0.5, "Entre letras", true));
    if (opciones.parrafos) partes.push(ctrlNumeroChico("espaciadoParrafos", numOr(b.espaciadoParrafos, 10), 0, 60, 1, "Entre párrafos", true));
    let filas = `<div class="barra-estilo-texto">${partes.join("")}</div>`;
    if (opciones.padding || opciones.margen) {
      const partes2 = [];
      if (opciones.padding) {
        partes2.push(ctrlNumeroChico("paddingSup", numOr(b.paddingSup, opciones.paddingDefecto || 6), 0, 100, 1, "Espacio interno arriba", true));
        partes2.push(ctrlNumeroChico("paddingInf", numOr(b.paddingInf, opciones.paddingDefecto || 6), 0, 100, 1, "Espacio interno abajo", true));
      }
      if (opciones.margen) {
        partes2.push(ctrlNumeroChico("margenSup", numOr(b.margenSup, opciones.margenSupDefecto || 0), 0, 100, 1, "Margen arriba", true));
        partes2.push(ctrlNumeroChico("margenInf", numOr(b.margenInf, opciones.margenInfDefecto || 0), 0, 100, 1, "Margen abajo", true));
      }
      filas += `<div class="barra-estilo-texto barra-espaciado">${partes2.join("")}</div>`;
    }
    return filas;
  }

  function barraFormatoHtml() {
    return `<div class="formato-barra">
      <button type="button" class="btn-formato" data-cmd="bold" title="Negrita"><b>N</b></button>
      <button type="button" class="btn-formato" data-cmd="italic" title="Cursiva"><i>K</i></button>
      <button type="button" class="btn-formato" data-cmd="insertUnorderedList" title="Lista">•</button>
      <button type="button" class="btn-formato" data-cmd="link" title="Enlace">${ICONO_ENLACE}</button>
    </div>`;
  }

  function campoRico(label, campo, html) {
    return `<div class="bloque-campo">
      <label>${escapeHTML(label)}</label>
      ${barraFormatoHtml()}
      <div class="contenteditable-campo" contenteditable="true" data-campo-html="${campo}">${html || ""}</div>
    </div>`;
  }

  function campoImagen(b) {
    const thumb = b.imagenDataUrl
      ? `<img class="imagen-picker-thumb" src="${b.imagenDataUrl}" alt="">`
      : `<div class="imagen-picker-vacio">Sin imagen todavía</div>`;
    return `<div class="bloque-campo imagen-picker">
      ${thumb}
      <button type="button" class="btn btn-ghost btn-mini btn-subir-imagen-bloque">📷 ${b.imagenDataUrl ? "Cambiar imagen" : "Subir imagen"}</button>
      <input type="file" class="input-imagen-bloque" accept=".jpg,.jpeg,.png,.webp" hidden>
    </div>`;
  }

  // Igual que campoImagen pero apuntando a un par de campos con nombre propio
  // (imagenId1/imagenDataUrl1, imagenId2/...) para poder tener varias fotos
  // independientes en un mismo bloque (galería). Los data-campo-imagen-*
  // los lee el listener genérico de subida en wireLista().
  function campoImagenGaleria(b, n) {
    const campoId = "imagenId" + n;
    const campoDataUrl = "imagenDataUrl" + n;
    const val = b[campoDataUrl];
    const thumb = val
      ? `<img class="imagen-picker-thumb" src="${val}" alt="">`
      : `<div class="imagen-picker-vacio">Foto ${n}</div>`;
    return `<div class="bloque-campo imagen-picker" data-campo-imagen-id="${campoId}" data-campo-imagen-dataurl="${campoDataUrl}">
      ${thumb}
      <button type="button" class="btn btn-ghost btn-mini btn-subir-imagen-bloque">📷 ${val ? "Cambiar" : "Subir"}</button>
      <input type="file" class="input-imagen-bloque" accept=".jpg,.jpeg,.png,.webp" hidden>
    </div>`;
  }

  function formEncabezado(b) {
    const controlImagen = b.imagenId
      ? (b.modoImagen === "fondo"
          ? campoNumero("Alto del encabezado", "altura", numOr(b.altura, 240), 120, 500)
          : campoNumero("Tamaño del logo", "tamanoLogo", numOr(b.tamanoLogo, 56), 24, 200))
      : `<p class="staff-hint">Sube una imagen para poder usarla como logo o como fondo a pantalla completa.</p>`;
    return `${campoImagen(b)}
      ${campoSelect("Uso de la imagen", "modoImagen", b.modoImagen || "logo", [["logo", "Logo encima del título"], ["fondo", "Fondo a pantalla completa (texto encima)"]], true)}
      ${controlImagen}
      ${campoColor("Color de fondo del encabezado", "color", b.color, "#0b6b3a")}
      <div class="bloque-campo">
        <label>Título</label>
        <input type="text" data-campo="titulo" value="${escapeAttr(b.titulo || "")}" placeholder="Título del boletín">
        <div class="barra-estilo-texto">
          ${ctrlFuenteCompacta("fuente", b.fuente)}
          ${ctrlNumeroChico("tamanoTitulo", numOr(b.tamanoTitulo, 26), 14, 60, 1, "Tamaño", true)}
          ${ctrlColorCompacto("colorTitulo", b.colorTitulo, "#ffffff", "Color")}
        </div>
      </div>
      <div class="bloque-campo">
        <label>Subtítulo (opcional)</label>
        <input type="text" data-campo="subtitulo" value="${escapeAttr(b.subtitulo || "")}" placeholder="Un mensaje breve debajo del título">
        <div class="barra-estilo-texto">
          ${ctrlFuenteCompacta("fuenteSubtitulo", b.fuenteSubtitulo)}
          ${ctrlNumeroChico("tamanoSubtitulo", numOr(b.tamanoSubtitulo, 15), 10, 40, 1, "Tamaño", true)}
          ${ctrlColorCompacto("colorSubtitulo", b.colorSubtitulo, "#ffffff", "Color")}
        </div>
      </div>`;
  }

  function formTitulo(b) {
    return `${campoTexto("Texto del título de sección", "texto", b.texto, "Título de sección")}
      ${barraEstiloTexto(b, { tamanoDefecto: 19, tamanoMin: 12, tamanoMax: 48, colorDefecto: "#1a1a1a", interlineadoDefecto: 1.3, margen: true, margenSupDefecto: 22, margenInfDefecto: 8 })}
      ${campoColor("Color de fondo (opcional)", "fondo", b.fondo, "#ffffff", true)}`;
  }

  function formCallout(b) {
    return `<p class="staff-hint">Una caja resaltada para avisos importantes (se muestra en mayúsculas).</p>
      ${campoTextoLargo("Texto del aviso", "texto", b.texto, "Recuerda compartir este boletín con todo tu equipo")}
      ${barraEstiloTexto(b, { tamanoDefecto: 16, tamanoMin: 11, tamanoMax: 40, colorDefecto: "#1a1a1a", interlineadoDefecto: 1.4, alineacion: false, padding: true, paddingDefecto: 18 })}
      ${campoColor("Color de fondo", "fondo", b.fondo, "#ffd9e6")}
      ${campoNumero("Redondeo de esquinas", "radio", numOr(b.radio, 0, { "": 0 }), 0, 40)}`;
  }

  function formCapitulo(b) {
    return `<p class="staff-hint">Divisor ancho para arrancar una sección/departamento (MARKETING, COMPRAS...).</p>
      ${campoTexto("Nombre del departamento/sección", "texto", b.texto, "MARKETING")}
      ${barraEstiloTexto(b, { tamanoDefecto: 22, tamanoMin: 14, tamanoMax: 48, colorDefecto: "#ffffff", interlineadoDefecto: 1.2, padding: true, paddingDefecto: 16 })}
      <div class="bloque-campo">
        <label>Email del responsable (opcional, aparece junto al título)</label>
        <input type="text" data-campo="email" value="${escapeAttr(b.email || "")}" placeholder="nombre@krispykreme.es">
        <div class="barra-estilo-texto">
          ${ctrlFuenteCompacta("emailFuente", b.emailFuente)}
          ${ctrlNumeroChico("emailTamanoFuente", numOr(b.emailTamanoFuente, 12), 8, 30, 1, "Tamaño", true)}
          ${ctrlColorCompacto("emailColorTexto", b.emailColorTexto, "#ffffff", "Color")}
        </div>
      </div>
      ${campoColor("Color de fondo", "fondo", b.fondo, "#0b6b3a")}`;
  }

  function formGaleria(b) {
    const slots = [1, 2, 3, 4].map((n) => `
      <div class="galeria-slot">
        ${campoImagenGaleria(b, n)}
        ${campoTexto("Pie de foto " + n + " (opcional)", "pie" + n, b["pie" + n], "")}
      </div>`).join("");
    return `<p class="staff-hint">Sube entre 2 y 4 fotos — se acomodan automáticamente en fila. Deja vacíos los huecos que no uses.</p>
      ${slots}
      ${campoNumero("Espacio entre fotos", "espacio", numOr(b.espacio, 8), 0, 40)}
      ${campoNumero("Redondeo de esquinas", "radio", numOr(b.radio, 8, { "": 0 }), 0, 40)}
      <div class="bloque-campo">
        <label>Pies de foto</label>
        <div class="barra-estilo-texto">
          ${ctrlNumeroChico("tamanoPie", numOr(b.tamanoPie, 11), 8, 24, 1, "Tamaño", true)}
          ${ctrlColorCompacto("colorPie", b.colorPie, "#666666", "Color")}
        </div>
      </div>
      ${campoColor("Color de fondo (opcional)", "fondo", b.fondo, "#ffffff", true)}`;
  }

  function formTexto(b) {
    return `${campoRico("Texto", "html", b.html)}
      ${barraEstiloTexto(b, { tamanoDefecto: 15, tamanoMin: 10, tamanoMax: 40, colorDefecto: "#1a1a1a", interlineadoDefecto: 1.6, parrafos: true, padding: true, paddingDefecto: 6 })}
      ${campoColor("Color de fondo (opcional)", "fondo", b.fondo, "#ffffff", true)}`;
  }

  function formImagen(b) {
    const controlAncho = b.anchoModo === "completa"
      ? `<p class="staff-hint">La imagen ocupará todo el ancho del boletín.</p>`
      : campoNumero("Ancho", "ancho", numOr(b.ancho, 380, TAMANOS_IMAGEN), 80, 600);
    return `${campoImagen(b)}
      ${campoSelect("Tamaño de la imagen", "anchoModo", b.anchoModo || "mediana", [["mediana", "Personalizado"], ["completa", "Ancho completo"]], true)}
      ${controlAncho}
      ${campoAlineacion("Alineación", "alineacion", b.alineacion)}
      ${campoNumero("Redondeo de esquinas", "radio", numOr(b.radio, 8, { "": 0 }), 0, 40)}
      ${campoTexto("Pie de foto (opcional)", "pie", b.pie, "")}
      ${campoUrl("Enlace al hacer clic (opcional)", "enlace", b.enlace)}
      ${campoColor("Color de fondo (opcional)", "fondo", b.fondo, "#ffffff", true)}`;
  }

  function formVideo(b) {
    const id = extraerYoutubeId(b.url);
    const previa = id
      ? `<img src="https://img.youtube.com/vi/${id}/hqdefault.jpg" alt="" style="max-width:100%;border-radius:8px;display:block;margin-top:8px;">`
      : `<p class="staff-hint">Pega el enlace y aparecerá la miniatura aquí.</p>`;
    return `<p class="staff-hint">Sube el vídeo a YouTube como "Oculto" (no listado) y pega aquí su enlace. En el
      correo se ve como una miniatura con botón de play (los emails no reproducen vídeo); al entrar a
      /blog.html se reproduce dentro de la propia página, sin enlace a su canal ni botón de descarga
      (YouTube exige dejar su logo pequeño en el reproductor, eso no se puede quitar).</p>
      ${campoTexto("Enlace o ID del vídeo de YouTube", "url", b.url, "https://youtu.be/...")}
      ${previa}
      ${campoNumero("Redondeo de esquinas", "radio", numOr(b.radio, 8, { "": 0 }), 0, 40)}
      ${campoColor("Color de fondo (opcional)", "fondo", b.fondo, "#ffffff", true)}`;
  }

  function formBoton(b) {
    return `${campoTexto("Texto del botón", "texto", b.texto, "Más información")}
      ${barraEstiloTexto(b, { tamanoDefecto: 15, tamanoMin: 11, tamanoMax: 34, colorDefecto: "#ffffff", interlineadoDefecto: 1.2, alineacion: false })}
      ${campoUrl("Dirección a la que lleva", "url", b.url)}
      ${campoAlineacion("Posición del botón", "alineacion", b.alineacion)}
      ${campoSelect("Tamaño del botón", "tamano", b.tamano || "mediano", [["pequeno", "Pequeño"], ["mediano", "Mediano"], ["grande", "Grande"]])}
      ${campoNumero("Redondeo de esquinas", "radio", numOr(b.radio, 8, { "": 0 }), 0, 40)}
      ${campoColor("Color del botón", "color", b.color, "#0b6b3a")}
      ${campoColor("Color de fondo de la franja (opcional)", "fondo", b.fondo, "#ffffff", true)}`;
  }

  function formDivisor(b) {
    return `<p class="staff-hint">Una línea para separar secciones.</p>
      ${campoSelect("Estilo de línea", "estilo", b.estilo || "solid", [["solid", "Continua"], ["dashed", "Discontinua (guiones)"], ["dotted", "Punteada"], ["double", "Doble"]])}
      ${campoNumero("Grosor", "grosor", numOr(b.grosor, 1), 1, 12)}
      ${campoColor("Color de la línea", "color", b.color, "#dddddd")}
      ${campoColor("Color de fondo (opcional)", "fondo", b.fondo, "#ffffff", true)}`;
  }

  function formEspaciador(b) {
    return `<p class="staff-hint">Espacio en blanco entre bloques.</p>
      ${campoNumero("Alto del espacio", "altura", numOr(b.altura, 28, TAMANOS_ESPACIADOR), 4, 160)}
      ${campoColor("Color de fondo (opcional)", "fondo", b.fondo, "#ffffff", true)}`;
  }

  function formColumnas(b) {
    const tipoColumnas = b.tipoColumnas || "imagen_texto";
    const selectorTipo = campoSelect("Tipo de columnas", "tipoColumnas", tipoColumnas, [
      ["imagen_texto", "Imagen y texto"],
      ["imagen_imagen", "Imagen e imagen"],
      ["texto_texto", "Texto y texto"],
    ], true);

    let contenido;
    if (tipoColumnas === "imagen_imagen") {
      contenido = `
        <div class="bloque-campo"><label>Imagen izquierda</label>${campoImagen(b)}</div>
        <div class="bloque-campo"><label>Imagen derecha</label>${campoImagenGaleria(b, 2)}</div>
        ${campoNumero("Ancho de cada imagen", "anchoImagen", numOr(b.anchoImagen, 200), 80, 400)}`;
    } else if (tipoColumnas === "texto_texto") {
      contenido = `
        ${campoRico("Texto columna izquierda", "texto", b.texto)}
        ${campoRico("Texto columna derecha", "texto2", b.texto2)}
        ${barraEstiloTexto(b, { tamanoDefecto: 14, tamanoMin: 10, tamanoMax: 34, colorDefecto: "#1a1a1a", interlineadoDefecto: 1.6, parrafos: true, padding: true, paddingDefecto: 14 })}`;
    } else {
      contenido = `${campoImagen(b)}
        ${campoSelect("Lado de la imagen", "imagenLado", b.imagenLado, [["izquierda", "Izquierda"], ["derecha", "Derecha"]])}
        ${campoNumero("Ancho de la imagen", "anchoImagen", numOr(b.anchoImagen, 200), 80, 400)}
        ${campoTexto("Título de la columna (opcional)", "tituloColumna", b.tituloColumna, "")}
        ${campoRico("Texto", "texto", b.texto)}
        ${barraEstiloTexto(b, { tamanoDefecto: 14, tamanoMin: 10, tamanoMax: 34, colorDefecto: "#1a1a1a", interlineadoDefecto: 1.6, parrafos: true, padding: true, paddingDefecto: 14 })}`;
    }
    return `${selectorTipo}${contenido}
      ${campoColor("Color de fondo (opcional)", "fondo", b.fondo, "#ffffff", true)}`;
  }

  function formAvanzado(b) {
    return `<p class="staff-hint">Modo avanzado: escribe HTML directamente. Pensado para quien ya sabe HTML — no se revisa ni se limpia.</p>
      <textarea data-campo="html" rows="8" class="textarea-avanzado" placeholder="&lt;p&gt;Tu HTML aquí...&lt;/p&gt;">${escapeHTML(b.html || "")}</textarea>`;
  }

  function formularioBloque(b) {
    switch (b.tipo) {
      case "encabezado": return formEncabezado(b);
      case "titulo": return formTitulo(b);
      case "callout": return formCallout(b);
      case "texto": return formTexto(b);
      case "imagen": return formImagen(b);
      case "galeria": return formGaleria(b);
      case "video": return formVideo(b);
      case "boton": return formBoton(b);
      case "divisor": return formDivisor(b);
      case "espaciador": return formEspaciador(b);
      case "columnas": return formColumnas(b);
      case "capitulo": return formCapitulo(b);
      case "html_avanzado": return formAvanzado(b);
      default: return "";
    }
  }

  // ------------------------------- lista de bloques (edición) -------------------------------

  function bloqueItemHtml(b, i) {
    const def = DEFINICIONES[b.tipo];
    return `<div class="bloque-item" draggable="true" data-id="${b.id}">
      <div class="bloque-item-head">
        <span class="bloque-handle" title="Arrastra para mover">${ICONO_ARRASTRAR}</span>
        <span class="bloque-tipo-badge">${def.icono} ${escapeHTML(def.etiqueta)}</span>
        <div class="bloque-item-acciones">
          <button type="button" class="btn btn-ghost btn-mini btn-mover-arriba" data-id="${b.id}" title="Subir" ${i === 0 ? "disabled" : ""}>${ICONO_FLECHA_ARRIBA}</button>
          <button type="button" class="btn btn-ghost btn-mini btn-mover-abajo" data-id="${b.id}" title="Bajar" ${i === bloques.length - 1 ? "disabled" : ""}>${ICONO_FLECHA_ABAJO}</button>
          <button type="button" class="btn btn-ghost btn-mini btn-eliminar-bloque" data-id="${b.id}" title="Eliminar"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg></button>
        </div>
      </div>
      <div class="bloque-item-body" data-id="${b.id}">${formularioBloque(b)}</div>
    </div>`;
  }

  function render() {
    renderLista();
    renderPreview();
  }

  function renderLista() {
    if (bloques.length === 0) {
      elLista.innerHTML = `<p class="builder-vacio">Todavía no has añadido ningún bloque. Usa los botones de arriba para empezar, o elige una plantilla.</p>`;
      return;
    }
    elLista.innerHTML = bloques.map((b, i) => bloqueItemHtml(b, i)).join("");
  }

  function renderPreview() {
    elPreview.innerHTML = bloques.length === 0
      ? `<p class="builder-vacio">La vista previa aparecerá aquí en cuanto añadas algún bloque.</p>`
      : getHtml();
    activarVideosBoletin(elPreview);
  }

  function actualizarBloqueBody(id) {
    const b = bloques.find((x) => x.id === id);
    const el = elLista.querySelector(`.bloque-item-body[data-id="${id}"]`);
    if (el && b) el.innerHTML = formularioBloque(b);
    renderPreview();
  }

  function moverBloque(id, delta) {
    const i = bloques.findIndex((b) => b.id === id);
    if (i === -1) return;
    const j = i + delta;
    if (j < 0 || j >= bloques.length) return;
    const tmp = bloques[i];
    bloques[i] = bloques[j];
    bloques[j] = tmp;
    render();
  }

  function moverBloqueJunto(idOrigen, idDestino, antes) {
    const iOrigen = bloques.findIndex((b) => b.id === idOrigen);
    if (iOrigen === -1) return;
    const [item] = bloques.splice(iOrigen, 1);
    let iDestino = bloques.findIndex((b) => b.id === idDestino);
    if (iDestino === -1) iDestino = bloques.length;
    bloques.splice(antes ? iDestino : iDestino + 1, 0, item);
  }

  function eliminarBloque(id) {
    if (!confirm("¿Eliminar este bloque? Esta acción no se puede deshacer.")) return;
    bloques = bloques.filter((b) => b.id !== id);
    render();
  }

  function agregarBloque(tipo) {
    const b = crearBloque(tipo);
    if (!b) return;
    bloques.push(b);
    render();
    const el = elLista.querySelector(".bloque-item:last-child");
    if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function aplicarPlantilla(nombre) {
    const fabrica = PLANTILLAS[nombre];
    if (!fabrica) return;
    if (bloques.length > 0 && !confirm("Esto reemplaza el contenido actual del boletín por la plantilla elegida. ¿Continuar?")) return;
    bloques = fabrica();
    render();
  }

  // campoImagenId/campoImagenDataUrl dejan elegir a qué par de propiedades
  // del bloque se escribe el resultado — por defecto imagenId/imagenDataUrl
  // (encabezado, imagen, columnas), pero la galería tiene 4 pares propios
  // (imagenId1/imagenDataUrl1...) para poder llevar varias fotos a la vez.
  async function subirImagenParaBloque(id, file, campoImagenId, campoImagenDataUrl) {
    campoImagenId = campoImagenId || "imagenId";
    campoImagenDataUrl = campoImagenDataUrl || "imagenDataUrl";
    const b = bloques.find((x) => x.id === id);
    if (!b) return;
    const formData = new FormData();
    formData.append("file", file);
    let res;
    try {
      res = await fetch(`${AUTH_API_BASE}/boletines/posts/${postId}/imagenes`, { method: "POST", body: formData });
    } catch (e) {
      alert("No se pudo subir la imagen (revisa tu conexión).");
      return;
    }
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      alert(err.detail || "No se pudo subir la imagen.");
      return;
    }
    const data = await res.json();
    b[campoImagenId] = data.id;
    b[campoImagenDataUrl] = await fileToDataURL(file);
    actualizarBloqueBody(id);
  }

  function aplicarFormato(btn) {
    const campo = btn.closest(".bloque-campo").querySelector("[data-campo-html]");
    if (!campo) return;
    campo.focus();
    const cmd = btn.dataset.cmd;
    if (cmd === "link") {
      const url = prompt("¿A qué dirección debe llevar el enlace?", "https://");
      if (!url) return;
      document.execCommand("createLink", false, url);
    } else {
      document.execCommand(cmd);
    }
    campo.dispatchEvent(new Event("input", { bubbles: true }));
  }

  // ------------------------------- wiring -------------------------------

  function wireToolbar() {
    elToolbar.addEventListener("click", (e) => {
      const btnTipo = e.target.closest("[data-tipo]");
      if (btnTipo) { agregarBloque(btnTipo.dataset.tipo); return; }
      const btnPlantilla = e.target.closest("[data-plantilla]");
      if (btnPlantilla) { aplicarPlantilla(btnPlantilla.dataset.plantilla); return; }
    });
  }

  function wireLista() {
    elLista.addEventListener("mousedown", (e) => {
      if (e.target.closest(".btn-formato")) { e.preventDefault(); return; }
      const item = e.target.closest(".bloque-item");
      if (!item) return;
      const interactivo = e.target.closest("input, textarea, select, [contenteditable], button");
      item.draggable = !interactivo;
    });

    elLista.addEventListener("click", (e) => {
      const btnFormato = e.target.closest(".btn-formato");
      if (btnFormato) { aplicarFormato(btnFormato); return; }
      const btnSubir = e.target.closest(".btn-subir-imagen-bloque");
      if (btnSubir) { btnSubir.closest(".bloque-campo").querySelector(".input-imagen-bloque").click(); return; }
      const btnArriba = e.target.closest(".btn-mover-arriba");
      if (btnArriba) { moverBloque(Number(btnArriba.dataset.id), -1); return; }
      const btnAbajo = e.target.closest(".btn-mover-abajo");
      if (btnAbajo) { moverBloque(Number(btnAbajo.dataset.id), 1); return; }
      const btnEliminar = e.target.closest(".btn-eliminar-bloque");
      if (btnEliminar) { eliminarBloque(Number(btnEliminar.dataset.id)); return; }
      const btnQuitarColor = e.target.closest(".btn-quitar-color");
      if (btnQuitarColor) {
        const id = Number(btnQuitarColor.closest(".bloque-item-body").dataset.id);
        const b = bloques.find((x) => x.id === id);
        if (b) { b[btnQuitarColor.dataset.campo] = ""; actualizarBloqueBody(id); }
        return;
      }
      const btnStepper = e.target.closest(".btn-stepper");
      if (btnStepper) {
        const input = btnStepper.closest(".mini-campo-num").querySelector("input[data-campo-num]");
        if (input) {
          const delta = Number(btnStepper.dataset.delta);
          const min = input.min !== "" ? Number(input.min) : -Infinity;
          const max = input.max !== "" ? Number(input.max) : Infinity;
          const paso = input.step && input.step !== "any" ? Number(input.step) : 1;
          const actual = input.value === "" ? 0 : Number(input.value);
          let nuevo = Math.min(max, Math.max(min, actual + delta * paso));
          nuevo = Math.round(nuevo * 100) / 100; // evita basura de coma flotante (0.1+0.2 etc.)
          input.value = nuevo;
          input.dispatchEvent(new Event("input", { bubbles: true }));
        }
        return;
      }
      const btnAlign = e.target.closest(".btn-align");
      if (btnAlign) {
        const id = Number(btnAlign.closest(".bloque-item-body").dataset.id);
        const b = bloques.find((x) => x.id === id);
        if (b) {
          const campo = btnAlign.dataset.campoValor;
          b[campo] = btnAlign.dataset.valor;
          btnAlign.parentElement.querySelectorAll(".btn-align").forEach((el) => el.classList.toggle("activo", el === btnAlign));
          renderPreview();
        }
        return;
      }
    });

    elLista.addEventListener("input", (e) => {
      const campoHtml = e.target.closest("[data-campo-html]");
      if (campoHtml) {
        const id = Number(campoHtml.closest(".bloque-item-body").dataset.id);
        const b = bloques.find((x) => x.id === id);
        if (b) { b[campoHtml.dataset.campoHtml] = campoHtml.innerHTML; renderPreview(); }
        return;
      }
      const swatch = e.target.closest(".color-swatch");
      if (swatch) {
        const id = Number(swatch.closest(".bloque-item-body").dataset.id);
        const b = bloques.find((x) => x.id === id);
        if (b) {
          b[swatch.dataset.campo] = swatch.value;
          const hexInput = swatch.parentElement.querySelector(".color-hex");
          if (hexInput) hexInput.value = swatch.value;
          renderPreview();
        }
        return;
      }
      const hexInput = e.target.closest(".color-hex");
      if (hexInput) {
        const val = hexInput.value.trim();
        if (/^#[0-9a-fA-F]{6}$/.test(val)) {
          const id = Number(hexInput.closest(".bloque-item-body").dataset.id);
          const b = bloques.find((x) => x.id === id);
          if (b) {
            b[hexInput.dataset.campoHex] = val;
            const swatchPar = hexInput.parentElement.querySelector(".color-swatch");
            if (swatchPar) swatchPar.value = val;
            renderPreview();
          }
        }
        return;
      }
      const campoNum = e.target.closest("[data-campo-num]");
      if (campoNum) {
        const id = Number(campoNum.closest(".bloque-item-body").dataset.id);
        const b = bloques.find((x) => x.id === id);
        if (b) {
          const nombre = campoNum.dataset.campoNum;
          // Campo vacío -> NaN, para que numOr caiga al valor por defecto en
          // vez de tomarlo como 0 (Number("") es 0, no NaN). El 0 escrito a
          // propósito sí se respeta (p.ej. radio 0 = esquinas rectas).
          b[nombre] = campoNum.value === "" ? NaN : Number(campoNum.value);
          // Sincroniza el gemelo (slider <-> número) del mismo campo, si lo hay.
          const contenedorNum = campoNum.closest(".numero-row, .mini-campo-num");
          if (contenedorNum) {
            contenedorNum.querySelectorAll(`[data-campo-num="${nombre}"]`).forEach((el) => {
              if (el !== campoNum) el.value = campoNum.value;
            });
          }
          renderPreview();
        }
        return;
      }
      const campo = e.target.closest("[data-campo]");
      if (campo) {
        const id = Number(campo.closest(".bloque-item-body").dataset.id);
        const b = bloques.find((x) => x.id === id);
        if (b) {
          b[campo.dataset.campo] = campo.value;
          if (campo.dataset.reload) actualizarBloqueBody(id);
          else renderPreview();
        }
      }
    });

    elLista.addEventListener("change", (e) => {
      if (e.target.matches(".input-imagen-bloque")) {
        const file = e.target.files[0];
        if (file) {
          const id = Number(e.target.closest(".bloque-item-body").dataset.id);
          const picker = e.target.closest(".imagen-picker");
          const campoImagenId = picker && picker.dataset.campoImagenId;
          const campoImagenDataUrl = picker && picker.dataset.campoImagenDataurl;
          subirImagenParaBloque(id, file, campoImagenId, campoImagenDataUrl);
        }
        e.target.value = "";
      }
    });

    elLista.addEventListener("dragstart", (e) => {
      const item = e.target.closest(".bloque-item");
      if (!item || item.draggable === false) return;
      arrastrandoId = Number(item.dataset.id);
      e.dataTransfer.effectAllowed = "move";
      item.classList.add("arrastrando");
    });

    elLista.addEventListener("dragover", (e) => {
      if (arrastrandoId == null) return;
      e.preventDefault();
      const item = e.target.closest(".bloque-item");
      if (!item || Number(item.dataset.id) === arrastrandoId) return;
      const rect = item.getBoundingClientRect();
      const antes = e.clientY - rect.top < rect.height / 2;
      elLista.querySelectorAll(".drop-antes,.drop-despues").forEach((el) => el.classList.remove("drop-antes", "drop-despues"));
      item.classList.add(antes ? "drop-antes" : "drop-despues");
    });

    elLista.addEventListener("drop", (e) => {
      if (arrastrandoId == null) return;
      e.preventDefault();
      const item = e.target.closest(".bloque-item");
      if (item) {
        const destinoId = Number(item.dataset.id);
        const antes = item.classList.contains("drop-antes");
        if (destinoId !== arrastrandoId) moverBloqueJunto(arrastrandoId, destinoId, antes);
      }
      arrastrandoId = null;
      render();
    });

    elLista.addEventListener("dragend", () => {
      arrastrandoId = null;
      elLista.querySelectorAll(".drop-antes,.drop-despues,.arrastrando").forEach((el) => el.classList.remove("drop-antes", "drop-despues", "arrastrando"));
    });
  }

  // ------------------------------- API pública -------------------------------

  function init(root) {
    elToolbar = root.querySelector(".builder-toolbar");
    elLista = root.querySelector(".builder-lista");
    elPreview = root.querySelector(".builder-preview-body");
    wireToolbar();
    wireLista();
    render();
  }

  function setPostId(id) {
    postId = id;
  }

  // Qué pares (idCampo, dataUrlCampo) de imagen tiene cada tipo de bloque —
  // la galería tiene 4 fotos independientes, el resto solo 1.
  const CAMPOS_IMAGEN_POR_TIPO = {
    encabezado: [["imagenId", "imagenDataUrl"]],
    imagen: [["imagenId", "imagenDataUrl"]],
    columnas: [["imagenId", "imagenDataUrl"], ["imagenId2", "imagenDataUrl2"]],
    galeria: [["imagenId1", "imagenDataUrl1"], ["imagenId2", "imagenDataUrl2"], ["imagenId3", "imagenDataUrl3"], ["imagenId4", "imagenDataUrl4"]],
  };

  async function precargarImagenes() {
    const tareas = [];
    bloques.forEach((b) => {
      (CAMPOS_IMAGEN_POR_TIPO[b.tipo] || []).forEach(([campoId, campoDataUrl]) => {
        if (!b[campoId] || b[campoDataUrl]) return;
        tareas.push((async () => {
          try {
            const res = await fetch(`${AUTH_API_BASE}/boletines/posts/${postId}/imagenes/${b[campoId]}`);
            if (!res.ok) return;
            const blob = await res.blob();
            b[campoDataUrl] = await blobToDataURL(blob);
          } catch (e) {
            // se queda con el placeholder de "sin imagen", no rompe el builder
          }
        })());
      });
    });
    await Promise.all(tareas);
  }

  async function cargarBloques(jsonStr) {
    let datos = [];
    try {
      datos = jsonStr ? JSON.parse(jsonStr) : [];
    } catch (e) {
      datos = [];
    }
    bloques = Array.isArray(datos) ? datos : [];
    contador = bloques.reduce((max, b) => Math.max(max, b.id || 0), 0) + 1;
    render();
    await precargarImagenes();
    render();
  }

  function cargarComoAvanzado(html) {
    bloques = [{ id: nuevoId(), tipo: "html_avanzado", html: html || "" }];
    render();
  }

  function nuevoVacio() {
    bloques = [];
    render();
  }

  function tieneBloques() {
    return bloques.length > 0;
  }

  // Se quita cualquier campo "imagenDataUrl*" (incluye los imagenDataUrl1..4
  // de la galería) antes de guardar — es solo un caché en memoria de la
  // imagen ya subida (identificada por imagenId), guardarlo también como
  // base64 en la fila de bloques infla el JSON sin necesidad.
  function getBloquesJSON() {
    return JSON.stringify(bloques.map((b) => {
      const limpio = {};
      Object.keys(b).forEach((k) => { if (!/^imagenDataUrl/.test(k)) limpio[k] = b[k]; });
      return limpio;
    }));
  }

  return { init, setPostId, cargarBloques, cargarComoAvanzado, nuevoVacio, tieneBloques, getBloquesJSON, getHtml };
})();

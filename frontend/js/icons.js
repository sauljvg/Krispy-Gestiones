// Sustituye los emojis del texto (est-tico en el HTML o generado por
// cualquier otro script, no hace falta tocar cada uno) por iconos SVG en
// linea -- estilo trazo consistente, 1em (escala con el texto), color
// heredado (currentColor, respeta el tema claro/oscuro sin nada mas).
//
// Como funciona: recorre el DOM al cargar la pagina y envuelve cada emoji
// encontrado en un <span class="icono-svg">; despues, un MutationObserver
// hace lo mismo con cualquier nodo que se añada o cambie mas tarde (listas
// que se repintan, avisos, badges...), asi que ningun script de ninguna
// pagina necesita saber que esto existe.

const ICON_MAP = {
  "★": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="#d99a1b"><path d="M12 2l2.9 6.6 7.1.6-5.4 4.7 1.6 7-6.2-3.8-6.2 3.8 1.6-7L2 9.2l7.1-.6z"/></svg>',
  "⭐": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="#d99a1b"><path d="M12 2l2.9 6.6 7.1.6-5.4 4.7 1.6 7-6.2-3.8-6.2 3.8 1.6-7L2 9.2l7.1-.6z"/></svg>',
  "☆": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="#d99a1b" stroke-width="1.8" stroke-linejoin="round"><path d="M12 2l2.9 6.6 7.1.6-5.4 4.7 1.6 7-6.2-3.8-6.2 3.8 1.6-7L2 9.2l7.1-.6z"/></svg>',
  "✕": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M5 5l14 14M19 5L5 19"/></svg>',
  "✗": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M5 5l14 14M19 5L5 19"/></svg>',
  "❌": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="#d03b3b" stroke-width="2.2" stroke-linecap="round"><circle cx="12" cy="12" r="9" opacity="0.15" fill="#d03b3b" stroke="none"/><path d="M8 8l8 8M16 8l-8 8"/></svg>',
  "🔗": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 13l2-2a3.5 3.5 0 105-5l3-3M16 11l-2 2a3.5 3.5 0 00-5 5l-3 3"/></svg>',
  "🌙": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="currentColor"><path d="M20 14.5A8.5 8.5 0 019.5 4 8.5 8.5 0 1020 14.5z"/></svg>',
  "☀": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4 12H2M22 12h-2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M19.1 4.9l-1.4 1.4M6.3 17.7l-1.4 1.4"/></svg>',
  "☀️": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4 12H2M22 12h-2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M19.1 4.9l-1.4 1.4M6.3 17.7l-1.4 1.4"/></svg>',
  "☰": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 7h16M4 12h16M4 17h16"/></svg>',
  "🗑️": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="#d03b3b" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2m3 0l-1 14a2 2 0 01-2 2H7a2 2 0 01-2-2L4 6h16z"/></svg>',
  "🗑": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="#d03b3b" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2m3 0l-1 14a2 2 0 01-2 2H7a2 2 0 01-2-2L4 6h16z"/></svg>',
  "🍩": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="3.2"/></svg>',
  "🏠": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 11l9-8 9 8"/><path d="M5 10v10a1 1 0 001 1h4v-6h4v6h4a1 1 0 001-1V10"/></svg>',
  "⬇️": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4v16M6 14l6 6 6-6"/></svg>',
  "⬇": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4v16M6 14l6 6 6-6"/></svg>',
  "✓": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M4 12l6 6L20 6"/></svg>',
  "⬆️": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20V4M6 10l6-6 6 6"/></svg>',
  "⬆": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20V4M6 10l6-6 6 6"/></svg>',
  "📊": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20V10M10 20V4M16 20v-7"/></svg>',
  "📄": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2h9l5 5v15a1 1 0 01-1 1H6a1 1 0 01-1-1V3a1 1 0 011-1z"/><path d="M15 2v5h5"/></svg>',
  "📃": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2h9l5 5v15a1 1 0 01-1 1H6a1 1 0 01-1-1V3a1 1 0 011-1z"/><path d="M15 2v5h5"/></svg>',
  "🍃": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20c8 0 14-6 14-14V4h-2C8 4 4 10 4 18z"/><path d="M4 20l7-7"/></svg>',
  "🌿": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20c8 0 14-6 14-14V4h-2C8 4 4 10 4 18z"/><path d="M4 20l7-7"/></svg>',
  "💬": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a8 8 0 01-8 8H7l-4 3 1-5.3A8 8 0 1121 12z"/></svg>',
  "📋": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="4" width="14" height="18" rx="2"/><rect x="9" y="2" width="6" height="4" rx="1"/><path d="M9 12h6M9 16h6"/></svg>',
  "📁": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6a1 1 0 011-1h5l2 2h9a1 1 0 011 1v11a1 1 0 01-1 1H4a1 1 0 01-1-1z"/></svg>',
  "✅": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="#0ca30c" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M8 12l3 3 5-6"/></svg>',
  "📝": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2h9l5 5v15a1 1 0 01-1 1H6a1 1 0 01-1-1V3a1 1 0 011-1z"/><path d="M8 13l6-6 2 2-6 6H8z"/></svg>',
  "🖼️": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="8.5" cy="9.5" r="1.5"/><path d="M21 16l-6-6-9 9"/></svg>',
  "🖼": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="8.5" cy="9.5" r="1.5"/><path d="M21 16l-6-6-9 9"/></svg>',
  "⚠️": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="#c98a12" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l10 18H2z"/><path d="M12 10v4M12 17.5v.1"/></svg>',
  "⚠": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="#c98a12" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l10 18H2z"/><path d="M12 10v4M12 17.5v.1"/></svg>',
  "⏱️": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 2h6"/><path d="M12 2v3"/><circle cx="12" cy="13" r="8"/><path d="M12 9v4l3 2"/></svg>',
  "⏱": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 2h6"/><path d="M12 2v3"/><circle cx="12" cy="13" r="8"/><path d="M12 9v4l3 2"/></svg>',
  "🚫": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="#d03b3b" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M6.5 6.5l11 11"/></svg>',
  "✉️": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="M2 5l10 8 10-8"/></svg>',
  "✉": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="M2 5l10 8 10-8"/></svg>',
  "➕": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M12 4v16M4 12h16"/></svg>',
  "🏢": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="2" width="16" height="20" rx="1"/><path d="M8 6h2M14 6h2M8 10h2M14 10h2M8 14h2M14 14h2M9 22v-4h6v4"/></svg>',
  "⚙️": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 13.5a7.9 7.9 0 000-3l2-1.5-2-3.4-2.3.9a8 8 0 00-2.6-1.5L14 2h-4l-.5 2.4a8 8 0 00-2.6 1.5l-2.3-.9-2 3.4L4.6 10a7.9 7.9 0 000 3l-2 1.5 2 3.4 2.3-.9c.8.7 1.7 1.2 2.6 1.5L10 22h4l.5-2.4a8 8 0 002.6-1.5l2.3.9 2-3.4z"/></svg>',
  "⚙": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 13.5a7.9 7.9 0 000-3l2-1.5-2-3.4-2.3.9a8 8 0 00-2.6-1.5L14 2h-4l-.5 2.4a8 8 0 00-2.6 1.5l-2.3-.9-2 3.4L4.6 10a7.9 7.9 0 000 3l-2 1.5 2 3.4 2.3-.9c.8.7 1.7 1.2 2.6 1.5L10 22h4l.5-2.4a8 8 0 002.6-1.5l2.3.9 2-3.4z"/></svg>',
  "🧑": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="7" r="4"/><path d="M4 21c0-4.4 3.6-8 8-8s8 3.6 8 8"/></svg>',
  "⛶": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 3H5a2 2 0 00-2 2v4M15 3h4a2 2 0 012 2v4M9 21H5a2 2 0 01-2-2v-4M15 21h4a2 2 0 002-2v-4"/></svg>',
  "🟢": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="#0ca30c"><circle cx="12" cy="12" r="7"/></svg>',
  "🗂️": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 8a1 1 0 011-1h4l2-2h5a1 1 0 011 1v2"/><rect x="3" y="8" width="18" height="12" rx="1"/></svg>',
  "🗂": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 8a1 1 0 011-1h4l2-2h5a1 1 0 011 1v2"/><rect x="3" y="8" width="18" height="12" rx="1"/></svg>',
  "📥": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v10M8 9l4 4 4-4"/><path d="M4 15v4a2 2 0 002 2h12a2 2 0 002-2v-4"/></svg>',
  "👤": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="currentColor"><circle cx="12" cy="8" r="4"/><path d="M4 21c0-4.4 3.6-8 8-8s8 3.6 8 8z"/></svg>',
  "📷": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 8h3l2-3h6l2 3h3a1 1 0 011 1v10a1 1 0 01-1 1H4a1 1 0 01-1-1V9a1 1 0 011-1z"/><circle cx="12" cy="13" r="3.5"/></svg>',
  "✎": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 013 3L7 19l-4 1 1-4z"/></svg>',
  "✏️": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 013 3L7 19l-4 1 1-4z"/></svg>',
  "✏": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 013 3L7 19l-4 1 1-4z"/></svg>',
  "🖌️": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9.5 14.5L19 5a2.1 2.1 0 013 3l-9.5 9.5"/><path d="M9 15c0 2-2 2-2 4-2 0-3-1-3-3 0-2 2-2 2-4z"/></svg>',
  "🖌": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9.5 14.5L19 5a2.1 2.1 0 013 3l-9.5 9.5"/><path d="M9 15c0 2-2 2-2 4-2 0-3-1-3-3 0-2 2-2 2-4z"/></svg>',
  "🏷️": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 11l8-8h6a2 2 0 012 2v6l-8 8a1 1 0 01-1.4 0l-6.6-6.6a1 1 0 010-1.4z"/><circle cx="14.5" cy="7.5" r="1.3" fill="currentColor" stroke="none"/></svg>',
  "🏷": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 11l8-8h6a2 2 0 012 2v6l-8 8a1 1 0 01-1.4 0l-6.6-6.6a1 1 0 010-1.4z"/><circle cx="14.5" cy="7.5" r="1.3" fill="currentColor" stroke="none"/></svg>',
  "🔠": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 5h16M12 5v14"/></svg>',
  "📣": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 10v4h4l6 4V6l-6 4z"/><path d="M17 9a4 4 0 010 6"/></svg>',
  "🎬": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 8l1.5-4h14L20 8"/><rect x="3" y="8" width="18" height="12" rx="1"/><path d="M6 8l1-4M11 8l1-4M16 8l1-4"/></svg>',
  "🔘": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="3.5" fill="currentColor" stroke="none"/></svg>',
  "➖": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M4 12h16"/></svg>',
  "🔔": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 10a6 6 0 0112 0c0 5 2 6 2 6H4s2-1 2-6z"/><path d="M10.5 20a1.5 1.5 0 003 0"/></svg>',
  "🚪": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="2" width="14" height="20" rx="1"/><circle cx="15" cy="12" r="1" fill="currentColor" stroke="none"/></svg>',
  "🖱️": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3a6 6 0 00-6 6v6a6 6 0 0012 0V9a6 6 0 00-6-6z"/><path d="M12 3v6"/></svg>',
  "🖱": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3a6 6 0 00-6 6v6a6 6 0 0012 0V9a6 6 0 00-6-6z"/><path d="M12 3v6"/></svg>',
  "⌨️": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="6" width="20" height="13" rx="2"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M6 14h.01M18 14h.01M9 14h6"/></svg>',
  "⌨": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="6" width="20" height="13" rx="2"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M6 14h.01M18 14h.01M9 14h6"/></svg>',
  "👀": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6-10-6-10-6z"/><circle cx="12" cy="12" r="3"/></svg>',
  "🎯": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.3" fill="currentColor" stroke="none"/></svg>',
  "⭕": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/></svg>',
  "📘": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 5.5A2.5 2.5 0 016.5 3H20v16H6.5A2.5 2.5 0 004 21z"/><path d="M4 5.5v15.5"/><path d="M8 8h8M8 12h6"/></svg>',
  "📈": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 17l6-6 4 4 8-8"/><path d="M15 6h6v6"/></svg>',
  "🤝": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 13l5-5 4 3 2-1 4 4M9 15l3 3 6-6"/></svg>',
  "✨": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="currentColor"><path d="M12 2l1.8 5.2L19 9l-5.2 1.8L12 16l-1.8-5.2L5 9l5.2-1.8z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/></svg>',
  "🔎": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="10" cy="10" r="7"/><path d="M21 21l-6-6"/></svg>',
  "👥": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="8" r="3.2"/><path d="M2.5 20c0-3.6 2.9-6.5 6.5-6.5s6.5 2.9 6.5 6.5"/><circle cx="17.5" cy="9" r="2.6"/><path d="M15.5 13.2a5.2 5.2 0 016 5"/></svg>',
  "🗄️": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="2" width="16" height="20" rx="1"/><path d="M4 12h16M9 7h1M9 17h1"/></svg>',
  "🗄": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="2" width="16" height="20" rx="1"/><path d="M4 12h16M9 7h1M9 17h1"/></svg>',
  "👉": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 12h16M14 6l6 6-6 6"/></svg>',
  "👉🏽": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 12h16M14 6l6 6-6 6"/></svg>',
  "🤖": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="8" width="16" height="12" rx="2"/><path d="M12 4v4M9 13v2M15 13v2"/><path d="M2 12h2M20 12h2"/></svg>',
  "🔁": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 2l4 4-4 4"/><path d="M3 12v-2a4 4 0 014-4h14M7 22l-4-4 4-4"/><path d="M21 12v2a4 4 0 01-4 4H3"/></svg>',
  "🚀": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2c3 2 5 6 5 10 0 2-1 4-2 5l-3 3-3-3c-1-1-2-3-2-5 0-4 2-8 5-10z"/><path d="M9 15l-3 1 1-3M15 15l3 1-1-3"/><circle cx="12" cy="10" r="1.5" fill="currentColor" stroke="none"/></svg>',
  "🧭": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M15 9l-2 6-6 2 2-6z"/></svg>',
  "🛵": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="6" cy="18" r="2.5"/><circle cx="18" cy="18" r="2.5"/><path d="M6 18h6l2-6h4M12 12l-2-5H8"/></svg>',
  "📰": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 4h13a2 2 0 012 2v13a1 1 0 01-1 1H6a2 2 0 01-2-2z"/><path d="M4 4v14M8 8h6M8 12h6M8 16h4"/></svg>',
  "⚏": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="1"/><path d="M9 4v16M15 4v16"/></svg>',
  "❔": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 114 2c-.8.6-1.5 1.1-1.5 2.3"/><path d="M12 17v.1"/></svg>',
  "💻": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="12" rx="1"/><path d="M8 20h8M12 16v4"/></svg>',
  "⬅️": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 12H4M10 6l-6 6 6 6"/></svg>',
  "⬅": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 12H4M10 6l-6 6 6 6"/></svg>',
  "➡️": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 12h16M14 6l6 6-6 6"/></svg>',
  "➡": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 12h16M14 6l6 6-6 6"/></svg>',
  "🏬": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9l3-5h12l3 5"/><path d="M4 9v11a1 1 0 001 1h14a1 1 0 001-1V9"/><path d="M10 21v-6h4v6"/></svg>',
  "🏭": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 21V11l5 3v-3l5 3V8l5 4v9z"/><path d="M3 21h18"/></svg>',
  "☑️": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M8 12l3 3 5-6"/></svg>',
  "☑": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M8 12l3 3 5-6"/></svg>',
  "📤": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 13V3M8 7l4-4 4 4"/><path d="M4 15v4a2 2 0 002 2h12a2 2 0 002-2v-4"/></svg>',
  "🎓": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 9l10-4 10 4-10 4z"/><path d="M6 11v5c0 1.5 2.7 3 6 3s6-1.5 6-3v-5"/><path d="M22 9v6"/></svg>',
  "💼": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="7" width="20" height="13" rx="2"/><path d="M8 7V5a2 2 0 012-2h4a2 2 0 012 2v2M2 12h20"/></svg>',
  "🔄": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 01-15.5 6.3M3 12a9 9 0 0115.5-6.3"/><path d="M3 17v-5h5M21 7v5h-5"/></svg>',
  "📎": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8l-8.5 8.5a3 3 0 004.2 4.2L21 13a5 5 0 00-7-7l-8 8a4 4 0 005.6 5.6"/></svg>',
  "🕒": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
  "🔑": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="8" cy="15" r="4"/><path d="M11 12l9-9M17 6l3 3M14 9l2 2"/></svg>',
  "♻️": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 12a8 8 0 0113-6M20 12a8 8 0 01-13 6"/><path d="M17 3v4h-4M7 21v-4h4"/></svg>',
  "♻": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 12a8 8 0 0113-6M20 12a8 8 0 01-13 6"/><path d="M17 3v4h-4M7 21v-4h4"/></svg>',
  "➤": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="currentColor"><path d="M5 4l14 8-14 8z"/></svg>',
  // No son emoji técnicamente (son símbolos Unicode de flechas/formas
  // geométricas), pero se usan igual como iconos sueltos en botones --
  // mismo criterio de sustituirlos por SVG.
  "←": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 12H4M10 6l-6 6 6 6"/></svg>',
  "→": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 12h16M14 6l6 6-6 6"/></svg>',
  "↑": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20V4M6 10l6-6 6 6"/></svg>',
  "↓": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4v16M6 14l6 6 6-6"/></svg>',
  "↔": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12h18M7 6l-4 6 4 6M17 6l4 6-4 6"/></svg>',
  "↕️": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v18M6 7l6-4 6 4M6 17l6 4 6-4"/></svg>',
  "↗": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 17L17 7M9 7h8v8"/></svg>',
  "↺": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 3v5h5"/></svg>',
  "▸": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="currentColor"><path d="M8 5l10 7-10 7z"/></svg>',
  "▲": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="currentColor"><path d="M12 6l8 12H4z"/></svg>',
  "▼": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="currentColor"><path d="M12 18L4 6h16z"/></svg>',
  "▾": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="currentColor"><path d="M12 16L6 8h12z"/></svg>',
  "●": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="currentColor"><circle cx="12" cy="12" r="7"/></svg>',
  "−": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M4 12h16"/></svg>',
  "▥": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="1"/><path d="M12 4v16"/></svg>',
  "ⓘ": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 11v5.5M12 7.5v.1"/></svg>',
  "⏳": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2h12M6 22h12"/><path d="M8 2c0 5 3 6 4 7 1-1 4-2 4-7M8 22c0-5 3-6 4-7 1 1 4 2 4 7"/></svg>',
  "⏸": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="currentColor"><rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/></svg>',
  "🧑‍🤝‍🧑": '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="8" r="3.2"/><path d="M2.5 20c0-3.6 2.9-6.5 6.5-6.5s6.5 2.9 6.5 6.5"/><circle cx="17.5" cy="9" r="2.6"/><path d="M15.5 13.2a5.2 5.2 0 016 5"/></svg>',
};

// Orden por longitud descendente -- para que "👉🏽" (secuencia de dos
// codepoints) se reconozca entera antes que el "👉" suelto que también
// está en el mapa.
const EMOJI_KEYS = Object.keys(ICON_MAP).sort((a, b) => b.length - a.length);
const EMOJI_REGEX = new RegExp(EMOJI_KEYS.map((k) => k.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|"), "g");

function reemplazarEmojisEnNodo(nodo) {
  if (!nodo) return;
  if (nodo.nodeType === Node.TEXT_NODE) {
    const texto = nodo.textContent;
    if (!texto || !EMOJI_REGEX.test(texto)) return;
    EMOJI_REGEX.lastIndex = 0;
    if (!nodo.parentNode) return;
    const frag = document.createDocumentFragment();
    let ultimo = 0;
    let match;
    while ((match = EMOJI_REGEX.exec(texto))) {
      if (match.index > ultimo) frag.appendChild(document.createTextNode(texto.slice(ultimo, match.index)));
      const span = document.createElement("span");
      span.className = "icono-svg";
      span.innerHTML = ICON_MAP[match[0]];
      frag.appendChild(span);
      ultimo = match.index + match[0].length;
    }
    if (ultimo < texto.length) frag.appendChild(document.createTextNode(texto.slice(ultimo)));
    nodo.replaceWith(frag);
    return;
  }
  if (nodo.nodeType !== Node.ELEMENT_NODE) return;
  const tag = nodo.tagName;
  if (tag === "SCRIPT" || tag === "STYLE" || tag === "TEXTAREA" || tag === "INPUT" || tag === "SELECT" || tag === "OPTION") return;
  if (nodo.classList && nodo.classList.contains("icono-svg")) return;
  Array.from(nodo.childNodes).forEach(reemplazarEmojisEnNodo);
}

document.addEventListener("DOMContentLoaded", () => {
  reemplazarEmojisEnNodo(document.body);
  const observer = new MutationObserver((mutations) => {
    for (const m of mutations) {
      if (m.type === "childList") {
        m.addedNodes.forEach((n) => reemplazarEmojisEnNodo(n));
      } else if (m.type === "characterData") {
        reemplazarEmojisEnNodo(m.target);
      }
    }
  });
  observer.observe(document.body, { childList: true, subtree: true, characterData: true });
});

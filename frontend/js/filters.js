// Mismo origen que sirve el HTML (el backend FastAPI monta el frontend como
// estático), así funciona igual en local y una vez desplegado.
const API_BASE = `${window.location.origin}/api`;

const state = {
  page: 1,
  pageSize: 10,
  tienda: "",
  rating: "",
  sentiment: "",
  dateFrom: "",
  dateTo: "",
  q: "",
  staff: "",
  hora: "",
  diaSemana: "",
  sort: "recientes",
};

function currentQueryParams(extra = {}) {
  const params = new URLSearchParams();
  if (state.tienda) params.set("tienda", state.tienda);
  if (state.rating) params.set("rating", state.rating);
  if (state.sentiment) params.set("sentiment", state.sentiment);
  if (state.dateFrom) params.set("date_from", state.dateFrom);
  if (state.dateTo) params.set("date_to", state.dateTo);
  if (state.q) params.set("q", state.q);
  if (state.staff) params.set("staff", state.staff);
  if (state.hora !== "") params.set("hora", state.hora);
  if (state.diaSemana) params.set("dia_semana", state.diaSemana);
  Object.entries(extra).forEach(([k, v]) => params.set(k, v));
  return params;
}

// onAggregateChange: se dispara cuando cambia un filtro que afecta a las
// estadísticas/gráficos (estrellas, sentimiento, fechas, búsqueda) — hay que
// refrescar stats+timeline+keywords+reviews.
// onSortChange: se dispara solo con el orden, que no afecta a los agregados.
function wireFilters(onAggregateChange, onSortChange) {
  const tiendaEl = document.getElementById("filter-tienda");
  const ratingEl = document.getElementById("filter-rating");
  const sentimentEl = document.getElementById("filter-sentiment");
  const dateFromEl = document.getElementById("filter-date-from");
  const dateToEl = document.getElementById("filter-date-to");
  const searchEl = document.getElementById("filter-search");
  const sortEl = document.getElementById("filter-sort");

  const applyAggregate = () => {
    state.page = 1;
    state.tienda = tiendaEl.value;
    state.rating = ratingEl.value;
    state.sentiment = sentimentEl.value;
    state.dateFrom = dateFromEl.value;
    state.dateTo = dateToEl.value;
    onAggregateChange();
  };

  tiendaEl.addEventListener("change", () => {
    // Un nombre de personal solo tiene sentido dentro de la tienda en la que
    // se seleccionó (el mismo nombre de pila puede ser otra persona en otro
    // local), así que se limpia al cambiar de tienda.
    state.staff = "";
    applyAggregate();
  });
  ratingEl.addEventListener("change", applyAggregate);
  sentimentEl.addEventListener("change", applyAggregate);
  dateFromEl.addEventListener("change", applyAggregate);
  dateToEl.addEventListener("change", applyAggregate);

  sortEl.addEventListener("change", () => {
    state.page = 1;
    state.sort = sortEl.value;
    onSortChange();
  });

  let debounceTimer;
  searchEl.addEventListener("input", () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      state.page = 1;
      state.q = searchEl.value.trim();
      onAggregateChange();
    }, 350);
  });
}

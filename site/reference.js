(function () {
  "use strict";

  var STORAGE_KEY = "refCompareFilters";
  var THEME_KEY = "carCompareTheme";
  var COL_STATE_KEY = "refCompareColState";
  var THRESHOLD_KEY = "refCompareThresholds";   // isolated: reference has its own numeric columns
  var HEATMODE_KEY = "carCompareHeatMode";       // shared with index (global appearance pref)

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    var glyph = document.querySelector("#btn-theme .theme-glyph");
    if (glyph) glyph.textContent = theme === "dark" ? "\u263E" : "\u2600";
    var gridEl = document.getElementById("grid");
    if (gridEl) {
      gridEl.classList.remove("ag-theme-alpine", "ag-theme-alpine-dark");
      gridEl.classList.add(theme === "dark" ? "ag-theme-alpine-dark" : "ag-theme-alpine");
    }
    if (gridApi) gridApi.refreshCells({ force: true });
  }

  window.toggleTheme = function () {
    var current = document.documentElement.getAttribute("data-theme") || "dark";
    var next = current === "dark" ? "light" : "dark";
    applyTheme(next);
    try { localStorage.setItem(THEME_KEY, next); } catch (_) {}
  };

  (function initTheme() {
    var saved = null;
    try { saved = localStorage.getItem(THEME_KEY); } catch (_) {}
    applyTheme(saved || "dark");
  })();

  // Custom multi-select set filter (same as main app)
  function SetFilter() {}

  SetFilter.prototype.init = function (params) {
    this.params = params;
    this.field = params.colDef.field;
    this.filterActive = false;
    this.selected = null;

    var valuesMap = {};
    var hasBlank = false;
    params.api.forEachNode(function (node) {
      if (!node.data) return;
      var val = node.data[params.colDef.field];
      if (val == null || val === "") hasBlank = true;
      else valuesMap[val] = true;
    });
    this.uniqueValues = Object.keys(valuesMap).sort(function (a, b) {
      return a.localeCompare(b, "cs");
    });
    this.hasBlank = hasBlank;

    this.gui = document.createElement("div");
    this.gui.className = "set-filter";

    var searchInput = document.createElement("input");
    searchInput.type = "text";
    searchInput.placeholder = "Hledat\u2026";
    searchInput.className = "set-filter-search";
    this.searchInput = searchInput;
    this.gui.appendChild(searchInput);

    var btnDiv = document.createElement("div");
    btnDiv.className = "set-filter-btns";
    var btnAll = document.createElement("button");
    btnAll.textContent = "V\u0161e";
    btnAll.className = "set-filter-btn";
    var btnNone = document.createElement("button");
    btnNone.textContent = "Nic";
    btnNone.className = "set-filter-btn";
    btnDiv.appendChild(btnAll);
    btnDiv.appendChild(btnNone);
    this.gui.appendChild(btnDiv);

    var listDiv = document.createElement("div");
    listDiv.className = "set-filter-list";
    this.listDiv = listDiv;
    this.checkboxes = [];

    if (this.hasBlank) {
      var blankItem = this._makeItem("(Pr\u00e1zdn\u00e9)", null, true);
      listDiv.appendChild(blankItem.div);
      this.checkboxes.push(blankItem);
    }
    for (var i = 0; i < this.uniqueValues.length; i++) {
      var item = this._makeItem(this.uniqueValues[i], this.uniqueValues[i], true);
      listDiv.appendChild(item.div);
      this.checkboxes.push(item);
    }
    this.gui.appendChild(listDiv);

    var self = this;
    searchInput.addEventListener("input", function () { self._filter(); });
    btnAll.addEventListener("click", function () { self._toggleAll(true); });
    btnNone.addEventListener("click", function () { self._toggleAll(false); });
  };

  SetFilter.prototype._makeItem = function (label, value, checked) {
    var div = document.createElement("label");
    div.className = "set-filter-item";
    var cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = checked;
    var span = document.createElement("span");
    span.textContent = label;
    div.appendChild(cb);
    div.appendChild(span);
    var self = this;
    cb.addEventListener("change", function () { self._apply(); });
    return { div: div, cb: cb, value: value, label: label };
  };

  SetFilter.prototype._filter = function () {
    var q = this.searchInput.value.toLowerCase();
    for (var i = 0; i < this.checkboxes.length; i++) {
      var item = this.checkboxes[i];
      item.div.style.display = (!q || item.label.toLowerCase().indexOf(q) >= 0) ? "" : "none";
    }
  };

  SetFilter.prototype._toggleAll = function (on) {
    for (var i = 0; i < this.checkboxes.length; i++) {
      if (this.checkboxes[i].div.style.display !== "none") {
        this.checkboxes[i].cb.checked = on;
      }
    }
    this._apply();
  };

  SetFilter.prototype._apply = function () {
    var allOn = true;
    for (var i = 0; i < this.checkboxes.length; i++) {
      if (!this.checkboxes[i].cb.checked) { allOn = false; break; }
    }
    if (allOn) {
      this.selected = null;
      this.filterActive = false;
    } else {
      this.selected = new Set();
      for (var i = 0; i < this.checkboxes.length; i++) {
        if (this.checkboxes[i].cb.checked) this.selected.add(this.checkboxes[i].value);
      }
      this.filterActive = true;
    }
    this.params.filterChangedCallback();
  };

  SetFilter.prototype.doesFilterPass = function (params) {
    if (!this.filterActive) return true;
    var val = params.data[this.field];
    if (val == null || val === "") return this.selected.has(null);
    return this.selected.has(val);
  };

  SetFilter.prototype.isFilterActive = function () { return this.filterActive; };

  SetFilter.prototype.getModel = function () {
    if (!this.filterActive || !this.selected) return null;
    return { filterType: "set", values: Array.from(this.selected) };
  };

  SetFilter.prototype.setModel = function (model) {
    if (!model || !model.values) {
      this.selected = null;
      this.filterActive = false;
      for (var i = 0; i < this.checkboxes.length; i++) this.checkboxes[i].cb.checked = true;
    } else {
      this.selected = new Set(model.values);
      this.filterActive = true;
      for (var i = 0; i < this.checkboxes.length; i++) {
        this.checkboxes[i].cb.checked = this.selected.has(this.checkboxes[i].value);
      }
    }
  };

  SetFilter.prototype.getGui = function () { return this.gui; };
  SetFilter.prototype.destroy = function () {};

  function ColTooltip() {}
  ColTooltip.prototype.init = function (params) {
    this.eGui = document.createElement("div");
    this.eGui.className = "col-tooltip";
    this.eGui.textContent = params.value;
  };
  ColTooltip.prototype.getGui = function () { return this.eGui; };
  ColTooltip.prototype.destroy = function () {};

  SetFilter.prototype.getModelAsString = function () {
    if (!this.filterActive || !this.selected) return "";
    var vals = Array.from(this.selected).map(function (v) { return v == null ? "(Prázdné)" : v; });
    return vals.join(", ");
  };

  var gridApi = null;
  var colRanges = {};
  var totalRowCount = 0;
  var userThresholds = {};

  // ── Missing-spec indicator (#19) ──
  // Flags reference rows missing "key" curated spec columns — the ones a human
  // fills in by hand (Spotřeba, Objem motoru, Cd, …), not columns aggregated
  // from live listings (Karoserie, Výkon), which are legitimately blank for a
  // reference model with no current matches. Purely a presentation layer: no
  // external data is sourced, this only surfaces gaps that already exist.
  var ICE_KEY_SPECS = [
    {
      field: "Spotřeba (l/100 km)", label: "Spotřeba",
      // PHEV combined consumption is intentionally blanked at build time
      // (docs/gotchas.md: WLTP weighted figure is misleading) — not a gap.
      skip: function (row) { return row["Hybrid typ"] === "PHEV"; },
    },
    { field: "Objem motoru", label: "Objem motoru" },
    { field: "Typ motoru", label: "Typ motoru" },
    { field: "Cd", label: "Odpor vzduchu (Cd)" },
    { field: "Hlučnost (dB)", label: "Hlučnost" },
  ];
  var EV_KEY_SPECS = [
    { field: "Kapacita baterie (kWh)", label: "Kapacita baterie" },
    { field: "Dojezd WLTP (km)", label: "Dojezd WLTP" },
    { field: "Dojezd EV-database (km)", label: "Dojezd EV-database" },
    { field: "Cd", label: "Odpor vzduchu (Cd)" },
  ];

  function isBlankSpec(v) {
    return v == null || v === "";
  }

  function computeMissingSpecs(row) {
    var specs = row["Typ"] === "Elektrické" ? EV_KEY_SPECS : ICE_KEY_SPECS;
    var missing = [];
    for (var i = 0; i < specs.length; i++) {
      var spec = specs[i];
      if (spec.skip && spec.skip(row)) continue;
      if (isBlankSpec(row[spec.field])) missing.push(spec.label);
    }
    return missing;
  }

  function missingBadgeRenderer(params) {
    var count = params.value;
    if (!count) return "";
    return '<span class="missing-badge">⚠ ' + count + "</span>";
  }

  function missingTooltipValueGetter(params) {
    var missing = params.data && params.data._missing;
    return missing && missing.length ? "Chybí: " + missing.join(", ") : undefined;
  }

  var incompleteOnly = false;
  var incompleteCount = 0;

  function updateIncompleteButton() {
    var btn = document.getElementById("btn-incomplete");
    if (!btn) return;
    btn.textContent = "Neúplné: " + incompleteCount + " / " + totalRowCount;
    btn.classList.toggle("active", incompleteOnly);
  }

  window.toggleIncomplete = function () {
    incompleteOnly = !incompleteOnly;
    updateIncompleteButton();
    if (gridApi) gridApi.onFilterChanged();
    updateRowCount();
  };

  // Shared columns follow the main grid's order (site/app.js COL_CONFIG) for
  // easier visual scanning between the two pages; reference-only columns
  // (Tepelné čerpadlo možné) go after, keeping their prior relative order.
  var COL_DEFS = [
    {
      field: "_missingCount", headerName: "", width: 50, minWidth: 50, maxWidth: 60,
      resizable: false, filter: false, sortable: true, suppressMovable: false,
      cellClass: "missing-badge-cell",
      cellRenderer: missingBadgeRenderer,
      tooltipValueGetter: missingTooltipValueGetter,
      headerTooltip: "Počet chybějících klíčových údajů (najeďte myší na ikonu pro seznam)",
    },
    { field: "Model auta", filter: "agTextColumnFilter", width: 280 },
    { field: "Verze", filter: SetFilter, width: 110, headerClass: "ag-header-cell-center", headerTooltip: "Verze/výbava dle referenčního záznamu. Prázdné, pokud pro tento model není určena." },
    { field: "Typ", filter: SetFilter, width: 100, headerClass: "ag-header-cell-center" },
    { field: "Palivo", filter: SetFilter, width: 100, headerClass: "ag-header-cell-center" },
    { field: "Spotřeba (l/100 km)", filter: "agNumberColumnFilter", width: 120, type: "numericColumn", headerTooltip: "Průměrná spotřeba dle WLTP. V praxi bývá o 10–20 % vyšší.\nU plug-in hybridů (PHEV) je prázdná: oficiální WLTP hodnota (~1 l/100 km) předpokládá nabitou baterii a je zavádějící.\nBarva buňky: zelená = nižší spotřeba, červená = vyšší." },
    { field: "Objem kufru (l)", filter: "agNumberColumnFilter", width: 110, type: "numericColumn", headerTooltip: "Barva buňky: zelená = větší kufr, červená = menší." },
    { field: "Výkon (kW)", filter: "agNumberColumnFilter", width: 100, type: "numericColumn", headerTooltip: "Barva buňky: zelená = vyšší výkon, červená = nižší." },
    { field: "Objem motoru", filter: "agNumberColumnFilter", width: 110, type: "numericColumn", headerTooltip: "Zdvihový objem spalovacího motoru v litrech." },
    { field: "Typ motoru", filter: SetFilter, width: 110, headerClass: "ag-header-cell-center" },
    { field: "Hybrid typ", filter: SetFilter, width: 110, headerClass: "ag-header-cell-center", headerTooltip: "MHEV = mild hybrid (rekuperace, bez čistě EV jízdy), HEV = plný hybrid (krátkodobě EV jízda), PHEV = plug-in hybrid (nabíjecí ze zásuvky)." },
    { field: "Karoserie", filter: SetFilter, width: 120, headerClass: "ag-header-cell-center" },
    { field: "Cd", filter: "agNumberColumnFilter", width: 90, type: "numericColumn", headerName: "Odpor vzduchu (%)", headerTooltip: "Nižší = lepší aerodynamika.\nBarva buňky: zelená = nižší (lepší), červená = vyšší." },
    { field: "Cd zdroj", filter: SetFilter, width: 120, headerClass: "ag-header-cell-center", headerName: "Zdroj odporu vzduchu", headerTooltip: "reálné = naměřená hodnota (výrobce / Wikipedia / ev-database), odhad = odhad dle tvaru karoserie (~42 % hodnot)." },
    { field: "Hlučnost (dB)", filter: "agNumberColumnFilter", width: 100, type: "numericColumn", headerTooltip: "Hlučnost kabiny dle WLTP. Nižší = tišší.\n< 65 dB výborné, 65–70 dB dobré, > 70 dB hlučné.\nPrůměrné auto při 120 km/h: cca 68–72 dB.\nBarva buňky: zelená = tišší, červená = hlučnější." },
    { field: "Kapacita baterie (kWh)", filter: "agNumberColumnFilter", width: 130, type: "numericColumn", headerTooltip: "Použitelná kapacita trakční baterie.\nBarva buňky: zelená = větší kapacita, červená = menší." },
    { field: "Dojezd WLTP (km)", filter: "agNumberColumnFilter", width: 120, type: "numericColumn", headerTooltip: "WLTP – standardizovaný laboratorní test (cyklus 0–131 km/h, teplota 23 °C). Výsledky bývají optimistické; reálný dojezd o 10–30 % nižší.\nBarva buňky: zelená = delší dojezd, červená = kratší." },
    { field: "Dojezd EV-database (km)", filter: "agNumberColumnFilter", width: 140, type: "numericColumn", headerTooltip: "Reálný dojezd dle ev-database.com – realističtější než WLTP.\nBarva buňky: zelená = delší dojezd, červená = kratší." },
    { field: "Tepelné čerpadlo možné", filter: SetFilter, width: 130, headerClass: "ag-header-cell-center", headerTooltip: "Lze doobjednat tepelné čerpadlo jako příplatek." },
  ];

  // Single-line header names for the filter-chips bar.
  var CHIP_HEADER_NAMES = {};
  for (var chi = 0; chi < COL_DEFS.length; chi++) {
    var chcfg = COL_DEFS[chi];
    CHIP_HEADER_NAMES[chcfg.field] = (chcfg.headerName || chcfg.field).replace(/\n/g, " ");
  }

  // Map numeric column fields to whether higher is better (true) or lower is better (false)
  var NUMERIC_COLS = {
    "Výkon (kW)": true,
    "Spotřeba (l/100 km)": false,
    "Objem kufru (l)": true,
    "Hlučnost (dB)": false,
    "Kapacita baterie (kWh)": true,
    "Dojezd WLTP (km)": true,
    "Dojezd EV-database (km)": true,
    "Cd": false,
  };

  // ── Heat-map colouring: user-selectable palette × style, theme-aware (mirrors
  //    site/app.js). Default soft red-green full-cell; switchable in the drawer. ──
  var HEAT_PALETTES = {
    redgreen:   { good: [46, 160, 60],  bad: [205, 55, 55],  label: "Červená–zelená" },
    bluered:    { good: [47, 111, 176], bad: [214, 69, 69],  label: "Modrá–červená" },
    blueorange: { good: [47, 111, 176], bad: [224, 138, 46], label: "Modrá–oranžová" },
    tealamber:  { good: [45, 196, 182], bad: [224, 135, 46], label: "Tyrkys–jantar" },
  };
  var HEAT_STYLES = { fullcell: "Plná buňka", databar: "Datové pruhy", combo: "Pruh + tón" };
  var heatMode = { palette: "redgreen", style: "combo" };

  function loadHeatMode() {
    try {
      var s = JSON.parse(localStorage.getItem(HEATMODE_KEY));
      if (s && HEAT_PALETTES[s.palette] && HEAT_STYLES[s.style]) heatMode = { palette: s.palette, style: s.style };
    } catch (_) {}
  }

  window.getHeatMode = function () { return { palette: heatMode.palette, style: heatMode.style }; };
  window.setHeatMode = function (palette, style) {
    if (HEAT_PALETTES[palette]) heatMode.palette = palette;
    if (HEAT_STYLES[style]) heatMode.style = style;
    try { localStorage.setItem(HEATMODE_KEY, JSON.stringify(heatMode)); } catch (_) {}
    if (gridApi) gridApi.refreshCells({ force: true });
    renderHeatModeChoices();
    updateThresholdGradients();
  };

  function isDarkTheme() {
    return (document.documentElement.getAttribute("data-theme") || "dark") === "dark";
  }

  function lerp3(a, b, u) {
    return [Math.round(a[0] + (b[0] - a[0]) * u),
            Math.round(a[1] + (b[1] - a[1]) * u),
            Math.round(a[2] + (b[2] - a[2]) * u)];
  }

  function heatRGBof(paletteKey, t) {
    var pal = HEAT_PALETTES[paletteKey] || HEAT_PALETTES.redgreen;
    var mid = isDarkTheme() ? [71, 85, 105] : [148, 163, 184];
    var c = t < 0.5 ? lerp3(pal.good, mid, t * 2) : lerp3(mid, pal.bad, (t - 0.5) * 2);
    return c[0] + "," + c[1] + "," + c[2];
  }

  function heatRGB(t) { return heatRGBof(heatMode.palette, t); }

  function heatGradientCSS(paletteKey, greenHigh) {
    var lo = greenHigh ? 1 : 0, hi = greenHigh ? 0 : 1;
    return "linear-gradient(90deg,rgb(" + heatRGBof(paletteKey, lo) + "),rgb(" +
      heatRGBof(paletteKey, 0.5) + "),rgb(" + heatRGBof(paletteKey, hi) + "))";
  }

  function heatBackground(t, pos) {
    var dark = isDarkTheme();
    var rgb = heatRGB(t);
    var pct = Math.round(Math.max(0, Math.min(1, pos)) * 100);
    if (heatMode.style === "fullcell") {
      return { backgroundColor: "rgba(" + rgb + "," + (dark ? 0.5 : 0.32) + ")" };
    }
    if (heatMode.style === "databar") {
      var a = dark ? 0.82 : 0.55;
      return { background: "linear-gradient(90deg, rgba(" + rgb + "," + a + ") 0, rgba(" + rgb + "," + a + ") " + pct + "%, transparent " + pct + "%, transparent 100%)" };
    }
    var barA = dark ? 0.8 : 0.5;
    var tintA = dark ? 0.18 : 0.12;
    return { background: "linear-gradient(90deg, rgba(" + rgb + "," + barA + ") 0, rgba(" + rgb + "," + barA + ") " + pct + "%, rgba(" + rgb + "," + tintA + ") " + pct + "%, rgba(" + rgb + "," + tintA + ") 100%)" };
  }

  function numericCellStyle(field) {
    return function (params) {
      var style = { textAlign: "center" };
      if (params.value == null) return style;
      var greenHigh = NUMERIC_COLS[field];
      var th = userThresholds[field] || {};
      var range = colRanges[field] || {};
      var min = th.min != null ? th.min : range.min;
      var max = th.max != null ? th.max : range.max;
      if (min == null || max == null || min === max) return style;
      var pos = (params.value - min) / (max - min);
      pos = Math.max(0, Math.min(1, pos));
      var t = greenHigh ? (1 - pos) : pos;
      var bg = heatBackground(t, pos);
      if (bg.backgroundColor) style.backgroundColor = bg.backgroundColor;
      if (bg.background) style.background = bg.background;
      return style;
    };
  }

  function computeRanges(data) {
    colRanges = {};
    var fields = Object.keys(NUMERIC_COLS);
    for (var i = 0; i < fields.length; i++) {
      var field = fields[i];
      var min = Infinity, max = -Infinity;
      for (var j = 0; j < data.length; j++) {
        var v = data[j][field];
        if (v != null && typeof v === "number" && isFinite(v)) {
          if (v < min) min = v;
          if (v > max) max = v;
        }
      }
      if (min !== Infinity) colRanges[field] = { min: min, max: max };
    }
  }

  // ── Row count ──

  function updateRowCount() {
    var displayed = 0;
    if (gridApi) {
      gridApi.forEachNodeAfterFilter(function () { displayed++; });
    }
    var el = document.getElementById("row-count");
    if (el) {
      if (displayed < totalRowCount) {
        el.textContent = "Vyfiltrováno " + displayed + " / " + totalRowCount + " záznamů";
      } else {
        el.textContent = totalRowCount + " záznamů";
      }
    }
  }

  // ── State persistence — filters in the URL fragment (#f=, shared codec in
  //    site/url-state.js), column layout in localStorage only (never the URL). ──
  var U = window.UrlState;

  function saveFiltersToStorage(model) {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(model)); } catch (_) {}
  }

  function loadFiltersFromStorage() {
    try {
      var s = localStorage.getItem(STORAGE_KEY);
      return s ? JSON.parse(s) : null;
    } catch (_) { return null; }
  }

  function writeHash() {
    U.writeHash({ filters: gridApi ? gridApi.getFilterModel() : null });
  }

  function persistColState() {
    if (!gridApi) return;
    try { localStorage.setItem(COL_STATE_KEY, JSON.stringify(gridApi.getColumnState())); } catch (_) {}
  }

  function loadColStateFromStorage() {
    try {
      var s = localStorage.getItem(COL_STATE_KEY);
      if (!s) return null;
      var v = JSON.parse(s);
      if (!v || !v.length) return null;
      // old format: array of colId strings; new format: array of full state objects
      return typeof v[0] === "string" ? v.map(function (id) { return { colId: id }; }) : v;
    } catch (_) { return null; }
  }

  function applyColState(state) {
    if (!gridApi || !state || !state.length) return;
    gridApi.applyColumnState({
      state: state.map(function (c) {
        return {
          colId: c.colId,
          sort: c.sort || null,
          sortIndex: c.sortIndex != null ? c.sortIndex : null,
          pinned: c.pinned || null,
          hide: !!c.hide,
          width: c.width,
        };
      }),
      applyOrder: true,
      defaultState: { sort: null },
    });
  }

  function onColResized(e) { if (e && e.finished) persistColState(); }

  // ── Filter chips bar ──

  function updateFilterChips() {
    if (!window.renderFilterChips) return;
    window.renderFilterChips({
      gridApi: gridApi,
      barEl: document.getElementById("filter-chips-bar"),
      headerNames: CHIP_HEADER_NAMES,
      onClearAll: window.clearFilters,
    });
  }

  // ── Toolbar actions ──

  window.clearFilters = function () {
    localStorage.removeItem(STORAGE_KEY);
    if (gridApi) gridApi.setFilterModel(null); // fires onFilterChanged → writeHash
    else writeHash();
    updateRowCount();
  };

  window.resetColOrder = function () {
    localStorage.removeItem(COL_STATE_KEY);
    if (gridApi) {
      gridApi.applyColumnState({
        state: COL_DEFS.map(function (c) {
          return { colId: c.field, sort: null, sortIndex: null, pinned: c.pinned || null, hide: false, width: c.width };
        }),
        applyOrder: true,
        defaultState: { sort: null },
      });
      persistColState();
    }
  };

  // ── Value formatter ──

  function numericValueFormatter(params) {
    if (params.value == null) return "";
    var n = Number(params.value);
    if (isNaN(n)) return params.value;
    if (params.colDef && params.colDef.field === "Cd") return String(Math.round(n * 100));
    return n.toLocaleString("cs-CZ");
  }

  // ── Colour settings: threshold system + heat-mode drawer (mirrors app.js) ──
  function loadThresholds() {
    try {
      var s = localStorage.getItem(THRESHOLD_KEY);
      userThresholds = s ? JSON.parse(s) : {};
    } catch (_) { userThresholds = {}; }
  }

  // Reference keeps thresholds in localStorage only (no writeHash — its URL
  // fragment carries filters only, and onGridReady never reads #t=).
  window.saveThresholds = function () {
    var rows = document.querySelectorAll("#threshold-inputs .threshold-row");
    userThresholds = {};
    rows.forEach(function (row) {
      var field = row.dataset.field;
      var minVal = row.querySelector(".th-min").value.trim();
      var maxVal = row.querySelector(".th-max").value.trim();
      if (minVal !== "" || maxVal !== "") {
        userThresholds[field] = {};
        if (minVal !== "") userThresholds[field].min = parseFloat(minVal);
        if (maxVal !== "") userThresholds[field].max = parseFloat(maxVal);
      }
    });
    try { localStorage.setItem(THRESHOLD_KEY, JSON.stringify(userThresholds)); } catch (_) {}
    if (gridApi) gridApi.refreshCells({ force: true });
  };

  window.resetThresholds = function () {
    userThresholds = {};
    try { localStorage.removeItem(THRESHOLD_KEY); } catch (_) {}
    renderThresholdInputs();
    if (gridApi) gridApi.refreshCells({ force: true });
  };

  var _thTimer = null;
  function scheduleThresholdApply() {
    if (_thTimer) clearTimeout(_thTimer);
    _thTimer = setTimeout(function () { window.saveThresholds(); updateThresholdOverrides(); }, 300);
  }

  function updateThresholdOverrides() {
    document.querySelectorAll("#threshold-inputs .threshold-row").forEach(function (row) {
      var th = userThresholds[row.dataset.field] || {};
      row.classList.toggle("overridden", th.min != null || th.max != null);
    });
  }

  function updateThresholdGradients() {
    document.querySelectorAll("#threshold-inputs .threshold-row").forEach(function (row) {
      var g = row.querySelector(".th-slider");
      if (g) g.style.background = heatGradientCSS(heatMode.palette, NUMERIC_COLS[row.dataset.field]);
    });
  }

  function _sliderRound(v, step) {
    return parseFloat((Math.round(v / step) * step).toFixed(4));
  }

  function renderThresholdInputs() {
    var container = document.getElementById("threshold-inputs");
    if (!container) return;
    while (container.firstChild) container.removeChild(container.firstChild);

    Object.keys(NUMERIC_COLS).forEach(function (field) {
      var th = userThresholds[field] || {};
      var range = colRanges[field] || {};
      var greenHigh = NUMERIC_COLS[field];

      var row = document.createElement("div");
      row.className = "threshold-row" + ((th.min != null || th.max != null) ? " overridden" : "");
      row.dataset.field = field;

      var labelWrap = document.createElement("div");
      labelWrap.className = "th-label";
      var name = document.createElement("span");
      name.textContent = field;
      var dir = document.createElement("span");
      dir.className = "th-dir";
      dir.textContent = greenHigh ? "více = lépe" : "méně = lépe";
      labelWrap.appendChild(name); labelWrap.appendChild(dir);
      row.appendChild(labelWrap);

      var minInput = document.createElement("input");
      minInput.type = "number";
      minInput.className = "th-min";
      minInput.placeholder = "min: " + (range.min != null ? range.min : "");
      if (th.min != null) minInput.value = th.min;
      var maxInput = document.createElement("input");
      maxInput.type = "number";
      maxInput.className = "th-max";
      maxInput.placeholder = "max: " + (range.max != null ? range.max : "");
      if (th.max != null) maxInput.value = th.max;
      minInput.addEventListener("input", scheduleThresholdApply);
      maxInput.addEventListener("input", scheduleThresholdApply);

      // Dual-range slider; the track is the column's good→bad gradient. Kept in
      // sync with the number inputs both ways; a thumb parked at the data edge
      // clears its input (= automatic bound).
      if (range.min != null && range.max != null && range.max > range.min) {
        var slider = document.createElement("div");
        slider.className = "th-slider";
        slider.style.background = heatGradientCSS(heatMode.palette, greenHigh);
        var step = parseFloat(((range.max - range.min) / 200).toPrecision(2)) || 1;
        var rMin = document.createElement("input");
        var rMax = document.createElement("input");
        [rMin, rMax].forEach(function (r) {
          r.type = "range"; r.min = range.min; r.max = range.max; r.step = step;
        });
        rMin.value = th.min != null ? th.min : range.min;
        rMax.value = th.max != null ? th.max : range.max;
        rMin.setAttribute("aria-label", field + " min");
        rMax.setAttribute("aria-label", field + " max");
        rMin.addEventListener("input", function () {
          if (+rMin.value > +rMax.value) rMin.value = rMax.value;
          var v = _sliderRound(+rMin.value, step);
          minInput.value = v <= range.min ? "" : v;
          scheduleThresholdApply();
        });
        rMax.addEventListener("input", function () {
          if (+rMax.value < +rMin.value) rMax.value = rMin.value;
          var v = _sliderRound(+rMax.value, step);
          maxInput.value = v >= range.max ? "" : v;
          scheduleThresholdApply();
        });
        minInput.addEventListener("input", function () {
          rMin.value = minInput.value !== "" ? minInput.value : range.min;
        });
        maxInput.addEventListener("input", function () {
          rMax.value = maxInput.value !== "" ? maxInput.value : range.max;
        });
        slider.appendChild(rMin);
        slider.appendChild(rMax);
        row.appendChild(slider);
      }

      var pair = document.createElement("div");
      pair.className = "th-pair";
      pair.appendChild(minInput); pair.appendChild(maxInput);
      row.appendChild(pair);

      container.appendChild(row);
    });
  }

  function styleIcoBg(styleKey) {
    var dark = isDarkTheme();
    var rgb = heatRGB(0.72);
    var barA = dark ? 0.8 : 0.5, tintA = dark ? 0.18 : 0.12;
    if (styleKey === "fullcell") return "rgba(" + rgb + "," + (dark ? 0.5 : 0.32) + ")";
    if (styleKey === "databar") return "linear-gradient(90deg,rgba(" + rgb + "," + barA + ") 0,rgba(" + rgb + "," + barA + ") 60%,transparent 60%)";
    return "linear-gradient(90deg,rgba(" + rgb + "," + barA + ") 0,rgba(" + rgb + "," + barA + ") 60%,rgba(" + rgb + "," + tintA + ") 60%)";
  }

  function renderHeatModeChoices() {
    var palWrap = document.getElementById("palette-choices");
    var styWrap = document.getElementById("style-choices");
    if (!palWrap || !styWrap) return;
    while (palWrap.firstChild) palWrap.removeChild(palWrap.firstChild);
    while (styWrap.firstChild) styWrap.removeChild(styWrap.firstChild);

    Object.keys(HEAT_PALETTES).forEach(function (key) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "choice" + (heatMode.palette === key ? " active" : "");
      var sw = document.createElement("span");
      sw.className = "swatch";
      sw.style.background = heatGradientCSS(key, false);
      var lbl = document.createElement("span");
      lbl.textContent = HEAT_PALETTES[key].label;
      btn.appendChild(sw); btn.appendChild(lbl);
      btn.onclick = function () { window.setHeatMode(key, heatMode.style); };
      palWrap.appendChild(btn);
    });

    Object.keys(HEAT_STYLES).forEach(function (key) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "choice" + (heatMode.style === key ? " active" : "");
      var ico = document.createElement("span");
      ico.className = "style-ico";
      ico.style.background = styleIcoBg(key);
      var lbl = document.createElement("span");
      lbl.textContent = HEAT_STYLES[key];
      btn.appendChild(ico); btn.appendChild(lbl);
      btn.onclick = function () { window.setHeatMode(heatMode.palette, key); };
      styWrap.appendChild(btn);
    });
  }

  window.toggleToolsMenu = function (ev) {
    if (ev) ev.stopPropagation();
    var pop = document.getElementById("tools-menu");
    var btn = document.getElementById("btn-tools");
    if (!pop) return;
    var willOpen = pop.classList.contains("hidden");
    pop.classList.toggle("hidden");
    if (btn) btn.setAttribute("aria-expanded", willOpen ? "true" : "false");
  };

  function closeToolsMenu() {
    var pop = document.getElementById("tools-menu");
    var btn = document.getElementById("btn-tools");
    if (pop && !pop.classList.contains("hidden")) {
      pop.classList.add("hidden");
      if (btn) btn.setAttribute("aria-expanded", "false");
    }
  }

  document.addEventListener("click", function (e) {
    var c = e.target.closest ? e.target.closest.bind(e.target) : function () { return null; };
    if (!c(".menu-wrap")) closeToolsMenu();
    // Drawer closes on any click outside it (opening click comes from .menu-wrap).
    if (!c("#settings-panel") && !c(".menu-wrap")) window.closeColorSettings();
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") { closeToolsMenu(); window.closeColorSettings(); }
  });

  window.openColorSettings = function () {
    closeToolsMenu();
    renderHeatModeChoices();
    renderThresholdInputs();
    var panel = document.getElementById("settings-panel");
    if (panel) panel.classList.remove("hidden");
  };

  window.closeColorSettings = function () {
    var panel = document.getElementById("settings-panel");
    if (panel) panel.classList.add("hidden");
  };

  // ── Grid init ──

  function init(data) {
    computeRanges(data);
    loadThresholds();
    loadHeatMode();
    totalRowCount = data.length;

    incompleteCount = 0;
    for (var r = 0; r < data.length; r++) {
      var missing = computeMissingSpecs(data[r]);
      data[r]._missing = missing;
      data[r]._missingCount = missing.length;
      if (missing.length) incompleteCount++;
    }

    for (var i = 0; i < COL_DEFS.length; i++) {
      var col = COL_DEFS[i];
      if (col.sortable === undefined) col.sortable = true;
      if (col.resizable === undefined) col.resizable = true;
      if (col.type === "numericColumn") {
        col.valueFormatter = numericValueFormatter;
        if (NUMERIC_COLS.hasOwnProperty(col.field)) {
          col.cellStyle = numericCellStyle(col.field);
        }
      }
    }

    var gridDiv = document.getElementById("grid");
    var gridOptions = {
      theme: "legacy",
      localeText: {
        equals: "Rovná se", notEqual: "Nerovná se",
        lessThan: "Menší než", lessThanOrEqual: "Menší nebo rovno",
        greaterThan: "Větší než", greaterThanOrEqual: "Větší nebo rovno",
        inRange: "V rozsahu", inRangeStart: "od", inRangeEnd: "do",
        contains: "Obsahuje", notContains: "Neobsahuje",
        startsWith: "Začíná na", endsWith: "Končí na",
        blank: "Prázdné", notBlank: "Neprázdné",
        filterOoo: "Filtrovat…", applyFilter: "Použít", resetFilter: "Vymazat",
        clearFilter: "Vymazat", cancelFilter: "Zrušit",
        andCondition: "A zároveň", orCondition: "Nebo",
        noMatches: "Žádná shoda",
      },
      columnDefs: COL_DEFS,
      rowData: data,
      rowHeight: 25,
      defaultColDef: {
        floatingFilter: true,
        wrapHeaderText: true,
        autoHeaderHeight: true,
        filterParams: { buttons: ["reset"] },
        tooltipComponent: ColTooltip,
      },
      tooltipShowDelay: 400,
      tooltipMouseTrack: true,
      animateRows: false,
      enableCellTextSelection: true,
      // External filter (#19): independent of the column filters — toggled by
      // the "Neúplné: N / M" button, not part of getFilterModel() so
      // clearFilters()/the chips bar don't touch it.
      isExternalFilterPresent: function () { return incompleteOnly; },
      doesExternalFilterPass: function (node) {
        return !incompleteOnly || (node.data && node.data._missingCount > 0);
      },
      onFilterChanged: function () {
        var model = gridApi ? gridApi.getFilterModel() : null;
        saveFiltersToStorage(model);
        writeHash();
        updateRowCount();
        updateFilterChips();
      },
      onDragStopped: persistColState,
      onSortChanged: persistColState,
      onColumnPinned: persistColState,
      onColumnVisible: persistColState,
      onColumnResized: onColResized,
      onGridReady: function (params) {
        gridApi = params.api;
        window.__gridApi = params.api;

        var hash = U.parseHash();
        var legacyFilters = hash.f ? null : U.decodeLegacyFilters();

        // Column layout: localStorage only (never the URL).
        var colState = loadColStateFromStorage();
        if (colState) applyColState(colState);

        // Filters: URL fragment (#f=) → legacy ?filters= → localStorage.
        var urlFilters = hash.f ? U.decFilters(hash.f) : legacyFilters;
        var filters = urlFilters || loadFiltersFromStorage();
        if (filters) gridApi.setFilterModel(filters);

        // Migrate an old ?filters= link to the canonical #fragment form.
        if (legacyFilters) writeHash();

        updateIncompleteButton();
        updateRowCount();
        updateFilterChips();
      },
    };

    agGrid.createGrid(gridDiv, gridOptions);
  }

  fetch("data/reference.json")
    .then(function (r) { return r.json(); })
    .then(function (data) { init(data); })
    .catch(function (err) { console.error("Failed to load reference data:", err); });
})();

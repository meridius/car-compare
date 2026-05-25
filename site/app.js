(function () {
  "use strict";

  var STORAGE_KEY = "carCompareFilters";
  var THRESHOLD_KEY = "carCompareThresholds";
  var THEME_KEY = "carCompareTheme";
  var COL_STATE_KEY = "carCompareColState";

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    document.getElementById("btn-theme").textContent = theme === "dark" ? "\u263E" : "\u2600";
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

  // Custom multi-select set filter (AG Grid Community replacement for Enterprise agSetColumnFilter)
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

  SetFilter.prototype.getModelAsString = function () {
    if (!this.filterActive || !this.selected) return "";
    var vals = [];
    if (this.selected.has(null)) vals.push("(\u2205)");
    this.selected.forEach(function (v) { if (v !== null) vals.push(v); });
    if (vals.length <= 2) return vals.join(", ");
    return vals.length + " vybr\u00e1no";
  };

  SetFilter.prototype.afterGuiAttached = function () {
    if (this.searchInput) this.searchInput.focus();
  };

  var COL_CONFIG = [
    { field: "Odkaz na auto", hdr: "Odkaz", filter: false, w: 60, pinned: "left", link: true },
    { field: "Model auta", filter: "agTextColumnFilter", w: 260, pinned: "left", align: "left" },
    { field: "Typ", filter: "agSetColumnFilter", w: 80 },
    { field: "Palivo", filter: "agSetColumnFilter", w: 100 },
    { field: "Stav", filter: "agSetColumnFilter", w: 110 },
    { field: "Cena (Kč)", filter: "agNumberColumnFilter", w: 120, num: true, hi: false, align: "right" },
    { field: "Rok výroby", filter: "agNumberColumnFilter", w: 80, num: true, hi: true },
    { field: "Nájezd (km)", filter: "agNumberColumnFilter", w: 110, num: true, hi: false, align: "right" },
    { field: "Spotřeba (l/100 km)", filter: "agNumberColumnFilter", w: 100, num: true, hi: false },
    { field: "Objem kufru (l)", filter: "agNumberColumnFilter", w: 80, num: true, hi: true },
    { field: "Výkon (kW)", filter: "agNumberColumnFilter", w: 80, num: true, hi: true },
    { field: "Objem motoru", filter: "agSetColumnFilter", w: 80 },
    { field: "Typ motoru", filter: "agSetColumnFilter", w: 90 },
    { field: "Hybrid typ", filter: "agSetColumnFilter", w: 90 },
    { field: "Karoserie", filter: "agSetColumnFilter", w: 100 },
    { field: "Hlučnost (dB)", filter: "agNumberColumnFilter", w: 80, num: true, hi: false },
    { field: "Kapacita baterie (kWh)", filter: "agNumberColumnFilter", w: 100, num: true, hi: true },
    { field: "Dojezd WLTP (km)", filter: "agNumberColumnFilter", w: 100, num: true, hi: true },
    { field: "Dojezd EV-database (km)", filter: "agNumberColumnFilter", w: 110, num: true, hi: true, hdr: "Dojezd\nEV-db (km)" },
    { field: "Aerodynamická modifikace", filter: "agSetColumnFilter", w: 100, hdr: "Aerodyn.\nmodifikace" },
    { field: "Převodovka", filter: "agSetColumnFilter", w: 110 },
    { field: "Dvouspojková převodovka", filter: "agSetColumnFilter", w: 90, hdr: "Dvousp.\npřevodovka" },
    { field: "Náhon 4x4", filter: "agSetColumnFilter", w: 80 },
    { field: "Filtr pevných částic", filter: "agSetColumnFilter", w: 90, hdr: "Filtr pevn.\nčástic" },
    { field: "Tepelné čerpadlo", filter: "agSetColumnFilter", w: 80, hdr: "Tepelné\nčerpadlo" },
    { field: "Tepelné čerpadlo možné", filter: "agSetColumnFilter", w: 90, hdr: "Tep. čerp.\nmožné" },
    { field: "Výbava", filter: "agSetColumnFilter", w: 110 },
    { field: "Kola", filter: "agSetColumnFilter", w: 70 },
    { field: "Záruka", filter: "agSetColumnFilter", w: 80 },
    { field: "Extra", filter: "agTextColumnFilter", w: 200 },
    { field: "Zdroj", filter: "agSetColumnFilter", w: 100 },
  ];

  var NUMERIC_COLS = {};
  for (var ci = 0; ci < COL_CONFIG.length; ci++) {
    if (COL_CONFIG[ci].num) NUMERIC_COLS[COL_CONFIG[ci].field] = COL_CONFIG[ci].hi;
  }

  var gridApi = null;
  var colRanges = {};
  var userThresholds = {};

  function hslToRgb(h, s, l) {
    s /= 100; l /= 100;
    var c = (1 - Math.abs(2 * l - 1)) * s;
    var x = c * (1 - Math.abs((h / 60) % 2 - 1));
    var m = l - c / 2;
    var r, g, b;
    if (h < 60) { r = c; g = x; b = 0; }
    else if (h < 120) { r = x; g = c; b = 0; }
    else if (h < 180) { r = 0; g = c; b = x; }
    else if (h < 240) { r = 0; g = x; b = c; }
    else if (h < 300) { r = x; g = 0; b = c; }
    else { r = c; g = 0; b = x; }
    return [Math.round((r + m) * 255), Math.round((g + m) * 255), Math.round((b + m) * 255)];
  }

  function colorForValue(val, min, max, greenHigh) {
    if (val == null || min === max) return null;
    var t = (val - min) / (max - min);
    t = Math.max(0, Math.min(1, t));
    if (!greenHigh) t = 1 - t;
    var hue = t * 120;
    var rgb = hslToRgb(hue, 80, 35);
    return "rgb(" + rgb[0] + "," + rgb[1] + "," + rgb[2] + ")";
  }

  function makeHeaderName(field) {
    var m = field.match(/^(.+?)\s*\(([^)]+)\)$/);
    if (m) return m[1] + "\n(" + m[2] + ")";
    return field;
  }

  function numericCellStyle(field) {
    var isRight = (field === "Cena (Kč)" || field === "Nájezd (km)");
    return function (params) {
      var style = { textAlign: isRight ? "right" : "center" };
      if (params.value == null) return style;
      var greenHigh = NUMERIC_COLS[field];
      var th = userThresholds[field] || {};
      var range = colRanges[field] || {};
      var min = th.min != null ? th.min : range.min;
      var max = th.max != null ? th.max : range.max;
      if (min == null || max == null) return style;
      var bg = colorForValue(params.value, min, max, greenHigh);
      if (bg) { style.backgroundColor = bg; style.color = "#fff"; }
      return style;
    };
  }

  function numericFormatter(field) {
    return function (p) {
      if (p.value == null) return "";
      if (field === "Cena (Kč)") return Number(p.value).toLocaleString("cs-CZ") + " Kč";
      if (field === "Nájezd (km)") return Number(p.value).toLocaleString("cs-CZ") + " km";
      if (field === "Spotřeba (l/100 km)") return p.value.toFixed(1);
      return String(p.value);
    };
  }

  function linkRenderer(params) {
    if (!params.value) return "";
    var a = document.createElement("a");
    a.href = params.value;
    a.target = "_blank";
    a.rel = "noopener";
    a.textContent = "\u2197";
    a.title = params.value;
    a.style.fontSize = "1.2em";
    return a;
  }

  function buildColumnDefs() {
    var defs = [];
    for (var i = 0; i < COL_CONFIG.length; i++) {
      var cfg = COL_CONFIG[i];
      var def = {
        field: cfg.field,
        headerName: cfg.hdr || makeHeaderName(cfg.field),
        filter: cfg.filter === "agSetColumnFilter" ? SetFilter : cfg.filter,
        width: cfg.w,
      };

      if (cfg.pinned) def.pinned = cfg.pinned;

      if (cfg.link) {
        def.cellRenderer = linkRenderer;
        def.cellStyle = { textAlign: "center" };
      } else if (cfg.num) {
        def.cellStyle = numericCellStyle(cfg.field);
        def.valueFormatter = numericFormatter(cfg.field);
      } else {
        def.cellStyle = { textAlign: cfg.align || "center" };
      }

      defs.push(def);
    }
    return defs;
  }

  function getFilterModel() {
    return gridApi ? gridApi.getFilterModel() : null;
  }

  function setFilterModel(model) {
    if (gridApi && model) gridApi.setFilterModel(model);
  }

  function saveFiltersToStorage(model) {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(model)); } catch (_) {}
  }

  function loadFiltersFromStorage() {
    try {
      var s = localStorage.getItem(STORAGE_KEY);
      return s ? JSON.parse(s) : null;
    } catch (_) { return null; }
  }

  function saveFiltersToUrl(model) {
    var url = new URL(window.location);
    if (model && Object.keys(model).length > 0) {
      url.searchParams.set("filters", btoa(unescape(encodeURIComponent(JSON.stringify(model)))));
    } else {
      url.searchParams.delete("filters");
    }
    history.replaceState(null, "", url);
  }

  function loadFiltersFromUrl() {
    var url = new URL(window.location);
    var b64 = url.searchParams.get("filters");
    if (!b64) return null;
    try { return JSON.parse(decodeURIComponent(escape(atob(b64)))); }
    catch (_) { return null; }
  }

  function saveColState() {
    if (!gridApi) return;
    var state = gridApi.getColumnState();
    var ids = state.map(function (c) { return c.colId; });
    try { localStorage.setItem(COL_STATE_KEY, JSON.stringify(ids)); } catch (_) {}
    var url = new URL(window.location);
    url.searchParams.set("cols", btoa(JSON.stringify(ids)));
    history.replaceState(null, "", url);
  }

  function loadColState() {
    var url = new URL(window.location);
    var b64 = url.searchParams.get("cols");
    if (b64) {
      try { return JSON.parse(atob(b64)); } catch (_) {}
    }
    try {
      var s = localStorage.getItem(COL_STATE_KEY);
      return s ? JSON.parse(s) : null;
    } catch (_) { return null; }
  }

  function applyColState(ids) {
    if (!gridApi || !ids || !ids.length) return;
    var state = ids.map(function (id, idx) {
      return { colId: id, sort: null, sortIndex: null };
    });
    gridApi.applyColumnState({ state: state, applyOrder: true });
  }

  function onFilterChanged() {
    var model = getFilterModel();
    saveFiltersToStorage(model);
    saveFiltersToUrl(model);
    updateRowCount();
  }

  function loadThresholds() {
    try {
      var s = localStorage.getItem(THRESHOLD_KEY);
      userThresholds = s ? JSON.parse(s) : {};
    } catch (_) { userThresholds = {}; }
  }

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
    localStorage.setItem(THRESHOLD_KEY, JSON.stringify(userThresholds));
    if (gridApi) gridApi.refreshCells({ force: true });
  };

  window.resetThresholds = function () {
    userThresholds = {};
    localStorage.removeItem(THRESHOLD_KEY);
    renderThresholdInputs();
    if (gridApi) gridApi.refreshCells({ force: true });
  };

  function renderThresholdInputs() {
    var container = document.getElementById("threshold-inputs");
    while (container.firstChild) container.removeChild(container.firstChild);

    var fields = Object.keys(NUMERIC_COLS);
    for (var i = 0; i < fields.length; i++) {
      var field = fields[i];
      var th = userThresholds[field] || {};
      var range = colRanges[field] || {};

      var row = document.createElement("div");
      row.className = "threshold-row";
      row.dataset.field = field;

      var label = document.createElement("label");
      label.textContent = field;
      row.appendChild(label);

      var minInput = document.createElement("input");
      minInput.type = "number";
      minInput.className = "th-min";
      minInput.placeholder = "min (" + (range.min != null ? range.min : "") + ")";
      if (th.min != null) minInput.value = th.min;
      row.appendChild(minInput);

      var maxInput = document.createElement("input");
      maxInput.type = "number";
      maxInput.className = "th-max";
      maxInput.placeholder = "max (" + (range.max != null ? range.max : "") + ")";
      if (th.max != null) maxInput.value = th.max;
      row.appendChild(maxInput);

      container.appendChild(row);
    }
  }

  window.toggleSettings = function () {
    document.getElementById("settings-panel").classList.toggle("hidden");
  };

  function updateRowCount() {
    var count = 0;
    if (gridApi) gridApi.forEachNodeAfterFilter(function () { count++; });
    document.getElementById("row-count").textContent = count + " aut";
  }

  window.clearFilters = function () {
    localStorage.removeItem(STORAGE_KEY);
    var url = new URL(window.location);
    url.searchParams.delete("filters");
    history.replaceState(null, "", url);
    if (gridApi) gridApi.setFilterModel(null);
    updateRowCount();
  };

  window.resetColOrder = function () {
    localStorage.removeItem(COL_STATE_KEY);
    var url = new URL(window.location);
    url.searchParams.delete("cols");
    history.replaceState(null, "", url);
    if (gridApi) {
      gridApi.applyColumnState({ defaultState: { sort: null } });
      var defaultIds = COL_CONFIG.map(function (c) { return c.field; });
      applyColState(defaultIds);
    }
  };

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

  function init(data) {
    computeRanges(data);
    loadThresholds();
    renderThresholdInputs();

    var gridOptions = {
      columnDefs: buildColumnDefs(),
      rowData: data,
      defaultColDef: {
        sortable: true,
        resizable: true,
        floatingFilter: true,
        wrapHeaderText: true,
        autoHeaderHeight: true,
        filterParams: { buttons: ["reset"] },
      },
      animateRows: false,
      enableCellTextSelection: true,
      onFilterChanged: onFilterChanged,
      onDragStopped: saveColState,
      onGridReady: function (params) {
        gridApi = params.api;
        var savedCols = loadColState();
        if (savedCols) applyColState(savedCols);
        var urlFilters = loadFiltersFromUrl();
        var storageFilters = loadFiltersFromStorage();
        var filters = urlFilters || storageFilters;
        if (filters) setFilterModel(filters);
        updateRowCount();
      },
    };

    var gridDiv = document.getElementById("grid");
    agGrid.createGrid(gridDiv, gridOptions);
  }

  fetch("data/cars.json")
    .then(function (r) { return r.json(); })
    .then(init)
    .catch(function (err) {
      document.getElementById("grid").textContent = "Chyba načítání dat: " + err.message;
    });
})();

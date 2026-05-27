(function () {
  "use strict";

  var STORAGE_KEY = "refCompareFilters";
  var THEME_KEY = "carCompareTheme";
  var COL_STATE_KEY = "refCompareColState";

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    document.getElementById("btn-theme").textContent = theme === "dark" ? "\u263E" : "\u2600";
    var gridEl = document.getElementById("grid");
    if (gridEl) {
      gridEl.classList.remove("ag-theme-alpine", "ag-theme-alpine-dark");
      gridEl.classList.add(theme === "dark" ? "ag-theme-alpine-dark" : "ag-theme-alpine");
    }
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

  SetFilter.prototype.getModelAsString = function () {
    if (!this.filterActive || !this.selected) return "";
    var vals = Array.from(this.selected).map(function (v) { return v == null ? "(Prázdné)" : v; });
    return vals.join(", ");
  };

  var gridApi = null;
  var colRanges = {};
  var totalRowCount = 0;

  var COL_DEFS = [
    { field: "Typ", filter: SetFilter, width: 100, headerClass: "ag-header-cell-center" },
    { field: "Model auta", filter: "agTextColumnFilter", width: 280 },
    { field: "Spotřeba (l/100 km)", filter: "agNumberColumnFilter", width: 120, type: "numericColumn" },
    { field: "Objem kufru (l)", filter: "agNumberColumnFilter", width: 110, type: "numericColumn" },
    { field: "Hlučnost (dB)", filter: "agNumberColumnFilter", width: 100, type: "numericColumn" },
    { field: "Kapacita baterie (kWh)", filter: "agNumberColumnFilter", width: 130, type: "numericColumn" },
    { field: "Dojezd WLTP (km)", filter: "agNumberColumnFilter", width: 120, type: "numericColumn" },
    { field: "Dojezd EV-database (km)", filter: "agNumberColumnFilter", width: 140, type: "numericColumn" },
    { field: "Aerodynamická modifikace", filter: SetFilter, width: 140, headerClass: "ag-header-cell-center" },
    { field: "Tepelné čerpadlo možné", filter: SetFilter, width: 130, headerClass: "ag-header-cell-center" },
  ];

  // Map numeric column fields to whether higher is better (true) or lower is better (false)
  var NUMERIC_COLS = {
    "Spotřeba (l/100 km)": false,
    "Objem kufru (l)": true,
    "Hlučnost (dB)": false,
    "Kapacita baterie (kWh)": true,
    "Dojezd WLTP (km)": true,
    "Dojezd EV-database (km)": true,
  };

  // ── HSL gradient coloring for numeric columns ──

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

  function numericCellStyle(field) {
    return function (params) {
      var style = { textAlign: "center" };
      if (params.value == null) return style;
      var greenHigh = NUMERIC_COLS[field];
      var range = colRanges[field] || {};
      if (range.min == null || range.max == null) return style;
      var bg = colorForValue(params.value, range.min, range.max, greenHigh);
      if (bg) { style.backgroundColor = bg; style.color = "#fff"; }
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

  // ── Filter persistence (URL + localStorage) ──

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

  // ── Column state persistence (URL + localStorage) ──

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
    var state = ids.map(function (id) {
      return { colId: id, sort: null, sortIndex: null };
    });
    gridApi.applyColumnState({ state: state, applyOrder: true });
  }

  // ── Toolbar actions ──

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
      var defaultIds = COL_DEFS.map(function (c) { return c.field; });
      applyColState(defaultIds);
    }
  };

  // ── Value formatter ──

  function numericValueFormatter(params) {
    if (params.value == null) return "";
    var n = Number(params.value);
    if (isNaN(n)) return params.value;
    return n.toLocaleString("cs-CZ");
  }

  // ── Grid init ──

  function init(data) {
    computeRanges(data);
    totalRowCount = data.length;

    for (var i = 0; i < COL_DEFS.length; i++) {
      var col = COL_DEFS[i];
      col.sortable = true;
      col.resizable = true;
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
      columnDefs: COL_DEFS,
      rowData: data,
      defaultColDef: {
        floatingFilter: true,
        wrapHeaderText: true,
        autoHeaderHeight: true,
        filterParams: { buttons: ["reset"] },
      },
      animateRows: false,
      enableCellTextSelection: true,
      onFilterChanged: function () {
        var model = gridApi ? gridApi.getFilterModel() : null;
        saveFiltersToStorage(model);
        saveFiltersToUrl(model);
        updateRowCount();
      },
      onDragStopped: saveColState,
      onGridReady: function (params) {
        gridApi = params.api;
        var savedCols = loadColState();
        if (savedCols) applyColState(savedCols);
        var urlFilters = loadFiltersFromUrl();
        var storageFilters = loadFiltersFromStorage();
        var filters = urlFilters || storageFilters;
        if (filters) gridApi.setFilterModel(filters);
        updateRowCount();
      },
    };

    agGrid.createGrid(gridDiv, gridOptions);
  }

  fetch("data/reference.json")
    .then(function (r) { return r.json(); })
    .then(function (data) { init(data); })
    .catch(function (err) { console.error("Failed to load reference data:", err); });
})();

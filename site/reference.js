(function () {
  "use strict";

  var STORAGE_KEY = "refCompareFilters";
  var THEME_KEY = "carCompareTheme";
  var COL_STATE_KEY = "refCompareColState";

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

  function updateRowCount() {
    var displayed = 0;
    if (gridApi) {
      gridApi.forEachNodeAfterFilter(function () { displayed++; });
    }
    var el = document.getElementById("row-count");
    if (el) el.textContent = displayed + " záznamů";
  }

  function saveFilters() {
    if (!gridApi) return;
    try {
      var model = gridApi.getFilterModel();
      localStorage.setItem(STORAGE_KEY, JSON.stringify(model));
    } catch (_) {}
  }

  function restoreFilters() {
    if (!gridApi) return;
    try {
      var saved = localStorage.getItem(STORAGE_KEY);
      if (saved) gridApi.setFilterModel(JSON.parse(saved));
    } catch (_) {}
  }

  function saveColState() {
    if (!gridApi) return;
    try {
      var state = gridApi.getColumnState();
      localStorage.setItem(COL_STATE_KEY, JSON.stringify(state));
    } catch (_) {}
  }

  function restoreColState() {
    if (!gridApi) return;
    try {
      var saved = localStorage.getItem(COL_STATE_KEY);
      if (saved) gridApi.applyColumnState({ state: JSON.parse(saved), applyOrder: true });
    } catch (_) {}
  }

  window.clearFilters = function () {
    if (!gridApi) return;
    gridApi.setFilterModel(null);
    try { localStorage.removeItem(STORAGE_KEY); } catch (_) {}
    updateRowCount();
  };

  window.resetColOrder = function () {
    if (!gridApi) return;
    gridApi.resetColumnState();
    try { localStorage.removeItem(COL_STATE_KEY); } catch (_) {}
  };

  function numericValueFormatter(params) {
    if (params.value == null) return "";
    var n = Number(params.value);
    if (isNaN(n)) return params.value;
    return n.toLocaleString("cs-CZ");
  }

  function init(data) {
    for (var i = 0; i < COL_DEFS.length; i++) {
      var col = COL_DEFS[i];
      col.sortable = true;
      col.resizable = true;
      if (col.type === "numericColumn") {
        col.valueFormatter = numericValueFormatter;
      }
    }

    var gridDiv = document.getElementById("grid");
    var gridOptions = {
      columnDefs: COL_DEFS,
      rowData: data,
      defaultColDef: {
        floatingFilter: true,
        filterParams: { buttons: ["reset"] },
      },
      animateRows: false,
      onFilterChanged: function () {
        updateRowCount();
        saveFilters();
      },
      onColumnMoved: saveColState,
      onColumnResized: saveColState,
      onSortChanged: saveColState,
      onGridReady: function () {
        restoreFilters();
        restoreColState();
        updateRowCount();
      },
    };

    gridApi = agGrid.createGrid(gridDiv, gridOptions);
  }

  fetch("data/reference.json")
    .then(function (r) { return r.json(); })
    .then(function (data) { init(data); })
    .catch(function (err) { console.error("Failed to load reference data:", err); });
})();

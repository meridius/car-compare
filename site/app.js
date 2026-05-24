(function () {
  "use strict";

  var STORAGE_KEY = "carCompareFilters";
  var THRESHOLD_KEY = "carCompareThresholds";

  var NUMERIC_COLS = {
    "Cena (Kč)": false,
    "Nájezd (km)": false,
    "Rok výroby": true,
    "Výkon (kW)": true,
    "Objem kufru (l)": true,
    "Hlučnost (dB)": false,
    "Spotřeba (l/100 km)": false,
    "Kapacita baterie (kWh)": true,
    "Dojezd WLTP (km)": true,
    "Dojezd EV-database (km)": true,
  };

  var SET_COLS = [
    "Typ", "Palivo", "Stav", "Karoserie", "Převodovka",
    "Náhon 4x4", "Hybrid typ", "Dvouspojková převodovka",
    "Filtr pevných částic", "Tepelné čerpadlo", "Zdroj",
    "Aerodynamická modifikace", "Tepelné čerpadlo možné", "Výbava", "Záruka",
  ];

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

  function cellStyle(field) {
    return function (params) {
      if (params.value == null) return null;
      var greenHigh = NUMERIC_COLS[field];
      var th = userThresholds[field] || {};
      var range = colRanges[field] || {};
      var min = th.min != null ? th.min : range.min;
      var max = th.max != null ? th.max : range.max;
      if (min == null || max == null) return null;
      var bg = colorForValue(params.value, min, max, greenHigh);
      return bg ? { backgroundColor: bg, color: "#fff" } : null;
    };
  }

  function buildColumnDefs() {
    var defs = [];

    defs.push({ field: "Typ", filter: "agSetColumnFilter", width: 100, pinned: "left" });
    defs.push({ field: "Model auta", filter: "agTextColumnFilter", width: 260, pinned: "left" });

    var numericFields = Object.keys(NUMERIC_COLS);
    for (var i = 0; i < numericFields.length; i++) {
      (function (field) {
        defs.push({
          field: field,
          filter: "agNumberColumnFilter",
          cellStyle: cellStyle(field),
          width: 130,
          valueFormatter: function (p) {
            if (p.value == null) return "";
            if (field === "Cena (Kč)") return Number(p.value).toLocaleString("cs-CZ") + " Kč";
            if (field === "Nájezd (km)") return Number(p.value).toLocaleString("cs-CZ") + " km";
            if (field === "Spotřeba (l/100 km)") return p.value.toFixed(1);
            return String(p.value);
          },
        });
      })(numericFields[i]);
    }

    for (var j = 0; j < SET_COLS.length; j++) {
      defs.push({ field: SET_COLS[j], filter: "agSetColumnFilter", width: 130 });
    }

    var textCols = ["Objem motoru", "Typ motoru", "Kola", "Extra"];
    for (var k = 0; k < textCols.length; k++) {
      defs.push({ field: textCols[k], filter: "agTextColumnFilter", width: 130 });
    }

    defs.push({
      field: "Odkaz na auto",
      filter: false,
      width: 100,
      cellRenderer: function (params) {
        if (!params.value) return "";
        var a = document.createElement("a");
        a.href = params.value;
        a.target = "_blank";
        a.rel = "noopener";
        a.textContent = "Otevřít";
        return a;
      },
    });

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
        filterParams: { buttons: ["reset"] },
      },
      animateRows: false,
      enableCellTextSelection: true,
      onFilterChanged: onFilterChanged,
      onGridReady: function (params) {
        gridApi = params.api;
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

(function () {
  "use strict";

  var STORAGE_KEY = "refCompareFilters";
  var THEME_KEY = "carCompareTheme";
  var COL_STATE_KEY = "refCompareColState";
  var THRESHOLD_KEY = "refCompareThresholds";   // isolated: reference has its own numeric columns
  var HEATMODE_KEY = "carCompareHeatMode";       // shared with index (global appearance pref)
  var PRICE_VIEW_KEY = "refPriceView";           // "compact" | "boxplot" | "histogram"

  // "Cena na trhu" column: the price band of a reference model's paired listings,
  // rendered three ways (user toggle). Axis is SHARED with build_data.py
  // (PRICE_HIST_MIN/MAX/BINS) so the histogram counts map onto the same ruler every
  // row uses — cross-row comparison is the whole point. Each view has ONE uniform
  // row height (set via setGridOption on toggle), so all grid rows stay equal-height.
  var PRICE_AXIS_MIN = 100000, PRICE_AXIS_MAX = 800000, PRICE_HIST_BINS = 14;
  var PRICE_ROW_HEIGHTS = { compact: 25, boxplot: 44, histogram: 58 };
  var priceView = "compact";
  var maxNabidek = 1;   // busiest reference model — scales the Nabídek count bar

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

  // ── Numeric range: ONE shared state drives BOTH colouring and filtering. ──
  // Mirrors site/app.js. userThresholds[field] = {min,max} is the single source of
  // truth: the colour-settings slider and the column-filter slider are two views of
  // it. Every editor routes through commitRange(); the filter side emits the
  // standard AG number model so the URL codec / chips work unchanged. (Reference
  // persists thresholds to localStorage only; filters go to #f=.)

  function fmtRangeNum(field, v) {
    if (v == null || v === "" || isNaN(v)) return "";
    return Number(v).toLocaleString("cs-CZ", { useGrouping: true, maximumFractionDigits: 3 });
  }
  function parseNum(s) {
    if (s == null) return null;
    s = String(s).replace(/\s/g, "").replace(",", ".");
    if (s === "" || s === "-" || s === ".") return null;
    var n = parseFloat(s);
    return isNaN(n) ? null : n;
  }
  function cssEsc(s) {
    return (window.CSS && CSS.escape) ? CSS.escape(s) : s.replace(/["\\]/g, "\\$&");
  }
  function mkNumInput(placeholder) {
    var i = document.createElement("input");
    i.type = "text"; i.inputMode = "decimal"; i.autocomplete = "off"; i.spellcheck = false;
    i.placeholder = placeholder;
    return i;
  }

  function rangeOf(field) {
    var th = userThresholds[field] || {};
    return { min: th.min != null ? th.min : null, max: th.max != null ? th.max : null };
  }
  function setRange(field, min, max) {
    if (min == null && max == null) { delete userThresholds[field]; return; }
    var o = {};
    if (min != null) o.min = min;
    if (max != null) o.max = max;
    userThresholds[field] = o;
  }
  function rangeModel(field) {
    var r = rangeOf(field);
    if (r.min == null && r.max == null) return null;
    return { filterType: "number", type: "inRange", filter: r.min, filterTo: r.max };
  }
  function persistThresholds() {
    try { localStorage.setItem(THRESHOLD_KEY, JSON.stringify(userThresholds)); } catch (_) {}
  }

  var rangeFilters = {};
  var _rangeTimers = {};

  function commitRange(field, min, max) {
    setRange(field, min, max);
    syncSidebarRow(field);
    if (rangeFilters[field]) rangeFilters[field].renderState();
    updateThresholdOverrides();
    if (_rangeTimers[field]) clearTimeout(_rangeTimers[field]);
    _rangeTimers[field] = setTimeout(function () {
      persistThresholds();
      if (gridApi) {
        gridApi.refreshCells({ force: true });
        gridApi.setColumnFilterModel(field, rangeModel(field)).then(function () {
          gridApi.onFilterChanged();
        });
      }
    }, 220);
  }

  function syncSidebarRow(field) {
    var container = document.getElementById("threshold-inputs");
    if (!container) return;
    var row = container.querySelector('.threshold-row[data-field="' + cssEsc(field) + '"]');
    if (!row) return;
    var r = rangeOf(field), rg = colRanges[field] || {};
    var mn = row.querySelector(".th-min"), mx = row.querySelector(".th-max");
    if (mn && document.activeElement !== mn) mn.value = fmtRangeNum(field, r.min);
    if (mx && document.activeElement !== mx) mx.value = fmtRangeNum(field, r.max);
    var rMin = row.querySelector(".th-range-min"), rMax = row.querySelector(".th-range-max");
    if (rMin && document.activeElement !== rMin) rMin.value = r.min != null ? r.min : rg.min;
    if (rMax && document.activeElement !== rMax) rMax.value = r.max != null ? r.max : rg.max;
    row.classList.toggle("overridden", r.min != null || r.max != null);
  }

  function RangeFilter() {}

  RangeFilter.prototype.init = function (params) {
    this.params = params;
    this.field = params.colDef.field;
    rangeFilters[this.field] = this;

    var field = this.field;
    var range = colRanges[field] || {};
    var greenHigh = NUMERIC_COLS[field];
    this.range = range;

    this.gui = document.createElement("div");
    this.gui.className = "range-filter";

    var self = this;

    // ⟲ reset header (matches the colour-sidebar icon), always visible in the popup.
    var head = document.createElement("div");
    head.className = "range-head";
    var reset = document.createElement("button");
    reset.type = "button"; reset.className = "th-reset";
    reset.title = "Vymazat rozsah"; reset.setAttribute("aria-label", "Vymazat rozsah " + field);
    reset.textContent = "⟲";
    reset.addEventListener("click", function () { commitRange(field, null, null); });
    head.appendChild(reset);
    this.gui.appendChild(head);

    if (range.min != null && range.max != null && range.max > range.min) {
      var step = range.step || 1;
      this.step = step;
      var slider = document.createElement("div");
      slider.className = "th-slider";
      slider.style.background = heatGradientCSS(heatMode.palette, greenHigh);
      var rMin = document.createElement("input"), rMax = document.createElement("input");
      [rMin, rMax].forEach(function (r) { r.type = "range"; r.min = range.min; r.max = range.max; r.step = step; });
      rMin.setAttribute("aria-label", field + " min");
      rMax.setAttribute("aria-label", field + " max");
      this.rMin = rMin; this.rMax = rMax;
      rMin.addEventListener("input", function () {
        if (+rMin.value > +rMax.value) rMin.value = rMax.value;
        var v = _sliderRound(+rMin.value, step);
        self._edit(v <= range.min ? null : v, undefined);
      });
      rMax.addEventListener("input", function () {
        if (+rMax.value < +rMin.value) rMax.value = rMin.value;
        var v = _sliderRound(+rMax.value, step);
        self._edit(undefined, v >= range.max ? null : v);
      });
      slider.appendChild(rMin); slider.appendChild(rMax);
      this.gui.appendChild(slider);
    }

    var pair = document.createElement("div");
    pair.className = "th-pair";
    // Empty by default (= no filter); placeholder shows the data min/max.
    var minInput = mkNumInput(range.min != null ? fmtRangeNum(field, range.min) : "od");
    var maxInput = mkNumInput(range.max != null ? fmtRangeNum(field, range.max) : "do");
    minInput.className = "th-min"; maxInput.className = "th-max";
    this.minInput = minInput; this.maxInput = maxInput;
    minInput.addEventListener("input", function () { self._edit(parseNum(minInput.value), undefined); });
    maxInput.addEventListener("input", function () { self._edit(undefined, parseNum(maxInput.value)); });
    minInput.addEventListener("change", function () { minInput.value = fmtRangeNum(field, rangeOf(field).min); });
    maxInput.addEventListener("change", function () { maxInput.value = fmtRangeNum(field, rangeOf(field).max); });
    pair.appendChild(minInput); pair.appendChild(maxInput);
    this.gui.appendChild(pair);

    this.renderState();
  };

  RangeFilter.prototype._edit = function (min, max) {
    var r = rangeOf(this.field);
    commitRange(this.field, min === undefined ? r.min : min, max === undefined ? r.max : max);
  };

  RangeFilter.prototype.renderState = function () {
    var r = rangeOf(this.field), rg = this.range || {};
    if (this.rMin && document.activeElement !== this.rMin) this.rMin.value = r.min != null ? r.min : rg.min;
    if (this.rMax && document.activeElement !== this.rMax) this.rMax.value = r.max != null ? r.max : rg.max;
    if (this.minInput && document.activeElement !== this.minInput) this.minInput.value = fmtRangeNum(this.field, r.min);
    if (this.maxInput && document.activeElement !== this.maxInput) this.maxInput.value = fmtRangeNum(this.field, r.max);
  };

  RangeFilter.prototype.doesFilterPass = function (params) {
    var r = rangeOf(this.field);
    var v = params.data[this.field];
    if (v == null || v === "") return false;
    var n = typeof v === "number" ? v : parseFloat(v);    // reference stores some numeric cols as strings
    if (isNaN(n)) return false;
    if (r.min != null && n < r.min) return false;
    if (r.max != null && n > r.max) return false;
    return true;
  };

  RangeFilter.prototype.isFilterActive = function () {
    var r = rangeOf(this.field);
    return r.min != null || r.max != null;
  };

  RangeFilter.prototype.getModel = function () { return rangeModel(this.field); };

  RangeFilter.prototype.setModel = function (model) {
    var min = null, max = null;
    if (model) {
      if (model.type === "inRange") {
        min = model.filter != null ? +model.filter : null;
        max = model.filterTo != null ? +model.filterTo : null;
      } else {
        var v = model.filter != null ? +model.filter : null;
        if (model.type === "greaterThan" || model.type === "greaterThanOrEqual") min = v;
        else if (model.type === "lessThan" || model.type === "lessThanOrEqual") max = v;
        else if (model.type === "equals") { min = v; max = v; }
      }
    }
    setRange(this.field, min, max);
    syncSidebarRow(this.field);
    this.renderState();
    if (gridApi) gridApi.refreshCells({ force: true, columns: [this.field] });
  };

  RangeFilter.prototype.getGui = function () { return this.gui; };
  RangeFilter.prototype.destroy = function () { if (rangeFilters[this.field] === this) delete rangeFilters[this.field]; };

  RangeFilter.prototype.getModelAsString = function () {
    var r = rangeOf(this.field);
    if (r.min == null && r.max == null) return "";
    var f = function (n) { return fmtRangeNum(this.field, n); }.bind(this);
    if (r.min != null && r.max != null) return f(r.min) + "–" + f(r.max);
    if (r.min != null) return "≥ " + f(r.min);
    return "≤ " + f(r.max);
  };

  RangeFilter.prototype.afterGuiAttached = function () {
    if (this.minInput) this.minInput.focus();
  };

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

  // Date columns (Přidáno/Upraveno) hold ISO "YYYY-MM-DD" strings, so
  // agDateColumnFilter needs a comparator to compare them against its Date entry.
  // Mirror of site/app.js "Odstraněno dne" — see gotchas → site → date filters.
  // Parse into a LOCAL-midnight Date (new Date("2026-07-11") is UTC midnight and
  // shifts a day in negative-offset zones, breaking equality). browserDatePicker
  // must be false EXPLICITLY (AG defaults it true where <input type=date> exists),
  // else the native picker renders in the browser locale, not the ISO the cells show.
  function maskDateEntry(el) {
    var digits = el.value.replace(/\D/g, "").slice(0, 8);
    var out = digits.slice(0, 4);
    if (digits.length > 4) out += "-" + digits.slice(4, 6);
    if (digits.length > 6) out += "-" + digits.slice(6, 8);
    return out;
  }
  document.addEventListener("input", function (e) {
    var el = e.target;
    if (!el || el.tagName !== "INPUT" || !el.closest || !el.closest(".ag-date-filter")) return;
    var masked = maskDateEntry(el);
    if (el.value !== masked) el.value = masked;
  }, true);

  var DATE_FILTER_PARAMS = {
    browserDatePicker: false,
    buttons: ["reset"],
    inRangeInclusive: true,  // "between these dates" — AG defaults to exclusive bounds
    comparator: function (filterDate, cellValue) {
      if (!cellValue) return -1;
      var p = String(cellValue).split("-");
      if (p.length !== 3) return -1;
      var cell = new Date(+p[0], +p[1] - 1, +p[2]);
      var d = cell.getTime() - filterDate.getTime();
      return d < 0 ? -1 : d > 0 ? 1 : 0;
    },
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
    { field: "Model auta", filter: "agTextColumnFilter", width: 260 },
    {
      field: "Nabídek", headerName: "Počet nabídek", filter: RangeFilter, width: 140, headerClass: "ag-header-cell-center",
      cellClass: "rc-count-cell", cellRenderer: nabidekRenderer,
      headerTooltip: "Počet inzerátů, které se aktuálně párují s tímto referenčním modelem (spárováno Ano / Nejisté). Klik na buňku otevře tyto inzeráty v tabulce.",
    },
    {
      field: "Cena medián", headerName: "Cena na trhu", filter: RangeFilter, width: 340,
      cellClass: "rc-price-cell", cellRenderer: priceCellRenderer,
      headerTooltip: "Cenové rozpětí spárovaných inzerátů (tis. Kč) na společné ose 100–800.\nPohled přepneš v liště: Kompaktní / Box-plot / Histogram. Filtr a řazení jsou dle mediánu ceny.\nKlik na buňku → detail s histogramem a odkazy na nejlevnější/nejdražší inzerát.",
    },
    { field: "Verze", filter: SetFilter, width: 110, headerClass: "ag-header-cell-center", headerTooltip: "Verze/výbava dle referenčního záznamu. Prázdné, pokud pro tento model není určena." },
    { field: "Typ", filter: SetFilter, width: 100, headerClass: "ag-header-cell-center" },
    { field: "Palivo", filter: SetFilter, width: 100, headerClass: "ag-header-cell-center" },
    { field: "Spotřeba (l/100 km)", filter: RangeFilter, width: 120, type: "numericColumn", headerTooltip: "Průměrná spotřeba dle WLTP. V praxi bývá o 10–20 % vyšší.\nU plug-in hybridů (PHEV) je prázdná: oficiální WLTP hodnota (~1 l/100 km) předpokládá nabitou baterii a je zavádějící.\nBarva buňky: zelená = nižší spotřeba, červená = vyšší." },
    { field: "Objem kufru (l)", filter: RangeFilter, width: 110, type: "numericColumn", headerTooltip: "Barva buňky: zelená = větší kufr, červená = menší." },
    { field: "Výkon (kW)", filter: RangeFilter, width: 100, type: "numericColumn", headerTooltip: "Barva buňky: zelená = vyšší výkon, červená = nižší." },
    { field: "Objem motoru", filter: RangeFilter, width: 110, type: "numericColumn", headerTooltip: "Zdvihový objem spalovacího motoru v litrech." },
    { field: "Typ motoru", filter: SetFilter, width: 110, headerClass: "ag-header-cell-center" },
    { field: "Hybrid typ", filter: SetFilter, width: 110, headerClass: "ag-header-cell-center", headerTooltip: "MHEV = mild hybrid (rekuperace, bez čistě EV jízdy), HEV = plný hybrid (krátkodobě EV jízda), PHEV = plug-in hybrid (nabíjecí ze zásuvky)." },
    { field: "Karoserie", filter: SetFilter, width: 120, headerClass: "ag-header-cell-center" },
    { field: "Cd", filter: RangeFilter, width: 90, type: "numericColumn", headerName: "Odpor vzduchu (%)", headerTooltip: "Nižší = lepší aerodynamika.\nBarva buňky: zelená = nižší (lepší), červená = vyšší." },
    { field: "Cd zdroj", filter: SetFilter, width: 120, headerClass: "ag-header-cell-center", headerName: "Zdroj odporu vzduchu", headerTooltip: "reálné = naměřená hodnota (výrobce / Wikipedia / ev-database), odhad = odhad dle tvaru karoserie (~42 % hodnot)." },
    { field: "Hlučnost (dB)", filter: RangeFilter, width: 100, type: "numericColumn", headerTooltip: "Hlučnost kabiny dle WLTP. Nižší = tišší.\n< 65 dB výborné, 65–70 dB dobré, > 70 dB hlučné.\nPrůměrné auto při 120 km/h: cca 68–72 dB.\nBarva buňky: zelená = tišší, červená = hlučnější." },
    { field: "Kapacita baterie (kWh)", filter: RangeFilter, width: 130, type: "numericColumn", headerTooltip: "Použitelná kapacita trakční baterie.\nBarva buňky: zelená = větší kapacita, červená = menší." },
    { field: "Dojezd WLTP (km)", filter: RangeFilter, width: 120, type: "numericColumn", headerTooltip: "WLTP – standardizovaný laboratorní test (cyklus 0–131 km/h, teplota 23 °C). Výsledky bývají optimistické; reálný dojezd o 10–30 % nižší.\nBarva buňky: zelená = delší dojezd, červená = kratší." },
    { field: "Dojezd EV-database (km)", filter: RangeFilter, width: 140, type: "numericColumn", headerTooltip: "Reálný dojezd dle ev-database.com – realističtější než WLTP.\nBarva buňky: zelená = delší dojezd, červená = kratší." },
    { field: "Tepelné čerpadlo možné", filter: SetFilter, width: 130, headerClass: "ag-header-cell-center", headerTooltip: "Lze doobjednat tepelné čerpadlo jako příplatek." },
    { field: "Přidáno", filter: "agDateColumnFilter", filterParams: DATE_FILTER_PARAMS, width: 110, headerClass: "ag-header-cell-center", headerTooltip: "Datum, kdy byl tento referenční řádek poprvé přidán (dle git historie)." },
    { field: "Upraveno", filter: "agDateColumnFilter", filterParams: DATE_FILTER_PARAMS, width: 110, headerClass: "ag-header-cell-center", headerTooltip: "Datum poslední změny obsahu tohoto referenčního řádku (dle git historie)." },
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
    "Objem motoru": true,
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

  // Forced slider precision (decimals) for columns where the data precision is
  // not the desired step — overrides the auto-detected value in computeRanges.
  var STEP_DECIMALS = {
    "Spotřeba (l/100 km)": 0,
    "Hlučnost (dB)": 0,
    "Kapacita baterie (kWh)": 0,
    "Výkon (kW)": 0,
    "Objem motoru": 1,
  };
  // Absolute slider step (overrides the data-precision step). Prices are whole Kč, but
  // a 1-Kč step on a ~750 000 range is meaningless — step by thousands, no decimals.
  var STEP_VALUES = {
    "Cena medián": 1000,
  };

  // Decimal places a value carries, float-noise-tolerant, capped at 3.
  function _decimals(n) {
    if (!isFinite(n) || n === Math.round(n)) return 0;
    var s = n.toFixed(3).replace(/0+$/, "");
    var i = s.indexOf(".");
    return i < 0 ? 0 : s.length - i - 1;
  }

  function computeRanges(data) {
    colRanges = {};
    // NUMERIC_COLS drives heat + drawer; RANGE_EXTRA (Nabídek, Cena medián) only needs
    // a colRanges entry so its column-filter RangeFilter works (no heat, no drawer row).
    var fields = Object.keys(NUMERIC_COLS).concat(RANGE_EXTRA);
    for (var i = 0; i < fields.length; i++) {
      var field = fields[i];
      var min = Infinity, max = -Infinity, dec = 0;
      for (var j = 0; j < data.length; j++) {
        var v = data[j][field];
        // reference.json stores some numeric columns as strings ("150") —
        // coerce so Výkon/Objem kufru get a real range (and thus a slider).
        var n = typeof v === "number" ? v : (v != null && v !== "" ? parseFloat(v) : NaN);
        if (isFinite(n)) {
          if (n < min) min = n;
          if (n > max) max = n;
          var d = _decimals(n);
          if (d > dec) dec = d;
        }
      }
      // Slider step = the data's own precision (integer cols step by 1, etc.),
      // unless STEP_DECIMALS forces it.
      if (STEP_DECIMALS[field] != null) dec = STEP_DECIMALS[field];
      var step = STEP_VALUES[field] != null ? STEP_VALUES[field] : Math.pow(10, -dec);
      if (min !== Infinity) colRanges[field] = { min: min, max: max, step: step };
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

  // ── "Spárované vozy & rozpětí cen": Nabídek count + the three-view price cell ──
  // Not heat-styled (price is not a good→bad axis), so these live outside NUMERIC_COLS
  // and paint via custom cellRenderers. RANGE_EXTRA gives them a colRanges entry so the
  // column-filter RangeFilter still works (filter by count / by median price).
  var RANGE_EXTRA = ["Nabídek", "Cena medián"];

  function pricePct(v) {
    if (v == null) return 0;
    return Math.max(0, Math.min(100, (v - PRICE_AXIS_MIN) / (PRICE_AXIS_MAX - PRICE_AXIS_MIN) * 100));
  }
  function fmtTis(v) {  // Kč → integer thousands ("603")
    if (v == null || isNaN(v)) return "";
    return Math.round(Number(v) / 1000).toLocaleString("cs-CZ");
  }
  function fmtKc(v) {
    if (v == null || isNaN(v)) return "";
    return Math.round(Number(v)).toLocaleString("cs-CZ") + " Kč";
  }
  // The popup embeds a model name into markup and scraped listing URLs into href;
  // both are build-time data, but escape defensively (XSS): text → entity-escape,
  // href → allow only http(s) and neutralise a quote break-out.
  function escHtml(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  function safeHref(u) {
    u = String(u == null ? "" : u);
    return /^https?:\/\//i.test(u) ? u.replace(/"/g, "%22") : "";
  }

  // Build an index.html URL filtered to this reference model's listings, using the
  // index grid's own columns (Značka + Model, both mirror the payload split, plus the
  // ICE engine cols). Reproduces the pairing closely; not variant-exact for ICE bodies
  // that share an engine. EV matches by nameplate (Model contains). Encoded with the
  // shared url-state codec so it decodes on index.html exactly like a shared link.
  function indexFilterModel(d) {
    var znacka = d["Značka"], model = d["Model"];
    if (!znacka) return null;
    var m = { "Značka": { filterType: "set", values: [znacka] } };
    if (d["Typ"] === "Spalovací") {
      if (model) m["Model"] = { filterType: "text", type: "equals", filter: model };
      if (d["Objem motoru"] != null) m["Objem motoru"] = { filterType: "number", type: "equals", filter: d["Objem motoru"] };
      if (d["Typ motoru"]) m["Typ motoru"] = { filterType: "set", values: [d["Typ motoru"]] };
    } else if (model) {
      m["Model"] = { filterType: "text", type: "contains", filter: model };
    }
    return m;
  }
  function indexUrlForRef(d) {
    var m = indexFilterModel(d);
    if (!m || !window.UrlState) return "index.html";
    var f = window.UrlState.encFilters(m);
    return f ? "index.html#f=" + f : "index.html";
  }
  function openIndexForRef(d) {
    if (d && d["Nabídek"]) window.open(indexUrlForRef(d), "_blank", "noopener");
  }

  function nabidekRenderer(params) {
    var n = params.value || 0;
    var el = document.createElement("div");
    el.className = "rc-count";
    if (!n) { el.innerHTML = '<span class="rc-count-n rc-muted">0</span>'; return el; }
    var w = Math.max(3, Math.min(100, n / maxNabidek * 100));
    // Bar left, count hard-right — so a 4-digit count ("3 870") never overflows the
    // cell's left edge (it did when the number led and the bar followed).
    el.innerHTML =
      '<span class="rc-count-bar"><span style="width:' + w.toFixed(1) + '%"></span></span>' +
      '<span class="rc-count-n">' + n.toLocaleString("cs-CZ") + '</span>';
    return el;
  }

  // A ">" cap when a model's max exceeds the shared axis (rare luxury outliers —
  // 99.96% of listings are ≤750k). The bar clamps to the edge but the true value
  // still shows in the label / popup, so the clamp is never a silent lie.
  function overflowMark(hi) {
    return hi > PRICE_AXIS_MAX ? '<span class="rc-of" title="Maximum přesahuje osu (viz štítek)">›</span>' : '';
  }
  function compactPriceHTML(lo, med, hi) {
    var l = pricePct(lo), r = pricePct(hi), m = pricePct(med);
    return '<div class="rc-rng-text"><span class="rc-ends">' + fmtTis(lo) + '</span> – ' +
      '<span class="rc-med">' + fmtTis(med) + '</span> – <span class="rc-ends">' + fmtTis(hi) + '</span></div>' +
      '<div class="rc-spark"><span class="rc-spark-fill" style="left:' + l + '%;width:' + (r - l) + '%"></span>' +
      '<span class="rc-spark-m" style="left:' + m + '%"></span>' + overflowMark(hi) + '</div>';
  }
  function boxplotPriceHTML(lo, q1, med, q3, hi) {
    var l = pricePct(lo), r = pricePct(hi), a = pricePct(q1), b = pricePct(q3), m = pricePct(med);
    return '<div class="rc-band"><div class="rc-band-track"></div>' +
      '<div class="rc-whisker" style="left:' + l + '%;width:' + (r - l) + '%"></div>' +
      '<div class="rc-cap" style="left:' + l + '%"></div><div class="rc-cap" style="left:' + r + '%"></div>' +
      '<div class="rc-box" style="left:' + a + '%;width:' + (b - a) + '%"></div>' +
      '<div class="rc-median" style="left:' + m + '%"></div>' + overflowMark(hi) + '</div>' +
      '<div class="rc-band-labels"><span>' + fmtTis(lo) + '</span><span class="rc-med">' + fmtTis(med) +
      '</span><span>' + fmtTis(hi) + '</span></div>';
  }
  function barsHTML(hist, med) {
    hist = hist || [];
    var hm = 1;
    for (var i = 0; i < hist.length; i++) if (hist[i] > hm) hm = hist[i];
    var bars = "";
    for (var j = 0; j < hist.length; j++) {
      if (!hist[j]) bars += '<span class="rc-bar rc-bar-empty"></span>';
      else bars += '<span class="rc-bar" style="height:' + Math.max(8, hist[j] / hm * 100).toFixed(0) + '%"></span>';
    }
    return '<div class="rc-bars">' + bars + '<span class="rc-hist-med" style="left:' + pricePct(med) + '%"></span></div>';
  }
  function histogramPriceHTML(hist, lo, med, hi) {
    return '<div class="rc-hist">' + barsHTML(hist, med) + overflowMark(hi) + '</div>' +
      '<div class="rc-band-labels"><span>' + fmtTis(lo) + '</span><span class="rc-med">' + fmtTis(med) +
      '</span><span>' + fmtTis(hi) + '</span></div>';
  }

  function priceCellRenderer(params) {
    var d = params.data || {};
    var el = document.createElement("div");
    el.className = "rc-price rc-price-" + priceView;
    if (!d["Nabídek"]) { el.innerHTML = '<span class="rc-muted">—</span>'; return el; }
    var lo = d["Cena min"], q1 = d["Cena p25"], med = d["Cena medián"], q3 = d["Cena p75"], hi = d["Cena max"];
    if (priceView === "boxplot") el.innerHTML = boxplotPriceHTML(lo, q1, med, q3, hi);
    else if (priceView === "histogram") el.innerHTML = histogramPriceHTML(d["Cena histogram"], lo, med, hi);
    else el.innerHTML = compactPriceHTML(lo, med, hi);
    el.title = "Klikněte pro detail cen";
    return el;
  }

  // View toggle — one uniform rowHeight per mode keeps every grid row equal-height.
  function loadPriceView() {
    try { var v = localStorage.getItem(PRICE_VIEW_KEY); if (PRICE_ROW_HEIGHTS[v]) priceView = v; } catch (_) {}
  }
  function updatePriceViewButtons() {
    var wrap = document.getElementById("price-view-toggle");
    if (!wrap) return;
    var btns = wrap.querySelectorAll("button");
    for (var i = 0; i < btns.length; i++) btns[i].classList.toggle("on", btns[i].dataset.view === priceView);
  }
  window.setPriceView = function (v) {
    if (!PRICE_ROW_HEIGHTS[v]) return;
    priceView = v;
    try { localStorage.setItem(PRICE_VIEW_KEY, v); } catch (_) {}
    updatePriceViewButtons();
    if (gridApi) {
      gridApi.setGridOption("rowHeight", PRICE_ROW_HEIGHTS[v]);
      gridApi.resetRowHeights();  // re-apply the single height to ALL rows
      gridApi.refreshCells({ force: true, columns: ["Cena medián"] });
    }
  };

  // ── Price detail popup (click a "Cena na trhu" cell) ──
  function openPricePopup(d, ev) {
    var pop = document.getElementById("price-popup");
    if (!pop || !d || !d["Nabídek"]) return;
    var lo = d["Cena min"], med = d["Cena medián"], hi = d["Cena max"], n = d["Nabídek"];
    var hist = d["Cena histogram"] || [];
    var hm = 1;
    for (var i = 0; i < hist.length; i++) if (hist[i] > hm) hm = hist[i];
    var bars = "";
    for (var j = 0; j < hist.length; j++) {
      bars += hist[j]
        ? '<span class="pp-bar" style="height:' + Math.max(6, hist[j] / hm * 100).toFixed(0) + '%" title="' + (hist[j]).toLocaleString("cs-CZ") + '"></span>'
        : '<span class="pp-bar pp-bar-empty"></span>';
    }
    var idxUrl = indexUrlForRef(d);
    var links = '<a class="pp-link" href="' + idxUrl + '" target="_blank" rel="noopener">' +
      '<span class="pp-lbl">Zobrazit v tabulce</span><span class="pp-val">' + n.toLocaleString("cs-CZ") + ' inzerátů →</span></a>';
    pop.innerHTML =
      '<div class="pp-head"><span class="pp-model">' + escHtml(d["Model auta"]) + '</span>' +
      '<button class="pp-close" id="pp-close" title="Zavřít" aria-label="Zavřít">&times;</button></div>' +
      '<div class="pp-body">' +
      '<div class="pp-stats">' +
      '<div class="pp-stat"><div class="pp-v">' + fmtTis(lo) + '<span class="pp-u">tis</span></div><div class="pp-l">od</div></div>' +
      '<div class="pp-stat pp-hl"><div class="pp-v">' + fmtTis(med) + '<span class="pp-u">tis</span></div><div class="pp-l">medián</div></div>' +
      '<div class="pp-stat"><div class="pp-v">' + fmtTis(hi) + '<span class="pp-u">tis</span></div><div class="pp-l">do</div></div>' +
      '</div>' +
      '<h4 class="pp-h4">Rozdělení cen <span class="pp-sub">tis. Kč · osa 100–800, medián ' + fmtTis(med) + '</span></h4>' +
      '<div class="pp-chart">' +
      '<div class="pp-yaxis"><span>' + hm.toLocaleString("cs-CZ") + '</span><span>0</span></div>' +
      '<div class="pp-plot">' +
      '<div class="pp-hist">' + bars + '<span class="pp-hist-med" style="left:' + pricePct(med) + '%"></span>' + overflowMark(hi) + '</div>' +
      '<div class="pp-axis"><span>' + fmtTis(PRICE_AXIS_MIN) + '</span><span>' + fmtTis(PRICE_AXIS_MAX) + '</span></div>' +
      '</div></div>' +
      '<div class="pp-links">' + links + '</div>' +
      '</div>';
    var closeBtn = document.getElementById("pp-close");
    if (closeBtn) closeBtn.addEventListener("click", function (e) { e.stopPropagation(); closePricePopup(); });
    pop.classList.remove("hidden");
    // Position near the click, clamped to the viewport.
    var pw = 320, ph = pop.offsetHeight || 320;
    var x = ev ? ev.clientX : window.innerWidth / 2;
    var y = ev ? ev.clientY : 120;
    var left = Math.min(Math.max(8, x + 12), window.innerWidth - pw - 8);
    var top = Math.min(Math.max(8, y + 12), window.innerHeight - ph - 8);
    pop.style.left = left + "px";
    pop.style.top = top + "px";
  }
  function closePricePopup() {
    var pop = document.getElementById("price-popup");
    if (pop) pop.classList.add("hidden");
  }
  function _findRow(model) {
    var found = null;
    if (gridApi) gridApi.forEachNode(function (node) { if (!found && node.data && node.data["Model auta"] === model) found = node.data; });
    return found;
  }
  // Test hooks for build/verify_ui.py.
  window.__openPricePopup = function (model) {
    var found = _findRow(model);
    if (found) { openPricePopup(found, null); return true; }
    return false;
  };
  window.__indexUrlForRef = function (model) {
    var found = _findRow(model);
    return found ? indexUrlForRef(found) : null;
  };

  // ── Colour settings: threshold system + heat-mode drawer (mirrors app.js) ──
  function loadThresholds() {
    try {
      var s = localStorage.getItem(THRESHOLD_KEY);
      userThresholds = s ? JSON.parse(s) : {};
    } catch (_) { userThresholds = {}; }
  }

  // Reference keeps thresholds in localStorage only; state now flows through
  // commitRange, so this only re-persists + repaints the current shared state.
  window.saveThresholds = function () {
    persistThresholds();
    if (gridApi) gridApi.refreshCells({ force: true });
  };

  // Reset ALL columns: clears every colour threshold AND its coupled range filter.
  window.resetThresholds = function () {
    var fields = Object.keys(userThresholds);
    userThresholds = {};
    try { localStorage.removeItem(THRESHOLD_KEY); } catch (_) {}
    renderThresholdInputs();
    if (gridApi) {
      fields.forEach(function (f) { gridApi.setColumnFilterModel(f, null); });
      gridApi.refreshCells({ force: true });
      gridApi.onFilterChanged();
    }
  };

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
      var r = rangeOf(field);
      var range = colRanges[field] || {};
      var greenHigh = NUMERIC_COLS[field];

      var row = document.createElement("div");
      row.className = "threshold-row" + ((r.min != null || r.max != null) ? " overridden" : "");
      row.dataset.field = field;

      var labelWrap = document.createElement("div");
      labelWrap.className = "th-label";
      var name = document.createElement("span");
      name.textContent = field;
      var dir = document.createElement("span");
      dir.className = "th-dir";
      dir.textContent = greenHigh ? "více = lépe" : "méně = lépe";
      labelWrap.appendChild(name); labelWrap.appendChild(dir);
      var reset = document.createElement("button");
      reset.type = "button"; reset.className = "th-reset";
      reset.title = "Vymazat rozsah"; reset.setAttribute("aria-label", "Vymazat rozsah " + field);
      reset.textContent = "⟲";
      reset.addEventListener("click", function () { commitRange(field, null, null); });
      labelWrap.appendChild(reset);
      row.appendChild(labelWrap);

      var minInput = mkNumInput(range.min != null ? fmtRangeNum(field, range.min) : "min");
      var maxInput = mkNumInput(range.max != null ? fmtRangeNum(field, range.max) : "max");
      minInput.className = "th-min"; maxInput.className = "th-max";
      minInput.value = fmtRangeNum(field, r.min);
      maxInput.value = fmtRangeNum(field, r.max);
      minInput.addEventListener("input", function () { commitRange(field, parseNum(minInput.value), rangeOf(field).max); });
      maxInput.addEventListener("input", function () { commitRange(field, rangeOf(field).min, parseNum(maxInput.value)); });
      minInput.addEventListener("change", function () { minInput.value = fmtRangeNum(field, rangeOf(field).min); });
      maxInput.addEventListener("change", function () { maxInput.value = fmtRangeNum(field, rangeOf(field).max); });

      // Dual-range slider; shares state with the number boxes and the column-filter
      // slider via commitRange; a thumb at the data edge clears that bound (= open).
      if (range.min != null && range.max != null && range.max > range.min) {
        var slider = document.createElement("div");
        slider.className = "th-slider";
        slider.style.background = heatGradientCSS(heatMode.palette, greenHigh);
        var step = range.step || 1;
        var rMin = document.createElement("input");
        var rMax = document.createElement("input");
        [rMin, rMax].forEach(function (rr) {
          rr.type = "range"; rr.min = range.min; rr.max = range.max; rr.step = step;
        });
        rMin.className = "th-range-min"; rMax.className = "th-range-max";
        rMin.value = r.min != null ? r.min : range.min;
        rMax.value = r.max != null ? r.max : range.max;
        rMin.setAttribute("aria-label", field + " min");
        rMax.setAttribute("aria-label", field + " max");
        rMin.addEventListener("input", function () {
          if (+rMin.value > +rMax.value) rMin.value = rMax.value;
          var v = _sliderRound(+rMin.value, step);
          commitRange(field, v <= range.min ? null : v, rangeOf(field).max);
        });
        rMax.addEventListener("input", function () {
          if (+rMax.value < +rMin.value) rMax.value = rMin.value;
          var v = _sliderRound(+rMax.value, step);
          commitRange(field, rangeOf(field).min, v >= range.max ? null : v);
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
    // Price popup closes on any click outside it and outside the cell that opened it.
    if (!c("#price-popup") && !c(".rc-price-cell") && !c(".rc-count-cell")) closePricePopup();
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") { closeToolsMenu(); window.closeColorSettings(); closePricePopup(); }
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
    loadPriceView();
    totalRowCount = data.length;

    incompleteCount = 0;
    maxNabidek = 1;
    for (var r = 0; r < data.length; r++) {
      var missing = computeMissingSpecs(data[r]);
      data[r]._missing = missing;
      data[r]._missingCount = missing.length;
      if (missing.length) incompleteCount++;
      if (data[r]["Nabídek"] > maxNabidek) maxNabidek = data[r]["Nabídek"];
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
        before: "Před", after: "Po",  // agDateColumnFilter relabels lessThan/greaterThan
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
      rowHeight: PRICE_ROW_HEIGHTS[priceView],
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
      onCellClicked: function (e) {
        var f = e.colDef && e.colDef.field;
        if (!e.data || !e.data["Nabídek"]) return;
        // Count cell → open the paired listings in the index table; price cell → price popup.
        if (f === "Nabídek") openIndexForRef(e.data);
        else if (f === "Cena medián") openPricePopup(e.data, e.event);
      },
      onGridReady: function (params) {
        gridApi = params.api;
        window.__gridApi = params.api;

        var hash = U.parseHash();
        var legacyFilters = hash.f ? null : U.decodeLegacyFilters();

        // Column layout: localStorage only (never the URL).
        var colState = loadColStateFromStorage();
        if (colState) applyColState(colState);

        // Filters: URL fragment (#f=) → legacy ?filters= → localStorage.
        // The filter store is the sole source of truth for which columns filter;
        // colour thresholds only tint. A colour-only threshold must NOT be re-armed
        // as a filter on load (that resurrected filters cleared via the chip ×).
        var urlFilters = hash.f ? U.decFilters(hash.f) : legacyFilters;
        var filters = urlFilters || loadFiltersFromStorage();
        if (filters) gridApi.setFilterModel(filters);

        // Migrate an old ?filters= link to the canonical #fragment form.
        if (legacyFilters) writeHash();

        updateIncompleteButton();
        updatePriceViewButtons();
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

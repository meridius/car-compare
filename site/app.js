// Payload is parquet (129 MB JSON → ~8 MB, decode 9 s → ~1.5 s at 141k rows).
// hyparquet decodes snappy natively — keep cars.parquet snappy-compressed and
// this stays the only import. Pin the version: the unpinned jsdelivr URL serves
// a stale cached build. See docs/decisions/001-scalable-storage.md.
import { parquetReadObjects } from "https://cdn.jsdelivr.net/npm/hyparquet@1.26.2/+esm";

(function () {
  "use strict";

  var STORAGE_KEY = "carCompareFilters";
  var THRESHOLD_KEY = "carCompareThresholds";
  var THEME_KEY = "carCompareTheme";
  var COL_STATE_KEY = "carCompareColState";
  var HEATMODE_KEY = "carCompareHeatMode";

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    var glyph = document.querySelector("#btn-theme .theme-glyph");
    if (glyph) glyph.textContent = theme === "dark" ? "\u263E" : "\u2600";
    var gridEl = document.getElementById("grid");
    if (gridEl) {
      gridEl.classList.remove("ag-theme-alpine", "ag-theme-alpine-dark");
      gridEl.classList.add(theme === "dark" ? "ag-theme-alpine-dark" : "ag-theme-alpine");
    }
    // Heat colours are theme-aware (see heatColor) \u2014 re-tint on theme change.
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

  // Custom multi-select set filter (AG Grid Community replacement for Enterprise agSetColumnFilter)
  function SetFilter() {}

  SetFilter.prototype.init = function (params) {
    this.params = params;
    this.field = params.colDef.field;
    this.filterActive = false;
    this.selected = null;

    var valuesMap = {};
    var blankCount = 0;
    params.api.forEachNode(function (node) {
      if (!node.data) return;
      var val = node.data[params.colDef.field];
      if (val == null || val === "") blankCount++;
      else valuesMap[val] = (valuesMap[val] || 0) + 1;
    });
    this.uniqueValues = Object.keys(valuesMap).sort(function (a, b) {
      return a.localeCompare(b, "cs");
    });
    this.hasBlank = blankCount > 0;
    this.blankCount = blankCount;
    this.valuesMap = valuesMap;

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

    var fp = params.colDef && params.colDef.filterParams;
    var groupDefs = fp && fp.groups;
    this.groupHeaders = [];

    if (this.hasBlank) {
      var blankItem = this._makeItem("(Pr\u00e1zdn\u00e9)", null, true, this.blankCount);
      listDiv.appendChild(blankItem.div);
      this.checkboxes.push(blankItem);
    }

    if (groupDefs) {
      var covered = {};
      for (var g = 0; g < groupDefs.length; g++) {
        var grp = groupDefs[g];
        var grpItems = [];
        var headerEl = document.createElement("div");
        headerEl.className = "set-filter-group-header";
        headerEl.textContent = grp.label;
        listDiv.appendChild(headerEl);
        for (var k = 0; k < grp.values.length; k++) {
          var gv = grp.values[k];
          covered[gv] = true;
          if (!(gv in this.valuesMap)) continue;
          var gitem = this._makeItem(gv, gv, true, this.valuesMap[gv]);
          listDiv.appendChild(gitem.div);
          this.checkboxes.push(gitem);
          grpItems.push(gitem);
        }
        this.groupHeaders.push({ el: headerEl, items: grpItems });
      }
      for (var i = 0; i < this.uniqueValues.length; i++) {
        var uv = this.uniqueValues[i];
        if (covered[uv]) continue;
        var uitem = this._makeItem(uv, uv, true, this.valuesMap[uv]);
        listDiv.appendChild(uitem.div);
        this.checkboxes.push(uitem);
      }
    } else {
      for (var i = 0; i < this.uniqueValues.length; i++) {
        var v = this.uniqueValues[i];
        var item = this._makeItem(v, v, true, this.valuesMap[v]);
        listDiv.appendChild(item.div);
        this.checkboxes.push(item);
      }
    }
    this.gui.appendChild(listDiv);

    var self = this;
    searchInput.addEventListener("input", function () { self._filter(); });
    btnAll.addEventListener("click", function () { self._toggleAll(true); });
    btnNone.addEventListener("click", function () { self._toggleAll(false); });
  };

  SetFilter.prototype._makeItem = function (label, value, checked, count) {
    var div = document.createElement("label");
    div.className = "set-filter-item";
    var cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = checked;
    var span = document.createElement("span");
    span.textContent = label;
    div.appendChild(cb);
    div.appendChild(span);
    if (count != null) {
      var badge = document.createElement("span");
      badge.className = "set-filter-count";
      badge.textContent = count;
      div.appendChild(badge);
    }
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
    for (var g = 0; g < this.groupHeaders.length; g++) {
      var gh = this.groupHeaders[g];
      var anyVisible = false;
      for (var j = 0; j < gh.items.length; j++) {
        if (gh.items[j].div.style.display !== "none") { anyVisible = true; break; }
      }
      gh.el.style.display = anyVisible ? "" : "none";
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

  function ColTooltip() {}
  ColTooltip.prototype.init = function (params) {
    this.eGui = document.createElement("div");
    this.eGui.className = "col-tooltip";
    this.eGui.textContent = params.value;
  };
  ColTooltip.prototype.getGui = function () { return this.eGui; };
  ColTooltip.prototype.destroy = function () {};

  // ── Numeric range: ONE shared state drives BOTH colouring and filtering. ──
  // userThresholds[field] = {min,max} is the single source of truth. The colour-
  // settings slider (Nastavení barev drawer) and the column-filter slider (this
  // RangeFilter popup) are two views of that same value — edit either and the
  // other updates live, the heat-map recolours, and rows filter. Every editor
  // (either slider, either number box, either reset) routes through commitRange().
  //
  // The filter side emits the STANDARD AG number model ({type:"inRange",filter,
  // filterTo}, null bound = open), so the URL codec (url-state.js), filter chips
  // and localStorage persistence all work unchanged.

  // cs-CZ thousands separator for display; parse tolerates spaces/NBSP + comma.
  function fmtRangeNum(field, v) {
    if (v == null || v === "" || isNaN(v)) return "";
    var group = field !== "Rok výroby";   // a year is not a thousand
    return Number(v).toLocaleString("cs-CZ", { useGrouping: group, maximumFractionDigits: 3 });
  }
  function parseNum(s) {
    if (s == null) return null;
    s = String(s).replace(/[\s  ]/g, "").replace(",", ".");
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

  var rangeFilters = {};   // field -> live RangeFilter instance (for cross-view sync)
  var _rangeTimers = {};

  // The one entry point every range editor calls. Updates shared state, mirrors it
  // into BOTH views (skipping whatever control the user is touching), then debounces
  // the expensive part — recolour + (re)activate the grid filter — off the 152k-row
  // hot path so dragging stays smooth.
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
        // setColumnFilterModel instantiates + activates the filter even if its popup
        // was never opened (e.g. edited from the colour drawer). Its setModel writes
        // the same state back — idempotent, no loop.
        gridApi.setColumnFilterModel(field, rangeModel(field)).then(function () {
          gridApi.onFilterChanged();
        });
      }
    }, 220);
  }

  // Mirror shared state into the colour-drawer row for `field` (if rendered).
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

  // Change one bound (undefined = leave the other as-is), keeping the paired value.
  RangeFilter.prototype._edit = function (min, max) {
    var r = rangeOf(this.field);
    commitRange(this.field, min === undefined ? r.min : min, max === undefined ? r.max : max);
  };

  // Mirror shared state into this popup's own controls (skip the focused one).
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
    if (v == null || v === "") return false;              // blanks fail when active (AG number default)
    var n = typeof v === "number" ? v : parseFloat(v);    // some columns arrive as numeric strings
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
        // Tolerate simple bound models (e.g. a legacy greaterThanOrEqual link).
        var v = model.filter != null ? +model.filter : null;
        if (model.type === "greaterThan" || model.type === "greaterThanOrEqual") min = v;
        else if (model.type === "lessThan" || model.type === "lessThanOrEqual") max = v;
        else if (model.type === "equals") { min = v; max = v; }
      }
    }
    setRange(this.field, min, max);       // no commitRange → no debounce/loop; AG drives the filter pass
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

  var STAV_GROUPS = [
    { label: "Dostupné", values: ["Dostupný", "Nové", "Předváděcí", "Ojeté", "Havarované"] },
    { label: "Nedostupné", values: ["Zamluvené", "Prodané", "Odstraněno"] },
  ];

  // Date columns hold ISO "YYYY-MM-DD" strings (stringly payload — see gotchas).
  // agDateColumnFilter needs a comparator to compare those against the entry Date.
  // Parse the parts manually into a LOCAL-midnight Date: new Date("2026-07-11")
  // would parse as UTC midnight and shift a day in negative-offset zones, breaking
  // equality. Blank cells sort before any date (returned -1) → excluded by after/range.
  //
  // browserDatePicker: false is REQUIRED, not just omittable — AG defaults it to
  // true whenever the browser supports <input type=date>, and that native input
  // renders in the browser's locale (dd.mm.yyyy / mm/dd/yyyy — never the ISO the
  // cells show) with an untranslatable "Clear" chrome button. AG's own text input
  // defaults to the yyyy-mm-dd format, matching the cells exactly, and its only
  // clear control is the Czech "Vymazat" reset button below.
  // Digit-mask the date filter's entry field(s): AG's own agDateColumnFilter text
  // input (browserDatePicker off) already shows the yyyy-mm-dd placeholder we want,
  // but accepts any text. This capture-phase listener strips non-digits and
  // auto-inserts the two dashes as the user types, BEFORE AG's own input handler
  // (target phase) reads the value — so AG only ever parses a clean yyyy-mm-dd.
  // Scoped to `.ag-date-filter` inputs (only the "Odstraněno dne" column has one);
  // delegated on document so it survives the filter popup being re-created.
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
    // AG's inRange defaults to EXCLUSIVE bounds (inRangeInclusive:false → strict
    // </>). With day-granular dates that makes a range like [08-07, 09-07] match
    // nothing — both endpoints excluded, nothing strictly between. Inclusive is
    // what a user means by "between these two dates".
    inRangeInclusive: true,
    comparator: function (filterDate, cellValue) {
      if (!cellValue) return -1;
      var p = String(cellValue).split("-");
      if (p.length !== 3) return -1;
      var cell = new Date(+p[0], +p[1] - 1, +p[2]);
      var d = cell.getTime() - filterDate.getTime();
      return d < 0 ? -1 : d > 0 ? 1 : 0;
    },
  };

  var COL_CONFIG = [
    { field: "Stav", filter: "agSetColumnFilter", w: 110, pinned: "left", stav: true, groups: STAV_GROUPS, tip: "Dostupnost inzerátu: Dostupný / Zamluvené / Chystá se / Prodané / Odstraněno" },
    { field: "Značka", filter: "agSetColumnFilter", w: 110, pinned: "left", align: "left" },
    { field: "Model", filter: "agTextColumnFilter", w: 200, pinned: "left", align: "left" },
    // Verze is declared first among the non-pinned columns (ahead of "Odstraněno
    // dne", which predates it here) so it renders immediately after the pinned
    // Značka/Model pair, with nothing in between — the "right after Model" spot.
    { field: "Verze", filter: "agSetColumnFilter", w: 110, align: "left" },
    { field: "Odstraněno dne", filter: "agDateColumnFilter", filterParams: DATE_FILTER_PARAMS, w: 100, hdr: "Odstraněno\ndne", tip: "Datum, kdy inzerát zmizel ze zdroje. Odstraněné řádky starší 60 dnů se z živých dat vyřazují — plná historie zůstává v měsíčních snapshot release." },
    { field: "Typ", filter: "agSetColumnFilter", w: 80 },
    { field: "Palivo", filter: "agSetColumnFilter", w: 100 },
    { field: "Cena (Kč)", filter: "agNumberColumnFilter", w: 120, num: true, hi: false, align: "right", tip: "Barva buňky: zelená = nižší cena, červená = vyšší." },
    { field: "Rok výroby", filter: "agNumberColumnFilter", w: 80, num: true, hi: true, tip: "Barva buňky: zelená = novější, červená = starší." },
    { field: "Nájezd (km)", filter: "agNumberColumnFilter", w: 110, num: true, hi: false, align: "right", tip: "Barva buňky: zelená = nižší nájezd, červená = vyšší." },
    { field: "Spotřeba (l/100 km)", filter: "agNumberColumnFilter", w: 100, num: true, hi: false, tip: "Průměrná spotřeba dle WLTP. V praxi bývá o 10–20 % vyšší.\nU plug-in hybridů (PHEV) je prázdná: oficiální WLTP hodnota (~1 l/100 km) předpokládá nabitou baterii a je zavádějící.\nBarva buňky: zelená = nižší spotřeba, červená = vyšší." },
    { field: "Objem kufru (l)", filter: "agNumberColumnFilter", w: 80, num: true, hi: true, tip: "Barva buňky: zelená = větší kufr, červená = menší." },
    { field: "Výkon (kW)", filter: "agNumberColumnFilter", w: 80, num: true, hi: true, tip: "Barva buňky: zelená = vyšší výkon, červená = nižší." },
    { field: "Objem motoru", filter: "agNumberColumnFilter", w: 80, num: true, hi: true, tip: "Zdvihový objem spalovacího motoru v litrech.\nBarva buňky: zelená = větší objem, červená = menší." },
    { field: "Počet válců", filter: "agNumberColumnFilter", w: 82, num: true, hi: true, hdr: "Počet\nválců", tip: "Počet válců spalovacího motoru. Zatím dostupné jen u části inzerátů (Sauto.cz).\nBarva buňky: zelená = více válců, červená = méně." },
    { field: "Spolehlivost", filter: "agNumberColumnFilter", w: 80, num: true, hi: true, tip: "Hrubý odhad dle pravidla: více válců a větší objem = vyšší spolehlivost. Není to empirická spolehlivost.\nPočet válců chybí u většiny inzerátů — odhad je pak jen z objemu motoru. Jen pro spalovací motory.\nBarva buňky: zelená = vyšší, červená = nižší." },
    { field: "Typ motoru", filter: "agSetColumnFilter", w: 90 },
    { field: "Hybrid typ", filter: "agSetColumnFilter", w: 90, tip: "MHEV = mild hybrid (rekuperace, bez čistě EV jízdy), HEV = plný hybrid (krátkodobě EV jízda), PHEV = plug-in hybrid (nabíjecí ze zásuvky)." },
    { field: "Karoserie", filter: "agSetColumnFilter", w: 100 },
    { field: "Cd", filter: "agNumberColumnFilter", w: 90, num: true, hi: false, hdr: "Odpor\nvzduchu (%)", tip: "Nižší = lepší aerodynamika.\nBarva buňky: zelená = nižší (lepší), červená = vyšší." },
    { field: "Cd zdroj", filter: "agSetColumnFilter", w: 100, hdr: "Zdroj odporu\nvzduchu", tip: "reálné = naměřená hodnota (výrobce / Wikipedia / ev-database), odhad = odhad dle tvaru karoserie (~42 % hodnot)." },
    { field: "Hlučnost (dB)", filter: "agNumberColumnFilter", w: 80, num: true, hi: false, tip: "Hlučnost kabiny dle WLTP. Nižší = tišší.\n< 65 dB výborné, 65–70 dB dobré, > 70 dB hlučné.\nPrůměrné auto při 120 km/h: cca 68–72 dB.\nBarva buňky: zelená = tišší, červená = hlučnější." },
    { field: "Kapacita baterie (kWh)", filter: "agNumberColumnFilter", w: 100, num: true, hi: true, tip: "Použitelná kapacita trakční baterie.\nBarva buňky: zelená = větší kapacita, červená = menší." },
    { field: "Dojezd WLTP (km)", filter: "agNumberColumnFilter", w: 100, num: true, hi: true, tip: "WLTP – standardizovaný laboratorní test (cyklus 0–131 km/h, teplota 23 °C). Výsledky bývají optimistické; reálný dojezd o 10–30 % nižší.\nBarva buňky: zelená = delší dojezd, červená = kratší." },
    { field: "Dojezd EV-database (km)", filter: "agNumberColumnFilter", w: 110, num: true, hi: true, hdr: "Dojezd\nEV-db (km)", tip: "Reálný dojezd dle ev-database.com – realističtější než WLTP.\nBarva buňky: zelená = delší dojezd, červená = kratší." },
    { field: "Převodovka", filter: "agSetColumnFilter", w: 110 },
    { field: "Dvouspojková převodovka", filter: "agSetColumnFilter", w: 90, hdr: "Dvousp.\npřevodovka", tip: "DSG / DCT / S-tronic / PDK – dvě spojky pro sudá a lichá rychlostní stupně.\n+ Rychlé a plynulé řazení, nižší spotřeba.\n– Může škubat při pomalé jízdě a parkování." },
    { field: "Typ převodovky", filter: "agSetColumnFilter", w: 150, hdr: "Typ\npřevodovky", tip: "Odvozeno z Převodovka + Dvouspojková převodovka + Typ: Manuální / Automatická / Dvouspojková (DSG/DCT) / Redukční (EV) – elektromobily mají pevný jednostupňový převod.\nHydraulický měnič a CVT nejsou v datech rozlišitelné – bez odhadu." },
    { field: "Náhon 4x4", filter: "agSetColumnFilter", w: 80 },
    { field: "Filtr pevných částic", filter: "agSetColumnFilter", w: 90, hdr: "Filtr pevn.\nčástic", tip: "GPF (benzín) nebo DPF (nafta) – zachycuje saze z výfukových plynů." },
    { field: "Tepelné čerpadlo", filter: "agSetColumnFilter", w: 80, hdr: "Tepelné\nčerpadlo", tip: "Efektivní vytápění a chlazení EV. V zimě výrazně šetří kapacitu baterie." },
    { field: "Tepelné čerpadlo možné", filter: "agSetColumnFilter", w: 90, hdr: "Tep. čerp.\nmožné", tip: "Lze doobjednat tepelné čerpadlo jako příplatek." },
    { field: "Kola", filter: "agSetColumnFilter", w: 70 },
    { field: "Záruka", filter: "agSetColumnFilter", w: 80 },
    { field: "Spárováno", filter: "agSetColumnFilter", w: 90, sparovano: true, tip: "Ano = jistá shoda s referenčním modelem, Nejisté = slabá nebo nejednoznačná shoda, Ne = nespárováno.\nBarva buňky: červená = Ne, oranžová = Nejisté." },
    { field: "Skóre shody", filter: "agNumberColumnFilter", w: 80, num: true, hi: true, hdr: "Skóre\nshody", tip: "Číselné skóre spolehlivosti párování. Vyšší = jistější. Prázdné pro Ne (nespárováno) a EV – elektromobily se párují prefixovým spojením bez skórovacího algoritmu.\nBarva buňky: zelená = vyšší skóre, červená = nižší." },
    { field: "Extra", filter: "agTextColumnFilter", w: 200 },
    { field: "Země", filter: "agSetColumnFilter", w: 100, tip: "Země prodejce. Inzeráty z mobile.de mohou být z Česka, Slovenska, Německa, Rakouska nebo Polska; ostatní zdroje jsou z Česka." },
    { field: "Zdroj", filter: "agSetColumnFilter", w: 100 },
  ];

  var NUMERIC_COLS = {};
  for (var ci = 0; ci < COL_CONFIG.length; ci++) {
    if (COL_CONFIG[ci].num) NUMERIC_COLS[COL_CONFIG[ci].field] = COL_CONFIG[ci].hi;
  }

  // Single-line header names for the filter-chips bar (headerName itself may
  // carry a "\n" line break for narrow grid columns — flatten that here).
  var CHIP_HEADER_NAMES = {};
  for (var chi = 0; chi < COL_CONFIG.length; chi++) {
    var chcfg = COL_CONFIG[chi];
    CHIP_HEADER_NAMES[chcfg.field] = (chcfg.hdr || chcfg.field).replace(/\n/g, " ");
  }

  var gridApi = null;
  var colRanges = {};
  var userThresholds = {};
  var appMetadata = null;
  var chartLoaded = false;
  var summaryRendered = false;
  var totalRows = 0;
  // Removed listings live in a separate cars-archived.parquet, fetched on demand
  // (decision 001, option C). "unloaded" | "loading" | "loaded".
  var archiveState = "unloaded";
  var archiveVisible = false;   // Archiv toggle: are removed rows shown?
  var archivedLoaded = 0;       // count of rows added from the archive

  // ── Heat-map colouring: user-selectable palette × style, theme-aware. ──
  // palette = which diverging colours (good→bad); style = how they're painted.
  // Default is soft red-green full-cell (familiar); every combo is switchable in
  // Nastavení barev and persisted to localStorage. All styles paint via the cell
  // background only (no cellRenderer) so column virtualisation stays fast.
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
    renderHeatModeChoices();      // reflect new active state
    updateThresholdGradients();   // recolour the per-row direction swatches
  };

  function isDarkTheme() {
    return (document.documentElement.getAttribute("data-theme") || "dark") === "dark";
  }

  function lerp3(a, b, u) {
    return [Math.round(a[0] + (b[0] - a[0]) * u),
            Math.round(a[1] + (b[1] - a[1]) * u),
            Math.round(a[2] + (b[2] - a[2]) * u)];
  }

  // t: 0 = good, 1 = bad. Diverges good→mid→bad; mid is a theme-tuned slate so
  // the tint reads on both backgrounds. Returns "r,g,b".
  function heatRGBof(paletteKey, t) {
    var pal = HEAT_PALETTES[paletteKey] || HEAT_PALETTES.redgreen;
    var mid = isDarkTheme() ? [71, 85, 105] : [148, 163, 184];
    var c = t < 0.5 ? lerp3(pal.good, mid, t * 2) : lerp3(mid, pal.bad, (t - 0.5) * 2);
    return c[0] + "," + c[1] + "," + c[2];
  }

  function heatRGB(t) { return heatRGBof(heatMode.palette, t); }

  // A left→right good/bad gradient preview for a column direction (greenHigh =
  // higher-is-better ⇒ min is bad/left). Used for the drawer swatches.
  function heatGradientCSS(paletteKey, greenHigh) {
    var lo = greenHigh ? 1 : 0, hi = greenHigh ? 0 : 1;
    return "linear-gradient(90deg,rgb(" + heatRGBof(paletteKey, lo) + "),rgb(" +
      heatRGBof(paletteKey, 0.5) + "),rgb(" + heatRGBof(paletteKey, hi) + "))";
  }

  // CSS background for a value's badness t (0..1) and magnitude pos (0..1).
  // Alphas are theme-tuned so the cell text (theme foreground, not forced white)
  // stays legible over both the filled and unfilled parts.
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
    // combo: strong bar up to pct, faint full-cell tint for the remainder
    var barA = dark ? 0.8 : 0.5;
    var tintA = dark ? 0.18 : 0.12;
    return { background: "linear-gradient(90deg, rgba(" + rgb + "," + barA + ") 0, rgba(" + rgb + "," + barA + ") " + pct + "%, rgba(" + rgb + "," + tintA + ") " + pct + "%, rgba(" + rgb + "," + tintA + ") 100%)" };
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
      if (min == null || max == null || min === max) return style;
      var pos = (params.value - min) / (max - min);
      pos = Math.max(0, Math.min(1, pos));
      var t = greenHigh ? (1 - pos) : pos;   // badness: 0 good … 1 bad
      var bg = heatBackground(t, pos);
      if (bg.backgroundColor) style.backgroundColor = bg.backgroundColor;
      if (bg.background) style.background = bg.background;
      return style;
    };
  }

  function numericFormatter(field) {
    return function (p) {
      if (p.value == null) return "";
      if (field === "Cena (Kč)") return Number(p.value).toLocaleString("cs-CZ") + " Kč";
      if (field === "Nájezd (km)") return Number(p.value).toLocaleString("cs-CZ") + " km";
      if (field === "Spotřeba (l/100 km)" || field === "Objem motoru") return p.value.toFixed(1);
      if (field === "Cd") return String(Math.round(Number(p.value) * 100));
      return String(p.value);
    };
  }

  // Tri-state Spárováno background: red = no reference match, amber = uncertain
  // (weak/ambiguous), none = confident match.
  function sparovanoBg(v) {
    if (v === "Ne") return "rgba(239, 68, 68, 0.18)";
    if (v === "Nejisté") return "rgba(245, 158, 11, 0.18)";
    return "";
  }

  function stavRenderer(params) {
    var text = params.value || "";
    var url = params.data && params.data["Odkaz na auto"];
    var el;
    if (url) {
      el = document.createElement("a");
      el.href = url;
      el.target = "_blank";
      el.rel = "noopener";
      el.textContent = text || "\u2197";
    } else {
      el = document.createElement("span");
      el.textContent = text;
    }
    return el;
  }

  function buildColumnDefs() {
    var defs = [];
    for (var i = 0; i < COL_CONFIG.length; i++) {
      var cfg = COL_CONFIG[i];
      var def = {
        field: cfg.field,
        headerName: cfg.hdr || makeHeaderName(cfg.field),
        filter: cfg.num ? RangeFilter : (cfg.filter === "agSetColumnFilter" ? SetFilter : cfg.filter),
        filterParams: cfg.filterParams || (cfg.groups ? { groups: cfg.groups } : undefined),
        width: cfg.w,
      };

      if (cfg.pinned) def.pinned = cfg.pinned;

      if (cfg.stav) {
        // Stav = availability only. Match-confidence colour/tooltip lives on the
        // Spárováno column (where it agrees with the cell's own value) — not here,
        // where an amber Stav cell meant something unrelated to its "Ojeté" text.
        def.cellRenderer = stavRenderer;
        def.cellStyle = { textAlign: "center" };
      } else if (cfg.sparovano) {
        def.cellStyle = function (params) {
          var style = { textAlign: "center" };
          var bg = sparovanoBg(params.value);
          if (bg) style.backgroundColor = bg;
          return style;
        };
        def.tooltipValueGetter = function (p) {
          if (p.value === "Ne") return "Nespárováno – auto nebylo nalezeno v referenčních datech.";
          if (p.value === "Nejisté") return "Nejisté spárování – málo dat nebo nejednoznačná shoda; zkontrolujte.";
          return null;
        };
      } else if (cfg.num) {
        def.cellStyle = numericCellStyle(cfg.field);
        def.valueFormatter = numericFormatter(cfg.field);
      } else {
        def.cellStyle = { textAlign: cfg.align || "center" };
      }

      if (cfg.tip) def.headerTooltip = cfg.tip;
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

  // ── URL/localStorage state (shared codec in site/url-state.js → window.UrlState) ──
  //
  // Filters + colour thresholds live in the URL fragment (#f= / #t=); column
  // layout is per-browser localStorage only (NOT the URL — it would bloat every
  // link with the full ordered column list). See docs/gotchas.md.
  var U = window.UrlState;

  function writeHash() {
    U.writeHash({ filters: getFilterModel(), thresholds: userThresholds });
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

  // Column-layout changes (sort / drag-reorder / resize / pin / hide) persist to
  // localStorage only — deliberately not the URL.
  function onColResized(e) { if (e && e.finished) persistColState(); }

  function updateFilterChips() {
    if (!window.renderFilterChips) return;
    window.renderFilterChips({
      gridApi: gridApi,
      barEl: document.getElementById("filter-chips-bar"),
      headerNames: CHIP_HEADER_NAMES,
      onClearAll: window.clearFilters,
    });
  }

  function onFilterChanged() {
    var model = getFilterModel();
    saveFiltersToStorage(model);
    writeHash();
    updateRowCount();
    updateFilterChips();
    updatePairingGapButton();
  }

  function loadThresholds() {
    try {
      var s = localStorage.getItem(THRESHOLD_KEY);
      userThresholds = s ? JSON.parse(s) : {};
    } catch (_) { userThresholds = {}; }
  }

  // Kept for any external caller; state now flows through commitRange, so this
  // only re-persists + repaints the current shared state (no DOM parsing).
  window.saveThresholds = function () {
    persistThresholds();
    writeHash();
    if (gridApi) gridApi.refreshCells({ force: true });
  };

  // Reset ALL columns: clears every colour threshold AND its coupled range filter.
  window.resetThresholds = function () {
    var fields = Object.keys(userThresholds);
    userThresholds = {};
    localStorage.removeItem(THRESHOLD_KEY);
    renderThresholdInputs();
    if (gridApi) {
      fields.forEach(function (f) { if (NUMERIC_COLS[f] !== undefined) gridApi.setColumnFilterModel(f, null); });
      gridApi.refreshCells({ force: true });
      gridApi.onFilterChanged();
    }
    writeHash();
  };

  // Mini style preview for a choice chip (uses the current palette).
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

      // Dual-range slider; the track is the column's good→bad gradient. Shares the
      // same state as the number boxes and the column-filter slider via commitRange;
      // a thumb parked at the data edge clears that bound (= automatic / open).
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


  // \u2500\u2500 Gear menu (colour settings + theme) \u2500\u2500
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

  // Colour settings live in a right-side drawer (does not displace the grid).
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

  // \u2500\u2500 Archive toggle (load + show / hide removed listings) \u2500\u2500
  function updateArchiveLabel() {
    var lbl = document.getElementById("archive-label");
    if (!lbl) return;
    if (archiveState === "loading") { lbl.textContent = "Na\u010d\u00edt\u00e1m\u2026"; return; }
    var n = (appMetadata && appMetadata.archivedCars) || archivedLoaded || 0;
    lbl.textContent = n ? "Archiv (" + Number(n).toLocaleString("cs-CZ") + ")" : "Archiv";
  }

  function setupArchiveToggle() {
    var wrap = document.getElementById("archive-toggle");
    var chk = document.getElementById("archive-check");
    if (!wrap || !chk) return;
    var n = (appMetadata && appMetadata.archivedCars) || 0;
    if (!n) {
      wrap.classList.add("disabled");
      wrap.title = "\u017d\u00e1dn\u00e9 archivovan\u00e9 inzer\u00e1ty";
      chk.disabled = true;
      return;
    }
    wrap.classList.remove("disabled");
    chk.disabled = false;
    updateArchiveLabel();
  }

  window.onArchiveToggle = function (on) {
    archiveVisible = on;
    if (on && archiveState === "unloaded") loadArchive();
    if (gridApi) gridApi.onFilterChanged();  // re-eval external filter (show/hide Odstran\u011bno)
    updateArchiveLabel();
    updateRowCount();
  };

  function updateRowCount() {
    var shown = 0;
    if (gridApi) gridApi.forEachNodeAfterFilter(function () { shown++; });
    var universe = totalRows + (archiveVisible ? archivedLoaded : 0);
    var el = document.getElementById("row-count");
    if (!el) return;
    while (el.firstChild) el.removeChild(el.firstChild);
    if (shown < universe) {
      el.textContent = "Vyfiltrov\u00e1no " + shown.toLocaleString("cs-CZ") + " / " + universe.toLocaleString("cs-CZ") + " aut";
    } else {
      var num = document.createElement("span");
      num.className = "num";
      num.textContent = universe.toLocaleString("cs-CZ");
      var lbl = document.createElement("span");
      lbl.className = "lbl";
      lbl.textContent = "aut";
      el.appendChild(num);
      el.appendChild(document.createTextNode(" "));
      el.appendChild(lbl);
    }
  }

  // #14: unpaired-listings shortcut — counts Spárováno == "Ne" / "Nejisté" over
  // the FULL loaded dataset (forEachNode, not AfterFilter — the label must stay
  // stable while the user filters, only growing when the archive is loaded).
  function computePairingGapCounts() {
    var counts = { ne: 0, nejiste: 0 };
    if (!gridApi) return counts;
    gridApi.forEachNode(function (node) {
      if (!node.data) return;
      var v = node.data["Spárováno"];
      if (v === "Ne") counts.ne++;
      else if (v === "Nejisté") counts.nejiste++;
    });
    return counts;
  }

  function isPairingGapFilterActive() {
    if (!gridApi) return false;
    var model = gridApi.getFilterModel() || {};
    var sp = model["Spárováno"];
    if (!sp || sp.filterType !== "set" || !sp.values) return false;
    var vals = sp.values.slice().sort();
    return vals.length === 2 && vals[0] === "Ne" && vals[1] === "Nejisté";
  }

  function updatePairingGapButton() {
    var btn = document.getElementById("btn-pairing-gap");
    if (!btn) return;
    var counts = computePairingGapCounts();
    if (counts.ne === 0 && counts.nejiste === 0) {
      btn.style.display = "none";
      return;
    }
    btn.style.display = "";
    btn.textContent = "Nespárováno: " + counts.ne + " (" + counts.nejiste + " nejistých)";
    btn.classList.toggle("active", isPairingGapFilterActive());
  }

  // Toggle: apply {Ne, Nejisté} to the Spárováno set filter, merging with
  // whatever other column filters are active (never clobbers them); clicking
  // again while that exact filter is active clears just the Spárováno entry.
  window.togglePairingGapFilter = function () {
    if (!gridApi) return;
    var model = gridApi.getFilterModel() || {};
    if (isPairingGapFilterActive()) {
      delete model["Spárováno"];
    } else {
      model["Spárováno"] = { filterType: "set", values: ["Ne", "Nejisté"] };
    }
    gridApi.setFilterModel(model);
  };

  // Fetch removed listings on demand (the Archiv toggle). cars.parquet holds only
  // live listings, so the archive stays out of memory until the user flips it on.
  // Visibility is a grid external filter (hides Stav == "Odstran\u011bno" when off), so
  // the rows stay loaded and toggling is instant after the first fetch.
  window.loadArchive = function () {
    if (archiveState !== "unloaded") return;
    archiveState = "loading";
    updateArchiveLabel();
    fetch("data/cars-archived.parquet")
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.arrayBuffer(); })
      .then(function (buf) { return parquetReadObjects({ file: buf }); })
      .then(function (rows) {
        if (gridApi && rows.length) {
          gridApi.applyTransaction({ add: rows });
          archivedLoaded = rows.length;
        }
        archiveState = "loaded";
        if (gridApi) gridApi.onFilterChanged();  // apply external filter to the new rows
        updateArchiveLabel();
        updateRowCount();
      })
      .catch(function () {
        archiveState = "unloaded";
        archiveVisible = false;
        var chk = document.getElementById("archive-check");
        if (chk) chk.checked = false;
        var lbl = document.getElementById("archive-label");
        if (lbl) lbl.textContent = "Archiv \u2013 chyba";
      });
  };

  window.clearFilters = function () {
    localStorage.removeItem(STORAGE_KEY);
    if (gridApi) gridApi.setFilterModel(null); // fires onFilterChanged → writeHash
    else writeHash();
    updateRowCount();
  };

  window.resetColOrder = function () {
    localStorage.removeItem(COL_STATE_KEY);
    if (gridApi) {
      // Restore the COL_CONFIG defaults: original order, default widths/pins, no sort.
      gridApi.applyColumnState({
        state: COL_CONFIG.map(function (c) {
          return { colId: c.field, sort: null, sortIndex: null, pinned: c.pinned || null, hide: false, width: c.w };
        }),
        applyOrder: true,
        defaultState: { sort: null },
      });
      persistColState();
    }
  };

  // Forced slider precision (decimals) for columns where the data precision is
  // not the desired step — overrides the auto-detected value in computeRanges.
  var STEP_DECIMALS = {
    "Spotřeba (l/100 km)": 0,
    "Hlučnost (dB)": 0,
    "Kapacita baterie (kWh)": 0,
    "Výkon (kW)": 0,
    "Objem motoru": 1,
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
    var fields = Object.keys(NUMERIC_COLS);
    for (var i = 0; i < fields.length; i++) {
      var field = fields[i];
      var min = Infinity, max = -Infinity, dec = 0;
      for (var j = 0; j < data.length; j++) {
        var v = data[j][field];
        if (v != null && typeof v === "number" && isFinite(v)) {
          if (v < min) min = v;
          if (v > max) max = v;
          var d = _decimals(v);
          if (d > dec) dec = d;
        }
      }
      // Slider step = the data's own precision (integer cols step by 1,
      // one-decimal cols by 0.1, …), unless STEP_DECIMALS forces it.
      if (STEP_DECIMALS[field] != null) dec = STEP_DECIMALS[field];
      if (min !== Infinity) colRanges[field] = { min: min, max: max, step: Math.pow(10, -dec) };
    }
  }

  function init(data) {
    totalRows = data.length;
    computeRanges(data);
    loadThresholds();
    loadHeatMode();
    renderThresholdInputs();

    var gridOptions = {
      theme: "legacy",
      // Czech labels for the built-in number/text filters (the custom SetFilter is
      // already Czech). Without this AG shows "Equals" / "Filter…" in an otherwise
      // Czech UI.
      localeText: {
        equals: "Rovná se", notEqual: "Nerovná se",
        lessThan: "Menší než", lessThanOrEqual: "Menší nebo rovno",
        greaterThan: "Větší než", greaterThanOrEqual: "Větší nebo rovno",
        // Date filters relabel lessThan/greaterThan as before/after (own keys).
        before: "Před", after: "Po",
        inRange: "V rozsahu", inRangeStart: "od", inRangeEnd: "do",
        contains: "Obsahuje", notContains: "Neobsahuje",
        startsWith: "Začíná na", endsWith: "Končí na",
        blank: "Prázdné", notBlank: "Neprázdné",
        filterOoo: "Filtrovat…", applyFilter: "Použít", resetFilter: "Vymazat",
        clearFilter: "Vymazat", cancelFilter: "Zrušit",
        andCondition: "A zároveň", orCondition: "Nebo",
        noMatches: "Žádná shoda",
      },
      columnDefs: buildColumnDefs(),
      rowData: data,
      rowHeight: 25,
      defaultColDef: {
        sortable: true,
        resizable: true,
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
      // Archiv toggle: hide removed listings unless the user asks for them.
      isExternalFilterPresent: function () { return !archiveVisible; },
      doesExternalFilterPass: function (node) { return !node.data || node.data["Stav"] !== "Odstraněno"; },
      onFilterChanged: onFilterChanged,
      onModelUpdated: updatePairingGapButton,
      onDragStopped: persistColState,
      onSortChanged: persistColState,
      onColumnPinned: persistColState,
      onColumnVisible: persistColState,
      onColumnResized: onColResized,
      onGridReady: function (params) {
        gridApi = params.api;
        window.__gridApi = params.api;

        var hash = U.parseHash();
        var legacyFilters = (hash.f || hash.t) ? null : U.decodeLegacyFilters();

        // Column layout: localStorage only (never the URL).
        var colState = loadColStateFromStorage();
        if (colState) applyColState(colState);

        // Colour thresholds: URL fragment (#t=) overrides the localStorage default.
        if (hash.t) {
          userThresholds = U.decThresholds(hash.t);
          try { localStorage.setItem(THRESHOLD_KEY, JSON.stringify(userThresholds)); } catch (_) {}
          renderThresholdInputs();
          gridApi.refreshCells({ force: true });
        }

        // Filters: URL fragment (#f=) → legacy ?filters= → localStorage.
        // The filter store (#f= / carCompareFilters) is the sole source of truth
        // for which columns filter. Colour thresholds (#t= / carCompareThresholds)
        // only tint — a threshold with no matching filter entry is colour-only and
        // must NOT be re-armed as a filter on load (that resurrected filters the
        // user had cleared via the chip ×). Both are kept in sync at edit time by
        // commitRange(); clearing the filter leaves the colour threshold alone.
        var urlFilters = hash.f ? U.decFilters(hash.f) : legacyFilters;
        var filters = urlFilters || loadFiltersFromStorage();
        if (filters) setFilterModel(filters);

        // Migrate an old ?filters= link (or stray #t=) to the canonical fragment.
        if (legacyFilters || hash.t) writeHash();

        updateRowCount();
        updateFilterChips();
        updatePairingGapButton();
      },
    };

    var gridDiv = document.getElementById("grid");
    agGrid.createGrid(gridDiv, gridOptions);
  }

  // ── Summary modal ──

  window.toggleSummary = function () {
    var overlay = document.getElementById("summary-overlay");
    overlay.classList.toggle("hidden");
    if (!overlay.classList.contains("hidden") && !summaryRendered) {
      renderSummary();
      summaryRendered = true;
    }
  };

  window.closeSummary = function () {
    document.getElementById("summary-overlay").classList.add("hidden");
  };

  window.closeSummaryBackdrop = function (e) {
    if (e.target === document.getElementById("summary-overlay")) {
      window.closeSummary();
    }
  };

  function fmtDate(iso) {
    if (!iso) return "\u2014";
    var d = new Date(iso);
    return d.toLocaleDateString("cs-CZ") + " " + d.toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" });
  }

  function fmtNum(n) {
    return n != null ? Number(n).toLocaleString("cs-CZ") : "\u2014";
  }

  function renderSummary() {
    var body = document.getElementById("summary-body");
    while (body.firstChild) body.removeChild(body.firstChild);

    if (appMetadata) {
      // github.event_name (schedule/push/workflow_dispatch) or "manual" for a
      // local build. A push-triggered rebuild is automatic \u2014 only a
      // workflow_dispatch is genuinely hand-started, so don't label push
      // "Manu\u00e1ln\u00ed".
      var TRIGGER_LABELS = {
        schedule: "Automaticky (pl\u00e1n)",
        push: "Automaticky (push)",
        workflow_dispatch: "Ru\u010dn\u011b (dispatch)",
        manual: "Lok\u00e1ln\u00ed sestaven\u00ed",
      };
      var trigger = TRIGGER_LABELS[appMetadata.trigger] || appMetadata.trigger || "\u2013";

      // Build info card
      var card1 = makeCard("Posledn\u00ed sestaven\u00ed");
      addStat(card1, "Datum", fmtDate(appMetadata.buildDate));
      addStat(card1, "Spu\u0161t\u011bn\u00ed", trigger);
      addStat(card1, "Celkem aut", fmtNum(appMetadata.totalCars));
      if (appMetadata.archivedCars) {
        addStat(card1, "Archiv (odstraněné)", fmtNum(appMetadata.archivedCars));
      }
      body.appendChild(card1);

      // Source breakdown
      if (appMetadata.sources) {
        var card2 = makeCard("Zdroje dat");
        var tbl = makeTable(["Zdroj", "Elektrick\u00e9", "Spalovac\u00ed", "Celkem"]);
        var srcKeys = Object.keys(appMetadata.sources).sort();
        for (var i = 0; i < srcKeys.length; i++) {
          var s = appMetadata.sources[srcKeys[i]];
          addRow(tbl, [srcKeys[i], fmtNum(s.electric), fmtNum(s.combustion), fmtNum(s.total)]);
        }
        card2.appendChild(tbl);
        body.appendChild(card2);
      }

      // Match statistics
      if (appMetadata.matching) {
        var card3 = makeCard("P\u00e1rov\u00e1n\u00ed s referen\u010dn\u00edmi modely");
        var tbl3 = makeTable(["Typ", "Sp\u00e1rov\u00e1no", "Nejist\u00e9", "Nesp\u00e1rov\u00e1no", "Celkem", "%"]);
        var types = [["electric", "Elektrick\u00e9"], ["combustion", "Spalovac\u00ed"]];
        for (var i = 0; i < types.length; i++) {
          var m = appMetadata.matching[types[i][0]];
          if (!m) continue;
          var uncertain = m.uncertain || 0;
          var pct = m.total > 0 ? (100 * m.matched / m.total).toFixed(1) : "0.0";
          addRow(tbl3, [types[i][1], fmtNum(m.matched), fmtNum(uncertain), fmtNum(m.unmatched), fmtNum(m.total), pct + " %"]);
        }
        card3.appendChild(tbl3);
        body.appendChild(card3);
      }

      // Reference data
      if (appMetadata.referenceData) {
        var card4 = makeCard("Referen\u010dn\u00ed data");
        var tbl4 = makeTable(["Typ", "Soubor", "Model\u016f"]);
        var rd = appMetadata.referenceData;
        if (rd.combustion) addRow(tbl4, ["Spalovac\u00ed", rd.combustion.file, fmtNum(rd.combustion.count)]);
        if (rd.electric) addRow(tbl4, ["Elektrick\u00e9", rd.electric.file, fmtNum(rd.electric.count)]);
        card4.appendChild(tbl4);
        var link = document.createElement("p");
        link.style.cssText = "margin-top:8px;font-size:0.85rem";
        var a = document.createElement("a");
        a.href = "reference.html";
        a.textContent = "Zobrazit referen\u010dn\u00ed modely \u2192";
        link.appendChild(a);
        card4.appendChild(link);
        body.appendChild(card4);
      }

      // Data-selection criteria (hard filters each scraper applies)
      if (appMetadata.filters && appMetadata.filters.length) {
        body.appendChild(makeFiltersCard(appMetadata.filters));
      }
    } else {
      var noData = makeCard("");
      var p = document.createElement("p");
      p.textContent = "Data nebyla sestavena n\u00e1strojem build (spus\u0165te python build/build_data.py).";
      noData.appendChild(p);
      body.appendChild(noData);
    }

    // Body type / Drivetrain matrix from loaded grid data
    if (gridApi) {
      // Karoserie now arrives already folded onto the canonical display set by
      // build_data.canonicalize_body_vocab (SUV/Hatchback/Kombi/Sedan/MPV/Kupé;
      // Liftback/Sportback/Fastback fold into Hatchback — the reference labels
      // that body class inconsistently). Synonyms kept for defence in depth.
      var bodyGroups = {
        "Kombi": ["Kombi", "Combi", "Variant", "SW", "Touring", "Sports Tourer", "Avant"],
        "SUV": ["SUV", "CUV", "Terénní"],
        "Hatchback": ["Hatchback", "Liftback", "Sportback", "Fastback"],
        "Sedan": ["Sedan/limuzína", "Sedan"],
        "MPV": ["MPV", "VAN", "Allspace"],
        "Kupé / Kabrio": ["Kupé", "Kabriolet"],
        "Pick-up": ["Pick-up"],
      };
      var bodyLookup = {};
      var groupOrder = Object.keys(bodyGroups);
      for (var g = 0; g < groupOrder.length; g++) {
        var members = bodyGroups[groupOrder[g]];
        for (var m = 0; m < members.length; m++) bodyLookup[members[m]] = groupOrder[g];
      }

      var matrix = {};
      gridApi.forEachNode(function (node) {
        if (!node.data) return;
        var rawBody = node.data["Karoserie"] || "";
        var body = bodyLookup[rawBody] || (rawBody ? rawBody : "Nezadáno");
        var typ = node.data["Typ"] || "";
        var pal = node.data["Palivo"] || "";
        var pohon = typ === "Elektrické" ? "Elektro" : (pal || "Nezadáno");
        if (!matrix[body]) matrix[body] = {};
        matrix[body][pohon] = (matrix[body][pohon] || 0) + 1;
      });

      var allPohon = {};
      var bodyKeys = Object.keys(matrix);
      for (var b = 0; b < bodyKeys.length; b++) {
        var fuels = Object.keys(matrix[bodyKeys[b]]);
        for (var f = 0; f < fuels.length; f++) allPohon[fuels[f]] = true;
      }
      var pohonOrder = ["Benzín", "Nafta", "Elektro", "LPG + benzín", "CNG + benzín"];
      var pohonList = pohonOrder.filter(function (p) { return allPohon[p]; });
      for (var p in allPohon) {
        if (pohonList.indexOf(p) === -1) pohonList.push(p);
      }

      // Sort body keys: known groups first (by groupOrder), then alphabetical remainder
      bodyKeys.sort(function (a, b) {
        var ia = groupOrder.indexOf(a);
        var ib = groupOrder.indexOf(b);
        if (ia === -1) ia = 999;
        if (ib === -1) ib = 999;
        return ia !== ib ? ia - ib : a.localeCompare(b);
      });

      var card5 = makeCard("Karoserie × Pohon");
      var hdr5 = ["Karoserie"];
      for (var f = 0; f < pohonList.length; f++) hdr5.push(pohonList[f]);
      hdr5.push("Celkem");
      var tbl5 = makeTable(hdr5);
      tbl5.querySelector("tr").lastChild.className = "celkem-col";
      var colTotals = {};
      var grandTotal = 0;
      for (var b = 0; b < bodyKeys.length; b++) {
        var cells = [bodyKeys[b]];
        var rowTotal = 0;
        for (var f = 0; f < pohonList.length; f++) {
          var val = matrix[bodyKeys[b]][pohonList[f]] || 0;
          cells.push(fmtNum(val));
          rowTotal += val;
          colTotals[pohonList[f]] = (colTotals[pohonList[f]] || 0) + val;
        }
        cells.push(fmtNum(rowTotal));
        grandTotal += rowTotal;
        var tr5 = addRow(tbl5, cells);
        tr5.lastChild.className = "celkem-col";
      }
      var totCells = ["Celkem"];
      for (var f = 0; f < pohonList.length; f++) totCells.push(fmtNum(colTotals[pohonList[f]] || 0));
      totCells.push(fmtNum(grandTotal));
      var trTot = addRow(tbl5, totCells);
      trTot.className = "celkem-row";
      trTot.lastChild.className = "celkem-col";
      card5.appendChild(tbl5);
      body.appendChild(card5);

      // Země × Typ (country breakdown) — mobile.de brings multi-country listings
      var countries = {};
      gridApi.forEachNode(function (node) {
        if (!node.data) return;
        var zeme = (node.data["Země"] || "Nezadáno").trim() || "Nezadáno";
        var typ = node.data["Typ"] || "";
        if (!countries[zeme]) countries[zeme] = { ev: 0, ice: 0 };
        if (typ === "Elektrické") countries[zeme].ev += 1;
        else countries[zeme].ice += 1;
      });
      var countryKeys = Object.keys(countries).sort(function (a, b) {
        return (countries[b].ev + countries[b].ice) - (countries[a].ev + countries[a].ice);
      });
      if (countryKeys.length) {
        var card7 = makeCard("Země × Typ");
        var tbl7 = makeTable(["Země", "Elektrické", "Spalovací", "Celkem"]);
        tbl7.querySelector("tr").lastChild.className = "celkem-col";
        var cEv = 0, cIce = 0;
        for (var c = 0; c < countryKeys.length; c++) {
          var cc = countries[countryKeys[c]];
          cEv += cc.ev; cIce += cc.ice;
          var trC = addRow(tbl7, [countryKeys[c], fmtNum(cc.ev), fmtNum(cc.ice), fmtNum(cc.ev + cc.ice)]);
          trC.lastChild.className = "celkem-col";
        }
        var trCtot = addRow(tbl7, ["Celkem", fmtNum(cEv), fmtNum(cIce), fmtNum(cEv + cIce)]);
        trCtot.className = "celkem-row";
        trCtot.lastChild.className = "celkem-col";
        card7.appendChild(tbl7);
        body.appendChild(card7);
      }
    }

    // Chart container
    if (appMetadata) {
      var card6 = makeCard("Historie scrapov\u00e1n\u00ed");
      var chartDiv = document.createElement("div");
      chartDiv.id = "summary-chart-container";
      var loading = document.createElement("p");
      loading.id = "chart-loading";
      loading.textContent = "Na\u010d\u00edt\u00e1n\u00ed grafu\u2026";
      chartDiv.appendChild(loading);
      card6.appendChild(chartDiv);
      body.appendChild(card6);
      loadChart();
    }
  }

  function makeCard(title) {
    var div = document.createElement("div");
    div.className = "summary-card";
    if (title) {
      var h3 = document.createElement("h3");
      h3.textContent = title;
      div.appendChild(h3);
    }
    return div;
  }

  function addStat(parent, label, value) {
    var span = document.createElement("span");
    span.className = "summary-stat";
    var lbl = document.createElement("span");
    lbl.className = "label";
    lbl.textContent = label + ": ";
    var val = document.createElement("span");
    val.className = "value";
    val.textContent = value;
    span.appendChild(lbl);
    span.appendChild(val);
    parent.appendChild(span);
  }

  function makeTable(headers) {
    var tbl = document.createElement("table");
    tbl.className = "summary-table";
    var tr = document.createElement("tr");
    for (var i = 0; i < headers.length; i++) {
      var th = document.createElement("th");
      th.textContent = headers[i];
      tr.appendChild(th);
    }
    tbl.appendChild(tr);
    return tbl;
  }

  function addRow(tbl, cells) {
    var tr = document.createElement("tr");
    for (var i = 0; i < cells.length; i++) {
      var td = document.createElement("td");
      td.textContent = cells[i];
      tr.appendChild(td);
    }
    tbl.appendChild(tr);
    return tr;
  }

  // "Kritéria výběru dat" — renders the per-source hard filters carried in
  // cars-meta.json.filters (source of truth: scrapers/core/filters.py).
  function makeFiltersCard(sources) {
    var card = makeCard("Kritéria výběru dat");
    var intro = document.createElement("p");
    intro.className = "filters-intro";
    intro.textContent = "Pevné filtry, kterými je omezen sběr dat z každého zdroje. "
      + "Auta mimo tato kritéria se do databáze vůbec nedostanou.";
    card.appendChild(intro);

    function bulletList(items) {
      var ul = document.createElement("ul");
      ul.className = "filters-list";
      for (var i = 0; i < items.length; i++) {
        var li = document.createElement("li");
        li.textContent = items[i];
        ul.appendChild(li);
      }
      return ul;
    }

    for (var s = 0; s < sources.length; s++) {
      var src = sources[s];
      var block = document.createElement("div");
      block.className = "filters-source";

      var h = document.createElement("h4");
      h.textContent = src.source;
      block.appendChild(h);

      if (src.note) {
        var note = document.createElement("p");
        note.className = "filters-note";
        note.textContent = src.note;
        block.appendChild(note);
      }

      var common = src.common || [], ev = src.ev || [], ice = src.ice || [];
      if (common.length) block.appendChild(bulletList(common));
      if (ev.length) {
        var evLbl = document.createElement("p");
        evLbl.className = "filters-sublabel";
        evLbl.textContent = "Elektrické navíc:";
        block.appendChild(evLbl);
        block.appendChild(bulletList(ev));
      }
      if (ice.length) {
        var iceLbl = document.createElement("p");
        iceLbl.className = "filters-sublabel";
        iceLbl.textContent = "Spalovací navíc:";
        block.appendChild(iceLbl);
        block.appendChild(bulletList(ice));
      }
      card.appendChild(block);
    }
    return card;
  }

  function loadChart() {
    if (chartLoaded) {
      fetchAndRenderChart();
      return;
    }
    var script = document.createElement("script");
    script.src = "https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js";
    script.onload = function () {
      chartLoaded = true;
      fetchAndRenderChart();
    };
    script.onerror = function () {
      var el = document.getElementById("chart-loading");
      if (el) el.textContent = "Nepoda\u0159ilo se na\u010d\u00edst Chart.js.";
    };
    document.head.appendChild(script);
  }

  function fetchAndRenderChart() {
    fetch("data/scrape_history.json")
      .then(function (r) { return r.json(); })
      .then(function (history) {
        var container = document.getElementById("summary-chart-container");
        if (!container) return;
        while (container.firstChild) container.removeChild(container.firstChild);
        if (!history || !history.length) {
          container.textContent = "\u017d\u00e1dn\u00e1 historick\u00e1 data.";
          return;
        }
        var canvas = document.createElement("canvas");
        container.appendChild(canvas);

        var labels = history.map(function (h) {
          var d = new Date(h.date);
          if (isNaN(d.getTime())) return h.date;
          var day = d.getDate();
          var mon = d.getMonth() + 1;
          var hh = String(d.getHours()).padStart(2, "0");
          var mm = String(d.getMinutes()).padStart(2, "0");
          return day + "." + mon + ". " + hh + ":" + mm;
        });
        var totals = history.map(function (h) { return h.total; });
        var elecData = history.map(function (h) {
          return h.matching && h.matching.electric ? h.matching.electric.total : 0;
        });
        var combData = history.map(function (h) {
          return h.matching && h.matching.combustion ? h.matching.combustion.total : 0;
        });

        var isDark = document.documentElement.getAttribute("data-theme") === "dark";
        var gridColor = isDark ? "rgba(255,255,255,0.1)" : "rgba(0,0,0,0.1)";
        var textColor = isDark ? "#94a3b8" : "#64748b";

        new Chart(canvas, {
          type: "line",
          data: {
            labels: labels,
            datasets: [
              { label: "Celkem", data: totals, borderColor: "#3b82f6", backgroundColor: "rgba(59,130,246,0.1)", fill: true, tension: 0.3 },
              { label: "Spalovac\u00ed", data: combData, borderColor: "#f97316", backgroundColor: "transparent", tension: 0.3 },
              { label: "Elektrick\u00e9", data: elecData, borderColor: "#22c55e", backgroundColor: "transparent", tension: 0.3 },
            ],
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
              legend: { labels: { color: textColor } },
              tooltip: {
                callbacks: {
                  title: function (items) {
                    var idx = items[0].dataIndex;
                    var h = history[idx];
                    var d = new Date(h.date);
                    var label = isNaN(d.getTime()) ? h.date : d.toLocaleString("cs-CZ");
                    return label + " (" + (h.trigger || "?") + ")";
                  },
                },
              },
            },
            scales: {
              x: { ticks: { color: textColor, maxRotation: 45, autoSkip: true }, grid: { color: gridColor } },
              y: { ticks: { color: textColor }, grid: { color: gridColor }, beginAtZero: true },
            },
          },
        });
      })
      .catch(function () {
        var el = document.getElementById("summary-chart-container");
        if (el) el.textContent = "Historie nen\u00ed k dispozici.";
      });
  }

  // Full-buffer fetch on purpose: ranged reads of compressible types are
  // broken on GitHub Pages (Content-Range counts gzipped bytes), and at ~8 MB
  // there is nothing to gain from partial reads anyway.
  Promise.all([
    fetch("data/cars.parquet").then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status + " (cars.parquet)");
      return r.arrayBuffer();
    }),
    fetch("data/cars-meta.json")
      .then(function (r) { return r.ok ? r.json() : null; })
      .catch(function () { return null; }),
  ])
    .then(function (results) {
      return parquetReadObjects({ file: results[0] }).then(function (rows) {
        appMetadata = results[1];
        init(rows);
        setupArchiveToggle();
        hideLoadingOverlay();
      });
    })
    .catch(function (err) {
      hideLoadingOverlay();
      document.getElementById("grid").textContent = "Chyba načítání dat: " + err.message;
    });

  function hideLoadingOverlay() {
    var overlay = document.getElementById("loading-overlay");
    if (overlay) overlay.classList.add("hidden");
  }
})();

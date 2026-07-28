(function () {
  "use strict";

  var STORAGE_KEY = "refCompareFilters";
  var THEME_KEY = "carCompareTheme";
  var COL_STATE_KEY = "refCompareColState";
  var THRESHOLD_KEY = "refCompareThresholds";   // isolated: reference has its own numeric columns
  var COLOUR_ONLY_KEY = "refCompareColourOnly";  // ditto — which ranges only tint
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
    repaintTracks();          // the histogram bars are heat-coloured too
    renderThemeChoices();     // the miniatures show which theme is active
    renderHeatModeChoices();  // palette/style previews are theme-tuned
  }

  window.setTheme = function (theme) {
    if (theme !== "dark" && theme !== "light") return;
    applyTheme(theme);
    try { localStorage.setItem(THEME_KEY, theme); } catch (_) {}
  };

  window.toggleTheme = function () {
    var current = document.documentElement.getAttribute("data-theme") || "dark";
    window.setTheme(current === "dark" ? "light" : "dark");
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
  // truth: the colour tint and the column-filter range are two views of it. Every
  // editor routes through commitRange(); the filter side emits the standard AG
  // number model so the URL codec / chips work unchanged. (Reference persists
  // thresholds to localStorage only; filters go to #f=.)

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
  // reference.json stores some numeric columns as strings ("150") — every value
  // read (ranges, histogram bins, blank counts, filtering) goes through this.
  function numOf(v) {
    if (typeof v === "number") return isFinite(v) ? v : NaN;
    if (v == null || v === "") return NaN;
    var n = parseFloat(v);
    return isFinite(n) ? n : NaN;
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
  // ── Filter model ──────────────────────────────────────────────────────────
  // Blank cells are a real filter question ("only models that HAVE the number",
  // "only the ones missing it") and it maps onto AG's own shapes, so the URL codec
  // and the filter chips need no new token:
  //   hide + range → { inRange }                                (blanks fail)
  //   show + range → { operator:"OR", conditions:[inRange, blank] }
  //   only         → { blank }
  //   nothing set  → null
  var blankModes = {};              // field -> "hide" | "show" | "only"
  var BLANK_COND = { filterType: "number", type: "blank" };

  function blankModeOf(field) { return blankModes[field] || "hide"; }

  function boundsCond(field) {
    var r = rangeOf(field);
    if (r.min == null && r.max == null) return null;
    return { filterType: "number", type: "inRange", filter: r.min, filterTo: r.max };
  }

  function rangeModel(field) {
    if (colourOnly[field]) return null;         // colours the column, filters nothing
    var mode = blankModeOf(field);
    if (mode === "only") return { filterType: "number", type: "blank" };
    var cond = boundsCond(field);
    if (!cond) return null;
    if (mode === "show") {
      return { filterType: "number", operator: "OR", conditions: [cond, BLANK_COND] };
    }
    return cond;
  }

  // A range that only tints. Same {min,max} state as a filtering range — the flag
  // just says "do not turn it into a filter model".
  var colourOnly = {};

  function isColourOnly(field) { return !!colourOnly[field]; }

  function setColourOnly(field, on) {
    if (on) colourOnly[field] = true;
    else delete colourOnly[field];
    persistColourOnly();
  }

  function persistColourOnly() {
    try { localStorage.setItem(COLOUR_ONLY_KEY, JSON.stringify(Object.keys(colourOnly))); } catch (_) {}
  }

  function loadColourOnly() {
    colourOnly = {};
    try {
      var arr = JSON.parse(localStorage.getItem(COLOUR_ONLY_KEY));
      if (Array.isArray(arr)) arr.forEach(function (f) { if (colRanges[f]) colourOnly[f] = true; });
    } catch (_) {}
  }

  function persistThresholds() {
    try { localStorage.setItem(THRESHOLD_KEY, JSON.stringify(userThresholds)); } catch (_) {}
  }

  var rangeFilters = {};   // field -> live RangeFilter instance
  var _rangeTimers = {};

  // The one entry point every range editor calls. Updates shared state, mirrors it
  // into the popup, then debounces the expensive part (recolour + (re)activate the
  // grid filter) so dragging stays smooth.
  function commitRange(field, min, max) {
    setRange(field, min, max);
    if (rangeFilters[field]) rangeFilters[field].renderState();
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

  // Blank-handling / colour-only changes alter the model, not the range, so they
  // apply immediately (no drag to debounce).
  function commitFilterShape(field) {
    if (rangeFilters[field]) rangeFilters[field].renderState();
    if (!gridApi) return;
    gridApi.refreshCells({ force: true });
    gridApi.setColumnFilterModel(field, rangeModel(field)).then(function () {
      gridApi.onFilterChanged();
    });
  }

  // ── The numeric filter popup ──────────────────────────────────────────────
  var HIST_MODES = [
    ["all", "Vše", "Všechny modely v tabulce"],
    ["filter", "Po filtru", "Jen modely, které tabulka teď zobrazuje"],
    ["both", "Obojí", "Bledě všechny, plně po filtru — společné měřítko"],
  ];
  var BLANK_OPTS = [
    ["hide", "Skrýt", "Skrýt modely bez hodnoty"],
    ["show", "Zahrnout", "Zahrnout i modely bez hodnoty"],
    ["only", "Jen ty", "Jen modely bez hodnoty"],
  ];
  var ZOOM_TIP_IN = "Přiblížit osu na rozsah po filtru";
  var ZOOM_TIP_OUT = "Zrušit přiblížení osy";

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  function zoomIconSVG(on) {
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
      'stroke-linecap="round"><circle cx="10.5" cy="10.5" r="6.5"/><path d="M20 20l-4.8-4.8"/>' +
      '<path d="M7.5 10.5h6"/>' + (on ? "" : '<path d="M10.5 7.5v6"/>') + "</svg>";
  }

  // Slide the segmented highlight onto the active button (CSS animates it).
  function slideIndicator(indicator, btn) {
    if (!indicator || !btn || !btn.offsetWidth) return;
    indicator.style.width = btn.offsetWidth + "px";
    indicator.style.transform = "translateX(" + btn.offsetLeft + "px)";
    indicator.style.opacity = "1";
  }

  function segmented(options, active, onPick) {
    var seg = el("div", "seg");
    var ind = el("div", "seg-ind");
    seg.appendChild(ind);
    var btns = {};
    options.forEach(function (o) {
      var b = el("button", null, o[1]);
      b.type = "button";
      b.dataset.value = o[0];
      b.title = o[2];
      if (o[0] === active) b.classList.add("active");
      seg.appendChild(b);
      btns[o[0]] = b;
    });
    seg.addEventListener("click", function (e) {
      var b = e.target.closest("button[data-value]");
      if (!b || b.disabled) return;
      onPick(b.dataset.value);
    });
    return { gui: seg, indicator: ind, buttons: btns };
  }

  function RangeFilter() {}

  RangeFilter.prototype.init = function (params) {
    this.params = params;
    this.field = params.colDef.field;
    rangeFilters[this.field] = this;

    var self = this;
    var field = this.field;
    var range = colRanges[field] || {};
    this.range = range;
    this.dec = _decimals(range.step || 1);

    this.gui = el("div", "range-filter");

    // ── header: name + direction + reset ──
    var nameRow = el("div", "rf-name-row");
    var name = el("span", "rf-name", CHIP_HEADER_NAMES[field] || field);
    name.title = field;
    nameRow.appendChild(name);
    // Only the heat-coloured columns have a good→bad direction; Nabídek / Cena
    // medián are plain counts (RANGE_EXTRA), so claiming one would be a lie.
    if (NUMERIC_COLS.hasOwnProperty(field)) {
      nameRow.appendChild(el("span", "rf-dir", NUMERIC_COLS[field] ? "více = lépe" : "méně = lépe"));
    }
    nameRow.appendChild(el("span", "rf-spacer"));
    var reset = el("button", "th-reset", "⟲");
    reset.type = "button";
    reset.title = "Vymazat rozsah";
    reset.setAttribute("aria-label", "Vymazat rozsah " + field);
    reset.addEventListener("click", function () {
      blankModes[field] = "hide";
      setColourOnly(field, false);
      commitRange(field, null, null);
      commitFilterShape(field);
    });
    nameRow.appendChild(reset);
    this.reset = reset;
    this.gui.appendChild(nameRow);

    // A column whose values are all blank (or a single value) has nothing to bin —
    // it keeps the od/do boxes and the blank switch, without a track.
    var hasTrack = range.min != null && range.max != null && range.max > range.min;

    // ── controls: what the histogram counts + axis zoom + hover readout ──
    if (hasTrack) {
      var ctlRow = el("div", "rf-ctl-row");
      var seg = segmented(HIST_MODES, histMode.mode, function (v) {
        histMode.mode = v;
        if (v === "all") histMode.zoom = false;
        saveHistMode();
        // one global appearance choice — every open track follows
        Object.keys(rangeFilters).forEach(function (f) { rangeFilters[f].applyHistMode(true); });
      });
      this.seg = seg;
      ctlRow.appendChild(seg.gui);

      var zoomBtn = el("button", "ht-zoom");
      zoomBtn.type = "button";
      zoomBtn.innerHTML = zoomIconSVG(false);
      zoomBtn.title = ZOOM_TIP_IN;
      zoomBtn.setAttribute("aria-label", ZOOM_TIP_IN);
      zoomBtn.addEventListener("click", function () {
        histMode.zoom = !histMode.zoom;
        saveHistMode();
        Object.keys(rangeFilters).forEach(function (f) { rangeFilters[f].applyHistMode(true); });
      });
      this.zoomBtn = zoomBtn;
      ctlRow.appendChild(zoomBtn);

      ctlRow.appendChild(el("span", "rf-spacer"));
      this.readout = el("span", "rf-readout empty", "—");
      ctlRow.appendChild(this.readout);
      this.gui.appendChild(ctlRow);
    }

    // ── track + thumbs + value axis ──
    if (hasTrack) {
      var wrap = el("div", "track-wrap");
      var trackEl = el("div", "ht-track");
      wrap.appendChild(trackEl);
      this.trackEl = trackEl;

      var step = range.step || 1;
      this.step = step;
      var rMin = document.createElement("input"), rMax = document.createElement("input");
      [rMin, rMax].forEach(function (r) {
        r.type = "range"; r.min = range.min; r.max = range.max; r.step = step;
        r.style.left = window.HistTrack.GUTTER + "px";
        r.style.width = "calc(100% - " + window.HistTrack.GUTTER + "px)";
      });
      rMin.setAttribute("aria-label", field + " min");
      rMax.setAttribute("aria-label", field + " max");
      this.rMin = rMin; this.rMax = rMax;
      rMin.addEventListener("input", function () {
        if (+rMin.value > +rMax.value) rMin.value = rMax.value;
        var v = _sliderRound(+rMin.value, step);
        var dom = self.drawnDomain();
        self._edit(v <= dom.min ? null : v, undefined);
      });
      rMax.addEventListener("input", function () {
        if (+rMax.value < +rMin.value) rMax.value = rMin.value;
        var v = _sliderRound(+rMax.value, step);
        var dom = self.drawnDomain();
        self._edit(undefined, v >= dom.max ? null : v);
      });
      trackEl.appendChild(rMin);
      trackEl.appendChild(rMax);

      this.xAxis = el("div", "ht-xaxis");
      for (var t = 0; t < 4; t++) this.xAxis.appendChild(el("span"));
      wrap.appendChild(this.xAxis);
      this.gui.appendChild(wrap);

      this.track = makeTrack(trackEl, field, false, function (dom) { self.updateAxis(dom); });
      if (this.track) {
        trackEl.addEventListener("mousemove", function (e) {
          if (!self.track.state) return;
          var r = trackEl.getBoundingClientRect();
          self.showHover(self.track.binAt(self.track.state.m, e.clientX - r.left));
        });
        trackEl.addEventListener("mouseleave", function () { self.clearHover(); });
      }
    }

    // ── od / do ──
    var pair = el("div", "th-pair");
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
    this.pair = pair;
    this.gui.appendChild(pair);

    // ── blank cells ──
    var blankRow = el("div", "rf-blank-row");
    blankRow.appendChild(el("span", "rf-blank-lbl", "Bez hodnoty:"));
    var bseg = segmented(BLANK_OPTS, blankModeOf(field), function (v) {
      blankModes[field] = v;
      if (v !== "hide") setColourOnly(field, false);   // a blank rule must filter
      commitFilterShape(field);
    });
    this.blankSeg = bseg;
    blankRow.appendChild(bseg.gui);
    this.blankCount = el("span", "rf-blank-count");
    blankRow.appendChild(this.blankCount);
    this.gui.appendChild(blankRow);

    // ── colour-only ──
    var checkRow = el("label", "rf-check");
    var check = document.createElement("input");
    check.type = "checkbox";
    check.checked = isColourOnly(field);
    check.addEventListener("change", function () {
      setColourOnly(field, check.checked);
      if (check.checked) blankModes[field] = "hide";
      commitFilterShape(field);
    });
    checkRow.appendChild(check);
    checkRow.appendChild(el("span", null, "Jen barvit, nefiltrovat"));
    checkRow.title = "Rozsah jen barví, nic neskryje";
    this.colourCheck = check;
    this.gui.appendChild(checkRow);

    this.applyHistMode(false);
    this.renderState();
  };

  // Push the global mode/zoom choice into this popup's track + controls.
  RangeFilter.prototype.applyHistMode = function (animate) {
    if (!this.track) { this.syncControls(); return; }
    this.track.setState({ mode: histMode.mode, zoom: histMode.zoom, range: this.trackRange() }, animate);
    this.updateAxis(this.track.domain());
    this.renderState();      // the thumbs re-scale to the domain that is now drawn
  };

  // Current bounds as 0..1 of the drawn domain (null bound = open end).
  RangeFilter.prototype.trackRange = function () {
    var r = rangeOf(this.field);
    var dom = this.track ? this.track.domain() : { min: this.range.min, max: this.range.max };
    var span = dom.max - dom.min;
    if (!(span > 0)) return { lo: 0, hi: 1 };
    var lo = r.min != null ? (r.min - dom.min) / span : 0;
    var hi = r.max != null ? (r.max - dom.min) / span : 1;
    lo = Math.max(0, Math.min(1, lo));
    hi = Math.max(lo, Math.min(1, hi));
    return { lo: lo, hi: hi };
  };

  RangeFilter.prototype.syncControls = function () {
    var field = this.field;
    if (this.seg) {
      Object.keys(this.seg.buttons).forEach(function (k) {
        this.seg.buttons[k].classList.toggle("active", k === histMode.mode);
      }, this);
      slideIndicator(this.seg.indicator, this.seg.buttons[histMode.mode]);
    }
    if (this.zoomBtn) {
      var zoomed = histMode.zoom && histMode.mode !== "all";
      this.zoomBtn.disabled = histMode.mode === "all";
      this.zoomBtn.classList.toggle("on", zoomed);
      this.zoomBtn.innerHTML = zoomIconSVG(zoomed);
      this.zoomBtn.title = zoomed ? ZOOM_TIP_OUT : ZOOM_TIP_IN;
      this.zoomBtn.setAttribute("aria-label", this.zoomBtn.title);
    }
    var mode = blankModeOf(field);
    if (this.blankSeg) {
      Object.keys(this.blankSeg.buttons).forEach(function (k) {
        this.blankSeg.buttons[k].classList.toggle("active", k === mode);
      }, this);
      slideIndicator(this.blankSeg.indicator, this.blankSeg.buttons[mode]);
    }
    // "only blanks" makes the numeric range meaningless — grey it out rather than
    // keep a range that silently does nothing.
    var off = mode === "only";
    if (this.trackEl) this.trackEl.classList.toggle("disabled", off);
    if (this.pair) this.pair.classList.toggle("disabled", off);
    if (this.colourCheck) {
      this.colourCheck.checked = isColourOnly(field);
      this.colourCheck.disabled = off;
    }
    if (this.blankCount) {
      var missing = blankCountOf(field);
      this.blankCount.textContent = missing ? "(" + window.HistTrack.fmtInt(missing) + " modelů)" : "";
    }
    var active = rangeOf(field).min != null || rangeOf(field).max != null || mode === "only";
    this.reset.classList.toggle("on", active);
  };

  RangeFilter.prototype.updateAxis = function (dom) {
    if (!this.xAxis || !this.track) return;
    var spans = this.xAxis.children;
    var unit = unitOf(this.field);
    for (var i = 0; i < spans.length; i++) {
      var v = dom.min + (dom.max - dom.min) * (i / (spans.length - 1));
      spans[i].textContent = window.HistTrack.fmtValue(v, this.dec, false) +
        (i === spans.length - 1 && unit ? " " + unit : "");
    }
    var m = this.track.state && this.track.state.m;
    if (m) {
      this.xAxis.style.paddingLeft = m.x0 + "px";
      this.xAxis.style.paddingRight = Math.max(0, m.w - m.x0 - m.barsW) + "px";
    }
  };

  RangeFilter.prototype.showHover = function (i) {
    if (!this.track) return;
    if (this.track.hover === i && this.readout && !this.readout.classList.contains("empty")) return;
    this.track.hover = i;
    this.track.repaint();
    var info = this.track.binInfo(i);
    if (!info || !this.readout) return;
    var unit = unitOf(this.field);
    var span = window.HistTrack.fmtValue(info.lo, this.dec, false) + "–" +
      window.HistTrack.fmtValue(info.hi, this.dec, false) + (unit ? " " + unit : "");
    this.readout.classList.remove("empty");
    this.readout.textContent = "";
    this.readout.appendChild(document.createTextNode(span + " · "));
    var b = document.createElement("b");
    b.textContent = window.HistTrack.fmtInt(info.count);
    this.readout.appendChild(b);
    this.readout.appendChild(document.createTextNode(" modelů"));
  };

  RangeFilter.prototype.clearHover = function () {
    if (!this.track) return;
    this.track.hover = null;
    this.track.repaint();
    if (this.readout) this.readout.classList.add("empty");
  };

  // Change one bound (undefined = leave the other as-is), keeping the paired value.
  RangeFilter.prototype._edit = function (min, max) {
    var r = rangeOf(this.field);
    commitRange(this.field, min === undefined ? r.min : min, max === undefined ? r.max : max);
  };

  // The domain currently DRAWN (zoom shrinks it onto the filtered rows); the thumbs
  // must span the same range as the axis under them.
  RangeFilter.prototype.drawnDomain = function () {
    if (this.track) return this.track.domain();
    var rg = this.range || {};
    return { min: rg.min, max: rg.max };
  };

  // Mirror shared state into this popup's own controls (skip the focused one).
  RangeFilter.prototype.renderState = function () {
    var r = rangeOf(this.field), rg = this.range || {};
    var dom = this.drawnDomain();
    [this.rMin, this.rMax].forEach(function (input) {
      if (!input || dom.min == null || dom.max == null) return;
      input.min = dom.min;
      input.max = dom.max;
    });
    if (this.rMin && document.activeElement !== this.rMin) {
      this.rMin.value = r.min != null ? Math.max(dom.min, Math.min(dom.max, r.min)) : dom.min;
    }
    if (this.rMax && document.activeElement !== this.rMax) {
      this.rMax.value = r.max != null ? Math.max(dom.min, Math.min(dom.max, r.max)) : dom.max;
    }
    if (this.minInput && document.activeElement !== this.minInput) this.minInput.value = fmtRangeNum(this.field, r.min);
    if (this.maxInput && document.activeElement !== this.maxInput) this.maxInput.value = fmtRangeNum(this.field, r.max);
    if (this.track) {
      this.track.range = this.trackRange();
      this.track.repaint();
    }
    this.syncControls();
  };

  RangeFilter.prototype.doesFilterPass = function (params) {
    var field = this.field;
    var mode = blankModeOf(field);
    var n = numOf(params.data[field]);   // reference stores some numeric cols as strings
    var blank = isNaN(n);
    if (mode === "only") return blank;
    if (blank) return mode === "show";
    var r = rangeOf(field);
    if (r.min != null && n < r.min) return false;
    if (r.max != null && n > r.max) return false;
    return true;
  };

  RangeFilter.prototype.isFilterActive = function () {
    if (blankModeOf(this.field) === "only") return true;
    if (isColourOnly(this.field)) return false;
    var r = rangeOf(this.field);
    return r.min != null || r.max != null;
  };

  RangeFilter.prototype.getModel = function () { return rangeModel(this.field); };

  RangeFilter.prototype.setModel = function (model) {
    var field = this.field;
    // Turning a range colour-only means clearing the FILTER model while keeping the
    // range itself — and AG clears a filter by calling setModel(null), which would
    // otherwise wipe the very range we are preserving.
    if (!model && isColourOnly(field)) {
      blankModes[field] = "hide";
      this.renderState();
      return;
    }
    if (!model && blankModeOf(field) === "show") {
      // "Zahrnout" with no bounds filters nothing, so AG hands back a null model —
      // that is agreement, not a reason to drop the choice.
      setRange(field, null, null);
      this.renderState();
      return;
    }
    var min = null, max = null, mode = "hide";
    var cond = model;
    if (model && model.operator && model.conditions) {
      // OR-with-blank is how "Zahrnout" is expressed
      var hasBlank = false, bounds = null;
      model.conditions.forEach(function (c) {
        if (c.type === "blank") hasBlank = true;
        else bounds = c;
      });
      if (hasBlank) mode = "show";
      cond = bounds;
    }
    if (cond) {
      if (cond.type === "blank") {
        mode = "only";
        cond = null;
      } else if (cond.type === "inRange") {
        min = cond.filter != null ? +cond.filter : null;
        max = cond.filterTo != null ? +cond.filterTo : null;
      } else {
        // Tolerate simple bound models (e.g. a legacy greaterThanOrEqual link).
        var v = cond.filter != null ? +cond.filter : null;
        if (cond.type === "greaterThan" || cond.type === "greaterThanOrEqual") min = v;
        else if (cond.type === "lessThan" || cond.type === "lessThanOrEqual") max = v;
        else if (cond.type === "equals") { min = v; max = v; }
      }
    }
    blankModes[field] = mode;
    if (model) delete colourOnly[field];     // an incoming model means it filters
    setRange(field, min, max);               // no commitRange → no debounce/loop
    this.renderState();
    if (gridApi) gridApi.refreshCells({ force: true, columns: [field] });
  };

  RangeFilter.prototype.getGui = function () { return this.gui; };

  RangeFilter.prototype.destroy = function () {
    if (rangeFilters[this.field] === this) delete rangeFilters[this.field];
    if (this.track) dropTrack(this.track);
  };

  RangeFilter.prototype.getModelAsString = function () {
    var mode = blankModeOf(this.field);
    if (mode === "only") return "bez hodnoty";
    var r = rangeOf(this.field);
    var suffix = mode === "show" ? " nebo bez hodnoty" : "";
    var f = function (n) { return fmtRangeNum(this.field, n); }.bind(this);
    if (r.min == null && r.max == null) return "";
    if (r.min != null && r.max != null) return f(r.min) + "–" + f(r.max) + suffix;
    if (r.min != null) return "≥ " + f(r.min) + suffix;
    return "≤ " + f(r.max) + suffix;
  };

  RangeFilter.prototype.afterGuiAttached = function () {
    // The track needs a laid-out host to measure; the popup is attached now.
    var self = this;
    requestAnimationFrame(function () {
      self.applyHistMode(false);
      self.renderState();
    });
    if (this.minInput) this.minInput.focus();
  };

  // ── Distribution track ────────────────────────────────────────────────────
  // The numeric range sits on a histogram of the column's own values instead of
  // an inert gradient. Drawing lives in site/hist-track.js; this section only
  // feeds it data + colours and caches the two value arrays it bins.
  //
  //   "Vše"      — every row in the grid
  //   "Po filtru" — the rows the grid currently shows
  //   "Obojí"    — both layers on a shared scale
  //
  // Mode + zoom are a GLOBAL appearance choice shared with the index page
  // (same localStorage key, same shape), like the palette and the theme.
  var HIST_MODE_KEY = "carCompareHistMode";
  var histRows = [];              // every row currently in the grid
  var allValueCache = {};         // field -> number[] (all rows)
  var filteredCache = {};         // field -> { version, values }
  var filterVersion = 0;          // bumped whenever the grid's filters change
  var histMode = { mode: "all", zoom: false };

  function setHistRows(rows) {
    histRows = rows || [];
    allValueCache = {};
    filteredCache = {};
    blankCounts = {};
  }

  function loadHistMode() {
    try {
      var s = JSON.parse(localStorage.getItem(HIST_MODE_KEY));
      if (s && (s.mode === "all" || s.mode === "filter" || s.mode === "both")) {
        histMode = { mode: s.mode, zoom: !!s.zoom && s.mode !== "all" };
      }
    } catch (_) {}
  }

  function saveHistMode() {
    try { localStorage.setItem(HIST_MODE_KEY, JSON.stringify(histMode)); } catch (_) {}
  }

  function allValuesFor(field) {
    if (allValueCache[field]) return allValueCache[field];
    var out = [];
    for (var i = 0; i < histRows.length; i++) {
      var n = numOf(histRows[i][field]);
      if (!isNaN(n)) out.push(n);
    }
    allValueCache[field] = out;
    return out;
  }

  // Rows the grid shows right now. One pass per column, cached until the filter
  // model changes — the tracks re-bin from the cached array every animation frame,
  // so this must never run per frame.
  function filteredValuesFor(field) {
    var hit = filteredCache[field];
    if (hit && hit.version === filterVersion) return hit.values;
    var out = [];
    if (gridApi) {
      gridApi.forEachNodeAfterFilter(function (node) {
        if (!node.data) return;
        var n = numOf(node.data[field]);
        if (!isNaN(n)) out.push(n);
      });
    }
    filteredCache[field] = { version: filterVersion, values: out };
    return out;
  }

  // "Výkon (kW)" → "kW"; the axis prints the unit once, at its right end.
  function unitOf(field) {
    var m = field.match(/\(([^)]+)\)$/);
    return m ? m[1] : "";
  }

  // How many rows have no number in this column — the blanks switch prints it, so
  // the choice is informed (EV spec columns are blank on every combustion model).
  var blankCounts = {};
  function blankCountOf(field) {
    if (blankCounts[field] != null) return blankCounts[field];
    var n = 0;
    for (var i = 0; i < histRows.length; i++) {
      if (isNaN(numOf(histRows[i][field]))) n++;
    }
    blankCounts[field] = n;
    return n;
  }

  function cssColourTriplet(name) {
    var raw = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    var hex = raw.replace("#", "");
    if (hex.length === 3) hex = hex[0] + hex[0] + hex[1] + hex[1] + hex[2] + hex[2];
    var n = parseInt(hex || "888888", 16);
    if (isNaN(n)) return "136,136,136";
    return ((n >> 16) & 255) + "," + ((n >> 8) & 255) + "," + (n & 255);
  }

  // Live tracks, so a palette/theme/data change can repaint them all.
  var liveTracks = [];

  function makeTrack(host, field, compact, onFrame) {
    var rg = colRanges[field] || {};
    if (rg.min == null || rg.max == null || rg.max <= rg.min) return null;
    // RANGE_EXTRA columns (Nabídek, Cena medián) carry no good→bad axis — their
    // bars take the flat accent colour instead of a heat gradient.
    var heat = NUMERIC_COLS.hasOwnProperty(field);
    var track = window.HistTrack.create(host, {
      min: rg.min, max: rg.max, step: rg.step, dec: _decimals(rg.step || 1),
      unit: unitOf(field),
      noGroup: false,
      greenHigh: !!NUMERIC_COLS[field],
      allValues: function () { return allValuesFor(field); },
      filteredValues: function () { return filteredValuesFor(field); },
      colourAt: heat ? function (t) { return heatRGB(t); }
                     : function () { return cssColourTriplet("--clr-accent"); },
      cssColour: cssColourTriplet,
      isDark: isDarkTheme,
      compact: !!compact,
      onFrame: onFrame,
    });
    track.field = field;
    liveTracks.push(track);
    return track;
  }

  function dropTrack(track) {
    var i = liveTracks.indexOf(track);
    if (i >= 0) liveTracks.splice(i, 1);
    if (track) track.destroy();
  }

  // Palette + theme change the bar colours; a filter change changes the counts.
  function repaintTracks(invalidate) {
    // initTheme() runs at module top, before `var liveTracks` is assigned.
    if (!liveTracks) return;
    for (var i = 0; i < liveTracks.length; i++) {
      if (invalidate) liveTracks[i].invalidate();
      liveTracks[i].render(false);
    }
  }

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

  // Same cap as the index grid (site/app.js) — AG defaults combined AND/OR
  // conditions to 2; five is the practical limit we allow.
  var MAX_FILTER_CONDITIONS = 5;

  var DATE_FILTER_PARAMS = {
    browserDatePicker: false,
    buttons: ["reset"],
    maxNumConditions: MAX_FILTER_CONDITIONS,
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
    { field: "Servis (Kč/rok)", filter: RangeFilter, width: 120, type: "numericColumn", headerName: "Servis (Kč/rok)", cellRenderer: servisRenderer, headerTooltip: "Odhadované průměrné roční náklady na servis a údržbu (dílna) za 5 let: pravidelný servis + běžné opotřebení (brzdy, rozvody, kapaliny). Bez pneumatik, paliva, pojištění a ztráty hodnoty.\nVzorec: základ 12000 × palivo × značka × karoserie × objem. Kalibrovaný odhad (vždy „odhad“) na reálné údaje (ADAC/ČR) — podrobnosti a zdroje v Přehledu datasetu na hlavní stránce.\n⚠ = mimo věrohodný rozsah 3000–60000 Kč/rok.\nBarva buňky: zelená = levnější servis, červená = dražší." },
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
    "Servis (Kč/rok)": false,
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
    renderHeatModeChoices();   // reflect new active state
    renderThemeChoices();      // the miniatures preview the palette too
    repaintTracks();           // histogram bars are heat-coloured
  };

  function isDarkTheme() {
    return (document.documentElement.getAttribute("data-theme") || "dark") === "dark";
  }

  function lerp3(a, b, u) {
    return [Math.round(a[0] + (b[0] - a[0]) * u),
            Math.round(a[1] + (b[1] - a[1]) * u),
            Math.round(a[2] + (b[2] - a[2]) * u)];
  }

  function heatRGBof(paletteKey, t, darkOverride) {
    var pal = HEAT_PALETTES[paletteKey] || HEAT_PALETTES.redgreen;
    var dark = darkOverride == null ? isDarkTheme() : darkOverride;
    var mid = dark ? [71, 85, 105] : [148, 163, 184];
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

  // Colour-only ranges have no AG filter model (they hide nothing), so they ride
  // into the chip bar as extra chips — otherwise a column could stay tinted with
  // nothing on screen saying so.
  function colourOnlyChips() {
    return Object.keys(colourOnly).filter(function (f) {
      var r = rangeOf(f);
      return r.min != null || r.max != null;
    }).map(function (field) {
      var r = rangeOf(field);
      var summary = r.min != null && r.max != null
        ? fmtRangeNum(field, r.min) + "–" + fmtRangeNum(field, r.max)
        : (r.min != null ? "od " + fmtRangeNum(field, r.min) : "do " + fmtRangeNum(field, r.max));
      return {
        field: field,
        label: (CHIP_HEADER_NAMES && CHIP_HEADER_NAMES[field]) || field,
        summary: summary,
        tag: "jen barva",
        onRemove: function () { clearColumnRange(field); },
      };
    });
  }

  // Drop a column's range entirely: colour, blank rule and filter model.
  function clearColumnRange(field) {
    setRange(field, null, null);
    setColourOnly(field, false);
    delete blankModes[field];
    persistThresholds();
    if (rangeFilters[field]) rangeFilters[field].renderState();
    if (!gridApi) return;
    gridApi.refreshCells({ force: true });
    gridApi.setColumnFilterModel(field, null).then(function () {
      gridApi.onFilterChanged();
    });
  }

  function updateFilterChips() {
    if (!window.renderFilterChips) return;
    window.renderFilterChips({
      gridApi: gridApi,
      barEl: document.getElementById("filter-chips-bar"),
      headerNames: CHIP_HEADER_NAMES,
      onClearAll: window.clearFilters,
      extraChips: colourOnlyChips(),
      onRemoveField: function (field) {
        if (!colRanges[field]) return;      // only the RangeFilter columns
        setRange(field, null, null);
        setColourOnly(field, false);
        delete blankModes[field];
        persistThresholds();
      },
    });
  }

  // ── Toolbar actions ──

  window.clearFilters = function () {
    userThresholds = {};
    colourOnly = {};
    blankModes = {};
    persistThresholds();
    persistColourOnly();
    localStorage.removeItem(STORAGE_KEY);
    if (gridApi) {
      gridApi.setFilterModel(null); // fires onFilterChanged → writeHash
      gridApi.refreshCells({ force: true });   // thresholds gone → heat scale is auto again
    } else writeHash();
    // A colour-only range leaves the AG model EMPTY, so setFilterModel(null) is a
    // no-op there and onFilterChanged never fires — the chips must be re-rendered
    // here or a cleared "jen barva" chip stays on screen.
    updateFilterChips();
    writeHash();
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

  // "Servis (Kč/rok)" cell (task #23): the estimated number, plus a ⚠ badge when
  // the row's estimate hit the plausibility clamp (row["Servis mimo rozsah"]) —
  // like the missing-spec ⚠, so out-of-range models are never a silent value.
  function servisRenderer(params) {
    if (params.value == null || params.value === "") return "—";
    var n = Number(params.value);
    if (isNaN(n)) return "—";
    var txt = n.toLocaleString("cs-CZ");
    if (params.data && params.data["Servis mimo rozsah"]) {
      return txt + ' <span class="missing-badge" title="Mimo věrohodný rozsah 3000–60000 Kč/rok">⚠</span>';
    }
    return txt;
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

  // Reset ALL columns: clears every colour threshold AND its coupled range filter
  // (including a blank-only rule, which carries no {min,max} of its own).
  window.resetThresholds = function () {
    var seen = {}, fields = [];
    Object.keys(userThresholds).concat(Object.keys(blankModes)).forEach(function (f) {
      if (!seen[f]) { seen[f] = 1; fields.push(f); }
    });
    userThresholds = {};
    colourOnly = {};
    blankModes = {};
    try {
      localStorage.removeItem(THRESHOLD_KEY);
      localStorage.removeItem(COLOUR_ONLY_KEY);
    } catch (_) {}
    if (gridApi) {
      fields.forEach(function (f) { gridApi.setColumnFilterModel(f, null); });
      gridApi.refreshCells({ force: true });
      gridApi.onFilterChanged();
    }
  };

  function _sliderRound(v, step) {
    return parseFloat((Math.round(v / step) * step).toFixed(4));
  }

  // Theme is chosen from two miniatures of the page itself (header, filter chip,
  // grid rows with heat bars) painted in that theme's own tokens — a pair of plain
  // swatches would not show what actually changes. Lives in the colour drawer
  // because it is the same kind of choice as the palette, not a tool.
  var THEME_MINI = {
    dark: { bg: "#0f172a", surf: "#1e293b", border: "#334155", muted: "#94a3b8", acc: "#e0872e", barA: 0.75 },
    light: { bg: "#f8fafc", surf: "#ffffff", border: "#e2e8f0", muted: "#64748b", acc: "#b4611c", barA: 0.5 },
  };

  function themeMiniature(theme) {
    var t = THEME_MINI[theme];
    var card = el("div", "theme-mini");
    card.style.background = t.bg;
    card.style.borderColor = t.border;

    var head = el("div", "tm-head");
    head.style.background = t.surf;
    head.style.borderColor = t.border;
    var dot = el("span", "tm-dot");
    dot.style.background = t.acc;
    head.appendChild(dot);
    [24, 17, 13].forEach(function (w) {
      var tab = el("span", "tm-tab");
      tab.style.width = w + "px";
      tab.style.background = t.muted;
      head.appendChild(tab);
    });
    card.appendChild(head);

    var chip = el("div", "tm-chip");
    chip.style.borderColor = t.acc;
    chip.style.background = theme === "dark" ? "rgba(224,135,46,0.16)" : "rgba(180,97,28,0.12)";
    card.appendChild(chip);

    var grid = el("div", "tm-grid");
    [[0.15, 0.9], [0.4, 0.62], [0.62, 0.44], [0.85, 0.24], [0.5, 0.7]].forEach(function (r) {
      var row = el("div", "tm-row");
      row.style.borderColor = t.border;
      var lbl = el("span", "tm-lbl");
      lbl.style.background = t.muted;
      row.appendChild(lbl);
      var cell = el("span", "tm-cell");
      var rgb = heatRGBof(heatMode.palette, r[0], theme === "dark");
      var pct = Math.round(r[1] * 100);
      cell.style.background = "linear-gradient(90deg,rgba(" + rgb + "," + t.barA + ") 0,rgba(" + rgb + "," +
        t.barA + ") " + pct + "%,rgba(" + rgb + ",0.14) " + pct + "%,rgba(" + rgb + ",0.14) 100%)";
      row.appendChild(cell);
      grid.appendChild(row);
    });
    card.appendChild(grid);
    return card;
  }

  function renderThemeChoices() {
    var wrap = document.getElementById("theme-choices");
    if (!wrap || typeof heatMode === "undefined" || !heatMode) return;
    while (wrap.firstChild) wrap.removeChild(wrap.firstChild);
    var current = document.documentElement.getAttribute("data-theme") || "dark";
    [["dark", "Tmavý"], ["light", "Světlý"]].forEach(function (pair) {
      var btn = el("button", "theme-card" + (current === pair[0] ? " active" : ""));
      btn.type = "button";
      btn.title = pair[1] + " motiv";
      btn.setAttribute("aria-pressed", String(current === pair[0]));
      btn.appendChild(themeMiniature(pair[0]));
      btn.appendChild(el("span", "theme-card-lbl", pair[1]));
      btn.addEventListener("click", function () { window.setTheme(pair[0]); });
      wrap.appendChild(btn);
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
    // applyTheme() runs at module top, before `var heatMode` is assigned.
    if (typeof heatMode === "undefined" || !heatMode) return;
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
    // A drawer control that re-renders its own row (theme / palette / style) detaches
    // the clicked button, and closest() on a detached node can no longer see
    // #settings-panel — so the drawer used to close on every appearance choice. A node
    // that is no longer in the document cannot be an "outside" click.
    if (!e.target.isConnected) return;
    // Drawer closes on any click outside it (opening click comes from .menu-wrap).
    if (!c("#settings-panel") && !c(".menu-wrap")) window.closeColorSettings();
    // Price popup closes on any click outside it and outside the cell that opened it.
    if (!c("#price-popup") && !c(".rc-price-cell") && !c(".rc-count-cell")) closePricePopup();
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") { closeToolsMenu(); window.closeColorSettings(); closePricePopup(); }
  });

  // The colour drawer is appearance only — theme, palette, style. Per-column
  // ranges live in the column-filter popup (one {min,max} state, one view).
  window.openColorSettings = function () {
    closeToolsMenu();
    renderHeatModeChoices();
    renderThemeChoices();
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
    setHistRows(data);
    loadThresholds();
    loadColourOnly();
    loadHeatMode();
    loadHistMode();
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
        filterParams: { buttons: ["reset"], maxNumConditions: MAX_FILTER_CONDITIONS },
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
        // "Po filtru" / "Obojí" count the rows the grid shows, so every filter
        // change invalidates the cached arrays and repaints the open tracks.
        filterVersion++;
        repaintTracks(true);
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

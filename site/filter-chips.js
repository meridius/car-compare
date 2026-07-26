// Shared helper: renders an "active filters" chip bar above the grid.
// Used by both index.html (app.js, ES module) and reference.html (reference.js,
// classic script) — kept as a plain classic script so both can call the global
// window.renderFilterChips without needing a shared module system.
(function () {
  "use strict";

  var CONDITION_LABELS = {
    equals: "=",
    notEqual: "≠",
    contains: "obsahuje",
    notContains: "neobsahuje",
    startsWith: "začíná na",
    endsWith: "končí na",
    lessThan: "<",
    lessThanOrEqual: "≤",
    greaterThan: ">",
    greaterThanOrEqual: "≥",
    blank: "prázdné",
    notBlank: "neprázdné",
  };

  function summarizeSet(model) {
    var vals = (model.values || []).map(function (v) {
      return v == null ? "(Prázdné)" : v;
    });
    if (vals.length <= 3) return vals.join(", ");
    return vals.slice(0, 3).join(", ") + " +" + (vals.length - 3);
  }

  // Date models carry the value in dateFrom/dateTo (not filter/filterTo), as
  // "YYYY-MM-DD HH:mm:ss" — show the day only. Reading .filter here gave "undefined".
  function dayOnly(v) { return v == null ? "" : String(v).slice(0, 10); }

  function summarizeCondition(cond) {
    if (!cond) return "";
    if (cond.filterType === "set") return summarizeSet(cond);
    if (cond.filterType === "date") {
      if (cond.type === "blank" || cond.type === "notBlank") return CONDITION_LABELS[cond.type] || cond.type;
      if (cond.type === "inRange") return "od " + dayOnly(cond.dateFrom) + " do " + dayOnly(cond.dateTo);
      var opd = CONDITION_LABELS[cond.type] || cond.type || "";
      return (opd + " " + dayOnly(cond.dateFrom)).trim();
    }
    if (cond.type === "inRange") {
      // The RangeFilter emits an open bound as null ("od 100 do null" otherwise).
      if (cond.filter == null) return "do " + cond.filterTo;
      if (cond.filterTo == null) return "od " + cond.filter;
      return "od " + cond.filter + " do " + cond.filterTo;
    }
    if (cond.type === "blank" || cond.type === "notBlank") {
      return CONDITION_LABELS[cond.type] || cond.type;
    }
    var op = CONDITION_LABELS[cond.type] || cond.type || "";
    var val = cond.filter != null ? cond.filter : "";
    return (op + " " + val).trim();
  }

  function summarizeModel(model) {
    // Combined filters (AND/OR of multiple conditions) carry `conditions`.
    if (model.conditions && model.conditions.length) {
      var joiner = model.operator === "OR" ? " nebo " : " a ";
      return model.conditions.map(summarizeCondition).join(joiner);
    }
    return summarizeCondition(model);
  }

  // Open the column-filter popup for `field` — the same popup the column-header
  // filter icon opens. A hidden column has no header to anchor the popup to, so
  // unhide it first; a scrolled-away one is scrolled into view.
  function openColumnFilter(gridApi, field) {
    try {
      var col = gridApi.getColumn ? gridApi.getColumn(field) : null;
      if (col && col.isVisible && !col.isVisible() && gridApi.setColumnsVisible) {
        gridApi.setColumnsVisible([field], true);
      }
      if (gridApi.ensureColumnVisible) gridApi.ensureColumnVisible(field);
      if (gridApi.showColumnFilter) gridApi.showColumnFilter(field);
    } catch (_) { /* a chip click must never break the page */ }
  }

  // opts: { gridApi, barEl, headerNames: {field: label}, onClearAll: fn }
  window.renderFilterChips = function (opts) {
    var gridApi = opts.gridApi;
    var bar = opts.barEl;
    if (!gridApi || !bar) return;

    var model = gridApi.getFilterModel() || {};
    var fields = Object.keys(model);

    while (bar.firstChild) bar.removeChild(bar.firstChild);

    if (!fields.length) {
      bar.classList.add("hidden");
      return;
    }
    bar.classList.remove("hidden");

    fields.forEach(function (field) {
      var headerName = (opts.headerNames && opts.headerNames[field]) || field;
      var summary = summarizeModel(model[field]);

      var chip = document.createElement("span");
      chip.className = "filter-chip";
      chip.title = headerName + ": " + summary;

      // The label is a button: clicking a chip opens that column's filter popup
      // (edit in place) — the [×] next to it still removes the filter outright.
      // No title on it, so hovering shows the chip's full "Header: summary".
      var label = document.createElement("button");
      label.type = "button";
      label.className = "filter-chip-label";
      label.textContent = headerName + ": " + summary;
      label.setAttribute("aria-label", "Upravit filtr „" + headerName + "“");
      label.addEventListener("click", function () {
        openColumnFilter(gridApi, field);
      });
      chip.appendChild(label);

      var closeBtn = document.createElement("button");
      closeBtn.type = "button";
      closeBtn.className = "filter-chip-close";
      closeBtn.textContent = "×";
      closeBtn.title = "Odebrat filtr „" + headerName + "“";
      closeBtn.addEventListener("click", function () {
        var current = gridApi.getFilterModel() || {};
        delete current[field];
        gridApi.setFilterModel(current);
      });
      chip.appendChild(closeBtn);

      bar.appendChild(chip);
    });

    if (fields.length >= 2 && opts.onClearAll) {
      var clearBtn = document.createElement("button");
      clearBtn.type = "button";
      clearBtn.className = "filter-chips-clear";
      clearBtn.textContent = "Vymazat vše";
      clearBtn.addEventListener("click", opts.onClearAll);
      bar.appendChild(clearBtn);
    }
  };
})();

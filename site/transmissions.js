// Transmission overview page (#28) — static seed catalogue + live counts from
// the same cars.parquet payload the other pages load (hyparquet, snappy).
import { parquetReadObjects } from "https://cdn.jsdelivr.net/npm/hyparquet@1.26.2/+esm";

(function () {
  "use strict";

  var THEME_KEY = "carCompareTheme";

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    document.getElementById("btn-theme").textContent = theme === "dark" ? "☾" : "☀";
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

  var AUTOMAT_VALUES = { "Automatická": true, "Automat": true };
  var MANUAL_VALUES = { "Manuální": true, "Manual": true };

  function setCount(key, value) {
    var el = document.querySelector('.trans-count[data-count-key="' + key + '"]');
    if (el) el.textContent = value;
  }

  function computeCounts(rows) {
    var counts = { manual: 0, automat: 0, dsg: 0, ev: 0 };
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i];
      var prevodovka = row["Převodovka"] || "";
      var dsg = row["Dvouspojková převodovka"] === "Ano";
      if (dsg) {
        counts.dsg++;
      } else if (AUTOMAT_VALUES[prevodovka]) {
        counts.automat++;
      } else if (MANUAL_VALUES[prevodovka]) {
        counts.manual++;
      }
      if (row["Typ"] === "Elektrické") counts.ev++;
    }
    return counts;
  }

  // Full-buffer fetch, same rationale as app.js/reference.js: GitHub Pages
  // corrupts Range reads for compressible types, and the payload is small
  // enough that partial reads buy nothing.
  fetch("data/cars.parquet")
    .then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.arrayBuffer();
    })
    .then(function (buf) { return parquetReadObjects({ file: buf }); })
    .then(function (rows) {
      var counts = computeCounts(rows);
      setCount("manual", counts.manual + " vozů");
      setCount("automat", counts.automat + " vozů");
      setCount("dsg", counts.dsg + " vozů");
      setCount("ev", counts.ev + " vozů");
      var rc = document.getElementById("row-count");
      if (rc) rc.textContent = rows.length + " vozů v datasetu";
    })
    .catch(function () {
      // Live counts are a nice-to-have; the seed catalogue itself is fully
      // static and useful without them.
      var rc = document.getElementById("row-count");
      if (rc) rc.textContent = "";
    });
})();

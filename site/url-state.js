// Shared compact URL-state codec for the dashboard pages (index + reference).
// See docs/gotchas.md → "site — URL state codec".
//
// Shareable state lives in the URL *fragment* (`#f=` filters, `#t=` colour
// thresholds — index only), never the query string: the fragment is never sent
// to the server or leaked in the Referer header (it would be, to the jsdelivr
// CDN, as a query param). Column layout is deliberately NOT in the URL — it is
// per-browser localStorage state (would bloat the URL with the full ordered
// column list on any change). Each key is a compact, human-readable codec — no
// base64. `btoa` also can't encode the Czech column names (throws on non-Latin1),
// which silently broke the old `?cols=`.
//
// enc()/dec() are the escaping primitives: enc() percent-encodes everything
// encodeURIComponent does PLUS the four structural chars it leaves raw and we use
// as delimiters (- _ ~ *). So an enc()'d token is drawn from [A-Za-z0-9.!'()] +
// %XX and can never contain a delimiter → split is always unambiguous. `*` (raw)
// is the reserved sentinel for a null set value (the SetFilter blank bucket).
(function () {
  "use strict";

  function enc(s) {
    return encodeURIComponent(String(s)).replace(/[-_~*]/g, function (c) {
      return "%" + c.charCodeAt(0).toString(16).toUpperCase();
    });
  }
  function dec(s) {
    try { return decodeURIComponent(s); } catch (_) { return s; }
  }

  // op-code ⇆ AG Grid filter `type` (1 char each, kept distinct across text/number)
  var TXT_OP = { contains: "c", notContains: "C", equals: "e", notEqual: "E", startsWith: "s", endsWith: "d", blank: "b", notBlank: "B" };
  var NUM_OP = { equals: "e", notEqual: "E", greaterThan: "g", greaterThanOrEqual: "G", lessThan: "l", lessThanOrEqual: "L", inRange: "r", blank: "b", notBlank: "B" };
  function invert(m) { var o = {}; for (var k in m) o[m[k]] = k; return o; }
  var TXT_OP_REV = invert(TXT_OP), NUM_OP_REV = invert(NUM_OP);

  function encSimpleCond(c) {
    if (c.filterType === "number") {
      var body = "n" + (NUM_OP[c.type] || "e");
      if (c.type === "blank" || c.type === "notBlank") return body;
      body += c.filter != null ? enc(c.filter) : "";
      if (c.type === "inRange") body += "-" + (c.filterTo != null ? enc(c.filterTo) : "");
      return body;
    }
    var t = "t" + (TXT_OP[c.type] || "c");
    if (c.type === "blank" || c.type === "notBlank") return t;
    return t + enc(c.filter != null ? c.filter : "");
  }

  function decSimpleCond(body) {
    var kind = body[0], op, rest = body.slice(2), cond;
    if (kind === "n") {
      op = NUM_OP_REV[body[1]] || "equals";
      cond = { filterType: "number", type: op };
      if (op === "blank" || op === "notBlank") return cond;
      if (op === "inRange") {
        var i = rest.indexOf("-"); // '-' is escaped inside values → raw '-' is the range sep
        var a = i < 0 ? rest : rest.slice(0, i);
        var b = i < 0 ? "" : rest.slice(i + 1);
        cond.filter = a === "" ? null : parseFloat(dec(a));
        cond.filterTo = b === "" ? null : parseFloat(dec(b));
      } else {
        cond.filter = rest === "" ? null : parseFloat(dec(rest));
      }
      return cond;
    }
    op = TXT_OP_REV[body[1]] || "contains";
    cond = { filterType: "text", type: op };
    if (op !== "blank" && op !== "notBlank") cond.filter = dec(rest);
    return cond;
  }

  function encCond(c) {
    if (c.operator && c.conditions) { // combined AND/OR
      return "k" + (c.operator === "OR" ? "o" : "a") + c.conditions.map(encSimpleCond).join("|");
    }
    if (c.filterType === "set") {
      var vals = (c.values || []).map(function (v) { return v === null ? "*" : enc(v); });
      return "s" + vals.join(",");
    }
    return encSimpleCond(c);
  }

  function decCond(body) {
    if (!body) return null;
    var kind = body[0];
    if (kind === "s") {
      var rest = body.slice(1);
      var vals = rest === "" ? [] : rest.split(",").map(function (t) { return t === "*" ? null : dec(t); });
      return { filterType: "set", values: vals };
    }
    if (kind === "k") {
      var op = body[1] === "o" ? "OR" : "AND";
      var subs = body.slice(2).split("|").map(decSimpleCond);
      return { filterType: subs[0] ? subs[0].filterType : "text", operator: op, conditions: subs };
    }
    return decSimpleCond(body);
  }

  function encFilters(model) {
    if (!model) return "";
    var keys = Object.keys(model);
    if (!keys.length) return "";
    return keys.map(function (f) { return enc(f) + "~" + encCond(model[f]); }).join(";");
  }

  function decFilters(str) {
    if (!str) return null;
    var model = {};
    str.split(";").forEach(function (entry) {
      var i = entry.indexOf("~");
      if (i < 0) return;
      var cond = decCond(entry.slice(i + 1));
      if (cond) model[dec(entry.slice(0, i))] = cond;
    });
    return Object.keys(model).length ? model : null;
  }

  function encThresholds(obj) {
    var keys = Object.keys(obj || {});
    if (!keys.length) return "";
    return keys.map(function (f) {
      var t = obj[f] || {};
      return enc(f) + "~" + (t.min != null ? enc(t.min) : "") + "," + (t.max != null ? enc(t.max) : "");
    }).join(";");
  }

  function decThresholds(str) {
    var obj = {};
    if (!str) return obj;
    str.split(";").forEach(function (e) {
      var i = e.indexOf("~");
      if (i < 0) return;
      var rest = e.slice(i + 1), ci = rest.indexOf(",");
      var mn = ci < 0 ? rest : rest.slice(0, ci);
      var mx = ci < 0 ? "" : rest.slice(ci + 1);
      var t = {};
      if (mn !== "") t.min = parseFloat(dec(mn));
      if (mx !== "") t.max = parseFloat(dec(mx));
      if (t.min != null || t.max != null) obj[dec(e.slice(0, i))] = t;
    });
    return obj;
  }

  function parseHash() {
    var h = window.location.hash;
    if (h && h[0] === "#") h = h.slice(1);
    var out = {};
    if (!h) return out;
    h.split("&").forEach(function (p) {
      var i = p.indexOf("=");
      if (i > 0) out[p.slice(0, i)] = p.slice(i + 1);
    });
    return out;
  }

  // Backward-compat: decode a pre-fragment `?filters=<base64>` link value.
  function decodeLegacyFilters() {
    var b64 = new URL(window.location).searchParams.get("filters");
    if (!b64) return null;
    try { return JSON.parse(decodeURIComponent(escape(atob(b64)))); } catch (_) { return null; }
  }

  // Rebuild the whole fragment from {filters, thresholds}; strip the legacy query
  // params (`?filters`/`?cols`) so an old link silently upgrades to the `#` form.
  function writeHash(state) {
    state = state || {};
    var parts = [];
    var f = encFilters(state.filters);
    if (f) parts.push("f=" + f);
    if (state.thresholds) {
      var t = encThresholds(state.thresholds);
      if (t) parts.push("t=" + t);
    }
    var url = new URL(window.location);
    url.searchParams.delete("filters");
    url.searchParams.delete("cols");
    url.hash = parts.join("&");
    history.replaceState(null, "", url.toString());
  }

  window.UrlState = {
    enc: enc, dec: dec,
    encFilters: encFilters, decFilters: decFilters,
    encThresholds: encThresholds, decThresholds: decThresholds,
    parseHash: parseHash, decodeLegacyFilters: decodeLegacyFilters, writeHash: writeHash,
  };
})();

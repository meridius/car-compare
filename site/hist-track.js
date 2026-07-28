// Distribution track for numeric range controls (index + reference pages).
//
// One <canvas> per track draws the bars, the count gridlines, the hovered-bin
// marker and the out-of-range scrim; the Y labels are DOM spans in a left gutter
// so they align like the rest of the UI. The two native <input type=range> thumbs
// are positioned by the caller over the same inner box.
//
// Why canvas and not DOM bars: with `flex: 1` + a 1px gap the browser spreads
// fractional pixels, so bars come out 4px/5px/4px. Here the bar width is an
// integer decided up front, every gap is exactly GAP, and the leftover pixels
// become equal padding at the two EDGES — neither bars nor gaps vary. It also
// means one node per track instead of ~50, and hover is arithmetic, not hit-test.
//
// The caller owns the data and the colours; this module only bins and paints:
//   HistTrack.create(hostEl, {
//     min, max, step, dec, unit, noGroup,      // column domain + formatting
//     greenHigh,                               // higher-is-better (colour flip)
//     allValues:      fn -> number[],          // every row in the grid
//     filteredValues: fn -> number[],          // rows passing the other filters
//     colourAt:       fn(u 0..1) -> "r,g,b",   // heat colour at a global position
//     cssColour:      fn(name) -> "r,g,b",     // theme token → rgb triplet
//     compact:        bool,                    // short track, no axes (drawer)
//     onFrame:        fn(domain)               // called per animation frame
//   })
(function () {
  "use strict";

  var GUTTER = 34;          // px reserved for the Y labels
  var GAP = 1;              // px between bars
  var MIN_BAR = 3;
  var MAX_BAR = 9;
  var MIN_BINS = 8;
  var ANIM_MS = 170;        // mode/zoom switches morph instead of jumping

  function reduceMotion() {
    return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  // ── binning ───────────────────────────────────────────────────────────────
  // Bar width is an integer, so the bin count follows the available width; a
  // coarse column (Rok výroby has 12 distinct values) is capped to one bin per
  // value, with the bars widened to fill the track instead of combing it.
  function layout(innerW, maxBins) {
    // A coarse column gets one bin per value; the bars widen to fill the track.
    if (maxBins && maxBins < Math.floor((innerW + GAP) / (MIN_BAR + GAP))) {
      var wide = Math.max(MIN_BAR, Math.floor((innerW - (maxBins - 1) * GAP) / maxBins));
      return { bar: wide, bins: maxBins };
    }
    // Otherwise take the integer bar width that wastes the fewest edge pixels.
    var best = null;
    for (var bar = MAX_BAR; bar >= MIN_BAR; bar--) {
      var bins = Math.floor((innerW + GAP) / (bar + GAP));
      if (bins < MIN_BINS) continue;
      if (maxBins && bins > maxBins) continue;
      var slack = innerW - (bins * (bar + GAP) - GAP);
      if (!best || slack < best.slack) best = { bar: bar, bins: bins, slack: slack };
      if (slack === 0) break;
    }
    if (best) return { bar: best.bar, bins: best.bins };
    var fallbackBins = Math.max(2, Math.min(maxBins || MIN_BINS, Math.floor(innerW / (MIN_BAR + GAP))));
    return { bar: Math.max(MIN_BAR, Math.floor((innerW - (fallbackBins - 1) * GAP) / fallbackBins)), bins: fallbackBins };
  }

  function histogram(values, min, max, bins) {
    var counts = new Array(bins), i;
    for (i = 0; i < bins; i++) counts[i] = 0;
    if (!values || max <= min) return { counts: counts, peak: 0, total: 0 };
    var span = max - min, total = 0, n = values.length;
    for (i = 0; i < n; i++) {
      var v = values[i];
      if (v == null || !isFinite(v)) continue;
      var b = Math.floor((v - min) / span * bins);
      if (b < 0 || b > bins) continue;          // outside a zoomed axis
      if (b === bins) b = bins - 1;             // the max value belongs to the last bin
      counts[b]++; total++;
    }
    var peak = 0;
    for (i = 0; i < bins; i++) if (counts[i] > peak) peak = counts[i];
    return { counts: counts, peak: peak, total: total };
  }

  // Three round gridline counts, all ≤ peak — a line above the tallest bar reads
  // as a broken axis. Bars are sqrt-scaled, so the targets are picked in HEIGHT
  // space (0.25 / 0.6 / 1 of the track) and converted back to counts.
  function niceTicks(peak) {
    if (!peak || peak < 1) return [];
    var out = [], seen = {};
    [0.25, 0.6, 1].forEach(function (h) {
      // A count is a whole number of cars: a "0,25" gridline (or two both printing
      // "0") is nonsense on a low-peak track.
      var v = Math.round(niceRound(peak * h * h));
      if (v >= 1 && v <= peak && !seen[v]) { seen[v] = 1; out.push(v); }
    });
    return out.sort(function (a, b) { return a - b; });
  }

  function niceRound(v) {
    if (v <= 0) return 0;
    var mag = Math.pow(10, Math.floor(Math.log10(v)));
    var f = v / mag, steps = [1, 2, 2.5, 5, 10], pick = 1;
    for (var i = 0; i < steps.length; i++) if (steps[i] <= f) pick = steps[i];
    return pick * mag;
  }

  function fmtInt(v, noGroup) {
    return Number(v).toLocaleString("cs-CZ", { maximumFractionDigits: 0, useGrouping: !noGroup });
  }

  // One unit for the whole count axis: mixing "10 tis." with "1 000" reads as two
  // different scales.
  function tickFormatter(ticks) {
    var top = ticks.length ? ticks[ticks.length - 1] : 0;
    if (top >= 1e6) {
      return function (v) { return (v / 1e6).toLocaleString("cs-CZ", { maximumFractionDigits: 2 }) + " mil."; };
    }
    if (top >= 1e4) {
      return function (v) {
        return (v / 1e3).toLocaleString("cs-CZ", { maximumFractionDigits: v % 1000 ? 1 : 0 }) + " tis.";
      };
    }
    return function (v) { return fmtInt(v); };
  }

  // Value-axis label: compact for big numbers, honest for years/decimals.
  function fmtValue(v, dec, noGroup) {
    if (noGroup) return fmtInt(v, true);
    var a = Math.abs(v);
    if (a >= 1e6) return (v / 1e6).toLocaleString("cs-CZ", { maximumFractionDigits: 1 }) + " mil.";
    if (a >= 1e4) return fmtInt(Math.round(v / 1e3)) + " tis.";
    return Number(v).toLocaleString("cs-CZ", { maximumFractionDigits: dec || 0 });
  }

  // ── the track ─────────────────────────────────────────────────────────────
  function Track(host, opts) {
    this.host = host;
    this.o = opts;
    this.mode = "all";      // "all" | "filter" | "both"
    this.zoom = false;      // shrink the value axis onto the filtered rows
    this.range = { lo: 0, hi: 1 };
    this.hover = null;
    this.canvas = document.createElement("canvas");
    this.canvas.className = "ht-canvas";
    host.appendChild(this.canvas);
    this.yLabels = document.createElement("div");
    this.yLabels.className = "ht-ylabels";
    host.appendChild(this.yLabels);
  }

  Track.prototype.setState = function (st, animate) {
    if (st.mode != null) this.mode = st.mode;
    if (st.zoom != null) this.zoom = !!st.zoom;
    if (st.range) this.range = st.range;
    if (this.mode === "all") this.zoom = false;
    this.render(animate);
  };

  // Data changed underneath (archive loaded, another filter moved) — drop the
  // cached frame so the next render re-bins from scratch instead of tweening
  // against stale counts.
  Track.prototype.invalidate = function () { this.drawn = null; };

  Track.prototype.destroy = function () {
    if (this.raf) cancelAnimationFrame(this.raf);
    this.raf = null;
  };

  Track.prototype.domain = function () {
    var o = this.o;
    if (!this.zoom || this.mode === "all") return { min: o.min, max: o.max };
    var vals = o.filteredValues() || [], lo = Infinity, hi = -Infinity;
    for (var i = 0; i < vals.length; i++) {
      var v = vals[i];
      if (v == null || !isFinite(v)) continue;
      if (v < lo) lo = v;
      if (v > hi) hi = v;
    }
    if (!isFinite(lo)) return { min: o.min, max: o.max };
    if (hi === lo) { lo -= (o.step || 1); hi += (o.step || 1); }
    return { min: lo, max: hi };
  };

  Track.prototype.metrics = function (dom) {
    var rect = this.host.getBoundingClientRect();
    var innerW = Math.max(40, rect.width - GUTTER);
    var maxBins = null;
    if (this.o.step) {
      var steps = Math.round((dom.max - dom.min) / this.o.step) + 1;
      if (steps <= 200) maxBins = Math.max(2, steps);
    }
    var lay = layout(innerW, maxBins);
    var barsW = lay.bins * (lay.bar + GAP) - GAP;
    var pad = Math.max(0, Math.floor((innerW - barsW) / 2));
    return {
      w: rect.width, h: rect.height || 1, innerW: innerW,
      bar: lay.bar, bins: lay.bins, barsW: barsW, x0: GUTTER + pad,
    };
  };

  Track.prototype.binX = function (m, i) { return m.x0 + i * (m.bar + GAP); };

  Track.prototype.binAt = function (m, xCss) {
    var i = Math.floor((xCss - m.x0) / (m.bar + GAP));
    return Math.max(0, Math.min(m.bins - 1, i));
  };

  // Bin the current (or a given) domain; no drawing.
  Track.prototype.compute = function (domOverride) {
    var o = this.o;
    var dom = domOverride || this.domain();
    var m = this.metrics(dom);
    var withGhost = this.mode === "both";
    var liveVals = this.mode === "all" ? o.allValues() : o.filteredValues();
    var live = histogram(liveVals, dom.min, dom.max, m.bins);
    var ghost = withGhost ? histogram(o.allValues(), dom.min, dom.max, m.bins) : null;
    // Shared scale while both layers show (the height ratio is then the share
    // that survives the filter); own scale once the context layer is gone, so a
    // narrow filter still draws a readable shape.
    var scaleGhost = ghost ? ghost.peak : live.peak;
    return {
      m: m, dom: dom, live: live, ghost: ghost,
      scaleLive: withGhost ? scaleGhost : live.peak,
      scaleGhost: scaleGhost || 1,
    };
  };

  // Morph from what is on screen to the new state.
  //  - domain changed (Lupa)      → interpolate the AXIS and re-bin per frame, so
  //                                 bars spread apart / draw together
  //  - bin count changed (resize) → short cross-fade; bin i means something else
  //                                 on the two sides, so a tween would be a lie
  //  - counts changed (mode)      → tween the bar heights
  // In every animated case the count ticks are frozen to the END state: deriving
  // them per frame made the labels flicker through different round numbers.
  Track.prototype.render = function (animate) {
    var self = this;
    var next = this.compute();
    var prev = this.drawn;
    if (this.raf) { cancelAnimationFrame(this.raf); this.raf = null; }
    if (animate && reduceMotion()) animate = false;

    if (!animate || !prev) { this.paint(next, next); return; }

    var ticks = niceTicks(next.scaleGhost);

    if (prev.dom.min !== next.dom.min || prev.dom.max !== next.dom.max) {
      var from = prev.dom, to = next.dom, t0 = null;
      var zoomStep = function (ts) {
        if (t0 === null) t0 = ts;
        var u = Math.min(1, (ts - t0) / ANIM_MS);
        var e = 1 - Math.pow(1 - u, 3);
        var dom = { min: from.min + (to.min - from.min) * e, max: from.max + (to.max - from.max) * e };
        var f = self.compute(dom);
        f.ticks = ticks;
        f.scaleGhost = prev.scaleGhost + (next.scaleGhost - prev.scaleGhost) * e;
        f.scaleLive = prev.scaleLive + (next.scaleLive - prev.scaleLive) * e;
        self.paint(f, f);
        if (self.o.onFrame) self.o.onFrame(dom);
        self.raf = u < 1 ? requestAnimationFrame(zoomStep) : null;
      };
      this.raf = requestAnimationFrame(zoomStep);
      return;
    }

    if (prev.m.bins !== next.m.bins) {
      this.canvas.style.opacity = "0.2";
      setTimeout(function () {
        self.paint(next, next);
        self.canvas.style.opacity = "1";
      }, ANIM_MS / 2);
      return;
    }

    var s0 = null;
    var heightStep = function (ts) {
      if (s0 === null) s0 = ts;
      var u = Math.min(1, (ts - s0) / ANIM_MS);
      var e = 1 - Math.pow(1 - u, 3);
      var f = mix(prev, next, e);
      f.ticks = ticks;
      self.paint(next, f);
      self.raf = u < 1 ? requestAnimationFrame(heightStep) : null;
    };
    this.raf = requestAnimationFrame(heightStep);
  };

  function lerpCounts(a, b, e) {
    var out = new Array(b.length);
    for (var i = 0; i < b.length; i++) {
      var from = a && a[i] != null ? a[i] : 0;
      out[i] = from + (b[i] - from) * e;
    }
    return out;
  }

  function mix(a, b, e) {
    return {
      m: b.m, dom: b.dom,
      live: { counts: lerpCounts(a.live.counts, b.live.counts, e) },
      ghost: b.ghost ? { counts: lerpCounts(a.ghost ? a.ghost.counts : null, b.ghost.counts, e) } : null,
      scaleLive: a.scaleLive + (b.scaleLive - a.scaleLive) * e,
      scaleGhost: a.scaleGhost + (b.scaleGhost - a.scaleGhost) * e,
    };
  }

  // `target` fixes the axis + scrim (end state); `frame` carries the heights drawn.
  Track.prototype.paint = function (target, frame) {
    var o = this.o;
    var m = target.m, dom = target.dom;
    var live = frame.live, ghost = frame.ghost;
    var scaleLive = frame.scaleLive || 1;
    var scaleGhost = frame.scaleGhost || scaleLive || 1;
    this.state = target;
    this.drawn = target;

    var dpr = window.devicePixelRatio || 1;
    this.canvas.width = Math.max(1, Math.round(m.w * dpr));
    this.canvas.height = Math.max(1, Math.round(m.h * dpr));
    var ctx = this.canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, m.w, m.h);

    var baseline = m.h - 1;
    var usable = Math.max(4, m.h - 6);

    // count gridlines + labels (the compact drawer variant has no axes)
    if (!o.compact) {
      var ticks = frame.ticks || niceTicks(scaleGhost);
      var fmtTick = tickFormatter(ticks);
      ctx.strokeStyle = "rgba(" + o.cssColour("--clr-border") + ",0.85)";
      ctx.setLineDash([2, 3]);
      ctx.lineWidth = 1;
      var i;
      for (i = 0; i < ticks.length; i++) {
        var gy = baseline - Math.min(1, Math.sqrt(ticks[i] / scaleGhost)) * usable;
        ctx.beginPath();
        ctx.moveTo(m.x0, Math.round(gy) + 0.5);
        ctx.lineTo(m.x0 + m.barsW, Math.round(gy) + 0.5);
        ctx.stroke();
      }
      ctx.setLineDash([]);
      // Reuse the label spans — recreating them every frame made the text twitch.
      while (this.yLabels.childElementCount > ticks.length) this.yLabels.removeChild(this.yLabels.lastChild);
      while (this.yLabels.childElementCount < ticks.length) this.yLabels.appendChild(document.createElement("span"));
      for (i = 0; i < ticks.length; i++) {
        var ly = baseline - Math.min(1, Math.sqrt(ticks[i] / scaleGhost)) * usable;
        var span = this.yLabels.children[i];
        var txt = fmtTick(ticks[i]);
        if (span.textContent !== txt) span.textContent = txt;
        span.style.top = Math.max(0, Math.min(m.h - 9, ly - 4)) + "px";
      }
    } else if (this.yLabels.childElementCount) {
      this.yLabels.textContent = "";
    }

    // bars
    var globalSpan = o.max - o.min || 1;
    for (var b = 0; b < m.bins; b++) {
      var x = this.binX(m, b);
      var u = m.bins > 1 ? b / (m.bins - 1) : 0;
      // Colour comes from the value's GLOBAL position, never the bin index — a
      // zoomed axis must not repaint globally-cheap cars red.
      var gu = (dom.min + (dom.max - dom.min) * u - o.min) / globalSpan;
      gu = Math.max(0, Math.min(1, gu));
      var rgb = o.colourAt(o.greenHigh ? 1 - gu : gu);
      if (ghost && ghost.counts[b] > 0) {
        var gh = Math.sqrt(ghost.counts[b] / scaleGhost) * usable;
        ctx.fillStyle = "rgba(" + rgb + "," + (o.isDark() ? 0.3 : 0.26) + ")";
        ctx.fillRect(x, baseline - gh, m.bar, gh);
      }
      if (live.counts[b] > 0) {
        var lh = Math.sqrt(live.counts[b] / scaleLive) * usable;
        ctx.fillStyle = "rgba(" + rgb + "," + (this.hover === b ? 1 : 0.9) + ")";
        ctx.fillRect(x, baseline - lh, m.bar, lh);
      }
    }

    // hovered bin: quiet backdrop + a marker at the baseline, never a tooltip
    // over the bars (the readout lives in the popup header)
    if (this.hover != null && this.hover < m.bins) {
      var hx = this.binX(m, this.hover);
      ctx.fillStyle = "rgba(" + o.cssColour("--clr-text") + ",0.035)";
      ctx.fillRect(hx - 1, 0, m.bar + 2, m.h - 3);
      ctx.fillStyle = "rgba(" + o.cssColour("--clr-accent") + ",0.55)";
      ctx.fillRect(hx - 1, m.h - 3, m.bar + 2, 2);
    }

    // what the current range excludes
    var lo = this.range.lo == null ? 0 : this.range.lo;
    var hi = this.range.hi == null ? 1 : this.range.hi;
    ctx.fillStyle = "rgba(" + o.cssColour("--clr-surface") + ",0.74)";
    if (lo > 0) ctx.fillRect(m.x0, 0, lo * m.barsW, m.h);
    if (hi < 1) ctx.fillRect(m.x0 + hi * m.barsW, 0, (1 - hi) * m.barsW, m.h);

    ctx.fillStyle = "rgba(" + o.cssColour("--clr-border") + ",1)";
    ctx.fillRect(m.x0, m.h - 1, m.barsW, 1);
  };

  // Repaint the frame already on screen (hover in/out, scrim move). Hover fires on
  // every mousemove, and a full render() would re-bin 150k values each time.
  Track.prototype.repaint = function () {
    if (this.drawn) this.paint(this.drawn, this.drawn);
    else this.render(false);
  };

  Track.prototype.binInfo = function (i) {
    var st = this.state;
    if (!st) return null;
    var w = (st.dom.max - st.dom.min) / st.m.bins;
    return {
      lo: st.dom.min + i * w,
      hi: st.dom.min + (i + 1) * w,
      count: Math.round(st.live.counts[i] || 0),
      total: Math.round(st.live.total || 0),
    };
  };

  window.HistTrack = {
    GUTTER: GUTTER,
    ANIM_MS: ANIM_MS,
    create: function (host, opts) { return new Track(host, opts); },
    fmtValue: fmtValue,
    fmtInt: fmtInt,
    niceTicks: niceTicks,
    histogram: histogram,
    layout: layout,
  };
})();

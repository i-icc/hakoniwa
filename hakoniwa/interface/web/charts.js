// Line charts and the node-link world map, in plain SVG.
// Marks: 2px lines, hairline grid, end dots with a surface ring, legend for 2+ series,
// crosshair + tooltip on hover, and a table view behind a toggle.
import { compact, fmt, t } from "/i18n.js";

const NS = "http://www.w3.org/2000/svg";
export const SERIES = [1, 2, 3, 4, 5, 6, 7, 8].map((i) => `var(--series-${i})`);

export function el(tag, attrs = {}, ...kids) {
  const svg = ["svg", "g", "path", "line", "circle", "text", "rect", "title"].includes(tag);
  const n = svg ? document.createElementNS(NS, tag) : document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") n.setAttribute("class", v);
    else if (k === "html") n.innerHTML = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (k === "style" && typeof v === "object") Object.assign(n.style, v);
    else n.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false) n.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  return n;
}

const tip = () => document.getElementById("tooltip");
export function showTip(html, x, y) {
  const n = tip();
  n.innerHTML = html;
  n.hidden = false;
  const w = n.offsetWidth, h = n.offsetHeight;
  n.style.left = Math.min(window.innerWidth - w - 8, x + 14) + "px";
  n.style.top = Math.max(8, Math.min(window.innerHeight - h - 8, y - h - 10)) + "px";
}
export function hideTip() { tip().hidden = true; }

function niceTicks(lo, hi, n = 4) {
  if (lo === hi) { hi = lo + 1; }
  const span = hi - lo, raw = span / n, mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => span / s <= n + 0.5) || raw;
  const a = Math.floor(lo / step) * step, out = [];
  for (let v = a; v <= hi + step * 0.5; v += step) out.push(+v.toFixed(10));
  return out;
}

// series: [{name, color, points: [[tick, value], ...]}]
export function lineChart(host, { series, format, unit, cursor, marks = [], xLabel, clockOf }) {
  host.replaceChildren();
  const W = Math.max(280, host.clientWidth || 380), H = 170, m = { l: 46, r: 14, t: 8, b: 22 };
  const all = series.flatMap((s) => s.points);
  if (!all.length) { host.append(el("div", { class: "muted small" }, "–")); return; }
  let x0 = Math.min(...all.map((p) => p[0])), x1 = Math.max(...all.map((p) => p[0]));
  if (x1 === x0) x1 = x0 + 1;
  let lo = Math.min(...all.map((p) => p[1])), hi = Math.max(...all.map((p) => p[1]));
  if (lo > 0 && lo < hi * 0.6) lo = 0;                 // start at zero unless that would flatten the line
  if (format === "pct" && hi <= 100 && hi > 60) hi = 100;
  const ticks = niceTicks(lo, hi);
  lo = Math.min(lo, ticks[0]); hi = Math.max(hi, ticks[ticks.length - 1]);
  const X = (v) => m.l + (v - x0) / (x1 - x0) * (W - m.l - m.r);
  const Y = (v) => H - m.b - (v - lo) / (hi - lo || 1) * (H - m.t - m.b);
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, height: H, role: "img" });
  const axis = el("g", { class: "axis" });
  for (const v of ticks) {
    axis.append(el("line", { x1: m.l, x2: W - m.r, y1: Y(v), y2: Y(v), stroke: v === 0 ? "var(--axis)" : "var(--grid)", "stroke-width": 1 }));
    axis.append(el("text", { x: m.l - 6, y: Y(v) + 3.5, "text-anchor": "end" }, format === "pct" ? v + "%" : compact(v)));
  }
  const xt = niceTicks(x0, x1, 5).filter((v) => v >= x0 && v <= x1 && Number.isInteger(v));
  for (const v of xt) axis.append(el("text", { x: X(v), y: H - 6, "text-anchor": "middle" }, v));
  svg.append(axis);
  for (const mk of marks) {
    if (mk.tick < x0 || mk.tick > x1) continue;
    svg.append(el("line", { x1: X(mk.tick), x2: X(mk.tick), y1: m.t, y2: H - m.b, stroke: "var(--series-7)", "stroke-width": 1, opacity: 0.55 }, el("title", {}, mk.label)));
    svg.append(el("path", { d: `M${X(mk.tick) - 4},${m.t} h8 l-4,6 z`, fill: "var(--series-7)" }, el("title", {}, mk.label)));
  }
  series.forEach((s) => {
    if (!s.points.length) return;
    const d = s.points.map((p, i) => (i ? "L" : "M") + X(p[0]).toFixed(1) + "," + Y(p[1]).toFixed(1)).join("");
    svg.append(el("path", { d, fill: "none", stroke: s.color, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));
    const last = s.points[s.points.length - 1];
    svg.append(el("circle", { cx: X(last[0]), cy: Y(last[1]), r: 4, fill: s.color, stroke: "var(--surface-1)", "stroke-width": 2 }));
  });
  const cross = el("line", { y1: m.t, y2: H - m.b, stroke: "var(--axis)", "stroke-width": 1, visibility: "hidden" });
  const cur = el("line", { y1: m.t, y2: H - m.b, stroke: "var(--text-secondary)", "stroke-width": 1, opacity: 0.5, visibility: "hidden" });
  if (cursor !== null && cursor !== undefined && cursor >= x0 && cursor <= x1) { cur.setAttribute("x1", X(cursor)); cur.setAttribute("x2", X(cursor)); cur.setAttribute("visibility", "visible"); }
  svg.append(cur, cross);
  const hit = el("rect", { x: m.l, y: 0, width: W - m.l - m.r, height: H, fill: "transparent" });
  hit.addEventListener("mousemove", (e) => {
    const r = svg.getBoundingClientRect();
    const tx = Math.round(x0 + ((e.clientX - r.left) / r.width * W - m.l) / (W - m.l - m.r) * (x1 - x0));
    const tk = Math.max(x0, Math.min(x1, tx));
    cross.setAttribute("x1", X(tk)); cross.setAttribute("x2", X(tk)); cross.setAttribute("visibility", "visible");
    const rows = series.map((s) => {
      const p = s.points.find((q) => q[0] === tk);
      return p ? `<div class="r"><span><i style="background:${s.color}"></i>${esc(s.name)}</span><b>${fmt(p[1], format, unit)}</b></div>` : "";
    }).join("");
    showTip(`<div class="t">${esc(clockOf ? clockOf(tk) : (xLabel || t("tick")) + " " + tk)}</div>${rows}`, e.clientX, e.clientY);
  });
  hit.addEventListener("mouseleave", () => { cross.setAttribute("visibility", "hidden"); hideTip(); });
  svg.append(hit);
  host.append(svg);
}

export function legend(series) {
  return el("div", { class: "legend" }, series.map((s) => el("span", {}, el("i", { style: { background: s.color } }), s.name)));
}

export function dataTable(series, format, unit) {
  const ticks = [...new Set(series.flatMap((s) => s.points.map((p) => p[0])))].sort((a, b) => a - b);
  const step = Math.max(1, Math.ceil(ticks.length / 40));
  const rows = ticks.filter((_, i) => i % step === 0 || i === ticks.length - 1);
  const maps = series.map((s) => new Map(s.points));
  return el("div", { class: "panel", style: { maxHeight: "190px" } }, el("table", {},
    el("tr", {}, el("th", {}, t("tick")), series.map((s) => el("th", { class: "num" }, s.name))),
    rows.map((tk) => el("tr", {}, el("td", {}, tk), maps.map((mp) => el("td", { class: "num" }, mp.has(tk) ? fmt(mp.get(tk), format, unit) : ""))))));
}

export const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// ---- world map: nodes sized and shaded by value, links by flow, speech bubbles on top ----
const STATUS = { warn: { color: "var(--warning)", glyph: "▲" }, crit: { color: "var(--critical)", glyph: "!" } };

export function worldMap(host, view, { label, bubbles = [], onNode }) {
  host.replaceChildren();
  const W = 1000, H = 580;
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img" });
  const pos = new Map();
  const PX = (x) => 60 + x / 100 * (W - 120), PY = (y) => 50 + y / 100 * (H - 110);
  for (const n of view.nodes || []) pos.set(n.id, [PX(n.x), PY(n.y)]);
  for (const k of view.links || []) {
    const a = pos.get(k.a), b = pos.get(k.b);
    if (!a || !b) continue;
    const r = Math.max(0, Math.min(1, (k.value || 0) / (k.max || 1)));
    svg.append(el("line", { x1: a[0], y1: a[1], x2: b[0], y2: b[1], stroke: r > 0 ? "var(--seq-3)" : "var(--grid)", "stroke-width": 1.5 + r * 9, "stroke-linecap": "round", opacity: r > 0 ? 0.75 : 1 }));
  }
  for (const n of view.nodes || []) {
    const [x, y] = pos.get(n.id);
    const r = Math.max(0, Math.min(1, (n.value || 0) / (n.max || 1)));
    const rad = 13 + Math.sqrt(r) * 26;
    const g = el("g", { style: { cursor: onNode ? "pointer" : "default" } });
    g.append(el("circle", { cx: x, cy: y, r: rad, fill: `var(--seq-${1 + Math.min(5, Math.floor(r * 6))})`, stroke: "var(--surface-1)", "stroke-width": 2 }));
    const st = STATUS[n.status];
    if (st) {
      g.append(el("circle", { class: "ring", cx: x, cy: y, r: rad + 4, stroke: st.color }));
      g.append(el("circle", { cx: x + rad * 0.75, cy: y - rad * 0.75, r: 9, fill: st.color, stroke: "var(--surface-1)", "stroke-width": 2 }));
      g.append(el("text", { x: x + rad * 0.75, y: y - rad * 0.75 + 4, "text-anchor": "middle", "font-size": 11, "font-weight": 700, fill: "#0b0b0b" }, st.glyph));
    }
    g.append(el("text", { class: "nlabel", x, y: y + rad + 15, "text-anchor": "middle", "font-size": 15 }, label(n.label)));
    if (n.sub) {
      // long captions are broken at " / " or "、" so neighbours do not collide
      const parts = String(label(n.sub)).split(/\s*\/\s*|、\s*|,\s+/).slice(0, 4);
      parts.forEach((part, i) => g.append(el("text", { class: "nsub", x, y: y + rad + 31 + i * 15, "text-anchor": "middle", "font-size": 12.5 }, part)));
    }
    g.append(el("title", {}, `${label(n.label)}: ${n.value}`));
    if (onNode) g.addEventListener("click", () => onNode(n));
    svg.append(g);
  }
  host.append(svg);
  for (const b of bubbles) {
    const p = pos.get(b.node);
    if (!p) continue;
    host.append(el("div", { class: "bubble", style: { left: (p[0] / W * 100) + "%", top: ((p[1] - 34) / H * 100) + "%" } }, el("b", {}, b.who), b.text));
  }
}

// ---- world lines: every run of a world as a line over time; forks branch off where they split ----
const LANE = ["#6930c3", "#5390d9", "#48bfe3", "#5e60ce", "#4ea8de", "#56cfe1"];

// The automaton as a state diagram, measured from the run: one circle per state (its size is how many residents are
// in it now), one arrow per move that happened (its width is how many made it so far).
export function stateDiagram(host, { states, colors, now, flows, label }) {
  host.replaceChildren();
  const W = 1000, H = 420, n = states.length, cx = W / 2, cy = H / 2, rx = W * 0.36, ry = H * 0.33;
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img" });
  const at = states.map((_, i) => n === 1 ? [cx, cy] : [cx + rx * Math.cos(-Math.PI / 2 + 2 * Math.PI * i / n), cy + ry * Math.sin(-Math.PI / 2 + 2 * Math.PI * i / n)]);
  const total = now.reduce((a, b) => a + b, 0) || 1, most = Math.max(1, ...flows.map((f) => f[2]));
  const rad = (i) => 16 + 46 * Math.sqrt(now[i] / total);
  for (const [i, j, c] of [...flows].sort((a, b) => a[2] - b[2])) {
    const [x1, y1] = at[i], [x2, y2] = at[j], dx = x2 - x1, dy = y2 - y1, len = Math.hypot(dx, dy) || 1;
    const nx = -dy / len, ny = dx / len, bend = 34;                     // each direction bends its own way, so A->B and B->A do not overlap
    const sx = x1 + dx / len * rad(i), sy = y1 + dy / len * rad(i), ex = x2 - dx / len * (rad(j) + 9), ey = y2 - dy / len * (rad(j) + 9);
    const mx = (sx + ex) / 2 + nx * bend, my = (sy + ey) / 2 + ny * bend, w = 1.2 + 9 * c / most;
    svg.append(el("path", { d: `M${sx},${sy} Q${mx},${my} ${ex},${ey}`, fill: "none", stroke: colors[i], "stroke-width": w, "stroke-linecap": "round", opacity: 0.55 }));
    const ang = Math.atan2(ey - my, ex - mx), ah = 7 + w;
    svg.append(el("path", { d: `M${ex + Math.cos(ang) * ah},${ey + Math.sin(ang) * ah} L${ex + Math.cos(ang + 2.5) * ah},${ey + Math.sin(ang + 2.5) * ah} L${ex + Math.cos(ang - 2.5) * ah},${ey + Math.sin(ang - 2.5) * ah} Z`, fill: colors[i], opacity: 0.8 }));
    const tx = (sx + 2 * mx + ex) / 4, ty = (sy + 2 * my + ey) / 4;
    svg.append(el("text", { x: tx, y: ty + 4, "text-anchor": "middle", "font-size": 13, fill: "var(--text-secondary)", stroke: "var(--surface-1)", "stroke-width": 4, "paint-order": "stroke" }, String(c)));
  }
  states.forEach((st, i) => {
    const [x, y] = at[i], r = rad(i);
    svg.append(el("circle", { cx: x, cy: y, r, fill: colors[i], stroke: "var(--surface-1)", "stroke-width": 2 }));
    svg.append(el("text", { x, y: y + r + 17, "text-anchor": "middle", "font-size": 15, "font-weight": 600, fill: "var(--text-primary)" }, label(st)));
    svg.append(el("text", { x, y: y + r + 33, "text-anchor": "middle", "font-size": 13, fill: "var(--text-secondary)" }, String(now[i])));
  });
  host.append(svg);
}

// The cast as a board: one square per resident, coloured by what they last decided. Squares are kept between
// draws, so a change of mind shows as a change of colour when time moves.
export function peopleGrid(host, { cells, onPick, tipOf }) {
  const W = 1000, H = 580, n = cells.length;
  const cols = Math.ceil(Math.sqrt(n * W / H)), rows = Math.ceil(n / cols);
  const size = Math.min(W / cols, H / rows, 46), gap = Math.max(2, size * 0.14), side = size - gap;
  const ox = (W - cols * size) / 2, oy = (H - rows * size) / 2;
  let kept = host.__board;
  if (!kept || kept.n !== n || !host.contains(kept.svg)) {
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img" });
    const rects = [], dots = [];
    for (let i = 0; i < n; i++) {
      const x = ox + (i % cols) * size + gap / 2, y = oy + Math.floor(i / cols) * size + gap / 2;
      const r = el("rect", { class: "cell", x, y, width: side, height: side, rx: Math.min(5, side * 0.2) });
      const d = el("circle", { cx: x + side / 2, cy: y + side / 2, r: Math.max(1.5, side * 0.14), fill: "var(--surface-1)", "pointer-events": "none" });
      r.addEventListener("mousemove", (e) => showTip(host.__board.tipOf(i), e.clientX, e.clientY));
      r.addEventListener("mouseleave", hideTip);
      r.addEventListener("click", () => host.__board.onPick(i));
      svg.append(r, d); rects.push(r); dots.push(d);
    }
    host.replaceChildren(svg);
    kept = host.__board = { n, svg, rects, dots };
  }
  kept.tipOf = tipOf; kept.onPick = onPick;
  cells.forEach((c, i) => {
    const r = kept.rects[i];
    r.setAttribute("fill", c.color || "var(--surface-1)");
    r.setAttribute("stroke", c.fresh ? "var(--text-secondary)" : (c.color ? "none" : "var(--axis)"));
    r.setAttribute("stroke-width", c.fresh ? 1.6 : 1);
    kept.dots[i].setAttribute("visibility", c.meant ? "visible" : "hidden");
  });
}

export function worldLines(host, { runs, current, label, onOpen, unit }) {
  host.replaceChildren();
  if (!runs.length) return;
  const byParent = new Map();
  for (const r of runs) {
    const key = runs.some((x) => x.id === r.parent_run_id) ? r.parent_run_id : 0;
    if (!byParent.has(key)) byParent.set(key, []);
    byParent.get(key).push(r);
  }
  const order = [];
  const walk = (key) => { for (const r of (byParent.get(key) || []).sort((a, b) => (a.fork_tick ?? 0) - (b.fork_tick ?? 0) || a.id - b.id)) { order.push(r); walk(r.id); } };
  walk(0);
  const lane = new Map(order.map((r, i) => [r.id, i]));
  const W = Math.max(520, host.clientWidth || 800), rowH = 38, top = 26, padL = 14, padR = Math.min(300, W * 0.36);
  const H = top + order.length * rowH + 22;
  const maxT = Math.max(1, ...order.map((r) => Math.max(r.total || 0, r.tick || 0)));
  const X = (t) => padL + t / maxT * (W - padL - padR), Y = (i) => top + i * rowH + 6;
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, height: H, class: "lines", role: "img" });
  for (const v of [0, Math.round(maxT / 2), maxT]) {
    svg.append(el("line", { x1: X(v), x2: X(v), y1: top - 12, y2: H - 18, stroke: "var(--grid)", "stroke-width": 1 }));
    svg.append(el("text", { x: X(v), y: H - 5, "text-anchor": v === 0 ? "start" : v === maxT ? "end" : "middle", class: "lines-axis" }, v === maxT && unit ? `${v} ${unit}` : v));
  }
  for (const r of order) {
    const i = lane.get(r.id), y = Y(i), col = LANE[i % LANE.length], me = r.id === current;
    const start = r.parent_run_id && lane.has(r.parent_run_id) ? (r.fork_tick ?? 0) : 0;
    const g = el("g", { class: "lane" + (me ? " me" : ""), style: { cursor: "pointer" } });
    let x0 = X(start);
    if (start > 0 || (r.parent_run_id && lane.has(r.parent_run_id))) {
      const yp = Y(lane.get(r.parent_run_id));
      x0 = X(start) + 18;
      g.append(el("path", { d: `M${X(start)},${yp} C${X(start)},${y} ${X(start) + 4},${y} ${x0},${y}`, fill: "none", stroke: col, "stroke-width": me ? 3 : 2, "stroke-linecap": "round" }));
      svg.append(el("circle", { cx: X(start), cy: yp, r: 4, fill: "var(--surface-1)", stroke: col, "stroke-width": 2 }));
      if (r.diff && r.diff.length) g.append(el("text", { x: x0 + 4, y: y - 7, class: "lines-event" }, r.diff.join(" · ").slice(0, 70)));
    } else {
      g.append(el("circle", { cx: x0, cy: y, r: 4, fill: col, stroke: "var(--surface-1)", "stroke-width": 2 }));
    }
    const planned = X(Math.max(r.total || 0, r.tick || 0)), done = Math.max(x0, X(r.tick || 0));
    g.append(el("line", { x1: x0, x2: planned, y1: y, y2: y, stroke: col, "stroke-width": 2, opacity: 0.25, "stroke-linecap": "round" }));
    g.append(el("line", { x1: x0, x2: done, y1: y, y2: y, stroke: col, "stroke-width": me ? 4 : 2.5, "stroke-linecap": "round" }));
    g.append(el("circle", { cx: done, cy: y, r: me ? 6 : 4.5, fill: col, stroke: "var(--surface-1)", "stroke-width": 2 }));
    g.append(el("text", { x: planned + 12, y: y + 1, class: "lines-name" + (me ? " me" : "") }, r.name.length > 34 ? r.name.slice(0, 33) + "…" : r.name));
    if (r.result) g.append(el("text", { x: planned + 12, y: y + 14, class: "lines-result" }, r.result));
    g.append(el("rect", { x: 0, y: y - rowH / 2, width: W, height: rowH, fill: "transparent" }));
    g.addEventListener("click", () => onOpen(r));
    g.addEventListener("mousemove", (e) => showTip(`<div><b>${esc(r.name)}</b></div><div class="t">${esc(r.statusText || "")} · ${r.tick} / ${r.total}</div>${(r.diff || []).map((d) => `<div>${esc(d)}</div>`).join("")}${r.result ? `<div class="t">${esc(r.result)}</div>` : ""}`, e.clientX, e.clientY));
    g.addEventListener("mouseleave", hideTip);
    svg.append(g);
  }
  host.append(svg);
}

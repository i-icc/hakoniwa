// Hakoniwa viewer. Plain ES modules, no build step.
import { L, fmt, lang, setLang, t, usd } from "/i18n.js";
import { SERIES, dataTable, el, esc, legend, lineChart, worldLines, worldMap } from "/charts.js";

const api = {
  async call(method, url, body) {
    const r = await fetch(url, { method, headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || data.detail || `HTTP ${r.status}`);
    return data;
  },
  get: (u) => api.call("GET", u), post: (u, b) => api.call("POST", u, b || {}), del: (u) => api.call("DELETE", u),
};

const app = document.getElementById("app");
const SQLITE_MEDIA = "application/vnd.sqlite3";
const DATA_CHANGE = "hakoniwa.data-restored";
let info = null;
let cleanup = [];
const later = (fn, ms) => { const id = setTimeout(fn, ms); cleanup.push(() => clearTimeout(id)); return id; };

// While AI is creating a world or drafting a scenario, leaving the page asks first.
let busy = 0;
let lastHash = location.hash;
const leaveDialog = () => new Promise((resolve) => {
  const dlg = el("dialog", { class: "dlg" });
  let answer = false;
  dlg.append(el("div", { class: "stack" }, el("h2", {}, t("leaveTitle")), el("p", {}, t("leaveBody")),
    el("div", { class: "row", style: { justifyContent: "flex-end" } }, el("button", { onclick: () => { answer = true; dlg.close(); } }, t("leaveGo")),
      el("button", { class: "primary", onclick: () => dlg.close() }, t("leaveStay")))));
  dlg.addEventListener("close", () => { dlg.remove(); resolve(answer); });
  document.body.append(dlg); dlg.showModal();
});
window.addEventListener("beforeunload", (e) => { if (busy) { e.preventDefault(); e.returnValue = ""; } });

function crumbs(items) {
  const n = document.getElementById("crumbs");
  n.replaceChildren(...items.flatMap((it) => [el("span", {}, "/"), it.href ? el("a", { href: it.href }, it.text) : el("span", {}, it.text)]));
}
function chrome() {
  document.getElementById("lang-en").className = lang === "en" ? "on" : "";
  document.getElementById("lang-ja").className = lang === "ja" ? "on" : "";
  const chip = document.getElementById("ai-chip");
  if (!info) return;
  chip.className = "chip " + (info.llm_live ? "live" : "warn");
  chip.replaceChildren(el("span", { class: "dot" }), info.llm_live ? info.models.agent : t("noAI"), el("span", { class: "caret" }, "▾"));
  chip.onclick = modelDialog;
  chip.title = (info.llm_live ? `designer ${info.models.designer} (${info.efforts.designer}) / residents ${info.models.agent} (${info.efforts.agent}) / report ${info.models.report} / ` : "") + `${t("sandbox")}: ${info.sandbox_backend}`;
}
async function modelDialog() {
  const data = await api.get("/api/models");
  const dlg = el("dialog", { class: "dlg wide-dlg" });
  const picks = {};
  const row = (role, label, help) => {
    const cur = data.roles[role];
    const names = data.available.includes(cur.model) ? data.available : [cur.model, ...data.available];
    const price = (m) => data.prices[m] ? `  ·  $${data.prices[m].in} / $${data.prices[m].out}` : "";
    const model = el("select", {}, names.map((m) => el("option", { value: m, selected: m === cur.model }, m + price(m))));
    const effort = el("select", {}, data.efforts.map((e) => el("option", { value: e, selected: e === cur.effort }, e)));
    picks[role] = { model, effort };
    return el("div", { class: "model-row" }, el("div", {}, el("div", { class: "name" }, label), el("div", { class: "muted small" }, help)), model, effort);
  };
  const save = async (roles) => {
    if (roles === null) await api.del("/api/models");
    else await api.post("/api/models", { roles });
    info = null; dlg.close(); route();
  };
  dlg.append(el("div", { class: "stack" }, el("h2", {}, t("modelsTitle")),
    data.live ? null : el("p", { class: "muted small" }, t("needKey")),
    el("div", { class: "model-row head muted small" }, el("span", {}), el("span", {}, `${t("estModel")}  ·  ${t("per1m")}`), el("span", {}, t("effort"))),
    row("designer", t("roleDesigner"), t("roleDesignerHelp")), row("agent", t("roleAgent"), t("roleAgentHelp")), row("report", t("roleReport"), t("roleReportHelp")),
    el("div", { class: "row", style: { justifyContent: "flex-end" } }, el("button", { class: "ghost", onclick: () => save(null) }, t("resetEnv")), el("span", { style: { flex: 1 } }),
      el("button", { onclick: () => dlg.close() }, t("cancel")),
      el("button", { class: "primary", onclick: () => save(Object.fromEntries(Object.entries(picks).map(([r, p]) => [r, { model: p.model.value, effort: p.effort.value }]))) }, t("save")))));
  dlg.addEventListener("close", () => dlg.remove());
  document.body.append(dlg);
  dlg.showModal();
}
for (const l of ["en", "ja"]) document.getElementById("lang-" + l).addEventListener("click", async () => {
  if (busy && !(await leaveDialog())) return;
  busy = 0; setLang(l); route();
});

const statusText = (s) => t("status" + s[0].toUpperCase() + s.slice(1));
const statusChip = (s) => el("span", { class: "chip " + (s === "running" ? "live" : s === "failed" ? "bad" : "") }, el("span", { class: "dot" }), statusText(s));
function md(src) {
  // small Markdown subset: headings, bullets, bold, tables, paragraphs
  const out = []; let list = false, table = false;
  const inline = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`(.+?)`/g, "<code>$1</code>");
  const close = () => { if (list) { out.push("</ul>"); list = false; } if (table) { out.push("</table>"); table = false; } };
  for (const raw of String(src || "").split("\n")) {
    const line = raw.trimEnd();
    if (/^\|.*\|$/.test(line.trim())) {
      if (/^\|[\s:|-]+\|$/.test(line.trim())) continue;
      if (!table) { close(); out.push("<table>"); table = true; }
      out.push("<tr>" + line.trim().slice(1, -1).split("|").map((c) => `<td>${inline(c.trim())}</td>`).join("") + "</tr>");
      continue;
    }
    const h = line.match(/^(#{1,4})\s+(.*)/), b = line.match(/^\s*[-*]\s+(.*)/);
    if (h) { close(); out.push(`<h${Math.min(3, h[1].length + 1)}>${inline(h[2])}</h${Math.min(3, h[1].length + 1)}>`); }
    else if (b) { if (table) close(); if (!list) { out.push("<ul>"); list = true; } out.push(`<li>${inline(b[1])}</li>`); }
    else if (!line.trim()) close();
    else { close(); out.push(`<p>${inline(line)}</p>`); }
  }
  close();
  return out.join("");
}

// ---------------------------------------------------------------- home
async function home() {
  crumbs([]);
  const worlds = await api.get("/api/worlds");
  const ta = el("textarea", { placeholder: t("scenarioPh") });
  const logBox = el("div", { class: "log", hidden: true });
  const btn = el("button", { class: "primary big", disabled: !info.llm_live }, t("design"));
  const samples = worlds.filter((w) => w.scenario);
  let si = 0;
  const example = samples.length ? el("button", { type: "button", class: "outline", onclick: () => { ta.value = L(samples[si++ % samples.length].scenario); ta.focus(); } }, t("example")) : null;
  const draft = el("button", { type: "button", class: "outline", disabled: !info.llm_live, title: t("draftHelp") }, "✦ " + t("draft"));
  const confirmEmpty = () => new Promise((resolve) => {
    const dlg = el("dialog", { class: "dlg" });
    const done = (v) => { dlg.close(); resolve(v); };
    dlg.append(el("div", { class: "stack" }, el("h2", {}, t("draftEmptyTitle")), el("p", {}, t("draftEmptyBody")),
      el("div", { class: "row", style: { justifyContent: "flex-end" } }, el("button", { onclick: () => done(false) }, t("draftEmptyBack")), el("button", { class: "primary", onclick: () => done(true) }, t("draftEmptyGo")))));
    dlg.addEventListener("close", () => { dlg.remove(); resolve(false); });
    document.body.append(dlg); dlg.showModal();
  });
  draft.addEventListener("click", async () => {
    if (!ta.value.trim() && !(await confirmEmpty())) { ta.focus(); return; }
    draft.disabled = true; btn.disabled = true; draft.textContent = t("drafting"); logBox.hidden = true;
    busy++;
    try { const res = await api.post("/api/scenario/draft", { idea: ta.value, lang }); ta.value = res.scenario; ta.style.height = Math.min(360, ta.scrollHeight + 4) + "px"; ta.focus(); }
    catch (e) { logBox.hidden = false; logBox.textContent = e.message; }
    busy = Math.max(0, busy - 1);
    draft.disabled = false; btn.disabled = !info.llm_live; draft.textContent = "✦ " + t("draft");
  });
  const follow = (first) => {
    let job = first, active = true;
    btn.disabled = true; draft.disabled = true; btn.textContent = t("designing"); logBox.hidden = false;
    busy++;
    cleanup.push(() => { active = false; });
    const tick = async () => {
      if (!active) return;
      try { job = await api.get(`/api/design/${job.id}`); } catch { return later(tick, 3000); }
      logBox.textContent = job.log.map((l) => `[${String(l.t).padStart(4)}s] ${L(l.text)}`).join("\n") + `\n${usd(job.cost)} · ${job.seconds}s`;
      logBox.scrollTop = logBox.scrollHeight;
      if (job.status === "running") return later(tick, 2000);
      busy = Math.max(0, busy - 1);
      btn.disabled = false; draft.disabled = !info.llm_live; btn.textContent = t("design");
      if (job.status === "done") location.hash = `#/world/${job.world_id}`;
    };
    tick();
  };
  btn.addEventListener("click", async () => {
    logBox.hidden = false; logBox.textContent = "";
    try { follow(await api.post("/api/worlds/design", { scenario: ta.value })); }
    catch (e) { logBox.textContent = e.message; }
  });
  api.get("/api/design").then((jobs) => {            // a world still being created (e.g. after a reload): show it again
    const running = jobs.find((j) => j.status === "running");
    if (running) follow(running);
  }).catch(() => {});
  app.replaceChildren(el("div", { class: "wide" },
    el("section", { class: "hero" },
      el("div", { class: "hero-text" },
        el("h1", { class: "display" }, t("heroA"), el("br"), el("span", { class: "hl" }, t("heroB"))),
        el("p", { class: "lead" }, t("heroSub")),
        ta,
        el("div", { class: "row", style: { marginTop: "12px" } }, btn, example, draft, info.llm_live ? el("span", { class: "muted small" }, t("designHint")) : null),
        info.llm_live ? null : el("p", { class: "muted small", style: { marginTop: "10px" } }, t("needKey")),
        logBox),
      el("img", { class: "hero-scene", src: "/scene.svg", alt: "" })),
    el("h2", { class: "section" }, t("worlds")),
    el("div", { class: "world-list" }, worlds.map((w) => el("a", { class: "world-row", href: `#/world/${w.id}`, title: L(w.summary) },
      el("span", {}, L(w.title)), w.source === "builtin" ? null : el("span", { class: "tag" }, "AI"), el("span", { class: "arrow" }, "→"))))));
}

// ---------------------------------------------------------------- history
const when = (ts) => new Date(ts * 1000).toLocaleString(lang === "ja" ? "ja-JP" : "en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
async function historyPage() {
  crumbs([{ text: t("history") }]);
  const [runs, worlds] = await Promise.all([api.get("/api/runs"), api.get("/api/worlds")]);
  let filter = "";
  const body = el("div", {});
  const render = () => {
    const rows = runs.filter((r) => !filter || String(r.world_id) === filter);
    body.replaceChildren(rows.length ? el("div", { class: "run-list" }, rows.map((r) => el("a", { class: "run-row", href: `#/run/${r.id}` },
      el("div", { class: "grow" }, el("div", { class: "name" }, r.parent_run_id ? "⑂ " : "", r.name), el("div", { class: "muted small" }, L(r.world_title))),
      r.status === "finished" ? null : statusChip(r.status),
      el("span", { class: "muted small" }, when(r.created_at)),
      el("span", { class: "cost" }, r.calls ? usd(r.cost) : "–"),
      el("button", { class: "ghost danger", title: t("delete"), onclick: async (e) => { e.preventDefault(); if (confirm(t("confirmDelete"))) { await api.del(`/api/runs/${r.id}`); route(); } } }, "×"))))
      : el("p", { class: "muted" }, t("noRuns")));
  };
  const sel = el("select", { onchange: (e) => { filter = e.target.value; render(); } }, el("option", { value: "" }, t("allWorlds")), worlds.map((w) => el("option", { value: w.id }, L(w.title))));
  app.replaceChildren(el("div", { class: "stack narrow" }, el("div", { class: "row" }, el("h1", {}, t("history")), el("span", { style: { flex: 1 } }), sel), body));
  render();
}

// ---------------------------------------------------------------- data transfer
function dataPage() {
  crumbs([{ text: t("data") }]);
  const file = el("input", { id: "backup-file", type: "file", accept: ".sqlite3,.sqlite,.db," + SQLITE_MEDIA });
  const notice = el("p", { role: "status", hidden: true });
  const exp = el("button", { onclick: () => transfer(false) }, t("dataExport"));
  const imp = el("button", { class: "primary", disabled: true, onclick: () => transfer(true) }, t("dataImport"));
  file.addEventListener("change", () => { imp.disabled = !file.files.length; });
  function status(message, error = false) {
    notice.className = error ? "banner err" : "banner";
    notice.textContent = message;
    notice.hidden = !message;
  }
  async function transfer(importing) {
    const backup = file.files[0];
    if (importing && (!backup || !confirm(t("dataConfirm") + "\n\n" + backup.name))) return;
    exp.disabled = imp.disabled = file.disabled = true;
    status(t("dataWorking"));
    try {
      const response = await fetch(importing ? "/api/data/import" : "/api/data/export", importing
        ? { method: "POST", headers: { "Content-Type": SQLITE_MEDIA }, body: backup } : undefined);
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(response.status === 409 ? t("dataPause") : data.error || data.detail || `HTTP ${response.status}`);
      }
      if (importing) {
        info = null;
        file.value = "";
        localStorage.setItem(DATA_CHANGE, String(Date.now()));
        status(t("dataImported"));
      } else {
        const url = URL.createObjectURL(await response.blob());
        const link = el("a", { href: url, download: "hakoniwa.sqlite3" });
        document.body.append(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
        status("");
      }
    } catch (e) {
      status(e.message, true);
    } finally {
      exp.disabled = file.disabled = false;
      imp.disabled = !file.files.length;
    }
  }
  app.replaceChildren(el("div", { class: "stack narrow" }, el("h1", {}, t("data")),
    el("div", { class: "card stack" }, el("h2", {}, t("dataExport")), el("p", {}, t("dataExportHelp")), exp),
    el("div", { class: "card stack" }, el("h2", {}, t("dataImport")), el("p", {}, t("dataImportHelp")),
      el("label", { for: file.id }, t("dataFile")), el("div", { class: "row" }, file, imp)),
    el("p", { class: "muted small" }, t("dataPause")), notice));
}
window.addEventListener("storage", (e) => {
  if (e.key === DATA_CHANGE) location.reload();
});

// ---------------------------------------------------------------- world lines
function lineRuns(spec, defaults, runs, results) {
  const byId = new Map(runs.map((r) => [r.id, r]));
  return runs.map((r) => {
    const base = byId.get(r.parent_run_id)?.params || defaults;
    const diff = Object.keys(r.params).filter((k) => k in defaults && r.params[k] !== base[k]).map((k) => paramLabel(spec, k, r.params[k]));
    const h = (results.get(r.id) || [])[0];
    return { id: r.id, name: r.name, parent_run_id: r.parent_run_id, fork_tick: r.fork_tick, tick: r.tick, total: r.config.ticks, diff,
      statusText: statusText(r.status), result: h ? `${L(h.label)} ${fmt(h.value, h.format, h.unit)}` : "" };
  });
}
async function runResults(worldId) {
  const all = await api.get("/api/runs");
  return new Map(all.filter((r) => r.world_id === worldId).map((r) => [r.id, r.headline]));
}

// ---------------------------------------------------------------- world
function paramInput(p, value, onChange) {
  if (p.type === "bool") return el("input", { type: "checkbox", checked: !!value, onchange: (e) => onChange(e.target.checked) });
  if (p.type === "choice") return el("select", { onchange: (e) => onChange(e.target.value) }, p.choices.map((c) => el("option", { value: c.id, selected: c.id === value }, L(c.label))));
  return el("input", { type: "number", value, min: p.min, max: p.max, step: p.step ?? "any", onchange: (e) => onChange(e.target.value === "" ? p.default : Number(e.target.value)) });
}
function paramForm(spec, values, { runtimeOnly = false, onChange } = {}) {
  const groups = new Map();
  for (const p of spec.parameters) {
    if (runtimeOnly && p.runtime === false) continue;
    const g = L(p.group) || "";
    if (!groups.has(g)) groups.set(g, []);
    groups.get(g).push(p);
  }
  const kids = [];
  for (const [g, ps] of groups) {
    if (g) kids.push(el("div", { class: "group-title" }, g));
    for (const p of ps) {
      const assumed = /assum/i.test(p.source || "");
      kids.push(el("div", { class: "param" }, el("label", {}, L(p.label) + (p.unit ? ` (${L(p.unit)})` : "")),
        paramInput(p, values[p.id], (v) => { values[p.id] = v; onChange && onChange(p.id, v); }),
        runtimeOnly ? null : el("div", { class: "src" + (assumed ? " assumed" : ""), title: p.source || "" }, p.source || "")));
    }
  }
  return el("div", { class: "params" }, kids);
}
const paramLabel = (spec, id, v) => {
  const p = spec.parameters.find((x) => x.id === id);
  if (!p) return `${id} = ${v}`;
  const shown = p.type === "choice" ? L((p.choices.find((c) => c.id === v) || {}).label) || v : p.type === "bool" ? (v ? "✓" : "✗") : Number(v).toLocaleString();
  return `${L(p.label)} = ${shown}`;
};

async function worldPage(id) {
  const w = await api.get(`/api/worlds/${id}`);
  const spec = w.spec;
  crumbs([{ text: L(spec.title) }]);
  const values = { ...w.defaults };
  const cfg = { ticks: spec.tick.default_ticks, seed: 1, ai: info.llm_live ? "auto" : "mock", agent_model: null, max_decisions_per_tick: 40, budget_usd: null };
  const estLine = el("div", { class: "est" }), estMore = el("div", {});
  const nameIn = el("input", { type: "text", placeholder: `Run ${w.runs.length + 1}`, style: { width: "100%" } });
  const paramSummary = el("summary", {});
  const refreshSummary = () => {
    const n = spec.parameters.filter((p) => values[p.id] !== w.defaults[p.id]).length;
    paramSummary.textContent = `${t("parameters")} (${spec.parameters.length})` + (n ? ` · ${n} ${t("changed")}` : "");
  };
  let timer = null, seq = 0;
  cleanup.push(() => clearTimeout(timer));
  const estimate = () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const mine = ++seq;
      estLine.textContent = t("estimating");
      try {
        const e = await api.post(`/api/worlds/${id}/estimate`, { params: values, config: cfg });
        if (mine !== seq) return;
        if (e.ai === "mock") { estLine.textContent = t("estMock"); estMore.replaceChildren(); return; }
        const s = e.selected;
        estLine.replaceChildren(el("b", {}, s.cost === null ? t("estUnknown") : `${t("about")} ${usd(s.cost)}`), s.cost === null ? "" : ` (${usd(s.low)}–${usd(s.high)})`,
          el("span", { class: "muted" }, ` · ${e.calls.toLocaleString()} ${t("estCalls")} · ${s.model}`));
        const row = (r) => el("tr", { class: r.model === e.agent_model ? "sel" : "" }, el("td", {}, r.model), el("td", { class: "num" }, usd(r.cost)), el("td", { class: "num" }, `${usd(r.low)}–${usd(r.high)}`),
          el("td", { class: "num" }, `${r.out_per_call} (${r.basis === "observed" ? t("estObserved") : t("estAssumed")})`));
        estMore.replaceChildren(el("details", {}, el("summary", {}, t("estByModel")),
          el("table", {}, el("tr", {}, el("th", {}, t("estModel")), el("th", { class: "num" }, t("estLikely")), el("th", { class: "num" }, `${t("estLow")}–${t("estHigh")}`), el("th", { class: "num" }, t("estOut"))), e.by_model.map(row)),
          el("p", { class: "muted small" }, `${t("estNote")} ${t("estReport")}: ${usd(e.report.cost)} (${e.report.model}).`)),
          e.problems.length ? el("div", { class: "banner err small" }, e.problems.join(" / ")) : "");
      } catch (err) { if (mine === seq) estLine.replaceChildren(el("span", { class: "muted" }, err.message)); }
    }, 300);
  };
  const start = async (btn) => {
    btn.disabled = true;
    try {
      const run = await api.post(`/api/worlds/${id}/runs`, { name: nameIn.value || null, params: values, config: cfg, start: true });
      location.hash = `#/run/${run.id}`;
    } catch (e) { btn.disabled = false; estLine.replaceChildren(el("span", { class: "banner err" }, e.message)); }
  };
  const num = (key, attrs = {}) => el("input", { type: "number", value: cfg[key] ?? "", ...attrs, onchange: (e) => { cfg[key] = e.target.value === "" ? null : Number(e.target.value); estimate(); } });
  const setup = el("div", { class: "card stack start-card" }, el("h2", {}, t("startRun")),
    el("div", { class: "row", style: { alignItems: "flex-end" } },
      el("div", {}, el("label", {}, `${t("ticks")} (${L(spec.tick.unit)})`), num("ticks", { min: 1, max: spec.tick.max_ticks || 5000 })),
      el("div", {}, el("label", {}, t("ai")), el("select", { onchange: (e) => { cfg.ai = e.target.value; estimate(); } },
        el("option", { value: "auto", selected: cfg.ai === "auto", disabled: !info.llm_live }, t("aiLive")),
        el("option", { value: "mock", selected: cfg.ai === "mock" }, t("aiMock")))),
      el("button", { class: "primary big", onclick: (e) => start(e.target) }, "▶ " + t("start"))),
    estLine, estMore,
    el("details", {}, paramSummary, el("p", { class: "muted small" }, t("sourcesNote")), paramForm(spec, values, { onChange: () => { refreshSummary(); estimate(); } })),
    el("details", {}, el("summary", {}, t("moreSettings")), el("div", { class: "params", style: { marginTop: "8px" } },
      el("div", {}, el("label", {}, t("runName")), nameIn),
      el("div", {}, el("label", {}, t("agentModel")), el("input", { type: "text", list: "model-list", placeholder: info.models.agent, disabled: !info.llm_live,
        onchange: (e) => { cfg.agent_model = e.target.value.trim() || null; estimate(); } }), el("datalist", { id: "model-list" }, Object.keys(info.prices || {}).map((m) => el("option", { value: m })))),
      el("div", {}, el("label", {}, t("budget")), num("budget_usd", { min: 0, step: "any", placeholder: "—" })),
      el("div", {}, el("label", {}, t("maxDecisions")), num("max_decisions_per_tick", { min: 0, max: 500 })),
      el("div", {}, el("label", {}, t("seed")), num("seed", { min: 0 })))));
  refreshSummary(); estimate();

  const depth = (r) => { let d = 0, cur = r; while (cur && cur.parent_run_id) { d++; cur = w.runs.find((x) => x.id === cur.parent_run_id); } return d; };
  const runRows = w.runs.map((r) => {
    const diff = Object.keys(r.params).filter((k) => k in w.defaults && r.params[k] !== w.defaults[k]);
    return el("tr", {},
      el("td", { style: { paddingLeft: (8 + depth(r) * 18) + "px" } }, r.parent_run_id ? "⑂ " : "", el("a", { href: `#/run/${r.id}` }, r.name),
        diff.length ? el("div", { class: "muted small" }, diff.slice(0, 3).map((k) => paramLabel(spec, k, r.params[k])).join(" · ") + (diff.length > 3 ? " …" : "")) : null),
      el("td", {}, statusChip(r.status)), el("td", { class: "num" }, `${r.tick} / ${r.config.ticks}`),
      el("td", { class: "muted small" }, r.config.ai === "mock" || !info.llm_live ? t("aiMock") : (r.config.agent_model || info.models.agent)),
      el("td", { class: "num" }, el("button", { class: "ghost danger", onclick: async () => { if (confirm(t("confirmDelete"))) { await api.del(`/api/runs/${r.id}`); route(); } } }, t("delete"))));
  });
  const bullets = (items) => el("ul", { class: "plain" }, (items || []).map((q) => el("li", {}, L(q))));
  const linesHost = el("div", {});
  if (w.runs.length) runResults(id).then((results) => queueMicrotask(() => worldLines(linesHost, { runs: lineRuns(spec, w.defaults, w.runs, results), current: null, unit: L(spec.tick.unit), onOpen: (r) => { location.hash = `#/run/${r.id}`; } })));
  app.replaceChildren(el("div", { class: "stack" },
    el("div", {}, el("div", { class: "row" }, el("h1", {}, L(spec.title)), el("span", { class: "tag" }, w.source === "builtin" ? t("sample") : t("generated")),
      el("a", { class: "btn", href: `/api/worlds/${id}/report.md?lang=${lang}`, download: true }, t("worldReportDownload")),
      w.source !== "builtin" ? el("button", { class: "ghost danger", onclick: async () => { if (confirm(t("confirmDelete"))) { await api.del(`/api/worlds/${id}`); location.hash = "#/"; } } }, t("delete")) : null),
      el("p", { class: "muted", style: { maxWidth: "900px" } }, L(spec.summary))),
    el("div", { class: "two" },
      el("div", { class: "stack" }, setup,
        w.runs.length ? el("div", { class: "card stack" }, el("h2", {}, t("worldLines")), linesHost,
          el("details", {}, el("summary", {}, `${t("runsTitle")} (${w.runs.length})`), el("table", {}, runRows))) : null),
      el("div", { class: "stack" },
        el("div", { class: "card" }, el("h3", {}, t("questions")), bullets(spec.questions)),
        el("div", { class: "card" }, el("h3", {}, t("assumptions")), bullets(spec.assumptions)),
        el("div", { class: "card stack" },
          el("details", {}, el("summary", {}, `${t("residents")} (${spec.agents.length})`), el("table", {}, spec.agents.map((a) => el("tr", {}, el("td", { style: { fontWeight: 600 } }, L(a.name)), el("td", { class: "muted small" }, a.persona))))),
          el("details", {}, el("summary", {}, t("model")), el("pre", { class: "code" }, w.code)),
          w.notes ? el("details", {}, el("summary", {}, t("research")), el("pre", { class: "code" }, w.notes)) : null,
          w.design_usage && w.design_usage.cost ? el("div", { class: "muted small" }, `${t("designCost")}: ${usd(w.design_usage.cost)}`) : null)))));
}

// ---------------------------------------------------------------- run
async function runPage(id) {
  const R = { id, rows: [], last: -1, cursor: 0, follow: true, events: [], lastEvent: 0, tab: "feed", filter: "all", compare: new Map(), colors: new Map(), chatKey: null, tableMode: new Set(), frame: null, alive: true };
  cleanup.push(() => { R.alive = false; });
  R.run = await api.get(`/api/runs/${id}`);
  const world = await api.get(`/api/worlds/${R.run.world_id}`);
  const spec = world.spec;
  const metric = Object.fromEntries(spec.metrics.map((m) => [m.id, m]));
  const agentName = (aid) => L((spec.agents.find((a) => a.id === aid) || {}).name) || aid;
  const who = (x) => x.name ? `${L(x.name)} · ${agentName(x.agent)}` : agentName(x.agent);     // own name first, then what kind of resident
  crumbs([{ text: L(spec.title), href: `#/world/${world.id}` }, { text: R.run.name }]);
  if (R.run.parent_run_id) R.compare.set(R.run.parent_run_id, { run: world.runs.find((r) => r.id === R.run.parent_run_id), rows: [] });
  const colorOf = (rid) => { if (!R.colors.has(rid)) R.colors.set(rid, SERIES[(R.colors.size) % SERIES.length]); return R.colors.get(rid); };
  colorOf(id);

  // skeleton
  const $ = {};
  $.status = el("span", {}); $.clock = el("span", { class: "clock" }); $.cost = el("span", { class: "chip" });
  $.range = el("input", { type: "range", min: 0, max: 1, value: 0 });
  $.play = el("button", { class: "primary" }); $.step = el("button", {}, "⏭ " + t("step"));
  $.follow = el("input", { type: "checkbox", checked: true });
  $.speed = el("select", {}, [["slow", 900], ["normal", 250], ["fast", 60], ["max", 0]].map(([k, v]) => el("option", { value: v, selected: v === (R.run.config.tick_delay_ms ?? 250) }, t(k))));
  $.tiles = el("div", { class: "tiles" }); $.map = el("div", { class: "map" }); $.panel = el("div", { class: "panel" }); $.tabs = el("div", { class: "tabs" });
  $.charts = el("div", { class: "charts" }); $.compare = el("div", { class: "row" }); $.report = el("div", { class: "report" }); $.err = el("div", {});
  $.lines = el("div", {});
  if (world.runs.length > 1) runResults(world.id).then((results) => queueMicrotask(() => worldLines($.lines, { runs: lineRuns(spec, world.defaults, world.runs, results), current: id, unit: L(spec.tick.unit), onOpen: (r) => { if (r.id !== id) location.hash = `#/run/${r.id}`; } })));
  $.extend = el("button", { hidden: true, onclick: () => control("start", { ticks: R.total + spec.tick.default_ticks }) }, `+${spec.tick.default_ticks} ${t("ticksWord")}`);
  $.play.title = "Space"; $.range.title = "← →";
  const bar = el("div", { class: "runbar" }, $.play, $.step, $.extend, el("label", { class: "row", style: { margin: 0 } }, $.follow, t("live")), $.speed, $.clock, $.range, $.status, $.cost,
    el("button", { onclick: () => forkDialog() }, "⑂ " + t("forkHere")));
  const parent = world.runs.find((r) => r.id === R.run.parent_run_id);
  $.about = el("div", { class: "row small about" });
  const renderAbout = () => {
    const diffKeys = Object.keys(R.run.params).filter((k) => k in world.defaults && R.run.params[k] !== world.defaults[k]);
    $.about.hidden = !parent && !diffKeys.length;
    $.about.replaceChildren(...[parent ? el("span", { class: "muted" }, `⑂ ${t("branchOf")} `, el("a", { href: `#/run/${parent.id}` }, parent.name), ` · ${t("tick")} ${R.run.fork_tick}`) : null,
      ...diffKeys.map((k) => el("span", { class: "tag" }, paramLabel(spec, k, R.run.params[k])))].filter(Boolean));
  };
  app.replaceChildren(el("div", { class: "stack" }, bar, $.about, $.err, $.tiles,
    el("div", { class: "two" }, el("div", { class: "card" }, $.map), el("div", { class: "card" }, $.tabs, $.panel)),
    world.runs.length > 1 ? el("div", { class: "card stack" }, el("h2", { style: { margin: 0 } }, t("worldLines")), $.lines) : null,
    el("div", { class: "card stack" }, el("div", { class: "row" }, el("h2", { style: { margin: 0 } }, t("compare")), $.compare), $.charts),
    el("div", { class: "card stack" }, el("div", { class: "row" }, el("h2", { style: { margin: 0 } }, t("report")),
      el("button", { onclick: (e) => writeReport(e.target) }, t("writeReport"))), $.report)));

  const control = (action, extra) => api.post(`/api/runs/${id}/control`, { action, ...extra }).then(() => poll(true));
  $.play.addEventListener("click", () => control(R.status === "running" ? "pause" : "start"));
  const onKey = (e) => {
    if (/INPUT|TEXTAREA|SELECT|BUTTON/.test(e.target.tagName) || document.querySelector("dialog[open]")) return;
    if (e.code === "Space") { e.preventDefault(); if (!$.play.disabled) $.play.click(); }
    else if (e.key === "ArrowRight" || e.key === "ArrowLeft") { R.follow = false; $.follow.checked = false; setCursor(R.cursor + (e.key === "ArrowRight" ? 1 : -1)); }
  };
  window.addEventListener("keydown", onKey);
  cleanup.push(() => window.removeEventListener("keydown", onKey));
  $.step.addEventListener("click", () => control("step"));
  $.speed.addEventListener("change", () => control("set", { tick_delay_ms: Number($.speed.value) }));
  $.follow.addEventListener("change", () => { R.follow = $.follow.checked; if (R.follow) setCursor(R.last); });
  $.range.addEventListener("input", () => { R.follow = false; $.follow.checked = false; setCursor(Number($.range.value)); });

  async function setCursor(tk) {
    R.cursor = Math.max(0, Math.min(tk, R.last));
    try { R.frame = await api.get(`/api/runs/${id}/frame?tick=${R.cursor}`); } catch { return; }
    if (!R.alive) return;
    renderBar(); renderTiles(); renderMap(); renderPanel(); renderCharts();
  }
  const clockOf = (tk) => { const row = R.rows[tk - (R.rows[0]?.tick ?? 0)]; return (row && L(row.clock)) || `${t("tick")} ${tk}`; };

  function renderBar() {
    $.status.replaceChildren(statusChip(R.status || R.run.status));
    $.play.textContent = R.status === "running" ? "⏸ " + t("pause") : "▶ " + t("play");
    $.play.disabled = R.status === "finished" || R.status === "failed";
    $.step.disabled = R.status === "running" || R.status === "finished" || R.status === "failed";
    $.extend.hidden = R.status !== "finished";
    renderAbout();
    $.range.max = Math.max(1, R.total || 1); $.range.value = R.cursor;
    $.clock.textContent = `${clockOf(R.cursor)} · ${R.cursor} ${t("of")} ${R.total ?? "?"}`;
    const u = R.usage;
    $.cost.textContent = u ? (u.calls ? `${usd(u.cost)} · ${u.calls} ${t("calls")}` : (R.run.ai_live ? usd(0) : t("noAI"))) : "";
    $.err.replaceChildren(R.error ? el("div", { class: "banner err" }, el("b", {}, t("failed")), el("pre", { class: "code" }, R.error)) : "");
  }

  function renderTiles() {
    const cur = R.frame?.metrics || {};
    const cmp = [...R.compare.values()][0];
    const base = cmp ? (cmp.rows.find((r) => r.tick === R.cursor) || {}).metrics : null;
    $.tiles.replaceChildren(...spec.metrics.filter((m) => m.headline).map((m) => {
      const v = cur[m.id], b = base ? base[m.id] : undefined;
      let delta = null;
      if (v !== undefined && b !== undefined && v !== b) {
        const d = v - b, good = m.good === "up" ? d > 0 : m.good === "down" ? d < 0 : null;
        delta = el("div", { class: "delta" + (good === null ? "" : good ? " good" : " bad") }, `${d > 0 ? "▲" : "▼"} ${fmt(Math.abs(d), m.format, m.unit)} ${t("vs")} ${cmp.run.name}`);
      }
      return el("div", { class: "tile" }, el("div", { class: "label" }, L(m.label)), el("div", { class: "value" }, fmt(v, m.format, m.unit)), delta || (cmp ? el("div", { class: "delta" }, "–") : null));
    }));
  }

  function renderMap() {
    if (!R.frame) return;
    // show what residents said the last time they spoke, for a few ticks afterwards
    const says = R.events.filter((e) => e.kind === "say" && e.node && e.tick <= R.cursor && e.payload.source === "llm");
    const latest = says.length ? says[says.length - 1].tick : -99;
    const recent = new Map();
    for (const e of says) {
      if (e.tick < latest - 1 || R.cursor - e.tick > 6) continue;
      recent.set(e.node, { node: e.node, who: e.name ? L(e.name) : agentName(e.agent), text: L(e.payload.text), tick: e.tick });
    }
    const at = new Map((R.frame.view?.nodes || []).map((n) => [n.id, n]));
    const bubbles = [];
    for (const b of [...recent.values()].sort((a, c) => c.tick - a.tick)) {
      const n = at.get(b.node);
      if (!n || bubbles.length >= 4) continue;
      if (bubbles.some((o) => Math.abs(at.get(o.node).x - n.x) < 26 && Math.abs(at.get(o.node).y - n.y) < 30)) continue;   // would overlap
      bubbles.push(b);
    }
    worldMap($.map, R.frame.view || {}, { label: L, bubbles, onNode: (n) => { R.tab = "residents"; R.nodeFilter = n.id; renderPanel(); } });
  }

  const TABS = ["feed", "residents", "intervene", "chat", "facts"];
  function renderPanel() {
    $.tabs.replaceChildren(...TABS.map((k) => el("button", { class: R.tab === k ? "on" : "", onclick: () => { R.tab = k; if (k !== "residents") R.nodeFilter = null; renderPanel(); } }, t(k))));
    ({ feed: panelFeed, residents: panelResidents, intervene: panelIntervene, chat: panelChat, facts: panelFacts })[R.tab]();
  }

  function panelFeed() {
    const chips = el("div", { class: "row", style: { marginBottom: "6px" } }, ["all", "events", "voices"].map((k) => el("button", { class: "ghost" + (R.filter === k ? " on" : ""), style: R.filter === k ? { color: "var(--text-primary)", fontWeight: 600 } : {}, onclick: () => { R.filter = k; renderPanel(); } }, t(k))));
    const items = R.events.filter((e) => e.tick <= R.cursor && (R.filter === "all" || (R.filter === "voices") === (e.kind === "say"))).slice(-160).reverse();
    $.panel.replaceChildren(chips, ...(items.length ? items.map((e) => {
      const when = el("div", { class: "when" }, clockOf(e.tick));
      if (e.kind === "say") return el("div", { class: "feed-item" }, when, el("div", {}, el("div", { class: "who" }, who(e), e.node ? el("span", { class: "muted", style: { fontWeight: 400 } }, " · " + nodeLabel(e.node)) : null),
        el("div", {}, "“" + L(e.payload.text) + "”"), el("div", { class: "sum" }, L(e.payload.summary))));
      return el("div", { class: "feed-item" }, when, el("div", {}, el("span", { class: "kind " + e.kind }, e.kind), L(e.payload.text)));
    }) : [el("p", { class: "muted" }, t("noEvents"))]));
  }
  const nodeLabel = (nid) => { const n = (R.frame?.view?.nodes || []).find((x) => x.id === nid); return n ? L(n.label) : nid; };
  const srcLabel = (s) => t("src" + s[0].toUpperCase() + s.slice(1));

  function policyBlock(p, withButtons = true) {
    const act = p.action || {};
    const kids = [];
    if (act.weights && p.options) {
      const opts = p.options.map((o, i) => ({ ...o, w: act.weights[o.id] || 0, color: SERIES[i % SERIES.length] }));
      kids.push(el("div", { class: "segbar" }, opts.filter((o) => o.w > 0.004).map((o) => el("span", { style: { width: (o.w * 100) + "%", background: o.color }, title: `${L(o.label)} ${(o.w * 100).toFixed(0)}%` }))));
      kids.push(el("div", { class: "legend" }, opts.map((o) => el("span", {}, el("i", { style: { background: o.color } }), `${L(o.label)} ${(o.w * 100).toFixed(0)}%`))));
    } else if (act.choice) {
      const o = (p.options || []).find((x) => x.id === act.choice);
      kids.push(el("div", {}, "→ ", el("b", {}, o ? L(o.label) : act.choice)));
    }
    const nums = Object.entries(act.numbers || {});
    if (nums.length) kids.push(el("div", { class: "small" }, nums.map(([k, v]) => `${k}: ${Number(v).toLocaleString()}`).join(" · ")));
    if (p.say) kids.push(el("div", { class: "quote" }, "“" + L(p.say) + "”"));
    if (p.thought) kids.push(el("div", { class: "thought" }, `${t("thought")}: ${p.thought}`));
    return el("div", { class: "policy" },
      el("div", { class: "head" }, el("span", { class: "name" }, who(p)), p.node ? el("span", { class: "muted small" }, nodeLabel(p.node)) : null,
        p.population ? el("span", { class: "muted small" }, `${Number(p.population).toLocaleString()} ${t("population")}`) : null,
        el("span", { class: "tag" }, srcLabel(p.source)), el("span", { class: "muted small" }, clockOf(p.tick))),
      kids,
      withButtons ? el("div", { class: "row", style: { marginTop: "4px" } },
        el("button", { class: "ghost", onclick: (e) => showHistory(p, e.target) }, t("history")),
        el("button", { class: "ghost", onclick: () => { R.chatKey = p.key; R.tab = "chat"; renderPanel(); } }, t("interview"))) : null);
  }
  async function showHistory(p, btn) {
    const rows = await api.get(`/api/runs/${id}/history?key=${encodeURIComponent(p.key)}`);
    btn.closest(".policy").append(el("div", { style: { marginLeft: "10px" } }, rows.filter((r) => r.tick <= R.cursor).reverse().map((r) => el("div", { class: "small", style: { padding: "3px 0" } },
      el("span", { class: "muted" }, clockOf(r.tick) + " · "), lang === "ja" ? (r.summary_ja || r.summary) : r.summary, r.say ? el("div", { class: "muted" }, "“" + L(r.say) + "”") : null))));
    btn.disabled = true;
  }
  function panelResidents() {
    const allPs = R.frame?.policies || [];
    const kinds = [...new Set(allPs.map((p) => p.agent))];
    if (R.agentFilter && !kinds.includes(R.agentFilter)) R.agentFilter = null;
    const ps = allPs.filter((p) => (!R.nodeFilter || p.node === R.nodeFilter) && (!R.agentFilter || p.agent === R.agentFilter));
    const pick = kinds.length > 3 ? el("select", { style: { marginBottom: "6px" }, onchange: (e) => { R.agentFilter = e.target.value || null; renderPanel(); } },
      el("option", { value: "" }, `${t("all")} (${allPs.length})`), kinds.map((k) => el("option", { value: k, selected: k === R.agentFilter }, agentName(k)))) : "";
    $.panel.replaceChildren(pick, R.nodeFilter ? el("div", { class: "row" }, el("span", { class: "tag" }, nodeLabel(R.nodeFilter)), el("button", { class: "ghost", onclick: () => { R.nodeFilter = null; renderPanel(); } }, "×")) : "",
      ...(ps.length ? ps.map((p) => policyBlock(p)) : [el("p", { class: "muted" }, t("noResidents"))]));
  }

  function panelFacts() {
    const fs = R.frame?.facts || [];
    const plabel = Object.fromEntries(spec.parameters.map((p) => [p.id, L(p.label)]));
    $.panel.replaceChildren(el("table", {}, el("tr", {}, el("th", {}, t("subject")), el("th", {}, t("predicate")), el("th", {}, t("value")), el("th", { class: "num" }, t("since"))),
      fs.map((f) => el("tr", {}, el("td", {}, f.subject), el("td", {}, f.subject === "world" ? (plabel[f.predicate] || f.predicate) : f.predicate),
        el("td", {}, typeof f.object === "object" ? JSON.stringify(f.object) : String(f.object), f.origin === "intervention" ? el("span", { class: "tag", style: { marginLeft: "6px" } }, t("changed")) : null),
        el("td", { class: "num" }, f.valid_from)))));
  }

  async function applyIntervention(body, fork, note) {
    try {
      if (fork) return forkDialog(body);
      await api.post(`/api/runs/${id}/intervene`, body);
      note.textContent = t("queued");
    } catch (e) { note.textContent = e.message; }
  }
  function panelIntervene() {
    const note = el("div", { class: "muted small" });
    const presets = (spec.interventions || []).map((iv) => el("div", { class: "policy" }, el("div", { class: "name" }, L(iv.label)), el("div", { class: "muted small" }, L(iv.description)),
      el("div", { class: "row", style: { marginTop: "4px" } }, el("button", { onclick: () => applyIntervention({ id: iv.id }, false, note) }, t("applyNow")), el("button", { onclick: () => applyIntervention({ id: iv.id }, true, note) }, "⑂ " + t("forkApply")))));
    const patch = {};
    const vals = { ...(R.run.params || {}) };
    const form = paramForm(spec, vals, { runtimeOnly: true, onChange: (k, v) => { patch[k] = v; } });
    const ta = el("textarea", { placeholder: t("freeText"), style: { minHeight: "60px" } });
    const proposal = el("div", {});
    const interpret = async (btn) => {
      btn.disabled = true;
      try {
        const res = await api.post(`/api/runs/${id}/interpret`, { text: ta.value });
        const keys = Object.keys(res.patch || {});
        proposal.replaceChildren(keys.length ? el("div", { class: "banner stack" }, el("b", {}, t("proposed")), el("div", {}, L(res.explain)),
          el("div", { class: "small" }, keys.map((k) => `${k} → ${res.patch[k]}`).join(" · ")),
          el("div", { class: "row" }, el("button", { onclick: () => applyIntervention({ patch: res.patch, label: res.label }, false, note) }, t("applyNow")), el("button", { onclick: () => applyIntervention({ patch: res.patch, label: res.label }, true, note) }, "⑂ " + t("forkApply"))))
          : el("div", { class: "banner" }, t("nothingToChange"), " ", L(res.explain)));
      } catch (e) { proposal.replaceChildren(el("div", { class: "banner err" }, e.message)); }
      btn.disabled = false;
    };
    $.panel.replaceChildren(el("p", { class: "muted small" }, t("applyHint")), note, el("h3", {}, t("presets")), ...presets,
      el("h3", { style: { marginTop: "12px" } }, t("freeText")), ta, el("div", { class: "row", style: { margin: "6px 0" } }, el("button", { disabled: !info.llm_live, onclick: (e) => interpret(e.target) }, t("interpret"))), proposal,
      el("details", { style: { marginTop: "12px" } }, el("summary", {}, t("changeParams")), form,
        el("div", { class: "row", style: { marginTop: "8px" } }, el("button", { onclick: () => applyIntervention({ patch }, false, note) }, t("applyNow")), el("button", { onclick: () => applyIntervention({ patch }, true, note) }, "⑂ " + t("forkApply")))));
  }

  async function panelChat() {
    const ps = R.frame?.policies || [];
    if (!ps.length) { $.panel.replaceChildren(el("p", { class: "muted" }, t("noResidents"))); return; }
    if (!R.chatKey || !ps.some((p) => p.key === R.chatKey)) R.chatKey = ps[0].key;
    const sel = el("select", { onchange: (e) => { R.chatKey = e.target.value; panelChat(); } }, ps.map((p) => el("option", { value: p.key, selected: p.key === R.chatKey }, `${who(p)}${p.node ? " · " + nodeLabel(p.node) : ""}`)));
    const logEl = el("div", { class: "chat" });
    const input = el("input", { type: "text", placeholder: t("say"), style: { flex: 1 }, disabled: !info.llm_live });
    const send = async () => {
      const text = input.value.trim();
      if (!text) return;
      input.value = ""; logEl.append(el("div", { class: "msg user" }, text));
      const wait = el("div", { class: "msg muted" }, "…"); logEl.append(wait);
      try { const res = await api.post(`/api/runs/${id}/chat`, { key: R.chatKey, text, lang }); wait.className = "msg"; wait.textContent = res.reply; }
      catch (e) { wait.textContent = e.message; }
    };
    input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.isComposing) send(); });
    const me = ps.find((p) => p.key === R.chatKey);
    $.panel.replaceChildren(el("div", { class: "stack" }, sel, policyBlock(me, false), logEl, el("div", { class: "row" }, input, el("button", { onclick: send, disabled: !info.llm_live }, t("send"))),
      info.llm_live ? null : el("p", { class: "muted small" }, t("needKey"))));
    const hist = await api.get(`/api/runs/${id}/chat?key=${encodeURIComponent(R.chatKey)}`);
    logEl.prepend(...hist.map((m) => el("div", { class: "msg" + (m.role === "user" ? " user" : "") }, m.text)));
  }

  function renderCompare() {
    const others = world.runs.filter((r) => r.id !== id);
    $.compare.replaceChildren(...(others.length ? others.map((r) => el("label", { class: "row", style: { margin: 0, color: "var(--text-primary)", fontSize: "13px" } },
      el("input", { type: "checkbox", checked: R.compare.has(r.id), onchange: async (e) => {
        if (e.target.checked) { if (R.compare.size >= 3) { e.target.checked = false; return; } R.compare.set(r.id, { run: r, rows: [] }); colorOf(r.id); await pollCompare(); } else R.compare.delete(r.id);
        renderTiles(); renderCharts();
      } }), el("i", { style: { display: "inline-block", width: "9px", height: "9px", borderRadius: "2px", background: R.compare.has(r.id) ? colorOf(r.id) : "var(--axis)" } }), r.name)) : [el("span", { class: "muted small" }, t("none"))]));
  }

  function renderCharts() {
    const marks = R.events.filter((e) => e.kind === "intervention").map((e) => ({ tick: e.tick, label: L(e.payload.text) }));
    const pts = (rows, mid) => rows.filter((r) => r.metrics[mid] !== undefined).map((r) => [r.tick, r.metrics[mid]]);
    const defs = [];
    if (R.compare.size) {
      for (const c of spec.charts || []) for (const mid of c.metrics) {
        const m = metric[mid];
        defs.push({ key: "m:" + mid, title: L(m.label), format: m.format, unit: m.unit,
          series: [{ name: R.run.name, color: colorOf(id), points: pts(R.rows, mid) }, ...[...R.compare].map(([rid, c2]) => ({ name: c2.run.name, color: colorOf(rid), points: pts(c2.rows, mid) }))] });
      }
    } else {
      for (const c of spec.charts || []) {
        const m0 = metric[c.metrics[0]];
        defs.push({ key: "c:" + c.id, title: L(c.title), format: m0.format, unit: m0.unit, series: c.metrics.map((mid, i) => ({ name: L(metric[mid].label), color: SERIES[i % SERIES.length], points: pts(R.rows, mid) })) });
      }
    }
    $.charts.replaceChildren(...defs.map((d) => {
      const host = el("div", {});
      const tbl = R.tableMode.has(d.key);
      const box = el("div", { class: "chart" }, el("div", { class: "chart-head" }, el("h3", {}, d.title), el("span", { class: "spacer", style: { flex: 1 } }),
        el("button", { class: "ghost small", onclick: () => { tbl ? R.tableMode.delete(d.key) : R.tableMode.add(d.key); renderCharts(); } }, tbl ? t("chartView") : t("table"))),
        d.series.length > 1 ? legend(d.series) : null, host);
      queueMicrotask(() => { if (tbl) host.replaceChildren(dataTable(d.series, d.format, d.unit)); else lineChart(host, { ...d, cursor: R.cursor, marks, clockOf }); });
      return box;
    }));
  }

  function forkDialog(preset) {
    const dlg = el("dialog", { class: "dlg" });
    const name = el("input", { type: "text", value: `${R.run.name} ⑂ ${clockOf(R.cursor)}`, style: { width: "100%" } });
    const custom = preset && preset.patch ? preset : null;
    const sel = el("select", { style: { width: "100%" } }, el("option", { value: "" }, t("noEvent")),
      (spec.interventions || []).map((iv) => el("option", { value: iv.id, selected: !!preset && preset.id === iv.id }, L(iv.label))));
    const err = el("div", { class: "small", style: { color: "var(--bad-text)" } });
    const go = async (btn) => {
      btn.disabled = true;
      try {
        const nr = await api.post(`/api/runs/${id}/fork`, { tick: R.cursor, name: name.value, intervention: custom || (sel.value ? { id: sel.value } : null), start: true });
        dlg.close(); location.hash = `#/run/${nr.id}`;
      } catch (e) { err.textContent = e.message; btn.disabled = false; }
    };
    dlg.append(el("div", { class: "stack" }, el("h2", {}, `⑂ ${t("forkTitle")} · ${clockOf(R.cursor)}`), el("p", { class: "muted small" }, t("forkHelp")),
      el("div", {}, el("label", {}, t("name")), name),
      el("div", {}, el("label", {}, t("forkEvent")), custom ? el("div", { class: "row" }, Object.entries(custom.patch).map(([k, v]) => el("span", { class: "tag" }, paramLabel(spec, k, v)))) : sel),
      err, el("div", { class: "row", style: { justifyContent: "flex-end" } }, el("button", { onclick: () => dlg.close() }, t("cancel")), el("button", { class: "primary", onclick: (e) => go(e.target) }, "⑂ " + t("fork")))));
    dlg.addEventListener("close", () => dlg.remove());
    document.body.append(dlg);
    dlg.showModal();
    name.select();
  }
  async function writeReport(btn) {
    btn.disabled = true; btn.textContent = t("writing");
    try { const rep = await api.post(`/api/runs/${id}/report`, { compare: [...R.compare.keys()] }); showReport(rep); }
    catch (e) { $.report.replaceChildren(el("div", { class: "banner err" }, e.message)); }
    btn.disabled = false; btn.textContent = t("writeReport");
  }
  function showReport(rep) {
    if (!rep || !rep.body) { $.report.replaceChildren(el("p", { class: "muted" }, t("reportEmpty"))); return; }
    $.report.replaceChildren(rep.source === "template" ? el("p", { class: "muted small" }, t("reportSrcTemplate")) : "", el("div", { html: md(L(rep.body)) }));
  }

  async function pollCompare() {
    for (const [rid, c] of R.compare) {
      const last = c.rows.length ? c.rows[c.rows.length - 1].tick : -1;
      const res = await api.get(`/api/runs/${rid}/ticks?since=${last}`);
      c.rows.push(...res.rows);
    }
  }
  async function poll(once) {
    if (!R.alive) return;
    try {
      const res = await api.get(`/api/runs/${id}/ticks?since=${R.last}`);
      const grew = res.rows.length > 0;
      R.rows.push(...res.rows);
      const changed = grew || res.status !== R.status;
      R.status = res.status; R.total = res.total; R.error = res.status === "failed" ? res.error : null;
      if (grew) R.last = R.rows[R.rows.length - 1].tick;
      const evs = await api.get(`/api/runs/${id}/events?since_id=${R.lastEvent}&limit=2000`);
      if (evs.length) { R.events.push(...evs); R.lastEvent = evs[evs.length - 1].id; }
      await pollCompare();
      if (changed || evs.some((e) => e.kind === "intervention")) { const r = await api.get(`/api/runs/${id}`); R.usage = r.usage; R.run = { ...R.run, ...r }; }
      if (grew && R.follow) await setCursor(R.last);
      else if (changed || evs.length) { renderBar(); if (R.tab === "feed") renderPanel(); if (grew) renderCharts(); }
    } catch (e) { $.err.replaceChildren(el("div", { class: "banner err" }, e.message)); }
    if (!once) later(() => poll(), R.status === "running" ? 700 : 2500);
  }

  renderCompare();
  showReport(await api.get(`/api/runs/${id}/report`));
  const wantTick = new URLSearchParams(location.hash.split("?")[1] || "").get("tick");   // #/run/3?tick=12 opens at that tick
  if (wantTick !== null) { R.follow = false; $.follow.checked = false; }
  await poll();
  if (wantTick !== null) await setCursor(Number(wantTick));
  else if (R.frame === null) await setCursor(R.last);
  window.addEventListener("resize", renderCharts);
  cleanup.push(() => window.removeEventListener("resize", renderCharts));
}

// ---------------------------------------------------------------- router
async function route() {
  cleanup.forEach((f) => f()); cleanup = [];
  lastHash = location.hash;
  document.getElementById("tooltip").hidden = true;
  try {
    info = info || await api.get("/api/info");
    chrome();
    const m = location.hash.match(/^#\/(world|run)\/(\d+)/);
    document.getElementById("nav-history").textContent = t("history");
    document.getElementById("nav-data").textContent = t("data");
    if (location.hash.startsWith("#/history")) await historyPage();
    else if (location.hash === "#/data") dataPage();
    else if (!m) await home();
    else if (m[1] === "world") await worldPage(Number(m[2]));
    else await runPage(Number(m[2]));
  } catch (e) {
    app.replaceChildren(el("div", { class: "banner err" }, e.message));
  }
}
window.addEventListener("hashchange", async () => {
  if (busy && location.hash !== lastHash) {
    const target = location.hash;
    history.replaceState(null, "", lastHash || "#/");       // stay where we are while asking
    if (!(await leaveDialog())) return;
    busy = 0;
    location.hash = target;                                  // fires this handler again, now free to go
    return;
  }
  route();
});
setLang(lang);
route();

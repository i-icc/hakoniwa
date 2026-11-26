// Hakoniwa viewer. Plain ES modules, no build step.
import { L, fmt, lang, setLang, t, usd } from "/i18n.js";
import { SERIES, dataTable, el, esc, legend, lineChart, peopleGrid, stateDiagram, worldLines, worldMap } from "/charts.js";

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
  document.getElementById("version").textContent = info.version ? "v" + info.version : "";
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
    ...[["designer", "roleDesigner"], ["draft", "roleDraft"], ["agent", "roleAgent"], ["report", "roleReport"]].filter(([r]) => data.roles[r]).map(([r, k]) => row(r, t(k), t(k + "Help"))),
    el("div", { class: "row", style: { justifyContent: "flex-end" } }, el("button", { class: "ghost", onclick: () => save(null) }, t("resetEnv")), el("span", { style: { flex: 1 } }),
      el("button", { onclick: () => dlg.close() }, t("cancel")),
      el("button", { class: "primary", onclick: () => save(Object.fromEntries(Object.entries(picks).map(([r, p]) => [r, { model: p.model.value, effort: p.effort.value }]))) }, t("save")))));
  dlg.addEventListener("close", () => dlg.remove());
  document.body.append(dlg);
  dlg.showModal();
}
// Switching language redraws the page. What the observer had chosen on it (runs to compare, the tick shown,
// settings, text typed) is handed to the redraw, so nothing is lost.
let keepState = null;      // set by the page on screen: () => its choices
let carried = null;
const kept = () => { const c = carried; carried = null; return c && c.hash === location.hash ? c.state : null; };
for (const l of ["en", "ja"]) document.getElementById("lang-" + l).addEventListener("click", async () => {
  if (l === lang) return;
  if (busy && !(await leaveDialog())) return;
  const y = window.scrollY;
  const open = [...app.querySelectorAll("details")].map((d) => d.open);
  carried = { hash: location.hash, state: keepState ? keepState() : null };
  busy = 0; setLang(l); await route();
  app.querySelectorAll("details").forEach((d, i) => { if (open[i]) d.open = true; });
  window.scrollTo(0, y);
});

// ---------------------------------------------------------------- data: take out, bring in
async function dataDialog() {
  const data = await api.get("/api/data");
  const dlg = el("dialog", { class: "dlg wide-dlg" });
  const size = (n) => n > 1048576 ? (n / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(n / 1024)) + " KB";
  const boxes = [];                                 // {kind: "world"|"run", id, bytes, box, world}
  const total = el("span", { class: "muted small" });
  const refresh = () => { const on = boxes.filter((b) => b.box.checked); total.textContent = `${on.filter((b) => b.kind === "run").length} ${t("runs")} · ${size(on.reduce((a, b) => a + b.bytes, 0))} ${t("dataChosen")}`; };
  const list = el("div", { style: { maxHeight: "300px", overflow: "auto", border: "1px solid var(--border)", borderRadius: "8px", padding: "6px 10px" } },
    data.worlds.map((w) => {
      const wb = el("input", { type: "checkbox", checked: w.source !== "builtin" || w.runs.length > 0 });
      const mine = w.runs.map((r) => { const b = el("input", { type: "checkbox", checked: true }); boxes.push({ kind: "run", id: r.id, bytes: r.bytes, box: b, world: w.id }); b.addEventListener("change", refresh); return [r, b]; });
      boxes.push({ kind: "world", id: w.id, bytes: w.bytes, box: wb, world: w.id, source: w.source });
      wb.addEventListener("change", () => { mine.forEach(([, b]) => { b.checked = wb.checked; }); refresh(); });
      return el("div", { style: { padding: "4px 0" } },
        el("label", { class: "row", style: { margin: 0, color: "var(--text-primary)", fontSize: "14px", fontWeight: 600 } }, wb, el("span", {}, L(w.title) || w.slug),
          w.source === "builtin" ? el("span", { class: "tag" }, t("sample")) : null),
        mine.map(([r, b]) => el("label", { class: "row", style: { margin: "0 0 0 22px", color: "var(--text-primary)", fontSize: "13px" } }, b,
          el("span", { style: { flex: 1 } }, (r.parent_run_id ? "⑂ " : "") + r.name), el("span", { class: "muted small" }, size(r.bytes)))));
    }));
  const gz = el("input", { type: "checkbox", checked: true });
  const all = (v) => { boxes.forEach((b) => { b.box.checked = v; }); refresh(); };
  const save = () => {
    const runs = boxes.filter((b) => b.kind === "run" && b.box.checked).map((b) => b.id);
    const worlds = boxes.filter((b) => b.kind === "world" && b.box.checked).map((b) => b.id);
    if (!runs.length && !worlds.length) return;
    const a = el("a", { href: `/api/data/export?runs=${runs.join(",")}&worlds=${worlds.join(",")}&gz=${gz.checked ? 1 : 0}`, download: "" });
    document.body.append(a); a.click(); a.remove();
  };
  const file = el("input", { type: "file", accept: ".sqlite3,.sqlite,.db,.gz" });
  const result = el("div", { class: "small" });
  const bring = el("button", { onclick: async () => {
    const f = file.files[0];
    if (!f) { file.click(); return; }
    bring.disabled = true; result.textContent = "…";
    try {
      const r = await fetch("/api/data/import", { method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: f });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(body.detail || body.error || r.statusText);
      result.replaceChildren(el("div", {}, t("dataDone").replace("{w}", body.worlds_added).replace("{r}", body.runs) + (body.worlds_matched ? " " + t("dataMatched").replace("{m}", body.worlds_matched) : "")),
        body.skipped.length ? el("div", { class: "muted" }, `${t("dataSkipped")}: ${body.skipped.join("; ")}`) : "");
      later(() => route(), 50);
    } catch (e) { result.replaceChildren(el("span", { class: "banner err" }, e.message)); }
    bring.disabled = false;
  } }, t("dataImportGo"));
  const kept = el("div", { class: "muted small" });
  const showKept = (b) => {
    if (!b) return;
    const last = b.last ? (b.last.error ? b.last.error : `${when(b.last.at)} · ${size(b.last.bytes)}`) : t("dataKeepNever");
    kept.replaceChildren(`${t("dataKept")}: ${b.folder} (${t("dataKeptEvery").replace("{n}", b.minutes)}) · ${t("dataKeptLast")}: ${last} `,
      el("button", { class: "ghost", onclick: async (e) => { e.target.disabled = true; try { b.last = await api.post("/api/data/backup", {}); } catch (err) { b.last = { error: err.message }; } showKept(b); } }, t("dataKeepNow")));
  };
  showKept(data.backup);
  dlg.append(el("div", { class: "stack" }, el("h2", {}, t("data")), el("p", { class: "muted small", style: { margin: 0 } }, t("dataWhy")), kept,
    el("h3", { style: { margin: "6px 0 0" } }, t("dataExport")), el("p", { class: "muted small", style: { margin: 0 } }, t("dataPick")),
    el("div", { class: "row" }, el("button", { class: "ghost", onclick: () => all(true) }, t("dataAll")), el("button", { class: "ghost", onclick: () => all(false) }, t("dataNone")), el("span", { style: { flex: 1 } }), total),
    list,
    el("div", { class: "row" }, el("label", { class: "row", style: { margin: 0 } }, gz, t("dataGz")), el("span", { style: { flex: 1 } }), el("button", { class: "primary", onclick: save }, t("dataGo"))),
    el("h3", { style: { margin: "10px 0 0" } }, t("dataImport")), el("p", { class: "muted small", style: { margin: 0 } }, `${t("dataImportHelp")} (≤ ${data.max_import_mb} MB)`),
    el("div", { class: "row" }, file, el("span", { style: { flex: 1 } }), bring), result,
    el("div", { class: "row", style: { justifyContent: "flex-end" } }, el("button", { onclick: () => dlg.close() }, t("close")))));
  dlg.addEventListener("close", () => dlg.remove());
  document.body.append(dlg); dlg.showModal(); refresh();
}
document.getElementById("nav-data").addEventListener("click", (e) => { e.preventDefault(); dataDialog(); });

const statusText = (s) => t("status" + s[0].toUpperCase() + s.slice(1));
const statusChip = (s) => el("span", { class: "chip " + (s === "running" ? "live" : s === "failed" ? "bad" : "") }, el("span", { class: "dot" }), statusText(s));
function md(src) {
  // small Markdown subset: headings, bullets, bold, tables, paragraphs
  const out = []; let list = false, table = false;
  const inline = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`(.+?)`/g, "<code>$1</code>");
  const close = () => { if (list) { out.push(list === "ol" ? "</ol>" : "</ul>"); list = false; } if (table) { out.push("</table>"); table = false; } };
  for (const raw of String(src || "").split("\n")) {
    const line = raw.trimEnd();
    if (/^\|.*\|$/.test(line.trim())) {
      if (/^\|[\s:|-]+\|$/.test(line.trim())) continue;
      if (!table) { close(); out.push("<table>"); table = true; }
      out.push("<tr>" + line.trim().slice(1, -1).split("|").map((c) => `<td>${inline(c.trim())}</td>`).join("") + "</tr>");
      continue;
    }
    const h = line.match(/^(#{1,4})\s+(.*)/), b = line.match(/^\s*[-*]\s+(.*)/), n = line.match(/^\s*\d+[.)]\s+(.*)/), q = line.match(/^>\s?(.*)/);
    if (h) { close(); out.push(`<h${Math.min(3, h[1].length + 1)}>${inline(h[2])}</h${Math.min(3, h[1].length + 1)}>`); }
    else if (/^-{3,}$/.test(line.trim())) { close(); out.push("<hr>"); }
    else if (q) { close(); out.push(`<blockquote>${inline(q[1])}</blockquote>`); }
    else if (n) { if (table || list === "ul") close(); if (!list) { out.push("<ol>"); list = "ol"; } out.push(`<li>${inline(n[1])}</li>`); }
    else if (b) { if (table || list === "ol") close(); if (!list) { out.push("<ul>"); list = "ul"; } out.push(`<li>${inline(b[1])}</li>`); }
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
  const refBox = el("textarea", { placeholder: t("referencePh"), style: { minHeight: "80px", fontFamily: "ui-monospace, monospace", fontSize: "12px" } });
  const logBox = el("div", { class: "log", hidden: true });
  const k = kept();
  let basedOn = k?.basedOn || null;                // the world this scenario grew out of (see "Take this world further")
  const mode = k?.mode || localStorage.getItem("hakoniwa.mode") || "society";      // "society", or "life": one person's crossroads
  const life = k?.life || null;                    // the person and their paths, once the interview is done
  if (k) { ta.value = k.scenario; refBox.value = k.reference; if (ta.value.length > 200) ta.style.height = "300px"; }
  if (mode === "life") ta.placeholder = t("lifePh");
  keepState = () => ({ scenario: ta.value, reference: refBox.value, basedOn, mode, life });
  const switchMode = (m) => {
    if (m === mode) return;
    localStorage.setItem("hakoniwa.mode", m);
    carried = { hash: location.hash, state: { scenario: "", reference: "", basedOn: null, mode: m, life: null } };
    route();
  };
  // The two things the tool does are the headline itself: two large choices side by side, the chosen one in ink.
  // (A small switch is for two views of one thing; these start different paths, so they get the room of a choice.)
  const MODES = [["society", "modeSociety", "heroA", "heroB"], ["life", "modeLife", "lifeA", "lifeB"]];
  const modeBar = el("div", { class: "modes", role: "tablist" },
    MODES.map(([m, tag, a, b]) => el("button", { class: "mode" + (mode === m ? " on" : ""), role: "tab", "aria-selected": String(mode === m), tabindex: mode === m ? "0" : "-1",
      onclick: () => switchMode(m), onkeydown: (e) => { if (e.key === "ArrowRight" || e.key === "ArrowLeft") switchMode(m === "society" ? "life" : "society"); } },
      el("span", { class: "who " + m }, t(tag)), el("span", { class: "big" }, t(a), el("br"), el("span", { class: "hl" }, t(b))))),
    // what the mode does is one click away, not spelled out on the page
    el("details", { class: "help" }, el("summary", { title: t("whatIsThis") }, "?"), el("p", {}, t(mode === "life" ? "lifeSub" : "heroSub"), mode === "life" ? el("span", { class: "muted" }, " " + t("lifeNot")) : "")));
  document.addEventListener("click", (e) => { const h = modeBar.querySelector(".help"); if (h && h.open && !h.contains(e.target)) h.open = false; });
  const origin = el("p", { class: "muted small", style: { margin: "0 0 6px" }, hidden: !basedOn }, basedOn ? `${t("basedOn")}: ${L(basedOn.title)} ` : "",
    el("button", { class: "ghost", onclick: () => { basedOn = null; origin.hidden = true; } }, "×"));
  const btn = el("button", { class: "primary big", disabled: !info.llm_live }, mode === "life" && !life ? t("lifeStart") : t("design"));
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
  const formBox = el("div", {}), sceneHost = el("div", { class: "hero-scene" }, el("img", { src: "/scene.svg", alt: "" }));
  // Before building, the designer may ask a few things that would change the world: options, or the observer's own words.
  // Resolves to the answers as text ("" when skipped or nothing was asked), or null when the observer backs out.
  const clarify = (questions, opts = {}) => new Promise((resolve) => {
    const dlg = el("dialog", { class: "dlg wide-dlg" });
    let settled = false;
    const done = (v) => { settled = true; dlg.close(); resolve(v); };
    const rows = questions.map((q, i) => {
      const own = el("input", { type: "text", placeholder: t("clarifyOwn"), style: { width: "100%", marginTop: "4px" } });
      const radios = q.options.map((o) => el("input", { type: "radio", name: "cq" + i, value: o }));
      own.addEventListener("input", () => { if (own.value.trim()) radios.forEach((r) => { r.checked = false; }); });
      return { q, own, radios, node: el("div", { class: "stack", style: { gap: "4px" } }, el("div", { style: { fontWeight: 600 } }, q.question),
        q.why ? el("div", { class: "muted small" }, q.why) : "",
        radios.map((r, j) => el("label", { class: "row", style: { margin: 0, fontSize: "14px", color: "var(--text-primary)", alignItems: "flex-start", flexWrap: "nowrap" } }, r, el("span", {}, q.options[j]))), own) };
    });
    const given = () => rows.map(({ q, own, radios }) => ({ question: q.question, answer: own.value.trim() || radios.find((r) => r.checked)?.value || "" })).filter((a) => a.answer);
    const answers = () => opts.list ? given() : given().map((a) => `- ${a.question} -> ${a.answer}`).join("\n");
    dlg.append(el("div", { class: "stack" }, el("h2", {}, opts.title || t("clarifyTitle")), el("p", { class: "muted small", style: { margin: 0 } }, opts.body || t("clarifyBody")), rows.map((r) => r.node),
      el("div", { class: "row", style: { justifyContent: "flex-end" } }, el("button", { onclick: () => done(null) }, t("cancel")), el("span", { style: { flex: 1 } }),
        opts.list ? "" : el("button", { onclick: () => done("") }, t("clarifySkip")), el("button", { class: "primary", onclick: () => done(answers()) }, opts.go || t("clarifyGo")))));
    dlg.addEventListener("close", () => { dlg.remove(); if (!settled) resolve(null); });
    document.body.append(dlg); dlg.showModal();
  });
  // One person's crossroads: first an interview, which turns what they wrote into a person, their paths and a scenario.
  const interview = async () => {
    const story = ta.value.trim();
    if (story.length < 20) { ta.focus(); return; }
    btn.disabled = true; btn.textContent = t("clarifying"); busy++;
    try {
      const { questions } = await api.post("/api/life/interview", { story, lang });
      const answers = questions.length ? await clarify(questions, { list: true, title: t("lifeInterview"), body: t("lifeInterviewBody"), go: t("lifeInterviewGo") }) : [];
      if (answers === null) { busy = Math.max(0, busy - 1); btn.disabled = false; btn.textContent = t("lifeStart"); return; }
      btn.textContent = t("lifeComposing");
      const res = await api.post("/api/life/compose", { story, answers, lang });
      busy = Math.max(0, busy - 1);
      carried = { hash: location.hash, state: { scenario: res.scenario, reference: "", basedOn: null, mode: "life", life: res.life } };
      route();
    } catch (e) { busy = Math.max(0, busy - 1); btn.disabled = false; btn.textContent = t("lifeStart"); logBox.hidden = false; logBox.textContent = e.message; }
  };
  btn.addEventListener("click", async () => {
    logBox.hidden = true;
    if (mode === "life" && !life) return interview();
    const scenario = ta.value.trim();
    if (scenario.length < 20) { ta.focus(); return; }
    if (mode === "life") {                                       // the interview has settled what would otherwise be asked now
      try { const job = await api.post("/api/worlds/design", { scenario, life }); location.hash = `#/world/${job.world_id}`; }
      catch (e) { logBox.hidden = false; logBox.textContent = e.message; }
      return;
    }
    btn.disabled = true; draft.disabled = true; btn.textContent = t("clarifying"); busy++;
    let extra = "";
    try {
      const { questions } = await api.post("/api/scenario/questions", { scenario, lang, based_on: basedOn?.id ?? null });
      if (questions.length) extra = await clarify(questions);
    } catch { /* building does not depend on the questions */ }
    busy = Math.max(0, busy - 1);
    btn.disabled = !info.llm_live; draft.disabled = !info.llm_live; btn.textContent = t("design");
    if (extra === null) return;                                  // backed out: the scenario stays as written
    try { const job = await api.post("/api/worlds/design", { scenario: scenario + (extra ? "\n\nSETTLED WITH THE OBSERVER BEFORE BUILDING:\n" + extra : ""), reference: refBox.value, based_on: basedOn?.id ?? null }); location.hash = `#/world/${job.world_id}`; }
    catch (e) { logBox.hidden = false; logBox.textContent = e.message; }
  });
  if (mode === "life") formBox.append(modeBar,
    life ? el("div", { class: "lifebrief" }, el("div", {}, el("b", {}, `${t("lifeWho")}: `), L(life.protagonist.name)),
      el("div", {}, el("b", {}, `${t("lifePaths")}: `), life.options.map((o) => L(o.label)).join(" / ")),
      el("details", {}, el("summary", { class: "small" }, t("lifeProfile")), el("p", { class: "muted small" }, life.protagonist.profile)),
      el("div", { class: "muted small" }, t("lifeReady"))) : "",
    ta,
    el("div", { class: "row", style: { marginTop: "12px" } }, btn, info.llm_live && life ? el("span", { class: "muted small" }, t("designHint")) : ""),
    info.llm_live ? "" : el("p", { class: "muted small", style: { marginTop: "10px" } }, t("needKey")),
    el("p", { class: "muted small", style: { marginTop: "10px" } }, t("lifePrivacy")),
    logBox);
  else formBox.append(modeBar,
    origin, ta,
    el("div", { class: "row", style: { marginTop: "12px" } }, btn, example || "", draft, info.llm_live ? el("span", { class: "muted small" }, t("designHint")) : ""),
    info.llm_live ? "" : el("p", { class: "muted small", style: { marginTop: "10px" } }, t("needKey")),
    el("details", { style: { marginTop: "10px" } }, el("summary", { class: "small" }, t("reference")), el("p", { class: "muted small" }, t("referenceHelp")), refBox),
    logBox);
  app.replaceChildren(el("div", { class: "wide" },
    el("section", { class: "hero" },
      el("div", { class: "hero-text" }, formBox),
      sceneHost),
    el("h2", { class: "section" }, t("worlds")),
    el("div", { class: "world-list" }, [...worlds].sort((x, y) => (y.source === "building") - (x.source === "building")).map((w) => el("a", { class: "world-row" + (w.source === "building" ? " building" : ""), href: `#/world/${w.id}`, title: L(w.summary) || L(w.scenario) || "" },
      el("span", {}, L(w.title)),
      w.source === "building" ? el("span", { class: "tag live" }, t("buildingTag")) : w.source === "failed" ? el("span", { class: "tag" }, t("failedTag")) : w.life ? el("span", { class: "tag" }, t("lifeTag")) : w.source === "builtin" ? null : el("span", { class: "tag" }, "AI"),
      el("span", { class: "arrow" }, "→"))))));
  if (worlds.some((w) => w.source === "building")) later(() => { if (location.hash === "#/" || location.hash === "") route(); }, 8000);     // the list catches up when a build ends
}

// ---------------------------------------------------------------- a world being built
// A world has its page from the moment building starts. Until it is ready the page is a building site:
// the steps, and the town put together piece by piece as the designer moves through them.
async function buildingPage(id, w) {
  crumbs([{ text: L(w.spec.title) }]);
  const scenario = L(w.spec.scenario) || "";
  const again = () => { carried = { hash: "#/", state: { scenario, reference: "", basedOn: null } }; location.hash = "#/"; };
  const remove = async () => { if (confirm(t("confirmDelete"))) { await api.del(`/api/worlds/${id}`); location.hash = "#/"; } };
  if (w.source === "failed" || !w.job) {                    // it did not work out: what happened, and the way back
    const f = w.spec.failure || {};
    app.replaceChildren(el("div", { class: "wide" }, el("section", { class: "hero" }, el("div", { class: "hero-text" },
      el("h1", { class: "display" }, t("buildFailed")),
      el("p", { class: "lead" }, f.error || ""),
      (f.log || []).length ? el("div", { class: "log" }, f.log.map((l) => `[${String(l.t).padStart(4)}s] ${L(l.text)}`).join("\n")) : "",
      el("div", { class: "row", style: { marginTop: "14px" } }, el("button", { class: "primary", onclick: again }, t("buildAgain")), el("button", { class: "ghost danger", onclick: remove }, t("delete"))),
      el("details", { style: { marginTop: "12px" } }, el("summary", { class: "small" }, t("scenario")), el("p", { class: "muted small" }, scenario))),
      el("div", { class: "hero-scene" }, el("img", { src: "/scene.svg", alt: "" })))));
    return;
  }
  const STEPS = [["research", "stepSurvey"], ["design", "stepRules"], ["validate", "stepTrial"], ["cast", "stepPeople"]];
  const stepOf = (stage) => ({ starting: 0, research: 0, design: 1, validate: 2, repair: 2, cast: 3, done: 4 })[stage] ?? 0;
  const PACE = [70, 140, 45, 60];              // seconds in which a stage shows most of its share of the town
  let job = w.job, active = true, polledAt = performance.now(), shown = 0, svg = null, finished = 0;
  cleanup.push(() => { active = false; });
  const stepsEl = el("ol", { class: "steps" }), meta = el("div", { class: "muted small" }), detail = el("div", { class: "log" });
  const sceneHost = el("div", { class: "hero-scene" });
  app.replaceChildren(el("div", { class: "wide" }, el("section", { class: "hero" }, el("div", { class: "hero-text" },
    el("h1", { class: "display" }, t("buildA"), el("br"), el("span", { class: "hl" }, t("buildB"))), stepsEl, meta,
    el("details", { style: { marginTop: "10px" } }, el("summary", { class: "small" }, t("buildDetail")), detail),
    el("details", { style: { marginTop: "6px" } }, el("summary", { class: "small" }, t("scenario")), el("p", { class: "muted small" }, scenario)),
    el("p", { class: "muted small", style: { marginTop: "12px" } }, t("buildLeave"), " ", el("button", { class: "ghost danger", onclick: remove }, t("buildStop")))),
    sceneHost)));
  fetch("/build.svg").then((r) => r.text()).then((text) => {
    if (!active) return;
    sceneHost.innerHTML = text; svg = sceneHost.querySelector("svg"); svg.classList.add("build");
    requestAnimationFrame(frame);
  }).catch(() => {});
  const draw = () => {
    const at = stepOf(job.stage), lines = job.log.filter((l) => l.stage !== "usage");
    stepsEl.replaceChildren(...STEPS.map(([, key], i) => el("li", { class: i < at ? "done" : i === at ? "on" : "" },
      el("span", { class: "mark" }, i < at ? "✓" : i === at ? "●" : "○"), el("span", {}, t(key)),
      i === at && lines.length ? el("span", { class: "sub" }, L(lines[lines.length - 1].text)) : null)));
    const sec = Math.round(job.seconds || 0);
    meta.textContent = `${usd(job.cost)} · ${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
    detail.textContent = job.log.map((l) => `[${String(l.t).padStart(4)}s] ${L(l.text)}`).join("\n");
  };
  const frame = () => {
    if (!active || !svg) return;
    const g = Number(svg.dataset.ground), th = Number(svg.dataset.things), total = Number(svg.dataset.total);
    const marks = [0, g, g + th * 0.6, g + th * 0.9, total], at = stepOf(job.stage);
    let target = total;
    if (at < 4) {
      const began = (job.log.find((l) => stepOf(l.stage) === at && l.stage !== "usage") || { t: 0 }).t;
      const sec = (job.seconds || 0) + (performance.now() - polledAt) / 1000;
      target = marks[at] + (marks[at + 1] - marks[at]) * (1 - Math.exp(-Math.max(0, sec - began) / PACE[at]));
      if (!shown) shown = marks[at] * 0.9;                    // opened part-way through: most of what is built is already standing
    }
    shown = Math.max(shown, shown + (target - shown) * (at < 4 ? 0.04 : 0.12));
    svg.style.setProperty("--shown", shown.toFixed(2));
    if (finished && (shown > total - 0.6 || performance.now() - finished > 2500)) { route(); return; }      // the same address is now the finished world
    requestAnimationFrame(frame);
  };
  const tick = async () => {
    if (!active) return;
    try { job = await api.get(`/api/design/${job.id}`); polledAt = performance.now(); } catch { return later(tick, 3000); }
    draw();
    if (job.status === "running") return later(tick, 2000);
    if (job.status === "done") { finished = performance.now(); if (!svg) route(); return; }
    active = false; route();                                 // it failed: this page now says so
  };
  draw(); tick();
}

// ---------------------------------------------------------------- history
const when = (ts) => new Date(ts * 1000).toLocaleString(lang === "ja" ? "ja-JP" : "en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
async function historyPage() {
  crumbs([{ text: t("history") }]);
  const [runs, worlds] = await Promise.all([api.get("/api/runs"), api.get("/api/worlds")]);
  let filter = kept()?.filter || "";
  keepState = () => ({ filter });
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
  const sel = el("select", { onchange: (e) => { filter = e.target.value; render(); } }, el("option", { value: "" }, t("allWorlds")), worlds.map((w) => el("option", { value: w.id, selected: String(w.id) === filter }, L(w.title))));
  app.replaceChildren(el("div", { class: "stack narrow" }, el("div", { class: "row" }, el("h1", {}, t("history")), el("span", { style: { flex: 1 } }), sel), body));
  render();
}

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

// ---------------------------------------------------------------- one person's crossroads
// A life world is shown as its futures: each run is one way things could go for the same person. The page puts the
// paths side by side, lets the observer talk with any of those future selves, and sums up across all of them.
async function lifePage(id, w) {
  const spec = w.spec, focus = spec.focus;
  crumbs([{ text: L(focus.question) || L(spec.title) }]);
  let alive = true;
  cleanup.push(() => { alive = false; });
  const k = kept();
  let per = k?.per || 3;
  keepState = () => ({ per });
  const board = el("div", {}), reportBox = el("div", { class: "report" }), makeErr = el("div", {});
  const saveMd = el("a", { class: "btn", hidden: true, download: "", href: `/api/worlds/${id}/life-report.md?lang=${lang}` }, t("saveMd"));
  const perIn = el("input", { type: "number", min: 1, max: 6, value: per, style: { width: "64px" }, onchange: (e) => { per = Math.max(1, Math.min(6, Number(e.target.value) || 3)); } });
  const makeBtn = el("button", { class: "primary", onclick: async () => {
    makeBtn.disabled = true; makeErr.replaceChildren();
    try { await api.post(`/api/worlds/${id}/futures`, { per_path: per, lang }); await refresh(); }
    catch (e) { makeErr.replaceChildren(el("span", { class: "banner err" }, e.message)); }
    makeBtn.disabled = false;
  } }, t("lifeMake"));
  const writeBtn = el("button", { onclick: async () => {
    writeBtn.disabled = true; writeBtn.textContent = t("writing");
    try { showReport(await api.post(`/api/worlds/${id}/life-report`, { lang })); } catch (e) { reportBox.replaceChildren(el("div", { class: "banner err" }, e.message)); }
    writeBtn.disabled = false; writeBtn.textContent = t("lifeWrite");
  } }, t("lifeWrite"));
  const showReport = (rep) => { saveMd.hidden = !(rep && rep.body); reportBox.replaceChildren(rep && rep.body ? el("div", { html: md(L(rep.body)) }) : ""); };

  const spark = (series, lo, hi) => {
    const W = 220, H = 44, n = series.length;
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, class: "spark", role: "img" });
    if (n > 1) {
      const y = (v) => H - 4 - (H - 8) * ((v - lo) / ((hi - lo) || 1));
      svg.append(el("path", { d: series.map((v, i) => `${i ? "L" : "M"}${(i / (n - 1) * W).toFixed(1)},${y(v ?? lo).toFixed(1)}`).join(" "), fill: "none", stroke: "var(--accent)", "stroke-width": 2, "stroke-linejoin": "round" }));
      svg.append(el("circle", { cx: W - 2, cy: y(series[n - 1] ?? lo), r: 3, fill: "var(--accent)" }));
    }
    return svg;
  };
  const talk = (f) => {                             // a conversation with the self of one future
    const dlg = el("dialog", { class: "dlg wide-dlg" });
    const logEl = el("div", { class: "chat", style: { maxHeight: "50vh", overflow: "auto" } });
    const input = el("input", { type: "text", placeholder: t("say"), style: { flex: 1 } });
    const send = async () => {
      const text = input.value.trim();
      if (!text) return;
      input.value = ""; logEl.append(el("div", { class: "msg user" }, text));
      const wait = el("div", { class: "msg muted" }, "…"); logEl.append(wait); logEl.scrollTop = logEl.scrollHeight;
      try { const res = await api.post(`/api/runs/${f.id}/chat`, { key: focus.key, text, lang }); wait.className = "msg"; wait.textContent = res.reply; }
      catch (e) { wait.textContent = e.message; }
      logEl.scrollTop = logEl.scrollHeight;
    };
    input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.isComposing) send(); });
    dlg.append(el("div", { class: "stack" }, el("h2", {}, `${t("lifeTalkTitle")} · ${f.name}`),
      f.last_words ? el("p", { class: "muted small", style: { margin: 0 } }, `${t("lifeLastWords")} (${f.last_words.when}): “${f.last_words.said}”`) : "",
      logEl, el("div", { class: "row" }, input, el("button", { class: "primary", onclick: send }, t("send"))),
      el("div", { class: "row", style: { justifyContent: "flex-end" } }, el("span", { class: "muted small", style: { flex: 1 } }, t("chatNote")), el("button", { onclick: () => dlg.close() }, t("close")))));
    dlg.addEventListener("close", () => dlg.remove());
    document.body.append(dlg); dlg.showModal(); input.focus();
    api.get(`/api/runs/${f.id}/chat?key=${encodeURIComponent(focus.key)}`).then((hist) => { logEl.prepend(...hist.map((m) => el("div", { class: "msg" + (m.role === "user" ? " user" : "") }, m.text))); logEl.scrollTop = logEl.scrollHeight; }).catch(() => {});
  };
  const card = (f, labels, lo, hi) => {
    const running = f.status === "running";
    const moments = [...f.turns.map((x) => ({ tick: x.tick, when: x.when, text: x.did, mine: true })), ...f.happened.filter((x) => !x.over).map((x) => ({ tick: x.tick, when: x.when, text: x.what }))]
      .sort((a, b) => a.tick - b.tick);
    const shown = moments.length > 4 ? [moments[0], moments[Math.floor(moments.length / 3)], moments[Math.floor(2 * moments.length / 3)], moments[moments.length - 1]] : moments;
    return el("div", { class: "future" },
      el("div", { class: "row" }, el("b", { style: { flex: 1 } }, f.name), running ? el("span", { class: "tag live" }, `${t("lifeRunning")} ${f.tick}/${f.total}`) : f.status === "failed" ? statusChip(f.status) : null,
        el("button", { class: "ghost danger", title: t("delete"), onclick: async () => { if (confirm(t("confirmDelete"))) { await api.del(`/api/runs/${f.id}`); refresh(); } } }, "×")),
      spark(f.series, lo, hi),
      el("div", { class: "figs" }, Object.entries(f.figures).slice(0, 3).map(([m, v]) => el("span", {}, el("span", { class: "muted small" }, labels[m] + " "), el("b", {}, String(v.end))))),
      shown.length ? el("ul", { class: "moments" }, shown.map((m) => el("li", { class: m.mine ? "mine" : "" }, el("span", { class: "muted" }, m.when + " "), m.text))) : "",
      f.last_words ? el("div", { class: "quote" }, "“" + f.last_words.said + "”") : "",
      el("div", { class: "row" }, el("button", { disabled: !f.can_talk, onclick: () => talk(f) }, t("lifeTalk")), el("a", { class: "btn ghost", href: `#/run/${f.id}` }, t("lifeDetail"))));
  };
  async function refresh() {
    if (!alive) return;
    let data;
    try { data = await api.get(`/api/worlds/${id}/futures?lang=${lang}`); } catch { return later(refresh, 4000); }
    if (!alive) return;
    const all = data.futures.flatMap((f) => f.series).filter((v) => Number.isFinite(v));
    const lo = all.length ? Math.min(...all) : 0, hi = all.length ? Math.max(...all) : 100;
    board.replaceChildren(...(data.futures.length ? focus.options.map((o) => {
      const mine = data.futures.filter((f) => f.path === o.id);
      return el("div", { class: "pathrow" }, el("h3", {}, L(o.label), el("span", { class: "muted small" }, ` · ${mine.length}`)),
        el("div", { class: "futures" }, mine.map((f) => card(f, data.labels, lo, hi))));
    }) : [el("p", { class: "muted" }, t("lifeNone"))]));
    if (data.report && !reportBox.childElementCount) showReport(data.report);
    writeBtn.disabled = !info.llm_live || !data.futures.some((f) => f.tick > 0);
    if (data.futures.some((f) => f.status === "running")) later(refresh, 2500);
  }
  app.replaceChildren(el("div", { class: "stack" },
    el("div", {}, el("div", { class: "row" }, el("h1", {}, L(focus.question) || L(spec.title)), el("span", { class: "tag" }, t("lifeTag")),
      w.source !== "builtin" ? el("button", { class: "ghost danger", onclick: async () => { if (confirm(t("confirmDelete"))) { await api.del(`/api/worlds/${id}`); location.hash = "#/"; } } }, t("delete")) : null),
      el("p", { class: "muted", style: { maxWidth: "900px", margin: "4px 0" } }, t("lifeNot")),
      w.protagonist ? el("details", {}, el("summary", { class: "small" }, `${t("lifeProfile")}: ${L(w.protagonist.name)}`), el("p", { class: "muted small", style: { maxWidth: "900px" } }, w.protagonist.profile)) : ""),
    el("div", { class: "card stack" }, el("div", { class: "row", style: { alignItems: "flex-end" } },
      el("div", {}, el("label", { title: t("lifeMakeHelp") }, t("lifePer")), perIn), makeBtn, el("span", { class: "muted small", style: { flex: 1 } }, t("lifeMakeHelp"))), makeErr),
    board,
    el("div", { class: "card stack" }, el("div", { class: "row" }, el("h2", { style: { margin: 0 } }, t("lifeReport")), writeBtn, saveMd), reportBox),
    el("p", {}, el("a", { class: "muted small", href: `#/world/${id}?raw=1` }, t("lifeInside")))));
  refresh();
}

async function worldPage(id) {
  const w = await api.get(`/api/worlds/${id}`);
  if (w.source === "building" || w.source === "failed") return buildingPage(id, w);
  if (w.spec.focus && !location.hash.includes("raw=1")) return lifePage(id, w);
  const spec = w.spec;
  crumbs([{ text: L(spec.title) }]);
  const values = { ...w.defaults };
  const cfg = { ticks: spec.tick.default_ticks, seed: 1, ai: info.llm_live ? "auto" : "mock", agent_model: null, max_decisions_per_tick: 2000, budget_usd: null, gate: "off", follow_through: 1,
    // the future is not known, so chance events are on - except in a world replaying a recorded event, where they would add things that did not happen
    chance: (spec.events || []).length > 0 && !spec.metrics.some((m) => m.id.startsWith("real_")) };
  const chanceLine = el("div", { class: "muted small" });
  const showChance = () => { chanceLine.textContent = cfg.chance ? `${t("chance")}: ${t("chanceOn")} (${(spec.events || []).length})` : ""; };
  const estLine = el("div", { class: "est" }), estMore = el("div", {});
  const nameIn = el("input", { type: "text", placeholder: `Run ${w.runs.length + 1}`, style: { width: "100%" } });
  const k = kept();
  const thoughts = el("textarea", { placeholder: t("evolvePh"), style: { minHeight: "88px", width: "100%" } });
  if (k) { Object.assign(values, k.values); Object.assign(cfg, k.cfg); nameIn.value = k.name; thoughts.value = k.thoughts || ""; }
  keepState = () => ({ values: { ...values }, cfg: { ...cfg }, name: nameIn.value, thoughts: thoughts.value });
  // the checkup: what a free rehearsal says about this world
  const checkBox = el("details", {});
  const drawCheck = (rep) => {
    const again = el("button", { class: "ghost", onclick: async () => {
      again.disabled = true; again.textContent = "…";
      try { drawCheck(await api.post(`/api/worlds/${id}/checkup`, {})); } catch (e) { again.disabled = false; again.textContent = t("checkupRun"); checkBox.append(el("div", { class: "banner err" }, e.message)); }
    } }, t("checkupRun"));
    const notes = rep?.notes || [];
    checkBox.replaceChildren(el("summary", {}, `${t("checkupTitle")}${rep ? ` (${notes.length})` : ""}`), el("p", { class: "muted small" }, t("checkupHelp")),
      rep ? (notes.length ? el("ul", { class: "small" }, notes.map((n) => el("li", {}, n))) : el("p", { class: "small" }, t("checkupOk"))) : "",
      rep?.options ? el("table", { class: "fit" }, Object.entries(rep.options).filter(([, v]) => v.moves !== null && v.moves !== undefined).map(([oid, v]) => el("tr", {},
        el("td", {}, L(v.label) || oid), el("td", { class: "muted" }, v.moves < 0.005 ? t("checkupDead") : t("checkupMoves"))))) : "",
      rep?.cast ? el("p", { class: "muted small" }, `${rep.asked} / ${rep.cast} ${t("checkupAsked")}`) : "", again);
  };
  drawCheck(spec.checkup || null);
  // the deck of chance events: what may simply happen in this world
  const eventsBox = el("details", {});
  const drawEvents = (deck) => {
    const write = el("button", { class: "ghost", disabled: !info.llm_live, onclick: async () => {
      write.disabled = true; write.textContent = t("drafting");
      try { drawEvents((await api.post(`/api/worlds/${id}/events`, {})).events); eventsBox.open = true; route(); }
      catch (e) { write.disabled = false; write.textContent = "✦ " + t("eventsWrite"); eventsBox.append(el("div", { class: "banner err" }, e.message)); }
    } }, "✦ " + t("eventsWrite"));
    eventsBox.replaceChildren(el("summary", {}, `${t("eventsDeck")} (${deck.length})`), el("p", { class: "muted small" }, t("chanceHelp")),
      deck.length ? el("table", {}, deck.map((e) => el("tr", {}, el("td", { style: { fontWeight: 600 } }, L(e.label) || e.id),
        el("td", { class: "muted small" }, L(e.description) || ""), el("td", { class: "muted small", style: { whiteSpace: "nowrap" } }, `${Math.round(e.chance * 100)}% ${t("perRun")}` + (e.personal ? ` · ${Math.round(e.personal.share * 100)}% ${t("ofPeople")}` : "")))))
        : el("p", { class: "muted" }, t("eventsNone")), write);
  };
  drawEvents(spec.events || []);
  const evolveErr = el("div", {});
  const evolveBtn = el("button", { class: "outline", disabled: !info.llm_live, onclick: async () => {
    if (thoughts.value.trim().length < 10) { thoughts.focus(); return; }
    evolveBtn.disabled = true; evolveBtn.textContent = t("drafting"); evolveErr.replaceChildren(); busy++;
    try {
      const res = await api.post(`/api/worlds/${id}/evolve`, { comment: thoughts.value, lang });
      busy = Math.max(0, busy - 1);
      carried = { hash: "#/", state: { scenario: res.scenario, reference: "", basedOn: res.based_on } };       // the top page shows it for a last look
      location.hash = "#/";
    } catch (e) { busy = Math.max(0, busy - 1); evolveBtn.disabled = false; evolveBtn.textContent = "✦ " + t("evolveGo"); evolveErr.replaceChildren(el("span", { class: "banner err" }, e.message)); }
  } }, "✦ " + t("evolveGo"));
  const evolveCard = el("div", { class: "card stack" }, el("h2", {}, t("evolveTitle")), thoughts,
    el("div", { class: "row" }, evolveBtn, el("span", { class: "muted small" }, info.llm_live ? t("evolveNote") : t("needKey"))), evolveErr);
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
      el("div", {}, el("label", {}, t("ai")), el("select", { onchange: (e) => { const v = e.target.value; cfg.ai = v === "mock" ? "mock" : "auto"; cfg.brain = v === "decision" ? "decision" : "chat"; estimate(); } },
        el("option", { value: "auto", selected: cfg.ai === "auto" && cfg.brain !== "decision", disabled: !info.llm_live }, t("aiLive")),
        el("option", { value: "decision", selected: cfg.ai === "auto" && cfg.brain === "decision", disabled: !info.llm_live }, t("aiDecision")),
        el("option", { value: "mock", selected: cfg.ai === "mock" }, t("aiMock")))),
      el("button", { class: "primary big", onclick: (e) => start(e.target) }, "▶ " + t("start"))),
    estLine, estMore, chanceLine,
    el("details", {}, paramSummary, el("p", { class: "muted small" }, t("sourcesNote")), paramForm(spec, values, { onChange: () => { refreshSummary(); estimate(); } })),
    el("details", {}, el("summary", {}, t("moreSettings")), el("div", { class: "params", style: { marginTop: "8px" } },
      el("div", {}, el("label", {}, t("runName")), nameIn),
      el("div", {}, el("label", {}, t("agentModel")), el("input", { type: "text", list: "model-list", placeholder: info.models.agent, value: cfg.agent_model || "", disabled: !info.llm_live,
        onchange: (e) => { cfg.agent_model = e.target.value.trim() || null; estimate(); } }), el("datalist", { id: "model-list" }, Object.keys(info.prices || {}).map((m) => el("option", { value: m })))),
      (spec.events || []).length ? el("div", {}, el("label", { title: t("chanceHelp") }, t("chance")), el("select", { title: t("chanceHelp"), onchange: (e) => { cfg.chance = e.target.value === "on"; showChance(); } },
        el("option", { value: "off" }, t("chanceOff")), el("option", { value: "on", selected: cfg.chance }, t("chanceOn")))) : "",
      el("div", {}, el("label", { title: t("gateHelp") }, t("gate")), el("select", { disabled: !info.llm_live, onchange: (e) => { cfg.gate = e.target.value; estimate(); } },
        el("option", { value: "off" }, t("gateOff")), el("option", { value: "judge", selected: cfg.gate === "judge" }, t("gateJudge")))),
      el("div", {}, el("label", { title: t("followHelp") }, t("follow")), num("follow_through", { min: 0, max: 1, step: 0.05, disabled: !info.llm_live })),
      el("div", {}, el("label", {}, t("budget")), num("budget_usd", { min: 0, step: "any", placeholder: "—" })),
      el("div", {}, el("label", {}, t("maxDecisions")), num("max_decisions_per_tick", { min: 0, max: 5000 })),
      el("div", {}, el("label", {}, t("seed")), num("seed", { min: 0 })))));
  refreshSummary(); estimate(); showChance();

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
      w.source !== "builtin" ? el("button", { class: "ghost danger", onclick: async () => { if (confirm(t("confirmDelete"))) { await api.del(`/api/worlds/${id}`); location.hash = "#/"; } } }, t("delete")) : null),
      el("p", { class: "muted", style: { maxWidth: "900px" } }, L(spec.summary)),
      spec.based_on ? el("p", { class: "muted small" }, `${t("basedOn")}: ${L(spec.based_on.title)}`) : null),
    el("div", { class: "two" },
      el("div", { class: "stack" }, setup,
        w.runs.length ? el("div", { class: "card stack" }, el("h2", {}, t("worldLines")), linesHost,
          el("details", {}, el("summary", {}, `${t("runsTitle")} (${w.runs.length})`), el("table", {}, runRows))) : null,
        evolveCard),
      el("div", { class: "stack" },
        el("div", { class: "card" }, el("h3", {}, t("questions")), bullets(spec.questions)),
        el("div", { class: "card" }, el("h3", {}, t("assumptions")), bullets(spec.assumptions)),
        el("div", { class: "card stack" },
          el("details", {}, el("summary", {}, `${t("residents")} (${spec.agents.length})`), el("table", {}, spec.agents.map((a) => el("tr", {}, el("td", { style: { fontWeight: 600 } }, L(a.name)), el("td", { class: "muted small" }, a.persona))))),
          el("details", {}, el("summary", {}, t("model")), el("pre", { class: "code" }, w.code)),
          spec.cast ? el("details", {}, el("summary", {}, `${t("cast")} (${spec.cast.size})`), el("pre", { class: "code" }, JSON.stringify(spec.cast, null, 1))) : null,
          eventsBox, checkBox,
          w.notes ? el("details", {}, el("summary", {}, t("research")), el("pre", { class: "code" }, w.notes)) : null,
          w.design_usage && w.design_usage.cost ? el("div", { class: "muted small" }, `${t("designCost")}: ${usd(w.design_usage.cost)}`) : null)))));
}

// ---------------------------------------------------------------- run
async function runPage(id) {
  const R = { id, rows: [], last: -1, cursor: 0, follow: true, events: [], lastEvent: 0, tab: "feed", filter: "all", compare: new Map(), colors: new Map(), chatKey: null, tableMode: new Set(), frame: null, alive: true };
  cleanup.push(() => { R.alive = false; });
  const k = kept();
  if (k) Object.assign(R, { tab: k.tab, filter: k.filter, nodeFilter: k.nodeFilter, chatKey: k.chatKey, tableMode: new Set(k.tableMode), colors: new Map(k.colors),
    view: k.view, keyFilter: k.keyFilter, optOrder: k.optOrder, colorBy: k.colorBy, catOrder: k.catOrder, ranges: k.ranges });
  keepState = () => ({ tab: R.tab, filter: R.filter, nodeFilter: R.nodeFilter, chatKey: R.chatKey, tableMode: [...R.tableMode], colors: [...R.colors],
    view: R.view, keyFilter: R.keyFilter, optOrder: R.optOrder, colorBy: R.colorBy, catOrder: R.catOrder, ranges: R.ranges,
    compare: [...R.compare.keys()], follow: R.follow, cursor: R.cursor });
  R.run = await api.get(`/api/runs/${id}`);
  const world = await api.get(`/api/worlds/${R.run.world_id}`);
  const spec = world.spec;
  const metric = Object.fromEntries(spec.metrics.map((m) => [m.id, m]));
  R.cast = spec.cast ? (await api.get(`/api/worlds/${world.id}/cast`).catch(() => ({ people: [] }))).people : [];
  R.view = R.view || (R.cast.length ? "people" : "places");       // a cast is shown as a board of people
  R.optOrder = R.optOrder || [];                                   // choices in the order first seen: a choice keeps its colour
  R.colorBy = R.colorBy || "answer";                               // "answer", or one variable of the automaton's state
  R.catOrder = R.catOrder || {}; R.ranges = R.ranges || {};        // per variable: values seen (words) or the range seen (numbers)
  R.cells = null;
  const agentName = (aid) => L((spec.agents.find((a) => a.id === aid) || {}).name) || aid;
  const who = (x) => x.name ? `${L(x.name)} · ${agentName(x.agent)}` : agentName(x.agent);     // own name first, then what kind of resident
  crumbs([{ text: L(spec.title), href: `#/world/${world.id}` }, { text: R.run.name }]);
  if (k) { for (const rid of k.compare) { const run = world.runs.find((r) => r.id === rid); if (run) R.compare.set(rid, { run, rows: [] }); } }
  else if (R.run.parent_run_id) R.compare.set(R.run.parent_run_id, { run: world.runs.find((r) => r.id === R.run.parent_run_id), rows: [] });
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
  $.charts = el("div", { class: "charts" }); $.compare = el("div", { class: "row" }); $.report = el("div", { class: "report" }); $.ask = el("div", { class: "stack", style: { marginTop: "12px" } });
  $.saveMd = el("a", { class: "btn", hidden: true, download: "", href: `/api/runs/${id}/report.md?lang=${lang}` }, t("saveMd")); $.err = el("div", {});
  $.lines = el("div", {});
  $.viewbar = el("div", { class: "viewbar" }); $.viewlegend = el("div", {}); $.viewnote = el("div", { class: "viewnote" });
  $.diagram = el("div", { class: "diagram", hidden: true }); $.diagramNote = el("div", { class: "viewnote", hidden: true }, t("diagramNote")); $.fit = el("div", {});
  R.trans = {};                                  // per state variable: the moves between its values, tick by tick
  const loadTrans = async (v) => {
    if (R.transLoading === v) return;
    R.transLoading = v;
    try { const res = await api.get(`/api/runs/${id}/transitions?var=${encodeURIComponent(v)}`); R.trans[v] = { ...res, upto: R.last }; } catch { R.trans[v] = { states: [], moves: [], upto: R.last }; }
    R.transLoading = null;
    if (R.alive && R.colorBy === v && R.view === "people") renderMap();
  };
  let replaying = false;
  const replay = async () => {                    // walk through the stored ticks again
    if (replaying) { replaying = false; return; }
    replaying = true; R.follow = false; $.follow.checked = false;
    for (let tk = R.cursor >= R.last ? 0 : R.cursor; tk <= R.last && replaying && R.alive; tk++) { await setCursor(tk); await new Promise((r) => setTimeout(r, 160)); }
    replaying = false; if (R.alive) renderMap();
  };
  cleanup.push(() => { replaying = false; });
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
    el("div", { class: "two" }, el("div", { class: "card" }, $.viewbar, $.viewlegend, $.map, $.viewnote, $.diagram, $.diagramNote), el("div", { class: "card" }, $.tabs, $.panel)),
    world.runs.length > 1 ? el("div", { class: "card stack" }, el("h2", { style: { margin: 0 } }, t("worldLines")), $.lines) : null,
    el("div", { class: "card stack" }, el("div", { class: "row" }, el("h2", { style: { margin: 0 } }, t("compare")), $.compare), $.fit, $.charts),
    el("div", { class: "card stack" }, el("div", { class: "row" }, el("h2", { style: { margin: 0 } }, t("report")),
      el("button", { onclick: (e) => writeReport(e.target) }, t("writeReport")), $.saveMd), $.report, $.ask)));

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
    try {
      const [frame, cells] = await Promise.all([api.get(`/api/runs/${id}/frame?tick=${R.cursor}`),
        R.cast.length && R.view === "people" ? api.get(`/api/runs/${id}/cells?tick=${R.cursor}`).catch(() => null) : null]);
      R.frame = frame; if (cells) R.cells = cells;
    } catch { return; }
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
    $.viewbar.replaceChildren(
      R.cast.length ? el("span", { class: "seg" }, ["people", "places"].map((v) => el("button", { class: R.view === v ? "on" : "", onclick: () => { R.view = v; setCursor(R.cursor); } }, t(v === "people" ? "viewPeople" : "viewPlaces")))) : "",
      R.view === "people" && R.cells?.vars.length ? el("select", { title: t("colorBy"), style: { fontSize: "12px", padding: "2px 6px" }, onchange: (e) => { R.colorBy = e.target.value; renderMap(); } },
        el("option", { value: "answer", selected: R.colorBy === "answer" }, `${t("colorBy")}: ${t("byAnswer")}`),
        R.cells.vars.map((v) => el("option", { value: v.id, selected: R.colorBy === v.id }, `${t("byState")}: ${v.id}`))) : "",
      el("span", { style: { flex: 1 } }),
      el("button", { class: "ghost", disabled: R.last < 1, onclick: replay }, replaying ? "■ " + t("stopReplay") : "▶ " + t("replay")));
    const byState = R.view === "people" && R.colorBy !== "answer" && R.cells?.cells[R.colorBy];
    $.viewnote.textContent = t(R.view === "people" && R.cast.length ? (byState ? "stateNote" : "gridNote") : "mapNote");
    if (R.view === "people" && R.cast.length) return renderPeople();
    $.viewlegend.replaceChildren(); $.diagram.hidden = true; $.diagramNote.hidden = true;
    if ($.map.__board) { $.map.__board = null; $.map.replaceChildren(); }
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

  function renderPeople() {
    // which square is whose: models key their people "something:<index in the cast>"
    const at = new Map();
    for (const p of R.frame.policies || []) { const i = Number(String(p.key).split(":").pop()); if (Number.isInteger(i) && i >= 0 && i < R.cast.length) at.set(i, p); }
    const labels = new Map(), habit = new Set();
    for (const p of at.values()) (p.options || []).forEach((o, j) => { labels.set(o.id, o.label); if (j === 0) habit.add(o.id); if (!R.optOrder.includes(o.id)) R.optOrder.push(o.id); });
    const others = R.optOrder.filter((o) => !habit.has(o));
    const colorOf = (cid) => habit.has(cid) ? "var(--axis)" : SERIES[others.indexOf(cid) % SERIES.length];
    const count = new Map();
    const chip = (color, text, hollow) => el("span", {}, el("i", { style: hollow ? { background: "var(--surface-1)", border: "1px solid var(--axis)" } : { background: color } }), text);
    const fmtV = (v) => typeof v === "number" ? (Number.isInteger(v) ? String(v) : v.toFixed(Math.abs(v) < 10 ? 2 : 1)) : String(v);
    const sv = R.colorBy !== "answer" && R.cells?.tick === R.cursor ? R.cells.cells[R.colorBy] : null;      // the automaton's own state
    let cells, legendRow, diagramOn = false;
    if (sv) {
      const kind = R.cells.vars.find((v) => v.id === R.colorBy)?.kind;
      if (kind === "num") {
        const rg = R.ranges[R.colorBy] = R.ranges[R.colorBy] || [Infinity, -Infinity];        // the range only widens, so a colour keeps its meaning over time
        for (const v of sv) { if (v < rg[0]) rg[0] = v; if (v > rg[1]) rg[1] = v; }
        const step = (v) => 1 + Math.min(5, Math.floor((rg[1] > rg[0] ? (v - rg[0]) / (rg[1] - rg[0]) : 0) * 6));
        cells = sv.map((v, i) => ({ color: `var(--seq-${step(v)})`, fresh: at.get(i)?.tick === R.cursor, meant: false }));
        legendRow = el("div", { class: "legend", style: { marginBottom: "6px", alignItems: "center" } }, el("b", {}, R.colorBy), el("span", {}, fmtV(rg[0])),
          el("span", {}, [1, 2, 3, 4, 5, 6].map((n) => el("i", { style: { background: `var(--seq-${n})`, marginRight: "2px" } }))), el("span", {}, fmtV(rg[1])));
      } else {
        const order = R.catOrder[R.colorBy] = R.catOrder[R.colorBy] || [];
        for (const v of sv) { const s2 = String(v); if (!order.includes(s2)) order.push(s2); count.set(s2, (count.get(s2) || 0) + 1); }
        const col = (s2) => order.indexOf(s2) === 0 ? "var(--axis)" : SERIES[(order.indexOf(s2) - 1) % SERIES.length];
        cells = sv.map((v, i) => ({ color: col(String(v)), fresh: at.get(i)?.tick === R.cursor, meant: false }));
        legendRow = el("div", { class: "legend", style: { marginBottom: "6px" } }, el("b", {}, R.colorBy), order.map((s2) => chip(col(s2), `${s2} ${count.get(s2) || 0}`)));
        // the same variable as a state diagram: who moved from which state to which, up to the tick on screen
        const tr = R.trans[R.colorBy];
        if (!tr || tr.upto < R.last - (R.status === "running" ? 4 : 0)) loadTrans(R.colorBy);
        if (tr && tr.states.length > 1) {
          for (const s2 of tr.states) if (!order.includes(s2)) order.push(s2);
          const flow = new Map();
          for (const [tk, i, j, c] of tr.moves) if (tk <= R.cursor) flow.set(i + ":" + j, (flow.get(i + ":" + j) || 0) + c);
          stateDiagram($.diagram, { states: tr.states, colors: tr.states.map(col), now: tr.states.map((s2) => count.get(s2) || 0),
            flows: [...flow].map(([k2, c]) => [...k2.split(":").map(Number), c]), label: (s2) => s2 });
          diagramOn = true;
        }
      }
    } else {
      cells = R.cast.map((person, i) => {
        const p = at.get(i), cid = p?.action?.choice;
        const key = p && cid != null ? cid : "";
        count.set(key, (count.get(key) || 0) + 1);
        return { color: key ? colorOf(key) : null, fresh: !!p && p.tick === R.cursor, meant: !!p?.meant };
      });
      legendRow = el("div", { class: "legend", style: { marginBottom: "6px" } },
        R.optOrder.filter((o) => labels.has(o)).sort((a, b) => habit.has(b) - habit.has(a)).map((o) => chip(colorOf(o), `${L(labels.get(o))} ${count.get(o) || 0}`)),
        count.get("") ? chip(null, `${t("notAsked")} ${count.get("")}`, true) : null);
    }
    $.diagram.hidden = !diagramOn; $.diagramNote.hidden = !diagramOn;
    const stateOf = (i) => R.cells?.tick === R.cursor ? R.cells.vars.map((v) => `${esc(v.id)} ${esc(fmtV(R.cells.cells[v.id][i]))}`).join(" · ") : "";
    $.viewlegend.replaceChildren(legendRow);
    peopleGrid($.map, { cells,
      tipOf: (i) => {
        const p = at.get(i), person = R.cast[i];
        const o = p && (p.options || []).find((x) => x.id === p.action?.choice);
        return `<b>${esc(L(person.name) || "")}</b><br>` + (p ? `${esc(o ? L(o.label) : String(p.action?.choice ?? ""))} <span class="muted">(${esc(clockOf(p.tick))} ${esc(t("since"))})</span>`
          + (p.meant ? `<br>${esc(t("meant"))}: ${esc(L(p.meant))}` : "") + (p.say ? `<br>“${esc(L(p.say))}”` : "") : esc(t("notAsked")))
          + (sv ? `<br><span class="muted">${stateOf(i)}</span>`
            : person.about ? `<br><span class="muted">${esc(person.about.slice(0, 150))}${person.about.length > 150 ? "…" : ""}</span>` : "");
      },
      onPick: (i) => { const p = at.get(i); R.pick = { i, key: p?.key || null }; R.tab = "residents"; R.nodeFilter = null; renderPanel(); } });
  }

  const TABS = ["feed", "residents", "intervene", "chat", "facts"];
  function renderPanel() {
    $.tabs.replaceChildren(...TABS.map((k) => el("button", { class: R.tab === k ? "on" : "", onclick: () => { R.tab = k; R.pick = null; if (k !== "residents") R.nodeFilter = null; renderPanel(); } }, t(k))));
    ({ feed: panelFeed, residents: panelResidents, intervene: panelIntervene, chat: panelChat, facts: panelFacts })[R.tab]();
  }

  function panelFeed() {
    const chips = el("div", { class: "row", style: { marginBottom: "6px" } }, ["all", "events", "voices"].map((k) => el("button", { class: "ghost" + (R.filter === k ? " on" : ""), style: R.filter === k ? { color: "var(--text-primary)", fontWeight: 600 } : {}, onclick: () => { R.filter = k; renderPanel(); } }, t(k))));
    const items = R.events.filter((e) => e.tick <= R.cursor && (R.filter === "all" || (R.filter === "voices") === (e.kind === "say"))).slice(-160).reverse();
    $.panel.replaceChildren(chips, ...(items.length ? items.map((e) => {
      const when = el("div", { class: "when" }, clockOf(e.tick));
      if (e.kind === "say") return el("div", { class: "feed-item" }, when, el("div", {}, el("div", { class: "who" }, who(e), e.node ? el("span", { class: "muted", style: { fontWeight: 400 } }, " · " + nodeLabel(e.node)) : null),
        el("div", {}, "“" + L(e.payload.text) + "”"), el("div", { class: "sum" }, L(e.payload.summary) + (e.payload.meant ? ` (${t("meant")}: ${L(e.payload.meant)})` : ""))));
      return el("div", { class: "feed-item" }, when, el("div", {}, el("span", { class: "kind " + e.kind }, e.kind), L(e.payload.text)));
    }) : [el("p", { class: "muted" }, t("noEvents"))]));
  }
  const nodeLabel = (nid) => { const n = (R.frame?.view?.nodes || []).find((x) => x.id === nid); return n ? L(n.label) : nid; };
  const srcLabel = (s) => t("src" + s[0].toUpperCase() + s.slice(1)) || s;

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
    if (p.meant) kids.push(el("div", { class: "muted small" }, `${t("meant")}: ${L(p.meant)}`));
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
  // Step in on one resident at the tick on screen: say something to them, or decide for them. Always as a fork.
  function nudgeForm(person, p) {
    const tell = el("input", { type: "text", placeholder: t("tellPh"), style: { flex: 1 } });
    const pick = el("select", {}, el("option", { value: "" }, t("forceNone")), (p.options || []).map((o) => el("option", { value: o.id }, L(o.label))));
    const err = el("div", {});
    const go = el("button", { class: "outline", onclick: async () => {
      if (!tell.value.trim() && !pick.value) { tell.focus(); return; }
      go.disabled = true;
      try {
        const nr = await api.post(`/api/runs/${id}/fork`, { tick: R.cursor, name: t("nudgedName").replace("{n}", L(person.name) || p.key), start: true,
          person: { key: p.key, tell: tell.value, choice: pick.value || null } });
        location.hash = `#/run/${nr.id}`;
      } catch (e) { go.disabled = false; err.replaceChildren(el("span", { class: "banner err" }, e.message)); }
    } }, "⑂ " + t("nudgeGo"));
    return el("div", { class: "stack", style: { marginTop: "10px", paddingTop: "10px", borderTop: "1px solid var(--grid)" } },
      el("div", { class: "name", style: { fontWeight: 600 } }, `${t("nudgeTitle")} · ${clockOf(R.cursor)}`),
      el("div", { class: "row" }, tell), el("div", { class: "row" }, pick, go), el("div", { class: "muted small" }, t("nudgeNote")), err);
  }

  function panelResidents() {
    const allPs = R.frame?.policies || [];
    const kinds = [...new Set(allPs.map((p) => p.agent))];
    if (R.agentFilter && !kinds.includes(R.agentFilter)) R.agentFilter = null;
    if (R.pick) {                                  // one square of the board was clicked: show that person
      const person = R.cast[R.pick.i] || {}, mine = allPs.filter((p) => p.key === R.pick.key);
      $.panel.replaceChildren(el("div", { class: "row" }, el("span", { class: "tag" }, L(person.name) || ""), el("button", { class: "ghost", onclick: () => { R.pick = null; renderPanel(); } }, "×")),
        person.about ? el("p", { class: "muted small" }, person.about) : "",
        ...(mine.length ? mine.map((p) => policyBlock(p)) : [el("p", { class: "muted" }, t("notAsked"))]),
        mine.length ? nudgeForm(person, mine[0]) : "");
      return;
    }
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
      el("p", { class: "muted small", style: { margin: 0 } }, t("chatNote")),
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

  // Where the world carries recorded figures (metrics named real_...), how close each run on screen comes to them.
  const realPairs = (() => {
    const ids = new Set(spec.metrics.map((m) => m.id)), out = [];
    for (const m of spec.metrics) {
      if (!m.id.startsWith("real_")) continue;
      const chart = (spec.charts || []).find((c) => c.metrics.includes(m.id));
      const sim = ids.has(m.id.slice(5)) ? m.id.slice(5) : chart?.metrics.find((x) => !x.startsWith("real_") && (!ids.has("real_" + x)));
      if (sim) out.push([sim, m.id]);
    }
    return out;
  })();
  function renderFit() {
    if (!realPairs.length) { $.fit.replaceChildren(); return; }
    const stat = (rows, sim, real) => {
      const pts = rows.filter((r) => r.tick > 0 && Number.isFinite(r.metrics[sim]) && Number.isFinite(r.metrics[real]));
      if (pts.length < 3) return null;
      const a = pts.map((r) => r.metrics[sim]), b = pts.map((r) => r.metrics[real]), n = a.length;
      const ma = a.reduce((x, y) => x + y, 0) / n, mb = b.reduce((x, y) => x + y, 0) / n;
      let cov = 0, va = 0, vb = 0, gap = 0;
      for (let i = 0; i < n; i++) { cov += (a[i] - ma) * (b[i] - mb); va += (a[i] - ma) ** 2; vb += (b[i] - mb) ** 2; gap += Math.abs(a[i] - b[i]); }
      const peak = (v) => pts[v.indexOf(Math.max(...v))].tick;
      const spiky = Math.max(...b) > 1.25 * [...b].sort((x, y) => x - y)[Math.floor(n / 2)];      // a peak is only worth timing when the record has one
      return { gap: gap / n, corr: va && vb ? cov / Math.sqrt(va * vb) : null, peak: spiky ? peak(a) - peak(b) : null };
    };
    const runs = [{ name: R.run.name, color: colorOf(id), rows: R.rows }, ...[...R.compare].map(([rid, c]) => ({ name: c.run.name, color: colorOf(rid), rows: c.rows }))];
    const body = [];
    for (const [sim, real] of realPairs) for (const r of runs) {
      const s = stat(r.rows, sim, real);
      if (!s) continue;
      body.push(el("tr", {}, el("td", {}, el("i", { style: { display: "inline-block", width: "9px", height: "9px", borderRadius: "2px", background: r.color, marginRight: "6px" } }), r.name),
        el("td", { class: "muted" }, L(metric[sim].label)), el("td", { class: "num" }, `${t("fitErr")} ${fmt(s.gap, "float")}`),
        el("td", { class: "num" }, s.corr === null ? "" : `${t("fitCorr")} ${s.corr.toFixed(2)}`),
        el("td", { class: "num muted" }, s.peak === null ? "" : `${t("fitPeak")} ${s.peak === 0 ? t("fitSame") : (s.peak > 0 ? "+" : "") + s.peak + " " + t("fitTicks")}`)));
    }
    $.fit.replaceChildren(body.length ? el("details", { open: true }, el("summary", { class: "small" }, t("fitTitle")), el("table", { class: "fit" }, body)) : "");
  }

  function renderCharts() {
    renderFit();
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
    try { const rep = await api.post(`/api/runs/${id}/report`, { compare: [...R.compare.keys()], lang }); showReport(rep); }
    catch (e) { $.report.replaceChildren(el("div", { class: "banner err" }, e.message)); }
    btn.disabled = false; btn.textContent = t("writeReport");
  }
  // questions to the analyst about this run and its report; the conversation is kept with the run
  async function setupAsk() {
    const logEl = el("div", { class: "chat" });
    const input = el("input", { type: "text", placeholder: t("askPh"), style: { flex: 1 }, disabled: !info.llm_live });
    const say = (m) => el("div", { class: "msg" + (m.role === "user" ? " user" : " answer"), ...(m.role === "user" ? {} : { html: md(m.text) }) }, m.role === "user" ? m.text : null);
    const send = async () => {
      const text = input.value.trim();
      if (!text) return;
      input.value = ""; logEl.append(say({ role: "user", text }));
      const wait = el("div", { class: "msg muted" }, "…"); logEl.append(wait);
      try { const res = await api.post(`/api/runs/${id}/ask`, { text, lang, compare: [...R.compare.keys()] }); wait.replaceWith(say({ role: "analyst", text: res.reply })); }
      catch (e) { wait.textContent = e.message; }
    };
    input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.isComposing) send(); });
    $.ask.replaceChildren(logEl, el("div", { class: "row" }, input, el("button", { onclick: send, disabled: !info.llm_live }, t("ask"))));
    try { logEl.replaceChildren(...(await api.get(`/api/runs/${id}/ask`)).map(say)); } catch { /* no history yet */ }
  }

  function showReport(rep) {
    $.saveMd.hidden = !(rep && rep.body);
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
  setupAsk();
  const wantTick = new URLSearchParams(location.hash.split("?")[1] || "").get("tick");   // #/run/3?tick=12 opens at that tick
  const stay = k && !k.follow;                     // the observer was looking at an earlier tick
  if (wantTick !== null || stay) { R.follow = false; $.follow.checked = false; }
  await poll();
  if (stay) await setCursor(k.cursor);
  else if (wantTick !== null) await setCursor(Number(wantTick));
  else if (R.frame === null) await setCursor(R.last);
  window.addEventListener("resize", renderCharts);
  cleanup.push(() => window.removeEventListener("resize", renderCharts));
}

// ---------------------------------------------------------------- router
async function route() {
  cleanup.forEach((f) => f()); cleanup = [];
  keepState = null;
  lastHash = location.hash;
  document.getElementById("tooltip").hidden = true;
  try {
    info = info || await api.get("/api/info");
    chrome();
    const m = location.hash.match(/^#\/(world|run)\/(\d+)/);
    document.getElementById("nav-history").textContent = t("history");
    document.getElementById("nav-data").textContent = t("data");
    if (location.hash.startsWith("#/history")) await historyPage();
    else if (!m) await home();
    else if (m[1] === "world") await worldPage(Number(m[2]));
    else await runPage(Number(m[2]));
  } catch (e) {
    app.replaceChildren(el("div", { class: "banner err" }, e.message));
  }
  carried = null;
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

// UI strings. English is the default; Japanese is selectable (top right, or ?lang=ja).
const S = {
  en: {
    data: "Data", dataExport: "Export SQLite", dataImport: "Import SQLite", dataFile: "SQLite backup file",
    dataExportHelp: "Download one file with worlds, runs, reports, and model settings.",
    dataImportHelp: "Import replaces all current Hakoniwa data. Export a backup first if you want to keep it.",
    dataConfirm: "Replace all current Hakoniwa data with this backup?",
    dataPause: "Pause active runs and wait for ongoing work to finish before transferring data.",
    dataWorking: "Transferring…", dataImported: "Backup restored.", worldReportDownload: "Download report (.md)",
    draft: "Draft with AI", drafting: "Thinking…", draftHelp: "Type a rough idea (or nothing), and AI writes it up as a scenario.",
    modelsTitle: "Models", per1m: "USD per 1M tokens, in / out", effort: "Effort", save: "Save", resetEnv: "Back to .env",
    roleDesigner: "World design", roleDesignerHelp: "Turns a scenario into a world. One large call.", roleAgent: "Residents", roleAgentHelp: "Decisions and speech during a run. Many small calls.",
    roleReport: "Report", roleReportHelp: "The written summary of a run.",
    worldLines: "World lines", draftEmptyTitle: "The box is empty", draftEmptyBody: "A rough idea is enough: AI will shape it into a scenario. With nothing written, AI picks the whole subject itself. Is that OK?",
    draftEmptyBack: "I'll write something", draftEmptyGo: "Let AI decide",
    leaveTitle: "AI is still working", leaveBody: "If you leave this page now, the work in progress may be lost.", leaveStay: "Stay here", leaveGo: "Leave anyway",
    heroA: "Build a world.", heroB: "Watch it run.", heroSub: "Describe a situation. AI builds the math model and the residents.", example: "Example",
    step1: "Open a world.", step2: "Start a run and watch.", step3: "Trigger an event or fork, then compare the branches.",
    designHint: "about 6 min, about $0.3", start: "Start", about: "About", estByModel: "Cost by model", moreSettings: "More settings",
    noEvent: "No event (just branch)", forkTitle: "Fork", forkHelp: "This run stays as it is. A new branch starts from this point and runs on.", forkEvent: "Event at the fork", cancel: "Cancel", fork: "Fork",
    applyHint: "Apply changes this run from the next tick. Fork keeps this run and starts a branch you can compare.",
    ticksWord: "ticks", history: "History", date: "Started", world: "World", result: "Result at the last tick", allWorlds: "All worlds", noRuns: "No runs yet.",
    worlds: "Worlds", sample: "Sample", generated: "Made by AI", open: "Open", runs: "runs",
    tagline: "Worlds that run on equations. AI plays the residents.",
    newWorld: "New world from a scenario",
    newWorldHelp: "Describe a situation. AI writes the parameters, the residents and the math model, then tests them in a sandbox.",
    examples: "Try:", design: "Create", designing: "Creating…",
    needKey: "No API key yet. Put OPENAI_API_KEY in .env to create worlds. Existing worlds still run without AI.",
    scenarioPh: "A town of 3,000 people. A large supermarket opens next to the old shopping street…",
    questions: "Things to find out", assumptions: "Assumptions", parameters: "Parameters", runSetup: "Run setup",
    ticks: "Length", seed: "Random seed", ai: "Residents", aiLive: "AI residents", aiMock: "No AI (model defaults)",
    agentModel: "Model for residents", maxDecisions: "Max questions per tick", budget: "Stop at (USD)", speed: "Speed",
    estimate: "Estimate cost", estimating: "Estimating…", startRun: "Start a run", runName: "Run name",
    estCalls: "questions to residents", estLikely: "Likely", estLow: "Low", estHigh: "High", estModel: "Model", estOut: "Output tokens per answer",
    estObserved: "measured", estAssumed: "assumed", estReport: "Report at the end", estUnknown: "price unknown",
    estNote: "Counted by rehearsing the model without AI. Real residents change the course of a run, so expect the low–high range.",
    estMock: "No AI, no cost. Residents follow the model's defaults.",
    runsTitle: "Runs", name: "Name", status: "Status", progress: "Progress", cost: "AI cost", forkOf: "fork of", at: "at",
    delete: "Delete", confirmDelete: "Delete this? This cannot be undone.", model: "Math model (Python)", research: "Research notes",
    source: "Source", assumed: "assumed", designCost: "Design cost",
    play: "Run", pause: "Pause", step: "One tick", live: "Follow", tick: "Tick", of: "of",
    forkHere: "Fork here", report: "Report", writeReport: "Write report", writing: "Writing…", compare: "Compare with",
    map: "World", feed: "Feed", residents: "Residents", facts: "Facts", intervene: "Intervene", chat: "Interview",
    all: "All", voices: "Voices", events: "Events", noEvents: "Nothing yet. Press Run.",
    asked: "asked", thought: "Thought", history: "History", interview: "Interview", population: "people",
    srcLlm: "AI", srcMock: "default", srcDefault: "default (over limit)", srcFallback: "default (AI error)", srcInherited: "inherited",
    presets: "Events", applyNow: "Apply to this run", forkApply: "Fork and apply", changeParams: "Change parameters", apply: "Apply",
    freeText: "Describe an event in your own words", interpret: "Translate to changes", proposed: "Proposed changes", nothingToChange: "No change could be made from that text.",
    queued: "Queued. It takes effect on the next tick.", subject: "Subject", predicate: "What", value: "Value", since: "Since",
    chooseResident: "Choose a resident", say: "Ask something…", send: "Send", noResidents: "No resident has decided anything yet.",
    table: "Table", chartView: "Chart", vsStart: "vs start", vs: "vs", statusCreated: "ready", statusRunning: "running", statusPaused: "paused",
    statusFinished: "finished", statusFailed: "failed", calls: "calls", noAI: "No AI", sandbox: "sandbox",
    reportEmpty: "No report yet.", reportSrcTemplate: "Numbers only (no AI).", back: "Back to world", extend: "Extend",
    failed: "The run stopped with an error", forkName: "Name of the new branch", branchOf: "Branch of",
    slow: "Slow", normal: "Normal", fast: "Fast", max: "Max", none: "none", changed: "changed", sourcesNote: "△ = assumption, not a measured number",
  },
  ja: {
    data: "データ", dataExport: "SQLite を書き出す", dataImport: "SQLite を取り込む", dataFile: "SQLite バックアップファイル",
    dataExportHelp: "世界、実行履歴、レポート、モデル設定を1つのファイルに保存します。",
    dataImportHelp: "取り込むと現在の Hakoniwa データがすべて置き換わります。残しておくには、先に書き出してください。",
    dataConfirm: "現在の Hakoniwa データをすべて、このバックアップで置き換えますか？",
    dataPause: "実行を一時停止し、進行中の処理が終わってから操作してください。",
    dataWorking: "処理中…", dataImported: "バックアップを取り込みました。", worldReportDownload: "レポートをダウンロード（.md）",
    draft: "AI でシナリオを考える", drafting: "考え中…", draftHelp: "ざっくりした要望を書くと（空でも可）、AI がシナリオの文章に整えます。",
    modelsTitle: "モデル", per1m: "100 万トークンあたり USD（入力 / 出力）", effort: "考える深さ", save: "保存", resetEnv: ".env の設定に戻す",
    roleDesigner: "世界の設計", roleDesignerHelp: "シナリオから世界を作る。大きな呼び出しが 1 回。", roleAgent: "住人", roleAgentHelp: "実行中の判断と発言。小さな呼び出しが多数。",
    roleReport: "レポート", roleReportHelp: "実行のまとめの文章。",
    worldLines: "世界線", draftEmptyTitle: "入力が空です", draftEmptyBody: "ラフな案でも書いてもらえれば、それを元に整えます。空のままだと、題材から全部 AI が考えます。それで大丈夫ですか？",
    draftEmptyBack: "戻って書く", draftEmptyGo: "AI に任せる",
    leaveTitle: "AI が作業中です", leaveBody: "今このページを離れると、今行っている作業が失われてしまうかもしれません。", leaveStay: "このまま待つ", leaveGo: "それでも離れる",
    heroA: "世界を作って、", heroB: "動かす。", heroSub: "状況を書くと、AI が数理モデルと住人を作ります。", example: "例を入れる",
    step1: "世界を開く。", step2: "実行を始めて、眺める。", step3: "事件を起こすか分岐して、結果を比べる。",
    designHint: "約 6 分・約 $0.3", start: "始める", about: "約", estByModel: "モデルごとの費用", moreSettings: "その他の設定",
    noEvent: "事件なし（分岐だけ）", forkTitle: "分岐", forkHelp: "この実行はそのまま残ります。ここから新しい分岐が始まり、先へ進みます。", forkEvent: "分岐と同時に起こす事件", cancel: "やめる", fork: "分岐する",
    applyHint: "「適用」は、この実行を次のティックから変えます。「分岐」は、この実行を残して、比べられる分岐を作ります。",
    ticksWord: "ティック", history: "履歴", date: "開始", world: "世界", result: "最後のティックの結果", allWorlds: "すべての世界", noRuns: "まだ実行がありません。",
    worlds: "世界", sample: "サンプル", generated: "AI が作成", open: "開く", runs: "回の実行",
    tagline: "数式で動く世界。住人は AI が演じます。",
    newWorld: "シナリオから新しい世界を作る",
    newWorldHelp: "状況を文章で書くと、AI がパラメータ・住人・数理モデルを作り、サンドボックスで試運転します。",
    examples: "例：", design: "作る", designing: "作成中…",
    needKey: "API キーが未設定です。世界を作るには .env に OPENAI_API_KEY を入れてください。既存の世界は AI なしで動きます。",
    scenarioPh: "人口 3,000 人の町。古い商店街の隣に大きなスーパーが開店する…",
    questions: "確かめたいこと", assumptions: "前提", parameters: "パラメータ", runSetup: "実行の設定",
    ticks: "長さ", seed: "乱数の種", ai: "住人", aiLive: "AI の住人", aiMock: "AI なし（モデルの既定の動き）",
    agentModel: "住人に使うモデル", maxDecisions: "1 ティックの質問数の上限", budget: "この金額で止める（USD）", speed: "速さ",
    estimate: "費用を見積もる", estimating: "見積もり中…", startRun: "実行を始める", runName: "実行の名前",
    estCalls: "回の質問", estLikely: "見込み", estLow: "低め", estHigh: "高め", estModel: "モデル", estOut: "1 回の回答の出力トークン",
    estObserved: "実測", estAssumed: "仮定", estReport: "最後のレポート", estUnknown: "料金が未登録",
    estNote: "AI なしでモデルを空回しして数えています。本物の住人は展開を変えるので、低め〜高めの幅で見てください。",
    estMock: "AI なし。費用はかかりません。住人はモデルの既定の動きをします。",
    runsTitle: "実行の一覧", name: "名前", status: "状態", progress: "進み具合", cost: "AI の費用", forkOf: "分岐元", at: "時点",
    delete: "削除", confirmDelete: "削除しますか？元に戻せません。", model: "数理モデル（Python）", research: "調査メモ",
    source: "出典", assumed: "仮定", designCost: "設計の費用",
    play: "進める", pause: "止める", step: "1 ティック", live: "最新を追う", tick: "ティック", of: "/",
    forkHere: "ここで分岐", report: "レポート", writeReport: "レポートを書く", writing: "作成中…", compare: "比べる相手",
    map: "世界", feed: "できごと", residents: "住人", facts: "事実", intervene: "介入", chat: "インタビュー",
    all: "すべて", voices: "声", events: "できごと", noEvents: "まだ何も起きていません。「進める」を押してください。",
    asked: "に質問", thought: "考え", history: "履歴", interview: "話を聞く", population: "人",
    srcLlm: "AI", srcMock: "既定", srcDefault: "既定（上限超え）", srcFallback: "既定（AI エラー）", srcInherited: "引き継ぎ",
    presets: "事件", applyNow: "この実行に適用", forkApply: "分岐して適用", changeParams: "パラメータを変える", apply: "適用",
    freeText: "事件を自分の言葉で書く", interpret: "変更に変換する", proposed: "変更の案", nothingToChange: "その文章からは変更を作れませんでした。",
    queued: "受け付けました。次のティックから効きます。", subject: "対象", predicate: "項目", value: "値", since: "いつから",
    chooseResident: "住人を選ぶ", say: "質問を書く…", send: "送る", noResidents: "まだ誰も判断していません。",
    table: "表", chartView: "グラフ", vsStart: "開始との差", vs: "との差", statusCreated: "準備完了", statusRunning: "実行中", statusPaused: "一時停止",
    statusFinished: "完了", statusFailed: "失敗", calls: "回", noAI: "AI なし", sandbox: "サンドボックス",
    reportEmpty: "レポートはまだありません。", reportSrcTemplate: "数字だけの要約です（AI なし）。", back: "世界に戻る", extend: "延長",
    failed: "エラーで止まりました", forkName: "新しい分岐の名前", branchOf: "分岐元：",
    slow: "ゆっくり", normal: "ふつう", fast: "速い", max: "最速", none: "なし", changed: "変更あり", sourcesNote: "△ = 仮定の値（実測ではない）",
  },
};

const qs = new URLSearchParams(location.search);
export let lang = qs.get("lang") || localStorage.getItem("hakoniwa.lang") || "en";
if (!S[lang]) lang = "en";

export function setLang(l) {
  lang = S[l] ? l : "en";
  localStorage.setItem("hakoniwa.lang", lang);
  document.documentElement.lang = lang;
}
export const t = (k) => S[lang][k] ?? S.en[k] ?? k;
// pick a language from a {en, ja} object coming from a world
export const L = (v) => (v && typeof v === "object") ? (v[lang] ?? v.en ?? Object.values(v)[0] ?? "") : (v ?? "");

export function fmt(v, format, unitIn) {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  const unit = L(unitIn);       // a unit may be plain text or {en, ja}
  const loc = lang === "ja" ? "ja-JP" : "en-US";
  if (format === "pct") return v.toLocaleString(loc, { maximumFractionDigits: 1 }) + "%";
  if (format === "money") return money(v, unit);
  if (format === "int") return Math.round(v).toLocaleString(loc);
  const a = Math.abs(v);
  return v.toLocaleString(loc, { maximumFractionDigits: a >= 100 ? 0 : a >= 10 ? 1 : 2 }) + (unit && unit !== "%" && unit.length <= 6 ? " " + unit : "");
}
export function money(v, unit) {
  const cur = unit === "USD" ? "$" : "¥";
  const a = Math.abs(v), sign = v < 0 ? "−" : "";
  if (lang === "ja" && cur === "¥") {
    if (a >= 1e8) return sign + (a / 1e8).toLocaleString("ja-JP", { maximumFractionDigits: 2 }) + "億円";
    if (a >= 1e4) return sign + Math.round(a / 1e4).toLocaleString("ja-JP") + "万円";
    return sign + Math.round(a).toLocaleString("ja-JP") + "円";
  }
  if (a >= 1e9) return sign + cur + (a / 1e9).toFixed(2) + "B";
  if (a >= 1e6) return sign + cur + (a / 1e6).toFixed(a >= 1e8 ? 0 : 1) + "M";
  if (a >= 1e4) return sign + cur + Math.round(a / 1e3) + "K";
  return sign + cur + Math.round(a).toLocaleString("en-US");
}
export function compact(v) {
  const a = Math.abs(v);
  if (a >= 1e9) return (v / 1e9).toFixed(1).replace(/\.0$/, "") + "B";
  if (a >= 1e6) return (v / 1e6).toFixed(1).replace(/\.0$/, "") + "M";
  if (a >= 1e4) return (v / 1e3).toFixed(0) + "K";
  return v.toLocaleString("en-US", { maximumFractionDigits: a < 10 ? 1 : 0 });
}
export const usd = (v) => (v === null || v === undefined) ? t("estUnknown") : "$" + (v < 0.01 ? v.toFixed(4) : v < 1 ? v.toFixed(3) : v.toFixed(2));

// UI strings. English is the default; Japanese is selectable (top right, or ?lang=ja).
const S = {
  en: {
    draft: "Draft with AI", drafting: "Thinking…", draftHelp: "Type a rough idea (or nothing), and AI writes it up as a scenario.",
    modelsTitle: "Models", per1m: "USD per 1M tokens, in / out", effort: "Effort", save: "Save", resetEnv: "Back to .env",
    roleDesigner: "World building", roleDesignerHelp: "Builds the rules and the cast from a scenario. A few large calls.", roleDraft: "Scenario help", roleDraftHelp: "Turns a rough idea into a scenario.", roleAgent: "Residents", roleAgentHelp: "Decisions and speech during a run. Many small calls.",
    roleReport: "Report", roleReportHelp: "The written summary of a run.",
    worldLines: "World lines", draftEmptyTitle: "The box is empty", draftEmptyBody: "A rough idea is enough: AI will shape it into a scenario. With nothing written, AI picks the whole subject itself. Is that OK?",
    draftEmptyBack: "I'll write something", draftEmptyGo: "Let AI decide",
    leaveTitle: "AI is still working", leaveBody: "If you leave this page now, the work in progress may be lost.", leaveStay: "Stay here", leaveGo: "Leave anyway",
    aiDecision: "AI, decisions only (fast, cheap, no speech)", srcDecision: "AI (decision)", srcHabit: "habit (did not stop to think)",
    colorBy: "Colour", byAnswer: "Last answer", byState: "State", stateNote: "One square = one resident. Colour = the value the model holds for that person at this tick. Hover for all of their values.",
    chatNote: "Talking does not change what they do. To change the world, use Intervene.",
    buildingTag: "building", failedTag: "did not build", buildFailed: "This world could not be built.", buildAgain: "Change the scenario and try again", buildStop: "Stop and remove",
    buildLeave: "You can leave this page: building goes on, and the world is in the list on the top page.", scenario: "Scenario",
    buildA: "Building", buildB: "your box garden.", stepSurvey: "Survey the land", stepRules: "Lay down the rules", stepTrial: "Trial run", stepPeople: "People move in", buildDetail: "Details",
    askPh: "Ask about this run or the report…", ask: "Ask", saveMd: "Save as Markdown",
    whatIsThis: "What this does", modeAsk: "What would you like to do?", modeSociety: "Society", modeLife: "Myself",
    lifeA: "Explore", lifeB: "your futures.", lifeSub: "Say where you are and what you are weighing. AI interviews you, builds you and the people around you, and runs several futures of each path.",
    lifePh: "I'm 32, a backend engineer, five years at the same company. A friend's startup has offered me a job…", lifeStart: "Start the interview",
    lifePrivacy: "What you write is sent to the AI provider you configured.",
    lifeInterview: "Tell me about you", lifeInterviewBody: "The world is only as good as the picture of you. Pick an answer or use your own words; leave blank what you would rather not say.",
    lifeInterviewGo: "Go on", lifeComposing: "Putting it together…", lifeReady: "Read it, change what is off, then create.", lifeWho: "About", lifePaths: "Paths",
    lifeTag: "crossroads", lifeMake: "Make futures", lifePer: "Futures per path", lifeMakeHelp: "Every path gets the same strokes of luck: future 2 of one path and future 2 of another meet the same outside events.",
    lifeNone: "No futures yet. Make some, and each path is lived a few times over.", lifeTalk: "Ask this future self", lifeDetail: "Open", lifeLastWords: "At the end",
    lifeReport: "Across all futures", lifeWrite: "Write the report", lifeProfile: "Who this is about", lifeInside: "Inside this world (rules, people, settings)",
    lifeNot: "Not a forecast and not advice: futures that could be.", lifeTalkTitle: "A future self", lifeRunning: "living…", lifeOthers: "Around them",
    close: "Close", data: "Data", dataExport: "Take out", dataImport: "Bring in", dataPick: "Choose the worlds and runs to save as one SQLite file. A branch brings the run it came from.",
    dataGz: "Compress (.gz)", dataGo: "Save as SQLite", dataAll: "All", dataNone: "None", dataChosen: "chosen",
    dataImportHelp: "Adds the worlds and runs of a saved file to what is here. Nothing here is replaced.", dataImportGo: "Bring in",
    dataDone: "Added {w} world(s) and {r} run(s).", dataMatched: "{m} world(s) were already here.", dataSkipped: "Left out",
    dataKept: "A whole copy is kept in", dataKeptEvery: "every {n} min when something changed", dataKeptLast: "last copy", dataKeepNow: "Copy now", dataKeepNever: "no copy yet",
    dataWhy: "The database is one file on this machine. Where the machine does not keep its files (a hosted demo), save what you want to keep before it restarts.",
    diagramNote: "Circle = how many are in that state now. Arrow = how many have moved that way so far.",
    fitTitle: "Against the record", fitErr: "mean gap", fitCorr: "shape (correlation)", fitPeak: "peak", fitSame: "same tick", fitTicks: "ticks",
    checkupTitle: "Checkup", checkupRun: "Run the checkup (free)", checkupOk: "Nothing looked broken.", checkupHelp: "Rehearsals with no AI: every answer is tried on everyone in turn, to find answers that change nothing, people who are never asked, figures that never move, and recorded figures in another unit.",
    checkupAsked: "asked", checkupMoves: "moves the figures", checkupDead: "changes nothing",
    chance: "Chance events", chanceOff: "None", chanceOn: "Let them happen", chanceHelp: "Things nobody chose may happen during the run. Which and when is drawn from the seed: the same seed gives the same future, every fork meets the same events, another seed gives another future.",
    eventsDeck: "Things that may happen", eventsWrite: "Have AI write them", eventsNone: "None yet.", perRun: "per run", ofPeople: "of the people",
    clarifying: "Checking…", clarifyTitle: "Before building", clarifyBody: "A few things would change the world. Pick one, or write your own. Leave any blank.",
    clarifyOwn: "Or in your own words…", clarifyGo: "Build with these", clarifySkip: "Build without answering",
    evolveTitle: "Take this world further", evolvePh: "What you think of this world, what you would change, what you want to see next…", evolveGo: "Make it a new world's theme",
    evolveNote: "AI turns your thoughts into a scenario. You read it, change it, then create.", basedOn: "Grew out of",
    nudgeTitle: "Step in on this person", tellPh: "Say something to them…", forceNone: "Let them decide", nudgeGo: "Fork here and step in",
    nudgeNote: "This run stays as it is. The branch runs on from this tick with AI.", nudgedName: "Stepped in on {n}", srcObserver: "decided by you",
    viewPeople: "People", viewPlaces: "Places", replay: "Replay", stopReplay: "Stop", notAsked: "Not asked yet", since: "since",
    gridNote: "One square = one resident. Colour = their last answer. Outline = answered on this tick. White dot = meant to change, did not.",
    mapNote: "Circle = the amount at that place. Line = what moved today. ▲ low · ! critical.",
    meant: "Meant to", gate: "Who is asked", gateOff: "Everyone the model lists", gateJudge: "Only those who stop to think",
    gateHelp: "AI residents react sooner and harder than real people. With the second choice, a decision model first judges whether each person really weighs a change that day; the others carry on by habit.",
    follow: "Share who act on a change of mind", followHelp: "1 = everyone does what they say. Lower: some mean to change but carry on by habit. Fit it on one real event, then test it on another.",
    reference: "Real data to compare with (optional)", referenceHelp: "Paste CSV with a header row, or JSON rows. Say in the scenario which columns are inputs and which are observed results.",
    referencePh: "day,date,sales_index,deliveries_index,stock_pct\n0,2021-09-13,105.8,99.1,36.3", cast: "How the cast was made",
    heroA: "Run", heroB: "a world.", heroSub: "Describe a situation. AI builds the rules of the world and the people in it, one by one.", example: "Example",
    step1: "Open a world.", step2: "Start a run and watch.", step3: "Trigger an event or fork, then compare the branches.",
    designHint: "about 10-15 min, a few dollars", start: "Start", about: "About", estByModel: "Cost by model", moreSettings: "More settings",
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
    delete: "Delete", confirmDelete: "Delete this? This cannot be undone.", model: "Rules of the world (Python)", research: "Research notes",
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
    draft: "AI でシナリオを考える", drafting: "考え中…", draftHelp: "ざっくりした要望を書くと（空でも可）、AI がシナリオの文章に整えます。",
    modelsTitle: "モデル", per1m: "100 万トークンあたり USD（入力 / 出力）", effort: "考える深さ", save: "保存", resetEnv: ".env の設定に戻す",
    roleDesigner: "世界の構築", roleDesignerHelp: "シナリオから規則と住人を作る。大きな呼び出しが数回。", roleDraft: "シナリオ作成の補助", roleDraftHelp: "ざっくりした案をシナリオに整える。", roleAgent: "住人", roleAgentHelp: "実行中の判断と発言。小さな呼び出しが多数。",
    roleReport: "レポート", roleReportHelp: "実行のまとめの文章。",
    worldLines: "世界線", draftEmptyTitle: "入力が空です", draftEmptyBody: "ラフな案でも書いてもらえれば、それを元に整えます。空のままだと、題材から全部 AI が考えます。それで大丈夫ですか？",
    draftEmptyBack: "戻って書く", draftEmptyGo: "AI に任せる",
    leaveTitle: "AI が作業中です", leaveBody: "今このページを離れると、今行っている作業が失われてしまうかもしれません。", leaveStay: "このまま待つ", leaveGo: "それでも離れる",
    aiDecision: "AI・判断だけ（速い・安い・発言なし）", srcDecision: "AI（判断）", srcHabit: "いつも通り（立ち止まらなかった）",
    colorBy: "色", byAnswer: "最後の答え", byState: "状態", stateNote: "マス 1 つ = 住人 1 人。色 = モデルがその人について持っている値（このティック時点）。マウスを乗せると全部の値が出ます。",
    chatNote: "話しても、その人の行動は変わりません。世界を変えるには「介入」を使います。",
    buildingTag: "組み立て中", failedTag: "作れなかった", buildFailed: "この世界は作れませんでした。", buildAgain: "シナリオを直してもう一度", buildStop: "やめて消す",
    buildLeave: "このページを離れても組み立ては続きます。トップの一覧から戻れます。", scenario: "シナリオ",
    buildA: "箱庭を", buildB: "組み立て中。", stepSurvey: "土地を調べる", stepRules: "規則を組む", stepTrial: "試しに動かす", stepPeople: "住人が越してくる", buildDetail: "くわしい記録",
    askPh: "この実行やレポートについて聞く…", ask: "聞く", saveMd: "Markdown で保存",
    whatIsThis: "これは何？", modeAsk: "何をしたい？", modeSociety: "社会", modeLife: "自分",
    lifeA: "未来を", lifeB: "探索する。", lifeSub: "いまの状況と、迷っていることを書いてください。AI がインタビューして、あなたと周りの人たちを作り、それぞれの道の未来をいくつも動かします。",
    lifePh: "32 歳、バックエンドエンジニア。今の会社は 5 年目。友人のスタートアップから誘われていて…", lifeStart: "インタビューを始める",
    lifePrivacy: "書いた内容は、設定した AI の提供元に送られます。",
    lifeInterview: "あなたのことを教えてください", lifeInterviewBody: "世界の出来は、あなたの人物像の細かさで決まります。選ぶか、自分の言葉で書いてください。言いたくないことは空欄で構いません。",
    lifeInterviewGo: "次へ", lifeComposing: "まとめています…", lifeReady: "読んで、違うところを直してから「作る」を押してください。", lifeWho: "主人公", lifePaths: "道",
    lifeTag: "分かれ道", lifeMake: "未来を作る", lifePer: "道ごとの未来の数", lifeMakeHelp: "どの道にも同じ運を配ります。ある道の「未来 2」と別の道の「未来 2」は、外から起こる出来事が同じです。",
    lifeNone: "まだ未来がありません。作ると、それぞれの道を何度か生きてみます。", lifeTalk: "この未来の自分に聞く", lifeDetail: "開く", lifeLastWords: "最後の言葉",
    lifeReport: "すべての未来を通して", lifeWrite: "レポートを書く", lifeProfile: "主人公について", lifeInside: "この世界の中身（規則・住人・設定）",
    lifeNot: "予測でも助言でもありません。こんな未来もあるかもしれない、という眺めです。", lifeTalkTitle: "未来の自分", lifeRunning: "生きている途中…", lifeOthers: "周りの人",
    close: "閉じる", data: "データ", dataExport: "書き出す", dataImport: "読み込む", dataPick: "残したい世界と実行を選ぶと、1 つの SQLite ファイルにします。分岐を選ぶと、分岐元の実行も一緒に入ります。",
    dataGz: "圧縮する（.gz）", dataGo: "SQLite に書き出す", dataAll: "すべて", dataNone: "外す", dataChosen: "選択中",
    dataImportHelp: "書き出したファイルの世界と実行を、ここに追加します。今あるものは消えません。", dataImportGo: "読み込む",
    dataDone: "世界 {w} 件、実行 {r} 件を追加しました。", dataMatched: "世界 {m} 件は、すでにここにありました。", dataSkipped: "読み込まなかったもの",
    dataKept: "丸ごとの控えの保存先", dataKeptEvery: "変更があれば {n} 分ごと", dataKeptLast: "最後の控え", dataKeepNow: "今すぐ控えを取る", dataKeepNever: "まだありません",
    dataWhy: "データベースは、このマシン上の 1 つのファイルです。ファイルが残らない環境（公開デモなど）では、再起動の前に残したいものを書き出してください。",
    diagramNote: "円 = いまその状態にいる人数。矢印 = これまでにその向きへ移った人数。",
    fitTitle: "実データとの一致", fitErr: "平均のずれ", fitCorr: "形（相関）", fitPeak: "ピーク", fitSame: "同じティック", fitTicks: "ティック",
    checkupTitle: "点検", checkupRun: "点検する（無料）", checkupOk: "壊れているところは見つかりませんでした。", checkupHelp: "AI なしの試運転です。選択肢を 1 つずつ全員に選ばせて、選んでも何も変わらない選択肢、一度も聞かれない人、動かない数字、単位の合わない実データを探します。",
    checkupAsked: "人に質問", checkupMoves: "数字が動く", checkupDead: "何も変わらない",
    chance: "偶然の出来事", chanceOff: "起こさない", chanceOn: "起こす", chanceHelp: "誰も選んでいない出来事が、実行の途中で起こることがあります。何がいつ起こるかは乱数の種で決まります。同じ種なら同じ未来、分岐しても同じ出来事に出会い、種を変えると別の未来になります。",
    eventsDeck: "起こりうる出来事", eventsWrite: "AI に考えてもらう", eventsNone: "まだありません。", perRun: "1 回の実行あたり", ofPeople: "の住人に",
    clarifying: "確認中…", clarifyTitle: "作る前に、確かめたいこと", clarifyBody: "答えによって世界の作りが変わります。選ぶか、自分の言葉で書いてください。空欄のままでも構いません。",
    clarifyOwn: "自分の言葉で書く…", clarifyGo: "この内容で作る", clarifySkip: "答えずに作る",
    evolveTitle: "この世界を発展させる", evolvePh: "この世界への思い、変えたいこと、その先で見たいこと…", evolveGo: "新しい世界のテーマにする",
    evolveNote: "AI が思いを汲んでシナリオに整えます。読んで直してから作れます。", basedOn: "もとの世界",
    nudgeTitle: "この人に介入する", tellPh: "この人に伝える言葉…", forceNone: "行動は本人に任せる", nudgeGo: "ここで分岐して介入",
    nudgeNote: "この実行はそのまま残ります。分岐先は、この時点から AI で動きます。", nudgedName: "{n} に介入", srcObserver: "あなたが指定",
    viewPeople: "住人", viewPlaces: "場所", replay: "再生", stopReplay: "止める", notAsked: "まだ聞かれていない", since: "から",
    gridNote: "マス 1 つ = 住人 1 人。色 = 最後に答えた行動。枠 = このティックで答えた人。白い点 = 変えるつもりで、変えなかった人。",
    mapNote: "円 = その場所の量。線 = 今日動いた量。▲ 注意 · ! 危険。",
    meant: "やろうとしたこと", gate: "誰に聞くか", gateOff: "モデルが挙げた全員", gateJudge: "立ち止まって考える人だけ",
    gateHelp: "AI の住人は、現実の人より早く、大きく動きます。2 つ目を選ぶと、その日に本当に考え直す人かを判断モデルが先に見て、残りの人はいつも通りに動きます。",
    follow: "考えを変えた人のうち実行する割合", followHelp: "1 なら全員が言った通りに動きます。下げると、変えるつもりでも結局いつも通りの人が出ます。1 つの現実の出来事で合わせ、別の出来事で試してください。",
    reference: "比べたい実データ（任意）", referenceHelp: "見出し行つきの CSV か、JSON の行を貼ってください。どの列が入力で、どの列が観測された結果かは、シナリオに書いてください。",
    referencePh: "day,date,sales_index,deliveries_index,stock_pct\n0,2021-09-13,105.8,99.1,36.3", cast: "住人の作り方",
    heroA: "世界を", heroB: "動かす。", heroSub: "状況を書くと、AI が世界の規則と、住人を 1 人ずつ作ります。", example: "例を入れる",
    step1: "世界を開く。", step2: "実行を始めて、眺める。", step3: "事件を起こすか分岐して、結果を比べる。",
    designHint: "約 10〜15 分・数ドル", start: "始める", about: "約", estByModel: "モデルごとの費用", moreSettings: "その他の設定",
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
    delete: "削除", confirmDelete: "削除しますか？元に戻せません。", model: "世界の規則（Python）", research: "調査メモ",
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

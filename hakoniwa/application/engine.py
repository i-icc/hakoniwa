"""The run engine: advances a world tick by tick.

Per tick:  model.step (math)  ->  model.decisions (who needs to decide?)
           -> AI residents answer (in parallel)  ->  model.apply (math again)
           -> store metrics, map view, snapshot, events, facts.

The observer can pause, step, change parameters, trigger interventions and
fork a run at any stored tick; forks share history up to the fork point.
"""
from __future__ import annotations

import asyncio
import json
import random
import time
from typing import Any

from ..domain.contract import chance_events, check_frame, clean_params, default_params, draw_schedule
from ..domain.decisions import (check_request, default_action, habit_action, mock_decision,
                                normalize_action, summarize_action)
from ..domain.names import display_name, resident_names
from ..domain.pricing import cost_usd
from ..domain.text import T
from . import prompts
from .ports import (LanguageModel, LLMError, LLMResult, ModelSandbox, SandboxError,
                    SandboxFactory, Store, chat_json)

DEFAULT_CONFIG = {
    "ticks": None,                 # None = spec.tick.default_ticks
    "seed": 1,
    "ai": "auto",                  # auto | live | mock   (mock = model defaults, no API calls)
    "brain": "chat",               # chat = thought and speech; decision = typed decisions API (fast, cheap, no speech)
    "agent_model": None,           # None = HAKONIWA_MODEL_AGENT
    # AI residents react sooner and harder than real people. Two corrections, both off by default:
    "gate": "off",                 # judge = a decision model first judges whether this person stops to think today
    "follow_through": 1.0,         # share of changes of mind that are acted on; the rest carry on by habit
    "stance": "habit",             # wording of the residents' instructions: habit | classic
    "personas": True,              # False = ask without each person's own description (for comparison only)
    "told": None,                  # what the observer has said to single residents: {key: [{"clock", "text"}]}
    "life": None,                  # what has happened in single residents' own lives: {key: [{"at", "until", "text"}]}
    "chance": False,               # True = things nobody chose may happen (the world's deck of chance events)
    "schedule": None,              # which of them happen in this run and when; drawn from the seed when the run is created
    "max_decisions_per_tick": 2000,
    "budget_usd": None,            # pause the run when spend passes this
    "tick_delay_ms": 250,
}


def merged_config(spec: dict, given: dict | None) -> dict:
    cfg = dict(DEFAULT_CONFIG)
    for k, v in (given or {}).items():
        if k in cfg and v is not None:
            cfg[k] = v
    if not cfg["ticks"]:
        cfg["ticks"] = spec["tick"]["default_ticks"]
    cfg["ticks"] = max(1, min(int(cfg["ticks"]), int(spec["tick"].get("max_ticks", 5000))))
    cfg["seed"] = int(cfg["seed"])
    cfg["max_decisions_per_tick"] = max(0, int(cfg["max_decisions_per_tick"]))
    cfg["follow_through"] = min(1.0, max(0.0, float(cfg["follow_through"])))
    cfg["gate"] = cfg["gate"] if cfg["gate"] in ("off", "judge") else "off"
    return cfg


class RunWorker:
    def __init__(self, mgr: "RunManager", run_id: int):
        self.mgr = mgr
        self.db: Store = mgr.db
        self.llm: LanguageModel = mgr.llm
        self.run_id = run_id
        self.sb: ModelSandbox | None = None
        self.task: asyncio.Task | None = None
        self.want = "paused"           # running | paused | stopped
        self.step_budget = 0           # extra single steps requested while paused
        self.pending: list[dict] = []  # interventions queued for the next tick
        self.wake = asyncio.Event()
        self.lock = asyncio.Lock()
        self.last_clock = ""
        row = self.db.run(run_id)
        self.world = self.db.world(row["world_id"])
        self.spec = self.world["spec"]
        self.config = row["config"]
        self.params = row["params"]
        self.tick = row["tick"]
        self.agents = {a["id"]: a for a in self.spec.get("agents", [])}
        self.spent = self.db.usage(run_id)["cost"]
        self.cast: list[dict] = [{"key": r["key"], "agent": r["agent"], "given": r["given"]} for r in self.db.residents(run_id)]

    # -- lifecycle ----------------------------------------------------------
    @property
    def ai_live(self) -> bool:
        mode = self.config.get("ai", "auto")
        if mode == "mock":
            return False
        return self.llm.live

    async def open(self) -> None:
        """Start a sandbox and bring the model to this run's current tick."""
        if self.sb is not None:
            return
        trusted = self.world["source"] == "builtin"
        self.sb = await self.mgr.sandboxes.open(trusted=trusted)
        await self.sb.load(self.world["code"], {**self.params, "_data": self.spec.get("data")}, self.config["seed"])
        snap = self.db.snapshot(self.run_id, self.tick)
        if snap is None and self.tick > 0:
            raise SandboxError(f"no snapshot stored for tick {self.tick}")
        if snap is None:
            frame = await self.sb.init()
            self._store_frame(0, frame, [])
            for pid, val in self.params.items():
                self.db.assert_fact(self.run_id, "world", pid, val, 0, origin="parameter")
        else:
            await self.sb.restore(snap["state"], snap["rng"], self.tick, self.params)
            fr = self.db.frame(self.run_id, self.tick)
            self.last_clock = T(((fr or {}).get("view") or {}).get("clock"))

    async def close(self) -> None:
        if self.sb is not None:
            await self.sb.close()
            self.sb = None

    def _store_frame(self, tick: int, frame: dict, events: list[dict]) -> None:
        view = frame.get("view") or {}
        self.last_clock = T(view.get("clock")) or f"t={tick}"
        self.db.save_tick(self.run_id, tick, frame.get("metrics") or {}, view, frame["snapshot"], self.params)
        for ev in events:
            self._store_event(tick, ev)
        self.tick = tick
        self.db.set_run(self.run_id, tick=tick)

    def _store_event(self, tick: int, ev: dict) -> None:
        if not isinstance(ev, dict):
            return
        fact = ev.get("fact")
        if isinstance(fact, dict) and "subject" in fact and "predicate" in fact:
            self.db.assert_fact(self.run_id, str(fact["subject"]), str(fact["predicate"]), fact.get("object"), tick, origin="model")
        self.db.add_event(self.run_id, tick, str(ev.get("kind", "info")),
                          {"text": ev.get("text"), "data": ev.get("data")}, agent=ev.get("agent"), node=ev.get("node"))

    # -- one tick -----------------------------------------------------------
    async def advance(self) -> None:
        async with self.lock:
            await self.open()
            assert self.sb is not None
            pre_events: list[dict] = []
            pre_events.extend(await self._chance(self.tick + 1))
            # A branch may be paused or restored before the first step on its new path.
            if self.tick == self.config.get("fork_tick") and self.config.get("fork_intervention"):
                pre_events.extend(await self._apply_intervention(self.config["fork_intervention"]))
            people: list[dict] = []                # the observer steps in on single residents this tick
            while self.pending:
                iv = self.pending.pop(0)
                if iv.get("person"):
                    people.append(iv["person"])
                else:
                    pre_events.extend(await self._apply_intervention(iv))
            res = await self.sb.tick()
            t = res["t"]
            events = pre_events + list(res.get("events") or [])
            requests = [r for r in (res.get("requests") or []) if check_request(r, set(self.agents)) is None]
            actions = await self._resolve(t, requests)
            for p in people:
                events.extend(await self._step_in(t, p, requests, actions))
            frame = await self.sb.apply(actions)
            problems = [p for p in check_frame(self.spec, frame) if p.startswith("invariant") or "finite" in p]
            for p in problems[:3]:
                events.append({"kind": "alert", "text": {"en": f"Model check: {p}", "ja": f"モデルの検査: {p}"}})
            self._store_frame(t, frame, events + list(frame.get("events") or []))

    async def _resolve(self, t: int, requests: list[dict]) -> list[dict]:
        for r in requests:
            self._name(r)                      # fix the order of appearance before answers come back in any order
        cap = self.config["max_decisions_per_tick"]
        live = self.ai_live
        budget = self.config.get("budget_usd")
        over = budget is not None and self.spent >= float(budget)
        if over and live:
            self.want = "paused"
            self.db.add_event(self.run_id, t, "alert", {"text": {
                "en": f"Budget of ${float(budget):.2f} reached. Paused; residents fall back to model defaults.",
                "ja": f"予算 ${float(budget):.2f} に達しました。一時停止し、住人はモデルの既定の動きに戻ります。"}})
        context = self._context(t) if (live and not over and requests) else None

        fast = self.config.get("brain") == "decision"
        gate = self.config.get("gate") == "judge"
        if not self.config.get("personas", True):
            requests = [{k: v for k, v in r.items() if k != "persona"} for r in requests]

        async def one(i: int, req: dict) -> dict:
            if live and not over and i < cap:
                try:
                    if gate and not await self._stops_to_think(t, req, context):
                        act = habit_action(req)
                        self._record(t, req, act, {}, "habit", None, [])
                        return act
                    if fast:
                        return await self._decide_fast(t, req, context)
                    return await self._decide_live(t, req, context)
                except (LLMError, ValueError, json.JSONDecodeError, KeyError) as e:
                    act = default_action(req)
                    self._record(t, req, act, {"error": str(e)[:300]}, "fallback", None, [])
                    return act
            if not live:
                raw = mock_decision(req, self.config["seed"], t)
                act = normalize_action(req, raw)
                self._record(t, req, act, raw, "mock", None, [])
                return act
            act = default_action(req)
            self._record(t, req, act, {}, "default", None, [])
            return act

        return list(await asyncio.gather(*(one(i, r) for i, r in enumerate(requests))))

    async def _step_in(self, t: int, p: dict, requests: list[dict], actions: list[dict]) -> list[dict]:
        """The observer steps in on one resident: says something to them, or decides for them.
        Told something, the resident is asked again there and then and answers for themselves; what was said
        stays with them for later questions. A decision made for them is applied as it is."""
        key = str(p.get("key"))
        req = next((r for r in requests if r["key"] == key), None)
        if req is None:                            # not asked this tick: take up the question they last answered
            last = self.db.decisions(self.run_id, key=key, upto_tick=t, limit=1)
            if not last:
                return [{"kind": "alert", "text": {"en": "That resident has not been asked anything yet, so there is nothing to step in on.",
                                                    "ja": "この住人はまだ一度も聞かれていないので、介入できません。"}}]
            req = dict(last[-1]["request"])
            req["situation"] = (req.get("situation") or "") + " (That was your situation when you last took stock; some time has passed since.)"
        who = T(self._name(req)) or key
        said = str(p.get("tell") or "").strip()[:500]
        if said:
            told = dict(self.config.get("told") or {})
            told[key] = list(told.get(key) or []) + [{"at": t, "clock": self.last_clock or f"t={t}", "text": said}]
            self.config["told"] = told
            self.db.set_run(self.run_id, config=self.config)
        ids = [o["id"] for o in req.get("options") or []]
        if p.get("choice") in ids:
            act = normalize_action(req, {"choice": p["choice"], "numbers": {n["id"]: n["default"] for n in req.get("numbers") or [] if "default" in n}})
            self._record(t, req, act, {"thought": "(decided by the observer)"}, "observer", None, [])
        elif said and self.ai_live:
            try:
                act = await self._decide_live(t, req, self._context(t))
            except (LLMError, ValueError, json.JSONDecodeError, KeyError):
                return []
        else:
            return []
        for i, a in enumerate(actions):
            if a.get("key") == key:
                actions[i] = act
                break
        else:
            actions.append(act)
        did = summarize_action(req, act), summarize_action(req, act, "ja")
        return [{"kind": "intervention", "agent": req["agent"], "node": req.get("node"), "text": {
            "en": f"The observer stepped in on {who}" + (f': "{said}"' if said else "") + f" -> {did[0]}",
            "ja": f"{who} に介入" + (f"：「{said}」" if said else "") + f" → {did[1]}"}}]

    def _with_told(self, req: dict) -> dict:
        """The question, with what the observer has said to this resident added to their situation."""
        lines = [f'An outsider you spoke with ({x["clock"]}) said to you: "{x["text"]}"' for x in (self.config.get("told") or {}).get(req["key"], [])
                 if x["text"] not in (req.get("situation") or "")]
        lines += [f'In your own life lately: {x["text"]}' for x in (self.config.get("life") or {}).get(req["key"], [])
                  if x["until"] > self.tick and x["text"] not in (req.get("situation") or "")]
        return {**req, "situation": ((req.get("situation") or "") + " " + " ".join(lines)).strip()} if lines else req

    def _context(self, t: int) -> dict:
        evs = self.db.events(self.run_id, upto_tick=t, limit=8)
        ev_lines = [T(e["payload"].get("text")) for e in evs if e["kind"] != "say" and e["payload"].get("text")][-6:]
        defaults = default_params(self.spec)
        labels = {p["id"]: T(p.get("label")) for p in self.spec.get("parameters", [])}
        changed = [f"{labels.get(k, k)} = {v} (was {defaults.get(k)})" for k, v in self.params.items()
                   if k in defaults and defaults[k] != v and k in labels]
        return {"events": ev_lines, "facts": changed[:10]}

    def _memory(self, key: str, t: int, n: int = 3) -> list[dict]:
        rows = self.db.decisions(self.run_id, key=key, upto_tick=t, limit=n)
        out = []
        for r in rows:
            resp = r["response"]
            out.append({"clock": resp.get("clock") or f"t={r['tick']}", "summary": resp.get("summary", ""),
                        "say": T(resp.get("say"))})
        return out

    def _name(self, req: dict) -> dict | None:
        """The resident's own name (joins the cast the first time it appears)."""
        if not any(c["key"] == req["key"] for c in self.cast):
            self.cast.append({"key": req["key"], "agent": req["agent"], "given": req.get("name")})
        return display_name(resident_names(self.spec, self.cast).get(req["key"]), req.get("population"))

    async def _decide_live(self, t: int, req: dict, context: dict | None) -> dict:
        req = self._with_told(req)
        agent = self.agents[req["agent"]]
        msgs = prompts.decision_messages(
            self.spec, agent, req, clock=self.last_clock or f"t={t}", memory=self._memory(req["key"], t),
            events=(context or {}).get("events", []), facts=(context or {}).get("facts", []),
            langs=self.mgr.langs, name=T(self._name(req)), stance=self.config.get("stance", "habit"))
        raw, results = await chat_json(self.llm, "agent", msgs, max_tokens=600, model=self.config.get("agent_model"))
        act, meant = self._follow(t, req, normalize_action(req, raw))
        self._record(t, req, act, raw, "llm", results[-1].model, results, meant)
        return act

    async def _stops_to_think(self, t: int, req: dict, context: dict | None) -> bool:
        """The gate: most people carry on by habit most days. A decision model gives the chance that this person
        really weighs a change today; the draw decides. Providers without a decisions API let everyone through."""
        agent = self.agents[req["agent"]]
        brief = prompts.decision_brief(self.spec, agent, req, clock=self.last_clock or f"t={t}", memory=self._memory(req["key"], t),
                                       events=(context or {}).get("events", []), facts=(context or {}).get("facts", []),
                                       name=T(self._name(req)))
        got = await self.llm.decide(prompts.DECIDE_INTRO + "\n\n" + "\n\n".join(brief), [prompts.GATE_QUESTION])
        if got is None:
            return True
        answers, r = got
        c = cost_usd(self.mgr.prices, r.model, r.tokens_in, r.tokens_out)
        self.db.add_llm_call(self.run_id, self.world["id"], "agent", r.model, r.tokens_in, r.tokens_out, c, r.ms, r.estimated)
        self.spent += c or 0.0
        probs = {p.get("value"): float(p.get("probability") or 0) for a in answers if a.get("name") == "attend"
                 for p in a.get("probabilities") or []}
        if not probs:
            return True
        return random.Random(f"{self.config['seed']}:{t}:{req['key']}:gate").random() < probs.get("think", 0.0)

    def _follow(self, t: int, req: dict, act: dict) -> tuple[dict, dict | None]:
        """The gap between meaning to and doing: a change of mind is acted on with probability follow_through.
        Returns the action that happens and, when the person did not follow through, what they meant to do."""
        f = float(self.config.get("follow_through", 1.0))
        if f >= 1.0:
            return act, None
        base = habit_action(req)
        if "weights" in act:                    # a group: that share of it follows through
            w = {k: f * act["weights"].get(k, 0.0) + (1 - f) * base["weights"].get(k, 0.0) for k in base["weights"]}
            nums = {k: base["numbers"].get(k, v) + f * (v - base["numbers"].get(k, v)) for k, v in act["numbers"].items()}
            return normalize_action(req, {"weights": w, "numbers": nums}), None
        if act.get("choice") == base.get("choice") and act.get("numbers") == base.get("numbers"):
            return act, None
        if random.Random(f"{self.config['seed']}:{t}:{req['key']}:follow").random() < f:
            return act, None
        return base, {"en": summarize_action(req, act), "ja": summarize_action(req, act, "ja")}

    async def _decide_fast(self, t: int, req: dict, context: dict | None) -> dict:
        """Ask the decisions API: it returns probabilities, which are used as shares (groups) or drawn from (individuals)."""
        req = self._with_told(req)
        agent = self.agents[req["agent"]]
        brief = prompts.decision_brief(self.spec, agent, req, clock=self.last_clock or f"t={t}", memory=self._memory(req["key"], t),
                                       events=(context or {}).get("events", []), facts=(context or {}).get("facts", []),
                                       name=T(self._name(req)))
        got = await self.llm.decide(prompts.DECIDE_INTRO + "\n\n" + "\n\n".join(brief), prompts.decision_questions(req))
        if got is None:
            raise LLMError("this provider has no decisions API")
        answers, result = got
        by_name = {a.get("name"): a for a in answers if a.get("type") != "refusal"}
        rng = random.Random(f"{self.config['seed']}:{t}:{req['key']}")
        split = req.get("mode", "split") == "split"

        def draw(pairs: list[tuple]):
            total = sum(p for _, p in pairs) or 1.0
            r, acc = rng.random() * total, 0.0
            for v, p in pairs:
                acc += p
                if r <= acc:
                    return v
            return pairs[-1][0]

        raw: dict = {"numbers": {}}
        a = by_name.get("choice")
        if a:
            probs = [(p.get("value"), float(p.get("probability") or 0)) for p in a.get("probabilities") or []]
            if split:
                raw["weights"] = dict(probs)
            elif probs:
                raw["choice"] = draw(probs)
            raw["confidence"] = a.get("confidence")
        for n in req.get("numbers") or []:
            a = by_name.get("num_" + n["id"])
            if not a:
                continue
            levels = prompts.number_levels(n)
            probs = [(levels[i], float(p.get("probability") or 0)) for i, p in enumerate(a.get("probabilities") or []) if i < len(levels)]
            if probs:
                # the levels are coarse steps, so take the probability-weighted value, not one drawn step
                raw["numbers"][n["id"]] = sum(v * p for v, p in probs) / (sum(p for _, p in probs) or 1.0)
        if not by_name:
            raise LLMError("the decisions API declined to answer")
        act, meant = self._follow(t, req, normalize_action(req, raw))
        self._record(t, req, act, raw, "decision", result.model, [result], meant)
        return act

    def _record(self, t: int, req: dict, act: dict, raw: dict, source: str, model: str | None,
                results: list[LLMResult], meant: dict | None = None) -> None:
        tin = sum(r.tokens_in for r in results)
        tout = sum(r.tokens_out for r in results)
        cost = 0.0
        for r in results:
            c = cost_usd(self.mgr.prices, r.model, r.tokens_in, r.tokens_out)
            cost += c or 0.0
            self.db.add_llm_call(self.run_id, self.world["id"], "agent", r.model, r.tokens_in, r.tokens_out, c, r.ms, r.estimated)
        self.spent += cost
        say = raw.get("say") if isinstance(raw.get("say"), (dict, str)) else None
        response = {"action": act, "thought": raw.get("thought"), "say": say, "clock": self.last_clock,
                    "summary": summarize_action(req, act), "summary_ja": summarize_action(req, act, "ja"),
                    "error": raw.get("error")}
        if meant:
            response["meant"] = meant          # what they meant to do but did not
        self.db.add_decision(self.run_id, t, req["key"], req["agent"], req, response, source, model, tin, tout, cost)
        self.db.assert_fact(self.run_id, req["key"], "policy",
                            act.get("weights") or act.get("choice") or act.get("numbers"), t, origin="decision")
        if say:
            self.db.add_event(self.run_id, t, "say", {"text": say, "key": req["key"], "source": source, "meant": meant,
                                                      "summary": {"en": response["summary"], "ja": response["summary_ja"]}},
                              agent=req["agent"], node=req.get("node"))

    async def _chance(self, t: int) -> list[dict]:
        """Chance events due at this tick: the ones that begin, and the ones whose time is up."""
        schedule = self.config.get("schedule") or []
        if not schedule:
            return []
        deck = {e["id"]: e for e in chance_events(self.spec)}
        out: list[dict] = []
        touched = False
        for s in schedule:
            e = deck.get(s["id"])
            if not e:
                continue
            if s["tick"] == t and e.get("personal"):
                # it happens to some residents only: they carry it in mind when they are next asked
                pool = sorted(c["key"] for c in self.cast)
                hit = random.Random(f"{self.config['seed']}:life:{e['id']}").sample(pool, max(1, round(e["personal"]["share"] * len(pool)))) if pool else []
                life = dict(self.config.get("life") or {})
                for key in hit:
                    life[key] = list(life.get(key) or []) + [{"at": t, "until": t + (e.get("lasts") or 10_000), "text": T(e["personal"]["text"], "en")}]
                self.config["life"] = life
                touched = True
                out.append({"kind": "intervention", "text": {
                    "en": f"By chance, for {len(hit)} residents: " + (T(e.get("label"), "en") or e["id"]),
                    "ja": f"偶然の出来事（{len(hit)} 人に）：" + (T(e.get("label"), "ja") or e["id"])}})
            if s["tick"] == t and e["patch"]:
                s["prev"] = {k: self.params.get(k) for k in e["patch"]}          # to put things back when it is over
                touched = True
                out += await self._apply_intervention({"patch": e["patch"], "label": {
                    "en": "By chance: " + (T(e.get("label"), "en") or e["id"]), "ja": "偶然の出来事：" + (T(e.get("label"), "ja") or e["id"])}})
            elif s.get("lasts") and s.get("prev") and s["tick"] + s["lasts"] == t:
                out += await self._apply_intervention({"patch": s["prev"], "label": {
                    "en": "Over: " + (T(e.get("label"), "en") or e["id"]), "ja": "収まった：" + (T(e.get("label"), "ja") or e["id"])}})
        if touched:
            self.db.set_run(self.run_id, config=self.config)
        return out

    # -- interventions ------------------------------------------------------
    async def _apply_intervention(self, iv: dict) -> list[dict]:
        assert self.sb is not None
        patch = clean_params(self.spec, iv.get("patch"), runtime_only=True)
        if not patch:
            return []
        res = await self.sb.set_params(patch)
        self.params.update(patch)
        self.db.set_run(self.run_id, params=self.params)
        at = self.tick + 1
        for pid, val in patch.items():
            self.db.assert_fact(self.run_id, "world", pid, val, at, origin="intervention")
        label = iv.get("label") or {"en": "Parameters changed", "ja": "パラメータを変更"}
        detail = ", ".join(f"{k}={v}" for k, v in patch.items())
        ev = {"kind": "intervention", "text": {"en": f"{T(label, 'en')} ({detail})", "ja": f"{T(label, 'ja')}（{detail}）"},
              "data": {"patch": patch}}
        return [ev] + list(res.get("events") or [])

    # -- loop ---------------------------------------------------------------
    def start_loop(self) -> None:
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        try:
            while self.want != "stopped":
                total = self.config["ticks"]
                if self.tick >= total:
                    self.db.set_run(self.run_id, status="finished")
                    self.want = "paused"
                    self._rest()
                    break
                if self.want == "running" or self.step_budget > 0:
                    if self.step_budget > 0:
                        self.step_budget -= 1
                    self.db.set_run(self.run_id, status="running")
                    await self.advance()
                    if self.want == "running":
                        await asyncio.sleep(max(0, int(self.config.get("tick_delay_ms", 0))) / 1000)
                else:
                    self.db.set_run(self.run_id, status="paused")
                    self._rest()
                    self.wake.clear()
                    await self.wake.wait()
            if self.tick < self.config["ticks"] and self.want == "stopped":
                self.db.set_run(self.run_id, status="paused")
        except SandboxError as e:
            self.db.set_run(self.run_id, status="failed", error=f"{e}\n{e.trace}"[:3000])
            self._rest()
        except Exception as e:   # keep the server alive; show the error on the run
            self.db.set_run(self.run_id, status="failed", error=f"{type(e).__name__}: {e}"[:3000])
        finally:
            await self.close()

    def _rest(self) -> None:
        if self.mgr.on_milestone:
            self.mgr.on_milestone()

    def control(self, action: str, **kw) -> None:
        if "budget_usd" in kw:
            self.config["budget_usd"] = None if kw["budget_usd"] in (None, "") else float(kw["budget_usd"])
            self.db.set_run(self.run_id, config=self.config)
        if "tick_delay_ms" in kw and kw["tick_delay_ms"] is not None:
            self.config["tick_delay_ms"] = max(0, int(kw["tick_delay_ms"]))
            self.db.set_run(self.run_id, config=self.config)
        if kw.get("ticks"):
            self.config["ticks"] = max(self.tick, int(kw["ticks"]))
            self.db.set_run(self.run_id, config=self.config)
        if action == "start":
            self.want = "running"
        elif action == "pause":
            self.want = "paused"
        elif action == "step":
            self.want = "paused"
            self.step_budget += 1
        elif action == "stop":
            self.want = "stopped"
        self.start_loop()
        self.wake.set()


class RunManager:
    def __init__(self, store: Store, sandboxes: SandboxFactory, llm: LanguageModel,
                 prices: dict | None = None, langs: tuple[str, ...] = ("en", "ja")):
        self.db, self.sandboxes, self.llm = store, sandboxes, llm
        self.prices = prices or {}
        self.langs = langs
        self.workers: dict[int, RunWorker] = {}
        self.on_milestone = None       # called when a run comes to rest (finished, paused, failed)
        self.db.pause_running_runs()

    def worker(self, run_id: int) -> RunWorker:
        w = self.workers.get(run_id)
        if w is None:
            if not self.db.run(run_id):
                raise KeyError(run_id)
            w = self.workers[run_id] = RunWorker(self, run_id)
        return w

    async def create_run(self, world_id: int, name: str | None = None, params: dict | None = None,
                         config: dict | None = None) -> int:
        world = self.db.world(world_id)
        if not world:
            raise KeyError(world_id)
        spec = world["spec"]
        p = default_params(spec)
        p.update(clean_params(spec, params))
        cfg = merged_config(spec, config)
        cfg["schedule"] = draw_schedule(chance_events(spec), cfg["seed"], cfg["ticks"]) if cfg.get("chance") else None
        n = len(self.db.runs_for_world(world_id)) + 1
        run_id = self.db.create_run(world_id, name or f"Run {n}", cfg, p)
        w = self.worker(run_id)
        async with w.lock:
            await w.open()     # runs init, stores tick 0
        self.db.set_run(run_id, status="paused")
        return run_id

    async def fork(self, run_id: int, tick: int | None, name: str | None = None,
                   intervention: dict | None = None, config: dict | None = None) -> int:
        src = self.db.run(run_id)
        if not src:
            raise KeyError(run_id)
        tick = src["tick"] if tick is None else int(tick)
        snap = self.db.snapshot(run_id, tick)
        if snap is None:
            raise ValueError(f"run {run_id} has no snapshot at tick {tick}")
        world = self.db.world(src["world_id"])
        cfg = dict(src["config"])
        for k, v in (config or {}).items():
            if k in DEFAULT_CONFIG and v is not None:
                cfg[k] = v
        cfg = merged_config(world["spec"], cfg)
        if intervention and intervention.get("patch"):
            cfg.update(fork_tick=tick, fork_intervention=intervention)
        if cfg.get("schedule"):                    # the branch meets the same events; those after the fork have not happened yet
            cfg["schedule"] = [{k: v for k, v in s.items() if k != "prev" or s["tick"] <= tick} for s in cfg["schedule"]]
        for memory in ("told", "life"):            # what single residents heard or lived through after the fork point is not theirs yet
            if cfg.get(memory):
                cfg[memory] = {k: [x for x in v if x.get("at", 0) <= tick] for k, v in cfg[memory].items()}
        n = len(self.db.runs_for_world(src["world_id"])) + 1
        new_id = self.db.create_run(src["world_id"], name or f"Run {n} (fork of {src['name']} @ {tick})",
                                    cfg, snap["params"], parent=run_id, fork_tick=tick)
        self.db.copy_history(run_id, new_id, tick)
        self.db.set_run(new_id, status="paused", tick=tick)
        w = self.worker(new_id)
        if intervention and not intervention.get("patch"):
            w.pending.append(intervention)
        return new_id

    def intervene(self, run_id: int, intervention: dict) -> None:
        self.worker(run_id).pending.append(intervention)

    async def shutdown(self) -> None:
        for w in list(self.workers.values()):
            w.want = "stopped"
            w.wake.set()
            if w.task:
                try:
                    await asyncio.wait_for(w.task, timeout=5)
                except Exception:
                    w.task.cancel()
            await w.close()

    def delete_run(self, run_id: int) -> None:
        w = self.workers.pop(run_id, None)
        if w:
            w.want = "stopped"
            w.wake.set()
        self.db.delete_run(run_id)


async def run_headless(mgr: RunManager, run_id: int, on_tick=None) -> None:
    """Run to the end without the server loop (CLI and tests)."""
    w = mgr.worker(run_id)
    try:
        while w.tick < w.config["ticks"]:
            await w.advance()
            if on_tick:
                on_tick(w)
        mgr.db.set_run(run_id, status="finished")
    finally:
        await w.close()

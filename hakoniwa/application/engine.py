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
import time
from typing import Any

from ..domain.contract import check_frame, clean_params, default_params
from ..domain.decisions import (check_request, default_action, mock_decision,
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
    "agent_model": None,           # None = HAKONIWA_MODEL_AGENT
    "max_decisions_per_tick": 40,
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
        await self.sb.load(self.world["code"], self.params, self.config["seed"])
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
            while self.pending:
                pre_events.extend(await self._apply_intervention(self.pending.pop(0)))
            res = await self.sb.tick()
            t = res["t"]
            events = pre_events + list(res.get("events") or [])
            requests = [r for r in (res.get("requests") or []) if check_request(r, set(self.agents)) is None]
            actions = await self._resolve(t, requests)
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

        async def one(i: int, req: dict) -> dict:
            if live and not over and i < cap:
                try:
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
        agent = self.agents[req["agent"]]
        msgs = prompts.decision_messages(
            self.spec, agent, req, clock=self.last_clock or f"t={t}", memory=self._memory(req["key"], t),
            events=(context or {}).get("events", []), facts=(context or {}).get("facts", []),
            langs=self.mgr.langs, name=T(self._name(req)))
        raw, results = await chat_json(self.llm, "agent", msgs, max_tokens=600, model=self.config.get("agent_model"))
        act = normalize_action(req, raw)
        self._record(t, req, act, raw, "llm", results[-1].model, results)
        return act

    def _record(self, t: int, req: dict, act: dict, raw: dict, source: str, model: str | None,
                results: list[LLMResult]) -> None:
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
        self.db.add_decision(self.run_id, t, req["key"], req["agent"], req, response, source, model, tin, tout, cost)
        self.db.assert_fact(self.run_id, req["key"], "policy",
                            act.get("weights") or act.get("choice") or act.get("numbers"), t, origin="decision")
        if say:
            self.db.add_event(self.run_id, t, "say", {"text": say, "key": req["key"], "source": source,
                                                      "summary": {"en": response["summary"], "ja": response["summary_ja"]}},
                              agent=req["agent"], node=req.get("node"))

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
                    self.wake.clear()
                    await self.wake.wait()
            if self.tick < self.config["ticks"] and self.want == "stopped":
                self.db.set_run(self.run_id, status="paused")
        except SandboxError as e:
            self.db.set_run(self.run_id, status="failed", error=f"{e}\n{e.trace}"[:3000])
        except Exception as e:   # keep the server alive; show the error on the run
            self.db.set_run(self.run_id, status="failed", error=f"{type(e).__name__}: {e}"[:3000])
        finally:
            await self.close()

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
        n = len(self.db.runs_for_world(src["world_id"])) + 1
        new_id = self.db.create_run(src["world_id"], name or f"Run {n} (fork of {src['name']} @ {tick})",
                                    cfg, snap["params"], parent=run_id, fork_tick=tick)
        self.db.copy_history(run_id, new_id, tick)
        self.db.set_run(new_id, status="paused", tick=tick)
        w = self.worker(new_id)
        if intervention:
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

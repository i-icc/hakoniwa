"""Observer-facing use cases on a run: written report, interview a resident,
turn a free-text intervention into parameter changes."""
from __future__ import annotations

from ..domain.contract import clean_params, default_params
from ..domain.names import display_name, resident_names
from ..domain.pricing import cost_usd
from ..domain.text import T
from . import prompts
from .ports import LanguageModel, LLMError, LLMResult, Store, chat_json


class Observer:
    def __init__(self, store: Store, llm: LanguageModel, prices: dict, langs):
        self.store, self.llm, self.prices, self.langs = store, llm, prices, langs

    def _bill(self, run_id: int, world_id: int, role: str, results: list[LLMResult]) -> None:
        for r in results:
            self.store.add_llm_call(run_id, world_id, role, r.model, r.tokens_in, r.tokens_out,
                                    cost_usd(self.prices, r.model, r.tokens_in, r.tokens_out), r.ms, r.estimated)

    # -- report -------------------------------------------------------------
    def digest(self, run_id: int, compare: list[int] | None = None) -> dict:
        run = self.store.run(run_id)
        world = self.store.world(run["world_id"])
        spec = world["spec"]
        ticks = self.store.ticks(run_id)
        defaults = default_params(spec)

        def series(rows: list[dict]) -> dict:
            out = {}
            if not rows:
                return out
            n = len(rows)
            idx = sorted(set([0, n - 1] + [round(i * (n - 1) / 7) for i in range(8)]))
            for m in spec.get("metrics", []):
                vals = [r["metrics"].get(m["id"]) for r in rows if m["id"] in r["metrics"]]
                if not vals:
                    continue
                out[m["id"]] = {"label": T(m.get("label")), "unit": T(m.get("unit")), "start": vals[0], "end": vals[-1],
                                "min": min(vals), "max": max(vals),
                                "samples": [[rows[i]["tick"], rows[i]["metrics"].get(m["id"])] for i in idx]}
            return out

        events = [e for e in self.store.events(run_id, limit=2000) if e["kind"] != "say"]
        says = [e for e in self.store.events(run_id, limit=4000) if e["kind"] == "say" and e["payload"].get("source") == "llm"]
        step = max(1, len(says) // 14)
        policies = [{"who": d["key"], "at_tick": d["tick"], "chose": d["response"].get("summary"),
                     "why": d["response"].get("thought")} for d in self.store.latest_decisions(run_id, run["tick"])][:30]
        others = []
        for rid in compare or ([run["parent_run_id"]] if run.get("parent_run_id") else []):
            other = self.store.run(rid) if rid else None
            if not other or other["world_id"] != run["world_id"]:
                continue
            rows = [r for r in self.store.ticks(rid) if r["tick"] <= run["tick"]]
            if rows:
                others.append({"name": other["name"], "at_tick": rows[-1]["tick"],
                               "params_changed": {k: v for k, v in other["params"].items() if defaults.get(k) != v},
                               "end": {k: v for k, v in rows[-1]["metrics"].items()}})
        return {
            "world": {"title": T(spec.get("title")), "summary": T(spec.get("summary")), "tick_unit": T(spec["tick"].get("unit")),
                      "questions": [T(q) for q in spec.get("questions", [])], "assumptions": [T(a) for a in spec.get("assumptions", [])]},
            "run": {"name": run["name"], "ticks_done": run["tick"], "forked_from_tick": run.get("fork_tick"),
                    "residents_played_by": "AI" if any(s for s in says) else "model defaults (no AI)",
                    "params_changed_from_default": {k: v for k, v in run["params"].items() if k in defaults and defaults[k] != v}},
            "metrics": series(ticks),
            "events": [{"tick": e["tick"], "kind": e["kind"], "text": T(e["payload"].get("text"))} for e in events][-40:],
            "resident_policies_at_end": policies,
            "quotes": [{"tick": e["tick"], "who": e["agent"], "said": T(e["payload"].get("text"))} for e in says[::step]][:14],
            "compare_with": others,
        }

    async def report(self, run_id: int, compare: list[int] | None = None) -> dict:
        run = self.store.run(run_id)
        d = self.digest(run_id, compare)
        if self.llm.live:
            body, results = await chat_json(self.llm, "report", prompts.report_messages(self.store.world(run["world_id"])["spec"], d, self.langs),
                                            max_tokens=6000)
            self._bill(run_id, run["world_id"], "report", results)
            body = {k: str(v) for k, v in body.items() if k in self.langs or k in ("en", "ja")}
            source = "llm"
        else:
            body, source = _plain_report(d), "template"
        self.store.save_report(run_id, run["tick"], body, source)
        return {"body": body, "source": source, "tick": run["tick"]}

    # -- interview ----------------------------------------------------------
    async def chat(self, run_id: int, key: str, text: str, lang: str) -> dict:
        run = self.store.run(run_id)
        world = self.store.world(run["world_id"])
        spec = world["spec"]
        last = self.store.decisions(run_id, key=key, upto_tick=run["tick"], limit=3)
        if not last:
            raise LLMError("This resident has not appeared in the run yet.")
        agent = next((a for a in spec.get("agents", []) if a["id"] == last[-1]["agent"]), None)
        if not agent:
            raise LLMError("Unknown resident.")
        if not self.llm.live:
            raise LLMError("Interviews need an AI provider (set OPENAI_API_KEY).")
        frame = self.store.frame(run_id, run["tick"]) or {}
        memory = [{"clock": d["response"].get("clock") or f"t={d['tick']}", "summary": d["response"].get("summary", "")} for d in last]
        history = self.store.chats(run_id, key)
        msgs = prompts.chat_messages(spec, agent, clock=T((frame.get("view") or {}).get("clock")) or f"t={run['tick']}",
                                     situation=last[-1]["request"].get("situation", ""), memory=memory, history=history,
                                     text=text, lang=lang,
                                     name=T(display_name(resident_names(spec, self.store.residents(run_id)).get(key), last[-1]["request"].get("population")), lang))
        res = await self.llm.chat("agent", msgs, max_tokens=1500, model=run["config"].get("agent_model"))
        self._bill(run_id, run["world_id"], "chat", [res])
        self.store.add_chat(run_id, run["tick"], agent["id"], key, "user", text)
        self.store.add_chat(run_id, run["tick"], agent["id"], key, "resident", res.text.strip())
        return {"reply": res.text.strip(), "agent": agent["id"]}

    # -- free-text intervention --------------------------------------------
    async def interpret(self, run_id: int, text: str) -> dict:
        run = self.store.run(run_id)
        world = self.store.world(run["world_id"])
        if not self.llm.live:
            raise LLMError("Free-text interventions need an AI provider (set OPENAI_API_KEY).")
        raw, results = await chat_json(self.llm, "agent", prompts.interpret_messages(world["spec"], run["params"], text),
                                       max_tokens=1500, model=run["config"].get("agent_model"))
        self._bill(run_id, run["world_id"], "interpret", results)
        patch = clean_params(world["spec"], raw.get("patch") if isinstance(raw.get("patch"), dict) else {}, runtime_only=True)
        return {"patch": patch, "label": raw.get("label") or {"en": text[:60], "ja": text[:60]}, "explain": raw.get("explain")}


def _plain_report(d: dict) -> dict:
    """Report without AI: just the numbers, in both languages."""
    def lines(lang: str) -> str:
        head = {"en": f"## {d['world']['title']}\n\nRun **{d['run']['name']}**, {d['run']['ticks_done']} ticks. "
                      "This summary lists numbers only; set an API key for a written analysis.\n\n| Metric | Start | End | Min | Max |\n|---|---|---|---|---|",
                "ja": f"## {d['world']['title']}\n\n実行 **{d['run']['name']}**、{d['run']['ticks_done']} ティック。"
                      "この要約は数字だけです。文章での分析には API キーが必要です。\n\n| 指標 | 開始 | 終了 | 最小 | 最大 |\n|---|---|---|---|---|"}[lang]
        rows = [f"| {m['label']} | {m['start']:,} | {m['end']:,} | {m['min']:,} | {m['max']:,} |" for m in d["metrics"].values()]
        return head + "\n" + "\n".join(rows)
    return {"en": lines("en"), "ja": lines("ja")}

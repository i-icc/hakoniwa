"""Observer-facing use cases on a run: written report, interview a resident,
turn a free-text intervention into parameter changes."""
from __future__ import annotations

import re

from ..domain.contract import clean_params, default_params
from ..domain.names import display_name, resident_names
from ..domain.pricing import cost_usd
from ..domain.text import T
from . import prompts
from .ports import LanguageModel, LLMError, LLMResult, Store, chat_json
from .worlds import reality_pairs


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

    # -- the written report ---------------------------------------------------
    # Numbers come from the program, words from AI. `report_facts` gathers what is true of the run and of the other
    # runs of its world; AI writes short pieces from those facts; `render_report` lays tables and words out in a fixed
    # order of short sections, answer first and one next step last.
    def report_facts(self, run_id: int, compare: list[int] | None = None, lang: str = "en") -> dict:
        run = self.store.run(run_id)
        world = self.store.world(run["world_id"])
        spec = world["spec"]
        defaults = default_params(spec)
        labels = {m["id"]: T(m.get("label"), lang) or m["id"] for m in spec.get("metrics", [])}
        plabel = {p["id"]: T(p.get("label"), lang) or p["id"] for p in spec.get("parameters", [])}
        # as many digits as the eye can use: 233, 17.7, 0.82
        r3 = lambda v: (round(v) if abs(v) >= 100 else round(v, 1) if abs(v) >= 10 else round(v, 2)) if isinstance(v, float) else v

        def rows_of(rid: int) -> list[dict]:
            return [r for r in self.store.ticks(rid) if r["tick"] > 0]

        rows = rows_of(run_id)
        clock = {r["tick"]: T(r.get("clock"), lang) or f"t={r['tick']}" for r in rows}
        pairs = reality_pairs(spec)

        def fit(rs: list[dict]) -> list[dict]:
            out = []
            for sim, real in pairs:
                pts = [(r["tick"], r["metrics"].get(sim), r["metrics"].get(real)) for r in rs]
                pts = [p for p in pts if isinstance(p[1], (int, float)) and isinstance(p[2], (int, float))]
                if len(pts) < 3:
                    continue
                a, b = [p[1] for p in pts], [p[2] for p in pts]
                ma, mb = sum(a) / len(a), sum(b) / len(b)
                cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
                va, vb = sum((x - ma) ** 2 for x in a), sum((y - mb) ** 2 for y in b)
                spiky = max(b) > 1.25 * sorted(b)[len(b) // 2]
                far = max(range(len(a)), key=lambda k: abs(a[k] - b[k]))
                out.append({"metric": labels.get(sim, sim), "mean_gap": r3(sum(abs(x - y) for x, y in zip(a, b)) / len(a)),
                            "correlation": round(cov / (va * vb) ** 0.5, 2) if va and vb else None,
                            "peak_ticks_off": (pts[a.index(max(a))][0] - pts[b.index(max(b))][0]) if spiky else None,
                            "furthest": {"when": clock.get(pts[far][0]), "simulated": r3(a[far]), "recorded": r3(b[far])}})
            return out

        heads = [m["id"] for m in spec.get("metrics", []) if m.get("headline") and not m["id"].startswith("real_")] or \
                [m["id"] for m in spec.get("metrics", []) if not m["id"].startswith("real_")][:4]

        def figures(rs: list[dict]) -> list[dict]:
            out = []
            for mid in heads[:5]:
                pts = [(r["tick"], r["metrics"].get(mid)) for r in rs if isinstance(r["metrics"].get(mid), (int, float))]
                if not pts:
                    continue
                hi, lo = max(pts, key=lambda p: p[1]), min(pts, key=lambda p: p[1])
                out.append({"metric": labels.get(mid, mid), "start": r3(pts[0][1]), "highest": r3(hi[1]), "highest_when": clock.get(hi[0], f"t={hi[0]}"),
                            "lowest": r3(lo[1]), "lowest_when": clock.get(lo[0], f"t={lo[0]}"), "end": r3(pts[-1][1])})
            return out

        # what residents did
        tally: dict = {}
        by_tick: dict = {}
        people, moved, meant, turns = set(), 0, 0, []
        sources: dict = {}
        for d in self.store.decisions(run_id, limit=200_000):
            req, resp = d["request"], d["response"]
            what = (T(next((o.get("label") for o in req.get("options") or [] if o["id"] == (resp.get("action") or {}).get("choice")), None), lang)
                    or resp.get("summary") or "")[:90]
            tally[what] = tally.get(what, 0) + 1
            people.add(d["key"])
            sources[d["source"]] = sources.get(d["source"], 0) + 1
            first = (req.get("options") or [{}])[0].get("id")
            if resp.get("meant"):
                meant += 1
            if (resp.get("action") or {}).get("choice") != first:
                moved += 1
                by_tick[d["tick"]] = by_tick.get(d["tick"], 0) + 1
                if resp.get("thought") or resp.get("say"):
                    turns.append({"tick": d["tick"], "when": clock.get(d["tick"], f"t={d['tick']}"), "who": T(req.get("name"), lang) or d["key"], "did": what,
                                  "thought": resp.get("thought"), "said": T(resp.get("say"), lang) or None})
        asked = sum(tally.values())
        top = sorted(tally.items(), key=lambda kv: -kv[1])
        choices = [{"choice": k, "times": v, "share_pct": round(100 * v / asked)} for k, v in top[:5]]
        if len(top) > 5:
            rest = sum(v for _, v in top[5:])
            choices.append({"choice": {"en": "other answers", "ja": "その他の答え"}.get(lang, "other answers"), "times": rest, "share_pct": round(100 * rest / asked)})
        busy = [t for t, _ in sorted(by_tick.items(), key=lambda kv: -kv[1])[:3]]
        turns.sort(key=lambda v: (busy.index(v["tick"]) if v["tick"] in busy else 9, v["tick"]))     # voices from the moments that mattered first
        step = max(1, len([v for v in turns if v["tick"] in busy]) // 6)
        cast = len((spec.get("data") or {}).get((spec.get("cast") or {}).get("collection") or "") or [])

        # what happened on the way
        events = self.store.earlier_happenings(run_id, 10 ** 12)
        news = [{"when": clock.get(e["tick"], f"t={e['tick']}"), "what": T(e["payload"].get("text"), lang)} for e in events if e["kind"] in ("alert", "milestone", "info")]
        acts = [{"when": clock.get(e["tick"], f"t={e['tick']}"), "what": T(e["payload"].get("text"), lang)} for e in events if e["kind"] == "intervention"]

        # the other runs of this world, nearest first
        def differs(other: dict) -> str:
            out = [f"{plabel.get(k, k)} = {v}" for k, v in other["params"].items() if k in defaults and run["params"].get(k) != v]
            oc, mc = other["config"], run["config"]
            word = {"en": {"rules": "fixed rules only, no AI", "ai": "AI residents", "seed": "seed", "gate": "only those who stop to think are asked",
                           "follow": "share who act on a change of mind", "chance": "chance events on", "nochance": "chance events off", "told": "the observer stepped in on a resident"},
                    "ja": {"rules": "規則だけ（AI なし）", "ai": "AI の住人", "seed": "乱数の種", "gate": "立ち止まって考える人だけに聞く",
                           "follow": "考えを変えた人のうち実行する割合", "chance": "偶然の出来事あり", "nochance": "偶然の出来事なし", "told": "観察者が 1 人に介入"}}.get(lang) or {}
            if (oc.get("ai") == "mock") != (mc.get("ai") == "mock"):
                out.append(word.get("rules" if oc.get("ai") == "mock" else "ai", ""))
            if oc.get("seed") != mc.get("seed"):
                out.append(f"{word.get('seed', 'seed')} {oc.get('seed')}")
            if (oc.get("gate") == "judge") != (mc.get("gate") == "judge") and oc.get("gate") == "judge":
                out.append(word.get("gate", ""))
            if float(oc.get("follow_through", 1) or 1) != float(mc.get("follow_through", 1) or 1):
                out.append(f"{word.get('follow', '')} {oc.get('follow_through')}")
            if bool(oc.get("schedule")) != bool(mc.get("schedule")):
                out.append(word.get("chance" if oc.get("schedule") else "nochance", ""))
            if oc.get("told") and not mc.get("told"):
                out.append(word.get("told", ""))
            return "; ".join(x for x in out if x)[:160]

        siblings = [r for r in self.store.runs_for_world(run["world_id"]) if r["id"] != run_id and r["tick"] > 0]
        near = lambda r: (0 if r["id"] in (compare or []) else 1 if r["id"] == run.get("parent_run_id") or r.get("parent_run_id") == run_id else 2, -r["id"])
        others = []
        for o in sorted(siblings, key=near)[:6]:
            rs = [r for r in rows_of(o["id"])]
            f = fit(rs)
            relation = ("the run this one was forked from" if o["id"] == run.get("parent_run_id") else
                        f"forked from this run at tick {o.get('fork_tick')}" if o.get("parent_run_id") == run_id else "another run of the same world")
            others.append({"name": o["name"], "relation": relation, "differs_by": differs(o), "ticks": o["tick"],
                           "figures": [{k: v for k, v in x.items() if k in ("metric", "highest", "end")} for x in figures(rs)[:2]],
                           "mean_gap_to_record": f[0]["mean_gap"] if f else None})
        usage = self.store.usage(run_id)
        played = "AI" if sources.get("llm") or sources.get("decision") else "fixed rules only (no AI)"
        return {
            "world": {"title": T(spec.get("title"), lang), "summary": T(spec.get("summary"), lang), "one_tick": T(spec["tick"].get("unit"), lang),
                      "questions": [T(q, lang) for q in spec.get("questions", [])][:5], "assumptions": [T(a, lang) for a in spec.get("assumptions", [])][:5],
                      "what_if_events": [T(i.get("label"), lang) for i in spec.get("interventions", [])][:6]},
            "run": {"name": run["name"], "ticks": run["tick"], "from": clock.get(1), "to": clock.get(run["tick"]), "residents_played_by": played,
                    "forked_at_tick": run.get("fork_tick"), "calls": usage["calls"], "cost_usd": round(usage["cost"], 2),
                    "changed_from_default": {plabel.get(k, k): v for k, v in run["params"].items() if k in defaults and defaults[k] != v}},
            "figures": figures(rows),
            "residents": {"people_in_the_world": cast or None, "people_asked": len(people), "questions": asked, "answers_that_changed_course": moved,
                          "meant_to_change_but_did_not": meant, "choices": choices,
                          "busiest_moments": [{"when": clock.get(t, f"t={t}"), "changed_course": n} for t, n in sorted(by_tick.items(), key=lambda kv: -kv[1])[:3]],
                          "voices": [{k: x for k, x in v.items() if k != "tick"} for v in turns[::step][:10]]},
            "against_the_record": fit(rows),
            "world_news": news[:8], "interventions_and_chance": acts[:8],
            "other_runs": others,
            "checkup_notes": (spec.get("checkup") or {}).get("notes", [])[:3],
        }

    async def report(self, run_id: int, compare: list[int] | None = None, lang: str | None = None) -> dict:
        run = self.store.run(run_id)
        lang = lang if lang in self.langs else self.langs[0]
        facts = self.report_facts(run_id, compare, lang)
        words, source = {}, "template"
        if self.llm.live:
            try:
                words, results = await chat_json(self.llm, "report", prompts.report_messages(facts, lang), max_tokens=6000)
                self._bill(run_id, run["world_id"], "report", results)
                source = "llm"
            except (LLMError, ValueError):
                words = {}                          # the tables still stand on their own
        prev = self.store.latest_report(run_id)
        body = dict(prev["body"]) if prev and prev.get("tick") == run["tick"] and isinstance(prev.get("body"), dict) else {}
        body[lang] = render_report(facts, words if isinstance(words, dict) else {}, lang)
        if source == "template":                     # the tables cost nothing: lay them out in every language
            for lg in self.langs:
                if lg != lang:
                    body[lg] = render_report(self.report_facts(run_id, compare, lg), {}, lg)
        self.store.save_report(run_id, run["tick"], body, source)
        return {"body": body, "source": source, "tick": run["tick"]}

    def report_markdown(self, run_id: int, lang: str, with_questions: bool = True) -> str | None:
        """The report as one Markdown document, with the questions put to the analyst after it."""
        rep = self.store.latest_report(run_id)
        if not rep or not isinstance(rep.get("body"), dict) or not rep["body"]:
            return None
        text = rep["body"].get(lang) or next(iter(rep["body"].values()))
        asked = self.store.chats(run_id, self.ANALYST) if with_questions else []
        if asked:
            text += "\n\n## " + {"ja": "質問と答え"}.get(lang, "Questions and answers") + "\n"
            for m in asked:
                text += ("\n**Q. " + m["text"].strip() + "**\n" if m["role"] == "user" else "\n" + m["text"].strip() + "\n")
        return text.rstrip() + "\n"

    # -- one person's crossroads: all the futures of a life world -----------------
    def futures(self, world_id: int, lang: str = "en") -> dict:
        """Every run of a life world as one possible future: which path it took, how the outcomes moved,
        what the protagonist decided on the way, what happened to them, and what the people around them said."""
        world = self.store.world(world_id)
        spec = world["spec"]
        focus = spec.get("focus") or {}
        key, outcomes = focus.get("key", "you"), focus.get("outcomes") or []
        labels = {m["id"]: T(m.get("label"), lang) or m["id"] for m in spec.get("metrics", [])}
        r1 = lambda v: (round(v) if abs(v) >= 100 else round(v, 1)) if isinstance(v, float) else v
        out = []
        for run in self.store.runs_for_world(world_id):
            history = self.store.ticks(run["id"])
            rows = [r for r in history if r["tick"] > 0]
            clock = {r["tick"]: T(r.get("clock"), lang) or f"t={r['tick']}" for r in rows}
            figures = {}
            for m in outcomes:
                vals = [r["metrics"].get(m) for r in rows if isinstance(r["metrics"].get(m), (int, float))]
                if vals:
                    figures[m] = {"start": r1(vals[0]), "end": r1(vals[-1]), "low": r1(min(vals)), "high": r1(max(vals))}
            turns, last = [], None
            for d in self.store.decisions(run["id"], key=key, limit=400):
                req, resp = d["request"], d["response"]
                did = (T(next((o.get("label") for o in req.get("options") or [] if o["id"] == (resp.get("action") or {}).get("choice")), None), lang)
                       or resp.get("summary") or "")[:110]
                if resp.get("say"):
                    last = {"when": clock.get(d["tick"], f"t={d['tick']}"), "said": T(resp.get("say"), lang)}
                if (resp.get("action") or {}).get("choice") != (req.get("options") or [{}])[0].get("id"):
                    turns.append({"tick": d["tick"], "when": clock.get(d["tick"], f"t={d['tick']}"), "did": did,
                                  "thought": resp.get("thought"), "said": T(resp.get("say"), lang) or None})
            events = self.store.earlier_happenings(run["id"], 10 ** 12)
            # what struck from outside; a model's own status lines stay in the feed
            tidy = lambda s: re.sub(r"\s*[（(][^（()）]*=[^（()）]*[)）]\s*$", "", s or "").replace("By chance: ", "").replace("偶然の出来事：", "")
            happened = [{"tick": e["tick"], "when": clock.get(e["tick"], f"t={e['tick']}"), "what": tidy(T(e["payload"].get("text"), lang)),
                         "over": (T(e["payload"].get("text"), "en") or "").startswith("Over: ")}
                        for e in events if e["kind"] in ("intervention", "alert")]
            names = resident_names(spec, self.store.residents(run["id"]))
            voices = [{"when": clock.get(e["tick"], f"t={e['tick']}"), "who": T(display_name(names.get(e["payload"].get("key")), None), lang) or e.get("agent"),
                       "said": T(e["payload"].get("text"), lang)}
                      for e in self.store.events(run["id"], limit=2000) if e["kind"] == "say" and e["payload"].get("key") != key and e["payload"].get("source") == "llm"]
            first = outcomes[0] if outcomes else None
            out.append({"id": run["id"], "name": run["name"], "path": run["params"].get(focus.get("path_param", "path")), "seed": run["config"].get("seed"),
                        "parent_run_id": run["parent_run_id"], "fork_tick": run["fork_tick"],
                        "outcomes": {m: [[r["tick"], r["metrics"][m]] for r in history
                                         if isinstance(r["metrics"].get(m), (int, float))] for m in outcomes},
                        "status": run["status"], "tick": run["tick"], "total": run["config"].get("ticks"), "figures": figures,
                        "series": [r["metrics"].get(first) for r in rows] if first else [],
                        "turns": turns, "happened": happened, "last_words": last, "voices": voices[-4:],
                        "can_talk": bool(last or turns) and self.llm.live, "cost": round(self.store.usage(run["id"])["cost"], 3)})
        return {"focus": focus, "labels": {m: labels.get(m, m) for m in outcomes}, "futures": out}

    def life_facts(self, world_id: int, lang: str) -> dict:
        spec = self.store.world(world_id)["spec"]
        f = self.futures(world_id, lang)
        focus = f["focus"]
        r1 = lambda v: round(v) if abs(v) >= 100 else round(v, 1)
        done = [x for x in f["futures"] if x["tick"] > 0]
        paths = []
        for o in focus.get("options", []):
            mine = [x for x in done if x["path"] == o["id"]]
            agg = {}
            for m in focus.get("outcomes", []):
                ends = [x["figures"][m]["end"] for x in mine if m in x["figures"]]
                if ends:
                    agg[f["labels"][m]] = {"lowest_end": min(ends), "highest_end": max(ends), "average_end": r1(sum(ends) / len(ends))}
            paths.append({"id": o["id"], "label": T(o.get("label"), lang), "futures": len(mine), "outcomes_at_the_end": agg})
        thin = lambda xs, n: xs[::max(1, len(xs) // n)][:n] if xs else []
        return {"question": T(focus.get("question"), lang), "who": T(focus.get("name"), lang), "horizon": focus.get("horizon"),
                "one_tick": T(spec["tick"].get("unit"), lang), "paths": paths,
                "futures": [{"name": x["name"], "path": x["path"], "luck_number": x["seed"], "ticks": x["tick"],
                             "outcomes": {f["labels"][m]: v for m, v in x["figures"].items()},
                             "their_decisions": [{k: v for k, v in t.items() if k != "tick"} for t in thin(x["turns"], 6)],
                             "what_happened_to_them": [{"when": h["when"], "what": h["what"]} for h in thin([h for h in x["happened"] if not h.get("over")], 5)],
                             "last_words": x["last_words"], "what_others_said": x["voices"][-3:]} for x in done][:16],
                "assumptions": [T(a, lang) for a in spec.get("assumptions", [])][:4]}

    async def life_report(self, world_id: int, lang: str | None = None) -> dict:
        lang = lang if lang in self.langs else self.langs[0]
        facts = self.life_facts(world_id, lang)
        words, source = {}, "template"
        if self.llm.live and facts["futures"]:
            try:
                words, results = await chat_json(self.llm, "report", prompts.life_report_messages(facts, lang), max_tokens=7000)
                for r in results:
                    self.store.add_llm_call(None, world_id, "report", r.model, r.tokens_in, r.tokens_out,
                                            cost_usd(self.prices, r.model, r.tokens_in, r.tokens_out), r.ms, r.estimated)
                source = "llm"
            except (LLMError, ValueError):
                words = {}
        body = dict((self.store.get_setting(f"life_report:{world_id}") or {}).get("body") or {})
        body[lang] = render_life_report(facts, words if isinstance(words, dict) else {}, lang)
        self.store.set_setting(f"life_report:{world_id}", {"body": body, "source": source, "futures": len(facts["futures"])})
        return {"body": body, "source": source}

    # -- questions about the run and its report -------------------------------
    ANALYST = "@analyst"          # the key under which this conversation is stored with the run

    def detail(self, run_id: int) -> dict:
        """What a question may need beyond the digest: every metric at every tick, the tally of residents' choices
        per tick, and a spread of the moments when someone changed course, with what they thought."""
        spec = self.store.world(self.store.run(run_id)["world_id"])["spec"]
        ids = [m["id"] for m in spec.get("metrics", [])]
        ticks = self.store.ticks(run_id)
        r3 = lambda v: round(v, 3) if isinstance(v, float) else v
        table = {"columns": ["tick", "clock"] + ids,
                 "rows": [[r["tick"], T(r.get("clock")) or ""] + [r3(r["metrics"].get(i)) for i in ids] for r in ticks]}
        tally: dict = {}
        turns = []
        for d in self.store.decisions(run_id, limit=100_000):
            req, resp = d["request"], d["response"]
            what = resp.get("summary") or ""
            row = tally.setdefault(d["tick"], {})
            row[what[:80]] = row.get(what[:80], 0) + 1
            first = (req.get("options") or [{}])[0].get("id")
            if (resp.get("action") or {}).get("choice") != first or resp.get("meant"):
                turns.append({"tick": d["tick"], "who": T(req.get("name")) or d["key"], "did": what[:120],
                              "meant_to": T(resp.get("meant")) or None, "thought": resp.get("thought"), "said": T(resp.get("say")) or None})
        step = max(1, len(turns) // 40)
        return {"metrics_by_tick": table,
                "choices_by_tick": [{"tick": t, "counts": c} for t, c in sorted(tally.items())],
                "people_who_changed_course": turns[::step][:40]}

    async def ask(self, run_id: int, text: str, lang: str, compare: list[int] | None = None) -> dict:
        run = self.store.run(run_id)
        if not self.llm.live:
            raise LLMError("Questions need an AI provider (set OPENAI_API_KEY).")
        spec = self.store.world(run["world_id"])["spec"]
        rep = self.store.latest_report(run_id)
        msgs = prompts.analyst_messages(spec, self.digest(run_id, compare), self.detail(run_id), T((rep or {}).get("body"), lang) or "",
                                        self.store.chats(run_id, self.ANALYST), text, lang)
        res = await self.llm.chat("report", msgs, max_tokens=2500)
        self._bill(run_id, run["world_id"], "report", [res])
        self.store.add_chat(run_id, run["tick"], "analyst", self.ANALYST, "user", text)
        self.store.add_chat(run_id, run["tick"], "analyst", self.ANALYST, "analyst", res.text.strip())
        return {"reply": res.text.strip()}

    # -- interview ----------------------------------------------------------
    async def chat(self, run_id: int, key: str, text: str, lang: str) -> dict:
        run = self.store.run(run_id)
        world = self.store.world(run["world_id"])
        spec = world["spec"]
        last = self.store.decisions(run_id, key=key, upto_tick=run["tick"], limit=5)
        if not last:
            raise LLMError("This resident has not appeared in the run yet.")
        agent = next((a for a in spec.get("agents", []) if a["id"] == last[-1]["agent"]), None)
        if not agent:
            raise LLMError("Unknown resident.")
        if not self.llm.live:
            raise LLMError("Interviews need an AI provider (set OPENAI_API_KEY).")
        frame = self.store.frame(run_id, run["tick"]) or {}
        memory = [{"clock": d["response"].get("clock") or f"t={d['tick']}", "summary": d["response"].get("summary", ""),
                   "thought": d["response"].get("thought"), "say": T(d["response"].get("say"), lang)} for d in last]
        history = self.store.chats(run_id, key)
        life = None
        focus = spec.get("focus") or {}
        if focus and key == focus.get("key"):          # the person a life world is about: they look back on the whole of this future
            mine = next((x for x in self.futures(run["world_id"], lang)["futures"] if x["id"] == run_id), None)
            if mine:
                labels = {m["id"]: T(m.get("label"), lang) or m["id"] for m in spec.get("metrics", [])}
                path = next((T(o.get("label"), lang) for o in focus.get("options", []) if o["id"] == mine["path"]), mine["path"])
                life = {"path_taken_at_the_start": path, "how_things_moved": {labels.get(m, m): f"{v['start']} -> {v['end']} (lowest {v['low']}, highest {v['high']})" for m, v in mine["figures"].items()},
                        "what_you_decided_along_the_way": [{k: v for k, v in t.items() if k != "tick"} for t in mine["turns"]][-10:],
                        "what_happened_to_you": [h for h in mine["happened"] if not h.get("over")][-8:], "what_people_around_you_said": mine["voices"]}
        msgs = prompts.chat_messages(spec, agent, clock=T((frame.get("view") or {}).get("clock")) or f"t={run['tick']}",
                                     situation=last[-1]["request"].get("situation", ""), memory=memory, history=history, life=life,
                                     text=text, lang=lang, persona=last[-1]["request"].get("persona", ""),
                                     name=T(display_name(resident_names(spec, self.store.residents(run_id)).get(key), last[-1]["request"].get("population")), lang))
        res = await self.llm.chat("agent", msgs, max_tokens=1500, model=run["config"].get("agent_model"))
        self._bill(run_id, run["world_id"], "chat", [res])
        self.store.add_chat(run_id, run["tick"], agent["id"], key, "user", text)
        self.store.add_chat(run_id, run["tick"], agent["id"], key, "resident", res.text.strip())
        return {"reply": res.text.strip(), "agent": agent["id"]}

    # -- free-text intervention --------------------------------------------
    async def interpret(self, run_id: int, text: str, tick: int | None = None) -> dict:
        run = self.store.run(run_id)
        world = self.store.world(run["world_id"])
        params = run["params"]
        if tick is not None:
            snap = self.store.snapshot(run_id, tick)
            if snap is None:
                raise ValueError(f"run {run_id} has no snapshot at tick {tick}")
            params = snap["params"]
        if not self.llm.live:
            raise LLMError("Free-text interventions need an AI provider (set OPENAI_API_KEY).")
        raw, results = await chat_json(self.llm, "agent", prompts.interpret_messages(world["spec"], params, text),
                                       max_tokens=1500, model=run["config"].get("agent_model"))
        self._bill(run_id, run["world_id"], "interpret", results)
        patch = clean_params(world["spec"], raw.get("patch") if isinstance(raw.get("patch"), dict) else {}, runtime_only=True)
        return {"patch": patch, "label": raw.get("label") or {"en": text[:60], "ja": text[:60]}, "explain": raw.get("explain")}


_WORDS = {
    "en": {"gist": "In one line", "happened": "What happened", "figures": "The main figures", "residents": "What the residents did",
           "record": "Against the record", "others": "Next to the other runs", "onway": "On the way", "say": "What this run can and cannot say",
           "can": "It supports", "cannot": "It does not support", "next": "What to try next", "first": "Start with",
           "metric": "Figure", "start": "Start", "high": "Highest", "low": "Lowest", "end": "End", "choice": "Answer", "times": "Times", "share": "Share",
           "gap": "Mean gap", "corr": "Shape (correlation)", "peak": "Peak", "same": "same tick", "ticks": "ticks", "far": "Furthest apart",
           "run": "Run", "differs": "What differs", "this": "this run", "asked": "{a} of {p} people were asked, {q} times in all; {m} answers changed course.",
           "asked_nocast": "{a} residents were asked, {q} times in all; {m} answers changed course.", "meant": " {n} meant to change and did not.",
           "meta": "{ticks} {unit}s, {a} to {b} · residents: {who} · {calls} questions to AI, ${cost}", "not_forecast": "A simulation under stated assumptions, not a forecast.",
           "no_words": "This report lists what was measured. With an API key, a written reading is added.", "ai": "AI", "rules": "fixed rules only"},
    "ja": {"gist": "一言で", "happened": "何が起きたか", "figures": "主な数字", "residents": "住人の動き",
           "record": "実データとの一致", "others": "ほかの実行と並べると", "onway": "途中で起きたこと", "say": "この実行から言えること・言えないこと",
           "can": "言えること", "cannot": "言えないこと", "next": "次に試すなら", "first": "まず 1 つ",
           "metric": "指標", "start": "始め", "high": "最大", "low": "最小", "end": "終わり", "choice": "答え", "times": "回数", "share": "割合",
           "gap": "平均のずれ", "corr": "形（相関）", "peak": "ピーク", "same": "同じティック", "ticks": "ティック", "far": "いちばん離れた所",
           "run": "実行", "differs": "違うところ", "this": "この実行", "asked": "{p} 人のうち {a} 人に、のべ {q} 回聞きました。行動を変える答えは {m} 回です。",
           "asked_nocast": "{a} の住人に、のべ {q} 回聞きました。行動を変える答えは {m} 回です。", "meant": "変えるつもりで変えなかった答えが {n} 回あります。",
           "meta": "{ticks} {unit}、{a} 〜 {b} · 住人：{who} · AI への質問 {calls} 回、${cost}", "not_forecast": "前提を置いたシミュレーションです。予測ではありません。",
           "no_words": "このレポートは、測った数字の一覧です。API キーがあれば、文章での読み解きが加わります。", "ai": "AI", "rules": "規則だけ"},
}


def render_report(facts: dict, words: dict, lang: str) -> str:
    """Lay the report out: short sections in a fixed order, the answer first, one next step last.
    Tables are built from the facts, so every number in them is exact; `words` are the analyst's short pieces
    (any of them may be missing: the section then shows its table alone)."""
    L = _WORDS.get(lang) or _WORDS["en"]
    num = lambda v: "–" if v is None else (f"{v:,.2f}".rstrip("0").rstrip(".") if isinstance(v, float) else f"{v:,}" if isinstance(v, int) else str(v))
    cell = lambda v: str(v).replace("|", "/").replace("\n", " ")
    lines = lambda key, cap: [str(x).strip() for x in (words.get(key) or []) if str(x).strip()][:cap] if isinstance(words.get(key), list) else []
    text = lambda key: str(words.get(key) or "").strip()
    run, res = facts["run"], facts["residents"]
    who = L["ai"] if run["residents_played_by"] == "AI" else L["rules"]
    out = [f"# {facts['world']['title']} — {run['name']}", "",
           L["meta"].format(ticks=run["ticks"], unit=facts["world"]["one_tick"] or "", a=run.get("from") or "", b=run.get("to") or "", who=who, calls=run["calls"], cost=num(run["cost_usd"]))
           + " · " + L["not_forecast"], ""]
    if text("headline"):
        out += [f"**{L['gist']}:** {text('headline')}", ""]
    elif not words:
        out += [L["no_words"], ""]
    if lines("happened", 5):
        out += [f"## {L['happened']}", ""] + [f"{i}. {x}" for i, x in enumerate(lines("happened", 5), 1)] + [""]
    if facts["figures"]:
        out += [f"## {L['figures']}", "", f"| {L['metric']} | {L['start']} | {L['high']} | {L['low']} | {L['end']} |", "|---|---|---|---|---|"]
        out += [f"| {cell(f['metric'])} | {num(f['start'])} | **{num(f['highest'])}** ({cell(f['highest_when'])}) | {num(f['lowest'])} ({cell(f['lowest_when'])}) | {num(f['end'])} |" for f in facts["figures"]] + [""]
    if res["questions"]:
        out += [f"## {L['residents']}", ""] + [f"- {x}" for x in lines("residents", 4)] + ([""] if lines("residents", 4) else [])
        said = (L["asked"] if res.get("people_in_the_world") else L["asked_nocast"]).format(a=num(res["people_asked"]), p=num(res.get("people_in_the_world")), q=num(res["questions"]), m=num(res["answers_that_changed_course"]))
        out += [said + (L["meant"].format(n=num(res["meant_to_change_but_did_not"])) if res["meant_to_change_but_did_not"] else ""), "",
                f"| {L['choice']} | {L['times']} | {L['share']} |", "|---|---|---|"]
        out += [f"| {cell(c['choice'])} | {num(c['times'])} | {c['share_pct']}% |" for c in res["choices"]] + [""]
        for v in [v for v in res["voices"] if v.get("said")][:2]:
            out += [f"> “{v['said']}” — {v['who']}, {v['when']}", ""]
    if facts["against_the_record"]:
        out += [f"## {L['record']}", ""] + ([text("reality"), ""] if text("reality") else [])
        out += [f"| {L['metric']} | {L['gap']} | {L['corr']} | {L['peak']} | {L['far']} |", "|---|---|---|---|---|"]
        for f in facts["against_the_record"][:5]:
            peak = "–" if f["peak_ticks_off"] is None else L["same"] if f["peak_ticks_off"] == 0 else f"{f['peak_ticks_off']:+d} {L['ticks']}"
            out.append(f"| {cell(f['metric'])} | {num(f['mean_gap'])} | {num(f['correlation'])} | {peak} | {cell(f['furthest']['when'])}: {num(f['furthest']['simulated'])} / {num(f['furthest']['recorded'])} |")
        out.append("")
    if facts["other_runs"]:
        out += [f"## {L['others']}", ""] + [f"- {x}" for x in lines("others", 3)] + ([""] if lines("others", 3) else [])
        heads = [f["metric"] for f in facts["figures"][:2]]
        gap = any(o["mean_gap_to_record"] is not None for o in facts["other_runs"])
        out += ["| " + " | ".join([L["run"], L["differs"]] + [f"{cell(h)}: {L['high']} / {L['end']}" for h in heads] + ([L["gap"]] if gap else [])) + " |",
                "|" + "---|" * (2 + len(heads) + (1 if gap else 0))]
        mine = {f["metric"]: f for f in facts["figures"]}
        me = [f"**{run['name']}**", f"({L['this']})"] + [f"{num(mine[h]['highest'])} / {num(mine[h]['end'])}" if h in mine else "–" for h in heads]
        out.append("| " + " | ".join(me + ([num(facts['against_the_record'][0]['mean_gap']) if facts["against_the_record"] else "–"] if gap else [])) + " |")
        for o in facts["other_runs"][:5]:
            byname = {f["metric"]: f for f in o["figures"]}
            row = [cell(o["name"]), cell(o["differs_by"]) or "–"] + [f"{num(byname[h]['highest'])} / {num(byname[h]['end'])}" if h in byname else "–" for h in heads]
            out.append("| " + " | ".join(row + ([num(o["mean_gap_to_record"])] if gap else [])) + " |")
        out.append("")
    if facts["interventions_and_chance"]:
        out += [f"## {L['onway']}", ""] + [f"- {cell(e['when'])}: {e['what']}" for e in facts["interventions_and_chance"][:5]] + [""]
    if lines("can_say", 3) or lines("cannot_say", 3):
        out += [f"## {L['say']}", ""]
        if lines("can_say", 3):
            out += [f"**{L['can']}**", ""] + [f"- {x}" for x in lines("can_say", 3)] + [""]
        if lines("cannot_say", 3):
            out += [f"**{L['cannot']}**", ""] + [f"- {x}" for x in lines("cannot_say", 3)] + [""]
    if lines("next", 3) or text("next_one"):
        out += [f"## {L['next']}", ""] + [f"{i}. {x}" for i, x in enumerate(lines("next", 3), 1)] + [""]
        if text("next_one"):
            out += [f"**{L['first']}:** {text('next_one')}", ""]
    return "\n".join(out).rstrip() + "\n"


_LIFE_WORDS = {
    "en": {"gist": "In one line", "paths": "Where each path tended to lead", "path": "Path", "n": "Futures", "low": "lowest", "high": "highest", "avg": "average",
           "list": "The futures", "future": "Future", "what": "What happened on the way", "turning": "Where futures parted", "constant": "What stayed the same whatever was chosen",
           "regrets": "The shape of regret", "others": "How the people around came to see them", "ask": "Worth asking a future self", "first": "Start with",
           "meta": "{n} possible futures of {who} ({h}) · not a forecast and not advice: a way of looking at what could be.", "none": "No future has been run yet."},
    "ja": {"gist": "一言で", "paths": "それぞれの道の行き先", "path": "道", "n": "未来の数", "low": "最低", "high": "最高", "avg": "平均",
           "list": "未来の一覧", "future": "未来", "what": "途中で起きたこと", "turning": "分かれ目になったこと", "constant": "どの道でも変わらなかったこと",
           "regrets": "後悔の形", "others": "周りの人から見た姿", "ask": "未来の自分に聞いてみるなら", "first": "まず 1 つ",
           "meta": "{who}の {n} 通りの未来（{h}） · 予測でも助言でもありません。こんな未来もあるかもしれない、という眺め方です。", "none": "まだ未来を作っていません。"},
}


def render_life_report(facts: dict, words: dict, lang: str) -> str:
    """The report across all the futures of one person: the answer first, short sections, one next step last."""
    L = _LIFE_WORDS.get(lang) or _LIFE_WORDS["en"]
    cell = lambda v: str(v).replace("|", "/").replace("\n", " ")
    lines = lambda key, cap: [str(x).strip() for x in (words.get(key) or []) if str(x).strip()][:cap] if isinstance(words.get(key), list) else []
    text = lambda key: str(words.get(key) or "").strip()
    out = [f"# {facts['question'] or facts['who']}", "",
           L["meta"].format(n=len(facts["futures"]), who=facts["who"] or "", h=facts.get("horizon") or f"{max([x['ticks'] for x in facts['futures']] or [0])} {facts['one_tick']}"), ""]
    if not facts["futures"]:
        return "\n".join(out + [L["none"]]) + "\n"
    if text("headline"):
        out += [f"**{L['gist']}:** {text('headline')}", ""]
    names = []                                   # the first three outcomes, in the order the world gives them (satisfaction, regret, regard)
    for p in facts["paths"]:
        names += [k for k in p["outcomes_at_the_end"] if k not in names]
    names = names[:3]
    out += [f"## {L['paths']}", "", "| " + " | ".join([L["path"], L["n"]] + [f"{cell(k)} ({L['low']} – {L['high']}, {L['avg']})" for k in names]) + " |", "|" + "---|" * (2 + len(names))]
    for p in facts["paths"]:
        row = [f"**{cell(p['label'])}**", str(p["futures"])]
        for k in names:
            a = p["outcomes_at_the_end"].get(k)
            row.append(f"{a['lowest_end']} – {a['highest_end']}, **{a['average_end']}**" if a else "–")
        out.append("| " + " | ".join(row) + " |")
    out.append("")
    readings = {str(x.get("id")): x.get("reading") for x in words.get("paths") or [] if isinstance(x, dict)} if isinstance(words.get("paths"), list) else {}
    for p in facts["paths"]:
        got = [str(x).strip() for x in (readings.get(p["id"]) or []) if str(x).strip()][:3]
        if got:
            out += [f"**{p['label']}**", ""] + [f"- {x}" for x in got] + [""]
    out += [f"## {L['list']}", "", "| " + " | ".join([L["future"]] + [cell(k) for k in names] + [L["what"]]) + " |", "|" + "---|" * (2 + len(names))]
    for x in facts["futures"][:12]:
        what = "; ".join(h["what"] for h in x["what_happened_to_them"][:2]) or "–"
        out.append("| " + " | ".join([cell(x["name"])] + [str(x["outcomes"][k]["end"]) if k in x["outcomes"] else "–" for k in names] + [cell(what)[:140]]) + " |")
    out.append("")
    for key, cap in (("turning", 4), ("constant", 3), ("regrets", 3), ("others", 3)):
        if lines(key, cap):
            out += [f"## {L[key]}", ""] + [f"- {x}" for x in lines(key, cap)] + [""]
    if lines("ask", 3) or text("next_one"):
        out += [f"## {L['ask']}", ""] + [f"{i}. {x}" for i, x in enumerate(lines("ask", 3), 1)] + [""]
        if text("next_one"):
            out += [f"**{L['first']}:** {text('next_one')}", ""]
    return "\n".join(out).rstrip() + "\n"

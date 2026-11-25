"""Cost estimate for a run, before it starts.

Method: run the model once with no AI (free), count how many times it would
ask a resident, build the real prompt for each question to measure its size,
and multiply by the price table. Output size per answer is taken from earlier
real calls of the same model when there are enough; otherwise it is assumed.
"""
from __future__ import annotations

from ..domain.pricing import approx_tokens, cost_usd, price_for
from ..domain.text import T
from . import prompts
from .engine import merged_config
from .ports import LanguageModel, SandboxFactory, Store
from .worlds import dry_run

ASSUMED_OUT_TOKENS = 380      # answer JSON (~170) plus light reasoning; replaced by observed numbers when available
MEMORY_ALLOWANCE = 220        # memory, recent events and changed-parameter lines added during a real run
REPORT_IN, REPORT_OUT = 3500, 2200
MIN_OBSERVED_CALLS = 20


async def estimate_run(store: Store, sandboxes: SandboxFactory, llm: LanguageModel, prices: dict,
                       world: dict, params: dict | None, config: dict | None, langs) -> dict:
    spec = world["spec"]
    cfg = merged_config(spec, config)
    agents = {a["id"]: a for a in spec.get("agents", [])}
    cap = cfg["max_decisions_per_tick"]
    acc = {"calls": 0, "tokens_in": 0, "capped": 0, "per_agent": {}}

    def on_requests(t: int, reqs: list[dict], frame: dict | None) -> None:
        clock = T(((frame or {}).get("view") or {}).get("clock")) or f"t={t}"
        for i, r in enumerate(reqs):
            if r.get("agent") not in agents:
                continue
            if i >= cap:
                acc["capped"] += 1
                continue
            msgs = prompts.decision_messages(spec, agents[r["agent"]], r, clock=clock, memory=[], events=[], facts=[], langs=langs)
            acc["calls"] += 1
            acc["tokens_in"] += sum(approx_tokens(m["content"]) for m in msgs) + MEMORY_ALLOWANCE
            acc["per_agent"][r["agent"]] = acc["per_agent"].get(r["agent"], 0) + 1

    res = await dry_run(sandboxes, spec, world["code"], params=params, ticks=cfg["ticks"], seed=cfg["seed"],
                        trusted=world["source"] == "builtin", max_requests_per_tick=10_000, on_requests=on_requests)
    agent_model = cfg.get("agent_model") or llm.model_for("agent")
    report_model = llm.model_for("report")

    def row(model: str) -> dict:
        obs = store.observed_tokens("agent", model)
        use_obs = bool(obs and obs["calls"] >= MIN_OBSERVED_CALLS)
        out_per_call = obs["tokens_out"] if use_obs else ASSUMED_OUT_TOKENS
        tin, tout = acc["tokens_in"], int(acc["calls"] * out_per_call)
        c = cost_usd(prices, model, tin, tout)
        return {"model": model, "tokens_in": tin, "tokens_out": tout, "out_per_call": round(out_per_call),
                "basis": "observed" if use_obs else "assumed", "observed_calls": obs["calls"] if obs else 0,
                "cost": c, "low": None if c is None else c * 0.7, "high": None if c is None else c * 1.6,
                "price": price_for(prices, model)}

    models = [agent_model] + [m for m in (prices.get("models") or {}) if m != agent_model]
    report_cost = cost_usd(prices, report_model, REPORT_IN, REPORT_OUT)
    return {
        "ticks": cfg["ticks"], "calls": acc["calls"], "calls_over_cap": acc["capped"],
        "calls_per_agent": acc["per_agent"], "tokens_in": acc["tokens_in"],
        "agent_model": agent_model, "selected": row(agent_model), "by_model": [row(m) for m in models],
        "report": {"model": report_model, "cost": report_cost},
        "ai": "live" if (llm.live and cfg.get("ai") != "mock") else "mock",
        "problems": res["problems"][:5],
        "note": "The count comes from a no-AI rehearsal. Real residents change the course of the run, so the true "
                "number of questions can differ; treat low/high as the likely range.",
    }

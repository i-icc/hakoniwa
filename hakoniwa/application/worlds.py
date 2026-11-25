"""World use cases: register the sample worlds, validate a world in a sandbox."""
from __future__ import annotations

import random
import time

from ..domain.contract import check_code, check_frame, check_spec, default_params
from ..domain.decisions import check_request, default_action, random_action
from .ports import SandboxError, SandboxFactory, Store


def seed_worlds(store: Store, builtin: list[dict]) -> None:
    """Refresh sample worlds, preserving imported versions treated as generated."""
    for w in builtin:
        problems = check_spec(w["spec"]) + check_code(w["code"])
        if problems:
            raise ValueError(f"built-in world '{w['slug']}' is invalid: {problems[:3]}")
        existing = store.world_by_slug(w["slug"])
        if existing is None or existing["source"] == "builtin":
            store.upsert_world(w["slug"], "builtin", w["spec"], w["code"])


async def dry_run(sandboxes: SandboxFactory, spec: dict, code: str, *, params: dict | None = None,
                  ticks: int = 40, seed: int = 1, fuzz: bool = False, trusted: bool = False,
                  max_requests_per_tick: int = 200, on_requests=None) -> dict:
    """Run a model with no AI at all (defaults, or random legal answers when
    `fuzz`), checking every tick. Returns problems plus simple run statistics."""
    problems: list[str] = []
    stats = {"ticks": 0, "requests": 0, "requests_per_tick": [], "ms_per_tick": 0.0, "max_state_chars": 0}
    agent_ids = {a["id"] for a in spec.get("agents", [])}
    p = default_params(spec)
    p.update(params or {})
    rng = random.Random(seed * 7919 + (1 if fuzz else 0))
    sb = None
    frame = None
    t0 = time.time()
    try:
        sb = await sandboxes.open(trusted=trusted, op_timeout=15.0)
        await sb.load(code, p, seed)
        frame = await sb.init()
        problems += [f"tick 0: {e}" for e in check_frame(spec, frame)]
        for t in range(1, ticks + 1):
            res = await sb.tick()
            reqs = res.get("requests") or []
            if len(reqs) > max_requests_per_tick:
                problems.append(f"tick {t}: {len(reqs)} decision requests in one tick (max {max_requests_per_tick}); ask residents less often")
                reqs = reqs[:max_requests_per_tick]
            actions = []
            keys = set()
            for r in reqs:
                err = check_request(r, agent_ids)
                if err:
                    problems.append(f"tick {t}: bad decision request: {err}")
                    continue
                if r["key"] in keys:
                    problems.append(f"tick {t}: duplicate request key '{r['key']}'")
                    continue
                keys.add(r["key"])
                if "default" not in r:
                    problems.append(f"tick {t}: request '{r['key']}' has no default")
                actions.append(random_action(r, rng) if fuzz else default_action(r))
            if on_requests:
                on_requests(t, reqs, frame)
            frame = await sb.apply(actions)
            problems += [f"tick {t}: {e}" for e in check_frame(spec, frame)]
            stats["ticks"] = t
            stats["requests"] += len(actions)
            stats["requests_per_tick"].append(len(actions))
            stats["max_state_chars"] = max(stats["max_state_chars"], len(str(frame["snapshot"]["state"])))
            if len(problems) > 30:
                break
    except SandboxError as e:
        problems.append(f"model error: {e}" + (f"\n{e.trace}" if e.trace else ""))
    finally:
        if sb is not None:
            await sb.close()
    stats["ms_per_tick"] = (time.time() - t0) * 1000 / max(1, stats["ticks"])
    if stats["max_state_chars"] > 400_000:
        problems.append(f"state is too large ({stats['max_state_chars']} chars); use cohorts, not one object per person")
    # de-duplicate while keeping order
    seen, uniq = set(), []
    for pr in problems:
        k = pr.split(": ", 1)[-1]
        if k not in seen:
            seen.add(k)
            uniq.append(pr)
    return {"problems": uniq, "stats": stats, "last_frame": frame}


async def validate_world(sandboxes: SandboxFactory, spec: dict, code: str, trusted: bool = False) -> list[str]:
    """Full gate for a new world: static checks, then a default run and a fuzz run."""
    problems = check_spec(spec) + check_code(code)
    if problems:
        return problems
    ticks = min(int(spec["tick"]["default_ticks"]), 80)
    a = await dry_run(sandboxes, spec, code, ticks=ticks, trusted=trusted)
    problems += a["problems"]
    if not problems:
        b = await dry_run(sandboxes, spec, code, ticks=ticks, fuzz=True, seed=7, trusted=trusted)
        problems += [f"(with random resident behaviour) {x}" for x in b["problems"]]
        if a["stats"]["requests"] == 0:
            problems.append("the model never asked a resident anything: decisions() returned no requests")
        if a["stats"]["ms_per_tick"] > 1500:
            problems.append(f"the model is too slow ({a['stats']['ms_per_tick']:.0f} ms per tick)")
    return problems

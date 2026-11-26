"""World use cases: register the sample worlds, validate a world in a sandbox."""
from __future__ import annotations

import random
import time

from ..domain.contract import check_code, check_frame, check_spec, default_params
from ..domain.decisions import check_request, default_action, random_action
from .ports import SandboxError, SandboxFactory, Store


def seed_worlds(store: Store, builtin: list[dict]) -> None:
    """Sample worlds are refreshed from the package on every start."""
    for w in store.worlds():                     # a build cannot survive a restart: say so instead of "building" for ever
        if w["source"] == "building":
            spec = w["spec"]
            spec["failure"] = {"error": "The server stopped while this world was being built.", "log": [], "cost": None}
            store.update_world(w["id"], w["slug"], "failed", spec, "")
    for w in builtin:
        problems = check_spec(w["spec"]) + check_code(w["code"])
        if problems:
            raise ValueError(f"built-in world '{w['slug']}' is invalid: {problems[:3]}")
        old = store.world_by_slug(w["slug"])
        if old and old["spec"].get("events") and not w["spec"].get("events"):
            w["spec"]["events"] = old["spec"]["events"]
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
        await sb.load(code, {**p, "_data": spec.get("data")}, seed)
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
        if e.infra:
            raise                        # the sandbox is down: not something the model's author can fix
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
    cast = max([len(v) for v in (spec.get("data") or {}).values() if isinstance(v, list)] or [0])
    limit = max(200, cast * 2)           # everyone may hear the same news on the same day
    a = await dry_run(sandboxes, spec, code, ticks=ticks, trusted=trusted, max_requests_per_tick=limit)
    problems += a["problems"]
    if not problems:
        b = await dry_run(sandboxes, spec, code, ticks=ticks, fuzz=True, seed=7, trusted=trusted, max_requests_per_tick=limit)
        problems += [f"(with random resident behaviour) {x}" for x in b["problems"]]
        if a["stats"]["requests"] == 0:
            problems.append("the model never asked a resident anything: decisions() returned no requests")
        if a["stats"]["ms_per_tick"] > 1500:
            problems.append(f"the model is too slow ({a['stats']['ms_per_tick']:.0f} ms per tick)")
    return problems


# -- the checkup: debugging a world before anyone pays for a real run ----------

def reality_pairs(spec: dict) -> list[tuple[str, str]]:
    """(simulated metric, recorded metric) for every recorded series the world carries (ids starting real_)."""
    ids = {m["id"] for m in spec.get("metrics", [])}
    out = []
    for m in spec.get("metrics", []):
        if not m["id"].startswith("real_"):
            continue
        chart = next((c for c in spec.get("charts", []) if m["id"] in c.get("metrics", [])), None)
        sim = m["id"][5:] if m["id"][5:] in ids else next((x for x in (chart or {}).get("metrics", [])
                                                           if not x.startswith("real_") and "real_" + x not in ids), None)
        if sim:
            out.append((sim, m["id"]))
    return out


async def _rehearse(sandboxes: SandboxFactory, spec: dict, code: str, trusted: bool, ticks: int, force: str | None = None) -> dict:
    """One free run with no AI. Residents follow the model's formula, or all take one option whenever it is offered."""
    p = default_params(spec)
    sb = await sandboxes.open(trusted=trusted, op_timeout=15.0)
    rows, asks, keys, defaults, options = [], [], {}, {}, {}
    try:
        await sb.load(code, {**p, "_data": spec.get("data")}, 1)
        await sb.init()
        for _ in range(ticks):
            res = await sb.tick()
            reqs = res.get("requests") or []
            actions = []
            for r in reqs:
                act = default_action(r)
                ids = [o["id"] for o in r.get("options") or []]
                for i, o in enumerate(r.get("options") or []):
                    options.setdefault(o["id"], {"label": o.get("label"), "first": 0, "seen": 0, "formula": 0})
                    options[o["id"]]["seen"] += 1
                    options[o["id"]]["first"] += i == 0
                    options[o["id"]]["formula"] += act.get("choice") == o["id"]
                if force in ids:                       # one person takes it; a group takes it as a whole
                    act = {**act, "choice": force} if r.get("mode", "split") == "pick" else {**act, "weights": {i: float(i == force) for i in ids}}
                keys[r["key"]] = keys.get(r["key"], 0) + 1
                defaults[act.get("choice")] = defaults.get(act.get("choice"), 0) + 1
                actions.append(act)
            asks.append(len(reqs))
            rows.append((await sb.apply(actions)).get("metrics") or {})
    finally:
        await sb.close()
    return {"rows": rows, "asks": asks, "keys": keys, "defaults": defaults, "options": options}


async def checkup(sandboxes: SandboxFactory, spec: dict, code: str, trusted: bool = False) -> dict:
    """Rehearsals with no AI, read for the mistakes that otherwise only show after a paid run:
    answers that change nothing, people who are never asked, figures that never move, recorded and simulated
    figures in different units. `problems` are defects the designer must fix; `notes` are for the observer."""
    T = lambda v: (v.get("en") if isinstance(v, dict) else v) or ""
    ticks = min(int(spec["tick"]["default_ticks"]), 80)
    labels = {m["id"]: T(m.get("label")) or m["id"] for m in spec.get("metrics", [])}
    sims = [m["id"] for m in spec.get("metrics", []) if not m["id"].startswith("real_")]
    base = await _rehearse(sandboxes, spec, code, trusted, ticks)
    problems, notes = [], []
    col = lambda rows, k: [float(r.get(k) or 0) for r in rows]

    # who is asked, and when
    cast = max([len(v) for v in (spec.get("data") or {}).values() if isinstance(v, list)] or [0])
    busy = sum(1 for a in base["asks"] if a)
    if cast and len(base["keys"]) < 0.5 * cast:
        notes.append(f"Only {len(base['keys'])} of the {cast} people are ever asked anything in the rehearsal; the others follow the formula for the whole run.")
    if busy <= 1 and ticks > 5:
        notes.append(f"Every question falls on {busy} tick(s) of {ticks}; nobody reconsiders afterwards.")

    # do the answers matter? everyone takes one option whenever it is offered, and the figures must respond
    # the habit option and whatever the formula picks anyway cannot be told apart from the rehearsal itself
    habit = {o for o, v in base["options"].items() if v["first"] >= 0.9 * v["seen"] or v["formula"] >= 0.9 * v["seen"]}
    span = {k: (max(col(base["rows"], k)) - min(col(base["rows"], k))) or (abs(max(col(base["rows"], k), default=0)) or 1.0) for k in sims}
    effect = {}
    for oid in [o for o in base["options"] if o not in habit][:6]:
        run = await _rehearse(sandboxes, spec, code, trusted, ticks, force=oid)
        gap, where = 0.0, None
        for k in sims:
            d = max((abs(a - b) for a, b in zip(col(run["rows"], k), col(base["rows"], k))), default=0.0) / span[k]
            if d > gap:
                gap, where = d, k
        effect[oid] = {"moves": round(gap, 3), "metric": where}
        name = T(base["options"][oid]["label"]) or oid
        if gap < 0.005:
            problems.append(f"When every resident chooses \"{name}\" ({oid}) whenever it is offered, no metric changes at all: "
                            "apply() does not carry this choice into the rules, or no metric records what it does.")
    still = [k for k in sims if max(col(base["rows"], k)) == min(col(base["rows"], k))]
    if still:
        notes.append("These figures never move in the rehearsal: " + ", ".join(labels[k] for k in still[:5]) + ".")

    # recorded figures: the same unit as the simulated ones? and where is the rule-only rehearsal furthest off?
    far: list = []
    for sim, real in reality_pairs(spec):
        a, b = col(base["rows"], sim)[1:], col(base["rows"], real)[1:]
        ma, mb = sorted(abs(x) for x in a)[len(a) // 2], sorted(abs(x) for x in b)[len(b) // 2]
        if ma > 0 and mb > 0 and not 1 / 8 <= ma / mb <= 8:
            problems.append(f"\"{labels[sim]}\" ({sim}, typically {ma:.3g}) and the recorded \"{labels[real]}\" ({real}, typically {mb:.3g}) "
                            "are not in the same unit: express both the same way (for example an index where the first month is 100).")
            continue
        rng = (max(b) - min(b)) or 1.0
        i = max(range(len(a)), key=lambda j: abs(a[j] - b[j]))
        if abs(a[i] - b[i]) > 0.5 * rng:
            far.append((abs(a[i] - b[i]) / rng, f"\"{labels[sim]}\" at tick {i + 2}: {a[i]:.3g} against a recorded {b[i]:.3g}"))
    if far:
        notes.append("With fixed rules only, the rehearsal is furthest from the record here: " + "; ".join(t for _, t in sorted(far, reverse=True)[:3]) +
                     ". A test result to keep in mind, not something to tune to.")
    top = max(base["defaults"].values(), default=0)
    if base["defaults"] and top >= 0.985 * sum(base["defaults"].values()) and len(base["options"]) > 1:
        notes.append("The formula gives nearly every question the same answer; with no AI the residents never do anything else.")
    return {"problems": problems, "notes": notes, "asked": len(base["keys"]), "cast": cast, "questions": sum(base["asks"]),
            "options": {o: {"label": v["label"], **effect.get(o, {"moves": None})} for o, v in base["options"].items()}}

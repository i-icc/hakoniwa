"""Decision requests (what the model asks a resident) and actions (the answer,
made safe for the model). Pure functions: no I/O."""
from __future__ import annotations

import math
import random
from typing import Any

from .text import T


def check_request(req: Any, agent_ids: set[str]) -> str | None:
    if not isinstance(req, dict):
        return "request must be an object"
    if not isinstance(req.get("key"), str) or not req["key"]:
        return "request.key must be a non-empty string"
    if req.get("agent") not in agent_ids:
        return f"request.agent '{req.get('agent')}' is not in spec.agents"
    mode = req.get("mode", "split")
    if mode not in ("split", "pick"):
        return "request.mode must be 'split' or 'pick'"
    opts = req.get("options")
    if not isinstance(opts, list) or len(opts) < 2 and not req.get("numbers"):
        return "request.options must list at least 2 options (unless only numbers are asked)"
    for o in opts or []:
        if not isinstance(o, dict) or not isinstance(o.get("id"), str):
            return "each option needs an id"
    for n in req.get("numbers") or []:
        if not isinstance(n, dict) or not isinstance(n.get("id"), str) or "min" not in n or "max" not in n:
            return "each numbers[] entry needs id, min, max"
    return None


def default_action(req: dict) -> dict:
    """What the model itself would do with no AI: the request's `default`."""
    d = req.get("default") or {}
    ids = [o["id"] for o in req.get("options") or []]
    raw: dict = {}
    if req.get("mode", "split") == "split":
        raw["weights"] = d.get("weights") or {i: 1 for i in ids}
    else:
        raw["choice"] = d.get("choice") or (ids[0] if ids else None)
    raw["numbers"] = d.get("numbers") or {}
    return normalize_action(req, raw)


def habit_action(req: dict) -> dict:
    """Carrying on exactly as before. Not the same as the default: a default is what the model's formula would do,
    and a formula may react. Uses the request's `habit` when the model gives one; otherwise the first option
    (models list "carry on as before" first) with every number left where it is now."""
    h = req.get("habit")
    if isinstance(h, dict):
        return normalize_action(req, h)
    if req.get("mode", "split") == "split":
        return default_action(req)
    ids = [o["id"] for o in req.get("options") or []]
    return normalize_action(req, {"choice": ids[0] if ids else None,
                                  "numbers": {n["id"]: n["default"] for n in req.get("numbers") or [] if "default" in n}})


def normalize_action(req: dict, raw: dict) -> dict:
    """Turn whatever the AI answered into a valid action for the model."""
    ids = [o["id"] for o in req.get("options") or []]
    d = req.get("default") or {}
    action: dict = {"key": req["key"], "agent": req["agent"]}
    if req.get("mode", "split") == "split":
        w_in = raw.get("weights") if isinstance(raw.get("weights"), dict) else {}
        w = {}
        for i in ids:
            try:
                v = float(w_in.get(i, 0))
            except (TypeError, ValueError):
                v = 0.0
            w[i] = v if math.isfinite(v) and v > 0 else 0.0
        total = sum(w.values())
        if total <= 0:
            w = {i: float((d.get("weights") or {}).get(i, 1)) for i in ids}
            total = sum(w.values()) or 1.0
        action["weights"] = {i: round(v / total, 4) for i, v in w.items()}
    else:
        c = raw.get("choice")
        action["choice"] = c if c in ids else (d.get("choice") if d.get("choice") in ids else (ids[0] if ids else None))
    nums = {}
    raw_n = raw.get("numbers") if isinstance(raw.get("numbers"), dict) else {}
    for n in req.get("numbers") or []:
        base = (d.get("numbers") or {}).get(n["id"], n.get("default", (n["min"] + n["max"]) / 2))
        try:
            v = float(raw_n.get(n["id"], base))
        except (TypeError, ValueError):
            v = float(base)
        if not math.isfinite(v):
            v = float(base)
        nums[n["id"]] = min(float(n["max"]), max(float(n["min"]), v))
    action["numbers"] = nums
    return action


def random_action(req: dict, rng: random.Random) -> dict:
    """Used by validation to fuzz a model with arbitrary (but legal) behaviour."""
    ids = [o["id"] for o in req.get("options") or []]
    raw: dict = {"weights": {i: rng.random() ** 2 for i in ids}, "choice": rng.choice(ids) if ids else None,
                 "numbers": {n["id"]: rng.uniform(n["min"], n["max"]) for n in req.get("numbers") or []}}
    return normalize_action(req, raw)


_MOCK_LINES = {
    "en": ["Following the usual pattern for now.", "No strong reason to change course yet.",
           "Sticking with the default plan.", "Watching the numbers before doing anything different."],
    "ja": ["今のところ、いつも通りに動きます。", "まだ方針を変える理由はありません。",
           "既定の計画のままにします。", "数字を見てから、違う動きを考えます。"],
}


def mock_decision(req: dict, seed: int, tick: int) -> dict:
    """Stand-in for an AI resident: the model's own default, with a small seeded
    wobble. Used with no API key and as the 'no AI' baseline."""
    act = default_action(req)
    rng = random.Random(f"{seed}:{tick}:{req['key']}")
    raw: dict = {"numbers": act.get("numbers", {})}
    if "weights" in act:
        raw["weights"] = {k: max(0.0, v * (1 + rng.uniform(-0.08, 0.08))) for k, v in act["weights"].items()}
    else:
        raw["choice"] = act.get("choice")
    i = rng.randrange(len(_MOCK_LINES["en"]))
    raw["thought"] = "(mock AI) default behaviour of the model"
    raw["say"] = {"en": _MOCK_LINES["en"][i], "ja": _MOCK_LINES["ja"][i]}
    return raw


def summarize_action(req: dict, action: dict, lang: str = "en") -> str:
    """One line describing a decision, for memory and the feed."""
    parts = []
    labels = {o["id"]: T(o.get("label"), lang) or o["id"] for o in req.get("options") or []}
    if "weights" in action:
        top = sorted(action["weights"].items(), key=lambda kv: -kv[1])
        parts.append(", ".join(f"{labels.get(k, k)} {v * 100:.0f}%" for k, v in top if v >= 0.005))
    elif action.get("choice") is not None:
        parts.append(labels.get(action["choice"], str(action["choice"])))
    for n in req.get("numbers") or []:
        if n["id"] in (action.get("numbers") or {}):
            parts.append(f"{T(n.get('label'), lang) or n['id']}: {action['numbers'][n['id']]:g}")
    return "; ".join(p for p in parts if p)

"""The cast of a world: many individuals, each with attributes of their own.

A world designer writes a *recipe* (how many people, which attributes, how they
are distributed, what names to use). This module checks the recipe and draws
the people from it with a seeded random generator, so the same recipe and seed
always give the same cast. Life stories are added later by a language model.
Pure functions: no I/O.
"""
from __future__ import annotations

import csv
import io
import json
import random
from typing import Any

MAX_CAST = 2000


def check_recipe(recipe: Any) -> list[str]:
    e: list[str] = []
    if not isinstance(recipe, dict):
        return ["the cast recipe must be a JSON object"]
    if not isinstance(recipe.get("collection"), str) or not recipe["collection"].isidentifier():
        e.append("cast.collection must be an identifier, e.g. \"households\"")
    size = recipe.get("size")
    if not isinstance(size, int) or not 10 <= size <= MAX_CAST:
        e.append(f"cast.size must be a whole number between 10 and {MAX_CAST}")
    names = recipe.get("names")
    if not isinstance(names, dict) or not names.get("first") or not names.get("last"):
        e.append("cast.names needs non-empty 'first' and 'last' lists")
    if not isinstance(recipe.get("sketch"), str) or len(recipe.get("sketch", "")) < 40:
        e.append("cast.sketch must say, in a few sentences, what each person's life sketch should contain")
    seen = {"id", "name", "story"}
    for i, a in enumerate(recipe.get("attributes") or []):
        if not isinstance(a, dict) or not isinstance(a.get("id"), str):
            e.append(f"cast.attributes[{i}] needs an id")
            continue
        typ = a.get("type")
        if typ == "choice":
            opts = a.get("options")
            if not isinstance(opts, list) or len(opts) < 2 or any(not isinstance(o, dict) or "value" not in o for o in opts):
                e.append(f"cast attribute '{a['id']}': choice needs at least two options with a value")
            elif sum(float(o.get("share", 1)) for o in opts) <= 0:
                e.append(f"cast attribute '{a['id']}': shares must be positive")
        elif typ == "normal":
            if not all(isinstance(a.get(k), (int, float)) for k in ("mean", "sd")):
                e.append(f"cast attribute '{a['id']}': normal needs mean and sd")
        elif typ == "uniform":
            if not all(isinstance(a.get(k), (int, float)) for k in ("min", "max")):
                e.append(f"cast attribute '{a['id']}': uniform needs min and max")
        elif typ == "pick":
            if not isinstance(a.get("values"), list) or not a["values"]:
                e.append(f"cast attribute '{a['id']}': pick needs a list of values")
        elif typ == "scale":
            if a.get("of") not in seen or not isinstance(a.get("spread"), (int, float)):
                e.append(f"cast attribute '{a['id']}': scale needs 'of' (an earlier numeric field) and 'spread'")
        else:
            e.append(f"cast attribute '{a['id']}': unknown type '{typ}' (use choice, normal, uniform, pick or scale)")
        seen.add(a["id"])
        if typ == "choice":
            for o in a.get("options") or []:
                if isinstance(o, dict):
                    seen.update((o.get("with") or {}).keys())
    if not recipe.get("attributes"):
        e.append("cast.attributes must list at least one attribute")
    return e


def _pair(v: Any) -> tuple[str, str]:
    if isinstance(v, (list, tuple)) and v:
        return str(v[0]), str(v[1] if len(v) > 1 else v[0])
    return str(v), str(v)


def build_cast(recipe: dict, seed: int = 1) -> list[dict]:
    """Draw every person in the recipe. Life stories are left empty."""
    rng = random.Random(f"cast:{seed}:{recipe.get('collection')}")
    names = recipe["names"]
    last_first = names.get("order") == "last_first"
    out = []
    for i in range(int(recipe["size"])):
        f_en, f_ja = _pair(rng.choice(names["first"]))
        l_en, l_ja = _pair(rng.choice(names["last"]))
        person: dict = {"id": i, "name": {"en": f"{f_en} {l_en}", "ja": f"{l_ja} {f_ja}" if last_first else f"{f_ja} {l_ja}"}}
        for a in recipe["attributes"]:
            typ = a["type"]
            if typ == "choice":
                opts = a["options"]
                total = sum(float(o.get("share", 1)) for o in opts)
                r, acc, chosen = rng.random() * total, 0.0, opts[-1]
                for o in opts:
                    acc += float(o.get("share", 1))
                    if r <= acc:
                        chosen = o
                        break
                person[a["id"]] = chosen["value"]
                person.update(chosen.get("with") or {})
            elif typ == "normal":
                v = rng.gauss(a["mean"], a["sd"])
                v = max(a.get("min", v), min(a.get("max", v), v))
                person[a["id"]] = round(v, int(a.get("round", 2)))
            elif typ == "uniform":
                v = rng.uniform(a["min"], a["max"])
                person[a["id"]] = int(round(v)) if a.get("integer") else round(v, int(a.get("round", 3)))
            elif typ == "pick":
                person[a["id"]] = rng.choice(a["values"])
            elif typ == "scale":
                base = person.get(a["of"])
                if isinstance(base, (int, float)) and not isinstance(base, bool):
                    v = base * rng.uniform(1 - a["spread"], 1 + a["spread"])
                    person[a["id"]] = int(round(v)) if a.get("integer") else round(v, int(a.get("round", 2)))
        person["story"] = ""
        out.append(person)
    return out


def parse_reference(text: str) -> list[dict]:
    """Rows of real data pasted by the observer: a JSON list of objects (or an object holding one), or CSV with a header."""
    t = (text or "").strip()
    if not t:
        return []
    if t[0] in "[{":
        data = json.loads(t)
        if isinstance(data, dict):
            lists = [v for v in data.values() if isinstance(v, list) and v and isinstance(v[0], dict)]
            if not lists:
                raise ValueError("the reference data has no list of rows")
            data = lists[0]
        if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
            raise ValueError("the reference data must be a list of rows")
        return data[:5000]
    rows = []
    for r in csv.DictReader(io.StringIO(t)):
        row: dict = {}
        for k, v in r.items():
            if k is None:
                continue
            v = (v or "").strip()
            try:
                row[k.strip()] = int(v) if v.lstrip("-").isdigit() else float(v)
            except ValueError:
                row[k.strip()] = v
        rows.append(row)
    if not rows:
        raise ValueError("the reference data has no rows")
    return rows[:5000]

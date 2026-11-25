"""The world contract: what a world spec and a world model must look like,
plus the checks that run before any model code is trusted with a run."""
from __future__ import annotations

import ast
import math
from typing import Any

ALLOWED_MODULES = {
    "math", "random", "statistics", "itertools", "collections",
    "functools", "heapq", "bisect", "copy",
}
FORBIDDEN_NAMES = {
    "eval", "exec", "compile", "open", "input", "globals", "locals", "vars", "dir",
    "getattr", "setattr", "delattr", "breakpoint", "exit", "quit", "help", "memoryview",
    "__import__", "__builtins__",
}
REQUIRED_FUNCTIONS = {"init", "step", "metrics"}
OPTIONAL_FUNCTIONS = {"decisions", "apply", "view", "invariants", "on_params"}
MAX_CODE_CHARS = 60_000


def check_code(code: str) -> list[str]:
    """Static checks on model code. Returns a list of problems (empty = ok)."""
    errors: list[str] = []
    if len(code) > MAX_CODE_CHARS:
        errors.append(f"model code is too long ({len(code)} chars, max {MAX_CODE_CHARS})")
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [f"syntax error at line {e.lineno}: {e.msg}"]
    defined = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] not in ALLOWED_MODULES:
                    errors.append(f"line {node.lineno}: import of '{a.name}' is not allowed")
        elif isinstance(node, ast.ImportFrom):
            if node.level or (node.module or "").split(".")[0] not in ALLOWED_MODULES:
                errors.append(f"line {node.lineno}: import from '{node.module}' is not allowed")
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            errors.append(f"line {node.lineno}: use of '{node.id}' is not allowed")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            errors.append(f"line {node.lineno}: dunder attribute '{node.attr}' is not allowed")
        elif isinstance(node, (ast.ClassDef, ast.AsyncFunctionDef, ast.Await, ast.Global, ast.Nonlocal)):
            errors.append(f"line {node.lineno}: {type(node).__name__} is not allowed (use plain functions and dicts)")
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            defined.add(node.name)
    for name in sorted(REQUIRED_FUNCTIONS - defined):
        errors.append(f"missing required function {name}()")
    return errors


def _is_text(v: Any) -> bool:
    return isinstance(v, str) or (isinstance(v, dict) and isinstance(v.get("en"), str))


def check_spec(spec: Any) -> list[str]:
    """Structural checks on a world spec."""
    e: list[str] = []
    if not isinstance(spec, dict):
        return ["spec must be a JSON object"]
    for k in ("slug", "title", "summary", "tick", "parameters", "agents", "metrics"):
        if k not in spec:
            e.append(f"spec is missing '{k}'")
    if e:
        return e
    if not isinstance(spec["slug"], str) or not spec["slug"].replace("_", "").replace("-", "").isalnum():
        e.append("slug must be letters, digits, '_' or '-'")
    for k in ("title", "summary"):
        if not _is_text(spec[k]):
            e.append(f"{k} must be a string or {{en, ja}}")
    tick = spec["tick"]
    if not isinstance(tick, dict) or not isinstance(tick.get("default_ticks"), int) or tick["default_ticks"] < 1:
        e.append("tick.default_ticks must be a positive integer")
    seen = set()
    for i, p in enumerate(spec["parameters"] if isinstance(spec["parameters"], list) else []):
        pid = p.get("id") if isinstance(p, dict) else None
        if not isinstance(pid, str) or not pid.isidentifier() or pid.startswith("_"):
            e.append(f"parameters[{i}].id must be an identifier not starting with '_'")
            continue
        if pid in seen:
            e.append(f"duplicate parameter id '{pid}'")
        seen.add(pid)
        typ = p.get("type", "number")
        if typ not in ("number", "int", "bool", "choice"):
            e.append(f"parameter '{pid}': unknown type '{typ}'")
        if "default" not in p:
            e.append(f"parameter '{pid}': missing default")
        if typ in ("number", "int") and not isinstance(p.get("default"), (int, float)):
            e.append(f"parameter '{pid}': default must be a number")
        if typ == "choice":
            ids = [c.get("id") for c in p.get("choices", []) if isinstance(c, dict)]
            if not ids or p.get("default") not in ids:
                e.append(f"parameter '{pid}': choices missing or default not among them")
    agent_ids = set()
    for i, a in enumerate(spec["agents"] if isinstance(spec["agents"], list) else []):
        if not isinstance(a, dict) or not isinstance(a.get("id"), str) or not isinstance(a.get("persona"), str):
            e.append(f"agents[{i}] needs id and persona")
        else:
            agent_ids.add(a["id"])
    metric_ids = set()
    for i, m in enumerate(spec["metrics"] if isinstance(spec["metrics"], list) else []):
        if not isinstance(m, dict) or not isinstance(m.get("id"), str):
            e.append(f"metrics[{i}] needs an id")
        else:
            metric_ids.add(m["id"])
    if not metric_ids:
        e.append("spec needs at least one metric")
    for i, c in enumerate(spec.get("charts", [])):
        for mid in c.get("metrics", []):
            if mid not in metric_ids:
                e.append(f"charts[{i}] refers to unknown metric '{mid}'")
    for i, iv in enumerate(spec.get("interventions", [])):
        if not isinstance(iv.get("patch"), dict) or not iv.get("id"):
            e.append(f"interventions[{i}] needs id and patch")
            continue
        for pid in iv["patch"]:
            if pid not in seen:
                e.append(f"intervention '{iv['id']}' patches unknown parameter '{pid}'")
    return e


def default_params(spec: dict) -> dict:
    return {p["id"]: p["default"] for p in spec.get("parameters", [])}


def clean_params(spec: dict, given: dict | None, runtime_only: bool = False) -> dict:
    """Coerce and clamp user-supplied parameter values against the spec."""
    out: dict = {}
    by_id = {p["id"]: p for p in spec.get("parameters", [])}
    for pid, val in (given or {}).items():
        p = by_id.get(pid)
        if not p:
            continue
        if runtime_only and p.get("runtime") is False:
            continue
        typ = p.get("type", "number")
        try:
            if typ == "bool":
                v: Any = bool(val)
            elif typ == "choice":
                v = val if val in [c["id"] for c in p.get("choices", [])] else p["default"]
            else:
                v = float(val)
                if not math.isfinite(v):
                    continue
                if "min" in p:
                    v = max(float(p["min"]), v)
                if "max" in p:
                    v = min(float(p["max"]), v)
                if typ == "int":
                    v = int(round(v))
            out[pid] = v
        except (TypeError, ValueError):
            continue
    return out


def check_frame(spec: dict, frame: dict) -> list[str]:
    """Checks on one tick's output from the model."""
    errs: list[str] = []
    declared = {m["id"] for m in spec.get("metrics", [])}
    got = frame.get("metrics") or {}
    for mid in declared - set(got):
        errs.append(f"metrics() did not return declared metric '{mid}'")
    for k, v in got.items():
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v):
            errs.append(f"metric '{k}' is not a finite number: {v!r}")
    view = frame.get("view") or {}
    ids = set()
    for n in view.get("nodes") or []:
        if not isinstance(n, dict) or "id" not in n or "x" not in n or "y" not in n:
            errs.append("view node needs id, x, y")
            break
        ids.add(n["id"])
    for link in view.get("links") or []:
        if link.get("a") not in ids or link.get("b") not in ids:
            errs.append(f"view link {link.get('a')}->{link.get('b')} refers to an unknown node")
            break
    for v in frame.get("violations") or []:
        errs.append(f"invariant violated: {v}")
    return errs

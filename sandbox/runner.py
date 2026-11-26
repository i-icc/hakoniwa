"""Hakoniwa sandbox runner.

Runs ONE world model (untrusted, possibly AI-written Python) and talks to the
engine over stdin/stdout, one JSON object per line.

It is meant to run inside a locked-down container (no network, read-only
filesystem, non-root, memory/CPU limits). The restricted builtins below are a
second layer, not the security boundary.

Model contract (all functions are module-level in the model code):

    init(params, rng) -> state                      required
    step(state, params, rng, t) -> events | None    required, mutates state
    decisions(state, params, t) -> requests | None  optional
    apply(state, params, rng, t, action) -> events | None   optional
    metrics(state, params, t) -> {id: number}       required
    view(state, params, t) -> {clock, nodes, links} optional
    invariants(state, params, t) -> [str]           optional
    on_params(state, params, patch, t) -> events | None     optional
"""
import builtins
import json
import random
import sys
import traceback

ALLOWED_MODULES = {
    "math", "random", "statistics", "itertools", "collections",
    "functools", "heapq", "bisect", "copy",
}

SAFE_BUILTINS = [
    "abs", "all", "any", "bool", "dict", "divmod", "enumerate", "filter",
    "float", "frozenset", "int", "isinstance", "iter", "len", "list", "map",
    "max", "min", "next", "pow", "range", "repr", "reversed", "round", "set",
    "sorted", "str", "sum", "tuple", "zip", "print",
    "Exception", "ValueError", "KeyError", "IndexError", "TypeError",
    "ZeroDivisionError", "StopIteration", "RuntimeError", "ArithmeticError",
    "True", "False", "None",
]


def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    root = name.split(".")[0]
    if level != 0 or root not in ALLOWED_MODULES:
        raise ImportError(f"import of '{name}' is not allowed in a world model")
    return builtins.__import__(name, globals, locals, fromlist, level)


def _make_namespace():
    safe = {k: getattr(builtins, k) for k in SAFE_BUILTINS if hasattr(builtins, k)}
    safe["__import__"] = _safe_import
    # model print() goes to stderr so it never corrupts the protocol stream
    safe["print"] = lambda *a, **k: builtins.print(*a, file=sys.stderr, **{x: y for x, y in k.items() if x != "file"})
    return {"__builtins__": safe, "__name__": "world_model"}


class World:
    def __init__(self):
        self.ns = None
        self.params = {}
        self.rng = random.Random(0)
        self.state = None
        self.t = 0

    def fn(self, name, required=False):
        f = self.ns.get(name) if self.ns else None
        if f is None and required:
            raise RuntimeError(f"model is missing required function {name}()")
        return f

    # -- protocol ops -----------------------------------------------------
    def op_load(self, msg):
        self.ns = _make_namespace()
        exec(compile(msg["code"], "<world_model>", "exec"), self.ns)
        self.params = dict(msg.get("params") or {})
        seed = int(msg.get("seed", 0))
        self.params["_seed"] = seed
        self.rng = random.Random(seed)
        for name in ("init", "step", "metrics"):
            self.fn(name, required=True)
        return {"functions": sorted(k for k, v in self.ns.items() if callable(v) and not k.startswith("_"))}

    def op_init(self, msg):
        self.t = 0
        self.state = self.fn("init", True)(self.params, self.rng)
        if not isinstance(self.state, dict):
            raise RuntimeError("init() must return a dict")
        return self._frame(events=[])

    def op_tick(self, msg):
        self.t += 1
        events = self.fn("step", True)(self.state, self.params, self.rng, self.t) or []
        f = self.fn("decisions")
        requests = (f(self.state, self.params, self.t) or []) if f else []
        return {"t": self.t, "events": list(events), "requests": list(requests)}

    def op_apply(self, msg):
        events = []
        f = self.fn("apply")
        for action in msg.get("actions") or []:
            if f:
                ev = f(self.state, self.params, self.rng, self.t, action)
                if ev:
                    events.extend(ev)
        return self._frame(events=events)

    def op_set_params(self, msg):
        patch = dict(msg.get("patch") or {})
        self.params.update(patch)
        events = []
        f = self.fn("on_params")
        if f and self.state is not None:
            events = f(self.state, self.params, patch, self.t) or []
        return {"events": list(events), "params": self._public_params()}

    def op_restore(self, msg):
        self.state = msg["state"]
        self.t = int(msg["t"])
        if msg.get("params") is not None:
            kept = {k: v for k, v in self.params.items() if k.startswith("_")}     # seed and world data stay
            self.params = dict(msg["params"])
            for k, v in kept.items():
                self.params.setdefault(k, v)
        r = msg["rng"]
        self.rng.setstate((r[0], tuple(r[1]), r[2]))
        return {"t": self.t}

    def op_frame(self, msg):
        return self._frame(events=[])

    # -- helpers ----------------------------------------------------------
    def _public_params(self):
        return {k: v for k, v in self.params.items() if not k.startswith("_")}

    def _frame(self, events):
        metrics = self.fn("metrics", True)(self.state, self.params, self.t) or {}
        v = self.fn("view")
        view = (v(self.state, self.params, self.t) or {}) if v else {}
        inv = self.fn("invariants")
        violations = (inv(self.state, self.params, self.t) or []) if inv else []
        st = self.rng.getstate()
        return {
            "t": self.t,
            "events": list(events),
            "metrics": metrics,
            "view": view,
            "violations": [str(x) for x in violations],
            "snapshot": {"state": self.state, "rng": [st[0], list(st[1]), st[2]]},
        }


def main():
    world = World()
    out = sys.stdout
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            op = msg.get("op")
            if op == "quit":
                break
            handler = getattr(world, "op_" + str(op), None)
            if handler is None:
                raise RuntimeError(f"unknown op {op!r}")
            res = handler(msg) or {}
            res["ok"] = True
            text = json.dumps(res, allow_nan=False, ensure_ascii=False)
        except Exception as e:  # report every model error back to the engine
            tb = traceback.format_exc(limit=6)
            text = json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}", "trace": tb[-1800:]})
        out.write(text + "\n")
        out.flush()


if __name__ == "__main__":
    main()

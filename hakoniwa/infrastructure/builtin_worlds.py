"""Sample worlds shipped with the tool (hakoniwa/worlds/<slug>/spec.json + model.py)."""
from __future__ import annotations

import json

from .config import PKG

WORLDS_DIR = PKG / "worlds"


def load_builtin_worlds() -> list[dict]:
    out = []
    for d in sorted(WORLDS_DIR.iterdir()):
        spec_p, code_p = d / "spec.json", d / "model.py"
        if spec_p.exists() and code_p.exists():
            out.append({"slug": d.name, "spec": json.loads(spec_p.read_text()), "code": code_p.read_text()})
    return out

"""Small text helpers shared by every layer. Pure functions."""
from __future__ import annotations

import json
import re

LANG_NAMES = {"en": "English", "ja": "Japanese"}


def T(v, lang: str = "en") -> str:
    """Pick a language from a {en, ja} text object (or pass a plain string through)."""
    if isinstance(v, dict):
        return str(v.get(lang) or v.get("en") or next(iter(v.values()), ""))
    return "" if v is None else str(v)


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of a model reply (tolerates code fences and chatter)."""
    t = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", t, re.S)
    if m:
        t = m.group(1)
    start = t.find("{")
    if start < 0:
        raise ValueError("no JSON object in reply")
    depth, in_str, esc = 0, False, False
    for i in range(start, len(t)):
        ch = t[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(t[start:i + 1])
    raise ValueError("unterminated JSON object in reply")


def fenced_blocks(text: str, lang: str) -> list[str]:
    """Bodies of every ```lang fenced block, in order."""
    return [m.group(1) for m in re.finditer(r"```" + lang + r"\s*\n(.*?)\n```", text, re.S)]


def fenced_block(text: str, lang: str) -> str | None:
    """Return the body of the first ```lang fenced block."""
    m = re.search(r"```" + lang + r"\s*\n(.*?)\n```", text, re.S)
    return m.group(1) if m else None

"""All prompts. Internal prompts are English; residents' lines are produced in
every content language (default: English and Japanese) in the same call."""
from __future__ import annotations

import json

from ..domain.text import LANG_NAMES, T


def _say_schema(langs) -> str:
    return "{" + ", ".join(f'"{lg}": "one short line in {LANG_NAMES.get(lg, lg)}"' for lg in langs) + "}"


DECISION_SYSTEM = """You play residents of a small simulated world ("hakoniwa").
The world's numbers are computed by a mathematical model. You never change numbers directly.
Your only job: decide how the person or group you play behaves right now, in character.

Rules:
- Decide from the persona's own interests, habits and limits, using only what they can see.
- Different people in a group behave differently. For a group, answer with shares across the options.
- Be realistic, not optimal. People are impatient, stubborn, tired, proud, short of money.
- Do not copy the default. Use it only as a hint of what "nothing special" looks like.
- Reply with ONE JSON object and nothing else."""


def decision_messages(spec: dict, agent: dict, req: dict, *, clock: str, memory: list[dict],
                      events: list[str], facts: list[str], langs, name: str = "") -> list[dict]:
    mode = req.get("mode", "split")
    lines = [
        f"WORLD: {T(spec.get('title'))}. {T(spec.get('summary'))}",
        f"TIME: {clock}",
        f"YOU PLAY: {T(agent.get('name'))} - {agent.get('persona', '')}",
    ]
    if name:
        lines.append(f"KNOWN AS: {name}")
    if req.get("population"):
        lines.append(f"GROUP SIZE: about {int(req['population']):,} people (answer for the whole group)")
    if req.get("situation"):
        lines.append(f"SITUATION: {req['situation']}")
    if req.get("facts"):
        lines.append("NUMBERS YOU CAN SEE: " + json.dumps(req["facts"], ensure_ascii=False))
    if facts:
        lines.append("WHAT HAS CHANGED IN THE WORLD: " + "; ".join(facts))
    if events:
        lines.append("RECENT EVENTS:\n" + "\n".join(f"- {e}" for e in events))
    if memory:
        lines.append("YOUR EARLIER DECISIONS:\n" + "\n".join(
            f"- [{m['clock']}] {m['summary']}" + (f' You said: "{m["say"]}"' if m.get("say") else "") for m in memory))
    lines.append(f"QUESTION: {req.get('question', 'What do you do now?')}")
    if req.get("options"):
        lines.append("OPTIONS:\n" + "\n".join(
            f"- {o['id']}: {T(o.get('label'))}" + (f" ({o['note']})" if o.get("note") else "") for o in req["options"]))
    schema: list[str] = ['"thought": "1-2 sentences of private reasoning, in English"']
    if req.get("options"):
        if mode == "split":
            ids = ", ".join(f'"{o["id"]}": 0.0' for o in req["options"])
            schema.append(f'"weights": {{{ids}}}  // shares of the group choosing each option, summing to 1')
        else:
            ids = " | ".join(o["id"] for o in req["options"])
            schema.append(f'"choice": "{ids}"')
    if req.get("numbers"):
        nums = ", ".join(f'"{n["id"]}": <{n["min"]}..{n["max"]}>' for n in req["numbers"])
        lines.append("NUMBERS TO SET:\n" + "\n".join(
            f"- {n['id']}: {T(n.get('label'))} (from {n['min']} to {n['max']}" +
            (f", now {n['default']}" if "default" in n else "") + ")" for n in req["numbers"]))
        schema.append(f'"numbers": {{{nums}}}')
    schema.append(f'"say": {_say_schema(langs)}  // what they would say out loud; natural, specific, under 25 words')
    if req.get("default"):
        lines.append("DEFAULT (what happens with no special reaction): " + json.dumps(req["default"], ensure_ascii=False))
    lines.append("Reply with this JSON object:\n{\n  " + ",\n  ".join(schema) + "\n}")
    return [{"role": "system", "content": DECISION_SYSTEM}, {"role": "user", "content": "\n\n".join(lines)}]


CHAT_SYSTEM = """You are a resident of a small simulated world, being interviewed by an observer from outside.
Stay fully in character. Speak from your own situation and the numbers you can see. Do not invent world facts
that contradict what you are given. Keep answers short (2-5 sentences). Answer in {lang}."""


def chat_messages(spec: dict, agent: dict, *, clock: str, situation: str, memory: list[dict],
                  history: list[dict], text: str, lang: str, name: str = "") -> list[dict]:
    ctx = [
        f"WORLD: {T(spec.get('title'))}. {T(spec.get('summary'))}",
        f"TIME: {clock}",
        f"YOU ARE: {T(agent.get('name'))} - {agent.get('persona', '')}",
    ]
    if name:
        ctx.append(f"YOU ARE KNOWN AS: {name}")
    if situation:
        ctx.append(f"YOUR CURRENT SITUATION: {situation}")
    if memory:
        ctx.append("YOUR RECENT DECISIONS:\n" + "\n".join(f"- [{m['clock']}] {m['summary']}" for m in memory))
    msgs = [{"role": "system", "content": CHAT_SYSTEM.format(lang=LANG_NAMES.get(lang, lang)) + "\n\n" + "\n".join(ctx)}]
    for h in history[-8:]:
        msgs.append({"role": "user" if h["role"] == "user" else "assistant", "content": h["text"]})
    msgs.append({"role": "user", "content": text})
    return msgs


INTERPRET_SYSTEM = """You translate an observer's free-text intervention into parameter changes for a simulated world.
You may only change the listed parameters, within their ranges. If the request cannot be expressed with them,
return an empty patch and explain why. Reply with ONE JSON object:
{"patch": {"<param id>": <new value>, ...}, "label": {"en": "...", "ja": "..."}, "explain": {"en": "...", "ja": "..."}}"""


def interpret_messages(spec: dict, params: dict, text: str) -> list[dict]:
    rows = []
    for p in spec.get("parameters", []):
        if p.get("runtime") is False:
            continue
        rng = f" range {p.get('min')}..{p.get('max')}" if "min" in p else ""
        ch = " choices " + "/".join(c["id"] for c in p.get("choices", [])) if p.get("type") == "choice" else ""
        rows.append(f"- {p['id']} ({p.get('type', 'number')}{rng}{ch}) now {params.get(p['id'])}: {T(p.get('label'))}")
    user = (f"WORLD: {T(spec.get('title'))}. {T(spec.get('summary'))}\n\nPARAMETERS YOU MAY CHANGE:\n" +
            "\n".join(rows) + f"\n\nOBSERVER'S REQUEST: {text}")
    return [{"role": "system", "content": INTERPRET_SYSTEM}, {"role": "user", "content": user}]


REPORT_SYSTEM = """You are the analyst of a small simulated world. Write a short, honest report for the observer.
The numbers come from a mathematical model with stated assumptions; the behaviour comes from AI-played residents.
Never present the result as a forecast of the real world. Say what happened, why (linking numbers to residents'
decisions), what the interventions changed, and which assumptions the conclusion depends on most.
Reply with ONE JSON object: {{{fields}}} where each value is Markdown (headings, short bullets, under 350 words)."""


def report_messages(spec: dict, digest: dict, langs) -> list[dict]:
    fields = ", ".join(f'"{lg}": "report in {LANG_NAMES.get(lg, lg)}"' for lg in langs)
    return [{"role": "system", "content": REPORT_SYSTEM.format(fields=fields)},
            {"role": "user", "content": "RUN DIGEST (JSON):\n" + json.dumps(digest, ensure_ascii=False)}]


# -- world designer ---------------------------------------------------------

DESIGNER_SYSTEM = """You design small simulated worlds ("hakoniwa") from a scenario description.

A world has two parts:
1. spec  - a JSON document describing parameters, residents (agents), metrics, charts and interventions.
2. model - plain Python (standard library only) that IS the world's mathematics.

Division of labour, which you must respect:
- The MODEL owns every number: stocks, flows, queues, money, capacities, travel times, probabilities.
  It advances the world one tick at a time with equations. It must conserve what should be conserved
  (people, money, goods) and stay finite and non-negative where that is required.
- AI RESIDENTS own only behaviour. At chosen moments the model asks a resident (one person or a cohort)
  a question with options; the answer comes back as shares across options ("split"), a single choice
  ("pick"), and/or a few bounded numbers. The model then applies that answer through its equations.
- Ask residents sparingly: at the start, when something they can observe changes materially, and on a
  slow regular rhythm. Never every tick for every resident. Between questions their last answer stays in force.
- Large populations are cohorts (archetype x place), never one object per person. Add 2-4 named
  individuals when it helps the story.
- Mark every number you did not get from a source as an assumption in the parameter's "source" field.

MODEL CONTRACT (Python, module-level functions, no classes, no I/O, no imports beyond
math, random, statistics, itertools, collections, functools, heapq, bisect, copy):

  init(params, rng) -> state
      Build the initial state: a plain JSON-serialisable dict (numbers, strings, lists, dicts; string keys).
  step(state, params, rng, t) -> list of events (or None)
      Advance one tick (t starts at 1). Mutate state in place. Use `rng` (a random.Random) for all randomness.
      For exogenous randomness that must be identical across branches (arrivals, weather), use
      random.Random(params["_seed"] * 100003 + t) instead of rng.
  decisions(state, params, t) -> list of requests (or None)
      Called right after step. Return the questions to ask residents this tick.
  apply(state, params, rng, t, action) -> list of events (or None)
      Called once per answered request. Store the answer in state so later steps use it.
  metrics(state, params, t) -> dict {metric id: finite number}   (exactly the ids declared in the spec)
  view(state, params, t) -> {"clock": "text" or {"en","ja"}, "nodes": [...], "links": [...]}
      A small map of the world for the viewer. Node: {"id", "label": {"en","ja"}, "x": 0-100, "y": 0-100,
      "value": number, "max": number, "sub": {"en","ja"} (optional caption), "status": "ok"|"warn"|"crit" (optional)}.
      Link: {"a": node id, "b": node id, "value": number, "max": number}.
  invariants(state, params, t) -> list of strings (empty when all conservation checks hold)   [optional but expected]
  on_params(state, params, patch, t) -> list of events (or None)   [optional; called when the observer changes parameters mid-run]

  Event: {"kind": "info"|"alert"|"milestone", "text": {"en": "...", "ja": "..."}, "node": optional node id,
          "fact": optional {"subject": str, "predicate": str, "object": any}}
  Request: {"key": unique stable id of who is asked, e.g. "inn_owners" or "commuters:kokubunji:flex",
            "name": optional {"en","ja"} personal name; give one when several requests share the same agent (else the tool picks a name),
            "agent": id of an entry in spec.agents, "node": optional node id where they are,
            "population": optional cohort size, "mode": "split" | "pick",
            "situation": one or two English sentences with the concrete numbers they can observe,
            "facts": {small dict of numbers}, "question": English question,
            "options": [{"id", "label": {"en","ja"}, "note": optional}],
            "numbers": optional [{"id", "label": {"en","ja"}, "min", "max", "default"}],
            "default": {"weights": {...}} or {"choice": "..."} plus optional "numbers": {...}}
      `default` is REQUIRED: it is what happens with no AI at all, and the model must run sensibly on defaults alone.
  Action passed to apply: {"key", "agent", "weights": {option id: share summing to 1} or "choice": id, "numbers": {...}}

SPEC (JSON):
{
  "slug": "snake_case_id",
  "title": {"en": "...", "ja": "..."}, "summary": {"en": "...", "ja": "..."},
  "tick": {"unit": {"en": "week", "ja": "週"}, "default_ticks": 52},
  "questions": [{"en": "What the observer may want to find out", "ja": "..."}],
  "assumptions": [{"en": "...", "ja": "..."}],
  "parameters": [{"id", "label": {"en","ja"}, "type": "number"|"int"|"bool"|"choice", "default", "min", "max", "step",
                  "unit", "group": {"en","ja"}, "source": "assumed" or a URL or a citation, "runtime": true|false,
                  "choices": [{"id", "label": {"en","ja"}}] (for choice)}],
  "agents": [{"id", "name": {"en","ja"}, "kind": "cohort"|"individual", "persona": "English, 1-3 sentences: who they are, what they want, their limits"}],
  "metrics": [{"id", "label": {"en","ja"}, "unit": "text" or {"en","ja"}, "format": "int"|"float"|"pct"|"money", "good": "up"|"down"|"none", "headline": true|false}],
  "charts": [{"id", "title": {"en","ja"}, "metrics": ["metric ids sharing one unit"]}],
  "interventions": [{"id", "label": {"en","ja"}, "description": {"en","ja"}, "patch": {"param id": value}}]
}
Include 8-25 parameters (always: population/scale knobs the observer may want to change), 4-10 agents,
6-14 metrics (3-5 headline), 3-6 charts, 3-6 interventions that are real "what if" events for this scenario.
"runtime": false marks parameters that only make sense before the run starts.

OUTPUT FORMAT: first a ```json fenced block with the spec, then a ```python fenced block with the model. Nothing else."""


def designer_messages(scenario: str, research: str, example_spec: dict, example_code: str) -> list[dict]:
    user = [f"SCENARIO FROM THE OBSERVER:\n{scenario}"]
    if research:
        user.append("RESEARCH NOTES (use these numbers, cite them in parameter 'source' fields):\n" + research)
    else:
        user.append("No research notes are available. Use your own knowledge and mark every such number as \"assumed\".")
    user.append("A COMPLETE WORKING EXAMPLE of another world, for the format and the style of the mathematics "
                "(do not copy its content):\n```json\n" + json.dumps(example_spec, ensure_ascii=False, indent=1) +
                "\n```\n```python\n" + example_code + "\n```")
    user.append("Now design the world for the observer's scenario. Write titles, labels and descriptions in both "
                "English and Japanese. Keep the model under 450 lines.")
    return [{"role": "system", "content": DESIGNER_SYSTEM}, {"role": "user", "content": "\n\n".join(user)}]


def repair_messages(base: list[dict], reply: str, problems: list[str]) -> list[dict]:
    return base + [
        {"role": "assistant", "content": reply},
        {"role": "user", "content": "The world failed validation in the sandbox. Problems:\n" +
         "\n".join(f"- {p}" for p in problems[:25]) +
         "\n\nFix them and output the COMPLETE corrected spec and model again, in the same two fenced blocks."},
    ]


RESEARCH_PROMPT = """Collect the real-world numbers needed to build a small quantitative simulation of this scenario.
Search the web. Return a compact list: one fact per line as `name: value (unit) - source URL - date of the figure`.
Cover population/scale, capacities, prices, frequencies, costs, seasonal patterns. 12-25 facts. If a number
cannot be found, write `name: NOT FOUND` so the designer marks it as an assumption.

SCENARIO:
{scenario}"""


SCENARIO_SYSTEM = """You help an observer write the scenario for a small simulated world.
The simulator works like this: a mathematical model moves the numbers one tick at a time, and AI plays the residents
(individuals or groups) who make decisions. Turn the observer's rough idea into a clear scenario of 5-8 sentences that a
world designer can build from. Cover, in plain prose (no headings, no bullet points):
- the place and its scale (how many people, shops, vehicles, ...), with concrete numbers where sensible;
- the time span and the size of one step (minutes, days, weeks);
- who the residents are and what each kind of resident decides;
- what flows or stocks matter (people, money, queues, capacity);
- two or three "what if" events the observer may want to try;
- what the observer wants to find out.
Keep the observer's own details. Add plausible specifics where they left gaps; do not invent real statistics.
If the idea is empty, propose one fresh, concrete, everyday situation that would be interesting to watch.
Write in {lang}. Reply with the scenario text only."""


def scenario_messages(idea: str, lang: str) -> list[dict]:
    return [{"role": "system", "content": SCENARIO_SYSTEM.format(lang=LANG_NAMES.get(lang, lang))},
            {"role": "user", "content": idea.strip() or "(no idea given - propose one)"}]

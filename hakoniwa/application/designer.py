"""World designer: scenario text -> an automaton world with a cast of individuals.

Steps: optional web research -> design (spec, model, cast recipe) -> draw the
cast -> validate in a sandbox (static checks, a default run, a random-behaviour
run) -> repair, up to a few rounds -> write each person's life sketch.
Real data supplied by the observer travels with the world as reference rows.
Runs as a background job so the viewer can show progress. The world gets its
id the moment building starts (source "building"), so several can be built side
by side and each has a page of its own; a build that fails stays as "failed".
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field

from ..domain.cast import build_cast, check_recipe, parse_reference
from ..domain.contract import LIFE_KEY, chance_events, check_code, check_spec, clean_life, life_focus, life_problems
from ..domain.pricing import cost_usd
from ..domain.text import fenced_block, fenced_blocks
from . import prompts
from .ports import LanguageModel, LLMError, LLMResult, SandboxError, SandboxFactory, Store, chat_json
from .worlds import checkup, dry_run, validate_world

MAX_REPAIRS = 3
DESIGN_MAX_TOKENS = 40_000


@dataclass
class DesignJob:
    id: int
    scenario: str
    status: str = "running"          # running | done | failed
    stage: str = "starting"
    log: list[dict] = field(default_factory=list)
    world_id: int | None = None
    slug: str | None = None
    error: str | None = None
    cost: float = 0.0
    calls: int = 0
    started: float = field(default_factory=time.time)
    billed: list = field(default_factory=list)
    reference: list = field(default_factory=list)
    based_on: dict | None = None     # the world this one grew out of: {slug, title}
    placeholder: str = ""            # the provisional slug the world carries while it is being built
    life: dict | None = None         # set when the world is about one person: the protagonist, their paths, the question

    def public(self) -> dict:
        return {"id": self.id, "status": self.status, "stage": self.stage, "log": self.log[-30:], "world_id": self.world_id,
                "slug": self.slug, "error": self.error, "cost": round(self.cost, 4), "calls": self.calls,
                "seconds": round(time.time() - self.started)}


class WorldDesigner:
    def __init__(self, store: Store, sandboxes: SandboxFactory, llm: LanguageModel, prices: dict,
                 example_slug: str = "tp_2020"):
        self.store, self.sandboxes, self.llm, self.prices = store, sandboxes, llm, prices
        self.example_slug = example_slug
        self.jobs: dict[int, DesignJob] = {}
        self.on_milestone = None       # called when a world is finished (or its build has failed)
        self._tasks: set[asyncio.Task] = set()
        self._next = 1

    def start(self, scenario: str, reference_text: str = "", based_on: int | None = None, life: dict | None = None) -> DesignJob:
        job = DesignJob(id=self._next, scenario=scenario.strip(), life=clean_life(life))
        parent = self.store.world(based_on) if based_on else None
        if parent:
            job.based_on = {"slug": parent["slug"], "title": parent["spec"].get("title")}
        # the world exists from now on: a placeholder under a provisional slug, rewritten in place when the build ends
        short = " ".join(job.scenario.split())[:48] + ("…" if len(job.scenario) > 48 else "")
        title = job.life["question"] if job.life and job.life["question"].get("en") else {"en": short, "ja": short}
        job.placeholder = f"building_{int(job.started * 1000)}_{job.id}"
        job.world_id = self.store.upsert_world(job.placeholder, "building", {
            "slug": job.placeholder, "title": title, "summary": {"en": "", "ja": ""},
            "scenario": {"en": job.scenario, "ja": job.scenario}, "tick": {"unit": {"en": "tick", "ja": "ティック"}, "default_ticks": 1},
            "parameters": [], "agents": [], "metrics": [], "charts": [], "interventions": [], "based_on": job.based_on}, "")
        job.reference = parse_reference(reference_text)      # raises ValueError on bad input, before any AI call
        self._next += 1
        self.jobs[job.id] = job
        task = asyncio.create_task(self._run(job))
        task.job_id = job.id
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job

    async def draft_scenario(self, idea: str, lang: str) -> dict:
        """Turn a rough idea into a scenario text the designer can build from."""
        if not self.llm.live:
            raise LLMError("Drafting a scenario needs an AI provider. Set OPENAI_API_KEY in .env and restart.")
        res = await self.llm.chat("draft", prompts.scenario_messages(idea, lang), max_tokens=3000)
        cost = cost_usd(self.prices, res.model, res.tokens_in, res.tokens_out)
        self.store.add_llm_call(None, None, "draft", res.model, res.tokens_in, res.tokens_out, cost, res.ms, res.estimated)
        return {"scenario": res.text.strip(), "model": res.model, "cost": cost}

    async def write_events(self, world_id: int) -> list[dict]:
        """A deck of chance events for a world that has none (or a new one in its place), kept with the world."""
        if not self.llm.live:
            raise LLMError("This needs an AI provider. Set OPENAI_API_KEY in .env and restart.")
        world = self.store.world(world_id)
        spec = world["spec"]
        data, results = await chat_json(self.llm, "draft", prompts.events_messages(spec), max_tokens=5000)
        for res in results:
            self.store.add_llm_call(None, world_id, "draft", res.model, res.tokens_in, res.tokens_out,
                                    cost_usd(self.prices, res.model, res.tokens_in, res.tokens_out), res.ms, res.estimated)
        deck = chance_events({**spec, "events": data.get("events")})
        if not deck:
            raise LLMError("No usable events came back. Try again.")
        spec["events"] = deck
        self.store.upsert_world(world["slug"], world["source"], spec, world["code"], notes=world.get("notes") or "")
        return deck

    # -- one person's crossroads: the intake ------------------------------------
    async def life_interview(self, story: str, lang: str) -> dict:
        """Questions to the person before their world is built (options plus their own words)."""
        if not self.llm.live:
            raise LLMError("This needs an AI provider. Set OPENAI_API_KEY in .env and restart.")
        data, results = await chat_json(self.llm, "draft", prompts.life_interview_messages(story, lang), max_tokens=4000)
        self._bill_loose("draft", results)
        out = []
        for q in (data.get("questions") if isinstance(data.get("questions"), list) else [])[:6]:
            if isinstance(q, dict) and str(q.get("question") or "").strip():
                out.append({"question": str(q["question"]).strip(), "why": str(q.get("why") or "").strip(),
                            "options": [str(o).strip() for o in (q.get("options") or []) if str(o).strip()][:4]})
        return {"questions": out}

    async def life_compose(self, story: str, answers: list[dict], lang: str) -> dict:
        """The person, their paths and the scenario, from what they wrote and answered. Nothing is built yet."""
        if not self.llm.live:
            raise LLMError("This needs an AI provider. Set OPENAI_API_KEY in .env and restart.")
        data, results = await chat_json(self.llm, "draft", prompts.life_compose_messages(story, answers, lang), max_tokens=6000)
        self._bill_loose("draft", results)
        life = clean_life({"protagonist": {"name": data.get("name"), "profile": data.get("profile")}, "options": data.get("options"),
                           "question": data.get("question"), "horizon": data.get("horizon")})
        if not life or not str(data.get("scenario") or "").strip():
            raise LLMError("The interview could not be turned into a brief. Try again, or say a little more.")
        return {"life": life, "scenario": str(data["scenario"]).strip()}

    def _bill_loose(self, role: str, results: list[LLMResult]) -> None:
        for res in results:
            self.store.add_llm_call(None, None, role, res.model, res.tokens_in, res.tokens_out,
                                    cost_usd(self.prices, res.model, res.tokens_in, res.tokens_out), res.ms, res.estimated)

    async def clarify(self, scenario: str, lang: str, based_on: int | None = None) -> dict:
        """Before building: the few questions whose answers would change the world most, each with options.
        An empty list means the scenario is clear enough (or no AI is available) and building can start."""
        if not self.llm.live:
            return {"questions": []}
        parent = self.store.world(based_on) if based_on else None
        data, results = await chat_json(self.llm, "draft", prompts.clarify_messages(scenario, lang, parent["spec"] if parent else None), max_tokens=3000)
        for res in results:
            self.store.add_llm_call(None, based_on if parent else None, "draft", res.model, res.tokens_in, res.tokens_out,
                                    cost_usd(self.prices, res.model, res.tokens_in, res.tokens_out), res.ms, res.estimated)
        out = []
        for q in (data.get("questions") if isinstance(data.get("questions"), list) else [])[:4]:
            if not isinstance(q, dict) or not str(q.get("question") or "").strip():
                continue
            options = [str(o).strip() for o in (q.get("options") or []) if str(o).strip()][:4]
            out.append({"question": str(q["question"]).strip(), "why": str(q.get("why") or "").strip(), "options": options})
        return {"questions": out}

    async def evolve_scenario(self, world_id: int, comment: str, lang: str) -> dict:
        """What the observer thinks of a world, turned into the scenario for a new one. Nothing is built yet:
        the observer reads the scenario, changes it if they like, and then creates the world as usual."""
        if not self.llm.live:
            raise LLMError("This needs an AI provider. Set OPENAI_API_KEY in .env and restart.")
        world = self.store.world(world_id)
        res = await self.llm.chat("draft", prompts.evolve_messages(world["spec"], comment, lang), max_tokens=4000)
        cost = cost_usd(self.prices, res.model, res.tokens_in, res.tokens_out)
        self.store.add_llm_call(None, world_id, "draft", res.model, res.tokens_in, res.tokens_out, cost, res.ms, res.estimated)
        return {"scenario": res.text.strip(), "model": res.model, "cost": cost,
                "based_on": {"id": world_id, "slug": world["slug"], "title": world["spec"].get("title")}}

    async def _write_sketches(self, job: DesignJob, recipe: dict, people: list[dict], batch: int = 25) -> None:
        """Each person's life sketch, written once by the design model and kept with the world."""
        async def one(rows: list[dict]) -> None:
            brief = [{k: v for k, v in r.items() if k != "story"} | {"name": r["name"]["en"]} for r in rows]
            msg = prompts.SKETCH_PROMPT.format(sketch=recipe["sketch"], people=json.dumps(brief, ensure_ascii=False))
            data, results = await chat_json(self.llm, "designer", [{"role": "user", "content": msg}], max_tokens=12000)
            for res in results:
                self._bill(job, "designer", res)
            stories = data.get("stories") if isinstance(data.get("stories"), dict) else {}
            for r in rows:
                r["story"] = str(stories.get(str(r["id"]), "")).strip()

        await asyncio.gather(*(one(people[i:i + batch]) for i in range(0, len(people), batch)))
        missing = [r for r in people if not r["story"]]
        if missing:                                  # one more try for anyone the model skipped
            await asyncio.gather(*(one(missing[i:i + batch]) for i in range(0, len(missing), batch)))

    def _keep_failure(self, job: DesignJob) -> None:
        """A build that did not work out stays where it was, with what went wrong, until the observer removes it."""
        w = self.store.world(job.world_id)
        spec = w["spec"]
        spec["failure"] = {"error": job.error, "log": [l for l in job.log if l["stage"] != "usage"][-12:], "cost": round(job.cost, 4)}
        self.store.update_world(job.world_id, w["slug"], "failed", spec, "")

    def job_for(self, world_id: int) -> DesignJob | None:
        return next((j for j in self.jobs.values() if j.world_id == world_id), None)

    def cancel(self, world_id: int) -> None:
        """Stop building a world (it is about to be removed)."""
        job = self.job_for(world_id)
        if job and job.status == "running":
            job.status, job.error = "failed", "cancelled"
            job.world_id = None
            for t in list(self._tasks):
                if getattr(t, "job_id", None) == job.id:
                    t.cancel()

    def _say(self, job: DesignJob, stage: str, en: str, ja: str) -> None:
        job.stage = stage
        job.log.append({"t": round(time.time() - job.started), "stage": stage, "text": {"en": en, "ja": ja}})

    def _bill(self, job: DesignJob, role: str, res: LLMResult) -> None:
        c = cost_usd(self.prices, res.model, res.tokens_in, res.tokens_out)
        job.cost += c or 0.0
        job.calls += 1
        job.log.append({"t": round(time.time() - job.started), "stage": "usage", "text": {
            "en": f"{res.model}: {res.tokens_in:,} in / {res.tokens_out:,} out tokens" + (f" (${c:.3f})" if c is not None else ""),
            "ja": f"{res.model}: 入力 {res.tokens_in:,} / 出力 {res.tokens_out:,} トークン" + (f"（${c:.3f}）" if c is not None else "")}})
        job.billed.append((role, res, c))

    async def _run(self, job: DesignJob) -> None:
        try:
            if not self.llm.live:
                raise LLMError("Designing a new world needs an AI provider. Set OPENAI_API_KEY in .env and restart.")
            if (await self.sandboxes.backend()) == "process":
                # fail early with the sandbox's own explanation instead of after paying for a design
                sb = await self.sandboxes.open(trusted=False)
                await sb.close()
            example = self.store.world_by_slug(self.example_slug)
            research = ""
            self._say(job, "research", "Looking up real-world numbers on the web.", "現実の数字をウェブで調べています。")
            try:
                # a world about one person is built from what they said, and their story is not sent to a web search
                r = None if job.life else await self.llm.research(prompts.RESEARCH_PROMPT.format(scenario=job.scenario))
                if r is None:
                    self._say(job, "research", "Web research is off; the designer will mark its numbers as assumptions.",
                              "ウェブ調査はオフです。数字は仮定として印を付けます。")
                else:
                    research = r.text.strip()
                    self._bill(job, "research", r)
            except LLMError as e:
                self._say(job, "research", f"Web research failed ({str(e)[:120]}); continuing with assumptions.",
                          f"ウェブ調査に失敗しました（{str(e)[:120]}）。仮定の数字で続けます。")
            self._say(job, "design", "Writing the rules of the world and the recipe for its people.",
                      "世界の規則と、住人の作り方を書いています。")
            base = prompts.designer_messages(job.scenario, research, {"spec": _slim_spec(example["spec"]), "code": example["code"],
                                                                      "cast": example["spec"].get("cast")}, job.reference, job.life)
            msgs = base
            spec = code = recipe = None
            problems: list[str] = []
            for attempt in range(MAX_REPAIRS + 1):
                res = await self.llm.chat("designer", msgs, max_tokens=DESIGN_MAX_TOKENS)
                self._bill(job, "designer", res)
                spec, code, recipe, problems = _parse(res.text)
                if not problems:
                    data: dict = {}
                    if recipe:
                        data[recipe["collection"]] = build_cast(recipe, seed=1)
                        spec["cast"] = recipe
                    if job.reference:
                        data["reference"] = job.reference
                    if job.life:
                        data["protagonist"] = job.life["protagonist"]
                        spec["focus"] = life_focus(spec, job.life)
                        problems = life_problems(spec, job.life)
                    if data:
                        spec["data"] = data
                if not problems:
                    self._say(job, "validate", f"Trial run in the sandbox (attempt {attempt + 1}).",
                              f"サンドボックスで試運転しています（{attempt + 1} 回目）。")
                    for wait in (0, 20, 60):          # a sandbox outage is retried here, not blamed on the design
                        try:
                            await asyncio.sleep(wait)
                            problems = await validate_world(self.sandboxes, spec, code, trusted=False)
                            break
                        except SandboxError as e:
                            if not e.infra or wait == 60:
                                raise
                            self._say(job, "validate", "The sandbox is not available; trying again shortly.", "サンドボックスが使えません。少し待って再試行します。")
                if not problems:
                    # it runs; now look for what otherwise only shows after a paid run (answers that change nothing, mismatched units)
                    self._say(job, "validate", "Checkup: rehearsing with every answer in turn, looking for dead ends.",
                              "点検しています：選択肢を 1 つずつ全員に選ばせて、効かないものがないか見ています。")
                    if job.life:                # the person the world is about must actually be asked, on every path
                        for o in job.life["options"]:
                            seen: set = set()
                            await dry_run(self.sandboxes, spec, code, params={"path": o["id"]}, ticks=min(int(spec["tick"]["default_ticks"]), 80),
                                          trusted=False, max_requests_per_tick=5000, on_requests=lambda t, reqs, frame: seen.update(r.get("key") for r in reqs))
                            if LIFE_KEY not in seen:
                                problems.append(f'on the path "{o["id"]}" the protagonist (request key "{LIFE_KEY}") is never asked anything')
                    try:
                        report = await checkup(self.sandboxes, spec, code, trusted=False)
                        problems = (problems + report["problems"]) if attempt < MAX_REPAIRS else []      # on the last round, keep the world and tell the observer
                        spec["checkup"] = {"notes": report["notes"] + (report["problems"] if attempt == MAX_REPAIRS else []),
                                           "asked": report["asked"], "cast": report["cast"], "questions": report["questions"], "options": report["options"]}
                    except SandboxError as e:
                        if e.infra:
                            spec["checkup"] = {"notes": ["The checkup could not run: the sandbox was not available."]}
                        else:
                            problems = [f"model error during the checkup: {e}"]
                if not problems:
                    break
                self._say(job, "repair", f"{len(problems)} problem(s) found: {problems[0][:160]}",
                          f"問題が {len(problems)} 件見つかりました：{problems[0][:160]}")
                if attempt == MAX_REPAIRS:
                    raise ValueError("The designed world still fails validation after %d repairs: %s"
                                     % (MAX_REPAIRS, "; ".join(p[:200] for p in problems[:3])))
                msgs = prompts.repair_messages(base, res.text, problems)
            assert spec is not None and code is not None
            if recipe:
                people = spec["data"][recipe["collection"]]
                self._say(job, "cast", f"Writing life sketches for {len(people)} people.", f"{len(people)} 人の生い立ちを書いています。")
                await self._write_sketches(job, recipe, people)
            slug = _unique_slug(self.store, spec.get("slug") or "world")
            spec["slug"] = slug
            spec.setdefault("scenario", {"en": job.scenario, "ja": job.scenario})
            if job.based_on:
                spec["based_on"] = job.based_on
            self.store.update_world(job.world_id, slug, "generated", spec, code, notes=research)
            job.slug = slug
            job.status = "done"
            self._say(job, "done", f"World '{slug}' is ready.", f"世界「{slug}」ができました。")
        except (LLMError, SandboxError, ValueError, json.JSONDecodeError) as e:
            job.status, job.error = "failed", str(e)[:1500]
            self._say(job, "failed", job.error[:300], job.error[:300])
        except Exception as e:   # never leave a job hanging in "running"
            job.status, job.error = "failed", f"{type(e).__name__}: {e}"[:1500]
            self._say(job, "failed", job.error[:300], job.error[:300])
        finally:
            if job.status == "failed" and job.world_id and self.store.world(job.world_id):
                self._keep_failure(job)
            for role, res, c in job.billed:
                self.store.add_llm_call(None, job.world_id, role, res.model, res.tokens_in, res.tokens_out, c, res.ms, res.estimated)
            if self.on_milestone:
                self.on_milestone()


def _slim_spec(spec: dict) -> dict:
    """The example spec, without the long scenario text, the people and the recipe (shown separately)."""
    return {k: v for k, v in spec.items() if k not in ("scenario", "data", "cast")}


def _parse(text: str) -> tuple[dict | None, str | None, dict | None, list[str]]:
    blocks = fenced_blocks(text, "json")
    code = fenced_block(text, "python")
    if not blocks or not code:
        return None, None, None, ["the reply must contain a ```json block (spec), a ```python block (model) and a ```json block (cast recipe)"]
    try:
        spec = json.loads(blocks[0])
    except json.JSONDecodeError as e:
        return None, None, None, [f"the spec is not valid JSON: {e}"]
    recipe = None
    problems = check_spec(spec) + check_code(code)
    if len(blocks) > 1 and blocks[1].strip() not in ("null", "{}"):
        try:
            recipe = json.loads(blocks[1])
        except json.JSONDecodeError as e:
            return spec, code, None, problems + [f"the cast recipe is not valid JSON: {e}"]
        problems += check_recipe(recipe)
        if problems and check_recipe(recipe):
            recipe = None
    return spec, code, recipe, problems


def _unique_slug(store: Store, slug: str) -> str:
    slug = re.sub(r"[^a-z0-9_]+", "_", slug.lower()).strip("_") or "world"
    if not store.world_by_slug(slug):
        return slug
    n = 2
    while store.world_by_slug(f"{slug}_{n}"):
        n += 1
    return f"{slug}_{n}"

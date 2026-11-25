"""World designer: scenario text -> world spec + math model, checked in a sandbox.

Steps: optional web research -> design -> validate (static checks, a default
run and a random-behaviour run in the sandbox) -> repair, up to a few rounds.
Runs as a background job so the viewer can show progress.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field

from ..domain.contract import check_code, check_spec
from ..domain.pricing import cost_usd
from ..domain.text import fenced_block
from . import prompts
from .ports import LanguageModel, LLMError, LLMResult, SandboxError, SandboxFactory, Store
from .worlds import validate_world

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

    def public(self) -> dict:
        return {"id": self.id, "status": self.status, "stage": self.stage, "log": self.log[-30:], "world_id": self.world_id,
                "slug": self.slug, "error": self.error, "cost": round(self.cost, 4), "calls": self.calls,
                "seconds": round(time.time() - self.started)}


class WorldDesigner:
    def __init__(self, store: Store, sandboxes: SandboxFactory, llm: LanguageModel, prices: dict,
                 example_slug: str = "chuo_line"):
        self.store, self.sandboxes, self.llm, self.prices = store, sandboxes, llm, prices
        self.example_slug = example_slug
        self.jobs: dict[int, DesignJob] = {}
        self._tasks: set[asyncio.Task] = set()
        self._next = 1

    @property
    def busy(self) -> bool:
        return any(not task.done() for task in self._tasks)

    def start(self, scenario: str) -> DesignJob:
        job = DesignJob(id=self._next, scenario=scenario.strip())
        self._next += 1
        self.jobs[job.id] = job
        task = asyncio.create_task(self._run(job))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job

    async def draft_scenario(self, idea: str, lang: str) -> dict:
        """Turn a rough idea into a scenario text the designer can build from."""
        if not self.llm.live:
            raise LLMError("Drafting a scenario needs an AI provider. Set OPENAI_API_KEY in .env and restart.")
        res = await self.llm.chat("designer", prompts.scenario_messages(idea, lang), max_tokens=3000)
        cost = cost_usd(self.prices, res.model, res.tokens_in, res.tokens_out)
        self.store.add_llm_call(None, None, "draft", res.model, res.tokens_in, res.tokens_out, cost, res.ms, res.estimated)
        return {"scenario": res.text.strip(), "model": res.model, "cost": cost}

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
                r = await self.llm.research(prompts.RESEARCH_PROMPT.format(scenario=job.scenario))
                if r is None:
                    self._say(job, "research", "Web research is off; the designer will mark its numbers as assumptions.",
                              "ウェブ調査はオフです。数字は仮定として印を付けます。")
                else:
                    research = r.text.strip()
                    self._bill(job, "research", r)
            except LLMError as e:
                self._say(job, "research", f"Web research failed ({str(e)[:120]}); continuing with assumptions.",
                          f"ウェブ調査に失敗しました（{str(e)[:120]}）。仮定の数字で続けます。")
            self._say(job, "design", "Designing the world: parameters, residents, and the math model.",
                      "世界を設計しています：パラメータ、住人、数理モデル。")
            base = prompts.designer_messages(job.scenario, research, _slim_spec(example["spec"]), example["code"])
            msgs = base
            spec = code = None
            problems: list[str] = []
            for attempt in range(MAX_REPAIRS + 1):
                res = await self.llm.chat("designer", msgs, max_tokens=DESIGN_MAX_TOKENS)
                self._bill(job, "designer", res)
                spec, code, problems = _parse(res.text)
                if not problems:
                    self._say(job, "validate", f"Trial run in the sandbox (attempt {attempt + 1}).",
                              f"サンドボックスで試運転しています（{attempt + 1} 回目）。")
                    problems = await validate_world(self.sandboxes, spec, code, trusted=False)
                if not problems:
                    break
                self._say(job, "repair", f"{len(problems)} problem(s) found: {problems[0][:160]}",
                          f"問題が {len(problems)} 件見つかりました：{problems[0][:160]}")
                if attempt == MAX_REPAIRS:
                    raise ValueError("The designed world still fails validation after %d repairs: %s"
                                     % (MAX_REPAIRS, "; ".join(p[:200] for p in problems[:3])))
                msgs = prompts.repair_messages(base, res.text, problems)
            assert spec is not None and code is not None
            slug = _unique_slug(self.store, spec.get("slug") or "world")
            spec["slug"] = slug
            spec.setdefault("scenario", {"en": job.scenario, "ja": job.scenario})
            job.world_id = self.store.upsert_world(slug, "generated", spec, code, notes=research)
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
            for role, res, c in job.billed:
                self.store.add_llm_call(None, job.world_id, role, res.model, res.tokens_in, res.tokens_out, c, res.ms, res.estimated)


def _slim_spec(spec: dict) -> dict:
    """The example spec, without the long scenario text."""
    return {k: v for k, v in spec.items() if k != "scenario"}


def _parse(text: str) -> tuple[dict | None, str | None, list[str]]:
    spec_text = fenced_block(text, "json")
    code = fenced_block(text, "python")
    if not spec_text or not code:
        return None, None, ["the reply must contain one ```json block (spec) and one ```python block (model)"]
    try:
        spec = json.loads(spec_text)
    except json.JSONDecodeError as e:
        return None, None, [f"the spec is not valid JSON: {e}"]
    problems = check_spec(spec) + check_code(code)
    return spec, code, problems


def _unique_slug(store: Store, slug: str) -> str:
    slug = re.sub(r"[^a-z0-9_]+", "_", slug.lower()).strip("_") or "world"
    if not store.world_by_slug(slug):
        return slug
    n = 2
    while store.world_by_slug(f"{slug}_{n}"):
        n += 1
    return f"{slug}_{n}"

import pytest

from hakoniwa.application.engine import run_headless
from hakoniwa.application.estimator import estimate_run
from hakoniwa.application.ports import SandboxError
from hakoniwa.application.worlds import validate_world
from hakoniwa.infrastructure.sandboxes import ProcessSandbox


@pytest.mark.parametrize("slug", ["chuo_line", "izu_oshima", "presales"])
async def test_sample_worlds_pass_validation(app, slug):
    w = app.store.world_by_slug(slug)
    assert await validate_world(app.sandboxes, w["spec"], w["code"], trusted=True) == []


async def test_run_is_reproducible_and_fork_matches_parent(app):
    w = app.store.world_by_slug("chuo_line")
    a = await app.runs.create_run(w["id"], config={"ticks": 12})
    b = await app.runs.create_run(w["id"], config={"ticks": 12})
    await run_headless(app.runs, a)
    await run_headless(app.runs, b)
    ta, tb = app.store.ticks(a), app.store.ticks(b)
    assert [r["metrics"] for r in ta] == [r["metrics"] for r in tb]          # same seed, same world
    # a fork with no intervention must continue exactly like its parent
    f = await app.runs.fork(a, 6)
    await run_headless(app.runs, f)
    assert [r["metrics"] for r in app.store.ticks(f)] == [r["metrics"] for r in ta]
    # a fork with an intervention must differ after the fork point, and only after it
    g = await app.runs.fork(a, 6, intervention={"patch": {"detour_capacity_factor": 2.5}})
    await run_headless(app.runs, g)
    tg = app.store.ticks(g)
    assert [r["metrics"] for r in tg[:7]] == [r["metrics"] for r in ta[:7]]
    assert tg[-1]["metrics"] != ta[-1]["metrics"]
    facts = app.store.fact_history(g, "world", "detour_capacity_factor")
    assert [(x["object"], x["valid_from"], x["valid_to"]) for x in facts] == [(1.0, 0, 7), (2.5, 7, None)]


async def test_estimate_counts_the_questions_a_run_asks(app):
    w = app.store.world_by_slug("izu_oshima")
    est = await estimate_run(app.store, app.sandboxes, app.llm, app.settings.prices, w, None, {"ticks": 26}, ("en", "ja"))
    rid = await app.runs.create_run(w["id"], config={"ticks": 26})
    await run_headless(app.runs, rid)
    assert est["calls"] == len(app.store.decisions(rid, limit=10_000)) > 0
    assert est["tokens_in"] > 0 and est["ai"] == "mock"


async def test_sandbox_refuses_escape_attempts():
    sb = ProcessSandbox(op_timeout=5)
    await sb.open()
    try:
        base = "def init(p, r):\n    return {}\ndef step(s, p, r, t):\n    return None\ndef metrics(s, p, t):\n    return {}\n"
        with pytest.raises(SandboxError, match="not allowed"):
            await sb.load("import socket\n" + base, {}, 1)
        with pytest.raises(SandboxError):
            await sb.load(base + "f = open('/etc/hosts')\n", {}, 1)
        await sb.load(base.replace("return None", "while True:\n        pass"), {}, 1)
        await sb.init()
        sb.op_timeout = 1.5
        with pytest.raises(SandboxError, match="did not answer"):
            await sb.tick()
    finally:
        await sb.close()


async def test_untrusted_world_needs_isolation(app):
    with pytest.raises(SandboxError, match="isolated sandbox"):
        await app.sandboxes.open(trusted=False)

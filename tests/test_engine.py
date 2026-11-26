import pytest

from hakoniwa.application.engine import run_headless
from hakoniwa.application.estimator import estimate_run
from hakoniwa.application.ports import SandboxError
from hakoniwa.application.worlds import validate_world
from hakoniwa.infrastructure.builtin_worlds import load_builtin_worlds
from hakoniwa.infrastructure.sandboxes import ProcessSandbox
from hakoniwa.interface.cli import _check

SAMPLES = [w["slug"] for w in load_builtin_worlds()]


@pytest.mark.parametrize("slug", SAMPLES)
async def test_sample_worlds_pass_validation(app, slug):
    w = app.store.world_by_slug(slug)
    assert await validate_world(app.sandboxes, w["spec"], w["code"], trusted=True) == []


async def test_check_command_checks_all_sample_worlds(capsys):
    assert await _check(None) == 0
    reported = capsys.readouterr().out.splitlines()
    assert {line.split()[0] for line in reported if line.endswith(" ok")} == set(SAMPLES)


async def test_run_is_reproducible_and_fork_matches_parent(app):
    w = app.store.world_by_slug("tp_2020")
    a = await app.runs.create_run(w["id"], config={"ticks": 15})
    b = await app.runs.create_run(w["id"], config={"ticks": 15})
    await run_headless(app.runs, a)
    await run_headless(app.runs, b)
    ta, tb = app.store.ticks(a), app.store.ticks(b)
    assert [r["metrics"] for r in ta] == [r["metrics"] for r in tb]          # same seed, same world
    # a fork with no intervention must continue exactly like its parent
    f = await app.runs.fork(a, 8)
    await run_headless(app.runs, f)
    assert [r["metrics"] for r in app.store.ticks(f)] == [r["metrics"] for r in ta]
    # a fork with an intervention must differ after the fork point, and only after it
    g = await app.runs.fork(a, 8, intervention={"patch": {"tv_coverage": 0.0}})
    await run_headless(app.runs, g)
    tg = app.store.ticks(g)
    assert [r["metrics"] for r in tg[:9]] == [r["metrics"] for r in ta[:9]]
    assert tg[-1]["metrics"] != ta[-1]["metrics"]
    facts = app.store.fact_history(g, "world", "tv_coverage")
    assert [(x["object"], x["valid_from"], x["valid_to"]) for x in facts] == [(1.0, 0, 9), (0.0, 9, None)]


async def test_estimate_counts_the_questions_a_run_asks(app):
    w = app.store.world_by_slug("tp_2020")
    est = await estimate_run(app.store, app.sandboxes, app.llm, app.settings.prices, w, None, {"ticks": 20}, ("en", "ja"))
    rid = await app.runs.create_run(w["id"], config={"ticks": 20})
    await run_headless(app.runs, rid)
    assert est["calls"] == len(app.store.decisions(rid, limit=10_000)) > 0
    assert est["tokens_in"] > 0 and est["ai"] == "mock"


async def test_every_person_in_a_cast_world_has_their_own_name_and_persona(app):
    w = app.store.world_by_slug("tp_2020")
    rid = await app.runs.create_run(w["id"], config={"ticks": 13})
    await run_headless(app.runs, rid)
    asked = app.store.decisions(rid, limit=10_000)
    assert len(asked) > 50
    assert all(d["request"].get("persona") and d["request"].get("name") for d in asked)
    assert len({d["request"]["persona"] for d in asked}) > 40


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


class _EagerLLM:
    """A stand-in provider whose residents always pick the last option, and whose gate answer is set by the test."""
    live = True

    def __init__(self, think: float = 1.0):
        self.think, self.chats, self.gates = think, 0, 0

    def model_for(self, role):
        return "test-model"

    async def chat(self, role, messages, *, max_tokens=1200, want_json=False, model=None):
        import json, re
        from hakoniwa.application.ports import LLMResult
        self.chats += 1
        last = re.findall(r"^- (\w+):", messages[-1]["content"].split("OPTIONS:")[1].split("\n\n")[0], re.M)[-1]
        return LLMResult(json.dumps({"thought": "x", "choice": last, "say": {"en": "I will.", "ja": "やります。"}}), "test-model", 100, 20, 1)

    async def decide(self, text, questions):
        from hakoniwa.application.ports import LLMResult
        self.gates += 1
        return ([{"name": "attend", "probabilities": [{"value": "habit", "probability": 1 - self.think},
                                                      {"value": "think", "probability": self.think}]}],
                LLMResult("", "test-model", 100, 0, 1))


async def _run_with(app, llm, config):
    app.runs.llm = llm
    w = app.store.world_by_slug("tp_2020")
    rid = await app.runs.create_run(w["id"], config={"ticks": 13, **config})
    await run_headless(app.runs, rid)
    return app.store.decisions(rid, limit=10_000)


async def test_follow_through_keeps_some_residents_on_their_habit(app):
    asked = await _run_with(app, _EagerLLM(), {"follow_through": 0.4})
    changed = [d for d in asked if d["response"]["action"]["choice"] != d["request"]["options"][0]["id"]]
    lapsed = [d for d in asked if d["response"].get("meant")]
    assert len(asked) > 50 and changed and lapsed
    assert all(d["response"]["action"]["choice"] == d["request"]["options"][0]["id"] for d in lapsed)    # they carried on
    assert 0.2 < len(changed) / (len(changed) + len(lapsed)) < 0.6                                       # about 40% acted


async def test_gate_asks_only_those_who_stop_to_think(app):
    llm = _EagerLLM(think=0.0)
    asked = await _run_with(app, llm, {"gate": "judge"})
    assert llm.gates == len(asked) > 50 and llm.chats == 0
    assert {d["source"] for d in asked} == {"habit"}
    assert all(d["response"]["action"]["choice"] == d["request"]["options"][0]["id"] for d in asked)


async def test_observer_steps_in_on_one_resident_at_a_fork(app):
    app.runs.llm = _EagerLLM()
    w = app.store.world_by_slug("tp_2020")
    rid = await app.runs.create_run(w["id"], config={"ticks": 14, "ai": "mock"})
    await run_headless(app.runs, rid)
    key = app.store.decisions(rid, limit=10_000)[0]["key"]          # someone who has been asked
    # deciding for them: applied as it is, and marked as the observer's decision
    f = await app.runs.fork(rid, 12, intervention={"person": {"key": key, "choice": "today"}})
    await run_headless(app.runs, f)
    mine = [d for d in app.store.decisions(f, key=key, limit=100) if d["tick"] == 13]
    assert mine[-1]["source"] == "observer" and mine[-1]["response"]["action"]["choice"] == "today"
    assert any(e["kind"] == "intervention" for e in app.store.events(f, limit=5000))
    # saying something: they are asked again with the words in front of them, and the words stay with them
    g = await app.runs.fork(rid, 12, intervention={"person": {"key": key, "tell": "They say the factory is closing."}}, config={"ai": "auto"})
    await run_headless(app.runs, g)
    asked = [d for d in app.store.decisions(g, key=key, limit=100) if d["tick"] == 13]
    assert asked[-1]["source"] == "llm" and "factory is closing" in asked[-1]["request"]["situation"]
    assert app.store.run(g)["config"]["told"][key][0]["text"] == "They say the factory is closing."
    # the run it was forked from is untouched
    assert all(d["source"] == "mock" for d in app.store.decisions(rid, limit=10_000))


async def test_chance_events_are_drawn_from_the_seed_and_shared_by_forks(app):
    from hakoniwa.domain.contract import chance_events, draw_schedule
    w = app.store.world_by_slug("tp_2020")
    spec = w["spec"]
    spec["events"] = [{"id": "no_tv", "label": {"en": "TV strike", "ja": "テレビのスト"}, "chance": 1.0, "window": [5, 5], "patch": {"tv_coverage": 0.0}, "lasts": 3},
                      {"id": "never", "chance": 0.0, "patch": {"tv_coverage": 0.5}}, {"id": "bad", "chance": 0.5, "patch": {"no_such_parameter": 1}}]
    assert [e["id"] for e in chance_events(spec)] == ["no_tv"]                       # unusable ones are dropped
    assert draw_schedule(chance_events(spec), 7, 20) == draw_schedule(chance_events(spec), 7, 20)
    app.store.upsert_world(w["slug"], "builtin", spec, w["code"])
    plain = await app.runs.create_run(w["id"], config={"ticks": 12})
    lucky = await app.runs.create_run(w["id"], config={"ticks": 12, "chance": True})
    assert app.store.run(plain)["config"]["schedule"] is None
    await run_headless(app.runs, lucky)
    facts = app.store.fact_history(lucky, "world", "tv_coverage")
    assert [(x["object"], x["valid_from"]) for x in facts] == [(1.0, 0), (0.0, 5), (1.0, 8)]      # it happened at tick 5 and was over three ticks later
    f = await app.runs.fork(lucky, 3)                                                # a branch from before the event meets it too
    await run_headless(app.runs, f)
    assert [r["metrics"] for r in app.store.ticks(f)] == [r["metrics"] for r in app.store.ticks(lucky)]


async def test_a_personal_chance_event_reaches_some_residents_only(app):
    llm = _EagerLLM()
    seen = []
    chat = llm.chat

    async def spy(role, messages, **kw):
        seen.append(messages[-1]["content"])
        return await chat(role, messages, **kw)
    llm.chat = spy
    app.runs.llm = llm
    w = app.store.world_by_slug("tp_2020")
    spec = w["spec"]
    spec["events"] = [{"id": "bill", "label": {"en": "A big bill", "ja": "大きな請求"}, "chance": 1.0, "window": [11, 11], "lasts": 2,
                       "personal": {"share": 0.25, "text": {"en": "A repair bill has left you short this week.", "ja": "修理代で今週は苦しい。"}}}]
    app.store.upsert_world(w["slug"], "builtin", spec, w["code"])
    rid = await app.runs.create_run(w["id"], config={"ticks": 13, "chance": True})
    await run_headless(app.runs, rid)
    life = app.store.run(rid)["config"]["life"]
    asked = {d["key"] for d in app.store.decisions(rid, limit=10_000) if d["tick"] <= 10}
    assert 0 < len(life) < len(asked) and set(life) <= asked                 # a share of those in the story so far
    told = [m for m in seen if "repair bill" in m]
    assert told and len(told) < len(seen)                                    # only they are reminded of it


async def test_runs_and_worlds_travel_between_databases(app, tmp_path):
    from hakoniwa.bootstrap import build_app
    from hakoniwa.domain.contract import check_code, check_spec
    w = app.store.world_by_slug("tp_2020")
    a = await app.runs.create_run(w["id"], config={"ticks": 12})
    await run_headless(app.runs, a)
    f = await app.runs.fork(a, 8, intervention={"patch": {"tv_coverage": 0.0}})
    await run_headless(app.runs, f)
    other = await app.runs.create_run(w["id"], config={"ticks": 5})
    await run_headless(app.runs, other)
    made = dict(w["spec"], slug="my_world", title={"en": "Mine", "ja": "私の世界"})
    made.pop("data", None), made.pop("cast", None)
    app.store.upsert_world("my_world", "generated", made, w["code"])
    out = tmp_path / "export.sqlite3"
    assert app.store.export_to(out, run_ids=[f]) == {"worlds": 2, "runs": 2}        # the fork brings its parent; my world comes too
    there = build_app()                                                           # another, empty database
    try:
        check = lambda spec, code: check_spec(spec) + check_code(code)
        got = there.store.import_from(out, check)
        assert got["runs"] == 2 and got["worlds_added"] == 1 and got["worlds_matched"] == 1 and not got["skipped"]
        runs = there.store.runs_for_world(there.store.world_by_slug("tp_2020")["id"])
        child = next(r for r in runs if r["parent_run_id"])
        parent = next(r for r in runs if not r["parent_run_id"])
        assert child["parent_run_id"] == parent["id"] and child["fork_tick"] == 8
        assert [r["metrics"] for r in there.store.ticks(child["id"])] == [r["metrics"] for r in app.store.ticks(f)]
        assert len(there.store.decisions(child["id"], limit=10_000)) == len(app.store.decisions(f, limit=10_000))
        assert there.store.world_by_slug("my_world")["source"] == "generated"       # its code will only run in the isolated sandbox
        again = await there.runs.fork(child["id"], 10)                             # the snapshots came across: it can branch again
        await run_headless(there.runs, again)
        assert there.store.run(again)["tick"] == 12
        assert there.store.import_from(out, check)["worlds_added"] == 0             # the same world again is recognised, not duplicated
        (tmp_path / "junk.sqlite3").write_bytes(b"not a database")
        with pytest.raises(Exception):
            there.store.import_from(tmp_path / "junk.sqlite3", check)
    finally:
        await there.close()


async def test_the_database_survives_a_lost_machine_through_the_backup_folder(tmp_path):
    from dataclasses import replace
    from hakoniwa.bootstrap import build_app
    from hakoniwa.infrastructure.config import load_settings
    s = replace(load_settings(), db_path=tmp_path / "machine1" / "db.sqlite3", backup_dir=tmp_path / "bucket", backup_minutes=0.001)
    first = build_app(s)
    w = first.store.world_by_slug("tp_2020")
    rid = await first.runs.create_run(w["id"], config={"ticks": 6})
    await run_headless(first.runs, rid)
    assert (await first.keep_copy())["error"] is None and (tmp_path / "bucket" / "hakoniwa-backup.sqlite3.gz").stat().st_size > 1000
    assert await first.keep_copy() is None                                      # nothing changed since: no second copy
    metrics = [r["metrics"] for r in first.store.ticks(rid)]
    await first.close()
    second = build_app(replace(s, db_path=tmp_path / "machine2" / "db.sqlite3"))     # a new machine with empty disks
    try:
        assert [r["metrics"] for r in second.store.ticks(rid)] == metrics
        f = await second.runs.fork(rid, 3)                                          # and it is a working database, not a picture of one
        await run_headless(second.runs, f)
        assert second.store.run(f)["tick"] == 6
    finally:
        await second.close()


async def test_report_is_laid_out_for_a_quick_read(app):
    from hakoniwa.application.reporter import render_report
    w = app.store.world_by_slug("forecourt_evenings")
    a = await app.runs.create_run(w["id"], config={"ticks": 16})
    await run_headless(app.runs, a)
    b = await app.runs.create_run(w["id"], config={"ticks": 16, "seed": 3})
    await run_headless(app.runs, b)
    facts = app.observer.report_facts(a, lang="en")
    assert facts["figures"] and facts["against_the_record"] and facts["other_runs"][0]["differs_by"] == "seed 3"
    assert len(facts["residents"]["choices"]) <= 6 and facts["residents"]["questions"] > 100
    words = {"headline": "The rush peaked the day after the news.", "happened": [f"point {i}" for i in range(9)], "residents": ["Most carried on."],
             "reality": "The peak fell on the recorded day.", "others": ["Another seed peaked higher."], "can_say": ["a"], "cannot_say": ["b"],
             "next": ["Fork before the news."], "next_one": "Open the Intervene tab."}
    text = render_report(facts, words, "en")
    assert text.splitlines()[0].startswith("# ") and "**In one line:** The rush peaked" in text
    assert text.count("\n1. point 0") == 1 and "5. point 4" in text and "6. point 5" not in text          # a list stops at five
    assert text.rstrip().splitlines()[-1] == "**Start with:** Open the Intervene tab."                       # the last line is the next step
    for heading in ("## What happened", "## The main figures", "## What the residents did", "## Against the record", "## Next to the other runs", "## What to try next"):
        assert heading in text
    plain = (await app.observer.report(a, lang="ja"))                                                         # no AI: the tables alone, in every language
    assert plain["source"] == "template" and set(plain["body"]) == {"en", "ja"} and "## 主な数字" in plain["body"]["ja"]
    assert app.observer.report_markdown(a, "ja").startswith("# ")

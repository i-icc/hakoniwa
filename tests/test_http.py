import os

import httpx
import pytest

from hakoniwa.interface.http import create_app


@pytest.fixture
async def client(app):
    api = create_app(app)
    async with api.router.lifespan_context(api):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://t") as c:
            yield c


async def test_viewer_flow_over_http(client):
    import asyncio
    info = (await client.get("/api/info")).json()
    assert info["llm_live"] is False and "OPENAI_API_KEY" not in str(info) and os.environ.get("OPENAI_API_KEY", "x") not in str(info)
    worlds = (await client.get("/api/worlds")).json()
    wid = next(w["id"] for w in worlds if w["slug"] == "tp_2020")
    world = (await client.get(f"/api/worlds/{wid}")).json()
    assert "data" not in world["spec"] and world["spec"]["cast"]["size"] == 240       # the people stay on the server
    cast = (await client.get(f"/api/worlds/{wid}/cast")).json()["people"]                # only names and sketches go to the viewer's board
    assert len(cast) == 240 and set(cast[0]) == {"name", "about"} and cast[0]["about"]
    run = (await client.post(f"/api/worlds/{wid}/runs", json={"config": {"ticks": 13, "tick_delay_ms": 0}, "start": True})).json()
    for _ in range(400):
        await asyncio.sleep(0.05)
        st = (await client.get(f"/api/runs/{run['id']}/ticks?since=-1")).json()
        if st["status"] == "finished":
            break
    assert st["tick"] == 13 and st["status"] == "finished" and len(st["rows"]) == 14
    frame = (await client.get(f"/api/runs/{run['id']}/frame?tick=12")).json()
    assert frame["view"]["nodes"] and frame["policies"] and frame["policies"][0]["name"]
    assert (await client.post(f"/api/runs/{run['id']}/intervene", json={"id": "nope"})).status_code == 400
    fork = (await client.post(f"/api/runs/{run['id']}/fork", json={"tick": 8, "intervention": {"id": "no_tv"}})).json()
    assert fork["parent_run_id"] == run["id"] and fork["tick"] == 8
    rep = (await client.post(f"/api/runs/{run['id']}/report", json={})).json()
    assert rep["source"] == "template" and "ja" in rep["body"]
    hist = (await client.get("/api/runs")).json()
    assert [h["id"] for h in hist] == [fork["id"], run["id"]] and hist[1]["headline"] and hist[1]["has_report"]
    assert hist[0]["parent_run_id"] == run["id"]      # its event is still queued, so no parameter differs yet
    assert (await client.get("/")).status_code == 200 and (await client.get("/app.js")).status_code == 200
    assert (await client.post("/api/worlds/design", json={"scenario": "x" * 30, "reference": "not,a\ntable"})).status_code in (200, 400)


async def test_model_choices_are_saved_and_can_be_reset(client, app):
    before = (await client.get("/api/models")).json()["roles"]["agent"]
    after = (await client.post("/api/models", json={"roles": {"agent": {"model": "some-model", "effort": "high"}}})).json()["roles"]
    assert after["agent"]["model"] == "some-model" and after["agent"]["effort"] == "high"
    assert after["designer"]["model"] == before["default_model"] or after["designer"]["model"]      # other roles keep their values
    assert app.store.get_setting("models")["agent"] == {"model": "some-model", "effort": "high"}
    assert app.llm.model_for("agent") == "mock"                                                      # the mock adapter ignores choices
    assert app.settings.role("agent").model == "some-model"
    bad = (await client.post("/api/models", json={"roles": {"agent": {"model": "", "effort": "nonsense"}}})).json()["roles"]["agent"]
    assert bad["model"] == before["default_model"] and bad["effort"] == before["default_effort"]
    reset = (await client.delete("/api/models")).json()["roles"]["agent"]
    assert reset["model"] == before["default_model"] and app.store.get_setting("models") is None


async def test_a_world_has_an_id_from_the_moment_building_starts(client):
    import asyncio
    a = (await client.post("/api/worlds/design", json={"scenario": "A small bathhouse raises its price and changes its hours."})).json()
    b = (await client.post("/api/worlds/design", json={"scenario": "A ramen shop queue at lunchtime, and a price rise mid-week."})).json()
    assert a["world_id"] and b["world_id"] and a["world_id"] != b["world_id"]          # two at once, each with its own page
    await asyncio.sleep(0.3)                                                             # with no AI provider the builds fail at once
    w = (await client.get(f"/api/worlds/{a['world_id']}")).json()
    assert w["source"] == "failed" and "AI provider" in w["spec"]["failure"]["error"] and "bathhouse" in w["spec"]["scenario"]["en"]
    assert (await client.post(f"/api/worlds/{a['world_id']}/runs", json={})).status_code == 400
    assert (await client.delete(f"/api/worlds/{b['world_id']}")).status_code == 200
    left = [x["id"] for x in (await client.get("/api/worlds")).json() if x["source"] == "failed"]
    assert left == [a["world_id"]]


async def test_data_goes_out_and_comes_back_over_http(client):
    import asyncio, gzip, sqlite3
    wid = next(w["id"] for w in (await client.get("/api/worlds")).json() if w["slug"] == "tp_2020")
    run = (await client.post(f"/api/worlds/{wid}/runs", json={"config": {"ticks": 6, "tick_delay_ms": 0}, "start": True})).json()
    for _ in range(400):
        await asyncio.sleep(0.05)
        if (await client.get(f"/api/runs/{run['id']}")).json()["status"] == "finished":
            break
    seen = (await client.get("/api/data")).json()
    mine = next(w for w in seen["worlds"] if w["id"] == wid)
    assert [r["id"] for r in mine["runs"]] == [run["id"]] and mine["runs"][0]["bytes"] > 0
    out = await client.get(f"/api/data/export?runs={run['id']}&worlds=")
    assert out.status_code == 200 and out.content[:2] == b"\x1f\x8b" and ".sqlite3.gz" in out.headers["content-disposition"]
    assert gzip.decompress(out.content)[:15] == b"SQLite format 3"
    back = (await client.post("/api/data/import", content=out.content)).json()
    assert back["runs"] == 1 and back["worlds_matched"] == 1 and back["worlds_added"] == 0
    runs = (await client.get(f"/api/worlds/{wid}")).json()["runs"]
    assert len(runs) == 2 and runs[0]["tick"] == runs[1]["tick"] == 6                      # added beside the original, not instead of it
    plain = await client.get(f"/api/data/export?runs={run['id']}&worlds=&gz=0")
    assert plain.content[:15] == b"SQLite format 3"
    assert (await client.post("/api/data/import", content=b"not a database at all")).status_code == 400


async def test_a_copy_is_taken_when_a_run_comes_to_rest(tmp_path):
    import asyncio
    from dataclasses import replace
    from hakoniwa.bootstrap import build_app
    from hakoniwa.infrastructure.config import load_settings
    app = build_app(replace(load_settings(), db_path=tmp_path / "db.sqlite3", backup_dir=tmp_path / "bucket", backup_minutes=600))
    api = create_app(app)
    async with api.router.lifespan_context(api):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://t") as c:
            wid = next(w["id"] for w in (await c.get("/api/worlds")).json() if w["slug"] == "tp_2020")
            run = (await c.post(f"/api/worlds/{wid}/runs", json={"config": {"ticks": 5, "tick_delay_ms": 0}, "start": True})).json()
            copy = tmp_path / "bucket" / "hakoniwa-backup.sqlite3.gz"
            for _ in range(120):                              # no timer is due for ten hours: only the run's end can trigger it
                await asyncio.sleep(0.1)
                if copy.exists() and (await c.get(f"/api/runs/{run['id']}")).json()["status"] == "finished":
                    break
            assert copy.exists() and (await c.get("/api/data")).json()["backup"]["last"]["error"] is None


async def test_a_life_world_is_lived_several_times_over(client):
    import asyncio
    worlds = (await client.get("/api/worlds")).json()
    life = next(w for w in worlds if w["life"])
    other = next(w for w in worlds if not w["life"])
    assert (await client.get(f"/api/worlds/{other['id']}/futures")).status_code == 400
    w = (await client.get(f"/api/worlds/{life['id']}")).json()
    paths = [o["id"] for o in w["spec"]["focus"]["options"]]
    assert len(paths) >= 2 and w["protagonist"]["profile"]
    made = (await client.post(f"/api/worlds/{life['id']}/futures", json={"per_path": 2, "lang": "en"})).json()["made"]
    assert sorted((m["path"], m["seed"]) for m in made) == sorted((p, k) for p in paths for k in (1, 2))      # every path, the same strokes of luck
    for _ in range(600):
        await asyncio.sleep(0.05)
        f = (await client.get(f"/api/worlds/{life['id']}/futures")).json()
        if all(x["status"] == "finished" for x in f["futures"]):
            break
    assert len(f["futures"]) == 2 * len(paths) and all("satisfaction" in x["figures"] and len(x["series"]) == x["tick"] for x in f["futures"])
    more = (await client.post(f"/api/worlds/{life['id']}/futures", json={"per_path": 1})).json()["made"]
    assert sorted((m["path"], m["seed"]) for m in more) == sorted((p, 3) for p in paths)                        # asking again adds new luck, it does not repeat
    rep = (await client.post(f"/api/worlds/{life['id']}/life-report", json={"lang": "en"})).json()
    assert rep["source"] == "template" and "## Where each path tended to lead" in rep["body"]["en"]
    assert (await client.get(f"/api/worlds/{life['id']}/life-report.md?lang=en")).text.startswith("# ")


async def test_life_path_can_switch_after_a_shared_history(client, app):
    import asyncio

    worlds = (await client.get("/api/worlds")).json()
    world = next(w for w in worlds if w["slug"] == "eight_years_at_the_kitchen_table")
    url = f"/api/worlds/{world['id']}"
    original = (await client.post(f"{url}/runs", json={
        "params": {"path": "stay_current_role"},
        "config": {"ticks": 6, "tick_delay_ms": 0},
        "start": True,
    })).json()
    original_id = original["id"]
    for _ in range(200):
        old = (await client.get(f"/api/runs/{original_id}/ticks")).json()
        if old["status"] == "finished":
            break
        await asyncio.sleep(0.025)
    assert old["status"] == "finished"

    response = await client.post(f"/api/runs/{original_id}/fork", json={
        "tick": 3,
        "intervention": {"patch": {"next_path": "join_startup"}},
    })
    assert response.status_code == 200, response.text
    child = response.json()
    child_id = child["id"]
    assert child["fork_tick"] == 3 and child["parent_run_id"] == original_id
    for tick in range(4):
        assert app.store.snapshot(child_id, tick) == app.store.snapshot(original_id, tick)
    # A branch can be resumed after its worker has been recreated.
    app.runs.workers.pop(child_id)
    await client.post(f"/api/runs/{child_id}/control", json={"action": "start"})
    for _ in range(200):
        future = (await client.get(f"/api/runs/{child_id}/ticks")).json()
        if future["status"] == "finished":
            break
        await asyncio.sleep(0.025)
    assert future["status"] == "finished"
    assert future["rows"][:4] == old["rows"][:4]
    assert app.store.snapshot(child_id, 4)["state"]["goal"] == "startup"
    assert app.store.snapshot(original_id, 4)["state"]["work"] != "startup"
    futures = {f["id"]: f for f in (await client.get(f"{url}/futures")).json()["futures"]}
    assert futures[child_id]["fork_tick"] == 3
    shared = futures[original_id]["outcomes"]["satisfaction"][:4]
    assert [tick for tick, _ in shared] == [0, 1, 2, 3]
    assert futures[child_id]["outcomes"]["satisfaction"][:4] == shared

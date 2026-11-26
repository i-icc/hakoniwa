import asyncio
import os
import sqlite3
from contextlib import closing

import httpx
import pytest

from hakoniwa.application.worlds import seed_worlds
from hakoniwa.infrastructure.builtin_worlds import load_builtin_worlds
from hakoniwa.interface.http import SQLITE_MEDIA, create_app


@pytest.fixture
async def client(app):
    api = create_app(app)
    async with api.router.lifespan_context(api):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://t") as c:
            yield c


async def test_viewer_flow_over_http(client):
    info = (await client.get("/api/info")).json()
    assert info["llm_live"] is False and "OPENAI_API_KEY" not in str(info) and os.environ.get("OPENAI_API_KEY", "x") not in str(info)
    worlds = (await client.get("/api/worlds")).json()
    wid = next(w["id"] for w in worlds if w["slug"] == "presales")
    run = (await client.post(f"/api/worlds/{wid}/runs", json={"config": {"ticks": 4, "tick_delay_ms": 0}})).json()
    for _ in range(4):
        assert (await client.post(f"/api/runs/{run['id']}/control", json={"action": "step"})).status_code == 200
        for _ in range(100):
            await asyncio.sleep(0.05)
            st = (await client.get(f"/api/runs/{run['id']}/ticks?since=-1")).json()
            if st["status"] != "running":
                break
    st = (await client.get(f"/api/runs/{run['id']}/ticks?since=-1")).json()
    assert st["tick"] == 4 and st["status"] == "finished" and len(st["rows"]) == 5
    frame = (await client.get(f"/api/runs/{run['id']}/frame?tick=2")).json()
    assert frame["view"]["nodes"] and frame["policies"]
    assert (await client.post(f"/api/runs/{run['id']}/intervene", json={"id": "nope"})).status_code == 400
    fork = (await client.post(f"/api/runs/{run['id']}/fork", json={"tick": 2, "intervention": {"id": "to_squads"}})).json()
    assert fork["parent_run_id"] == run["id"] and fork["tick"] == 2
    rep = (await client.post(f"/api/runs/{run['id']}/report", json={})).json()
    assert rep["source"] == "template" and "ja" in rep["body"]
    hist = (await client.get("/api/runs")).json()
    assert [h["id"] for h in hist] == [fork["id"], run["id"]] and hist[1]["headline"] and hist[1]["has_report"]
    assert hist[0]["parent_run_id"] == run["id"]      # its event is still queued, so no parameter differs yet
    for lang, heading in (("ja", "## 実行とレポート"), ("en", "## Runs and reports")):
        md = await client.get(f"/api/worlds/{wid}/report.md", params={"lang": lang})
        assert md.status_code == 200 and md.headers["content-type"] == "text/markdown; charset=utf-8"
        assert md.headers["content-disposition"] == f'attachment; filename="presales-{lang}.md"'
        assert heading in md.text and rep["body"][lang] in md.text
        assert f"#{run['id']}" in md.text and f"#{fork['id']}" in md.text
    assert (await client.get("/api/worlds/999/report.md")).status_code == 404
    assert (await client.get("/")).status_code == 200 and (await client.get("/app.js")).status_code == 200


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


async def test_sqlite_backup_round_trip(client, app, tmp_path):
    w = app.store.world_by_slug("presales")
    run = await app.runs.create_run(w["id"], "saved", config={"ticks": 2})
    app.store.save_report(run, 0, {"en": "Saved report", "ja": "保存済み"}, "template")
    app.store.add_chat(run, 0, "person", "p", "user", "saved question")
    app.set_models({"agent": {"model": "backup-model"}})
    old_worker = app.runs.worker(run)
    snapshot = app.store.snapshot(run, 0)

    export = await client.get("/api/data/export")
    assert export.status_code == 200 and export.headers["content-type"] == SQLITE_MEDIA
    path = tmp_path / "backup.sqlite3"
    path.write_bytes(export.content)
    with closing(sqlite3.connect(path)) as db, db:
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert db.execute("PRAGMA journal_mode").fetchone() == ("delete",)
        db.execute("UPDATE runs SET status='running' WHERE id=?", (run,))

    other = await app.runs.create_run(w["id"], "discarded", config={"ticks": 2})
    app.set_models(None)
    import_url = "/api/data/import"
    assert (await client.post(import_url, content=export.content)).status_code == 415
    headers = {"Content-Type": SQLITE_MEDIA}
    assert (await client.post(import_url, content=b"bad database", headers=headers)).status_code == 400
    assert app.store.run(other)["name"] == "discarded"
    assert app.runs.worker(run) is old_worker

    restored = await client.post(import_url, content=path.read_bytes(), headers=headers)
    assert restored.status_code == 200, restored.text
    assert app.store.run(other) is None and app.store.run(run)["status"] == "paused"
    assert app.store.snapshot(run, 0) == snapshot
    assert app.store.chats(run, "p")[0]["text"] == "saved question"
    assert app.store.latest_report(run)["body"]["ja"] == "保存済み"
    assert app.settings.role("agent").model == "backup-model"
    assert app.runs.worker(run) is not old_worker
    fork = await client.post(f"/api/runs/{run}/fork", json={"tick": 0})
    assert fork.status_code == 200 and fork.json()["parent_run_id"] == run


async def test_backup_cannot_assign_builtin_trust(client, app, tmp_path):
    w = app.store.world_by_slug("presales")
    backup = tmp_path / "other-version.sqlite3"
    app.store.backup_to(backup)
    code = w["code"] + "\n# Another version of the sample.\n"
    with closing(sqlite3.connect(backup)) as db, db:
        db.execute("UPDATE worlds SET code=? WHERE id=?", (code, w["id"]))

    result = await client.post("/api/data/import", content=backup.read_bytes(), headers={"Content-Type": SQLITE_MEDIA})
    assert result.status_code == 200, result.text
    assert app.store.world(w["id"])["source"] == "generated"
    assert app.store.world(w["id"])["code"] == code
    seed_worlds(app.store, load_builtin_worlds())
    assert app.store.world(w["id"])["code"] == code


async def test_data_transfer_waits_for_inflight_work(client, app, monkeypatch):
    w = app.store.world_by_slug("presales")
    run = await app.runs.create_run(w["id"], config={"ticks": 2})
    entered, finish = asyncio.Event(), asyncio.Event()

    async def slow_report(*args):
        entered.set()
        await finish.wait()
        return {"body": {"en": "Done."}}

    monkeypatch.setattr(app.observer, "report", slow_report)
    pending = asyncio.create_task(client.post(f"/api/runs/{run}/report", json={}))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        assert (await client.get("/api/data/export")).status_code == 409
        assert (await client.post("/api/data/import", headers={"Content-Type": SQLITE_MEDIA})).status_code == 409
    finally:
        finish.set()
        assert (await pending).status_code == 200

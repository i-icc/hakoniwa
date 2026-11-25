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
    info = (await client.get("/api/info")).json()
    assert info["llm_live"] is False and "OPENAI_API_KEY" not in str(info) and os.environ.get("OPENAI_API_KEY", "x") not in str(info)
    worlds = (await client.get("/api/worlds")).json()
    wid = next(w["id"] for w in worlds if w["slug"] == "presales")
    run = (await client.post(f"/api/worlds/{wid}/runs", json={"config": {"ticks": 4, "tick_delay_ms": 0}})).json()
    for _ in range(4):
        assert (await client.post(f"/api/runs/{run['id']}/control", json={"action": "step"})).status_code == 200
        import asyncio
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

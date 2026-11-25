"""HTTP delivery: a JSON API for the viewer, plus the static viewer itself."""
from __future__ import annotations

import re
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile

from anyio import CancelScope
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from ..application.estimator import estimate_run
from ..application.ports import LLMError, SandboxError
from ..bootstrap import EFFORTS, App, build_app
from ..domain.contract import clean_params, default_params
from ..domain.names import display_name, resident_names

WEB = Path(__file__).resolve().parent / "web"
SQLITE_MEDIA = "application/vnd.sqlite3"
TRANSFER_PATHS = {"/api/data/export", "/api/data/import"}


def create_app(app_: App | None = None) -> FastAPI:
    state: dict = {}

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        state["app"] = app_ or build_app()
        yield
        await state["app"].close()

    api = FastAPI(title="Hakoniwa", lifespan=lifespan)

    def A() -> App:
        return state["app"]

    pending = 0
    transferring = False

    @api.middleware("http")
    async def guard_transfer(request: Request, call_next):
        nonlocal pending, transferring
        path = request.url.path
        if not path.startswith("/api/"):
            return await call_next(request)
        transfer = path in TRANSFER_PATHS
        if transferring or (transfer and (pending or A().runs.busy or A().designer.busy)):
            return JSONResponse({"error": "Pause runs and wait for other work to finish before transferring data."},
                                status_code=409)
        pending += 1
        transferring = transfer
        try:
            return await call_next(request)
        finally:
            pending -= 1
            if transfer:
                transferring = False

    @api.exception_handler(LLMError)
    async def _llm(_: Request, e: LLMError):
        return JSONResponse({"error": str(e)}, status_code=502)

    @api.exception_handler(SandboxError)
    async def _sb(_: Request, e: SandboxError):
        return JSONResponse({"error": str(e), "trace": e.trace}, status_code=500)

    @api.exception_handler(KeyError)
    async def _missing(_: Request, e: KeyError):
        return JSONResponse({"error": f"not found: {e}"}, status_code=404)

    @api.exception_handler(ValueError)
    async def _bad(_: Request, e: ValueError):
        return JSONResponse({"error": str(e)}, status_code=400)

    def names_of(run: dict) -> dict:
        """key -> own name, for everyone who has appeared in the run."""
        return resident_names(A().store.world(run["world_id"])["spec"], A().store.residents(run["id"]))

    def run_or_404(run_id: int) -> dict:
        run = A().store.run(run_id)
        if not run:
            raise HTTPException(404, "run not found")
        return run

    def world_or_404(world_id: int) -> dict:
        w = A().store.world(world_id)
        if not w:
            raise HTTPException(404, "world not found")
        return w

    # -- general ------------------------------------------------------------
    @api.get("/api/info")
    async def info():
        a = A()
        pub = a.settings.public()
        pub["llm_live"] = a.llm.live
        pub["sandbox_backend"] = await a.sandboxes.backend()
        pub["prices"] = a.settings.prices.get("models", {})
        return pub

    @api.get("/api/data/export")
    async def export_data():
        with NamedTemporaryFile(suffix=".sqlite3", delete=False) as f:
            path = Path(f.name)
        try:
            await run_in_threadpool(A().store.backup_to, path)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return FileResponse(path, media_type=SQLITE_MEDIA, filename="hakoniwa.sqlite3",
                            headers={"Cache-Control": "no-store"}, background=BackgroundTask(path.unlink))

    @api.post("/api/data/import")
    async def import_data(request: Request):
        if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != SQLITE_MEDIA:
            raise HTTPException(415, f"Send a SQLite file as {SQLITE_MEDIA}.")
        path = None
        try:
            with NamedTemporaryFile(suffix=".sqlite3", delete=False) as f:
                path = Path(f.name)
                async for chunk in request.stream():
                    f.write(chunk)
            with CancelScope(shield=True):
                await A().restore_data(path)
            return {"ok": True}
        finally:
            if path is not None:
                path.unlink(missing_ok=True)

    # -- model choices ------------------------------------------------------
    NOT_CHAT = ("embed", "tts", "whisper", "audio", "image", "dall", "sora", "realtime", "moderation", "transcribe", "search", "codex", "healthcare")

    async def _models_payload() -> dict:
        a = A()
        priced = a.settings.prices.get("models", {})
        offered = [m for m in await a.llm.list_models() if not any(w in m for w in NOT_CHAT)]
        names = [m for m in priced if not offered or m in offered] + [m for m in offered if m not in priced]
        return {"roles": a.model_choices(), "available": names, "prices": priced, "efforts": list(EFFORTS), "live": a.llm.live}

    @api.get("/api/models")
    async def models():
        return await _models_payload()

    @api.post("/api/models")
    async def set_models(body: dict):
        A().set_models(body.get("roles") if isinstance(body.get("roles"), dict) else None)
        return await _models_payload()

    @api.delete("/api/models")
    async def reset_models():
        A().set_models(None)
        return await _models_payload()

    # -- worlds -------------------------------------------------------------
    @api.get("/api/worlds")
    async def worlds():
        out = []
        for w in A().store.worlds():
            s = w["spec"]
            out.append({"id": w["id"], "slug": w["slug"], "source": w["source"], "title": s.get("title"),
                        "summary": s.get("summary"), "tick": s.get("tick"), "scenario": s.get("scenario"),
                        "runs": len(A().store.runs_for_world(w["id"]))})
        return out

    @api.get("/api/worlds/{world_id}")
    async def world(world_id: int):
        w = world_or_404(world_id)
        return {"id": w["id"], "slug": w["slug"], "source": w["source"], "spec": w["spec"], "code": w["code"],
                "notes": w.get("notes") or "", "defaults": default_params(w["spec"]),
                "design_usage": A().store.world_usage(world_id), "runs": [_run_public(r) for r in A().store.runs_for_world(world_id)]}

    @api.get("/api/worlds/{world_id}/report.md")
    async def world_report(world_id: int, lang: str = "en"):
        w = world_or_404(world_id)
        lang = "ja" if lang == "ja" else "en"
        slug = re.sub(r"[^A-Za-z0-9_-]", "_", w["slug"])
        return Response(A().observer.world_markdown(w, lang), media_type="text/markdown; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{slug}-{lang}.md"',
                                 "Cache-Control": "no-store"})

    @api.delete("/api/worlds/{world_id}")
    async def delete_world(world_id: int):
        w = world_or_404(world_id)
        if w["source"] == "builtin":
            raise HTTPException(400, "sample worlds cannot be deleted")
        for r in A().store.runs_for_world(world_id):
            await A().runs.delete_run(r["id"])
        A().store.delete_world(world_id)
        return {"ok": True}

    @api.post("/api/scenario/draft")
    async def draft_scenario(body: dict):
        return await A().designer.draft_scenario(str(body.get("idea") or "")[:4000], str(body.get("lang") or "en"))

    @api.post("/api/worlds/design")
    async def design(body: dict):
        scenario = str(body.get("scenario") or "").strip()
        if len(scenario) < 20:
            raise HTTPException(400, "describe the scenario in a few sentences")
        return A().designer.start(scenario[:6000]).public()

    @api.get("/api/design")
    async def design_jobs():
        """Design jobs of this server session, newest first (lets the top page pick a running one back up)."""
        return [j.public() for j in sorted(A().designer.jobs.values(), key=lambda j: -j.id)]

    @api.get("/api/design/{job_id}")
    async def design_job(job_id: int):
        job = A().designer.jobs.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        return job.public()

    @api.post("/api/worlds/{world_id}/estimate")
    async def estimate(world_id: int, body: dict):
        a = A()
        w = world_or_404(world_id)
        params = clean_params(w["spec"], body.get("params"))
        return await estimate_run(a.store, a.sandboxes, a.llm, a.settings.prices, w, params, body.get("config"),
                                  a.settings.content_langs)

    @api.post("/api/worlds/{world_id}/runs")
    async def create_run(world_id: int, body: dict):
        world_or_404(world_id)
        run_id = await A().runs.create_run(world_id, name=body.get("name"), params=body.get("params"), config=body.get("config"))
        if body.get("start"):
            A().runs.worker(run_id).control("start")
        return _run_public(A().store.run(run_id))

    # -- runs ---------------------------------------------------------------
    def _run_public(r: dict) -> dict:
        return {k: r.get(k) for k in ("id", "world_id", "parent_run_id", "fork_tick", "name", "config", "params",
                                      "status", "tick", "error", "created_at")}

    @api.get("/api/runs")
    async def all_runs():
        """History: every run across all worlds, newest first."""
        a = A()
        specs = {w["id"]: w["spec"] for w in a.store.worlds()}
        out = []
        for r in a.store.all_runs():
            spec = specs.get(r["world_id"])
            if not spec:
                continue
            defaults = default_params(spec)
            labels = {p["id"]: p.get("label") for p in spec.get("parameters", [])}
            live = a.llm.live and r["config"].get("ai") != "mock" and r["calls"]
            out.append({
                "id": r["id"], "world_id": r["world_id"], "world_title": spec.get("title"), "name": r["name"],
                "parent_run_id": r["parent_run_id"], "fork_tick": r["fork_tick"], "status": r["status"], "tick": r["tick"],
                "total": r["config"].get("ticks"), "created_at": r["created_at"], "calls": r["calls"], "cost": None if r["unpriced"] else (r["cost"] or 0.0),
                "model": (r["config"].get("agent_model") or a.llm.model_for("agent")) if live else None,
                "has_report": bool(r["reports"]),
                "changed": [{"label": labels.get(k, k), "value": v} for k, v in r["params"].items() if k in defaults and defaults[k] != v],
                "headline": [{"label": m.get("label"), "value": r["last_metrics"].get(m["id"]), "format": m.get("format"), "unit": m.get("unit")}
                             for m in spec.get("metrics", []) if m.get("headline") and m["id"] in r["last_metrics"]][:3],
            })
        return out

    @api.get("/api/runs/{run_id}")
    async def run(run_id: int):
        r = _run_public(run_or_404(run_id))
        r["usage"] = A().store.usage(run_id)
        r["ai_live"] = A().llm.live and r["config"].get("ai") != "mock"
        return r

    @api.delete("/api/runs/{run_id}")
    async def delete_run(run_id: int):
        run_or_404(run_id)
        await A().runs.delete_run(run_id)
        return {"ok": True}

    @api.get("/api/runs/{run_id}/ticks")
    async def ticks(run_id: int, since: int = -1):
        r = run_or_404(run_id)
        return {"status": r["status"], "tick": r["tick"], "total": r["config"]["ticks"], "error": r.get("error"),
                "rows": A().store.ticks(run_id, since)}

    @api.get("/api/runs/{run_id}/frame")
    async def frame(run_id: int, tick: int | None = None):
        r = run_or_404(run_id)
        t = r["tick"] if tick is None else max(0, min(int(tick), r["tick"]))
        f = A().store.frame(run_id, t)
        if not f:
            raise HTTPException(404, "no such tick")
        s = A().store
        names = names_of(r)
        f["policies"] = [{"key": d["key"], "agent": d["agent"], "tick": d["tick"], "source": d["source"],
                          "name": display_name(names.get(d["key"]), d["request"].get("population")),
                          "node": d["request"].get("node"), "mode": d["request"].get("mode", "split"),
                          "population": d["request"].get("population"), "options": d["request"].get("options"),
                          "question": d["request"].get("question"), "situation": d["request"].get("situation"),
                          "action": d["response"].get("action"), "thought": d["response"].get("thought"),
                          "say": d["response"].get("say"), "summary": d["response"].get("summary"),
                          "summary_ja": d["response"].get("summary_ja")} for d in s.latest_decisions(run_id, t)]
        f["facts"] = [{"subject": x["subject"], "predicate": x["predicate"], "object": x["object"],
                       "valid_from": x["valid_from"], "origin": x["origin"]}
                      for x in s.facts_as_of(run_id, t) if x["origin"] != "decision"]
        return f

    @api.get("/api/runs/{run_id}/events")
    async def events(run_id: int, since_id: int = 0, upto: int | None = None, limit: int = 300):
        r = run_or_404(run_id)
        rows = A().store.events(run_id, since_id=since_id, upto_tick=upto, limit=min(limit, 2000))
        if any(e["kind"] == "say" for e in rows):
            names = names_of(r)
            groups = {d["key"]: d["request"].get("population") for d in A().store.latest_decisions(run_id, r["tick"])}
            for e in rows:
                if e["kind"] == "say":
                    key = e["payload"].get("key")
                    e["name"] = display_name(names.get(key), groups.get(key))
        return rows

    @api.get("/api/runs/{run_id}/history")
    async def history(run_id: int, key: str):
        run_or_404(run_id)
        rows = A().store.decisions(run_id, key=key, limit=200)
        return [{"tick": d["tick"], "source": d["source"], "action": d["response"].get("action"),
                 "thought": d["response"].get("thought"), "say": d["response"].get("say"),
                 "summary": d["response"].get("summary"), "summary_ja": d["response"].get("summary_ja"),
                 "clock": d["response"].get("clock")} for d in rows]

    @api.post("/api/runs/{run_id}/control")
    async def control(run_id: int, body: dict):
        run_or_404(run_id)
        action = body.get("action")
        if action not in ("start", "pause", "step", "stop", "set"):
            raise HTTPException(400, "unknown action")
        kw = {k: body[k] for k in ("tick_delay_ms", "ticks", "budget_usd") if k in body}
        A().runs.worker(run_id).control(action, **kw)
        return {"ok": True}

    @api.post("/api/runs/{run_id}/intervene")
    async def intervene(run_id: int, body: dict):
        r = run_or_404(run_id)
        spec = world_or_404(r["world_id"])["spec"]
        iv = _intervention(spec, body)
        A().runs.intervene(run_id, iv)
        return {"ok": True, "queued": iv}

    def _intervention(spec: dict, body: dict) -> dict:
        if body.get("id"):
            found = next((i for i in spec.get("interventions", []) if i["id"] == body["id"]), None)
            if not found:
                raise HTTPException(400, "unknown intervention")
            return {"patch": found["patch"], "label": found.get("label")}
        patch = clean_params(spec, body.get("patch"), runtime_only=True)
        if not patch:
            raise HTTPException(400, "no valid parameter changes")
        return {"patch": patch, "label": body.get("label")}

    @api.post("/api/runs/{run_id}/interpret")
    async def interpret(run_id: int, body: dict):
        run_or_404(run_id)
        return await A().observer.interpret(run_id, str(body.get("text") or "")[:1000])

    @api.post("/api/runs/{run_id}/fork")
    async def fork(run_id: int, body: dict):
        r = run_or_404(run_id)
        spec = world_or_404(r["world_id"])["spec"]
        iv = _intervention(spec, body["intervention"]) if body.get("intervention") else None
        new_id = await A().runs.fork(run_id, body.get("tick"), name=body.get("name"), intervention=iv, config=body.get("config"))
        if body.get("start"):
            A().runs.worker(new_id).control("start")
        return _run_public(A().store.run(new_id))

    @api.post("/api/runs/{run_id}/chat")
    async def chat(run_id: int, body: dict):
        run_or_404(run_id)
        return await A().observer.chat(run_id, str(body.get("key")), str(body.get("text") or "")[:2000], str(body.get("lang") or "en"))

    @api.get("/api/runs/{run_id}/chat")
    async def chat_log(run_id: int, key: str):
        run_or_404(run_id)
        return A().store.chats(run_id, key)

    @api.post("/api/runs/{run_id}/report")
    async def report(run_id: int, body: dict):
        run_or_404(run_id)
        return await A().observer.report(run_id, body.get("compare"))

    @api.get("/api/runs/{run_id}/report")
    async def last_report(run_id: int):
        run_or_404(run_id)
        rep = A().store.latest_report(run_id)
        return rep or {}

    # -- static viewer ------------------------------------------------------
    @api.get("/")
    async def index():
        return FileResponse(WEB / "index.html")

    api.mount("/", StaticFiles(directory=str(WEB)), name="web")
    return api

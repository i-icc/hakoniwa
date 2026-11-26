"""HTTP delivery: a JSON API for the viewer, plus the static viewer itself."""
from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..application.estimator import estimate_run
from ..application.ports import LLMError, SandboxError
from ..bootstrap import EFFORTS, App, build_app
from ..domain.contract import chance_events, check_code, check_spec, clean_params, default_params
from ..domain.names import display_name, resident_names

WEB = Path(__file__).resolve().parent / "web"
MAX_IMPORT_MB = int(os.environ.get("HAKONIWA_MAX_IMPORT_MB", "512"))


def create_app(app_: App | None = None) -> FastAPI:
    state: dict = {}

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        state["app"] = app_ or build_app()
        import asyncio
        keeper = asyncio.create_task(state["app"].copy_regularly()) if state["app"].settings.backup_dir else None
        yield
        if keeper:
            keeper.cancel()
        await state["app"].close()

    api = FastAPI(title="Hakoniwa", version=__version__, lifespan=lifespan)

    def A() -> App:
        return state["app"]

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
        pub["version"] = __version__
        pub["llm_live"] = a.llm.live
        pub["sandbox_backend"] = await a.sandboxes.backend()
        pub["prices"] = a.settings.prices.get("models", {})
        return pub

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
            job = A().designer.job_for(w["id"]) if w["source"] == "building" else None
            out.append({"id": w["id"], "slug": w["slug"], "source": w["source"], "title": s.get("title"),
                        "summary": s.get("summary"), "tick": s.get("tick"), "scenario": s.get("scenario"),
                        "runs": len(A().store.runs_for_world(w["id"])), "stage": job.stage if job else None, "life": bool(s.get("focus"))})
        return out

    @api.get("/api/worlds/{world_id}")
    async def world(world_id: int):
        w = world_or_404(world_id)
        if w["source"] in ("building", "failed"):          # not a world yet: its page shows the build
            job = A().designer.job_for(world_id)
            return {"id": w["id"], "slug": w["slug"], "source": w["source"], "spec": w["spec"], "code": "", "notes": "", "defaults": {},
                    "runs": [], "job": job.public() if job else None}
        return {"id": w["id"], "slug": w["slug"], "source": w["source"], "spec": {k: v for k, v in w["spec"].items() if k != "data"} | {"events": chance_events(w["spec"])}, "code": w["code"],
                "protagonist": (w["spec"].get("data") or {}).get("protagonist"),
                "notes": w.get("notes") or "", "defaults": default_params(w["spec"]),
                "design_usage": A().store.world_usage(world_id), "runs": [_run_public(r) for r in A().store.runs_for_world(world_id)]}

    @api.post("/api/worlds/{world_id}/checkup")
    async def world_checkup(world_id: int):
        """Rehearse a world with no AI and report what looks broken (free)."""
        from ..application.worlds import checkup
        w = world_or_404(world_id)
        rep = await checkup(A().sandboxes, w["spec"], w["code"], trusted=w["source"] == "builtin")
        return {"notes": rep["problems"] + rep["notes"], "asked": rep["asked"], "cast": rep["cast"], "questions": rep["questions"], "options": rep["options"]}

    @api.post("/api/worlds/{world_id}/events")
    async def write_events(world_id: int):
        """Have AI write this world's deck of chance events (replaces an earlier deck)."""
        world_or_404(world_id)
        return {"events": await A().designer.write_events(world_id)}

    @api.get("/api/worlds/{world_id}/cast")
    async def world_cast(world_id: int):
        """Everyone in the world's cast, in order: the viewer draws one square per person."""
        spec = world_or_404(world_id)["spec"]
        rows = (spec.get("data") or {}).get((spec.get("cast") or {}).get("collection") or "") or []
        return {"people": [{"name": r.get("name"), "about": r.get("story") or ""} for r in rows if isinstance(r, dict)]}

    @api.delete("/api/worlds/{world_id}")
    async def delete_world(world_id: int):
        w = world_or_404(world_id)
        if w["source"] == "builtin":
            raise HTTPException(400, "sample worlds cannot be deleted")
        A().designer.cancel(world_id)
        for r in A().store.runs_for_world(world_id):
            A().runs.delete_run(r["id"])
        A().store.delete_world(world_id)
        return {"ok": True}

    # -- data: take runs and worlds out as a SQLite file, and bring such a file in ----
    @api.get("/api/data")
    async def data_overview():
        a = A()
        keep = {"folder": str(a.settings.backup_dir), "minutes": a.settings.backup_minutes, "last": getattr(a, "last_copy", None)} if a.settings.backup_dir else None
        return a.store.data_overview() | {"max_import_mb": MAX_IMPORT_MB, "backup": keep}

    @api.post("/api/data/backup")
    async def data_backup():
        """Copy the database to the backup folder now (when HAKONIWA_BACKUP_DIR is set)."""
        if not A().settings.backup_dir:
            raise HTTPException(400, "no backup folder is configured (HAKONIWA_BACKUP_DIR)")
        return await A().keep_copy(force=True)

    @api.get("/api/data/export")
    async def data_export(runs: str = "", worlds: str = "", gz: int = 1):
        """The chosen runs and worlds as one SQLite file (gzipped unless gz=0). Empty lists mean nothing; "all" means all."""
        import gzip, shutil, tempfile
        from starlette.background import BackgroundTask
        ids = lambda s: None if s == "all" else [int(x) for x in s.split(",") if x.strip().isdigit()]
        folder = Path(tempfile.mkdtemp(prefix="hakoniwa-export-"))
        name = time.strftime("hakoniwa-%Y%m%d-%H%M") + ".sqlite3"
        A().store.export_to(folder / name, ids(runs), ids(worlds))
        if gz:
            with open(folder / name, "rb") as f, gzip.open(folder / (name + ".gz"), "wb", compresslevel=6) as g:
                shutil.copyfileobj(f, g)
            name += ".gz"
        return FileResponse(folder / name, filename=name, media_type="application/gzip" if gz else "application/vnd.sqlite3",
                            background=BackgroundTask(shutil.rmtree, folder, True))

    @api.post("/api/data/import")
    async def data_import(request: Request):
        """Add an exported file (plain or gzipped SQLite) to this database. Nothing already here is replaced."""
        import gzip, shutil, tempfile
        folder = Path(tempfile.mkdtemp(prefix="hakoniwa-import-"))
        try:
            raw, size = folder / "upload", 0
            with open(raw, "wb") as f:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > MAX_IMPORT_MB * 1024 * 1024:
                        raise HTTPException(413, f"the file is larger than {MAX_IMPORT_MB} MB")
                    f.write(chunk)
            db = raw
            with open(raw, "rb") as f:
                packed = f.read(2) == b"\x1f\x8b"
            if packed:
                db = folder / "db.sqlite3"
                with gzip.open(raw, "rb") as g, open(db, "wb") as f:
                    shutil.copyfileobj(g, f)
            check = lambda spec, code: check_spec(spec) + check_code(code)
            try:
                done = A().store.import_from(db, check)
                A().note_milestone()
                return done
            except (ValueError, OSError, EOFError) as e:
                raise HTTPException(400, f"this file could not be read as a Hakoniwa export: {e}")
        finally:
            shutil.rmtree(folder, True)

    @api.post("/api/scenario/draft")
    async def draft_scenario(body: dict):
        return await A().designer.draft_scenario(str(body.get("idea") or "")[:4000], str(body.get("lang") or "en"))

    # -- one person's crossroads ------------------------------------------------
    @api.post("/api/life/interview")
    async def life_interview(body: dict):
        story = str(body.get("story") or "").strip()
        if len(story) < 20:
            raise HTTPException(400, "say a little more about where you stand and what you are weighing")
        return await A().designer.life_interview(story[:6000], str(body.get("lang") or "en"))

    @api.post("/api/life/compose")
    async def life_compose(body: dict):
        answers = [a for a in (body.get("answers") or []) if isinstance(a, dict)][:12]
        return await A().designer.life_compose(str(body.get("story") or "")[:6000], answers, str(body.get("lang") or "en"))

    @api.get("/api/worlds/{world_id}/futures")
    async def futures(world_id: int, lang: str = "en"):
        if not world_or_404(world_id)["spec"].get("focus"):
            raise HTTPException(400, "this world is not about one person")
        return A().observer.futures(world_id, lang) | {"report": A().store.get_setting(f"life_report:{world_id}")}

    @api.post("/api/worlds/{world_id}/futures")
    async def make_futures(world_id: int, body: dict):
        """Start several futures at once: every path, each with the same few strokes of luck (seeds), so that
        future 2 of one path and future 2 of another meet the same outside events."""
        w = world_or_404(world_id)
        focus = w["spec"].get("focus")
        if not focus:
            raise HTTPException(400, "this world is not about one person")
        per = max(1, min(int(body.get("per_path") or 3), 6))
        lang = str(body.get("lang") or "en")
        have = {(r["params"].get(focus["path_param"]), r["config"].get("seed")) for r in A().store.runs_for_world(world_id)}
        made = []
        for o in focus["options"]:
            for k in range(1, 50):
                if len([m for m in made if m["path"] == o["id"]]) >= per:
                    break
                if (o["id"], k) in have:
                    continue
                label = (o.get("label") or {}).get(lang) or (o.get("label") or {}).get("en") or o["id"]
                rid = await A().runs.create_run(world_id, name=f"{label} · {k}", params={focus["path_param"]: o["id"]},
                                                config={"seed": k, "chance": True, "tick_delay_ms": 0, "ticks": body.get("ticks")})
                A().runs.worker(rid).control("start")
                made.append({"id": rid, "path": o["id"], "seed": k})
        return {"made": made}

    @api.post("/api/worlds/{world_id}/life-report")
    async def life_report(world_id: int, body: dict):
        world_or_404(world_id)
        return await A().observer.life_report(world_id, body.get("lang"))

    @api.get("/api/worlds/{world_id}/life-report.md")
    async def life_report_md(world_id: int, lang: str = "en"):
        from fastapi.responses import Response
        w = world_or_404(world_id)
        rep = A().store.get_setting(f"life_report:{world_id}") or {}
        body = rep.get("body") or {}
        if not body:
            raise HTTPException(404, "no report has been written yet")
        return Response(body.get(lang) or next(iter(body.values())), media_type="text/markdown; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="hakoniwa-{w["slug"]}-futures.md"'})

    @api.post("/api/scenario/questions")
    async def scenario_questions(body: dict):
        """What the designer would like settled before it builds (may be nothing)."""
        scenario = str(body.get("scenario") or "").strip()
        if len(scenario) < 20:
            raise HTTPException(400, "describe the scenario in a few sentences")
        based_on = body.get("based_on")
        return await A().designer.clarify(scenario[:8000], str(body.get("lang") or "en"),
                                          based_on if isinstance(based_on, int) and A().store.world(based_on) else None)

    @api.post("/api/worlds/design")
    async def design(body: dict):
        scenario = str(body.get("scenario") or "").strip()
        if len(scenario) < 20:
            raise HTTPException(400, "describe the scenario in a few sentences")
        based_on = body.get("based_on")
        return A().designer.start(scenario[:8000], str(body.get("reference") or "")[:400_000],
                                  int(based_on) if isinstance(based_on, int) and A().store.world(based_on) else None,
                                  body.get("life") if isinstance(body.get("life"), dict) else None).public()

    @api.post("/api/worlds/{world_id}/evolve")
    async def evolve(world_id: int, body: dict):
        """Thoughts about a world, turned into the scenario for a new one (nothing is built yet)."""
        world_or_404(world_id)
        comment = str(body.get("comment") or "").strip()
        if len(comment) < 10:
            raise HTTPException(400, "say a little more about where you want to take this world")
        return await A().designer.evolve_scenario(world_id, comment[:4000], str(body.get("lang") or "en"))

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
        if world_or_404(world_id)["source"] in ("building", "failed"):
            raise HTTPException(400, "this world is not built yet")
        run_id = await A().runs.create_run(world_id, name=body.get("name"), params=body.get("params"), config=body.get("config"))
        if body.get("start"):
            A().runs.worker(run_id).control("start")
        return _run_public(A().store.run(run_id))

    # -- runs ---------------------------------------------------------------
    def _run_public(r: dict) -> dict:
        result = {k: r.get(k) for k in ("id", "world_id", "parent_run_id", "fork_tick", "name", "params",
                                        "status", "tick", "error", "created_at")}
        result["config"] = {k: v for k, v in r["config"].items() if k != "model_revisions"}
        result["rebuilt"] = any(v["tick"] == r["fork_tick"] for v in r["config"].get("model_revisions", []))
        return result

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
        A().runs.delete_run(run_id)
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
                          "say": d["response"].get("say"), "meant": d["response"].get("meant"), "summary": d["response"].get("summary"),
                          "summary_ja": d["response"].get("summary_ja")} for d in s.latest_decisions(run_id, t)]
        f["facts"] = [{"subject": x["subject"], "predicate": x["predicate"], "object": x["object"],
                       "valid_from": x["valid_from"], "origin": x["origin"]}
                      for x in s.facts_as_of(run_id, t) if x["origin"] != "decision"]
        return f

    @api.get("/api/runs/{run_id}/cells")
    async def cells(run_id: int, tick: int | None = None):
        """The automaton's own state at a tick, one value per resident for each plain variable the model keeps
        (numbers, words, yes/no; a list is shown as its length). Read from the stored snapshot, so any run works."""
        r = run_or_404(run_id)
        t = r["tick"] if tick is None else max(0, min(int(tick), r["tick"]))
        spec = world_or_404(r["world_id"])["spec"]
        size = len((spec.get("data") or {}).get((spec.get("cast") or {}).get("collection") or "") or [])
        snap = A().store.snapshot(run_id, t)
        rows = next((v for v in ((snap or {}).get("state") or {}).values()
                     if isinstance(v, list) and size and len(v) == size and all(isinstance(x, dict) for x in v)), None)
        if not rows:
            return {"tick": t, "vars": [], "cells": {}}
        plain = lambda v: len(v) if isinstance(v, (list, dict)) else v
        keys = [k for k, v in rows[0].items() if isinstance(v, (int, float, str, bool, list)) or v is None]
        out, kinds = {}, []
        for k in keys:
            col = [plain(x.get(k)) for x in rows]
            num = all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in col)
            out[k] = [round(v, 3) if isinstance(v, float) else v for v in col]
            kinds.append({"id": k, "kind": "num" if num else "cat"})
        return {"tick": t, "vars": kinds, "cells": out}

    _moves: dict = {}          # (run, variable, last tick) -> result; snapshots do not change once written

    @api.get("/api/runs/{run_id}/transitions")
    async def transitions(run_id: int, var: str):
        """The automaton as a state diagram, measured: for one state variable that takes a few values,
        how many residents moved from each value to each other value at every tick."""
        r = run_or_404(run_id)
        hit = _moves.get((run_id, var, r["tick"]))
        if hit:
            return hit
        spec = world_or_404(r["world_id"])["spec"]
        size = len((spec.get("data") or {}).get((spec.get("cast") or {}).get("collection") or "") or [])
        states: list[str] = []
        moves, prev = [], None
        for t in range(0, r["tick"] + 1):
            snap = A().store.snapshot(run_id, t)
            rows = next((v for v in ((snap or {}).get("state") or {}).values()
                         if isinstance(v, list) and size and len(v) == size and all(isinstance(x, dict) for x in v)), None)
            if rows is None:
                continue
            now = [str(x.get(var)) for x in rows]
            for s in now:
                if s not in states:
                    states.append(s)
                    if len(states) > 12:
                        raise HTTPException(400, "this variable takes too many values for a state diagram")
            if prev is not None:
                tally: dict = {}
                for a, b in zip(prev, now):
                    if a != b:
                        tally[(a, b)] = tally.get((a, b), 0) + 1
                moves += [[t, states.index(a), states.index(b), n] for (a, b), n in tally.items()]
            prev = now
        out = {"var": var, "states": states, "moves": moves}
        if len(_moves) > 40:
            _moves.clear()
        _moves[(run_id, var, r["tick"])] = out
        return out

    @api.get("/api/runs/{run_id}/events")
    async def events(run_id: int, since_id: int = 0, upto: int | None = None, limit: int = 300):
        r = run_or_404(run_id)
        rows = A().store.events(run_id, since_id=since_id, upto_tick=upto, limit=min(limit, 2000))
        if since_id == 0 and rows and len(rows) >= min(limit, 2000):          # the page is full: keep the few events that are not speech
            rows = A().store.earlier_happenings(run_id, rows[0]["id"]) + rows
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
        text = str(body.get("text") or "").strip()[:1000]
        if not text:
            raise HTTPException(400, "Describe the event first.")
        tick = body.get("tick")
        return await A().observer.interpret(run_id, text, int(tick) if tick is not None else None)

    @api.post("/api/runs/{run_id}/fork")
    async def fork(run_id: int, body: dict):
        r = run_or_404(run_id)
        spec = world_or_404(r["world_id"])["spec"]
        event_text = str(body.get("event_text") or "").strip()[:1000]
        rebuild = body.get("rebuild") is True
        if rebuild and (not event_text or body.get("intervention") or body.get("person")):
            raise HTTPException(400, "Rebuilding requires an event description and replaces the preset intervention.")
        iv = _intervention(spec, body["intervention"]) if body.get("intervention") else None
        if event_text and not (rebuild or iv):
            raise HTTPException(400, "Choose parameter changes or rebuild the model for this event.")
        person = body.get("person")
        if isinstance(person, dict) and person.get("key"):          # step in on one resident at the fork
            if not (str(person.get("tell") or "").strip() or person.get("choice")):
                raise HTTPException(400, "say something to them or choose what they do")
            iv = {"person": {"key": str(person["key"]), "tell": str(person.get("tell") or "")[:500], "choice": person.get("choice")}}
        new_id = await A().runs.fork(run_id, body.get("tick"), name=body.get("name"), intervention=iv,
                                     config=body.get("config"), event_text=event_text, rebuild=rebuild)
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

    @api.post("/api/runs/{run_id}/ask")
    async def ask(run_id: int, body: dict):
        """A question to the analyst about this run and its report."""
        run_or_404(run_id)
        return await A().observer.ask(run_id, str(body.get("text") or "")[:2000], str(body.get("lang") or "en"), body.get("compare"))

    @api.get("/api/runs/{run_id}/ask")
    async def ask_log(run_id: int):
        run_or_404(run_id)
        return A().store.chats(run_id, A().observer.ANALYST)

    @api.post("/api/runs/{run_id}/report")
    async def report(run_id: int, body: dict):
        run_or_404(run_id)
        return await A().observer.report(run_id, body.get("compare"), body.get("lang"))

    @api.get("/api/runs/{run_id}/report.md")
    async def report_markdown(run_id: int, lang: str = "en"):
        """The report (and the questions put to the analyst) as a Markdown file to keep."""
        from fastapi.responses import Response
        r = run_or_404(run_id)
        text = A().observer.report_markdown(run_id, lang)
        if text is None:
            raise HTTPException(404, "no report has been written for this run yet")
        slug = A().store.world(r["world_id"])["slug"]
        return Response(text, media_type="text/markdown; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="hakoniwa-{slug}-run{run_id}.md"'})

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

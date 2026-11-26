"""Command line: start the viewer, or run and estimate worlds without it."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from .. import __version__
from ..application.engine import run_headless
from ..application.estimator import estimate_run
from ..application.worlds import validate_world
from ..bootstrap import build_app
from ..domain.text import T


def _usd(v) -> str:
    return "price unknown" if v is None else f"${v:,.4f}"


async def _worlds(args) -> int:
    app = build_app()
    for w in app.store.worlds():
        print(f"{w['slug']:16s} {w['source']:9s} {T(w['spec'].get('title'))}")
    await app.close()
    return 0


async def _estimate(args) -> int:
    app = build_app()
    w = app.store.world_by_slug(args.world)
    if not w:
        print(f"unknown world '{args.world}'", file=sys.stderr)
        return 2
    cfg = {"ticks": args.ticks, "seed": args.seed}
    est = await estimate_run(app.store, app.sandboxes, app.llm, app.settings.prices, w, json.loads(args.params or "{}"), cfg,
                             app.settings.content_langs)
    print(f"World: {T(w['spec']['title'])}   ticks: {est['ticks']}   questions to residents: {est['calls']}")
    print(f"{'model':22s} {'likely':>10s} {'low':>10s} {'high':>10s}  output tokens per answer")
    for r in est["by_model"]:
        mark = "*" if r["model"] == est["agent_model"] else " "
        print(f"{mark}{r['model']:21s} {_usd(r['cost']):>10s} {_usd(r['low']):>10s} {_usd(r['high']):>10s}  {r['out_per_call']} ({r['basis']})")
    print(f"Report at the end ({est['report']['model']}): about {_usd(est['report']['cost'])}")
    print(est["note"])
    await app.close()
    return 0


async def _run(args) -> int:
    app = build_app()
    w = app.store.world_by_slug(args.world)
    if not w:
        print(f"unknown world '{args.world}'", file=sys.stderr)
        return 2
    cfg = {"ticks": args.ticks, "seed": args.seed, "ai": "mock" if args.no_ai else "auto"}
    run_id = await app.runs.create_run(w["id"], name=args.name, params=json.loads(args.params or "{}"), config=cfg)
    heads = [m for m in w["spec"]["metrics"] if m.get("headline")]
    await run_headless(app.runs, run_id, on_tick=lambda wk: print(f"\r{wk.last_clock:28s}", end="", flush=True))
    last = app.store.ticks(run_id)[-1]["metrics"]
    print(f"\nRun {run_id} finished.")
    for m in heads:
        print(f"  {T(m['label']):42s} {last.get(m['id']):>16,} {T(m.get('unit'))}")
    u = app.store.usage(run_id)
    print(f"  AI calls: {u['calls']}   tokens: {u['tokens_in']:,} in / {u['tokens_out']:,} out   cost: {_usd(u['cost'])}")
    if args.report:
        rep = await app.observer.report(run_id)
        print("\n" + rep["body"].get(args.lang) or rep["body"].get("en", ""))
    await app.close()
    return 0


async def _check(args) -> int:
    app = build_app()
    bad = 0
    for summary in app.store.worlds():
        w = app.store.world(summary["id"])
        if w is None or w["source"] in ("building", "failed"):
            continue
        problems = await validate_world(app.sandboxes, w["spec"], w["code"], trusted=w["source"] == "builtin")
        print(f"{w['slug']:16s} {'ok' if not problems else 'PROBLEMS'}")
        for p in problems[:5]:
            print("   -", p)
        bad += bool(problems)
    await app.close()
    return 1 if bad else 0


async def _export(args) -> int:
    """Write a world from the database as sample files (spec.json, model.py, data.json, cast.json)."""
    from pathlib import Path
    app = build_app()
    w = app.store.world_by_slug(args.world)
    if not w:
        print(f"unknown world '{args.world}'", file=sys.stderr)
        return 2
    out = Path(args.dir)
    out.mkdir(parents=True, exist_ok=True)
    spec = dict(w["spec"])
    data, cast = spec.pop("data", None), spec.pop("cast", None)
    (out / "spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=1) + "\n")
    (out / "model.py").write_text(w["code"])
    if data:
        (out / "data.json").write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n")
    if cast:
        (out / "cast.json").write_text(json.dumps(cast, ensure_ascii=False, indent=1) + "\n")
    print(f"wrote {out}/ (spec.json, model.py" + (", data.json" if data else "") + (", cast.json" if cast else "") + ")")
    await app.close()
    return 0


def _serve(args) -> int:
    import uvicorn

    from ..infrastructure.config import load_settings
    from .http import create_app
    s = load_settings()
    host, port = args.host or s.host, args.port or s.port
    print(f"Hakoniwa {__version__}: http://{host}:{port}   (AI: {s.llm_mode}, sandbox: {s.sandbox})")
    uvicorn.run(create_app(), host=host, port=port, log_level="warning")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="hakoniwa", description="Math-model worlds with AI residents.")
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("serve", help="start the viewer (default)")
    s.add_argument("--host")
    s.add_argument("--port", type=int)
    sub.add_parser("worlds", help="list worlds")
    sub.add_parser("check", help="validate every world in the sandbox")
    ex = sub.add_parser("export", help="write a world from the database as sample files")
    ex.add_argument("world")
    ex.add_argument("dir")
    for name, help_ in (("estimate", "estimate the AI cost of a run"), ("run", "run a world in the terminal")):
        c = sub.add_parser(name, help=help_)
        c.add_argument("world")
        c.add_argument("--ticks", type=int)
        c.add_argument("--seed", type=int, default=1)
        c.add_argument("--params", help='JSON, e.g. \'{"jet_sailings": 4}\'')
        if name == "run":
            c.add_argument("--name")
            c.add_argument("--no-ai", action="store_true", help="residents follow the model's defaults; no API calls")
            c.add_argument("--report", action="store_true", help="print a written report at the end")
            c.add_argument("--lang", default="en")
    args = p.parse_args(argv)
    if args.cmd in (None, "serve"):
        if args.cmd is None:
            args.host = args.port = None
        return _serve(args)
    return asyncio.run({"worlds": _worlds, "estimate": _estimate, "run": _run, "check": _check, "export": _export}[args.cmd](args))


if __name__ == "__main__":
    raise SystemExit(main())

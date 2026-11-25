"""SQLite adapter for the Store port. One local file holds worlds, runs, per-tick history,
snapshots (for forking), the temporal fact graph, and LLM usage."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Any, Iterable

from ..domain.contract import check_code, check_spec

SCHEMA = """
CREATE TABLE IF NOT EXISTS worlds (
  id INTEGER PRIMARY KEY, slug TEXT UNIQUE, source TEXT, spec TEXT, code TEXT,
  notes TEXT, created_at REAL
);
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY, world_id INTEGER, parent_run_id INTEGER, fork_tick INTEGER,
  name TEXT, config TEXT, params TEXT, status TEXT, tick INTEGER DEFAULT 0,
  error TEXT, created_at REAL, updated_at REAL
);
CREATE TABLE IF NOT EXISTS ticks (
  run_id INTEGER, tick INTEGER, metrics TEXT, view TEXT, PRIMARY KEY (run_id, tick)
);
CREATE TABLE IF NOT EXISTS snapshots (
  run_id INTEGER, tick INTEGER, state TEXT, rng TEXT, params TEXT, PRIMARY KEY (run_id, tick)
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY, run_id INTEGER, tick INTEGER, kind TEXT, agent TEXT,
  node TEXT, payload TEXT
);
CREATE INDEX IF NOT EXISTS events_run ON events(run_id, tick);
CREATE TABLE IF NOT EXISTS decisions (
  id INTEGER PRIMARY KEY, run_id INTEGER, tick INTEGER, key TEXT, agent TEXT,
  request TEXT, response TEXT, source TEXT, model TEXT,
  tokens_in INTEGER, tokens_out INTEGER, cost REAL
);
CREATE INDEX IF NOT EXISTS decisions_run ON decisions(run_id, tick);
CREATE INDEX IF NOT EXISTS decisions_key ON decisions(run_id, key, tick);
-- Temporal fact graph: (subject) -[predicate]-> (object), true from valid_from
-- until valid_to (NULL = still true). Replaces an external temporal-KG service.
CREATE TABLE IF NOT EXISTS facts (
  id INTEGER PRIMARY KEY, run_id INTEGER, subject TEXT, predicate TEXT, object TEXT,
  valid_from INTEGER, valid_to INTEGER, origin TEXT
);
CREATE INDEX IF NOT EXISTS facts_run ON facts(run_id, subject, predicate);
CREATE TABLE IF NOT EXISTS llm_calls (
  id INTEGER PRIMARY KEY, run_id INTEGER, world_id INTEGER, role TEXT, model TEXT,
  tokens_in INTEGER, tokens_out INTEGER, cost REAL, ms INTEGER, estimated INTEGER,
  created_at REAL
);
CREATE TABLE IF NOT EXISTS chats (
  id INTEGER PRIMARY KEY, run_id INTEGER, tick INTEGER, agent TEXT, key TEXT,
  role TEXT, text TEXT, created_at REAL
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS reports (
  id INTEGER PRIMARY KEY, run_id INTEGER, tick INTEGER, body TEXT, source TEXT, created_at REAL
);
"""


def _j(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"))


class InvalidBackup(ValueError):
    """A file that cannot be restored as a Hakoniwa database."""


_JSON_FIELDS = {
    "runs": {"config": "object", "params": "object"},
    "ticks": {"metrics": "object", "view": "object"},
    "snapshots": {"state": "object", "rng": "array", "params": "object"},
    "events": {"payload": "object"},
    "decisions": {"request": "object", "response": "object"},
    "reports": {"body": "object"},
    "facts": {"object": None},
    "settings": {"value": None},
}


class SqliteStore:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None, uri=True)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
            self.conn.execute("PRAGMA trusted_schema=OFF")
            self.conn.executescript(SCHEMA)

    # -- database transfer --------------------------------------------------
    def backup_to(self, path: Path) -> None:
        """Write a standalone snapshot, including committed content in the WAL."""
        with self.lock, closing(sqlite3.connect(path)) as output:
            self.conn.backup(output)
            output.execute("PRAGMA journal_mode=DELETE")

    def restore_from(self, path: Path, builtin: list[dict]) -> None:
        """Validate the source and atomically replace rows in the local schema."""
        with self.lock:
            db = self.conn
            try:
                db.execute("ATTACH DATABASE ? AS incoming", (path.resolve().as_uri() + "?mode=ro&immutable=1",))
                try:
                    tables, untrusted = self._check_backup(builtin)
                    with self.tx():
                        for table in tables:
                            db.execute(f'DELETE FROM main."{table}"')
                            db.execute(f'INSERT INTO main."{table}" SELECT * FROM incoming."{table}"')
                        db.executemany("UPDATE main.worlds SET source='generated' WHERE id=?", untrusted)
                        self.pause_running_runs()
                finally:
                    db.execute("DETACH DATABASE incoming")
            except sqlite3.Error as e:
                raise InvalidBackup(f"Could not restore the SQLite backup: {e}") from e

    def _check_backup(self, builtin: list[dict]) -> tuple[list[str], list[tuple[int]]]:
        def schema(name: str):
            return self.conn.execute(f"SELECT type, name, tbl_name, sql FROM {name}.sqlite_schema"
                                     " WHERE name NOT GLOB 'sqlite_*' ORDER BY name").fetchall()

        expected = schema("main")
        if schema("incoming") != expected:
            raise InvalidBackup("The file does not have the expected Hakoniwa database schema.")
        if [row[0] for row in self.conn.execute("PRAGMA incoming.integrity_check")] != ["ok"]:
            raise InvalidBackup("The SQLite integrity check failed.")

        for table, fields in _JSON_FIELDS.items():
            for column, kind in fields.items():
                check = f'CASE WHEN json_valid("{column}") THEN json_type("{column}") = ? ELSE 0 END' if kind else f'json_valid("{column}")'
                if self.conn.execute(f'SELECT 1 FROM incoming."{table}" WHERE NOT ({check}) LIMIT 1',
                                     (kind,) if kind else ()).fetchone():
                    raise InvalidBackup(f"The backup contains invalid data in {table}.{column}.")

        if self.conn.execute(
            "SELECT 1 FROM incoming.runs r LEFT JOIN incoming.worlds w ON w.id = r.world_id"
            " WHERE w.id IS NULL OR r.name IS NULL OR r.tick IS NULL OR r.tick < 0"
            " OR r.status IS NULL OR r.status NOT IN ('created', 'running', 'paused', 'finished', 'failed')"
            " OR json_type(r.config, '$.ticks') IS NOT 'integer'"
            " OR r.parent_run_id >= r.id LIMIT 1"
        ).fetchone():
            raise InvalidBackup("The backup contains an invalid run.")

        shipped = {w["slug"]: w for w in builtin}
        untrusted = []
        for row in self.conn.execute("SELECT id, slug, source, spec, code FROM incoming.worlds"):
            wid, slug, source, raw_spec, code = row
            try:
                spec = json.loads(raw_spec)
                if not isinstance(slug, str) or not isinstance(code, str) or check_spec(spec) or check_code(code):
                    raise ValueError
            except (TypeError, ValueError, AttributeError) as e:
                raise InvalidBackup(f"The backup contains an invalid world (ID {wid}).") from e
            local = shipped.get(slug)
            if source != "generated" and not (source == "builtin" and local and
                                               local["spec"] == spec and local["code"] == code):
                untrusted.append((wid,))
        return [row["name"] for row in expected if row["type"] == "table"], untrusted

    # -- low level ----------------------------------------------------------
    def x(self, sql: str, args: Iterable = ()) -> sqlite3.Cursor:
        with self.lock:
            return self.conn.execute(sql, tuple(args))

    def q(self, sql: str, args: Iterable = ()) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, tuple(args)).fetchall()]

    def one(self, sql: str, args: Iterable = ()) -> dict | None:
        rows = self.q(sql, args)
        return rows[0] if rows else None

    def tx(self):
        return _Tx(self)

    # -- worlds -------------------------------------------------------------
    def upsert_world(self, slug: str, source: str, spec: dict, code: str, notes: str = "") -> int:
        row = self.one("SELECT id FROM worlds WHERE slug=?", (slug,))
        if row:
            self.x("UPDATE worlds SET source=?, spec=?, code=?, notes=? WHERE id=?",
                   (source, _j(spec), code, notes, row["id"]))
            return row["id"]
        cur = self.x("INSERT INTO worlds(slug, source, spec, code, notes, created_at) VALUES(?,?,?,?,?,?)",
                     (slug, source, _j(spec), code, notes, time.time()))
        return cur.lastrowid

    def world(self, world_id: int) -> dict | None:
        row = self.one("SELECT * FROM worlds WHERE id=?", (world_id,))
        if row:
            row["spec"] = json.loads(row["spec"])
        return row

    def world_by_slug(self, slug: str) -> dict | None:
        row = self.one("SELECT id FROM worlds WHERE slug=?", (slug,))
        return self.world(row["id"]) if row else None

    def delete_world(self, world_id: int) -> None:
        for r in self.q("SELECT id FROM runs WHERE world_id=?", (world_id,)):
            self.delete_run(r["id"])
        self.x("DELETE FROM worlds WHERE id=?", (world_id,))

    def worlds(self) -> list[dict]:
        rows = self.q("SELECT id, slug, source, spec, created_at FROM worlds ORDER BY source, id")
        for r in rows:
            r["spec"] = json.loads(r["spec"])
        return rows

    # -- runs ---------------------------------------------------------------
    def create_run(self, world_id: int, name: str, config: dict, params: dict,
                   parent: int | None = None, fork_tick: int | None = None) -> int:
        now = time.time()
        cur = self.x(
            "INSERT INTO runs(world_id, parent_run_id, fork_tick, name, config, params, status, tick, created_at, updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (world_id, parent, fork_tick, name, _j(config), _j(params), "created", fork_tick or 0, now, now))
        return cur.lastrowid

    def run(self, run_id: int) -> dict | None:
        row = self.one("SELECT * FROM runs WHERE id=?", (run_id,))
        if row:
            row["config"] = json.loads(row["config"])
            row["params"] = json.loads(row["params"])
        return row

    def runs_for_world(self, world_id: int) -> list[dict]:
        rows = self.q("SELECT * FROM runs WHERE world_id=? ORDER BY id", (world_id,))
        for r in rows:
            r["config"] = json.loads(r["config"])
            r["params"] = json.loads(r["params"])
        return rows

    def all_runs(self) -> list[dict]:
        """Every run, newest first, with what the history page needs."""
        rows = self.q("SELECT r.*, (SELECT metrics FROM ticks t WHERE t.run_id=r.id ORDER BY tick DESC LIMIT 1) AS last_metrics,"
                      " (SELECT COUNT(*) FROM reports p WHERE p.run_id=r.id) AS reports,"
                      " (SELECT COUNT(*) FROM llm_calls c WHERE c.run_id=r.id) AS calls,"
                      " (SELECT SUM(cost) FROM llm_calls c WHERE c.run_id=r.id) AS cost,"
                      " (SELECT COUNT(*) FROM llm_calls c WHERE c.run_id=r.id AND c.cost IS NULL) AS unpriced"
                      " FROM runs r ORDER BY r.id DESC")
        for r in rows:
            r["config"] = json.loads(r["config"])
            r["params"] = json.loads(r["params"])
            r["last_metrics"] = json.loads(r["last_metrics"]) if r["last_metrics"] else {}
        return rows

    def pause_running_runs(self) -> None:
        """Runs that were live when the server last stopped are simply paused."""
        self.x("UPDATE runs SET status='paused' WHERE status='running'")

    def set_run(self, run_id: int, **fields) -> None:
        fields["updated_at"] = time.time()
        for k in ("config", "params"):
            if k in fields and not isinstance(fields[k], str):
                fields[k] = _j(fields[k])
        cols = ", ".join(f"{k}=?" for k in fields)
        self.x(f"UPDATE runs SET {cols} WHERE id=?", (*fields.values(), run_id))

    # -- per tick -----------------------------------------------------------
    def save_tick(self, run_id: int, tick: int, metrics: dict, view: dict, snapshot: dict, params: dict) -> None:
        self.x("INSERT OR REPLACE INTO ticks(run_id, tick, metrics, view) VALUES(?,?,?,?)",
               (run_id, tick, _j(metrics), _j(view)))
        self.x("INSERT OR REPLACE INTO snapshots(run_id, tick, state, rng, params) VALUES(?,?,?,?,?)",
               (run_id, tick, _j(snapshot["state"]), _j(snapshot["rng"]), _j(params)))

    def ticks(self, run_id: int, since: int = -1) -> list[dict]:
        rows = self.q("SELECT tick, metrics, json_extract(view, '$.clock') AS clock FROM ticks"
                      " WHERE run_id=? AND tick>? ORDER BY tick", (run_id, since))
        def clock(v):   # a plain string, or a {en, ja} object stored as JSON text
            return json.loads(v) if isinstance(v, str) and v.startswith("{") else v
        return [{"tick": r["tick"], "metrics": json.loads(r["metrics"]), "clock": clock(r["clock"])} for r in rows]

    def frame(self, run_id: int, tick: int) -> dict | None:
        row = self.one("SELECT tick, metrics, view FROM ticks WHERE run_id=? AND tick=?", (run_id, tick))
        if not row:
            return None
        return {"tick": row["tick"], "metrics": json.loads(row["metrics"]), "view": json.loads(row["view"])}

    def snapshot(self, run_id: int, tick: int) -> dict | None:
        row = self.one("SELECT * FROM snapshots WHERE run_id=? AND tick=?", (run_id, tick))
        if not row:
            return None
        return {"state": json.loads(row["state"]), "rng": json.loads(row["rng"]),
                "params": json.loads(row["params"]), "tick": row["tick"]}

    def add_event(self, run_id: int, tick: int, kind: str, payload: dict,
                  agent: str | None = None, node: str | None = None) -> int:
        cur = self.x("INSERT INTO events(run_id, tick, kind, agent, node, payload) VALUES(?,?,?,?,?,?)",
                     (run_id, tick, kind, agent, node, _j(payload)))
        return cur.lastrowid

    def events(self, run_id: int, since_id: int = 0, upto_tick: int | None = None, limit: int = 400) -> list[dict]:
        sql = "SELECT * FROM events WHERE run_id=? AND id>?"
        args: list = [run_id, since_id]
        if upto_tick is not None:
            sql += " AND tick<=?"
            args.append(upto_tick)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        rows = self.q(sql, args)
        for r in rows:
            r["payload"] = json.loads(r["payload"])
        return list(reversed(rows))

    def add_decision(self, run_id: int, tick: int, key: str, agent: str, request: dict, response: dict,
                     source: str, model: str | None, tokens_in: int, tokens_out: int, cost: float | None) -> None:
        self.x("INSERT INTO decisions(run_id, tick, key, agent, request, response, source, model, tokens_in, tokens_out, cost)"
               " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
               (run_id, tick, key, agent, _j(request), _j(response), source, model, tokens_in, tokens_out, cost))

    def decisions(self, run_id: int, tick: int | None = None, key: str | None = None,
                  upto_tick: int | None = None, limit: int = 200) -> list[dict]:
        sql = "SELECT * FROM decisions WHERE run_id=?"
        args: list = [run_id]
        if tick is not None:
            sql += " AND tick=?"
            args.append(tick)
        if key is not None:
            sql += " AND key=?"
            args.append(key)
        if upto_tick is not None:
            sql += " AND tick<=?"
            args.append(upto_tick)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        rows = self.q(sql, args)
        for r in rows:
            r["request"] = json.loads(r["request"])
            r["response"] = json.loads(r["response"])
        return list(reversed(rows))

    def residents(self, run_id: int) -> list[dict]:
        """Everyone who has decided something in a run, in order of first appearance."""
        rows = self.q("SELECT key, agent, json_extract(request, '$.name') AS given, MIN(id) AS first FROM decisions"
                      " WHERE run_id=? GROUP BY key ORDER BY first", (run_id,))
        for r in rows:
            g = r["given"]
            r["given"] = json.loads(g) if isinstance(g, str) and g.startswith("{") else g
        return rows

    def latest_decisions(self, run_id: int, upto_tick: int) -> list[dict]:
        """The most recent decision per key as of a tick (the policies in force)."""
        rows = self.q(
            "SELECT d.* FROM decisions d JOIN (SELECT key, MAX(id) AS mid FROM decisions"
            " WHERE run_id=? AND tick<=? GROUP BY key) m ON d.id=m.mid ORDER BY d.key", (run_id, upto_tick))
        for r in rows:
            r["request"] = json.loads(r["request"])
            r["response"] = json.loads(r["response"])
        return rows

    # -- temporal facts -----------------------------------------------------
    def assert_fact(self, run_id: int, subject: str, predicate: str, obj: Any, tick: int, origin: str = "engine") -> None:
        """State that (subject, predicate) is `obj` from `tick` on. Closes the previous value."""
        new = _j(obj)
        cur = self.one("SELECT id, object FROM facts WHERE run_id=? AND subject=? AND predicate=? AND valid_to IS NULL",
                       (run_id, subject, predicate))
        if cur and cur["object"] == new:
            return
        if cur:
            self.x("UPDATE facts SET valid_to=? WHERE id=?", (tick, cur["id"]))
        self.x("INSERT INTO facts(run_id, subject, predicate, object, valid_from, valid_to, origin) VALUES(?,?,?,?,?,NULL,?)",
               (run_id, subject, predicate, new, tick, origin))

    def facts_as_of(self, run_id: int, tick: int, subject: str | None = None) -> list[dict]:
        sql = ("SELECT * FROM facts WHERE run_id=? AND valid_from<=? AND (valid_to IS NULL OR valid_to>?)")
        args: list = [run_id, tick, tick]
        if subject:
            sql += " AND subject=?"
            args.append(subject)
        rows = self.q(sql + " ORDER BY subject, predicate", args)
        for r in rows:
            r["object"] = json.loads(r["object"])
        return rows

    def fact_history(self, run_id: int, subject: str, predicate: str) -> list[dict]:
        rows = self.q("SELECT * FROM facts WHERE run_id=? AND subject=? AND predicate=? ORDER BY valid_from",
                      (run_id, subject, predicate))
        for r in rows:
            r["object"] = json.loads(r["object"])
        return rows

    # -- usage --------------------------------------------------------------
    def add_llm_call(self, run_id: int | None, world_id: int | None, role: str, model: str,
                     tokens_in: int, tokens_out: int, cost: float | None, ms: int, estimated: bool) -> None:
        self.x("INSERT INTO llm_calls(run_id, world_id, role, model, tokens_in, tokens_out, cost, ms, estimated, created_at)"
               " VALUES(?,?,?,?,?,?,?,?,?,?)",
               (run_id, world_id, role, model, tokens_in, tokens_out, cost, ms, int(estimated), time.time()))

    def usage(self, run_id: int) -> dict:
        rows = self.q("SELECT role, model, COUNT(*) AS calls, SUM(tokens_in) AS tokens_in, SUM(tokens_out) AS tokens_out,"
                      " SUM(cost) AS cost, SUM(cost IS NULL) AS unpriced FROM llm_calls WHERE run_id=? GROUP BY role, model",
                      (run_id,))
        total = sum((r["cost"] or 0) for r in rows)
        return {"by_role": rows, "cost": total, "calls": sum(r["calls"] for r in rows),
                "tokens_in": sum(r["tokens_in"] or 0 for r in rows),
                "tokens_out": sum(r["tokens_out"] or 0 for r in rows),
                "unpriced": any(r["unpriced"] for r in rows)}

    def get_setting(self, key: str) -> Any:
        row = self.one("SELECT value FROM settings WHERE key=?", (key,))
        return json.loads(row["value"]) if row else None

    def set_setting(self, key: str, value: Any) -> None:
        if value is None:
            self.x("DELETE FROM settings WHERE key=?", (key,))
        else:
            self.x("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, _j(value)))

    def reprice(self, price_of) -> int:
        """Fill in the cost of calls recorded while their model had no price entry."""
        rows = self.q("SELECT id, model, tokens_in, tokens_out FROM llm_calls WHERE cost IS NULL")
        n = 0
        for r in rows:
            c = price_of(r["model"], r["tokens_in"] or 0, r["tokens_out"] or 0)
            if c is not None:
                self.x("UPDATE llm_calls SET cost=? WHERE id=?", (c, r["id"]))
                n += 1
        return n

    def observed_tokens(self, role: str, model: str) -> dict | None:
        """Average tokens per call seen so far for a model (used to sharpen cost estimates)."""
        row = self.one("SELECT COUNT(*) AS n, AVG(tokens_in) AS tin, AVG(tokens_out) AS tout FROM llm_calls"
                       " WHERE role=? AND model=? AND estimated=0", (role, model))
        if not row or not row["n"]:
            return None
        return {"calls": row["n"], "tokens_in": row["tin"], "tokens_out": row["tout"]}

    def world_usage(self, world_id: int) -> dict:
        rows = self.q("SELECT role, model, COUNT(*) AS calls, SUM(tokens_in) AS tokens_in, SUM(tokens_out) AS tokens_out,"
                      " SUM(cost) AS cost FROM llm_calls WHERE world_id=? AND run_id IS NULL GROUP BY role, model", (world_id,))
        return {"by_role": rows, "cost": sum((r["cost"] or 0) for r in rows)}

    # -- chat and reports ---------------------------------------------------
    def add_chat(self, run_id: int, tick: int, agent: str, key: str, role: str, text: str) -> None:
        self.x("INSERT INTO chats(run_id, tick, agent, key, role, text, created_at) VALUES(?,?,?,?,?,?,?)",
               (run_id, tick, agent, key, role, text, time.time()))

    def chats(self, run_id: int, key: str) -> list[dict]:
        return self.q("SELECT tick, role, text FROM chats WHERE run_id=? AND key=? ORDER BY id", (run_id, key))

    def save_report(self, run_id: int, tick: int, body: dict, source: str) -> None:
        self.x("INSERT INTO reports(run_id, tick, body, source, created_at) VALUES(?,?,?,?,?)",
               (run_id, tick, _j(body), source, time.time()))

    def latest_report(self, run_id: int) -> dict | None:
        row = self.one("SELECT * FROM reports WHERE run_id=? ORDER BY id DESC LIMIT 1", (run_id,))
        if row:
            row["body"] = json.loads(row["body"])
        return row

    # -- forking ------------------------------------------------------------
    def copy_history(self, src: int, dst: int, upto_tick: int) -> None:
        """A fork starts with its parent's history up to the fork tick."""
        with self.lock:
            c = self.conn
            c.execute("BEGIN")
            try:
                c.execute("INSERT INTO ticks SELECT ?, tick, metrics, view FROM ticks WHERE run_id=? AND tick<=?",
                          (dst, src, upto_tick))
                c.execute("INSERT INTO snapshots SELECT ?, tick, state, rng, params FROM snapshots WHERE run_id=? AND tick<=?",
                          (dst, src, upto_tick))
                c.execute("INSERT INTO events(run_id, tick, kind, agent, node, payload)"
                          " SELECT ?, tick, kind, agent, node, payload FROM events WHERE run_id=? AND tick<=? ORDER BY id",
                          (dst, src, upto_tick))
                c.execute("INSERT INTO decisions(run_id, tick, key, agent, request, response, source, model, tokens_in, tokens_out, cost)"
                          " SELECT ?, tick, key, agent, request, response, 'inherited', model, 0, 0, 0 FROM decisions"
                          " WHERE run_id=? AND tick<=? ORDER BY id", (dst, src, upto_tick))
                c.execute("INSERT INTO facts(run_id, subject, predicate, object, valid_from, valid_to, origin)"
                          " SELECT ?, subject, predicate, object, valid_from,"
                          " CASE WHEN valid_to IS NOT NULL AND valid_to<=? THEN valid_to ELSE NULL END, origin"
                          " FROM facts WHERE run_id=? AND valid_from<=?", (dst, upto_tick, src, upto_tick))
                c.execute("COMMIT")
            except Exception:
                c.execute("ROLLBACK")
                raise

    def delete_run(self, run_id: int) -> None:
        for t in ("ticks", "snapshots", "events", "decisions", "facts", "llm_calls", "chats", "reports"):
            self.x(f"DELETE FROM {t} WHERE run_id=?", (run_id,))
        self.x("DELETE FROM runs WHERE id=?", (run_id,))


class _Tx:
    def __init__(self, db: "SqliteStore"):
        self.db = db

    def __enter__(self):
        self.db.lock.acquire()
        try:
            self.db.conn.execute("BEGIN")
        except Exception:
            self.db.lock.release()
            raise
        return self.db

    def __exit__(self, et, ev, tb):
        try:
            self.db.conn.execute("ROLLBACK" if et else "COMMIT")
        except sqlite3.Error:
            if self.db.conn.in_transaction:
                self.db.conn.rollback()
            raise
        finally:
            self.db.lock.release()

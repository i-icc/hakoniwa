"""Composition root: the only place that knows which adapter fills which port."""
from __future__ import annotations

from dataclasses import dataclass

from .application.designer import WorldDesigner
from .application.engine import RunManager
from .application.ports import KeepsCopies, LanguageModel, SandboxFactory, Store
from .application.reporter import Observer
from .application.worlds import seed_worlds
from .domain.pricing import cost_usd
from .infrastructure.builtin_worlds import load_builtin_worlds
from .infrastructure.config import Settings, load_settings
from .infrastructure.openai_llm import make_llm
from .infrastructure.sandboxes import Sandboxes
from .infrastructure.sqlite_store import SqliteStore


EFFORTS = ("low", "medium", "high", "xhigh", "max")


@dataclass
class App:
    settings: Settings
    store: Store
    sandboxes: SandboxFactory
    llm: LanguageModel
    runs: RunManager
    designer: WorldDesigner
    observer: Observer
    env_models: dict

    async def close(self) -> None:
        await self.keep_copy()                    # first of all, one last copy: Cloud Run gives ten seconds, and stopping runs can take some of them
        await self.runs.shutdown()
        await self.llm.close()

    # -- a copy that outlives the machine (HAKONIWA_BACKUP_DIR) -----------------
    async def keep_copy(self, force: bool = False) -> dict | None:
        """Copy the whole database to the backup folder if anything changed since the last copy."""
        folder = self.settings.backup_dir
        if not folder or not isinstance(self.store, KeepsCopies):
            return None
        seen = self.store.changes()
        if not force and seen == getattr(self, "_copied_at_change", None):
            return None
        import asyncio, time
        try:
            size = await asyncio.to_thread(self.store.backup_to, folder)
            self._copied_at_change = seen
            self.last_copy = {"at": time.time(), "bytes": size, "error": None}
        except Exception as e:                    # a full or unreachable folder must not stop the app
            self.last_copy = {"at": time.time(), "bytes": None, "error": f"{type(e).__name__}: {e}"[:300]}
        return self.last_copy

    def note_milestone(self) -> None:
        """Something was just completed (a run stopped, a world was built, a file came in): a good moment for a copy.
        Several in a row make one copy."""
        if not self.settings.backup_dir or getattr(self, "_copy_soon", None):
            return
        import asyncio
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        async def soon() -> None:
            try:
                await asyncio.sleep(2)
                await self.keep_copy()
            finally:
                self._copy_soon = None
        self._copy_soon = loop.create_task(soon())

    async def copy_regularly(self) -> None:
        import asyncio
        while True:
            await asyncio.sleep(max(0.2, self.settings.backup_minutes * 60))
            await self.keep_copy()

    # -- model choices --------------------------------------------------------
    def model_choices(self) -> dict:
        return {role: {"model": rc.model, "effort": rc.effort, "default_model": self.env_models[role][0],
                       "default_effort": self.env_models[role][1]} for role, rc in self.settings.roles.items()}

    def set_models(self, choices: dict | None) -> dict:
        """Apply model choices from the viewer (None = back to .env) and remember them."""
        clean: dict = {}
        for role, rc in self.settings.roles.items():
            rc.model, rc.effort = self.env_models[role]
            c = (choices or {}).get(role) or {}
            model = str(c.get("model") or "").strip()
            effort = c.get("effort")
            if model:
                rc.model = model[:120]
            if effort in EFFORTS:
                rc.effort = effort
            if choices is not None:
                clean[role] = {"model": rc.model, "effort": rc.effort}
        self.store.set_setting("models", clean or None)
        return self.model_choices()


def build_app(settings: Settings | None = None, store: Store | None = None,
              llm: LanguageModel | None = None, sandboxes: SandboxFactory | None = None) -> App:
    s = settings or load_settings()
    if store is None and s.backup_dir:           # a machine that lost its files starts from the last copy
        SqliteStore.restore_if_missing(s.db_path, s.backup_dir)
    store = store or SqliteStore(s.db_path)
    llm = llm or make_llm(s)
    sandboxes = sandboxes or Sandboxes(s)
    seed_worlds(store, load_builtin_worlds())
    store.reprice(lambda model, tin, tout: cost_usd(s.prices, model, tin, tout))
    runs = RunManager(store, sandboxes, llm, prices=s.prices, langs=s.content_langs)
    designer = WorldDesigner(store, sandboxes, llm, s.prices)
    observer = Observer(store, llm, s.prices, s.content_langs)
    app = App(settings=s, store=store, sandboxes=sandboxes, llm=llm, runs=runs, designer=designer, observer=observer,
              env_models={role: (rc.model, rc.effort) for role, rc in s.roles.items()})
    runs.on_milestone = designer.on_milestone = app.note_milestone
    saved = store.get_setting("models")
    if saved:
        app.set_models(saved)
    return app

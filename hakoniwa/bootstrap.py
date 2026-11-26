"""Composition root: the only place that knows which adapter fills which port."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from .application.designer import WorldDesigner
from .application.engine import RunManager
from .application.ports import LanguageModel, SandboxFactory, Store
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
        await self.runs.shutdown()
        await self.llm.close()

    async def restore_data(self, path: Path) -> None:
        await asyncio.to_thread(self.store.restore_from, path, load_builtin_worlds())
        self.designer.jobs.clear()
        self.set_models(self.store.get_setting("models"), remember=False)
        await self.runs.discard_workers()

    # -- model choices --------------------------------------------------------
    def model_choices(self) -> dict:
        return {role: {"model": rc.model, "effort": rc.effort, "default_model": self.env_models[role][0],
                       "default_effort": self.env_models[role][1]} for role, rc in self.settings.roles.items()}

    def set_models(self, choices: dict | None, *, remember: bool = True) -> dict:
        """Apply model choices from the viewer (None = back to .env) and remember them."""
        clean: dict = {}
        for role, rc in self.settings.roles.items():
            rc.model, rc.effort = self.env_models[role]
            c = choices.get(role) if isinstance(choices, dict) else None
            if not isinstance(c, dict):
                c = {}
            model = str(c.get("model") or "").strip()
            effort = c.get("effort")
            if model:
                rc.model = model[:120]
            if effort in EFFORTS:
                rc.effort = effort
            if choices is not None:
                clean[role] = {"model": rc.model, "effort": rc.effort}
        if remember:
            self.store.set_setting("models", clean or None)
        return self.model_choices()


def build_app(settings: Settings | None = None, store: Store | None = None,
              llm: LanguageModel | None = None, sandboxes: SandboxFactory | None = None) -> App:
    s = settings or load_settings()
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
    saved = store.get_setting("models")
    if saved:
        app.set_models(saved)
    return app

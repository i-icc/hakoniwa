"""Settings. Everything comes from environment variables (see .env.example)."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent      # the hakoniwa package
ROOT = PKG.parent                                  # the project folder


def _env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name)
    return v if v not in (None, "") else default


def load_dotenv(path: Path | None = None) -> None:
    """Tiny .env loader (KEY=VALUE lines). Real environment variables win."""
    p = path or ROOT / ".env"
    if not p.exists():
        return
    for raw in p.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)


@dataclass
class RoleConfig:
    """One LLM role (designer / agent / report). All use the OpenAI chat API shape."""
    role: str
    model: str
    base_url: str
    api_key: str | None
    effort: str | None = None     # reasoning effort (low / medium / high ...), if the model takes one


@dataclass
class Settings:
    db_path: Path
    host: str
    port: int
    llm_mode: str            # "live" or "mock"
    roles: dict[str, RoleConfig]
    concurrency: int
    json_mode: bool
    temperature: float | None
    request_timeout: float
    sandbox: str             # "docker" | "process" | "remote" | "auto"
    sandbox_image: str
    sandbox_url: str | None
    allow_unsafe_sandbox: bool
    research: str            # "none" | "responses"
    research_model: str | None = None
    prices: dict = field(default_factory=dict)
    content_langs: tuple[str, ...] = ("en", "ja")

    def role(self, name: str) -> RoleConfig:
        return self.roles[name]

    def public(self) -> dict:
        """Safe to show in the viewer: never includes keys."""
        return {
            "llm_mode": self.llm_mode,
            "models": {k: v.model for k, v in self.roles.items()},
            "efforts": {k: v.effort for k, v in self.roles.items()},
            "base_urls": {k: v.base_url for k, v in self.roles.items()},
            "sandbox": self.sandbox,
            "research": self.research,
            "content_langs": list(self.content_langs),
        }


def load_prices() -> dict:
    p = Path(_env("HAKONIWA_PRICES_FILE", str(ROOT / "prices.json")))
    if p.exists():
        return json.loads(p.read_text())
    return {"models": {}}


def load_settings() -> Settings:
    load_dotenv()
    base = (_env("OPENAI_BASE_URL", "https://api.openai.com/v1") or "").rstrip("/")
    key = _env("OPENAI_API_KEY")
    default_model = _env("HAKONIWA_MODEL")
    default_models = {"designer": "gpt-6.2-sol", "agent": "gpt-6-luna", "report": "gpt-6.2-sol"}
    default_effort = {"designer": "medium", "agent": "low", "report": "low"}
    roles: dict[str, RoleConfig] = {}
    for role in ("designer", "agent", "report"):
        up = role.upper()
        roles[role] = RoleConfig(
            role=role,
            model=_env(f"HAKONIWA_MODEL_{up}", default_model or default_models[role]) or "",
            effort=_env(f"HAKONIWA_EFFORT_{up}", default_effort[role]),
            base_url=(_env(f"HAKONIWA_{up}_BASE_URL", base) or "").rstrip("/"),
            api_key=_env(f"HAKONIWA_{up}_API_KEY", key),
        )
    mode = _env("HAKONIWA_LLM", "auto")
    if mode == "auto":
        mode = "live" if roles["agent"].api_key else "mock"
    temp = _env("HAKONIWA_TEMPERATURE")
    return Settings(
        db_path=Path(_env("HAKONIWA_DB", str(ROOT / "data" / "hakoniwa.db"))),
        host=_env("HAKONIWA_HOST", "127.0.0.1") or "127.0.0.1",
        port=int(_env("HAKONIWA_PORT", "8787") or 8787),
        llm_mode=mode or "mock",
        roles=roles,
        concurrency=int(_env("HAKONIWA_CONCURRENCY", "8") or 8),
        json_mode=(_env("HAKONIWA_JSON_MODE", "0") == "1"),
        temperature=float(temp) if temp else None,
        request_timeout=float(_env("HAKONIWA_TIMEOUT", "900") or 900),
        sandbox=_env("HAKONIWA_SANDBOX", "auto") or "auto",
        sandbox_image=_env("HAKONIWA_SANDBOX_IMAGE", "hakoniwa-sandbox:latest") or "",
        sandbox_url=_env("HAKONIWA_SANDBOX_URL"),
        allow_unsafe_sandbox=(_env("HAKONIWA_ALLOW_UNSAFE_SANDBOX", "0") == "1"),
        research=_env("HAKONIWA_RESEARCH", "none") or "none",
        research_model=_env("HAKONIWA_MODEL_RESEARCH"),
        prices=load_prices(),
        content_langs=tuple((_env("HAKONIWA_LANGS", "en,ja") or "en,ja").split(",")),
    )

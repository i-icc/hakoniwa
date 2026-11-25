"""LanguageModel adapters.

OpenAICompatLLM speaks the OpenAI Chat Completions API shape, so any provider
with that interface works (set OPENAI_BASE_URL / OPENAI_API_KEY).
MockLLM is used when no key is configured: residents then follow each world
model's own default behaviour and nothing is sent anywhere.
"""
from __future__ import annotations

import asyncio
import time

import httpx

from ..application.ports import LLMError, LLMResult
from ..domain.pricing import approx_tokens
from .config import RoleConfig, Settings


class MockLLM:
    live = False

    def __init__(self, settings: Settings):
        self.s = settings

    def model_for(self, role: str) -> str:
        return "mock"

    async def chat(self, role, messages, *, max_tokens=1200, want_json=False, model=None) -> LLMResult:
        raise LLMError("No AI provider is configured (set OPENAI_API_KEY and OPENAI_BASE_URL).")

    async def research(self, prompt: str) -> LLMResult | None:
        return None

    async def list_models(self) -> list[str]:
        return []

    async def close(self) -> None:
        return None


class OpenAICompatLLM:
    live = True

    def __init__(self, settings: Settings):
        self.s = settings
        self._client: httpx.AsyncClient | None = None
        self._sem = asyncio.Semaphore(max(1, settings.concurrency))
        # which output-limit parameter each (base_url, model) accepts
        self._limit_param: dict[tuple[str, str], str] = {}
        self._no_effort: set[tuple[str, str]] = set()
        self._models: tuple[float, list[str]] | None = None

    def model_for(self, role: str) -> str:
        return self.s.role(role).model

    async def list_models(self) -> list[str]:
        """Model ids the provider offers (cached for ten minutes). Empty when the provider has no list."""
        now = time.time()
        if self._models and now - self._models[0] < 600:
            return self._models[1]
        rc = self.s.role("agent")
        try:
            r = await self._http().get(rc.base_url + "/models", headers={"Authorization": f"Bearer {rc.api_key}"}, timeout=20)
            ids = sorted(m["id"] for m in r.json().get("data", [])) if r.status_code == 200 else []
        except (httpx.HTTPError, ValueError, KeyError):
            ids = []
        self._models = (now, ids)
        return ids

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.s.request_timeout)
        return self._client

    async def chat(self, role: str, messages: list[dict], *, max_tokens: int = 1200,
                   want_json: bool = False, model: str | None = None) -> LLMResult:
        rc: RoleConfig = self.s.role(role)
        model = model or rc.model
        if not rc.api_key:
            raise LLMError(f"no API key for role '{role}' (set OPENAI_API_KEY)")
        key = (rc.base_url, model)
        body: dict = {"model": model, "messages": messages}
        if self.s.temperature is not None:
            body["temperature"] = self.s.temperature
        if want_json and self.s.json_mode:
            body["response_format"] = {"type": "json_object"}
        if rc.effort and rc.effort != "off" and key not in self._no_effort:
            body["reasoning_effort"] = rc.effort
        headers = {"Authorization": f"Bearer {rc.api_key}", "Content-Type": "application/json"}
        t0 = time.time()
        last = ""
        async with self._sem:
            for attempt in range(5):
                param = self._limit_param.get(key, "max_completion_tokens")
                body.pop("max_tokens", None)
                body.pop("max_completion_tokens", None)
                body[param] = max_tokens
                try:
                    r = await self._http().post(rc.base_url + "/chat/completions", json=body, headers=headers)
                except httpx.HTTPError as e:
                    last = f"{type(e).__name__}: {e}"
                    await asyncio.sleep(min(8, 1.5 ** attempt))
                    continue
                if r.status_code == 200:
                    data = r.json()
                    choice = (data.get("choices") or [{}])[0]
                    text = (choice.get("message") or {}).get("content") or ""
                    if isinstance(text, list):   # some providers return content parts
                        text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
                    usage = data.get("usage") or {}
                    tin, tout = usage.get("prompt_tokens"), usage.get("completion_tokens")
                    est = tin is None or tout is None
                    if est:
                        tin = sum(approx_tokens(str(m.get("content", ""))) for m in messages)
                        tout = approx_tokens(text)
                    return LLMResult(text=text, model=model, tokens_in=int(tin), tokens_out=int(tout),
                                     ms=int((time.time() - t0) * 1000), estimated=est)
                last = f"HTTP {r.status_code}: {r.text[:300]}"
                low = r.text.lower()
                if r.status_code == 400 and ("max_completion_tokens" in low or "max_tokens" in low) and attempt < 2:
                    # this provider wants the other spelling of the output limit
                    self._limit_param[key] = "max_tokens" if param == "max_completion_tokens" else "max_completion_tokens"
                    continue
                if r.status_code == 400 and "reasoning_effort" in low and "reasoning_effort" in body:
                    body.pop("reasoning_effort")      # this model or provider has no effort setting
                    self._no_effort.add(key)
                    continue
                if r.status_code == 400 and "response_format" in low and "response_format" in body:
                    body.pop("response_format")
                    continue
                if r.status_code in (408, 409, 429) or r.status_code >= 500:
                    retry = r.headers.get("retry-after")
                    delay = float(retry) if retry and retry.replace(".", "", 1).isdigit() else min(20, 2 ** attempt)
                    await asyncio.sleep(delay)
                    continue
                break
        raise LLMError(last or "LLM request failed")

    async def research(self, prompt: str) -> LLMResult | None:
        """Optional web research for the world designer (HAKONIWA_RESEARCH=responses).
        Uses the OpenAI Responses API with the built-in web_search tool; providers
        without it simply fail and the designer continues with assumptions."""
        if self.s.research != "responses":
            return None
        rc = self.s.role("designer")
        model = self.s.research_model or rc.model
        t0 = time.time()
        try:
            r = await self._http().post(
                rc.base_url + "/responses",
                json={"model": model, "input": prompt, "tools": [{"type": "web_search"}],
                      **({"reasoning": {"effort": rc.effort}} if rc.effort and rc.effort != "off" else {})},
                headers={"Authorization": f"Bearer {rc.api_key}", "Content-Type": "application/json"})
        except httpx.HTTPError as e:
            raise LLMError(f"research request failed: {e}")
        if r.status_code != 200:
            raise LLMError(f"research request failed: HTTP {r.status_code}: {r.text[:200]}")
        data = r.json()
        text = data.get("output_text") or ""
        if not text:
            for item in data.get("output") or []:
                for part in item.get("content") or []:
                    if isinstance(part, dict) and part.get("text"):
                        text += part["text"]
        usage = data.get("usage") or {}
        return LLMResult(text=text, model=model, tokens_in=int(usage.get("input_tokens") or approx_tokens(prompt)),
                         tokens_out=int(usage.get("output_tokens") or approx_tokens(text)),
                         ms=int((time.time() - t0) * 1000), estimated=not usage)


def make_llm(settings: Settings):
    return OpenAICompatLLM(settings) if settings.llm_mode == "live" else MockLLM(settings)

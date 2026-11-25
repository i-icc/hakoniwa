"""Sandbox adapters for world models (SandboxFactory / ModelSandbox ports). One sandbox = one world instance.

Backends (HAKONIWA_SANDBOX):
  docker  - a fresh container per world: no network, read-only, non-root, capped.
  remote  - a sidecar sandbox service (docker compose); a fresh process per world.
  process - a local subprocess. NOT isolated. For built-in worlds and tests.
  auto    - docker if the docker CLI works, else process.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import sys
from pathlib import Path
from urllib.parse import urlparse

from ..application.ports import SandboxError
from .config import ROOT, Settings

RUNNER = ROOT / "sandbox" / "runner.py"
LIMIT = 64 * 1024 * 1024


class Sandbox:
    """Line-protocol client. Subclasses only differ in how the pipe is opened."""
    backend = "?"

    def __init__(self, op_timeout: float = 20.0):
        self.op_timeout = op_timeout
        self._lock = asyncio.Lock()
        self._reader: asyncio.StreamReader | None = None
        self._writer = None
        self._proc: asyncio.subprocess.Process | None = None

    async def open(self) -> None:
        raise NotImplementedError

    async def call(self, op: str, **kw) -> dict:
        async with self._lock:
            if self._writer is None or self._reader is None:
                raise SandboxError("sandbox is not open")
            msg = json.dumps({"op": op, **kw}, ensure_ascii=False) + "\n"
            try:
                self._writer.write(msg.encode())
                await self._writer.drain()
                line = await asyncio.wait_for(self._reader.readline(), timeout=self.op_timeout)
            except asyncio.TimeoutError:
                await self.close()
                raise SandboxError(f"model did not answer '{op}' within {self.op_timeout:.0f}s (infinite loop or too slow)")
            except (BrokenPipeError, ConnectionError) as e:
                raise SandboxError(f"sandbox connection lost: {e}")
            if not line:
                err = await self._stderr_tail()
                raise SandboxError("sandbox exited unexpectedly" + (f": {err}" if err else ""))
            res = json.loads(line)
            if not res.get("ok"):
                raise SandboxError(res.get("error", "model error"), res.get("trace", ""))
            return res

    async def _stderr_tail(self) -> str:
        if self._proc and self._proc.stderr:
            try:
                data = await asyncio.wait_for(self._proc.stderr.read(4000), timeout=1)
                return data.decode(errors="replace")[-600:]
            except Exception:
                return ""
        return ""

    async def close(self) -> None:
        w, p = self._writer, self._proc
        self._writer = self._reader = self._proc = None
        try:
            if w is not None:
                w.close()
        except Exception:
            pass
        if p is not None and p.returncode is None:
            try:
                p.kill()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(p.wait(), timeout=5)
            except Exception:
                pass

    # convenience wrappers -------------------------------------------------
    async def load(self, code: str, params: dict, seed: int) -> dict:
        return await self.call("load", code=code, params=params, seed=seed)

    async def init(self) -> dict:
        return await self.call("init")

    async def tick(self) -> dict:
        return await self.call("tick")

    async def apply(self, actions: list[dict]) -> dict:
        return await self.call("apply", actions=actions)

    async def set_params(self, patch: dict) -> dict:
        return await self.call("set_params", patch=patch)

    async def restore(self, state: dict, rng: list, t: int, params: dict | None) -> dict:
        return await self.call("restore", state=state, rng=rng, t=t, params=params)


class _SubprocessSandbox(Sandbox):
    def _argv(self) -> list[str]:
        raise NotImplementedError

    async def open(self) -> None:
        self._proc = await asyncio.create_subprocess_exec(
            *self._argv(), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, limit=LIMIT, env=self._env())
        self._reader, self._writer = self._proc.stdout, self._proc.stdin

    def _env(self) -> dict | None:
        return None


class ProcessSandbox(_SubprocessSandbox):
    """Local subprocess. No isolation beyond the runner's restricted builtins."""
    backend = "process"

    def _argv(self) -> list[str]:
        return [sys.executable, "-I", "-u", str(RUNNER)]

    def _env(self) -> dict:
        return {"PATH": "/usr/bin:/bin"}   # do not pass API keys to model code


class DockerSandbox(_SubprocessSandbox):
    """One locked-down container per world."""
    backend = "docker"

    def __init__(self, image: str, op_timeout: float = 20.0):
        super().__init__(op_timeout)
        self.image = image

    def _argv(self) -> list[str]:
        return ["docker", "run", "-i", "--rm", "--network", "none", "--read-only",
                "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                "--memory", "256m", "--cpus", "1", "--pids-limit", "32",
                "--user", "65534:65534", "--tmpfs", "/tmp:size=16m",
                self.image]


class RemoteSandbox(Sandbox):
    """TCP connection to the sidecar sandbox service; one process per connection."""
    backend = "remote"

    def __init__(self, url: str, op_timeout: float = 20.0):
        super().__init__(op_timeout)
        u = urlparse(url)
        self.host, self.port = u.hostname or "sandbox", u.port or 7070

    async def open(self) -> None:
        self._reader, self._writer = await asyncio.open_connection(self.host, self.port, limit=LIMIT)

    async def close(self) -> None:
        w = self._writer
        self._writer = self._reader = None
        if w is not None:
            try:
                w.close()
                await w.wait_closed()
            except Exception:
                pass


_docker_ok: bool | None = None
_image_ready: set[str] = set()


async def docker_available() -> bool:
    global _docker_ok
    if _docker_ok is None:
        if not shutil.which("docker"):
            _docker_ok = False
        else:
            try:
                p = await asyncio.create_subprocess_exec(
                    "docker", "version", "--format", "{{.Server.Version}}",
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
                _docker_ok = (await asyncio.wait_for(p.wait(), timeout=8)) == 0
            except Exception:
                _docker_ok = False
    return _docker_ok


async def ensure_image(image: str) -> None:
    """Build the sandbox image on first use (small: python-alpine + two files)."""
    if image in _image_ready:
        return
    p = await asyncio.create_subprocess_exec("docker", "image", "inspect", image,
                                             stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    if await p.wait() != 0:
        b = await asyncio.create_subprocess_exec(
            "docker", "build", "-q", "-t", image, str(ROOT / "sandbox"),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        _, err = await b.communicate()
        if b.returncode != 0:
            raise SandboxError("could not build the sandbox image: " + err.decode(errors="replace")[-400:])
    _image_ready.add(image)


class Sandboxes:
    """SandboxFactory port: opens a fresh, isolated sandbox per world."""

    def __init__(self, settings: Settings):
        self.s = settings

    async def backend(self) -> str:
        b = self.s.sandbox
        if b == "auto":
            if self.s.sandbox_url:
                return "remote"
            return "docker" if await docker_available() else "process"
        return b

    async def open(self, trusted: bool, op_timeout: float = 20.0) -> Sandbox:
        """Untrusted (AI-written) code never runs in the unisolated 'process'
        backend unless HAKONIWA_ALLOW_UNSAFE_SANDBOX=1."""
        backend = await self.backend()
        if backend == "process" and not trusted and not self.s.allow_unsafe_sandbox:
            raise SandboxError(
                "AI-written world models need an isolated sandbox. Start Docker (HAKONIWA_SANDBOX=docker), "
                "use docker compose, or set HAKONIWA_ALLOW_UNSAFE_SANDBOX=1 to run them unisolated.")
        if backend == "docker":
            await ensure_image(self.s.sandbox_image)
            sb: Sandbox = DockerSandbox(self.s.sandbox_image, op_timeout)
        elif backend == "remote":
            sb = RemoteSandbox(self.s.sandbox_url or "tcp://sandbox:7070", op_timeout)
        elif backend == "process":
            sb = ProcessSandbox(op_timeout)
        else:
            raise SandboxError(f"unknown sandbox backend '{backend}'")
        await sb.open()
        return sb

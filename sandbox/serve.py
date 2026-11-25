"""Sidecar sandbox server (used by docker compose).

Each TCP connection gets its own fresh runner process: one world, one process.
This container has no outbound network and no secrets, so model code that
escapes the Python-level restrictions still has nothing to reach.
"""
import asyncio
import os
import sys

HOST = os.environ.get("SANDBOX_HOST", "0.0.0.0")
PORT = int(os.environ.get("SANDBOX_PORT", "7070"))
RUNNER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "runner.py")
MAX_WORLDS = int(os.environ.get("SANDBOX_MAX_WORLDS", "16"))
_sem = asyncio.Semaphore(MAX_WORLDS)


async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    async with _sem:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-I", "-u", RUNNER,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            limit=64 * 1024 * 1024, env={"PATH": "/usr/local/bin:/usr/bin:/bin"},
        )

        async def pump_in():
            try:
                while True:
                    line = await reader.readline()
                    if not line:
                        break
                    proc.stdin.write(line)
                    await proc.stdin.drain()
            except Exception:
                pass
            finally:
                try:
                    proc.stdin.close()
                except Exception:
                    pass

        async def pump_out():
            try:
                while True:
                    line = await proc.stdout.readline()
                    if not line:
                        break
                    writer.write(line)
                    await writer.drain()
            except Exception:
                pass

        t_in = asyncio.create_task(pump_in())
        t_out = asyncio.create_task(pump_out())
        await asyncio.wait([t_in, t_out], return_when=asyncio.FIRST_COMPLETED)
        for t in (t_in, t_out):
            t.cancel()
        if proc.returncode is None:
            proc.kill()
        await proc.wait()
        try:
            writer.close()
        except Exception:
            pass


async def main():
    server = await asyncio.start_server(handle, HOST, PORT, limit=64 * 1024 * 1024)
    print(f"hakoniwa sandbox listening on {HOST}:{PORT}", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())

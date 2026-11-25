import os

import pytest

os.environ["HAKONIWA_LLM"] = "mock"
os.environ["HAKONIWA_SANDBOX"] = "process"
os.environ["HAKONIWA_DB"] = ":memory:"


@pytest.fixture
async def app():
    from hakoniwa.bootstrap import build_app
    a = build_app()
    yield a
    await a.close()

from __future__ import annotations

import pytest

from kaggle_mcp import kaggle_client as kc


@pytest.fixture(autouse=True)
def isolate_workdir(tmp_path, monkeypatch):
    """Confine downloads/extraction to a temp dir for every test."""
    monkeypatch.setenv("KAGGLE_MCP_WORKDIR", str(tmp_path / "work"))
    yield


@pytest.fixture
def fake_api():
    """Inject a fake KaggleApi singleton; cleared after the test."""
    class FakeApi:
        def __init__(self):
            self.calls = []

    api = FakeApi()
    kc.reset_api_for_tests(api)
    yield api
    kc.reset_api_for_tests(None)

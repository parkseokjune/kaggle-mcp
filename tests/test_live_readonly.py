"""LIVE read-only smoke tests against the real Kaggle API.

Skipped by default. To run real verification with your own credentials:

    KAGGLE_LIVE=1 KAGGLE_USERNAME=you KAGGLE_KEY=... uv run pytest tests/test_live_readonly.py -v

These NEVER submit, create, or delete anything — they exercise only public
read-only endpoints (whoami, search, list, public dataset download).
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("KAGGLE_LIVE") != "1",
    reason="set KAGGLE_LIVE=1 (and real KAGGLE_USERNAME/KAGGLE_KEY) to run live smoke",
)


def unwrap(result):
    return result[1] if isinstance(result, tuple) else result


async def _call(name, args=None):
    from kaggle_mcp import server
    return unwrap(await server.mcp.call_tool(name, args or {}))


async def test_live_whoami():
    r = await _call("kaggle_whoami")
    assert r.get("authenticated") is True
    # username is present with legacy creds; None when using an opaque API token.
    assert "credentialSource" in r


async def test_live_search_datasets():
    r = await _call("kaggle_search_datasets", {"search": "titanic", "page_size": 5})
    assert r["count"] >= 1
    assert r["results"][0]["ref"]  # populated, not None


async def test_live_list_competitions():
    r = await _call("kaggle_list_competitions", {"search": "titanic"})
    assert r["count"] >= 1


async def test_live_public_dataset_download():
    # 'uciml/iris' is a small, public, rules-free dataset.
    r = await _call("kaggle_download_dataset", {"dataset": "uciml/iris"})
    assert "isError" not in r
    assert r["files"], "expected at least one extracted file"


async def test_live_search_and_read_discussion():
    s = await _call("kaggle_search_discussions", {"search": "titanic", "page_size": 3})
    assert s["count"] >= 1
    tid = s["topics"][0]["id"]
    d = await _call("kaggle_get_discussion", {"topic_id": tid, "max_messages": 2})
    assert d["message_count"] >= 1
    assert "<untrusted-content>" in d["messages"][0]["content"]  # injection-safe fencing

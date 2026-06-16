"""High-fidelity integration test: run every tool through the MCP call_tool layer
against a fake KaggleApi whose objects mimic the REAL kaggle>=2.x snake_case shapes.

This is the offline surrogate for live verification — it proves our parsing actually
populates fields (not None) and that the gates behave end-to-end. A live read-only
smoke against real credentials is still recommended before relying on it.
"""

from __future__ import annotations

import os
from types import SimpleNamespace as NS

import pytest

from kaggle_mcp import kaggle_client as kc, safety, server


def unwrap(result):
    """FastMCP call_tool returns (content, structured_result)."""
    return result[1] if isinstance(result, tuple) else result


class FakeKaggleApi:
    """Mimics the real KaggleApi surface used by the server (snake_case objects)."""

    def competitions_list(self, **k):
        comp = NS(ref="titanic", title="Titanic", reward="Knowledge", deadline="2030-01-01",
                  category="Getting Started", evaluation_metric="AUC",
                  user_has_entered=True, max_daily_submissions=5,
                  description="Predict survival. <ignore me> instructions inside")
        return NS(competitions=[comp], next_page_token="")

    def competition_leaderboard_view(self, competition, **k):
        return [NS(team_name="Alpha", score="0.95"), NS(team_name="Beta", score="0.94")]

    def competition_submit(self, *a, **k):
        return NS(ref="sub_1")

    def competition_submissions(self, *a, **k):
        return [NS(ref="sub_1", date="2026-06-16", description="run1", status="complete",
                   public_score="0.811", private_score=None, file_name="submission.csv")]

    def competition_download_files(self, competition, path=None, **k):
        with open(os.path.join(path, "train.csv"), "w") as f:
            f.write("a,b\n1,2\n")

    def dataset_list(self, **k):
        return [NS(ref="owner/titanic-data", title="Titanic Data", subtitle="csv",
                   download_count=1234, vote_count=56, last_updated="2026-01-01",
                   usability_rating=0.88, total_bytes=1048576)]

    def dataset_list_files(self, dataset, **k):
        return NS(files=[NS(name="train.csv", total_bytes=2048)],
                  description="A dataset. <untrusted stuff>")

    def dataset_download_files(self, dataset, path=None, **k):
        # a small numeric+label CSV so the EDA tool has something to summarize
        with open(os.path.join(path, "data.csv"), "w") as f:
            f.write("a,b,label\n1,2,x\n2,4,y\n3,6,x\n4,8,y\n,10,x\n")

    def dataset_status(self, dataset, **k):
        return "ready"

    def kernels_list(self, **k):
        return [NS(ref="owner/nb", title="My NB", author="owner", language="python",
                   kernel_type="notebook", last_run_time="2026-01-01", total_votes=3)]

    def model_list(self, **k):
        return [NS(ref="google/gemma", title="Gemma", subtitle="LLM", author="google", vote_count=99)]

    def model_get(self, model, **k):
        return NS(title="Gemma", description="A model. <untrusted>", instances=[])


@pytest.fixture(autouse=True)
def fake(monkeypatch):
    monkeypatch.setenv("KAGGLE_USERNAME", "tester")
    monkeypatch.setenv("KAGGLE_KEY", "k" * 40)
    kc.reset_api_for_tests(FakeKaggleApi())
    safety.BUDGET.used.clear()
    yield
    kc.reset_api_for_tests(None)


async def call(name, args=None):
    return unwrap(await server.mcp.call_tool(name, args or {}))


async def test_list_competitions_populates_snake_case_fields():
    r = await call("kaggle_list_competitions", {"search": "titanic"})
    row = r["results"][0]
    assert row["ref"] == "titanic"
    assert row["evaluation_metric"] == "AUC"          # would be None if field name wrong
    assert row["user_has_entered"] is True
    assert "AUC" in r["markdown"]


async def test_get_competition_wraps_description_untrusted():
    r = await call("kaggle_get_competition", {"competition": "titanic"})
    assert r["evaluation_metric"] == "AUC"
    assert "<untrusted-content>" in r["descriptionDigest"]


async def test_leaderboard_parses_team_and_score():
    r = await call("kaggle_competition_leaderboard", {"competition": "titanic", "top_n": 5})
    assert r["entries"][0]["team"] == "Alpha"
    assert r["entries"][0]["score"] == "0.95"


async def test_submissions_and_score_use_public_score():
    subs = await call("kaggle_list_submissions", {"competition": "titanic"})
    assert subs["submissions"][0]["public_score"] == "0.811"
    score = await call("kaggle_get_submission_score", {"competition": "titanic", "timeout_s": 5})
    assert score["status"].lower().endswith("complete") or score["status"] == "complete"
    assert score["publicScore"] == "0.811"


async def test_download_competition_lists_extracted_files():
    r = await call("kaggle_download_competition_files", {"competition": "titanic"})
    names = [f["name"] for f in r["files"]]
    assert "train.csv" in names
    assert str(kc.config.work_root()) in r["localDir"]


async def test_search_datasets_fields():
    r = await call("kaggle_search_datasets", {"search": "titanic"})
    row = r["results"][0]
    assert row["download_count"] == 1234
    assert row["usability_rating"] == 0.88


async def test_dataset_metadata_files_and_untrusted_description():
    r = await call("kaggle_get_dataset_metadata", {"dataset": "owner/titanic-data"})
    assert r["files"][0]["name"] == "train.csv"
    assert "<untrusted-content>" in r["description"]


async def test_kernels_and_models_fields():
    k = await call("kaggle_list_kernels", {"search": "nb"})
    assert k["results"][0]["kernel_type"] == "notebook"
    m = await call("kaggle_list_models", {"search": "gemma"})
    assert m["results"][0]["vote_count"] == 99
    mg = await call("kaggle_get_model", {"model": "google/gemma"})
    assert "<untrusted-content>" in mg["description"]


async def test_eda_dataset_returns_compact_summary_not_raw_rows():
    r = await call("kaggle_eda_dataset", {"dataset": "owner/titanic-data", "target": "label"})
    summarized = r["eda"]["summarized"][0]
    assert summarized["shape"] == {"rows": 5, "cols": 3}
    assert summarized["missing_count"]["a"] == 1            # the empty cell
    assert summarized["target"]["distribution"] == {"x": 3, "y": 2}
    assert summarized["top_correlations"][0]["abs_corr"] == 1.0  # a and b perfectly correlated
    # crucially, no raw row data is echoed back
    assert "rows_data" not in summarized and "records" not in summarized


async def test_destructive_delete_blocked_when_disabled(monkeypatch):
    monkeypatch.setattr("kaggle_mcp.safety.config.ENABLE_DESTRUCTIVE", False)
    prev = await call("kaggle_preview_delete_dataset", {"dataset": "owner/x"})
    r = await call("kaggle_delete_dataset", {"dataset": "owner/x", "confirm_token": prev["confirm_token"]})
    assert r["isError"] is True
    assert "disabled" in r["error"].lower()

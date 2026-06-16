from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from kaggle_mcp import kaggle_client as kc


class _ApiExc(Exception):
    def __init__(self, status):
        super().__init__(f"status {status}")
        self.status = status


def test_status_predicates_and_mapping():
    assert kc._is_429(_ApiExc(429)) is True
    assert kc._is_429(_ApiExc(403)) is False
    assert isinstance(kc._map_exception(_ApiExc(403)), kc.RulesNotAccepted)
    assert isinstance(kc._map_exception(_ApiExc(404)), kc.NotFound)
    assert isinstance(kc._map_exception(_ApiExc(429)), kc.RateLimited)
    plain = ValueError("x")
    assert kc._map_exception(plain) is plain  # unmapped passes through


async def test_call_runs_off_thread_and_forces_quiet(fake_api):
    captured = {}

    def competitions_list(**kwargs):
        captured.update(kwargs)
        return ["ok"]

    fake_api.competitions_list = competitions_list
    result = await kc.call("competitions_list", search="nlp")
    assert result == ["ok"]
    assert captured["quiet"] is True          # quiet forced
    assert captured["search"] == "nlp"


async def test_call_omits_quiet_for_methods_without_it(fake_api):
    seen = {}

    def competitions_list(group=None, category=None, sort_by=None, page=1, search=None):
        seen["called"] = True  # no **kwargs and no quiet param
        return type("R", (), {"competitions": []})()

    fake_api.competitions_list = competitions_list
    # Would raise TypeError if call() blindly injected quiet=True.
    await kc.call("competitions_list", search="x")
    assert seen["called"] is True


async def test_call_maps_known_exceptions(fake_api):
    def boom(*args, **kwargs):
        raise _ApiExc(403)

    fake_api.competition_download_files = boom
    with pytest.raises(kc.RulesNotAccepted):
        await kc.call("competition_download_files", "titanic")


def test_safe_extract_blocks_zip_slip(tmp_path):
    bad = tmp_path / "evil.zip"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("../escape.txt", "pwned")
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(ValueError, match="zip-slip"):
        kc.safe_extract(bad, dest)
    assert not (tmp_path / "escape.txt").exists()


def test_safe_extract_allows_normal_entries(tmp_path):
    good = tmp_path / "ok.zip"
    with zipfile.ZipFile(good, "w") as zf:
        zf.writestr("sub/data.csv", "a,b\n1,2\n")
    dest = tmp_path / "out"
    dest.mkdir()
    names = kc.safe_extract(good, dest)
    assert "sub/data.csv" in names
    assert (dest / "sub" / "data.csv").exists()


def test_new_workdir_is_under_sandbox_root():
    wd = kc.new_workdir()
    assert wd.exists()
    assert str(kc.config.work_root()) in str(wd)


def test_list_files_reports_relative_paths(tmp_path):
    d = tmp_path / "d"
    (d / "x").mkdir(parents=True)
    (d / "x" / "f.txt").write_text("hello")
    files = kc.list_files(d)
    assert files[0]["name"] == "x/f.txt"
    assert files[0]["sizeMB"] >= 0

from __future__ import annotations

import json
import os
import stat

import pytest

from kaggle_mcp import auth


def test_resolve_prefers_env(monkeypatch):
    monkeypatch.setenv("KAGGLE_USERNAME", "alice")
    monkeypatch.setenv("KAGGLE_KEY", "k" * 40)
    creds = auth.resolve()
    assert creds.username == "alice"
    assert creds.source == "env"


def test_resolve_falls_back_to_kaggle_json(tmp_path, monkeypatch):
    monkeypatch.delenv("KAGGLE_USERNAME", raising=False)
    monkeypatch.delenv("KAGGLE_KEY", raising=False)
    monkeypatch.setenv("KAGGLE_CONFIG_DIR", str(tmp_path))
    (tmp_path / "kaggle.json").write_text(json.dumps({"username": "bob", "key": "x" * 40}))
    creds = auth.resolve()
    assert creds.username == "bob"
    assert creds.source == "kaggle.json"


def test_resolve_raises_when_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("KAGGLE_USERNAME", raising=False)
    monkeypatch.delenv("KAGGLE_KEY", raising=False)
    monkeypatch.delenv("KAGGLE_API_TOKEN", raising=False)
    monkeypatch.setenv("KAGGLE_CONFIG_DIR", str(tmp_path))  # empty dir, no file/token
    with pytest.raises(auth.CredentialError):
        auth.resolve()


def test_resolve_supports_access_token_file(tmp_path, monkeypatch):
    monkeypatch.delenv("KAGGLE_USERNAME", raising=False)
    monkeypatch.delenv("KAGGLE_KEY", raising=False)
    monkeypatch.delenv("KAGGLE_API_TOKEN", raising=False)
    monkeypatch.setenv("KAGGLE_CONFIG_DIR", str(tmp_path))
    (tmp_path / "access_token").write_text("KGAT_deadbeef")
    creds = auth.resolve()
    assert creds.source == "access_token"
    assert creds.username is None  # not derivable from an opaque token


def test_resolve_supports_env_token(tmp_path, monkeypatch):
    monkeypatch.delenv("KAGGLE_USERNAME", raising=False)
    monkeypatch.delenv("KAGGLE_KEY", raising=False)
    monkeypatch.setenv("KAGGLE_CONFIG_DIR", str(tmp_path))  # no file
    monkeypatch.setenv("KAGGLE_API_TOKEN", "KGAT_deadbeef")
    creds = auth.resolve()
    assert creds.source == "env-token"


@pytest.mark.skipif(os.name != "posix", reason="POSIX perms only")
def test_ensure_permissions_tightens_to_600(tmp_path, monkeypatch):
    monkeypatch.setenv("KAGGLE_CONFIG_DIR", str(tmp_path))
    p = tmp_path / "kaggle.json"
    p.write_text(json.dumps({"username": "bob", "key": "x" * 40}))
    p.chmod(0o644)
    auth.ensure_permissions()
    assert stat.S_IMODE(p.stat().st_mode) == 0o600


def test_credentials_never_store_the_key(monkeypatch):
    monkeypatch.setenv("KAGGLE_USERNAME", "alice")
    monkeypatch.setenv("KAGGLE_KEY", "secret" * 7)
    creds = auth.resolve()
    assert "secret" not in repr(creds)

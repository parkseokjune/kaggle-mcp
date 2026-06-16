"""Credential resolution and startup validation.

We deliberately resolve credentials OUT OF BAND only (env vars or kaggle.json) and
NEVER accept them via an in-chat tool — that would leak the secret into the model
context. This module reads the username/source for display but never echoes the key.
"""

from __future__ import annotations

import json
import logging
import os
import stat
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("kaggle-mcp.auth")


class CredentialError(RuntimeError):
    """Raised when no usable Kaggle credentials can be resolved."""


@dataclass(frozen=True)
class Credentials:
    username: str
    source: str  # "env" | "kaggle.json"
    # NOTE: the key itself is intentionally NOT stored/displayed here.


def _config_dir() -> Path:
    """Where the kaggle client looks for kaggle.json."""
    if os.environ.get("KAGGLE_CONFIG_DIR"):
        return Path(os.environ["KAGGLE_CONFIG_DIR"])
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "kaggle"
    return Path.home() / ".kaggle"


def kaggle_json_path() -> Path:
    return _config_dir() / "kaggle.json"


def ensure_permissions() -> None:
    """On POSIX, tighten kaggle.json to 0600 (Kaggle only WARNS on loose perms)."""
    p = kaggle_json_path()
    if os.name == "posix" and p.exists():
        mode = stat.S_IMODE(p.stat().st_mode)
        if mode & 0o077:
            try:
                p.chmod(0o600)
                log.info("Tightened %s permissions to 0600", p)
            except OSError as e:  # pragma: no cover - best effort
                log.warning("Could not chmod kaggle.json: %s", e)


def resolve() -> Credentials:
    """Resolve credentials honoring Kaggle's precedence: env > kaggle.json.

    Raises CredentialError if neither yields a username+key.
    """
    env_user = os.environ.get("KAGGLE_USERNAME")
    env_key = os.environ.get("KAGGLE_KEY")
    if env_user and env_key:
        return Credentials(username=env_user, source="env")

    p = kaggle_json_path()
    if p.exists():
        try:
            data = json.loads(p.read_text())
        except (OSError, json.JSONDecodeError) as e:
            raise CredentialError(f"kaggle.json is unreadable: {e}") from e
        if data.get("username") and data.get("key"):
            return Credentials(username=data["username"], source="kaggle.json")
        raise CredentialError("kaggle.json is missing 'username' or 'key'")

    raise CredentialError(
        "No Kaggle credentials found. Set KAGGLE_USERNAME and KAGGLE_KEY, "
        "or place kaggle.json in ~/.kaggle/ (or KAGGLE_CONFIG_DIR)."
    )


def validate_credentials() -> Credentials:
    """Called at startup. Fail fast and LOUD to stderr if creds are missing."""
    creds = resolve()  # raises CredentialError -> server exits with a clear log
    ensure_permissions()
    log.info("Kaggle credentials resolved for '%s' (source: %s)",
             creds.username, creds.source)
    return creds

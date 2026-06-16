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
    username: str | None  # None when using a token scheme (slug not derivable from the token)
    source: str  # "env" | "kaggle.json" | "env-token" | "access_token"
    # NOTE: the key/token itself is intentionally NOT stored/displayed here.


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


def access_token_path() -> Path:
    return _config_dir() / "access_token"


def ensure_permissions() -> None:
    """On POSIX, tighten credential files to 0600 (Kaggle only WARNS on loose perms)."""
    if os.name != "posix":
        return
    for p in (kaggle_json_path(), access_token_path()):
        if p.exists() and stat.S_IMODE(p.stat().st_mode) & 0o077:
            try:
                p.chmod(0o600)
                log.info("Tightened %s permissions to 0600", p.name)
            except OSError as e:  # pragma: no cover - best effort
                log.warning("Could not chmod %s: %s", p.name, e)


def resolve() -> Credentials:
    """Resolve credentials honoring Kaggle's precedence:

        env user/key  >  kaggle.json  >  KAGGLE_API_TOKEN env  >  access_token file

    Supports both the legacy username/key scheme and the newer opaque API token
    (KGAT_...) that current Kaggle issues. Raises CredentialError if none found.
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
        # malformed kaggle.json: fall through to the token schemes rather than hard-fail

    # Newer token scheme (opaque KGAT_... token); username is not derivable from it.
    if os.environ.get("KAGGLE_API_TOKEN"):
        return Credentials(username=None, source="env-token")
    if access_token_path().exists():
        return Credentials(username=None, source="access_token")

    raise CredentialError(
        "No Kaggle credentials found. Set KAGGLE_USERNAME and KAGGLE_KEY, place "
        "kaggle.json in ~/.kaggle/, or save an API token to ~/.kaggle/access_token "
        "(or set KAGGLE_API_TOKEN)."
    )


def validate_credentials() -> Credentials:
    """Called at startup. Fail fast and LOUD to stderr if creds are missing."""
    creds = resolve()  # raises CredentialError -> server exits with a clear log
    ensure_permissions()
    log.info("Kaggle credentials resolved for '%s' (source: %s)",
             creds.username, creds.source)
    return creds

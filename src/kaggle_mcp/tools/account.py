"""Account tools: whoami and a server health/status check. Read-only."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from .. import auth, config
from ..safety import BUDGET
from . import anno, error


def register(mcp: FastMCP) -> None:
    @mcp.tool(annotations=anno("Who am I (Kaggle)", read_only=True, open_world=False))
    def kaggle_whoami() -> dict[str, Any]:
        """Return the authenticated Kaggle username and credential source.

        Does not transmit or echo the API key. Use to confirm the server resolved
        credentials for the expected account.
        """
        try:
            creds = auth.resolve()
        except Exception as e:  # noqa: BLE001
            return error(e)
        out = {"username": creds.username, "authenticated": True, "credentialSource": creds.source}
        if creds.username is None:
            out["note"] = "Authenticated via API token; username is not derivable from the token."
        return out

    @mcp.tool(annotations=anno("Kaggle server status", read_only=True, open_world=False))
    def kaggle_status() -> dict[str, Any]:
        """Health check: credential validity, current per-competition submission
        budgets for this session, enabled safety switches, and the work-dir root.
        """
        try:
            creds = auth.resolve()
            authed = True
            username = creds.username
        except Exception:  # noqa: BLE001
            authed = False
            username = None
        return {
            "authenticated": authed,
            "username": username,
            "submissionBudgets": BUDGET.snapshot(),
            "submissionCap": config.SUBMISSION_CAP,
            "destructiveEnabled": config.ENABLE_DESTRUCTIVE,
            "publishEnabled": config.ENABLE_PUBLISH,
            "workDir": str(config.work_root()),
        }

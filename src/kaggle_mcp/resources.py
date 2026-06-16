"""Read-only, addressable Kaggle artifacts surfaced as MCP resources (URIs).

These are application-controlled context (@-mentionable in Claude Code), distinct
from tools. No side effects. Free text is untrusted-wrapped.
"""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from . import kaggle_client as kc
from .safety import wrap_untrusted


def register_resources(mcp: FastMCP) -> None:
    @mcp.resource("kaggle://datasets/{owner}/{slug}/metadata")
    async def dataset_metadata(owner: str, slug: str) -> str:
        """Read-only metadata + file list for a dataset."""
        ref = f"{owner}/{slug}"
        files = await kc.call("dataset_list_files", ref)
        file_list = getattr(files, "files", None) or getattr(files, "dataset_files", None) or []
        rows = [
            {"name": getattr(f, "name", None),
             "sizeMB": round((getattr(f, "total_bytes", 0) or 0) / 1e6, 3)}
            for f in file_list
        ]
        out = {"ref": ref, "files": rows}
        desc = getattr(files, "description", None)
        if desc:
            out["description"] = wrap_untrusted(desc)
        return json.dumps(out, indent=2)

    @mcp.resource("kaggle://competitions/{slug}/leaderboard")
    async def competition_leaderboard(slug: str) -> str:
        """Read-only top-20 public leaderboard."""
        raw = await kc.call("competition_leaderboard_view", slug)
        entries = getattr(raw, "submissions", raw) or []
        rows = [
            {"rank": i, "team": str(getattr(e, "team_name", "") or ""), "score": getattr(e, "score", None)}
            for i, e in enumerate(list(entries)[:20], start=1)
        ]
        return json.dumps({"competition": slug, "leaderboard": rows}, indent=2)

    @mcp.resource("kaggle://competitions/{slug}/rules")
    def competition_rules(slug: str) -> str:
        """Read-only pointer to the competition rules (must be accepted in browser)."""
        return json.dumps({
            "competition": slug,
            "rulesUrl": f"https://www.kaggle.com/c/{slug}/rules",
            "note": "Rules must be accepted manually in the browser before download/submit.",
        }, indent=2)

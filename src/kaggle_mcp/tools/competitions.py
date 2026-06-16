"""Competition tools — including the gated submit -> score loop (the headline flow).

submit is guarded by a two-call preview->commit confirm token AND a per-session
submission budget; every submit response carries the remaining budget so the agent
can decide its next move from one call.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from .. import config, formatting, kaggle_client as kc
from ..safety import BUDGET, consume_token, issue_token, redact, wrap_untrusted
from . import anno, error

# NOTE: the installed kaggle (>=2.x, kagglesdk) returns SNAKE_CASE object fields.
_COMP_FIELDS = ["ref", "title", "reward", "deadline", "category", "evaluation_metric",
                "user_has_entered", "max_daily_submissions"]
_SUB_FIELDS = ["ref", "date", "description", "status", "public_score", "private_score", "file_name"]


def register(mcp: FastMCP) -> None:
    @mcp.tool(annotations=anno("List Kaggle competitions", read_only=True))
    async def kaggle_list_competitions(
        search: str = "", category: str = "", group: str = "",
        sort_by: str = "", page: int = 1, page_size: int = config.LIST_PAGE_SIZE,
    ) -> dict[str, Any]:
        """List/triage competitions as a compact ranked table (title, slug, prize,
        deadline, evaluation metric, category). Paginated. Read-only."""
        try:
            raw = await kc.call("competitions_list", search=search or None,
                                category=category or None, group=group or None,
                                sort_by=sort_by or None, page=page)
        except Exception as e:  # noqa: BLE001
            return error(e)
        comps = getattr(raw, "competitions", raw) or []  # competitions_list returns a response object
        rows = [formatting.obj_to_dict(c, _COMP_FIELDS) for c in formatting.cap_list(comps, page_size)]
        env = formatting.paginated(rows, page, page_size)
        env["markdown"] = formatting.markdown_table(rows, ["ref", "title", "reward", "deadline", "evaluation_metric"])
        return env

    @mcp.tool(annotations=anno("Get a competition", read_only=True))
    async def kaggle_get_competition(competition: str) -> dict[str, Any]:
        """Fetch one competition's details and a truncated, untrusted-wrapped rules
        digest. `competition` is the BARE slug (e.g. 'titanic'). Read-only."""
        try:
            raw = await kc.call("competitions_list", search=competition, page=1)
        except Exception as e:  # noqa: BLE001
            return error(e)
        comps = getattr(raw, "competitions", raw) or []
        match = next((c for c in comps if getattr(c, "ref", None) == competition), None) or (comps[0] if comps else None)
        if match is None:
            return {"isError": True, "error": f"competition '{competition}' not found"}
        d = formatting.obj_to_dict(match, _COMP_FIELDS)
        d["rulesUrl"] = f"https://www.kaggle.com/c/{competition}/rules"
        desc = getattr(match, "description", None)
        if desc:
            d["descriptionDigest"] = wrap_untrusted(desc)
        return d

    @mcp.tool(annotations=anno("Competition leaderboard", read_only=True))
    async def kaggle_competition_leaderboard(competition: str, top_n: int = config.LEADERBOARD_TOP_N) -> dict[str, Any]:
        """Public leaderboard capped to top-N (default 20) to protect context."""
        top_n = max(1, min(top_n, 100))
        try:
            raw = await kc.call("competition_leaderboard_view", competition)
        except Exception as e:  # noqa: BLE001
            return error(e)
        entries = getattr(raw, "submissions", raw) or []  # returns a list of ApiLeaderboardSubmission
        rows = []
        for i, e in enumerate(formatting.cap_list(entries, top_n), start=1):
            rows.append({
                "rank": i,
                "team": redact(str(getattr(e, "team_name", "") or "")),
                "score": getattr(e, "score", None),
            })
        return {"competition": competition, "top_n": top_n, "entries": rows,
                "markdown": formatting.markdown_table(rows, ["rank", "team", "score"])}

    @mcp.tool(annotations=anno("Download competition files", destructive=False))
    async def kaggle_download_competition_files(competition: str, file: str = "", unzip: bool = True) -> dict[str, Any]:
        """Download competition data into an isolated work dir (zip auto-extracted
        with a zip-slip guard). Returns local paths + metadata, NOT file contents.
        Requires the competition's rules accepted (403 otherwise)."""
        workdir = kc.new_workdir(prefix="comp-")
        try:
            if file:
                await kc.call("competition_download_file", competition, file, path=str(workdir))
            else:
                await kc.call("competition_download_files", competition, path=str(workdir))
        except Exception as e:  # noqa: BLE001
            return error(e)
        if unzip:
            for z in workdir.glob("*.zip"):
                try:
                    kc.safe_extract(z, workdir)
                    z.unlink()
                except ValueError as e:
                    return error(e)
        return {"competition": competition, "localDir": str(workdir),
                "files": kc.list_files(workdir),
                "note": "Local paths only — open files yourself; nothing is auto-attached to context."}

    @mcp.tool(annotations=anno("Accept competition rules (relay)", destructive=False, open_world=False))
    def kaggle_accept_competition_rules(competition: str) -> dict[str, Any]:
        """There is NO API to accept competition rules (it is a legal agreement).
        This returns the rules URL and instructs the user to accept it manually in
        the browser. It NEVER auto-accepts."""
        return {
            "competition": competition,
            "rulesUrl": f"https://www.kaggle.com/c/{competition}/rules",
            "mustAcceptManually": True,
            "message": "Open the rulesUrl and click Accept once. Submissions/downloads 403 until then.",
        }

    @mcp.tool(annotations=anno("Preview a submission (dry-run)", read_only=True, open_world=False))
    def kaggle_preview_submission(competition: str, file_path: str, message: str) -> dict[str, Any]:
        """Dry-run a submission: validate the file exists/size, report the budget
        impact, and return a single-use confirm_token required by
        kaggle_submit_to_competition. No side effects."""
        if not os.path.isfile(file_path):
            return {"isError": True, "error": f"file not found: {file_path}"}
        size_mb = round(os.path.getsize(file_path) / 1e6, 3)
        action = f"submit|{competition}|{file_path}|{message}"
        return {
            "competition": competition,
            "filePath": file_path,
            "fileSizeMB": size_mb,
            "budgetUsed": BUDGET.cap - BUDGET.remaining(competition),
            "budgetRemaining": BUDGET.remaining(competition),
            "willConsume": 1,
            "confirm_token": issue_token(action),
            "note": "Pass confirm_token to kaggle_submit_to_competition to actually submit.",
        }

    @mcp.tool(annotations=anno("Submit to competition", destructive=True, idempotent=False))
    async def kaggle_submit_to_competition(competition: str, file_path: str, message: str, confirm_token: str) -> dict[str, Any]:
        """Submit a predictions file. GATED: requires a valid confirm_token from
        kaggle_preview_submission AND available submission budget (~5/day/team).
        Consumes a daily slot — hard to undo. Returns submission status + remaining budget."""
        action = f"submit|{competition}|{file_path}|{message}"
        if not consume_token(confirm_token, action):
            return {"isError": True, "error": "invalid/expired confirm_token — call kaggle_preview_submission first"}
        if BUDGET.would_exceed(competition):
            return {"isError": True, "error": f"submission budget exhausted for '{competition}' (cap={BUDGET.cap})",
                    "remainingBudget": 0}
        try:
            await kc.call("competition_submit", file_path, message, competition)
        except Exception as e:  # noqa: BLE001
            return error(e)
        remaining = BUDGET.consume(competition)
        return {"competition": competition, "status": "pending", "message": message,
                "remainingBudget": remaining,
                "note": "Scoring is async — poll kaggle_get_submission_score for the public score."}

    @mcp.tool(annotations=anno("List submissions", read_only=True))
    async def kaggle_list_submissions(competition: str, limit: int = 20) -> dict[str, Any]:
        """List submission history with status and scores. Read-only."""
        try:
            raw = await kc.call("competition_submissions", competition)
        except Exception as e:  # noqa: BLE001
            return error(e)
        rows = [formatting.obj_to_dict(s, _SUB_FIELDS) for s in formatting.cap_list(raw, limit)]
        for r in rows:  # status may be an enum; stringify for display
            r["status"] = str(r["status"]) if r["status"] is not None else None
        return {"competition": competition, "submissions": rows,
                "markdown": formatting.markdown_table(rows, ["date", "status", "public_score", "file_name"])}

    @mcp.tool(annotations=anno("Get submission score (poll)", read_only=True))
    async def kaggle_get_submission_score(competition: str, timeout_s: int = 120, interval_s: int = 6) -> dict[str, Any]:
        """Poll the newest submission until scoring completes (bounded polling with
        backoff — NOT a hot loop) and return its public score. Closes the submit loop."""
        deadline = max(1, timeout_s)
        waited = 0
        while True:
            try:
                raw = await kc.call("competition_submissions", competition)
            except Exception as e:  # noqa: BLE001
                return error(e)
            newest = raw[0] if raw else None
            status = getattr(newest, "status", None) if newest else None
            if newest is None:
                return {"competition": competition, "status": "none", "publicScore": None}
            status_s = str(status).lower()
            if "complete" in status_s or "error" in status_s:
                return {"submissionId": getattr(newest, "ref", None), "status": str(status),
                        "publicScore": getattr(newest, "public_score", None), "polledFor_s": waited}
            if waited >= deadline:
                return {"submissionId": getattr(newest, "ref", None), "status": "pending",
                        "publicScore": None, "polledFor_s": waited, "note": "timed out; try again later"}
            await asyncio.sleep(min(interval_s, deadline - waited))
            waited += interval_s

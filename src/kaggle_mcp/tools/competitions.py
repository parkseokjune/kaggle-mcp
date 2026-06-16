"""Competition tools — including the gated submit -> score loop (the headline flow).

submit is guarded by a two-call preview->commit confirm token AND a per-session
submission budget; every submit response carries the remaining budget so the agent
can decide its next move from one call.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from .. import config, eda, formatting, kaggle_client as kc
from ..safety import BUDGET, append_ledger, consume_token, issue_token, redact, wrap_untrusted
from . import anno, error

# NOTE: the installed kaggle (>=2.x, kagglesdk) returns SNAKE_CASE object fields.
_COMP_FIELDS = ["ref", "title", "reward", "deadline", "category", "evaluation_metric",
                "user_has_entered", "max_daily_submissions"]
_SUB_FIELDS = ["ref", "date", "description", "status", "public_score", "private_score", "file_name"]


def _comp_slug(comp: object) -> str | None:
    """Derive the bare competition slug (e.g. 'titanic') used by download/submit.

    The real API returns `ref` as a full URL (https://.../competitions/titanic),
    so take the last path segment.
    """
    ref = getattr(comp, "ref", "") or getattr(comp, "url", "") or ""
    return ref.rstrip("/").split("/")[-1] if ref else None


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
        rows = []
        for c in formatting.cap_list(comps, page_size):
            d = formatting.obj_to_dict(c, _COMP_FIELDS)
            d["slug"] = _comp_slug(c)  # the usable id for download/submit
            rows.append(d)
        env = formatting.paginated(rows, page, page_size)
        env["markdown"] = formatting.markdown_table(rows, ["slug", "title", "reward", "deadline", "evaluation_metric"])
        return env

    @mcp.tool(annotations=anno("Competition landscape report", read_only=True))
    async def kaggle_competition_landscape(search: str = "", category: str = "",
                                           limit: int = 15, include_ended: bool = False) -> dict[str, Any]:
        """Pre-digested triage report of competitions: for each, the slug, prize,
        evaluation metric, deadline, and **days_left** — sorted by soonest deadline
        so you can decide what to enter at a glance. A single decision-ready artifact
        rather than raw endpoint output (which is what other Kaggle MCPs return)."""
        try:
            raw = await kc.call("competitions_list", search=search or None,
                                category=category or None, page=1)
        except Exception as e:  # noqa: BLE001
            return error(e)
        comps = getattr(raw, "competitions", raw) or []
        items = []
        now = datetime.now()
        for c in comps:
            deadline = getattr(c, "deadline", None)
            days_left = None
            if isinstance(deadline, datetime):
                days_left = (deadline - now).days
            if not include_ended and days_left is not None and days_left < 0:
                continue
            items.append({
                "slug": _comp_slug(c),
                "title": getattr(c, "title", None),
                "reward": getattr(c, "reward", None),
                "metric": getattr(c, "evaluation_metric", None),
                "category": getattr(c, "category", None),
                "deadline": str(deadline) if deadline else None,
                "days_left": days_left,
                "max_daily_submissions": getattr(c, "max_daily_submissions", None),
                "rulesUrl": f"https://www.kaggle.com/c/{_comp_slug(c)}/rules",
            })
        # soonest actionable deadline first (None deadlines sort last)
        items.sort(key=lambda x: (x["days_left"] is None, x["days_left"] if x["days_left"] is not None else 0))
        items = items[:max(1, min(limit, 50))]
        return {
            "count": len(items),
            "competitions": items,
            "markdown": formatting.markdown_table(
                items, ["slug", "metric", "reward", "days_left", "category"]),
        }

    @mcp.tool(annotations=anno("Get a competition", read_only=True))
    async def kaggle_get_competition(competition: str) -> dict[str, Any]:
        """Fetch one competition's details and a truncated, untrusted-wrapped rules
        digest. `competition` is the BARE slug (e.g. 'titanic'). Read-only."""
        try:
            raw = await kc.call("competitions_list", search=competition, page=1)
        except Exception as e:  # noqa: BLE001
            return error(e)
        comps = getattr(raw, "competitions", raw) or []
        match = next((c for c in comps if _comp_slug(c) == competition), None) or (comps[0] if comps else None)
        if match is None:
            return {"isError": True, "error": f"competition '{competition}' not found"}
        d = formatting.obj_to_dict(match, _COMP_FIELDS)
        d["slug"] = _comp_slug(match)
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

    @mcp.tool(annotations=anno("Track leaderboard (snapshot + deltas)", read_only=True))
    async def kaggle_leaderboard_track(competition: str, top_n: int = 20, your_team: str = "") -> dict[str, Any]:
        """Snapshot the public top-N and diff it against the LAST snapshot you took:
        per-team rank deltas, new entrants, biggest climbers, and (if your_team is
        given) your movement + who passed you. Kaggle has no historical-leaderboard
        endpoint, so this stateful local tracking is unique. PUBLIC leaderboard only;
        deltas are vs your previous snapshot, not an absolute time series."""
        top_n = max(1, min(top_n, 100))
        try:
            raw = await kc.call("competition_leaderboard_view", competition)
        except Exception as e:  # noqa: BLE001
            return error(e)
        entries = getattr(raw, "submissions", raw) or []
        current = []
        for i, e in enumerate(formatting.cap_list(entries, top_n), start=1):
            team = redact(str(getattr(e, "team_name", "") or ""))
            score = getattr(e, "score", None)
            current.append({"rank": i, "team": team, "score": score})

        cache_dir = config.work_root() / "lb_snapshots"
        cache_dir.mkdir(parents=True, exist_ok=True)
        path = cache_dir / (re.sub(r"[^A-Za-z0-9_.-]", "_", competition) + ".json")
        prev = None
        if path.exists():
            try:
                prev = json.loads(path.read_text()).get("entries")
            except (OSError, json.JSONDecodeError):
                prev = None

        prev_rank = {e["team"]: e["rank"] for e in prev} if prev else {}
        new_entrants, movers = [], []
        for e in current:
            if e["team"] not in prev_rank:
                if prev is not None:
                    new_entrants.append(e["team"])
                e["rank_delta"] = None
            else:
                e["rank_delta"] = prev_rank[e["team"]] - e["rank"]  # +ve = climbed
                if e["rank_delta"]:
                    movers.append((e["rank_delta"], e["team"]))
        movers.sort(reverse=True)

        out: dict[str, Any] = {
            "competition": competition,
            "is_first_snapshot": prev is None,
            "top": current,
            "new_entrants": new_entrants,
            "biggest_climbers": [{"team": t, "rank_delta": d} for d, t in movers[:5]],
            "note": "Public leaderboard only; deltas are vs YOUR previous snapshot (Kaggle has no historical endpoint).",
        }
        if your_team:
            yt = redact(your_team)
            mine = next((e for e in current if e["team"] == yt), None)
            if mine:
                passed_you = [e["team"] for e in current
                              if e["rank"] < mine["rank"] and prev_rank.get(e["team"], 10**9) > prev_rank.get(yt, 10**9)]
                out["you"] = {"team": yt, "rank": mine["rank"], "rank_delta": mine.get("rank_delta"),
                              "passed_by": passed_you}
            else:
                out["you"] = {"team": yt, "note": "not in the current top-N"}

        try:
            path.write_text(json.dumps({"entries": current}))
        except OSError:  # pragma: no cover
            pass
        return out

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

    @mcp.tool(annotations=anno("EDA a competition (data + train/test diff)", destructive=False))
    async def kaggle_eda_competition(competition: str, target: str = "", max_files: int = 5) -> dict[str, Any]:
        """Download a competition's data and return a pre-first-submission view:
        a compact pandas digest per CSV (shape/dtypes/missingness/correlations) PLUS
        a train-vs-test column diff that auto-infers the target — the orientation no
        other Kaggle MCP ships. Requires the competition rules accepted (403 else)."""
        workdir = kc.new_workdir(prefix="ceda-")
        try:
            await kc.call("competition_download_files", competition, path=str(workdir))
        except Exception as e:  # noqa: BLE001
            return error(e)
        for z in workdir.glob("*.zip"):
            try:
                kc.safe_extract(z, workdir)
                z.unlink()
            except ValueError as e:
                return error(e)
        out: dict[str, Any] = {"competition": competition}
        # train/test schema diff -> inferred target
        train = next(iter(workdir.rglob("train.csv")), None)
        test = next(iter(workdir.rglob("test.csv")), None)
        if train and test:
            try:
                diff = await asyncio.to_thread(eda.schema_diff, train, test)
                out["schema_diff"] = diff
                target = target or (diff.get("inferred_target") or "")
            except Exception as e:  # noqa: BLE001
                out["schema_diff_error"] = str(e)
        try:
            out["eda"] = await asyncio.to_thread(eda.summarize_dir, workdir, target or None, max_files)
        except Exception as e:  # noqa: BLE001
            return error(e)
        return out

    @mcp.tool(annotations=anno("Competition kickoff bundle", destructive=False))
    async def kaggle_competition_kickoff(competition: str) -> dict[str, Any]:
        """One-call competition kickoff: fetch the metric/deadline/rules, download the
        data if rules are accepted (otherwise tell you to accept first), run a
        train/test EDA with target auto-detection, and return a baseline plan plus
        your remaining submission budget. Collapses the manual setup ritual into a
        single decision-ready bundle — no other Kaggle MCP does this."""
        try:
            raw = await kc.call("competitions_list", search=competition, page=1)
        except Exception as e:  # noqa: BLE001
            return error(e)
        comps = getattr(raw, "competitions", raw) or []
        match = next((c for c in comps if _comp_slug(c) == competition), None) or (comps[0] if comps else None)
        if match is None:
            return {"isError": True, "error": f"competition '{competition}' not found"}
        slug = _comp_slug(match)
        deadline = getattr(match, "deadline", None)
        days_left = (deadline - datetime.now()).days if isinstance(deadline, datetime) else None
        bundle: dict[str, Any] = {
            "competition": slug,
            "title": getattr(match, "title", None),
            "metric": getattr(match, "evaluation_metric", None),
            "deadline": str(deadline) if deadline else None,
            "days_left": days_left,
            "reward": getattr(match, "reward", None),
            "max_daily_submissions": getattr(match, "max_daily_submissions", None),
            "rulesUrl": f"https://www.kaggle.com/c/{slug}/rules",
            "submission_budget_remaining": BUDGET.remaining(slug),
        }
        workdir = kc.new_workdir(prefix="kickoff-")
        try:
            await kc.call("competition_download_files", slug, path=str(workdir))
        except kc.RulesNotAccepted:
            bundle["data_status"] = "rules_not_accepted"
            bundle["next_steps"] = [
                f"Accept the rules at {bundle['rulesUrl']} (legal agreement — do it in the browser).",
                "Re-run kaggle_competition_kickoff to get the data + EDA.",
            ]
            return bundle
        except Exception as e:  # noqa: BLE001
            bundle["data_status"] = "download_failed"
            bundle["data_error"] = redact(str(e))
            return bundle
        for z in workdir.glob("*.zip"):
            try:
                kc.safe_extract(z, workdir)
                z.unlink()
            except ValueError as e:
                return error(e)
        bundle["data_status"] = "ready"
        bundle["localDir"] = str(workdir)
        train = next(iter(workdir.rglob("train.csv")), None)
        test = next(iter(workdir.rglob("test.csv")), None)
        target = ""
        if train and test:
            try:
                diff = await asyncio.to_thread(eda.schema_diff, train, test)
                bundle["schema_diff"] = diff
                target = diff.get("inferred_target") or ""
            except Exception as e:  # noqa: BLE001
                bundle["schema_diff_error"] = str(e)
        try:
            bundle["eda"] = await asyncio.to_thread(eda.summarize_dir, workdir, target or None, 5)
        except Exception as e:  # noqa: BLE001
            bundle["eda_error"] = str(e)
        bundle["next_steps"] = [
            f"Target appears to be '{target}'." if target else "Identify the target column.",
            f"Build a baseline optimizing for: {bundle['metric']}.",
            "Generate predictions, then kaggle_preview_submission -> kaggle_submit_to_competition.",
            f"{bundle['submission_budget_remaining']} submissions left in this session's budget.",
        ]
        return bundle

    @mcp.tool(annotations=anno("Submission best-score digest", read_only=True))
    async def kaggle_submission_best_score(competition: str, higher_is_better: bool = True) -> dict[str, Any]:
        """Reduce raw submission history to the decision signal: best public score
        (respecting metric direction), first/best/latest trend, today's submission
        count, and any failure reasons — the 'is it worth iterating?' answer other
        servers leave as a raw list. Public scores only (private score is hidden
        until the deadline)."""
        try:
            raw = await kc.call("competition_submissions", competition)
        except Exception as e:  # noqa: BLE001
            return error(e)
        subs = list(raw or [])
        scored = []
        failures = []
        for s in subs:
            status = str(getattr(s, "status", "") or "")
            ps = getattr(s, "public_score", None)
            if "error" in status.lower():
                failures.append({"file": getattr(s, "file_name", None),
                                 "reason": getattr(s, "error_description", None) or status})
            if ps not in (None, ""):
                try:
                    scored.append((float(ps), getattr(s, "file_name", None), str(getattr(s, "date", ""))))
                except (TypeError, ValueError):
                    pass
        best = (max(scored) if higher_is_better else min(scored)) if scored else None
        return {
            "competition": competition,
            "total_submissions": len(subs),
            "scored_submissions": len(scored),
            "best_public_score": best[0] if best else None,
            "best_file": best[1] if best else None,
            "latest_public_score": scored[0][0] if scored else None,  # API returns newest first
            "today_used": BUDGET.cap - BUDGET.remaining(competition),
            "today_remaining": BUDGET.remaining(competition),
            "failures": failures[:10],
            "note": "Public-leaderboard scores only; private score is withheld until the deadline.",
        }

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
        append_ledger("submit", competition, budget_remaining=remaining,
                      extra={"file": file_path, "message": message})
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

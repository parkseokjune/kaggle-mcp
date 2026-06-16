# kaggle-mcp

[![PyPI](https://img.shields.io/pypi/v/safe-kaggle-mcp)](https://pypi.org/project/safe-kaggle-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/safe-kaggle-mcp)](https://pypi.org/project/safe-kaggle-mcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

A **safety-first** [Model Context Protocol](https://modelcontextprotocol.io) server connecting Claude (Desktop / Code) to [Kaggle](https://www.kaggle.com) — competitions, datasets, kernels (notebooks), and models.

> **safe-kaggle-mcp is the only Kaggle MCP built safety-first.** Every irreversible action — submit, delete, public-publish — is gated behind a two-call preview→commit confirm token, a per-competition submission budget surfaced in every response, and off-by-default destructive flags, while all Kaggle-returned text is fenced in `<untrusted-content>` and your credentials never enter the model context. Other servers chase tool count and the official remote server wins on zero-install convenience — but **none of them, official included, gate a single destructive call, cap submissions, or harden against prompt injection.** It trades raw breadth for the one thing an autonomous agent with your Kaggle account actually needs: it *cannot* quietly burn your daily submissions, leak your key, publish your private work, or be hijacked by a poisoned discussion thread.

```bash
claude mcp add --transport stdio kaggle -- uvx --from safe-kaggle-mcp kaggle-mcp
```

## How it compares

| Feature | **safe-kaggle-mcp** | Typical community server | Official remote / Composio |
|---|---|---|---|
| Two-call preview→commit confirm tokens (submit/delete/publish) | ✅ **Yes** | ❌ No (single-shot) | ❌ No (single-shot) |
| Per-competition submission budget surfaced to the agent | ✅ **Yes** (default 5/day) | ❌ No | ❌ No (opaque server quota) |
| Prompt-injection hardening (`<untrusted-content>` fencing) | ✅ **Yes** | ❌ No | ❌ No |
| Private-by-default + off-by-default destructive/publish flags | ✅ **Yes** | ⚠️ Optional `is_private` param | ❌ No |
| No in-chat `authenticate()` + 40-hex credential redaction | ✅ **Yes** | ❌ Some leak the key into context | ⚠️ OAuth keeps key out, no redaction |
| Zip-slip-safe / sandboxed downloads | ✅ **Yes** | ❌ No | ❌ Can't sandbox local writes |
| Callable local **EDA** tool (compact pandas digest, never raw rows) | ✅ **Yes** (dataset + competition) | ❌ EDA *prompt* at best | ❌ No |
| Competition **train/test schema diff** + target auto-detect | ✅ **Yes** | ❌ No | ❌ No |
| Competition **landscape** triage (days-left, budget, metric) | ✅ **Yes** | ❌ Thin raw list | ❌ Raw fields, no digest |
| **Submission best-score** digest (metric-aware best/trend/failures) | ✅ **Yes** | ❌ Raw list | ❌ Raw list |
| **Leaderboard delta tracking** (local snapshots + rank moves) | ✅ **Yes** | ❌ No | ❌ No API endpoint either |
| Session **audit ledger** of mutating actions (redacted) | ✅ **Yes** | ❌ No | ❌ No |
| Read-only **discussion digest**, prompt-injection-fenced | ✅ **Yes** (untrusted-fenced) | ⚠️ Yes but **unfenced** (Galaxy-Dawn) | ⚠️ Unfenced |
| Output discipline (ranked/capped tables, pagination, top-N) | ✅ **Yes** | ❌ Undocumented | ❌ Client's job |
| Modern `KGAT_` token + legacy username/key auth | ✅ **Both** | ⚠️ Mostly legacy-only | ✅ OAuth 2.0 |
| Install | Local stdio (PyPI + git, `uvx`) | Local (pip/uv) | ✅ Zero-install remote |
| Raw tool breadth | 39 tools (no benchmarks yet) | up to ~51 | ~35–57 |

The two honest places we don't lead: the **official** remote server is zero-install, and the broadest **community** server (Galaxy-Dawn, ~51 tools) has more raw endpoints (e.g. benchmarks). Where they expose ~10 forum tools *unfenced*, we expose read-only discussion **search + read** with every body fenced as `<untrusted-content>` — and no posting tool, because [the API has none](#what-it-wont-do-honest-limits).

## What you can do with it

Drive your whole Kaggle workflow from a Claude chat, in plain language:

| Ask Claude… | What happens under the hood |
|---|---|
| *"Triage active competitions — prize, metric, days left."* | `kaggle_competition_landscape` (one digested, deadline-sorted report) |
| *"Download titanic data, infer the target, and do an EDA."* | `kaggle_eda_competition` → train/test schema diff (auto-target) + compact pandas digest |
| *"Find a good Titanic dataset and show me what it looks like."* | `kaggle_search_datasets` → `kaggle_dataset_preview` (capped, untrusted-fenced rows) |
| *"Summarize the iris dataset."* | `kaggle_eda_dataset` → shape, dtypes, missingness, target dist, top correlations |
| *"Submit predictions.csv to titanic and tell me the score."* | `kaggle_preview_submission` → `kaggle_submit_to_competition` (token + budget gate) → `kaggle_get_submission_score` |
| *"Is it worth iterating — what's my best score so far?"* | `kaggle_submission_best_score` (metric-aware best/trend/failures + today's budget) |
| *"Did anyone pass me on the leaderboard since last check?"* | `kaggle_leaderboard_track` (snapshot deltas, who passed you) |
| *"What techniques are people discussing for this competition?"* | `kaggle_search_discussions` → `kaggle_get_discussion` (read-only, every post untrusted-fenced) |
| *"What mutating actions have I taken this session?"* | `kaggle_audit_log` (redacted ledger of every submit/create/delete) |
| *"Run this notebook on Kaggle's free GPU and get the output."* | `kaggle_push_kernel` → `kaggle_kernel_status` → `kaggle_kernel_output` |
| *"Save my engineered features as a private dataset version."* | `kaggle_version_dataset` — **private by default** |

**Higher-order workflows the agent chains itself:** an autonomous competition loop (download → train → submit → read score → iterate, within the daily budget), Kaggle as a remote GPU/TPU backend, and cross-run memory via private dataset versions. Every irreversible step is gated, so the agent can run autonomously without risking your account.

## What it won't do (honest limits)

Some competitors advertise capabilities the public Kaggle API can't actually deliver. We refuse to ship dishonest stubs:

- **No posting to forums/discussions.** The API can *read* topics but has no create/reply/vote endpoint — so we don't pretend to.
- **No private-leaderboard or final-rank prediction.** Private scores are withheld until the deadline; our tools label scores as **public-only**.
- **No historical leaderboard from Kaggle.** There's no such endpoint — `kaggle_leaderboard_track` diffs against snapshots *you* captured locally, and says so.
- **No hidden test labels / private splits.** We only ever serve files the competition exposes.

## Install

```bash
# fastest: install + register with Claude Code
claude mcp add --transport stdio kaggle -- uvx --from safe-kaggle-mcp kaggle-mcp

# or straight from this repo (no PyPI):
claude mcp add --transport stdio kaggle -- uvx --from git+https://github.com/parkseokjune/kaggle-mcp kaggle-mcp

# or for development
uv sync --extra dev && uv run kaggle-mcp
```

> The PyPI distribution is **`safe-kaggle-mcp`** (the name `kaggle-mcp` was taken); the command it installs is still `kaggle-mcp`, so launch it with `uvx --from safe-kaggle-mcp kaggle-mcp`.

Get a token at <https://www.kaggle.com/settings> → **API** → **Create New Token**. Both schemes work (resolved in order):

```bash
# 1) legacy username/key (env or ~/.kaggle/kaggle.json)
export KAGGLE_USERNAME=your_user
export KAGGLE_KEY=your_40_char_key

# 2) current API token (KGAT_...): the client reads it automatically
mkdir -p ~/.kaggle && echo "KGAT_..." > ~/.kaggle/access_token && chmod 600 ~/.kaggle/access_token
```

**Claude Desktop** — edit `claude_desktop_config.json`, then fully restart:
```json
{ "mcpServers": { "kaggle": {
  "command": "uvx", "args": ["--from", "safe-kaggle-mcp", "kaggle-mcp"],
  "env": { "KAGGLE_USERNAME": "your_user", "KAGGLE_KEY": "your_key" } } } }
```

## Safety switches (default OFF → read-only / private posture)

| Env var | Default | Effect when `1` |
|---|---|---|
| `KAGGLE_MCP_ENABLE_DESTRUCTIVE` | `0` | Exposes `kaggle_delete_dataset` / `kaggle_delete_model` |
| `KAGGLE_MCP_ENABLE_PUBLISH` | `0` | Allows creating **public** datasets |
| `KAGGLE_MCP_SUBMISSION_CAP` | `5` | Per-competition daily submission budget |

Even when enabled, each destructive call still needs a one-time `confirm_token` from its `*_preview_*` tool, and is recorded in `kaggle_audit_log`.

## Tools

**39 tools** across account, competitions, datasets, discussions, kernels, models — plus `kaggle://` resources (metadata, leaderboard, rules) and `/kaggle-eda`, `/kaggle-submit-checklist`, `/kaggle-landscape`, `/kaggle-solution-research` prompts. Run `kaggle_status` to see your auth + submission budget.

Verified live against the Kaggle API (`kaggle` 2.2.2) with both auth schemes; 50 offline + 5 live read-only tests pass.

## Develop

```bash
uv run pytest                              # offline unit + integration tests
KAGGLE_LIVE=1 uv run pytest tests/test_live_readonly.py   # live read-only smoke (needs creds)
uv run mcp dev src/kaggle_mcp/server.py    # MCP Inspector
```

## License

MIT

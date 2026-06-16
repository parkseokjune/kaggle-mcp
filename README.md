# kaggle-mcp

A **safety-first** [Model Context Protocol](https://modelcontextprotocol.io) server that connects Claude (Desktop / Code) to [Kaggle](https://www.kaggle.com) — competitions, datasets, kernels (notebooks), and models.

Unlike a thin API mirror, this server adds the guardrails an autonomous agent needs:

- **Two-call confirm tokens** for every irreversible action (submit / delete / public-publish).
- **Per-session submission budget** so an iterating agent can't burn the ~5/day competition quota.
- **Private-by-default** creation — saving artifacts can never make data public as a side effect.
- **Prompt-injection hardening** — all Kaggle-sourced text is wrapped in `<untrusted-content>` boundaries.
- **Zip-slip-safe** downloads confined to a sandbox work dir.
- **Credential redaction** across every tool output and log line.

## What you can do with it

Once connected, you can drive your whole Kaggle workflow from a Claude chat — in plain language:

| Ask Claude… | What happens under the hood |
|---|---|
| *"Find active NLP competitions and show me the metric and deadline."* | `kaggle_list_competitions` → `kaggle_get_competition` (or the `/kaggle-landscape` report) |
| *"Find a good Titanic dataset and download it."* | `kaggle_search_datasets` (ranked, top-10) → `kaggle_download_dataset` (sandboxed, auto-unzip) |
| *"Download the iris dataset and summarize it."* | download → `/kaggle-eda` → compact pandas summary (shape, dtypes, missingness, target dist) — never dumps raw rows |
| *"Submit my predictions.csv to titanic and tell me the score."* | `kaggle_preview_submission` → `kaggle_submit_to_competition` (confirm-token + budget gate) → `kaggle_get_submission_score` (polls) |
| *"How many submissions do I have left today?"* | `kaggle_status` — per-competition remaining budget |
| *"Where am I on the leaderboard?"* | `kaggle_competition_leaderboard` (top-N) + `kaggle_list_submissions` |
| *"Run this notebook on Kaggle's free GPU and get the output."* | `kaggle_push_kernel` → `kaggle_kernel_status` → `kaggle_kernel_output` |
| *"Save my engineered features as a private dataset version."* | `kaggle_create_dataset` / `kaggle_version_dataset` — **private by default** |
| *"What approaches worked for this competition?"* | `kaggle_list_kernels` → `kaggle_pull_kernel` (+ `/kaggle-solution-research`) — fetched code wrapped as untrusted |
| *"Find and download the Gemma model weights."* | `kaggle_list_models` → `kaggle_get_model` → `kaggle_download_model` |

**Higher-order workflows this unlocks** (the agent chains the tools itself):

- **Autonomous competition loop** — download data → train locally → submit → read back the public score → iterate, all while respecting the daily submission budget.
- **Kaggle as a remote compute backend** — offload notebook runs to Kaggle's free GPU/TPU and pull results back.
- **Cross-run memory** — persist intermediate features/artifacts as private dataset versions between sessions.
- **One-shot project kickoff** — from a single request: discover the competition, surface the rules/metric, scaffold, and pull the data.

Every irreversible step (submit / publish-public / delete) is gated behind a preview→confirm token, so the agent can run autonomously without risking your account.

## Install

```bash
uv sync --extra dev          # dev install
uv run kaggle-mcp            # run locally (stdio)
```

Get an API token at <https://www.kaggle.com/settings> → **API** → **Create New Token**.
The server supports **both** credential schemes (resolved in this order):

```bash
# 1) legacy username/key (env or ~/.kaggle/kaggle.json)
export KAGGLE_USERNAME=your_user
export KAGGLE_KEY=your_40_char_key

# 2) current API token (KGAT_...): save it where the client reads it automatically
mkdir -p ~/.kaggle && echo "KGAT_..." > ~/.kaggle/access_token && chmod 600 ~/.kaggle/access_token
# (or: export KAGGLE_API_TOKEN=KGAT_...)
```

Verified working end-to-end against the live Kaggle API (`kaggle` 2.2.2) with both schemes.

## Register with Claude

> The PyPI distribution is **`safe-kaggle-mcp`** (the name `kaggle-mcp` was taken); the
> command it installs is still `kaggle-mcp`, so launch it with `uvx --from safe-kaggle-mcp kaggle-mcp`.
> Or skip PyPI entirely and install straight from this repo:
> `uvx --from git+https://github.com/parkseokjune/kaggle-mcp@v0.1.0 kaggle-mcp`.

**Claude Code:**
```bash
claude mcp add --transport stdio \
  --env KAGGLE_USERNAME=your_user --env KAGGLE_KEY=your_key \
  kaggle -- uvx --from safe-kaggle-mcp kaggle-mcp
claude mcp list      # expect: kaggle  ✓ Connected
```

**Claude Desktop** — edit `claude_desktop_config.json`, then fully restart:
```json
{ "mcpServers": { "kaggle": {
  "command": "uvx", "args": ["--from", "safe-kaggle-mcp", "kaggle-mcp"],
  "env": { "KAGGLE_USERNAME": "your_user", "KAGGLE_KEY": "your_key" } } } }
```

## Safety switches (default OFF → read-only/private posture)

| Env var | Default | Effect when `1` |
|---|---|---|
| `KAGGLE_MCP_ENABLE_DESTRUCTIVE` | `0` | Exposes `kaggle_delete_dataset` / `kaggle_delete_model` |
| `KAGGLE_MCP_ENABLE_PUBLISH` | `0` | Allows creating **public** datasets |
| `KAGGLE_MCP_SUBMISSION_CAP` | `5` | Per-competition daily submission budget |

Even when enabled, each destructive call still requires a one-time `confirm_token` from its `*_preview_*` tool.

## Tools

30 curated tools (26 core + 4 `*_preview_*` confirm-token issuers) across **account, competitions,
datasets, kernels, models** — plus `kaggle://` resources (metadata, leaderboard, rules) and
`/kaggle-eda`, `/kaggle-submit-checklist`, `/kaggle-landscape`, `/kaggle-solution-research` prompts.
Run `kaggle_status` to see your auth + submission budget.

## Develop

```bash
uv run pytest                 # unit + smoke tests (no network)
uv run mcp dev src/kaggle_mcp/server.py   # MCP Inspector
```

## License

MIT

# kaggle-mcp

A **safety-first** [Model Context Protocol](https://modelcontextprotocol.io) server that connects Claude (Desktop / Code) to [Kaggle](https://www.kaggle.com) — competitions, datasets, kernels (notebooks), and models.

Unlike a thin API mirror, this server adds the guardrails an autonomous agent needs:

- **Two-call confirm tokens** for every irreversible action (submit / delete / public-publish).
- **Per-session submission budget** so an iterating agent can't burn the ~5/day competition quota.
- **Private-by-default** creation — saving artifacts can never make data public as a side effect.
- **Prompt-injection hardening** — all Kaggle-sourced text is wrapped in `<untrusted-content>` boundaries.
- **Zip-slip-safe** downloads confined to a sandbox work dir.
- **Credential redaction** across every tool output and log line.

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

**Claude Code:**
```bash
claude mcp add --transport stdio \
  --env KAGGLE_USERNAME=your_user --env KAGGLE_KEY=your_key \
  kaggle -- uvx kaggle-mcp
claude mcp list      # expect: kaggle  ✓ Connected
```

**Claude Desktop** — edit `claude_desktop_config.json`, then fully restart:
```json
{ "mcpServers": { "kaggle": {
  "command": "uvx", "args": ["kaggle-mcp"],
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

26 curated tools across **account, competitions, datasets, kernels, models** — plus `kaggle://` resources
(metadata, leaderboard, rules) and `/kaggle-eda`, `/kaggle-submit-checklist`, `/kaggle-landscape`,
`/kaggle-solution-research` prompts. Run `kaggle_status` to see your auth + submission budget.

## Develop

```bash
uv run pytest                 # unit + smoke tests (no network)
uv run mcp dev src/kaggle_mcp/server.py   # MCP Inspector
```

## License

MIT

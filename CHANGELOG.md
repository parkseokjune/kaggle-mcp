# Changelog

All notable changes to **safe-kaggle-mcp** are documented here.
This project adheres to [Semantic Versioning](https://semver.org/).

## [0.4.2]
### Fixed
- The server no longer hard-exits when no Kaggle credentials are configured — it starts, serves tool discovery (`list_tools`), and auth-required tools return a clean error at call time. This unblocks registry/Smithery tool scanning and honors the "tool listing works without credentials" contract.
### Added
- Smithery listing enriched: the MCPB manifest now declares all 41 tools (name, description, inputSchema) and a rich long description.

## [0.4.1]
### Added
- MCP Registry support: `server.json` manifest, `<!-- mcp-name: io.github.parkseokjune/kaggle-mcp -->` PyPI-ownership marker in the README, and a `publish-mcp.yml` GitHub Action that publishes to registry.modelcontextprotocol.io headlessly via OIDC on every `v*` tag.
- `safe-kaggle-mcp` console-script alias so `uvx safe-kaggle-mcp` works directly (matches the registry's default pypi runtime).
- `glama.json` + `smithery.yaml` for Glama and Smithery listings.

## [0.4.0]
### Added
- `kaggle_search_writeups` — search competition solution write-ups (the highest-signal strategy source), untrusted-fenced.
- `kaggle_competition_kickoff` — one call: metric/deadline/rules → data download (graceful "accept rules first" on 403) → train/test EDA with target auto-detection → baseline plan + remaining submission budget.
- GitHub Actions CI (pytest + build across Python 3.10–3.12).
### Notes
- Benchmarks deliberately **not** added: the public `kaggle` 2.2.2 client exposes no clean benchmark-listing method, and we don't ship dishonest stubs.

## [0.3.0]
### Added
- `kaggle_search_discussions` / `kaggle_get_discussion` — read-only forum digest. Every message body is fenced as `<untrusted-content>` (forums are the prime prompt-injection vector). No post/reply/vote — the API has none.

## [0.2.0]
### Added
- `kaggle_eda_competition` (train/test schema diff + target auto-detect), `kaggle_competition_landscape` (deadline-sorted triage), `kaggle_submission_best_score` (metric-aware best/trend/failures), `kaggle_dataset_preview` (capped, untrusted-fenced rows), `kaggle_leaderboard_track` (local snapshot rank deltas), `kaggle_audit_log` (redacted ledger of mutating actions), `kaggle_eda_dataset`.
### Changed
- README rewritten to lead with an honest feature comparison vs community and official/managed Kaggle MCPs, plus a "what it won't do" section.

## [0.1.0]
### Added
- Initial release: 30-tool safety-first Kaggle MCP on FastMCP (stdio). Two-call confirm-token gating for submit/delete/publish, per-competition submission budget, private-by-default, prompt-injection `<untrusted-content>` wrapping, zip-slip-safe downloads, credential redaction, dual auth (legacy username/key + `KGAT_` token). Verified live against `kaggle` 2.2.2.

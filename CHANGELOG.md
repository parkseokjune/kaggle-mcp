# Changelog

All notable changes to **safe-kaggle-mcp** are documented here.
This project adheres to [Semantic Versioning](https://semver.org/).

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

"""Central configuration: limits, safety switches, and paths.

All values are read from the environment once at import time so the rest of the
server can import plain constants. Safety switches default to the *safe* posture
(read-only, private-only) and must be explicitly turned on by the operator.
"""

from __future__ import annotations

import os
from pathlib import Path

# --- Output discipline (keep tool results small for the LLM context) ---
CHARACTER_LIMIT = 25_000          # hard cap on any single tool's text output
UNTRUSTED_TEXT_LIMIT = 4_000      # truncate Kaggle-sourced free text to this
DATASET_PAGE_SIZE = 10            # default search results returned
LIST_PAGE_SIZE = 20              # default for list endpoints
LEADERBOARD_TOP_N = 20           # default leaderboard rows

# --- Rate-limit backoff (429 handling) ---
BACKOFF_INITIAL_S = 2
BACKOFF_MAX_S = 30
BACKOFF_ATTEMPTS = 5

# --- Submission budget (per competition, per server session) ---
SUBMISSION_CAP = int(os.environ.get("KAGGLE_MCP_SUBMISSION_CAP", "5"))

# --- Safety switches (default OFF) ---
ENABLE_DESTRUCTIVE = os.environ.get("KAGGLE_MCP_ENABLE_DESTRUCTIVE", "0") == "1"
ENABLE_PUBLISH = os.environ.get("KAGGLE_MCP_ENABLE_PUBLISH", "0") == "1"


def work_root() -> Path:
    """Sandbox root for all downloads/extractions.

    Resolved lazily so tests can override KAGGLE_MCP_WORKDIR at runtime.
    """
    root = Path(
        os.environ.get("KAGGLE_MCP_WORKDIR")
        or (Path.home() / ".kaggle-mcp-work")
    )
    root.mkdir(parents=True, exist_ok=True)
    return root

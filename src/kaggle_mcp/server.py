"""L1 — MCP transport. Wires primitives onto a FastMCP instance and runs it.

CRITICAL (stdio): stdout carries JSON-RPC. ALL logging goes to stderr; a single
stray write to stdout corrupts the protocol stream. A redaction filter scrubs any
40-hex credential pattern from log records as defense in depth.
"""

from __future__ import annotations

import logging
import os
import sys

from mcp.server.fastmcp import FastMCP

from . import auth
from .prompts import register_prompts
from .resources import register_resources
from .safety import redact
from .tools import register_all_tools


class _RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = redact(str(record.getMessage()))
            record.args = ()
        except Exception:  # pragma: no cover - never let logging crash the server
            pass
        return True


def _setup_logging() -> None:
    handler = logging.StreamHandler(stream=sys.stderr)  # NEVER stdout
    handler.addFilter(_RedactionFilter())
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)


_INSTRUCTIONS = (
    "Safety-first Kaggle MCP (41 tools) for competitions, datasets, kernels, models, "
    "and discussions. Every irreversible action (submit/delete/publish) is gated behind "
    "a two-call preview->confirm token; submissions are budgeted per competition; "
    "creation is private by default; all Kaggle-returned text is fenced as untrusted "
    "content; credentials never enter the model context. Highlights: kaggle_competition_"
    "kickoff (one-call setup+EDA+plan), kaggle_eda_dataset/_competition (compact pandas "
    "digests), kaggle_competition_landscape, kaggle_leaderboard_track, kaggle_search_"
    "writeups, kaggle_audit_log. Set KAGGLE_API_TOKEN (or KAGGLE_USERNAME/KAGGLE_KEY) for "
    "authenticated actions; tool listing works without credentials."
)

mcp = FastMCP("Kaggle", instructions=_INSTRUCTIONS)
register_all_tools(mcp)
register_resources(mcp)
register_prompts(mcp)


def main() -> None:
    _setup_logging()
    log = logging.getLogger("kaggle-mcp")
    try:
        auth.validate_credentials()
    except auth.CredentialError as e:
        # Start anyway: tool discovery (list_tools) and the registry/Smithery scan
        # must work without credentials, and auth-required tools surface a clean
        # error at call time. A hard exit here breaks discovery and contradicts the
        # "read-only / tool listing works without credentials" contract.
        log.warning("No Kaggle credentials configured: %s. Server starting; "
                    "auth-required tools will return an error until credentials are set.", e)

    transport = os.environ.get("KAGGLE_MCP_TRANSPORT", "stdio")
    log.info("Starting Kaggle MCP server (transport=%s)", transport)
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()

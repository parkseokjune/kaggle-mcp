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


mcp = FastMCP("Kaggle")
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

"""Tool registration. Each resource group registers its own tools onto the shared
FastMCP instance. A small helper standardizes error envelopes (errors are returned
in-result so the model can see and recover, with secrets redacted).
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ..safety import redact


def anno(title: str, *, read_only: bool = False, destructive: bool = False,
         idempotent: bool | None = None, open_world: bool = True) -> ToolAnnotations:
    """Build accurate (advisory) tool annotations. NOT the security boundary."""
    return ToolAnnotations(
        title=title,
        readOnlyHint=read_only,
        destructiveHint=destructive,
        idempotentHint=idempotent,
        openWorldHint=open_world,
    )


def error(exc: Exception) -> dict[str, Any]:
    """Standard in-result error envelope with credential redaction."""
    return {"isError": True, "error": redact(str(exc))}


def register_all_tools(mcp: FastMCP) -> None:
    from . import account, competitions, datasets, kernels, models

    account.register(mcp)
    competitions.register(mcp)
    datasets.register(mcp)
    kernels.register(mcp)
    models.register(mcp)

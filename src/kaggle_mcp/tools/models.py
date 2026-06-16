"""Model tools: read-leaning (list/get/download). Delete is flag-gated."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from .. import config, formatting, kaggle_client as kc
from ..safety import consume_token, issue_token, require_destructive_enabled, wrap_untrusted
from . import anno, error

# ApiModel (kaggle >=2.x) exposes vote_count but not download_count.
_M_FIELDS = ["ref", "title", "subtitle", "author", "vote_count"]


def register(mcp: FastMCP) -> None:
    @mcp.tool(annotations=anno("List models", read_only=True))
    async def kaggle_list_models(
        search: str = "", owner: str = "", sort_by: str = "",
        page: int = 1, page_size: int = config.LIST_PAGE_SIZE,
    ) -> dict[str, Any]:
        """List/search published models as a compact table. Paginated. Read-only."""
        try:
            raw = await kc.call("model_list", search=search or None, owner=owner or None,
                                sort_by=sort_by or None, page_size=page_size)
        except Exception as e:  # noqa: BLE001
            return error(e)
        items = getattr(raw, "models", raw) or []
        rows = [formatting.obj_to_dict(m, _M_FIELDS) for m in formatting.cap_list(items, page_size)]
        env = formatting.paginated(rows, page, page_size)
        env["markdown"] = formatting.markdown_table(rows, ["ref", "title", "subtitle", "vote_count"])
        return env

    @mcp.tool(annotations=anno("Get model", read_only=True))
    async def kaggle_get_model(model: str) -> dict[str, Any]:
        """Fetch a model's metadata and instances/variations. `model` is 'owner/slug'.
        Description is untrusted-wrapped. Read-only."""
        try:
            raw = await kc.call("model_get", model)
        except Exception as e:  # noqa: BLE001
            return error(e)
        out: dict[str, Any] = {"ref": model, "title": getattr(raw, "title", None),
                               "url": f"https://www.kaggle.com/models/{model}"}
        desc = getattr(raw, "description", None)
        if desc:
            out["description"] = wrap_untrusted(desc)
        return out

    @mcp.tool(annotations=anno("Download model version", destructive=False))
    async def kaggle_download_model(model_version: str) -> dict[str, Any]:
        """Download a specific model instance version's artifacts into a work dir.
        `model_version` is 'owner/model/framework/variation/version'. Returns paths."""
        workdir = kc.new_workdir(prefix="model-")
        try:
            await kc.call("model_instance_version_download", model_version, path=str(workdir))
        except Exception as e:  # noqa: BLE001
            return error(e)
        for z in workdir.glob("*.zip"):
            try:
                kc.safe_extract(z, workdir)
                z.unlink()
            except ValueError as e:
                return error(e)
        return {"ref": model_version, "localDir": str(workdir), "files": kc.list_files(workdir)}

    @mcp.tool(annotations=anno("Delete model", destructive=True, idempotent=False))
    async def kaggle_delete_model(model: str, confirm_token: str) -> dict[str, Any]:
        """Delete a model — IRREVERSIBLE. Disabled unless KAGGLE_MCP_ENABLE_DESTRUCTIVE=1,
        and requires a confirm_token from kaggle_preview_delete_model."""
        try:
            require_destructive_enabled()
        except Exception as e:  # noqa: BLE001
            return error(e)
        if not consume_token(confirm_token, f"delete-model|{model}"):
            return {"isError": True, "error": "delete requires a valid confirm_token from kaggle_preview_delete_model"}
        try:
            await kc.call("model_delete", model, no_confirm=True)
        except Exception as e:  # noqa: BLE001
            return error(e)
        return {"ref": model, "deleted": True}

    @mcp.tool(annotations=anno("Preview model delete", read_only=True, open_world=False))
    def kaggle_preview_delete_model(model: str) -> dict[str, Any]:
        """Issue a confirm_token for an irreversible model delete. No side effects."""
        return {"ref": model, "irreversible": True,
                "confirm_token": issue_token(f"delete-model|{model}"),
                "warning": "This permanently removes the model and all its versions."}

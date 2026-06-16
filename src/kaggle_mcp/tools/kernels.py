"""Kernel (notebook) tools: list/pull/push/status/output. Push uses Kaggle's free
GPU/TPU as a remote execution backend; private by default."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from .. import config, formatting, kaggle_client as kc
from ..safety import wrap_untrusted
from . import anno, error

# ApiKernelMetadata (kaggle >=2.x) snake_case fields.
_K_FIELDS = ["ref", "title", "author", "language", "kernel_type", "last_run_time", "total_votes"]


def register(mcp: FastMCP) -> None:
    @mcp.tool(annotations=anno("List kernels", read_only=True))
    async def kaggle_list_kernels(
        search: str = "", mine: bool = False, language: str = "", kernel_type: str = "",
        sort_by: str = "", page: int = 1, page_size: int = config.LIST_PAGE_SIZE,
    ) -> dict[str, Any]:
        """List/search notebooks (kernels) as a compact table. Paginated. Read-only."""
        try:
            raw = await kc.call("kernels_list", search=search or None,
                                mine=mine, language=language or None,
                                kernel_type=kernel_type or None, sort_by=sort_by or None, page=page)
        except Exception as e:  # noqa: BLE001
            return error(e)
        rows = [formatting.obj_to_dict(k, _K_FIELDS) for k in formatting.cap_list(raw or [], page_size)]
        env = formatting.paginated(rows, page, page_size)
        env["markdown"] = formatting.markdown_table(rows, ["ref", "title", "language", "kernel_type"])
        return env

    @mcp.tool(annotations=anno("Pull kernel source", destructive=False))
    async def kaggle_pull_kernel(kernel: str, with_metadata: bool = False) -> dict[str, Any]:
        """Pull a kernel's source (and optionally metadata) into a local work dir.
        Source code is untrusted-wrapped and truncated. `kernel` is 'owner/slug'."""
        workdir = kc.new_workdir(prefix="kern-")
        try:
            await kc.call("kernels_pull", kernel, path=str(workdir), metadata=with_metadata)
        except Exception as e:  # noqa: BLE001
            return error(e)
        files = kc.list_files(workdir)
        source = ""
        for f in files:
            if f["name"].endswith((".py", ".ipynb", ".r", ".R")):
                try:
                    source = open(f["path"], encoding="utf-8", errors="replace").read()
                except OSError:
                    source = ""
                break
        return {"ref": kernel, "localDir": str(workdir), "files": files,
                "source": wrap_untrusted(source) if source else None}

    @mcp.tool(annotations=anno("Push kernel (run on Kaggle)", destructive=False, idempotent=False))
    async def kaggle_push_kernel(folder: str) -> dict[str, Any]:
        """Push (create/update AND queue-run) a notebook from a local folder, using
        Kaggle's free GPU/TPU. Requires a valid kernel-metadata.json. PRIVATE by
        default (set is_private:true in metadata). Async — poll kaggle_kernel_status."""
        try:
            result = await kc.call("kernels_push", folder)
        except Exception as e:  # noqa: BLE001
            return error(e)
        return {"folder": folder, "status": "queued",
                "ref": getattr(result, "ref", None),
                "note": "Poll kaggle_kernel_status, then kaggle_kernel_output."}

    @mcp.tool(annotations=anno("Kernel run status", read_only=True))
    async def kaggle_kernel_status(kernel: str) -> dict[str, Any]:
        """Poll a kernel run's status (running|complete|error|cancelAcknowledged)."""
        try:
            status = await kc.call("kernels_status", kernel)
        except Exception as e:  # noqa: BLE001
            return error(e)
        return {"ref": kernel, "status": str(getattr(status, "status", status))}

    @mcp.tool(annotations=anno("Download kernel output", destructive=False))
    async def kaggle_kernel_output(kernel: str, file_pattern: str = "") -> dict[str, Any]:
        """Download a completed kernel's output files and logs into a local work dir.
        Log tail is untrusted-wrapped and truncated. Read-only fetch."""
        workdir = kc.new_workdir(prefix="kout-")
        try:
            await kc.call("kernels_output", kernel, path=str(workdir), file_pattern=file_pattern or None)
        except Exception as e:  # noqa: BLE001
            return error(e)
        files = kc.list_files(workdir)
        log_tail = ""
        for f in files:
            if f["name"].endswith(".log") or "log" in f["name"].lower():
                try:
                    log_tail = open(f["path"], encoding="utf-8", errors="replace").read()[-4000:]
                except OSError:
                    log_tail = ""
                break
        return {"ref": kernel, "localDir": str(workdir), "files": files,
                "logTail": wrap_untrusted(log_tail) if log_tail else None}

"""Dataset tools: search/metadata/download (safe), create/version (private-by-default),
status, and a flag-gated delete."""

from __future__ import annotations

import asyncio
from typing import Any

from mcp.server.fastmcp import FastMCP

from .. import config, eda, formatting, kaggle_client as kc
from ..safety import (
    append_ledger, consume_token, issue_token, require_destructive_enabled,
    require_publish_enabled, wrap_untrusted,
)
from . import anno, error

# Snake_case fields per the installed kaggle (>=2.x, kagglesdk) ApiDataset.
_DS_FIELDS = ["ref", "title", "subtitle", "download_count", "vote_count", "last_updated",
              "usability_rating", "total_bytes"]


def register(mcp: FastMCP) -> None:
    @mcp.tool(annotations=anno("Search datasets", read_only=True))
    async def kaggle_search_datasets(
        search: str, sort_by: str = "hottest", file_type: str = "",
        page: int = 1, page_size: int = config.DATASET_PAGE_SIZE,
    ) -> dict[str, Any]:
        """Search datasets; return top ~10 as a compact ranked table (ref, title,
        downloads, updated, usability) — not raw JSON. Paginated."""
        try:
            raw = await kc.call("dataset_list", search=search, sort_by=sort_by or None,
                                file_type=file_type or None, page=page)
        except Exception as e:  # noqa: BLE001
            return error(e)
        rows = [formatting.obj_to_dict(d, _DS_FIELDS) for d in formatting.cap_list(raw or [], page_size)]
        env = formatting.paginated(rows, page, page_size)
        env["markdown"] = formatting.markdown_table(rows, ["ref", "title", "download_count", "last_updated", "usability_rating"])
        return env

    @mcp.tool(annotations=anno("Get dataset metadata", read_only=True))
    async def kaggle_get_dataset_metadata(dataset: str) -> dict[str, Any]:
        """Fetch a dataset's metadata + file listing. `dataset` is 'owner/slug'.
        Description text is untrusted-wrapped and truncated. Read-only."""
        try:
            files = await kc.call("dataset_list_files", dataset)
        except Exception as e:  # noqa: BLE001
            return error(e)
        file_list = getattr(files, "files", None) or getattr(files, "dataset_files", None) or []
        file_rows = [
            {"name": getattr(f, "name", getattr(f, "ref", None)),
             "sizeMB": round((getattr(f, "total_bytes", 0) or 0) / 1e6, 3)}
            for f in file_list
        ]
        out: dict[str, Any] = {"ref": dataset, "url": f"https://www.kaggle.com/datasets/{dataset}", "files": file_rows}
        desc = getattr(files, "description", None)
        if desc:
            out["description"] = wrap_untrusted(desc)
        return out

    @mcp.tool(annotations=anno("Download dataset", destructive=False))
    async def kaggle_download_dataset(dataset: str, file: str = "", unzip: bool = True) -> dict[str, Any]:
        """Download a dataset (or single file) into an isolated work dir; zip
        auto-extracted with a zip-slip guard. Returns local paths + metadata."""
        workdir = kc.new_workdir(prefix="ds-")
        try:
            if file:
                await kc.call("dataset_download_file", dataset, file, path=str(workdir))
            else:
                await kc.call("dataset_download_files", dataset, path=str(workdir), unzip=unzip)
        except Exception as e:  # noqa: BLE001
            return error(e)
        if unzip:
            for z in workdir.glob("*.zip"):
                try:
                    kc.safe_extract(z, workdir)
                    z.unlink()
                except ValueError as e:
                    return error(e)
        return {"ref": dataset, "localDir": str(workdir), "files": kc.list_files(workdir)}

    @mcp.tool(annotations=anno("EDA a dataset (compact local summary)", destructive=False))
    async def kaggle_eda_dataset(dataset: str, file: str = "", target: str = "", max_files: int = 5) -> dict[str, Any]:
        """Download a dataset and return a COMPACT exploratory summary — shape,
        dtypes, missingness, target distribution, and top numeric correlations —
        computed locally with pandas. Never streams raw rows into context. This is
        the 'find data -> understand it' primitive that most Kaggle MCP servers
        lack (they dump raw files or just emit a prompt). `dataset` is 'owner/slug'."""
        workdir = kc.new_workdir(prefix="eda-")
        try:
            await kc.call("dataset_download_files", dataset, path=str(workdir), unzip=True)
        except Exception as e:  # noqa: BLE001
            return error(e)
        for z in workdir.glob("*.zip"):
            try:
                kc.safe_extract(z, workdir)
                z.unlink()
            except ValueError as e:
                return error(e)
        try:
            if file:
                path = workdir / file
                if not path.exists():
                    return {"isError": True, "error": f"file not found in dataset: {file}"}
                summary = await asyncio.to_thread(eda.summarize_csv, path, target or None)
                return {"ref": dataset, "file": file, "eda": summary}
            summary = await asyncio.to_thread(eda.summarize_dir, workdir, target or None, max_files)
            return {"ref": dataset, "eda": summary}
        except Exception as e:  # noqa: BLE001 - surface EDA errors cleanly
            return error(e)

    @mcp.tool(annotations=anno("Preview dataset rows (capped)", destructive=False))
    async def kaggle_dataset_preview(dataset: str, file: str = "", n: int = 5) -> dict[str, Any]:
        """Safe first-N-rows preview of a dataset CSV — headers, dtypes, and up to
        `n` (<=50) width-capped rows, wrapped as untrusted content. 'What does the
        data look like?' without dumping the whole file or unbounded rows."""
        workdir = kc.new_workdir(prefix="prev-")
        try:
            if file:
                await kc.call("dataset_download_file", dataset, file, path=str(workdir))
            else:
                await kc.call("dataset_download_files", dataset, path=str(workdir), unzip=True)
        except Exception as e:  # noqa: BLE001
            return error(e)
        for z in workdir.glob("*.zip"):
            try:
                kc.safe_extract(z, workdir)
                z.unlink()
            except ValueError as e:
                return error(e)
        csv = (workdir / file) if file else next(iter(workdir.rglob("*.csv")), None)
        if not csv or not csv.exists():
            return {"isError": True, "error": "no CSV found to preview"}
        try:
            prev = await asyncio.to_thread(eda.preview_csv, csv, n)
        except Exception as e:  # noqa: BLE001
            return error(e)
        return {"ref": dataset, "file": csv.name, "columns": prev["columns"],
                "dtypes": prev["dtypes"], "rows_shown": prev["rows_shown"],
                "preview": wrap_untrusted(str(prev["rows"]))}

    @mcp.tool(annotations=anno("Create dataset (private)", destructive=False))
    async def kaggle_create_dataset(folder: str, public: bool = False, confirm_token: str = "") -> dict[str, Any]:
        """Create a NEW dataset from a local folder. PRIVATE by default. Making it
        public requires KAGGLE_MCP_ENABLE_PUBLISH=1 AND a confirm_token from a
        preview. Async — returns 'queued'; poll kaggle_dataset_status. The folder
        must contain a valid dataset-metadata.json (id, title, licenses)."""
        if public:
            try:
                require_publish_enabled()
            except Exception as e:  # noqa: BLE001
                return error(e)
            if not consume_token(confirm_token, f"create-public|{folder}"):
                return {"isError": True, "error": "public publish requires a valid confirm_token (preview first)"}
        try:
            await kc.call("dataset_create_new", folder=folder, public=public)
        except Exception as e:  # noqa: BLE001
            return error(e)
        vis = "public" if public else "private"
        append_ledger("create_dataset", folder, extra={"visibility": vis})
        return {"folder": folder, "visibility": vis,
                "status": "queued", "note": "Poll kaggle_dataset_status until ready."}

    @mcp.tool(annotations=anno("Preview public dataset publish", read_only=True, open_world=False))
    def kaggle_preview_publish_dataset(folder: str) -> dict[str, Any]:
        """Issue a confirm_token to publish a dataset publicly. Surfaces that the
        data WILL become world-visible. No side effects."""
        return {"folder": folder, "becomesPublic": True,
                "confirm_token": issue_token(f"create-public|{folder}"),
                "warning": "This will make the dataset visible to everyone on Kaggle."}

    @mcp.tool(annotations=anno("Version dataset", destructive=False, idempotent=False))
    async def kaggle_version_dataset(folder: str, version_notes: str, delete_old_versions: bool = False) -> dict[str, Any]:
        """Push a new version/revision of an existing dataset from a local folder
        (persists engineered features across runs). Async; non-destructive (adds a version)."""
        try:
            await kc.call("dataset_create_version", folder, version_notes, delete_old_versions=delete_old_versions)
        except Exception as e:  # noqa: BLE001
            return error(e)
        append_ledger("version_dataset", folder, extra={"notes": version_notes})
        return {"folder": folder, "status": "queued", "versionNotes": version_notes}

    @mcp.tool(annotations=anno("Dataset status", read_only=True))
    async def kaggle_dataset_status(dataset: str) -> dict[str, Any]:
        """Poll the processing status of a dataset create/version op. Read-only."""
        try:
            status = await kc.call("dataset_status", dataset)
        except Exception as e:  # noqa: BLE001
            return error(e)
        return {"ref": dataset, "status": str(status)}

    @mcp.tool(annotations=anno("Delete dataset", destructive=True, idempotent=False))
    async def kaggle_delete_dataset(dataset: str, confirm_token: str) -> dict[str, Any]:
        """Delete a dataset and ALL its versions — IRREVERSIBLE. Disabled unless the
        server was started with KAGGLE_MCP_ENABLE_DESTRUCTIVE=1, AND requires a
        confirm_token. Never defaults to yes."""
        try:
            require_destructive_enabled()
        except Exception as e:  # noqa: BLE001
            return error(e)
        if not consume_token(confirm_token, f"delete-dataset|{dataset}"):
            return {"isError": True, "error": "delete requires a valid confirm_token from kaggle_preview_delete_dataset"}
        if "/" not in dataset:
            return {"isError": True, "error": "dataset must be 'owner/slug'"}
        owner, slug = dataset.split("/", 1)
        try:
            await kc.call("dataset_delete", owner, slug, no_confirm=True)
        except Exception as e:  # noqa: BLE001
            return error(e)
        append_ledger("delete_dataset", dataset)
        return {"ref": dataset, "deleted": True}

    @mcp.tool(annotations=anno("Preview dataset delete", read_only=True, open_world=False))
    def kaggle_preview_delete_dataset(dataset: str) -> dict[str, Any]:
        """Issue a confirm_token for an irreversible dataset delete. No side effects."""
        return {"ref": dataset, "irreversible": True,
                "confirm_token": issue_token(f"delete-dataset|{dataset}"),
                "warning": "This permanently removes the dataset and ALL versions."}

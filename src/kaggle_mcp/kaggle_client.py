"""The single chokepoint to Kaggle.

- Lazily builds ONE authenticated KaggleApi instance (singleton), reused across calls.
- Runs the synchronous, blocking client off the event loop via asyncio.to_thread.
- Forces quiet=True so the client never prints to stdout (which carries JSON-RPC).
- Retries 429s with exponential backoff + jitter.
- Maps ApiException status codes to clean, typed errors.
- Confines downloads/extraction to a per-request sandbox dir with a zip-slip guard.

This module has ZERO mcp imports so it is fully unit-testable with a mocked client.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Callable

from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from . import config

log = logging.getLogger("kaggle-mcp.client")

_api = None  # KaggleApi singleton


# --- Typed errors -------------------------------------------------------------


class KaggleClientError(RuntimeError):
    """Base for mapped Kaggle errors. Message is safe to surface to the model."""


class RulesNotAccepted(KaggleClientError):
    pass


class NotFound(KaggleClientError):
    pass


class RateLimited(KaggleClientError):
    pass


# --- Singleton ----------------------------------------------------------------


def get_api():
    """Construct and authenticate the KaggleApi once. Import is local so that a
    missing/invalid credential only fails here, not at module import time."""
    global _api
    if _api is None:
        from kaggle.api.kaggle_api_extended import KaggleApi  # local import on purpose

        api = KaggleApi()
        api.authenticate()
        _api = api
        log.info("KaggleApi authenticated")
    return _api


def reset_api_for_tests(fake: Any | None = None) -> None:
    """Test hook: inject a fake KaggleApi (or None to clear)."""
    global _api
    _api = fake


# --- 429 backoff --------------------------------------------------------------


def _status_of(exc: BaseException) -> int | None:
    return getattr(exc, "status", None)


def _is_429(exc: BaseException) -> bool:
    return _status_of(exc) == 429


_retry_429 = retry(
    retry=retry_if_exception(_is_429),
    wait=wait_exponential_jitter(initial=config.BACKOFF_INITIAL_S, max=config.BACKOFF_MAX_S),
    stop=stop_after_attempt(config.BACKOFF_ATTEMPTS),
    reraise=True,
)


def _map_exception(exc: BaseException) -> BaseException:
    status = _status_of(exc)
    if status == 403:
        return RulesNotAccepted(
            "403 from Kaggle — you likely must accept the competition's rules in the "
            "browser first, or you lack access to this resource."
        )
    if status == 404:
        return NotFound("404 from Kaggle — resource not found. Check the ref/slug format.")
    if status == 429:
        return RateLimited("429 from Kaggle — rate limited after retries. Back off and try later.")
    return exc


@_retry_429
def _invoke(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    return fn(*args, **kwargs)


async def call(method_name: str, *args: Any, **kwargs: Any) -> Any:
    """Call a KaggleApi method by name, off the event loop, with quiet + backoff.

    Raises a mapped KaggleClientError subclass on known status codes.
    """
    api = get_api()
    fn = getattr(api, method_name)
    kwargs.setdefault("quiet", True)

    def _run() -> Any:
        try:
            return _invoke(fn, *args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - map then re-raise
            mapped = _map_exception(exc)
            if mapped is not exc:
                raise mapped from exc
            raise

    return await asyncio.to_thread(_run)


# --- Sandbox + safe extraction ------------------------------------------------


def new_workdir(prefix: str = "req-") -> Path:
    """Create an isolated per-request working directory under the sandbox root."""
    return Path(tempfile.mkdtemp(prefix=prefix, dir=config.work_root()))


def safe_extract(zip_path: Path, dest: Path) -> list[str]:
    """Extract a zip, rejecting any entry that escapes `dest` (zip-slip guard)."""
    dest = dest.resolve()
    extracted: list[str] = []
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.namelist():
            target = (dest / member).resolve()
            if target != dest and dest not in target.parents:
                raise ValueError(f"Unsafe path in archive (zip-slip blocked): {member!r}")
        zf.extractall(dest)
        extracted = zf.namelist()
    return extracted


def list_files(directory: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in sorted(directory.rglob("*")):
        if p.is_file():
            out.append({
                "name": str(p.relative_to(directory)),
                "sizeMB": round(p.stat().st_size / 1e6, 3),
                "path": str(p),
            })
    return out

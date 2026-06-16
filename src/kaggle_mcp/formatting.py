"""Output discipline: convert Kaggle SDK objects to plain dicts, cap lists,
truncate large text, and render compact Markdown tables. Keeps tool results
small and decision-ready instead of dumping raw API JSON.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from . import config


def _coerce(v: Any) -> Any:
    """Make a value JSON-safe: datetimes, enums, etc. -> str."""
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    return str(v)


def obj_to_dict(obj: Any, fields: Sequence[str]) -> dict[str, Any]:
    """Pull a known set of attributes off an SDK model into a plain dict.

    Uses getattr defensively (missing attrs become None) and coerces non-scalar
    values (datetime, enums) to strings so the result is always JSON-serializable.
    """
    if isinstance(obj, dict):
        return {f: _coerce(obj.get(f)) for f in fields}
    return {f: _coerce(getattr(obj, f, None)) for f in fields}


def cap_list(items: Iterable[Any], limit: int) -> list[Any]:
    out = list(items)
    return out[:limit]


def truncate_text(text: str, limit: int = config.CHARACTER_LIMIT) -> str:
    if text is None:
        return ""
    if len(text) > limit:
        return text[:limit] + f"\n...(truncated, {len(text) - limit} more chars; narrow your query)"
    return text


def markdown_table(rows: list[dict[str, Any]], columns: Sequence[str]) -> str:
    """Render a list of dicts as a compact GitHub-flavored Markdown table."""
    if not rows:
        return "_(no results)_"
    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    body = []
    for r in rows:
        cells = []
        for c in columns:
            v = r.get(c, "")
            cells.append("" if v is None else str(v).replace("|", "\\|").replace("\n", " "))
        body.append("| " + " | ".join(cells) + " |")
    return truncate_text("\n".join([header, sep, *body]))


def paginated(results: list[Any], page: int, page_size: int, total: int | None = None) -> dict[str, Any]:
    """Standard pagination envelope returned by list/search tools."""
    has_more = len(results) >= page_size if total is None else (page * page_size) < total
    return {
        "page": page,
        "page_size": page_size,
        "count": len(results),
        "total": total,
        "has_more": has_more,
        "next_page": page + 1 if has_more else None,
        "results": results,
    }

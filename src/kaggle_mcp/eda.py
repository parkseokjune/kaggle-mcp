"""Local EDA: return a COMPACT summary of a CSV, never raw rows into context.

Used by datasets tools and the /kaggle-eda prompt. Keeps dataframes on disk and
emits only shape, dtypes, missingness, and (optionally) target distribution.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def summarize_csv(path: str | Path, target: str | None = None, max_cols: int = 40) -> dict[str, Any]:
    import pandas as pd  # local import; pandas is heavy

    df = pd.read_csv(path)
    n_rows, n_cols = df.shape
    cols = list(df.columns)[:max_cols]

    dtypes = {c: str(df[c].dtype) for c in cols}
    missing = {c: int(df[c].isna().sum()) for c in cols}
    missing_pct = {c: round(100 * missing[c] / n_rows, 2) if n_rows else 0.0 for c in cols}

    summary: dict[str, Any] = {
        "shape": {"rows": int(n_rows), "cols": int(n_cols)},
        "columns_shown": len(cols),
        "dtypes": dtypes,
        "missing_count": missing,
        "missing_pct": missing_pct,
    }

    if target and target in df.columns:
        vc = df[target].value_counts(dropna=False).head(20)
        summary["target"] = {
            "name": target,
            "distribution": {str(k): int(v) for k, v in vc.items()},
        }

    # Top absolute correlations among numeric columns (compact, decision-ready).
    numeric = df[cols].select_dtypes(include="number")
    if numeric.shape[1] >= 2:
        corr = numeric.corr(numeric_only=True).abs()
        pairs = []
        seen = set()
        for a in corr.columns:
            for b in corr.columns:
                if a != b and (b, a) not in seen:
                    seen.add((a, b))
                    val = corr.loc[a, b]
                    if val == val:  # skip NaN
                        pairs.append((round(float(val), 3), a, b))
        pairs.sort(reverse=True)
        summary["top_correlations"] = [
            {"cols": [a, b], "abs_corr": v} for v, a, b in pairs[:8]
        ]

    return summary


def _trunc_cell(v: Any, max_cell: int) -> str:
    s = str(v)
    return s[:max_cell] + "…" if len(s) > max_cell else s


def preview_csv(path: str | Path, n: int = 5, max_cell: int = 60) -> dict[str, Any]:
    """First-N-rows preview with width-capped cells — 'what does the data look like?'

    Hard-capped (n<=50) and truncated; meant to be wrapped as untrusted content.
    """
    import pandas as pd

    n = max(1, min(n, 50))
    df = pd.read_csv(path, nrows=n)
    cols = list(df.columns)
    dtypes = {c: str(df[c].dtype) for c in cols}
    rows = [{c: _trunc_cell(r[c], max_cell) for c in cols} for _, r in df.iterrows()]
    return {"columns": cols, "dtypes": dtypes, "rows_shown": len(rows), "rows": rows}


def schema_diff(train_path: str | Path, test_path: str | Path) -> dict[str, Any]:
    """Compare a competition's train vs test columns and infer the target.

    The target is, by convention, the column(s) present in train but absent from
    test. Reads headers only (nrows=0), so it's cheap.
    """
    import pandas as pd

    train_cols = list(pd.read_csv(train_path, nrows=0).columns)
    test_cols = list(pd.read_csv(test_path, nrows=0).columns)
    train_only = [c for c in train_cols if c not in test_cols]
    # Drop obvious id columns from the target guess.
    candidates = [c for c in train_only if c.lower() not in {"id", "index"}]
    return {
        "train_columns": train_cols,
        "test_columns": test_cols,
        "train_only_columns": train_only,
        "inferred_target": candidates[-1] if candidates else (train_only[-1] if train_only else None),
    }


def summarize_dir(directory: str | Path, target: str | None = None, max_files: int = 5) -> dict[str, Any]:
    """Summarize every CSV in a directory (capped), returning per-file EDA summaries."""
    directory = Path(directory)
    csvs = sorted(directory.rglob("*.csv"))[:max_files]
    out: dict[str, Any] = {"csv_count": len(list(directory.rglob("*.csv"))), "summarized": []}
    for csv in csvs:
        try:
            out["summarized"].append({"file": csv.name, **summarize_csv(csv, target=target)})
        except Exception as e:  # noqa: BLE001 - one bad CSV shouldn't kill the rest
            out["summarized"].append({"file": csv.name, "error": str(e)})
    return out

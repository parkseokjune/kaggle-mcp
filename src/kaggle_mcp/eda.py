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

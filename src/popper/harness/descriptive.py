"""Role-free descriptive statistics of a table: structure, quality, distribution and design."""

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from popper.harness.research import Entry, ResearchContext
from popper.harness.results import validate_results

_LEVEL_LIMIT = 20
_PATTERN_LIMIT = 10
_NON_NUMERIC_TYPES = {"id", "text", "categorical"}
_COLUMN_KEY = re.compile(r"^c\d{3}_")


@dataclass
class DescriptiveReport:
    results: dict[str, dict[str, Any]]
    layout: dict[str, Any]


def read_table(path: Path) -> pd.DataFrame:
    """CSV values are read as strings so identifiers and codes are never reinterpreted."""
    if path.suffix == ".csv":
        return pd.read_csv(path, dtype=str, keep_default_na=False)
    return pd.read_parquet(path)


class _Builder:
    def __init__(self) -> None:
        self.results: dict[str, dict[str, Any]] = {}
        self.omitted: dict[str, str] = {}

    def put(self, key: str, value: Any, reason: str = "undefined") -> None:
        """Record a statistic; a missing or non-finite value is omitted with its reason."""
        if value is None or (isinstance(value, float | np.floating) and not math.isfinite(value)):
            self.omitted[key] = reason
        elif isinstance(value, str):
            self.results[key] = {"value": value}
        elif isinstance(value, float | np.floating):
            self.results[key] = {"value": float(value)}
        else:
            self.results[key] = {"value": int(value)}


def _declared[T](entry: Entry[T]) -> T | None:
    return entry.value if entry.status == "confirmed" else None


def _text(series: pd.Series, strip: bool = True) -> pd.Series:
    """Strings with blanks as missing, trimmed unless `strip` is false; a new series."""
    text = series.where(series.notna()).astype("string")
    text = text.mask(text.str.strip() == "")
    return text.str.strip() if strip else text


def _numbers(series: pd.Series) -> pd.Series:
    out = pd.to_numeric(series, errors="coerce").astype("float64")
    return out.where(np.isfinite(out))


def _column(
    b: _Builder,
    key: str,
    series: pd.Series,
    declared_type: str | None,
    bounds: list[float] | None,
    levels: list[str] | None,
    cluster: pd.Series | None,
) -> tuple[pd.Series, dict[str, Any]]:
    """Add one column's statistics; returns its missing mask and layout fragment."""
    fragment: dict[str, Any] = {}
    failed = 0
    if pd.api.types.is_numeric_dtype(series) or pd.api.types.is_bool_dtype(series):
        values = _numbers(series.astype("float64"))
        missing = values.isna()
        numeric = True
    else:
        text = _text(series)
        missing = text.isna()
        values = _numbers(text)
        present = int((~missing).sum())
        converted = int(values.notna().sum())
        numeric = (
            declared_type not in _NON_NUMERIC_TYPES and converted > 0 and converted * 2 >= present
        )
        failed = present - converted
    present_n = int((~missing).sum())
    n_rows = len(series)

    shown = values.dropna() if numeric else _text(series, strip=False).dropna()
    unique = int(shown.nunique())
    b.put(f"{key}_n_unique", unique)
    b.put(f"{key}_unique_share", unique / present_n if present_n else None, "no values")
    b.put(f"{key}_constant", int(present_n > 0 and unique <= 1))
    b.put(f"{key}_missing_count", int(missing.sum()))
    b.put(f"{key}_missing_share", int(missing.sum()) / n_rows if n_rows else None, "no rows")
    if cluster is not None:
        shares = missing.groupby(cluster.to_numpy()).mean()
        b.put(
            f"{key}_missing_share_cluster_min", shares.min() if len(shares) else None, "no clusters"
        )
        b.put(
            f"{key}_missing_share_cluster_max", shares.max() if len(shares) else None, "no clusters"
        )

    if numeric:
        fragment["kind"] = "numeric"
        _numeric(b, key, shown, failed, bounds, fragment)
    else:
        fragment["kind"] = "categorical"
        _categorical(b, key, shown, levels, fragment)
    return missing, fragment


def _numeric(
    b: _Builder,
    key: str,
    v: pd.Series,
    failed: int,
    bounds: list[float] | None,
    fragment: dict[str, Any],
) -> None:
    n = len(v)
    b.put(f"{key}_failed_conversions", failed)
    b.put(f"{key}_n", n)
    if n == 0:
        for stat in ("mean", "sd", "median", "min", "max", "q1", "q3", "skewness", "zero_share"):
            b.omitted[f"{key}_{stat}"] = "no numeric values"
        return
    b.put(f"{key}_mean", v.mean())
    b.put(f"{key}_sd", v.std(ddof=1) if n >= 2 else None, "needs at least 2 values")
    b.put(f"{key}_median", v.median())
    b.put(f"{key}_min", v.min())
    b.put(f"{key}_max", v.max())
    q1, q3 = float(v.quantile(0.25)), float(v.quantile(0.75))
    b.put(f"{key}_q1", q1)
    b.put(f"{key}_q3", q3)
    b.put(f"{key}_skewness", v.skew() if n >= 3 else None, "needs 3 values and nonzero spread")
    b.put(f"{key}_zero_share", float((v == 0).mean()))
    if n >= 4:
        spread = 1.5 * (q3 - q1)
        b.put(f"{key}_outliers", int(((v < q1 - spread) | (v > q3 + spread)).sum()))
    else:
        b.omitted[f"{key}_outliers"] = "needs at least 4 values"
    if n >= 20 and bool((v == v.round()).all()) and v.max() - v.min() >= 20:
        b.put(f"{key}_heaping_share", float((v % 5 == 0).mean()))
    else:
        b.omitted[f"{key}_heaping_share"] = "needs 20 integer values spanning at least 20"
    lower, upper = (bounds[0], bounds[1]) if bounds else (float(v.min()), float(v.max()))
    fragment["bounds"] = "declared" if bounds else "observed"
    b.put(f"{key}_floor_count", int((v == lower).sum()))
    b.put(f"{key}_floor_share", float((v == lower).mean()))
    b.put(f"{key}_ceiling_count", int((v == upper).sum()))
    b.put(f"{key}_ceiling_share", float((v == upper).mean()))
    if bounds:
        b.put(f"{key}_out_of_range", int(((v < lower) | (v > upper)).sum()))


def _categorical(
    b: _Builder, key: str, v: pd.Series, levels: list[str] | None, fragment: dict[str, Any]
) -> None:
    b.put(f"{key}_n", len(v))
    variants = v.groupby(v.str.strip().str.casefold().to_numpy()).nunique()
    b.put(f"{key}_inconsistent_codes", int((variants > 1).sum()))
    if levels is not None:
        b.put(f"{key}_out_of_levels", int((~v.isin(levels)).sum()))
    counts = v.value_counts()
    if len(counts) > _LEVEL_LIMIT:
        b.omitted[f"{key}_levels"] = f"more than {_LEVEL_LIMIT} levels"
        return
    fragment["levels"] = {}
    for i, (level, count) in enumerate(counts.items()):
        level_key = f"{key}_level{i:02d}_count"
        b.put(level_key, int(count))
        fragment["levels"][level_key] = str(level)


def describe_table(
    frame: pd.DataFrame, research: ResearchContext | None = None
) -> DescriptiveReport:
    b = _Builder()
    names = [str(c) for c in frame.columns]
    design = research.design if research else None
    variables = research.variables if research else {}

    def named(entry: Entry[str] | None) -> str | None:
        value = _declared(entry) if entry else None
        return value if value in names else None

    cluster_name = named(design.cluster_column if design else None)
    id_name = named(design.id_column if design else None)
    time_name = named(design.time_column if design else None)
    cluster = _text(frame[cluster_name]) if cluster_name else None

    b.put("rows", len(frame))
    b.put("columns", len(names))
    b.put("duplicate_rows", int(frame.duplicated().sum()) if len(frame) else 0)
    layout: dict[str, Any] = {"columns": [], "declared": {}}
    masks: list[pd.Series] = []
    for i, name in enumerate(names):
        key = f"c{i:03d}"
        var = variables.get(name)
        missing, fragment = _column(
            b,
            key,
            frame.iloc[:, i],
            _declared(var.type) if var else None,
            _declared(var.range) if var else None,
            _declared(var.levels) if var else None,
            None if name == cluster_name else cluster,
        )
        masks.append(missing.reset_index(drop=True))
        layout["columns"].append({"name": name, "key": key, **fragment})

    _co_missing(b, masks, names, layout)
    if id_name:
        layout["declared"]["id"] = id_name
        per_id = _text(frame[id_name]).dropna().value_counts()
        b.put("duplicate_ids", int((per_id > 1).sum()))
        b.put("rows_per_id_max", per_id.max() if len(per_id) else None, "no ids")
        b.put("rows_per_id_mean", per_id.mean() if len(per_id) else None, "no ids")
    if cluster_name and cluster is not None:
        layout["declared"]["cluster"] = cluster_name
        sizes = cluster.dropna().value_counts()
        b.put("cluster_count", len(sizes))
        b.put("cluster_size_min", sizes.min() if len(sizes) else None, "no clusters")
        b.put("cluster_size_median", sizes.median() if len(sizes) else None, "no clusters")
        b.put("cluster_size_max", sizes.max() if len(sizes) else None, "no clusters")
    if time_name:
        layout["declared"]["time"] = time_name
        _time(b, frame[time_name], layout)

    layout["omitted"] = b.omitted
    return DescriptiveReport(validate_results(b.results), layout)


def _co_missing(
    b: _Builder, masks: list[pd.Series], names: list[str], layout: dict[str, Any]
) -> None:
    layout["comissing"] = {}
    if not masks:
        return
    grid = pd.concat(masks, axis=1, keys=range(len(masks)))
    counts: dict[tuple[int, ...], int] = {}
    for row in grid.to_numpy():
        pattern = tuple(int(c) for c in np.flatnonzero(row))
        if len(pattern) >= 2:
            counts[pattern] = counts.get(pattern, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:_PATTERN_LIMIT]
    for p, (pattern, count) in enumerate(ranked):
        key = f"comissing{p:02d}_count"
        b.put(key, count)
        layout["comissing"][key] = [names[c] for c in pattern]


def _time(b: _Builder, series: pd.Series, layout: dict[str, Any]) -> None:
    text = _text(series)
    numbers = _numbers(text).dropna()
    low: Any
    high: Any
    if len(numbers) and len(numbers) * 2 >= int(text.notna().sum()):
        points = np.sort(numbers.unique())
        low, high = points[0], points[-1]
        gap = float(np.diff(points).max()) if len(points) > 1 else None
        layout["time_gap_unit"] = "as recorded"
    else:
        stamps = pd.to_datetime(text, errors="coerce", format="mixed").dropna()
        points = np.sort(stamps.unique())
        low = str(stamps.min().date()) if len(stamps) else None
        high = str(stamps.max().date()) if len(stamps) else None
        gap = float(np.diff(points).max() / np.timedelta64(1, "D")) if len(points) > 1 else None
        layout["time_gap_unit"] = "days"
    b.put("time_min", low, "no time values")
    b.put("time_max", high, "no time values")
    b.put("time_max_gap", gap, "needs at least 2 distinct times")


def _shown(value: object) -> str:
    return f"{value:.6g}" if isinstance(value, float) else str(value)


def format_description(report: DescriptiveReport) -> str:
    """Text for agents. A result key is the column key joined to the statistic, as in c000_mean."""
    results, layout = report.results, report.layout

    def stats(prefix: str) -> str:
        return " ".join(
            f"{key.removeprefix(prefix)}={_shown(entry['value'])}"
            for key, entry in results.items()
            if key.startswith(prefix)
        )

    lines = [
        "Result key = column key + '_' + statistic (for example c000_mean).",
        "Table: "
        + " ".join(
            f"{key}={_shown(entry['value'])}"
            for key, entry in results.items()
            if not _COLUMN_KEY.match(key) and not key.startswith("comissing")
        ),
    ]
    for col in layout["columns"]:
        bounds = f" bounds {col['bounds']}" if "bounds" in col else ""
        lines.append(
            f"{col['key']} {col['name']!r} ({col['kind']}{bounds}): {stats(col['key'] + '_')}"
        )
        lines.extend(f"  {key} = {level!r}" for key, level in col.get("levels", {}).items())
    lines.extend(
        f"{key}: {_shown(results[key]['value'])} rows missing together in {columns}"
        for key, columns in layout["comissing"].items()
    )
    lines.extend(f"declared {role} column: {name!r}" for role, name in layout["declared"].items())
    by_reason: dict[str, list[str]] = {}
    for key, reason in layout["omitted"].items():
        by_reason.setdefault(reason, []).append(key)
    lines.extend(f"Omitted ({reason}): {', '.join(keys)}" for reason, keys in by_reason.items())
    return "\n".join(lines)

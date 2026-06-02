"""Shared helpers for manual-entry adapters (Spec §3.6-3.8).

Several signals have no free public API (ABMS bulk, FAIR Health, state boards).
The operator looks each up by hand and records it in a small CSV; KODEX consumes
the CSV. These helpers parse those CSVs uniformly and tolerantly.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterator

_TRUE = {"1", "true", "t", "yes", "y"}
_FALSE = {"0", "false", "f", "no", "n"}


def read_rows(csv_path: str) -> Iterator[dict[str, str]]:
    """Yield dict rows from a CSV. Missing file -> empty (manual inputs are
    optional; absence simply means those signals stay UNKNOWN). Whitespace is
    stripped from keys and values."""
    path = Path(csv_path)
    if not path.exists():
        return
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for raw in reader:
            yield {
                (k.strip() if k else k): (v.strip() if isinstance(v, str) else v)
                for k, v in raw.items()
            }


def parse_bool(value: str | None) -> bool | None:
    """Tolerant boolean: blank/unknown -> None (not False), so a missing manual
    entry renders as UNKNOWN rather than a fabricated negative."""
    if value is None:
        return None
    v = value.strip().lower()
    if v in _TRUE:
        return True
    if v in _FALSE:
        return False
    return None


def parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    v = value.strip().replace(",", "").replace("$", "")
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None

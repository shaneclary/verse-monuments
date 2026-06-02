"""FAIR Health — geographic cost benchmark (manual adapter, Spec §3.6).

The consumer tool has no free API and bulk data is licensed. The operator looks
up the estimate (by CPT + ZIP) at fairhealthconsumer.org and pastes it into a CSV;
KODEX consumes it as a sanity-check / fallback benchmark when an MRF is
unavailable. We do NOT scrape.

CSV columns: cpt, zip, estimate, as_of
"""

from __future__ import annotations

from ..models import Benchmark
from .manual_base import parse_float, read_rows


def load(csv_path: str) -> list[Benchmark]:
    out: list[Benchmark] = []
    for row in read_rows(csv_path):
        cpt = (row.get("cpt") or "").strip()
        zip_ = (row.get("zip") or "").strip()
        est = parse_float(row.get("estimate"))
        if not cpt or est is None:
            continue
        out.append(
            Benchmark(
                cpt=cpt,
                zip=zip_,
                estimate=est,
                source="FAIRHEALTH",
                as_of=(row.get("as_of") or None) or None,
            )
        )
    return out


def benchmark_lookup(benchmarks: list[Benchmark]) -> dict[tuple[str, str], float]:
    """(cpt, zip) -> estimate, for quick fallback lookup."""
    return {(b.cpt, b.zip): b.estimate for b in benchmarks}

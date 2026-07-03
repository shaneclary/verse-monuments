"""CMS Care Compare / Provider Data Catalog — FACILITY quality (Spec §3.5).

Facility-level complication/readmission measures for the shortlisted hospitals —
the closest legitimate outcome signal available, but it is FACILITY-level, not
surgeon-level. The report labels it as such; a great surgeon at an average
hospital (or vice versa) is invisible here (Spec §11).

Bulk-ingested CSVs are queried locally by (CCN, measure_id).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from ..db import DB
from ..errors import FetchError

_CCN_COLS = ["Facility ID", "facility_id", "Provider ID", "CCN", "provider_id"]
# "HCAHPS Measure ID" covers the patient-satisfaction (HCAHPS) dataset, whose
# measure column is named differently from the complications/readmissions ones.
_MEASURE_COLS = ["Measure ID", "measure_id", "MeasureID", "HCAHPS Measure ID"]
# For HCAHPS the meaningful value of the summary measure (H_STAR_RATING) lives in
# "Patient Survey Star Rating"; the others cover complications/readmissions.
_SCORE_COLS = [
    "Score", "score", "Rate", "rate",
    "Patient Survey Star Rating", "HCAHPS Linear Mean Value", "HCAHPS Answer Percent",
]


def _pick(cands: list[str], available: list[str]) -> str | None:
    for c in cands:
        if c in available:
            return c
    return None


def ingest_csv(db: DB, csv_path: str, dataset_label: str, as_of: str | None = None) -> int:
    """Ingest a Care Compare measures CSV (long format: one row per
    facility×measure) into the care_compare table. Fails loudly on missing file
    or unrecognizable schema."""
    path = Path(csv_path)
    if not path.exists():
        raise FetchError(
            f"Care Compare CSV not found at {csv_path}. Download it from the CMS "
            f"Provider Data Catalog (Spec §3.5) before running."
        )
    df = pd.read_csv(path, dtype=str, low_memory=False)
    cols = list(df.columns)
    ccn_c = _pick(_CCN_COLS, cols)
    m_c = _pick(_MEASURE_COLS, cols)
    s_c = _pick(_SCORE_COLS, cols)
    if not ccn_c or not m_c or not s_c:
        raise FetchError(
            f"Care Compare CSV {csv_path} lacks CCN/Measure/Score columns "
            f"(saw {cols[:8]}...). Schema may have changed (Spec §11)."
        )
    rows: list[dict[str, Any]] = []
    for _, r in df.iterrows():
        rows.append(
            {
                "ccn": str(r[ccn_c]).zfill(6) if str(r[ccn_c]).isdigit() else str(r[ccn_c]),
                "measure_id": str(r[m_c]),
                "score": _num(r[s_c]),
                "as_of": as_of,
            }
        )
    db.upsert_care_compare(rows)
    db.log_ingest(f"care_compare:{dataset_label}", csv_path, len(rows), as_of)
    return len(rows)


def _num(v: Any) -> float | None:
    if v is None:
        return None
    s = str(v).strip()
    if s in ("", "Not Available", "Not Applicable", "N/A", "*"):
        return None
    try:
        return float(s.replace(",", "").replace("%", ""))
    except (ValueError, TypeError):
        return None


def enrich_facility(
    db: DB, ccn: str, complication_measure_id: str, readmission_measure_id: str
) -> tuple[float | None, float | None]:
    """Return (complication_measure, readmission_measure) for a CCN, or None
    where the facility has no published score for that measure."""
    comp = db.care_compare_for(ccn, complication_measure_id)
    readm = db.care_compare_for(ccn, readmission_measure_id)
    return (
        comp["score"] if comp else None,
        readm["score"] if readm else None,
    )


def measure_score(db: DB, ccn: str, measure_id: str) -> float | None:
    """Single facility measure (e.g. the HCAHPS satisfaction star rating), or None
    where the facility has no published score / the measure id is unset."""
    if not measure_id:
        return None
    row = db.care_compare_for(ccn, measure_id)
    return row["score"] if row else None

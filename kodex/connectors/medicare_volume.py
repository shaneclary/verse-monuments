"""Medicare Physician & Other Practitioners — ADR volume proxy (Spec §3.2).

We bulk-download the dataset ONCE to SQLite and query locally per NPI rather than
hammering an API. The bulk CSV is large, so ingestion streams in chunks and keeps
only the rows whose HCPCS code is one of our ADR CPTs.

CRITICAL limitation (the report must print this): this dataset covers only
Original Medicare FFS. ADR patients skew younger, so volume here is a FLOOR, not
a count. A surgeon with high commercial ADR volume can show near-zero here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from ..db import DB
from ..errors import FetchError

# Column-name candidates across dataset vintages (CMS renames occasionally).
_NPI_COLS = ["Rndrng_NPI", "rndrng_npi", "NPI", "npi"]
_HCPCS_COLS = ["HCPCS_Cd", "hcpcs_cd", "HCPCS_Code"]
_SRVCS_COLS = ["Tot_Srvcs", "tot_srvcs"]
_BENES_COLS = ["Tot_Benes", "tot_benes"]
_SBMTD_COLS = ["Avg_Sbmtd_Chrg", "avg_sbmtd_chrg"]
_PYMT_COLS = ["Avg_Mdcr_Pymt_Amt", "avg_mdcr_pymt_amt", "Avg_Mdcr_Pymt"]


def _pick(cols: list[str], available: list[str]) -> str | None:
    for c in cols:
        if c in available:
            return c
    return None


def ingest_csv(
    db: DB,
    csv_path: str,
    cpts: list[str],
    year: str,
    *,
    chunksize: int = 200_000,
) -> int:
    """Stream the bulk Medicare CSV, keep only ADR-CPT rows, upsert to SQLite.
    Returns the number of rows ingested. Fails loudly if the file is missing or
    its schema is unrecognizable."""
    path = Path(csv_path)
    if not path.exists():
        raise FetchError(
            f"Medicare bulk CSV not found at {csv_path}. Download it once from "
            f"data.cms.gov (Spec §3.2) before running, or run with --offline using a "
            f"prior cache."
        )
    cpt_set = set(cpts)
    total = 0
    reader = pd.read_csv(path, dtype=str, chunksize=chunksize, low_memory=False)
    for chunk in reader:
        cols = list(chunk.columns)
        npi_c = _pick(_NPI_COLS, cols)
        hc_c = _pick(_HCPCS_COLS, cols)
        if not npi_c or not hc_c:
            raise FetchError(
                f"Medicare CSV at {csv_path} lacks recognizable NPI/HCPCS columns "
                f"(saw {cols[:8]}...). Schema may have changed (Spec §11)."
            )
        srv_c = _pick(_SRVCS_COLS, cols)
        ben_c = _pick(_BENES_COLS, cols)
        sb_c = _pick(_SBMTD_COLS, cols)
        py_c = _pick(_PYMT_COLS, cols)

        keep = chunk[chunk[hc_c].isin(cpt_set)]
        if keep.empty:
            continue
        rows: list[dict[str, Any]] = []
        for _, row in keep.iterrows():
            rows.append(
                {
                    "npi": str(row[npi_c]),
                    "cpt": str(row[hc_c]),
                    "year": year,
                    "tot_srvcs": _num(row.get(srv_c)),
                    "tot_benes": _num(row.get(ben_c)),
                    "avg_sbmtd_chrg": _num(row.get(sb_c)),
                    "avg_mdcr_pymt": _num(row.get(py_c)),
                }
            )
        db.upsert_medicare(rows)
        total += len(rows)
    db.log_ingest("medicare_volume", csv_path, total, year)
    return total


def _num(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(str(v).replace(",", "").replace("$", ""))
    except (ValueError, TypeError):
        return None


def enrich_provider(db: DB, npi: str, cpts: list[str]) -> tuple[int | None, float | None]:
    """Look up a provider's ADR service volume + avg Medicare payment from the
    locally ingested table. Returns (volume_floor, avg_payment).

    No matching rows -> (None, None): we cannot tell "zero Medicare FFS ADR" from
    "bills commercial only," so we report UNKNOWN rather than assert 0 (Spec §3.2)."""
    rows = db.medicare_for(npi, cpts)
    if not rows:
        return None, None
    volume = 0.0
    pay_weighted = 0.0
    pay_n = 0.0
    for r in rows:
        srv = r["tot_srvcs"] or 0.0
        volume += srv
        if r["avg_mdcr_pymt"] is not None and srv:
            pay_weighted += r["avg_mdcr_pymt"] * srv
            pay_n += srv
    avg_payment = (pay_weighted / pay_n) if pay_n else None
    return int(round(volume)), avg_payment

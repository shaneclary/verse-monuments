"""State medical board — license status + disciplinary actions (manual, Spec §3.8).

State boards are mostly web lookups, rarely APIs. The operator records, per
shortlisted surgeon: active license (bool), disciplinary action present (bool +
note). A disciplinary flag is ALWAYS surfaced in the report regardless of score.

CSV columns: npi, license_active, disciplinary_flag, disciplinary_note
"""

from __future__ import annotations

from .manual_base import parse_bool, read_rows


def load(csv_path: str) -> dict[str, dict]:
    """npi -> {license_active, disciplinary_flag, disciplinary_note}."""
    out: dict[str, dict] = {}
    for row in read_rows(csv_path):
        npi = (row.get("npi") or "").strip()
        if not npi:
            continue
        out[npi] = {
            "license_active": parse_bool(row.get("license_active")),
            "disciplinary_flag": parse_bool(row.get("disciplinary_flag")),
            "disciplinary_note": (row.get("disciplinary_note") or None) or None,
        }
    return out

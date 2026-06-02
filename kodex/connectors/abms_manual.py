"""ABMS Certification Matters — board certification (manual adapter, Spec §3.7).

Public verification is one-at-a-time; bulk is licensed. So the operator confirms
each shortlisted surgeon's status at certificationmatters.org and records it in a
CSV. We do NOT scrape.

CSV columns: npi, board_certified, board_name
"""

from __future__ import annotations

from .manual_base import parse_bool, read_rows


def load(csv_path: str) -> dict[str, dict]:
    """npi -> {board_certified: bool|None, board_name: str|None}."""
    out: dict[str, dict] = {}
    for row in read_rows(csv_path):
        npi = (row.get("npi") or "").strip()
        if not npi:
            continue
        out[npi] = {
            "board_certified": parse_bool(row.get("board_certified")),
            "board_name": (row.get("board_name") or None) or None,
        }
    return out

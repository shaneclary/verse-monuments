"""Operator-curated rosters that bridge gaps the public datasets don't fill.

NPPES does not reliably link a surgeon to the hospital CCN used by MRFs and Care
Compare, so the operator supplies two small CSVs while building the shortlist:

  facility_roster.csv : ccn, name, state, zip, mrf_domain
  provider_facility.csv: npi, ccn

These are the shortlist's backbone (Spec §3.4 "shortlist-driven, not crawl
everything"). Both are optional; absence just means fewer links.
"""

from __future__ import annotations

from ..models import Facility
from .manual_base import read_rows


def load_facilities(csv_path: str) -> dict[str, Facility]:
    """ccn -> Facility (identity only; cost/quality filled by other connectors)."""
    out: dict[str, Facility] = {}
    for row in read_rows(csv_path):
        ccn = (row.get("ccn") or "").strip()
        if not ccn:
            continue
        out[ccn] = Facility(
            ccn=ccn,
            name=(row.get("name") or f"Facility {ccn}").strip(),
            state=(row.get("state") or None) or None,
            zip=((row.get("zip") or "")[:5]) or None,
        )
    return out


def load_facility_domains(csv_path: str) -> dict[str, str]:
    """ccn -> website domain for cms-hpt.txt MRF discovery (Spec §3.4)."""
    out: dict[str, str] = {}
    for row in read_rows(csv_path):
        ccn = (row.get("ccn") or "").strip()
        domain = (row.get("mrf_domain") or row.get("domain") or "").strip()
        if ccn and domain:
            out[ccn] = domain
    return out


def load_provider_facility(csv_path: str) -> dict[str, str]:
    """npi -> primary facility CCN."""
    out: dict[str, str] = {}
    for row in read_rows(csv_path):
        npi = (row.get("npi") or "").strip()
        ccn = (row.get("ccn") or "").strip()
        if npi and ccn:
            out[npi] = ccn
    return out

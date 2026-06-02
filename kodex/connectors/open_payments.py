"""CMS Open Payments — industry/device-maker relationship signal (Spec §3.3).

Per NPI, aggregate general payments and surface the top paying companies, with
spine-implant makers flagged. SCORING STANCE: do NOT auto-penalize. Industry ties
are common and not inherently bad. This is a transparency flag to DISPLAY; it only
influences the score if the operator opts in (config: open_payments_in_score).
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from ..db import DB
from .base import HttpClient, cached_text


def parse_open_payments(payload: Any, flag_manufacturers: list[str]) -> tuple[float, list[str]]:
    """Pure parser: datastore-query result -> (total_usd, top_payers).

    Tolerant of the datastore 'results' envelope and a bare list. Manufacturer +
    amount field names vary by program year, so we probe a few candidates."""
    records = payload.get("results", payload) if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        return 0.0, []

    by_company: dict[str, float] = defaultdict(float)
    total = 0.0
    for rec in records:
        if not isinstance(rec, dict):
            continue
        amount = _first_num(
            rec,
            [
                "total_amount_of_payment_usdollars",
                "Total_Amount_of_Payment_USDollars",
                "total_amount",
            ],
        )
        company = _first_str(
            rec,
            [
                "applicable_manufacturer_or_applicable_gpo_making_payment_name",
                "Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_Name",
                "manufacturer_name",
            ],
        )
        if amount is None:
            continue
        total += amount
        if company:
            by_company[company] += amount

    flags = {m.lower() for m in flag_manufacturers}
    ranked = sorted(by_company.items(), key=lambda kv: kv[1], reverse=True)
    top = []
    for name, amt in ranked[:5]:
        marker = " [spine-implant maker]" if any(f in name.lower() for f in flags) else ""
        top.append(f"{name}: ${amt:,.0f}{marker}")
    return round(total, 2), top


def _first_num(rec: dict[str, Any], keys: list[str]) -> float | None:
    for k in keys:
        if k in rec and rec[k] not in (None, ""):
            try:
                return float(str(rec[k]).replace(",", "").replace("$", ""))
            except (ValueError, TypeError):
                continue
    return None


def _first_str(rec: dict[str, Any], keys: list[str]) -> str | None:
    for k in keys:
        if rec.get(k):
            return str(rec[k])
    return None


def fetch_for_npi(
    db: DB,
    http: HttpClient | None,
    endpoint: str,
    dataset_id: str,
    npi: str,
    flag_manufacturers: list[str],
    *,
    offline: bool = False,
) -> tuple[float | None, list[str]]:
    """Aggregate Open Payments for one NPI. Returns (total|None, top_payers).

    If dataset_id is unset, returns (None, []) — the signal is simply unavailable
    (UNKNOWN), not zero."""
    if not dataset_id:
        return None, []
    # Open Payments datastore query: filter general payments by covered recipient NPI.
    url = f"{endpoint.rstrip('/')}/{dataset_id}/0"
    params = {
        "conditions[0][property]": "covered_recipient_npi",
        "conditions[0][value]": npi,
        "conditions[0][operator]": "=",
        "limit": 500,
    }
    key = f"dataset={dataset_id}|npi={npi}"
    body = cached_text(
        db, http, source="open_payments", key=key, url=url, params=params, offline=offline
    )
    payload = json.loads(body)
    total, top = parse_open_payments(payload, flag_manufacturers)
    return total, top

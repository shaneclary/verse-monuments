"""NPPES NPI Registry — provider directory + credentials (Spec §3.1).

Seeds the provider list. Free, no auth. We query by taxonomy_description + state
(+ optional city/postal), paginate politely, and cache raw pages to SQLite.

Limitation surfaced in the report: the credential string is self-reported free
text and is NOT a substitute for board verification (that comes from the ABMS
manual adapter, §3.7).
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from ..db import DB
from ..models import Provider
from .base import HttpClient, cached_text

NPPES_PAGE_LIMIT = 200   # API max per page


def _years_since(enumeration_date: str | None, current_year: int) -> int | None:
    """Tenure proxy from the NPI enumeration date (YYYY-MM-DD)."""
    if not enumeration_date:
        return None
    try:
        yr = int(enumeration_date[:4])
    except (ValueError, TypeError):
        return None
    return max(0, current_year - yr)


def _primary_location(addresses: list[dict[str, Any]]) -> dict[str, Any] | None:
    for a in addresses or []:
        if a.get("address_purpose") == "LOCATION":
            return a
    return (addresses or [None])[0]


def parse_nppes_results(payload: dict[str, Any], current_year: int) -> list[Provider]:
    """Pure parser: NPPES JSON page -> Provider list. No I/O (unit-testable)."""
    providers: list[Provider] = []
    for r in payload.get("results", []) or []:
        basic = r.get("basic", {}) or {}
        taxonomies = r.get("taxonomies", []) or []
        primary_tax = next(
            (t for t in taxonomies if t.get("primary")), (taxonomies or [{}])[0]
        )
        addr = _primary_location(r.get("addresses", [])) or {}

        name_parts = [basic.get("first_name"), basic.get("last_name")]
        org = basic.get("organization_name")
        name = " ".join(p for p in name_parts if p) or org or "UNKNOWN"

        providers.append(
            Provider(
                npi=str(r.get("number")),
                name=name,
                credential=basic.get("credential"),
                taxonomy=primary_tax.get("desc"),
                address=", ".join(
                    p for p in [addr.get("address_1"), addr.get("city"), addr.get("state")] if p
                ) or None,
                state=addr.get("state"),
                zip=(addr.get("postal_code") or "")[:5] or None,
                years_in_practice_proxy=_years_since(
                    basic.get("enumeration_date"), current_year
                ),
            )
        )
    return providers


def search_providers(
    db: DB,
    http: HttpClient | None,
    endpoint: str,
    *,
    taxonomy: str,
    state: str,
    city: str | None = None,
    postal_code: str | None = None,
    offline: bool = False,
    max_records: int = 600,
    current_year: int | None = None,
) -> list[Provider]:
    """Search NPPES for individual providers (NPI-1) matching a taxonomy in a
    state. Paginates up to max_records, caching each page. Fails loudly."""
    current_year = current_year or date.today().year
    out: list[Provider] = []
    skip = 0
    while skip < max_records:
        params: dict[str, Any] = {
            "version": "2.1",
            "enumeration_type": "NPI-1",
            "taxonomy_description": taxonomy,
            "state": state,
            "limit": NPPES_PAGE_LIMIT,
            "skip": skip,
        }
        if city:
            params["city"] = city
        if postal_code:
            params["postal_code"] = postal_code

        key = f"taxonomy={taxonomy}|state={state}|city={city}|zip={postal_code}|skip={skip}"
        body = cached_text(
            db, http, source="nppes", key=key, url=endpoint, params=params, offline=offline
        )
        payload = json.loads(body)
        page = parse_nppes_results(payload, current_year)
        out.extend(page)
        # NPPES returns up to 200; fewer means we've reached the end.
        if len(page) < NPPES_PAGE_LIMIT:
            break
        skip += NPPES_PAGE_LIMIT
    return out

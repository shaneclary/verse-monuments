"""Hospital Price Transparency MRFs — the real cost axis (Spec §3.4).

SHORTLIST-DRIVEN, never crawl-everything. For each shortlisted facility we:
  1. locate its MRF via the CMS-required discovery file (``/cms-hpt.txt``),
  2. STREAM-parse it (files run hundreds of MB to GB — we never load one whole
     into memory), extracting only rows matching the ADR CPT codes,
  3. store discounted cash price (primary) + negotiated min/max (secondary).

If an MRF is missing or non-compliant we degrade gracefully: cost_source becomes
"MRF_UNAVAILABLE" and the pipeline falls back to the FAIR Health benchmark
(Spec §3.4 / §11). We never crash on schema drift and never fabricate a price.

Two schema adapters cover most hospitals: the CMS JSON template and the CMS
"tall" CSV. Both stream.
"""

from __future__ import annotations

import csv
import gzip
import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any, Iterator

import ijson

from ..db import DB
from ..errors import CacheMiss, FetchError, SchemaError
from ..models import Facility
from .base import HttpClient, cached_text

_URL_RE = re.compile(r'https?://[^\s"\'<>\)]+', re.IGNORECASE)
_MRF_FILE_RE = re.compile(r"\.(json|csv)(\.gz)?(\?|$)", re.IGNORECASE)


@dataclass
class CptPrice:
    cash: float | None = None
    negotiated_min: float | None = None
    negotiated_max: float | None = None

    def absorb(self, cash: float | None, lo: float | None, hi: float | None) -> None:
        """Keep the most favorable cash price (lowest) and widen neg. range."""
        if cash is not None:
            self.cash = cash if self.cash is None else min(self.cash, cash)
        if lo is not None:
            self.negotiated_min = lo if self.negotiated_min is None else min(self.negotiated_min, lo)
        if hi is not None:
            self.negotiated_max = hi if self.negotiated_max is None else max(self.negotiated_max, hi)


@dataclass
class MrfResult:
    prices: dict[str, CptPrice] = field(default_factory=dict)
    last_updated: str | None = None

    def absorb(self, cpt: str, cash: float | None, lo: float | None, hi: float | None) -> None:
        self.prices.setdefault(cpt, CptPrice()).absorb(cash, lo, hi)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------
def discover_mrf_urls(cms_hpt_text: str) -> list[str]:
    """Extract MRF file URLs from a cms-hpt.txt body. Prefer explicit .json/.csv
    URLs; fall back to any URL present."""
    urls = _URL_RE.findall(cms_hpt_text or "")
    mrf = [u for u in urls if _MRF_FILE_RE.search(u)]
    return mrf or urls


def fetch_discovery(
    db: DB, http: HttpClient | None, domain: str, discovery_path: str, *, offline: bool
) -> list[str]:
    """GET https://<domain>/cms-hpt.txt and return candidate MRF URLs."""
    base = domain.rstrip("/")
    if not base.startswith("http"):
        base = "https://" + base
    url = base + discovery_path
    body = cached_text(db, http, source="cms_hpt", key=domain, url=url, offline=offline)
    return discover_mrf_urls(body)


# ---------------------------------------------------------------------------
# Streaming parsers
# ---------------------------------------------------------------------------
def _open_maybe_gzip(path: str, mode: str) -> IO:
    """Open an MRF for streaming. mode 'rb' -> bytes (ijson); 'r' -> text (csv)."""
    is_gz = str(path).lower().endswith(".gz")
    if mode == "rb":
        return gzip.open(path, "rb") if is_gz else open(path, "rb")
    # text mode
    if is_gz:
        return gzip.open(path, "rt", encoding="utf-8", newline="")
    return open(path, "r", encoding="utf-8", newline="")


def _num(v: Any) -> float | None:
    if v is None:
        return None
    s = str(v).strip().replace(",", "").replace("$", "")
    if not s or s.lower() in ("na", "n/a", "not available"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _charges_from_entry(entry: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
    """Pull (cash, neg_min, neg_max) from one standard_charges entry."""
    cash = _num(entry.get("discounted_cash"))
    lo = _num(entry.get("minimum"))
    hi = _num(entry.get("maximum"))
    # If explicit min/max absent, derive from per-payer negotiated dollars.
    if lo is None or hi is None:
        payer_vals = []
        for p in entry.get("payers_information", []) or []:
            val = _num(p.get("standard_charge_dollar")) or _num(p.get("standard_charge_negotiated_dollar"))
            if val is not None:
                payer_vals.append(val)
        if payer_vals:
            lo = min(payer_vals) if lo is None else lo
            hi = max(payer_vals) if hi is None else hi
    return cash, lo, hi


def parse_mrf_json(path: str, cpts: list[str]) -> MrfResult:
    """Stream the CMS JSON template, extracting only ADR-CPT rows. Memory stays
    flat: we iterate standard_charge_information items one at a time."""
    cpt_set = set(cpts)
    result = MrfResult()
    with _open_maybe_gzip(path, "rb") as fh:
        # last_updated_on appears before the big array; grab it cheaply if present.
        # (Best-effort; the main pass is the streamed item iteration below.)
        try:
            for item in ijson.items(fh, "standard_charge_information.item"):
                codes = item.get("code_information", []) or []
                matched = {
                    str(c.get("code"))
                    for c in codes
                    if str(c.get("code")) in cpt_set
                }
                if not matched:
                    continue
                for entry in item.get("standard_charges", []) or []:
                    cash, lo, hi = _charges_from_entry(entry)
                    for cpt in matched:
                        result.absorb(cpt, cash, lo, hi)
        except ijson.JSONError as exc:
            raise SchemaError(f"MRF JSON at {path} failed to parse: {exc}") from exc
    return result


# CSV column patterns (CMS "tall" format).
_CODE_COL_RE = re.compile(r"^code\s*\|\s*(\d+)$", re.IGNORECASE)
_CODE_TYPE_COL_RE = re.compile(r"^code\s*\|\s*(\d+)\s*\|\s*type$", re.IGNORECASE)


def _find_header_row(rows: Iterator[list[str]]) -> tuple[list[str], Iterator[list[str]]]:
    """CMS CSVs carry a few metadata preamble rows above the real header. Find
    the header row (the one with 'description' or a 'code|N' column)."""
    import itertools

    buffered = []
    for row in rows:
        buffered.append(row)
        lowered = [c.strip().lower() for c in row]
        if "description" in lowered or any(_CODE_COL_RE.match(c.strip()) for c in row):
            header = row
            rest = itertools.chain([], rows)
            return header, rest
        if len(buffered) > 10:  # don't scan forever on a malformed file
            break
    raise SchemaError("MRF CSV: could not locate a header row (no 'description'/'code|N').")


def parse_mrf_csv(path: str, cpts: list[str]) -> MrfResult:
    """Stream the CMS 'tall' CSV row-by-row, extracting ADR-CPT rows only."""
    cpt_set = set(cpts)
    result = MrfResult()
    with _open_maybe_gzip(path, "r") as fh:
        reader = csv.reader(fh)
        header, _ = _find_header_row(reader)
        col_index = {name.strip(): i for i, name in enumerate(header)}
        code_cols = [(int(_CODE_COL_RE.match(n).group(1)), i)
                     for n, i in col_index.items() if _CODE_COL_RE.match(n)]
        cash_i = _col(col_index, ["standard_charge|discounted_cash", "standard_charge | discounted_cash"])
        min_i = _col(col_index, ["standard_charge|min", "standard_charge|minimum"])
        max_i = _col(col_index, ["standard_charge|max", "standard_charge|maximum"])

        # DictReader-like streaming using the same file handle (reader is positioned
        # right after the header).
        for row in reader:
            if not row:
                continue
            matched = set()
            for _, idx in code_cols:
                if idx < len(row) and row[idx].strip() in cpt_set:
                    matched.add(row[idx].strip())
            if not matched:
                continue
            cash = _num(row[cash_i]) if cash_i is not None and cash_i < len(row) else None
            lo = _num(row[min_i]) if min_i is not None and min_i < len(row) else None
            hi = _num(row[max_i]) if max_i is not None and max_i < len(row) else None
            for cpt in matched:
                result.absorb(cpt, cash, lo, hi)
    return result


def _col(index: dict[str, int], names: list[str]) -> int | None:
    for n in names:
        if n in index:
            return index[n]
    # case-insensitive fallback
    lower = {k.lower(): v for k, v in index.items()}
    for n in names:
        if n.lower() in lower:
            return lower[n.lower()]
    return None


def parse_mrf_file(path: str, cpts: list[str]) -> MrfResult:
    """Dispatch to the JSON or CSV adapter by file extension."""
    p = str(path).lower()
    base = p[:-3] if p.endswith(".gz") else p
    if base.endswith(".json"):
        return parse_mrf_json(path, cpts)
    if base.endswith(".csv"):
        return parse_mrf_csv(path, cpts)
    raise SchemaError(f"Unrecognized MRF extension for {path} (expected .json/.csv[.gz]).")


# ---------------------------------------------------------------------------
# Orchestration for one facility
# ---------------------------------------------------------------------------
def fetch_facility_cost(
    db: DB,
    http: HttpClient | None,
    facility: Facility,
    cpts: list[str],
    domain: str | None,
    *,
    offline: bool,
    discovery_path: str = "/cms-hpt.txt",
    max_bytes: int = 3_000_000_000,
) -> Facility:
    """Populate facility.cash_price / negotiated_min / negotiated_max from its
    MRF. On any failure, set cost_source='MRF_UNAVAILABLE' and return — the caller
    falls back to FAIR Health. NEVER raises for an individual facility's bad MRF."""
    if not domain:
        facility.cost_source = "MRF_UNAVAILABLE"
        return facility
    try:
        urls = fetch_discovery(db, http, domain, discovery_path, offline=offline)
        if not urls:
            facility.cost_source = "MRF_UNAVAILABLE"
            return facility

        result: MrfResult | None = None
        for url in urls:
            try:
                result = _get_mrf_result(db, http, url, cpts, offline=offline, max_bytes=max_bytes)
                if result.prices:
                    break
            except (FetchError, SchemaError, CacheMiss):
                continue  # try the next candidate URL

        if not result or not result.prices:
            facility.cost_source = "MRF_UNAVAILABLE"
            return facility

        for cpt, price in result.prices.items():
            if price.cash is not None:
                facility.cash_price[cpt] = price.cash
            if price.negotiated_min is not None:
                facility.negotiated_min[cpt] = price.negotiated_min
            if price.negotiated_max is not None:
                facility.negotiated_max[cpt] = price.negotiated_max
        facility.cost_source = "MRF" if facility.cash_price else "MRF_UNAVAILABLE"
        facility.cost_as_of = result.last_updated
        return facility
    except (FetchError, SchemaError, CacheMiss):
        facility.cost_source = "MRF_UNAVAILABLE"
        return facility


# Cache source for the EXTRACTED per-CPT prices (small), keyed by MRF URL. We
# deliberately do NOT cache the multi-GB body — only the handful of numbers we
# extracted — so a later --offline run reproduces the same costs/frontier
# without re-downloading or buffering the whole file (Spec §3.4 + §4).
_PRICES_SOURCE = "mrf_prices"


def serialize_result(result: MrfResult) -> str:
    return json.dumps({
        "last_updated": result.last_updated,
        "prices": {
            cpt: {"cash": p.cash, "negotiated_min": p.negotiated_min,
                  "negotiated_max": p.negotiated_max}
            for cpt, p in result.prices.items()
        },
    })


def deserialize_result(payload: str) -> MrfResult:
    data = json.loads(payload)
    result = MrfResult(last_updated=data.get("last_updated"))
    for cpt, p in (data.get("prices") or {}).items():
        result.prices[cpt] = CptPrice(
            cash=p.get("cash"), negotiated_min=p.get("negotiated_min"),
            negotiated_max=p.get("negotiated_max"),
        )
    return result


def _get_mrf_result(
    db: DB, http: HttpClient | None, url: str, cpts: list[str], *, offline: bool, max_bytes: int
) -> MrfResult:
    """Return the extracted ADR-CPT prices for one MRF URL.

    Offline: read the cached extracted prices (CacheMiss if a prior online run
    never stored them). Online: stream the body to a temp file (flat memory),
    parse out only the ADR-CPT rows, cache those extracted prices, and clean up
    the temp file."""
    if offline:
        cached = db.cache_get(_PRICES_SOURCE, url)
        if cached is None:
            raise CacheMiss(
                f"--offline: extracted MRF prices for {url} not cached. Run once "
                f"online to populate the cache (Spec §4)."
            )
        return deserialize_result(cached)

    if http is None:
        raise FetchError("MRF fetch requires an HttpClient when online.")
    suffix = ".json" if ".json" in url.lower() else (".csv" if ".csv" in url.lower() else "")
    if url.lower().endswith(".gz"):
        suffix += ".gz"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.close()
    try:
        http.stream_to_file(url, tmp.name, max_bytes=max_bytes)
        result = parse_mrf_file(tmp.name, cpts)
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
    db.cache_put(_PRICES_SOURCE, url, serialize_result(result), url=url)
    return result

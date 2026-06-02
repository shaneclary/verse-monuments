"""Bulk-dataset acquisition — turn config into real local CSVs (Spec §3.2/§3.5).

The big Medicare and Care Compare datasets are downloaded ONCE and ingested into
SQLite (the per-NPI / per-CCN lookups then run offline). This module is the piece
that actually *gets* them, plus the Open Payments dataset-id resolver.

Design stance — discovery by TITLE, never hard-coded UUIDs:
  CMS rotates dataset/distribution identifiers every vintage. Hard-coding a UUID
  rots silently. Instead we query each catalog's machine index and pick the
  current distribution whose dataset title matches a configured substring. The
  only things in config.yaml are stable: the catalog endpoints and the title
  text. (Spec §11 — survive schema/identifier drift, fail loudly otherwise.)

Three catalogs, three shapes — all handled by tolerant pure parsers:
  * data.cms.gov DCAT          (``/data.json``)            -> Medicare CSV
  * Provider Data Catalog       (DKAN metastore items)      -> Care Compare CSVs
  * openpaymentsdata.cms.gov    (DKAN metastore items)      -> datastore resource id

Pure parsers (``find_*``) take already-parsed JSON and are unit-tested against
fixtures; the ``resolve_*`` / ``download_*`` wrappers do the I/O (online only).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from ..db import DB
from ..errors import FetchError
from .base import HttpClient, cached_text


@dataclass
class Distribution:
    """One downloadable file (or datastore resource) inside a catalog dataset."""

    dataset_title: str
    url: str | None              # downloadURL (CSV) — None for a query-only resource
    identifier: str | None       # datastore resource id (Open Payments query) if any
    media_type: str | None = None
    modified: str | None = None   # dataset 'modified' date, surfaced in the appendix


# ---------------------------------------------------------------------------
# Shape-tolerant traversal helpers (DKAN and DCAT differ; vintages differ too)
# ---------------------------------------------------------------------------
def _dataset_title(ds: dict[str, Any]) -> str:
    return str(ds.get("title") or ds.get("name") or "")


def _iter_distributions(ds: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Yield each distribution as a flat dict, unwrapping the DKAN ``{"data": …}``
    envelope when present (DCAT puts the fields at the top level)."""
    for dist in ds.get("distribution", []) or []:
        if isinstance(dist, dict) and isinstance(dist.get("data"), dict):
            yield dist["data"]
        elif isinstance(dist, dict):
            yield dist


def _dist_url(dist: dict[str, Any]) -> str | None:
    return dist.get("downloadURL") or dist.get("download_url") or dist.get("accessURL")


def _is_csv(dist: dict[str, Any]) -> bool:
    mt = str(dist.get("mediaType") or dist.get("media_type") or "").lower()
    url = (_dist_url(dist) or "").lower()
    return "csv" in mt or url.endswith(".csv") or url.endswith(".csv.gz")


def _matching_datasets(datasets: list[dict[str, Any]], title_substr: str) -> list[dict[str, Any]]:
    needle = title_substr.lower().strip()
    return [d for d in datasets if needle in _dataset_title(d).lower()]


def _datasets_root(catalog: Any) -> list[dict[str, Any]]:
    """Both shapes reduce to a list of dataset dicts. DCAT wraps them in
    ``{"dataset": [...]}``; the DKAN metastore returns a bare list."""
    if isinstance(catalog, dict):
        return catalog.get("dataset", []) or []
    if isinstance(catalog, list):
        return catalog
    return []


# ---------------------------------------------------------------------------
# Pure resolvers (unit-tested against fixtures)
# ---------------------------------------------------------------------------
def find_csv_distribution(
    catalog: Any, title_substr: str, *, year: str | None = None
) -> Distribution:
    """Find the current CSV distribution for the dataset whose title contains
    ``title_substr``. When ``year`` is given (e.g. "2023"), prefer the dataset OR
    distribution whose title carries that year — Medicare publishes one dataset
    per program year, sometimes as sibling datasets, sometimes as sibling
    distributions. Raises FetchError (loud) if nothing matches.
    """
    datasets = _datasets_root(catalog)
    candidates = _matching_datasets(datasets, title_substr)
    if not candidates:
        raise FetchError(
            f"No dataset in the catalog matched title ~ {title_substr!r}. The "
            f"dataset may have been renamed — re-verify the title in config.yaml (Spec §11)."
        )

    # Newest dataset first, so an un-yeared request still picks the latest vintage.
    candidates.sort(key=lambda d: str(d.get("modified") or ""), reverse=True)

    for ds in candidates:
        title = _dataset_title(ds)
        ds_names_year = bool(year) and year in title
        csv_dists = [d for d in _iter_distributions(ds) if _is_csv(d) and _dist_url(d)]
        if year and not ds_names_year:
            # Dataset title doesn't name the year — only accept a distribution
            # that itself carries the year, so we never return the wrong vintage.
            csv_dists = [
                d for d in csv_dists
                if year in str(d.get("title") or "") or year in (_dist_url(d) or "")
            ]
        if not csv_dists:
            continue
        chosen = csv_dists[0]
        return Distribution(
            dataset_title=title,
            url=_dist_url(chosen),
            identifier=chosen.get("identifier"),
            media_type=chosen.get("mediaType") or chosen.get("media_type"),
            modified=str(ds.get("modified")) if ds.get("modified") else None,
        )

    raise FetchError(
        f"Dataset ~ {title_substr!r} found, but no CSV distribution"
        + (f" matched year {year}" if year else " was available")
        + " — re-verify the title/year in config.yaml (Spec §11)."
    )


def find_datastore_resource_id(
    catalog: Any, title_substr: str, *, year: str | None = None
) -> Distribution:
    """Open Payments: find the datastore RESOURCE id (used by the datastore-query
    endpoint as the dataset_id) for the dataset whose title matches. When ``year``
    is given, require it in the dataset title — program years are distinct datasets.
    """
    datasets = _datasets_root(catalog)
    candidates = _matching_datasets(datasets, title_substr)
    if year:
        candidates = [d for d in candidates if year in _dataset_title(d)]
    if not candidates:
        raise FetchError(
            f"No Open Payments dataset matched title ~ {title_substr!r}"
            + (f" for year {year}" if year else "")
            + ". Re-verify the title/year in config.yaml (Spec §3.3, §11)."
        )
    candidates.sort(key=lambda d: str(d.get("modified") or ""), reverse=True)
    for ds in candidates:
        for dist in _iter_distributions(ds):
            rid = dist.get("identifier")
            if rid:
                return Distribution(
                    dataset_title=_dataset_title(ds),
                    url=_dist_url(dist),
                    identifier=str(rid),
                    media_type=dist.get("mediaType") or dist.get("media_type"),
                    modified=str(ds.get("modified")) if ds.get("modified") else None,
                )
    raise FetchError(
        f"Open Payments dataset ~ {title_substr!r} found, but no distribution "
        f"carried a datastore resource identifier (Spec §11)."
    )


# ---------------------------------------------------------------------------
# Online orchestration (I/O) — cache the catalog index, stream the CSV
# ---------------------------------------------------------------------------
def _load_catalog(db: DB, http: HttpClient, url: str, source: str) -> Any:
    """Fetch + cache a catalog index (small JSON). Cached so a re-resolve is
    reproducible and we are polite to the index endpoint."""
    import json

    body = cached_text(db, http, source=source, key=url, url=url, offline=False)
    return json.loads(body)


def resolve_csv(
    db: DB, http: HttpClient, catalog_url: str, title_substr: str, *, year: str | None = None
) -> Distribution:
    catalog = _load_catalog(db, http, catalog_url, source="catalog")
    return find_csv_distribution(catalog, title_substr, year=year)


def resolve_open_payments_id(
    db: DB, http: HttpClient, metastore_url: str, title_substr: str, *, year: str | None = None
) -> Distribution:
    catalog = _load_catalog(db, http, metastore_url, source="catalog")
    return find_datastore_resource_id(catalog, title_substr, year=year)


def download_csv(
    http: HttpClient, dist: Distribution, dest_path: str, *, max_bytes: int
) -> int:
    """Stream a resolved CSV distribution to ``dest_path`` (flat memory, capped).
    Returns bytes written. Raises FetchError if the distribution has no URL."""
    if not dist.url:
        raise FetchError(
            f"Resolved dataset {dist.dataset_title!r} has no downloadURL — it may be "
            f"query-only (use the datastore API) rather than a bulk CSV (Spec §11)."
        )
    Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
    return http.stream_to_file(dist.url, dest_path, max_bytes=max_bytes)

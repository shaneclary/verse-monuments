"""Bulk-dataset acquisition resolvers (Spec §3.2/§3.5).

These verify the PURE catalog parsers — the part that survives CMS's identifier
drift by matching dataset titles and picking the current CSV distribution /
datastore resource id. The network I/O wrappers are thin and covered by the
offline-degradation behavior elsewhere; here we pin the resolution logic against
fixtures shaped like the real DCAT (`/data.json`) and DKAN metastore responses.
"""

from __future__ import annotations

import pytest

from kodex.connectors.datasets import (
    Distribution,
    download_csv,
    find_csv_distribution,
    find_datastore_resource_id,
)
from kodex.errors import FetchError


# --- DCAT shape: data.cms.gov/data.json -> {"dataset": [...]} -----------------
DCAT = {
    "dataset": [
        {
            "title": "Medicare Physician & Other Practitioners - by Provider and Service: 2022",
            "modified": "2024-05-01",
            "distribution": [
                {"mediaType": "text/csv", "downloadURL": "https://data.cms.gov/x/2022.csv", "title": "2022 CSV"},
            ],
        },
        {
            "title": "Medicare Physician & Other Practitioners - by Provider and Service: 2023",
            "modified": "2025-05-01",
            "distribution": [
                {"mediaType": "application/zip", "downloadURL": "https://data.cms.gov/x/2023.zip"},
                {"mediaType": "text/csv", "downloadURL": "https://data.cms.gov/x/2023.csv", "title": "2023 CSV"},
            ],
        },
        {"title": "Some Unrelated Dataset", "distribution": [{"mediaType": "text/csv", "downloadURL": "n.csv"}]},
    ]
}

# --- DKAN metastore shape: bare list, distributions wrapped in {"data": {...}} -
DKAN_PROVIDER = [
    {
        "title": "Complications and Deaths - Hospital",
        "modified": "2025-04-01",
        "distribution": [
            {"data": {"mediaType": "text/csv",
                      "downloadURL": "https://data.cms.gov/provider-data/sites/.../Complications.csv"}},
        ],
    },
    {
        "title": "Complications and Deaths - Hospital",
        "modified": "2024-04-01",  # older vintage, should lose to the newer one
        "distribution": [
            {"data": {"mediaType": "text/csv", "downloadURL": "https://old/Complications-2024.csv"}},
        ],
    },
]

DKAN_OPEN_PAYMENTS = [
    {
        "title": "General Payment Data - Detailed Dataset 2023 Reporting Year",
        "modified": "2024-06-30",
        "distribution": [
            {"data": {"identifier": "abc-2023-resource-id", "mediaType": "text/csv",
                      "downloadURL": "https://op/2023.csv"}},
        ],
    },
    {
        "title": "General Payment Data - Detailed Dataset 2022 Reporting Year",
        "modified": "2023-06-30",
        "distribution": [{"data": {"identifier": "abc-2022-resource-id"}}],
    },
]


# --------------------------------------------------------------------------
# CSV distribution resolution (DCAT)
# --------------------------------------------------------------------------
def test_find_csv_prefers_requested_year():
    dist = find_csv_distribution(DCAT, "Medicare Physician & Other Practitioners", year="2023")
    assert dist.url == "https://data.cms.gov/x/2023.csv"
    assert dist.media_type == "text/csv"
    assert dist.modified == "2025-05-01"


def test_find_csv_skips_non_csv_distributions():
    # 2023 dataset lists a .zip first; resolver must pick the CSV, not the zip.
    dist = find_csv_distribution(DCAT, "Medicare Physician & Other Practitioners", year="2023")
    assert dist.url.endswith(".csv")


def test_find_csv_no_year_picks_newest():
    dist = find_csv_distribution(DCAT, "Medicare Physician & Other Practitioners")
    assert dist.url == "https://data.cms.gov/x/2023.csv"  # newest 'modified'


def test_find_csv_unknown_title_raises():
    with pytest.raises(FetchError):
        find_csv_distribution(DCAT, "Nonexistent Dataset Title")


def test_find_csv_year_with_no_csv_raises():
    with pytest.raises(FetchError):
        find_csv_distribution(DCAT, "Medicare Physician & Other Practitioners", year="1999")


# --------------------------------------------------------------------------
# CSV distribution resolution (DKAN metastore, {"data": …} envelope)
# --------------------------------------------------------------------------
def test_find_csv_dkan_envelope_and_newest_vintage():
    dist = find_csv_distribution(DKAN_PROVIDER, "Complications and Deaths - Hospital")
    assert dist.url.endswith("Complications.csv")
    assert dist.modified == "2025-04-01"  # newer of the two vintages


# --------------------------------------------------------------------------
# Open Payments datastore resource id
# --------------------------------------------------------------------------
def test_find_open_payments_id_by_year():
    dist = find_datastore_resource_id(DKAN_OPEN_PAYMENTS, "General Payment Data", year="2023")
    assert dist.identifier == "abc-2023-resource-id"


def test_find_open_payments_id_year_filter_isolates_dataset():
    dist = find_datastore_resource_id(DKAN_OPEN_PAYMENTS, "General Payment Data", year="2022")
    assert dist.identifier == "abc-2022-resource-id"


def test_find_open_payments_missing_year_raises():
    with pytest.raises(FetchError):
        find_datastore_resource_id(DKAN_OPEN_PAYMENTS, "General Payment Data", year="2099")


# --------------------------------------------------------------------------
# download_csv guard
# --------------------------------------------------------------------------
def test_download_csv_requires_url():
    query_only = Distribution(dataset_title="x", url=None, identifier="rid")
    with pytest.raises(FetchError):
        download_csv(http=None, dist=query_only, dest_path="/tmp/x.csv", max_bytes=1)


# --------------------------------------------------------------------------
# End-to-end CLI wiring: resolve -> download -> ingest (fake HTTP, no network)
# --------------------------------------------------------------------------
import json
import textwrap

from kodex import cli
from kodex.db import DB

_MEDICARE_CSV = (
    "Rndrng_NPI,HCPCS_Cd,Tot_Srvcs,Tot_Benes,Avg_Sbmtd_Chrg,Avg_Mdcr_Pymt_Amt\n"
    "1111111111,22856,12,10,50000,15000\n"
    "1111111111,99213,400,300,200,80\n"   # non-ADR row, must be filtered out
    "2222222222,22857,5,5,60000,18000\n"
)


class _FakeResp:
    def __init__(self, text): self.text = text


class _FakeHttp:
    """Serves the DCAT catalog for the index GET and a tiny CSV for the stream."""
    def __init__(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def get(self, url, params=None):
        return _FakeResp(json.dumps(DCAT))
    def stream_to_file(self, url, dest_path, max_bytes):
        from pathlib import Path
        Path(dest_path).write_text(_MEDICARE_CSV)
        return len(_MEDICARE_CSV)


def test_fetch_bulk_resolves_downloads_and_ingests(tmp_path, monkeypatch):
    db_path = tmp_path / "k.sqlite"
    csv_dest = tmp_path / "bulk" / "medicare.csv"
    cfg = tmp_path / "config.yaml"
    cfg.write_text(textwrap.dedent(f"""
        procedure:
          cpt_codes: ["22856", "22857"]
        scoring:
          quality_weights: {{board_certified: 1.0}}
        catalogs:
          cms_data_json: "https://data.cms.gov/data.json"
          medicare_title: "Medicare Physician & Other Practitioners - by Provider and Service"
          medicare_year: "2023"
        bulk_data:
          medicare_csv: "{csv_dest}"
        run:
          db_path: "{db_path}"
    """))

    monkeypatch.setattr(cli, "HttpClient", _FakeHttp)
    rc = cli.main(["fetch-bulk", "--only", "medicare", "--config", str(cfg)])
    assert rc == 0
    assert csv_dest.exists()

    with DB(str(db_path)) as db:
        rows = db.medicare_for("1111111111", ["22856", "22857"])
        assert len(rows) == 1               # only the ADR row, not 99213
        assert rows[0]["tot_srvcs"] == 12
        assert db.medicare_for("2222222222", ["22857"])[0]["tot_srvcs"] == 5

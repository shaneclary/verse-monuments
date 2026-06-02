"""MRF cost parsing (Spec §10 Phase 4).

Covers both schema adapters (CMS JSON template + tall CSV), CPT filtering,
negotiated-range derivation, discovery-file URL extraction, graceful degradation
on bad input, and — importantly — that streaming keeps memory FLAT on a large
file (Spec §3.4: "never load a multi-GB file into memory").
"""

from __future__ import annotations

import json
import os
import shutil
import tracemalloc
from pathlib import Path

import pytest

from kodex.connectors.mrf_cost import (
    deserialize_result,
    discover_mrf_urls,
    fetch_facility_cost,
    parse_mrf_csv,
    parse_mrf_file,
    parse_mrf_json,
    serialize_result,
)
from kodex.db import DB
from kodex.errors import SchemaError
from kodex.models import Facility

FIX = Path(__file__).parent / "fixtures"
CPTS = ["22856", "22858", "22857", "22860"]


# --------------------------------------------------------------------------
# JSON adapter
# --------------------------------------------------------------------------
def test_parse_json_extracts_only_adr_cpts():
    res = parse_mrf_json(str(FIX / "mrf_sample.json"), CPTS)
    assert set(res.prices) == {"22856", "22857"}   # 27447 (knee) excluded
    assert res.prices["22856"].cash == 31000
    assert res.prices["22856"].negotiated_min == 24000
    assert res.prices["22856"].negotiated_max == 48000


def test_parse_json_derives_negotiated_range_from_payers():
    # 22857 has no explicit minimum/maximum -> derived from payer dollars.
    res = parse_mrf_json(str(FIX / "mrf_sample.json"), CPTS)
    assert res.prices["22857"].cash == 42000
    assert res.prices["22857"].negotiated_min == 38000
    assert res.prices["22857"].negotiated_max == 41000


# --------------------------------------------------------------------------
# CSV adapter (skips metadata preamble rows)
# --------------------------------------------------------------------------
def test_parse_csv_extracts_only_adr_cpts():
    res = parse_mrf_csv(str(FIX / "mrf_sample.csv"), CPTS)
    assert set(res.prices) == {"22856", "22857"}
    assert res.prices["22856"].cash == 31000
    assert res.prices["22856"].negotiated_min == 24000
    assert res.prices["22856"].negotiated_max == 48000
    assert res.prices["22857"].cash == 42000


def test_dispatch_by_extension():
    assert parse_mrf_file(str(FIX / "mrf_sample.json"), CPTS).prices
    assert parse_mrf_file(str(FIX / "mrf_sample.csv"), CPTS).prices
    with pytest.raises(SchemaError):
        parse_mrf_file("something.txt", CPTS)


# --------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------
def test_discover_mrf_urls_prefers_data_files():
    body = (
        "This hospital complies with CMS price transparency.\n"
        "location: https://example-hospital.org/assets/123_standardcharges.json\n"
        "see also https://example-hospital.org/about\n"
    )
    urls = discover_mrf_urls(body)
    assert "https://example-hospital.org/assets/123_standardcharges.json" in urls
    assert urls[0].endswith(".json")


def test_discover_mrf_urls_fallback_to_any_url():
    body = "MRF here: https://example-hospital.org/charges-page"
    urls = discover_mrf_urls(body)
    assert urls == ["https://example-hospital.org/charges-page"]


# --------------------------------------------------------------------------
# Graceful degradation (Spec §11)
# --------------------------------------------------------------------------
def test_malformed_json_raises_schema_error(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"standard_charge_information": [ {"code_information": ')  # truncated
    with pytest.raises(SchemaError):
        parse_mrf_json(str(bad), CPTS)


def test_no_matching_cpts_returns_empty(tmp_path):
    doc = {
        "standard_charge_information": [
            {"code_information": [{"code": "99213", "type": "CPT"}],
             "standard_charges": [{"discounted_cash": 100}]}
        ]
    }
    f = tmp_path / "nomatch.json"
    f.write_text(json.dumps(doc))
    res = parse_mrf_json(str(f), CPTS)
    assert res.prices == {}


# --------------------------------------------------------------------------
# Memory stays flat on a large file (streaming proof, Spec §3.4)
# --------------------------------------------------------------------------
class _FakeResp:
    def __init__(self, text: str):
        self.text = text


class _FakeHttp:
    """Stands in for HttpClient: serves the discovery body and 'streams' the MRF
    by copying a local fixture into the destination temp file."""

    def __init__(self, body_path: str, discovery_body: str):
        self.body_path = body_path
        self.discovery_body = discovery_body

    def get(self, url, params=None):
        return _FakeResp(self.discovery_body)

    def stream_to_file(self, url, dest_path, max_bytes):
        shutil.copyfile(self.body_path, dest_path)
        return os.path.getsize(dest_path)


def test_serialize_roundtrip():
    res = parse_mrf_json(str(FIX / "mrf_sample.json"), CPTS)
    again = deserialize_result(serialize_result(res))
    assert again.prices["22856"].cash == res.prices["22856"].cash
    assert again.prices["22857"].negotiated_min == res.prices["22857"].negotiated_min


def test_online_then_offline_reproduces_mrf_cost(tmp_path):
    """Regression for review #2: an online fetch must cache the EXTRACTED prices
    so a later --offline run reproduces the same cost (no CacheMiss, no silent
    MRF_UNAVAILABLE drift)."""
    db = DB(str(tmp_path / "k.sqlite"))
    domain = "h.example.org"
    mrf_url = "https://h.example.org/standardcharges.json"
    http = _FakeHttp(str(FIX / "mrf_sample.json"), f"location: {mrf_url}\n")

    # 1) Online run populates the cache.
    f_online = Facility(ccn="050099", name="Test", zip="93401")
    fetch_facility_cost(db, http, f_online, CPTS, domain, offline=False)
    assert f_online.cost_source == "MRF"
    assert f_online.cash_price["22856"] == 31000

    # 2) Offline run (http=None) reproduces identical prices from cache alone.
    f_offline = Facility(ccn="050099", name="Test", zip="93401")
    fetch_facility_cost(db, None, f_offline, CPTS, domain, offline=True)
    assert f_offline.cost_source == "MRF"
    assert f_offline.cash_price == f_online.cash_price
    assert f_offline.negotiated_min == f_online.negotiated_min
    db.close()


def test_offline_without_cache_falls_back_unavailable(tmp_path):
    """Offline with nothing cached must degrade to MRF_UNAVAILABLE, not crash."""
    db = DB(str(tmp_path / "k.sqlite"))
    f = Facility(ccn="050098", name="Test", zip="93401")
    fetch_facility_cost(db, None, f, CPTS, "no-cache.example.org", offline=True)
    assert f.cost_source == "MRF_UNAVAILABLE"
    db.close()


def test_json_streaming_memory_flat(tmp_path):
    # Build a large MRF: 60k non-matching items + a couple of ADR items. On disk
    # this is several MB; a non-streaming json.load would hold it all in RAM.
    big = tmp_path / "big.json"
    with big.open("w") as fh:
        fh.write('{"standard_charge_information": [')
        first = True
        for i in range(60_000):
            if not first:
                fh.write(",")
            first = False
            fh.write(json.dumps({
                "description": f"filler procedure {i} with a longish description to add bytes",
                "code_information": [{"code": f"{100000 + i}", "type": "CPT"}],  # 6-digit, never a CPT
                "standard_charges": [{"setting": "inpatient", "discounted_cash": 1000 + i,
                                      "payers_information": [{"payer_name": "X", "plan_name": "Y",
                                                              "standard_charge_dollar": 900 + i}]}],
            }))
        # one real ADR row at the very end
        fh.write("," + json.dumps({
            "description": "Cervical ADR",
            "code_information": [{"code": "22856", "type": "CPT"}],
            "standard_charges": [{"setting": "outpatient", "discounted_cash": 30000,
                                  "minimum": 25000, "maximum": 40000}],
        }))
        fh.write("]}")

    size_mb = big.stat().st_size / 1e6
    assert size_mb > 5, f"fixture should be sizable to make the test meaningful (got {size_mb:.1f} MB)"

    tracemalloc.start()
    res = parse_mrf_json(str(big), CPTS)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert res.prices["22856"].cash == 30000
    peak_mb = peak / 1e6
    # Streaming: peak well under the file size. A json.load() would be >> file size.
    assert peak_mb < size_mb, f"peak {peak_mb:.1f} MB not below file {size_mb:.1f} MB — not streaming?"

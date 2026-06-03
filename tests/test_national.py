"""National (fly-anywhere) seeding + HCAHPS satisfaction signal.

Covers the pieces added for a client who will travel: ranking the Medicare table
to a national top-N, seeding providers by NPI from NPPES, ingesting the HCAHPS
patient-satisfaction dataset, and the (non-inverted) satisfaction sub-score.
"""

from __future__ import annotations

import json

from kodex.connectors import care_compare, nppes
from kodex.connectors.nppes import fetch_provider_by_npi
from kodex.db import DB
from kodex.models import Facility, MatrixRow, Provider
from kodex.scoring import ScoringContext, subscores


# --------------------------------------------------------------------------
# National ranking: top-N NPIs by Medicare ADR volume floor
# --------------------------------------------------------------------------
def test_top_npis_by_volume_ranks_and_limits(tmp_path):
    db = DB(str(tmp_path / "k.sqlite"))
    db.upsert_medicare([
        {"npi": "A", "cpt": "22856", "year": "CY2023", "tot_srvcs": 40, "tot_benes": 30,
         "avg_sbmtd_chrg": 1, "avg_mdcr_pymt": 1},
        {"npi": "A", "cpt": "22857", "year": "CY2023", "tot_srvcs": 10, "tot_benes": 8,
         "avg_sbmtd_chrg": 1, "avg_mdcr_pymt": 1},   # A total = 50
        {"npi": "B", "cpt": "22856", "year": "CY2023", "tot_srvcs": 25, "tot_benes": 20,
         "avg_sbmtd_chrg": 1, "avg_mdcr_pymt": 1},   # B total = 25
        {"npi": "C", "cpt": "99999", "year": "CY2023", "tot_srvcs": 999, "tot_benes": 1,
         "avg_sbmtd_chrg": 1, "avg_mdcr_pymt": 1},   # non-ADR CPT -> excluded
    ])
    ranked = db.top_npis_by_volume(["22856", "22857"], n=10)
    assert [npi for npi, _ in ranked] == ["A", "B"]   # C excluded, A before B
    assert ranked[0][1] == 50
    # Limit honored.
    assert db.top_npis_by_volume(["22856", "22857"], n=1) == [("A", 50)]
    db.close()


# --------------------------------------------------------------------------
# Seed-by-NPI: NPPES single-record lookup, reproducible offline from cache
# --------------------------------------------------------------------------
def test_fetch_provider_by_npi_offline(tmp_path):
    db = DB(str(tmp_path / "k.sqlite"))
    npi = "1234567890"
    payload = {"results": [{
        "number": npi,
        "basic": {"first_name": "Sam", "last_name": "Reyes", "credential": "MD",
                  "enumeration_date": "2008-03-01"},
        "taxonomies": [{"desc": "Orthopaedic Surgery, Orthopaedic Surgery of the Spine",
                        "primary": True}],
        "addresses": [{"address_purpose": "LOCATION", "address_1": "1 Spine Way",
                       "city": "Des Moines", "state": "IA", "postal_code": "503090000"}],
    }]}
    db.cache_put("nppes", f"number={npi}", json.dumps(payload))

    p = fetch_provider_by_npi(db, None, "https://nppes", npi, offline=True, current_year=2026)
    assert p is not None
    assert p.npi == npi and p.name == "Sam Reyes"
    assert p.state == "IA" and p.zip == "50309"
    assert p.years_in_practice_proxy == 18    # 2026 - 2008
    db.close()


def test_fetch_provider_by_npi_no_match_returns_none(tmp_path):
    db = DB(str(tmp_path / "k.sqlite"))
    db.cache_put("nppes", "number=000", json.dumps({"results": []}))
    assert fetch_provider_by_npi(db, None, "https://nppes", "000", offline=True) is None
    db.close()


# --------------------------------------------------------------------------
# HCAHPS satisfaction ingest + single-measure lookup
# --------------------------------------------------------------------------
def test_hcahps_ingest_and_measure_score(tmp_path):
    csv = tmp_path / "hcahps.csv"
    csv.write_text(
        "Facility ID,HCAHPS Measure ID,HCAHPS Answer Description,Patient Survey Star Rating\n"
        "050001,H_STAR_RATING,Summary star rating,4\n"
        "050002,H_STAR_RATING,Summary star rating,Not Applicable\n"
        "050001,H_COMP_1_STAR_RATING,Nurse communication,5\n"
    )
    db = DB(str(tmp_path / "k.sqlite"))
    n = care_compare.ingest_csv(db, str(csv), "satisfaction", as_of="CY2024")
    assert n == 3
    assert care_compare.measure_score(db, "050001", "H_STAR_RATING") == 4.0
    # "Not Applicable" -> None, never invented.
    assert care_compare.measure_score(db, "050002", "H_STAR_RATING") is None
    # Unset measure id -> None.
    assert care_compare.measure_score(db, "050001", "") is None
    db.close()


# --------------------------------------------------------------------------
# Satisfaction sub-score: higher star = higher score (NOT inverted)
# --------------------------------------------------------------------------
def test_satisfaction_subscore_not_inverted():
    p = Provider(npi="1", name="x")
    f_hi = Facility(ccn="A", name="A", satisfaction_measure=5.0)
    f_lo = Facility(ccn="B", name="B", satisfaction_measure=1.0)
    rows = [MatrixRow(provider=p, facility=f_hi), MatrixRow(provider=p, facility=f_lo)]
    ctx = ScoringContext.build(rows, years_cap=30)
    assert subscores(p, f_hi, ctx)["facility_satisfaction"] == 1.0   # best -> 1.0
    assert subscores(p, f_lo, ctx)["facility_satisfaction"] == 0.0   # worst -> 0.0
    # Missing -> None, excluded from the weighted sum.
    f_na = Facility(ccn="C", name="C")
    assert subscores(p, f_na, ctx)["facility_satisfaction"] is None

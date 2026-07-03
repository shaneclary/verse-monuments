"""PipelineProviderSource: real candidates from the KODEX connectors (offline).

Seeds a SQLite cache + operator rosters exactly as a real online run would have,
then proves the generalized search path produces real, correctly-mapped
Candidates (surgeon volume from Medicare, board cert from ABMS, facility measures
from Care Compare, cost from the FAIR Health fallback) and scores them end to end.
"""

from __future__ import annotations

import json

from kodex.config import Config
from kodex.connectors.pipeline_source import PipelineProviderSource
from kodex.db import DB
from kodex.matching import PatientContext, build_result
from kodex.registry import Registry


def _seed(tmp_path):
    reg = Registry.load()
    proc = reg.procedures["adr_spine"]
    cpt0 = proc.code_sets["cpt"][0]

    mi = tmp_path / "mi"
    mi.mkdir()
    (mi / "abms.csv").write_text(
        "npi,board_certified,board_name\n1010101010,true,ABOS\n2020202020,false,\n")
    (mi / "state_board.csv").write_text(
        "npi,license_active,disciplinary_flag,disciplinary_note\n1010101010,true,false,\n")
    (mi / "provider_facility.csv").write_text("npi,ccn\n1010101010,111111\n2020202020,222222\n")
    (mi / "facility_roster.csv").write_text(
        "ccn,name,state,zip,mrf_domain\n111111,Alpha Spine,IA,50309,\n222222,Beta Spine,CA,94110,\n")
    (mi / "fairhealth.csv").write_text(
        f"cpt,zip,estimate,as_of\n{cpt0},50309,30000,2026-01\n{cpt0},94110,45000,2026-01\n")

    db_path = tmp_path / "k.sqlite"
    with DB(str(db_path)) as db:
        db.upsert_medicare([
            {"npi": "1010101010", "cpt": cpt0, "year": "CY2024", "tot_srvcs": 80,
             "tot_benes": 60, "avg_sbmtd_chrg": 1, "avg_mdcr_pymt": 1},
            {"npi": "2020202020", "cpt": cpt0, "year": "CY2024", "tot_srvcs": 20,
             "tot_benes": 15, "avg_sbmtd_chrg": 1, "avg_mdcr_pymt": 1},
        ])
        for npi, first, last, st, zp in [
            ("1010101010", "Alpha", "Vela", "IA", "50309"),
            ("2020202020", "Beta", "Ortega", "CA", "94110"),
        ]:
            db.cache_put("nppes", f"number={npi}", json.dumps({"results": [{
                "number": npi,
                "basic": {"first_name": first, "last_name": last, "credential": "MD",
                          "enumeration_date": "2005-01-01"},
                "taxonomies": [{"desc": "Orthopaedic Surgery, Orthopaedic Surgery of the Spine",
                                "primary": True}],
                "addresses": [{"address_purpose": "LOCATION", "state": st, "postal_code": zp + "0000"}],
            }]}))
        db.upsert_care_compare([
            {"ccn": "111111", "measure_id": "PSI_90_SAFETY", "score": 0.8, "as_of": "CY2024"},
            {"ccn": "111111", "measure_id": "READM_30_HOSP_WIDE", "score": 12.0, "as_of": "CY2024"},
            {"ccn": "111111", "measure_id": "H_STAR_RATING", "score": 5.0, "as_of": "CY2024"},
            {"ccn": "222222", "measure_id": "PSI_90_SAFETY", "score": 1.2, "as_of": "CY2024"},
            {"ccn": "222222", "measure_id": "READM_30_HOSP_WIDE", "score": 16.0, "as_of": "CY2024"},
            {"ccn": "222222", "measure_id": "H_STAR_RATING", "score": 3.0, "as_of": "CY2024"},
        ])

    cfg = Config({
        "procedure": {"cpt_codes": proc.code_sets["cpt"]},
        "scoring": {"quality_weights": {"board_certified": 1.0}},
        "endpoints": {"nppes": "https://nppes.example"},
        "seeding": {"mode": "national_medicare_topn", "top_n": 10},
        "mrf": {"discovery_path": "/cms-hpt.txt", "max_download_bytes": 1000000},
        "manual_inputs": {
            "abms_csv": str(mi / "abms.csv"),
            "state_board_csv": str(mi / "state_board.csv"),
            "provider_facility_csv": str(mi / "provider_facility.csv"),
            "facility_roster_csv": str(mi / "facility_roster.csv"),
            "fairhealth_csv": str(mi / "fairhealth.csv"),
        },
        "run": {"db_path": str(db_path)},
    })
    return reg, proc, cfg


def test_pipeline_source_maps_real_signals(tmp_path):
    reg, proc, cfg = _seed(tmp_path)
    cands = PipelineProviderSource(cfg, offline=True).candidates(
        proc, reg, PatientContext(willing_to_travel=True))
    assert len(cands) == 2
    by = {c.provider_id: c for c in cands}

    a = by["1010101010"]
    assert a.provider_name == "Alpha Vela"
    assert a.facility_name == "Alpha Spine"
    assert a.signals["surgeon_procedure_volume"] == 80.0        # Medicare volume floor
    assert a.signals["board_certified"] == 1.0                  # ABMS manual
    assert a.signals["subspecialty_fellowship"] == 1.0          # inferred from spine taxonomy
    assert a.signals["facility_complication"] == 0.8            # Care Compare PSI-90
    assert a.signals["facility_satisfaction"] == 5.0            # HCAHPS star
    assert a.signals["years_in_practice"] >= 20.0              # from NPPES enumeration 2005 (date-dependent)
    assert a.cost_estimate == 30000.0                           # FAIR Health fallback (no MRF domain)
    assert "FAIR Health" in a.cost_label

    b = by["2020202020"]
    assert b.signals["board_certified"] == 0.0                  # not fabricated to True


def test_pipeline_source_ranks_end_to_end(tmp_path):
    reg, proc, cfg = _seed(tmp_path)
    cands = PipelineProviderSource(cfg, offline=True).candidates(
        proc, reg, PatientContext(willing_to_travel=True))
    result = build_result(cands, proc, reg)
    # Real data, honestly graded: ADR has no surgeon outcomes -> limited.
    assert result.confidence.grade == "limited"
    assert result.confidence.has_surgeon_outcomes is False
    # Alpha (higher volume, better facility measures, cheaper) should lead Beta.
    order = [s.candidate.provider_id for s in result.ranked if s.quality_score is not None]
    assert order[0] == "1010101010"
    assert result.ranked[0].on_frontier is True

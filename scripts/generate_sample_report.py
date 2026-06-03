#!/usr/bin/env python3
"""Generate a sample KODEX report from synthetic, clearly-labeled demo data.

This does NOT touch any real provider or pricing data. It seeds a throwaway
SQLite cache (NPPES page, Medicare volume, Care Compare measures, hospital MRF
bodies, and PubMed evidence) plus operator manual-input CSVs under
``examples/demo/`` exactly the way a real online run + operator lookups would
have — then runs the pipeline OFFLINE to prove the end-to-end path and produce
``out/sample_report.pdf``.

It deliberately exercises BOTH cost paths: most facilities get a streamed-MRF
cash price (cost_source=MRF), while one facility has no MRF and falls back to a
FAIR Health benchmark (cost_source=FAIRHEALTH).

Run:  PYTHONPATH=. python scripts/generate_sample_report.py
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from kodex.config import Config
from kodex.db import DB
from kodex import pipeline
from kodex.connectors import pubmed
from kodex.connectors.mrf_cost import parse_mrf_file, serialize_result

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "examples" / "demo"

# A client in Iowa willing to travel anywhere: synthetic surgeons sit in several
# states, and the candidate pool is seeded NATIONALLY by Medicare volume floor.
# npi, first, last, enum_date, ccn, board, fellowship, disciplinary, note, medicare_vol
SURGEONS = [
    ("1011111111", "Ada", "Vela", "2006-02-01", "160001", True, True, False, "", 65),
    ("1022222222", "Ben", "Ortega", "2012-09-01", "330002", True, False, True, "2017 license reprimand (synthetic)", 20),
    ("1033333333", "Cara", "Singh", "2016-05-01", "050003", True, False, False, "", 25),
    ("1044444444", "Dev", "Romero", "2001-01-01", "450004", True, True, False, "", 40),
    ("1055555555", "Eli", "Nakamura", "2015-11-01", "330002", True, False, False, "", 35),
]
# ccn, name, state, zip, PSI-90, readmission, HCAHPS_star, cash_price(22856)
#   (cash None -> no MRF, FAIR Health fallback)
FACILITIES = [
    ("160001", "Hawkeye Spine Institute", "IA", "50309", 0.78, 12.5, 4.0, 33000),
    ("330002", "Metro Disc Center", "NY", "10016", 1.10, 15.0, 3.0, 38000),
    ("050003", "Pacific Spine Hospital", "CA", "94110", 1.20, 16.0, 5.0, None),  # no MRF -> FAIR Health
    ("450004", "Lone Star Orthopedic", "TX", "77030", 0.70, 12.0, 4.0, 46000),
]


def build_manual_inputs() -> None:
    DEMO.mkdir(parents=True, exist_ok=True)
    (DEMO / "abms.csv").write_text(
        "npi,board_certified,board_name\n"
        + "".join(f"{s[0]},{str(s[5]).lower()},"
                  f"{'American Board of Orthopaedic Surgery' if s[5] else ''}\n" for s in SURGEONS)
    )
    (DEMO / "state_board.csv").write_text(
        "npi,license_active,disciplinary_flag,disciplinary_note\n"
        + "".join(f"{s[0]},true,{str(s[7]).lower()},{s[8]}\n" for s in SURGEONS)
    )
    # FAIR Health estimates ONLY for facilities without an MRF cash price.
    fh = ["cpt,zip,estimate,as_of"]
    for ccn, name, st, zp, psi, readm, sat, cash in FACILITIES:
        if cash is None:
            fh.append(f"22856,{zp},28000,2026-01")
    (DEMO / "fairhealth.csv").write_text("\n".join(fh) + "\n")
    (DEMO / "provider_facility.csv").write_text(
        "npi,ccn\n" + "".join(f"{s[0]},{s[4]}\n" for s in SURGEONS)
    )
    # Facilities WITH an MRF get a discovery domain; the no-MRF one is left blank.
    rr = ["ccn,name,state,zip,mrf_domain"]
    for ccn, name, st, zp, psi, readm, sat, cash in FACILITIES:
        domain = f"hospital-{ccn}.example.org" if cash is not None else ""
        rr.append(f"{ccn},{name},{st},{zp},{domain}")
    (DEMO / "facility_roster.csv").write_text("\n".join(rr) + "\n")


def make_config() -> Config:
    data = {
        "geography": {"state": "IA", "center_zip": "50309", "radius_miles": 100},
        "seeding": {"mode": "national_medicare_topn", "top_n": 5},
        "procedure": {"cpt_codes": ["22856"], "region": "cervical",
                      "procedure_label": "Cervical Artificial Disc Replacement (DEMO DATA)",
                      "cpt_descriptions": {"22856": "Total disc arthroplasty, cervical, single interspace"}},
        "provider_taxonomies": ["Orthopaedic Surgery"],
        "endpoints": {"nppes": "https://npiregistry.cms.hhs.gov/api/?version=2.1",
                      "open_payments": "https://openpaymentsdata.cms.gov/api/1/datastore/query",
                      "pubmed": "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"},
        "open_payments": {"dataset_id": "", "flag_manufacturers": []},
        "care_compare": {"complication_measure_id": "PSI_90_SAFETY",
                         "readmission_measure_id": "READM_30_HOSP_WIDE",
                         "satisfaction_measure_id": "H_STAR_RATING", "reporting_period": "CY2024"},
        "mrf": {"discovery_path": "/cms-hpt.txt", "max_download_bytes": 1000000},
        "api_keys": {"pubmed": ""},
        "rate_limits": {"default_rps": 5},
        "scoring": {"quality_weights": {
            "board_certified": 0.15, "fellowship_spine": 0.10, "medicare_adr_volume": 0.25,
            "facility_complication": 0.20, "facility_readmission": 0.10,
            "facility_satisfaction": 0.15, "years_in_practice": 0.05, "open_payments": 0.0},
            "disciplinary_penalty": 0.5, "min_completeness_to_score": 0.4,
            "years_cap": 30, "open_payments_in_score": False},
        "report": {"shortlist_size": 100,
                   "title": "KODEX — National ADR Cost vs. Quality (SAMPLE / SYNTHETIC DATA)",
                   "cash_pay_assumed": True},
        "manual_inputs": {
            "abms_csv": str(DEMO / "abms.csv"),
            "state_board_csv": str(DEMO / "state_board.csv"),
            "fairhealth_csv": str(DEMO / "fairhealth.csv"),
            "provider_facility_csv": str(DEMO / "provider_facility.csv"),
            "facility_roster_csv": str(DEMO / "facility_roster.csv"),
        },
        "run": {"offline": True, "db_path": str(DEMO / "kodex.sqlite"),
                "out_dir": str(ROOT / "out")},
    }
    return Config(data)


def _mrf_json(cash: float) -> str:
    return json.dumps({
        "hospital_name": "Demo Hospital", "last_updated_on": "2026-01-15", "version": "2.0.0",
        "standard_charge_information": [{
            "description": "Cervical artificial disc replacement, single level",
            "code_information": [{"code": "22856", "type": "CPT"}],
            "standard_charges": [{
                "setting": "outpatient", "gross_charge": cash * 2, "discounted_cash": cash,
                "minimum": cash * 0.85, "maximum": cash * 1.4,
                "payers_information": [
                    {"payer_name": "Aetna", "plan_name": "PPO", "standard_charge_dollar": cash * 0.95},
                    {"payer_name": "BCBS", "plan_name": "HMO", "standard_charge_dollar": cash * 1.1},
                ],
            }],
        }],
    })


def seed_cache(cfg: Config) -> None:
    fac_loc = {ccn: (st, zp) for ccn, name, st, zp, *_ in FACILITIES}
    npi_ccn = {s[0]: s[4] for s in SURGEONS}
    with DB(cfg.db_path) as db:
        # National seeding looks each NPI up individually (key "number=<npi>"),
        # so cache a single-result NPPES payload per surgeon — exactly what an
        # online run would have cached.
        for npi, first, last, enum, *_ in SURGEONS:
            st, zp = fac_loc.get(npi_ccn[npi], ("IA", "50309"))
            payload = {"result_count": 1, "results": [{
                "number": npi,
                "basic": {"first_name": first, "last_name": last, "credential": "MD",
                          "enumeration_date": enum},
                "taxonomies": [{"desc": "Orthopaedic Surgery, Orthopaedic Surgery of the Spine",
                                "primary": True, "state": st}],
                "addresses": [{"address_purpose": "LOCATION", "address_1": "1 Demo St",
                               "city": "Demo City", "state": st, "postal_code": zp}],
            }]}
            db.cache_put("nppes", f"number={npi}", json.dumps(payload))

        med = [{"npi": s[0], "cpt": "22856", "year": "CY2024", "tot_srvcs": s[9],
                "tot_benes": s[9], "avg_sbmtd_chrg": 50000, "avg_mdcr_pymt": 9000}
               for s in SURGEONS if s[9] > 0]
        if med:
            db.upsert_medicare(med)
        cc = []
        for ccn, name, st, zp, psi, readm, sat, cash in FACILITIES:
            cc.append({"ccn": ccn, "measure_id": "PSI_90_SAFETY", "score": psi, "as_of": "CY2024"})
            cc.append({"ccn": ccn, "measure_id": "READM_30_HOSP_WIDE", "score": readm, "as_of": "CY2024"})
            cc.append({"ccn": ccn, "measure_id": "H_STAR_RATING", "score": sat, "as_of": "CY2024"})
        db.upsert_care_compare(cc)

        # Seed the offline MRF path for facilities that have a cash price, exactly
        # as a real online run would: cache the cms-hpt.txt discovery body and the
        # EXTRACTED per-CPT prices (not the body). We run the real parser here so
        # the demo faithfully exercises the streaming-parse + price-cache path.
        for ccn, name, st, zp, psi, readm, sat, cash in FACILITIES:
            if cash is None:
                continue
            domain = f"hospital-{ccn}.example.org"
            mrf_url = f"https://{domain}/standardcharges.json"
            db.cache_put("cms_hpt", domain, f"location: {mrf_url}\n")
            tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
            tmp.write(_mrf_json(cash))
            tmp.close()
            try:
                result = parse_mrf_file(tmp.name, ["22856"])
            finally:
                os.unlink(tmp.name)
            db.cache_put("mrf_prices", mrf_url, serialize_result(result))

        # Synthetic PubMed evidence (clearly fake PMIDs) for the evidence section.
        pmids = ["90000001", "90000002"]
        term = pubmed.build_queries("cervical")[0]
        db.cache_put("pubmed_esearch", f"{term}|8",
                     json.dumps({"esearchresult": {"idlist": pmids}}))
        xml = (
            "<PubmedArticleSet>"
            "<PubmedArticle><MedlineCitation><PMID>90000001</PMID>"
            "<Article><ArticleTitle>Cervical disc arthroplasty vs. fusion: a systematic review "
            "(SYNTHETIC DEMO ENTRY)</ArticleTitle>"
            "<Journal><Title>Demo Spine Journal</Title>"
            "<JournalIssue><PubDate><Year>2025</Year></PubDate></JournalIssue></Journal>"
            "<Abstract><AbstractText>Across pooled cohorts, cervical ADR showed comparable or "
            "lower reoperation rates than fusion at mid-term follow-up. Figures are illustrative "
            "placeholders for this sample report.</AbstractText></Abstract>"
            "</Article></MedlineCitation></PubmedArticle>"
            "<PubmedArticle><MedlineCitation><PMID>90000002</PMID>"
            "<Article><ArticleTitle>Long-term outcomes of cervical total disc replacement "
            "(SYNTHETIC DEMO ENTRY)</ArticleTitle>"
            "<Journal><Title>Demo Journal of Orthopaedics</Title>"
            "<JournalIssue><PubDate><Year>2024</Year></PubDate></JournalIssue></Journal>"
            "<Abstract><AbstractText>Illustrative aggregate finding only; not attributable to any "
            "individual surgeon.</AbstractText></Abstract>"
            "</Article></MedlineCitation></PubmedArticle>"
            "</PubmedArticleSet>"
        )
        db.cache_put("pubmed_efetch", ",".join(pmids), xml)


def main() -> None:
    build_manual_inputs()
    cfg = make_config()
    seed_cache(cfg)
    out = pipeline.run(cfg, offline=True, out_path=str(ROOT / "out" / "sample_report.pdf"))
    print(f"Sample report written to {out}")


if __name__ == "__main__":
    main()

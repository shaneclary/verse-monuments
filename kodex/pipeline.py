"""Pipeline orchestration — the run sequence (Spec §8).

  1. Seed providers      -> NPPES                                   [network]
  2. Enrich volume       -> Medicare table (local SQLite)            [local]
  3. Enrich payments     -> Open Payments per NPI                    [network]
  4. Build facility list -> rosters (CCN map)                        [local]
  5. Facility quality    -> Care Compare (local SQLite)              [local]
  6. Facility cost       -> MRF (cms-hpt.txt, stream) + FAIR Health  [network]
  7. Merge manual inputs -> ABMS, state board CSVs                   [local]
  8. Procedure evidence  -> PubMed (aggregate)                       [network]
  9. Score               -> scoring.py (pure)                        [local]
 10. Pareto frontier     -> scoring.py                              [local]
 11. Report              -> report.py -> out/report_<date>.pdf       [local]

--offline skips the network steps and rebuilds from the SQLite cache; each
network step caches before scoring, so the report is reproducible offline.

Resilience stance: a single provider/facility whose network fetch fails (or whose
cache is absent in offline mode) is logged and left UNKNOWN — it does not abort
the whole batch. Seeding (step 1) is the exception: with no providers there is
nothing to report, so that failure is fatal and loud.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timezone

from .config import Config
from .connectors import (
    abms_manual,
    care_compare,
    fairhealth_manual,
    medicare_volume,
    nppes,
    open_payments,
    pubmed,
    roster,
    state_board_manual,
)
from .connectors.base import HttpClient
from .connectors.mrf_cost import fetch_facility_cost
from .db import DB
from .errors import CacheMiss, FetchError
from .models import Facility, MatrixRow, Provider, ReportBundle
from .report import render_pdf
from .scoring import score_rows


def _log(msg: str) -> None:
    print(f"[kodex] {msg}", file=sys.stderr)


def _warn(msg: str) -> None:
    print(f"[kodex][warn] {msg}", file=sys.stderr)


def run(config: Config, *, offline: bool | None = None, out_path: str | None = None) -> str:
    offline = config.offline if offline is None else offline
    cpts = config.cpt_codes
    db = DB(config.db_path)
    http = None if offline else HttpClient(rps=float(config.get("rate_limits", "default_rps", default=5)))

    try:
        # 1. Seed providers (fatal if this yields nothing) -----------------
        providers = _seed_providers(config, db, http, offline)
        if not providers:
            raise FetchError(
                "No providers seeded from NPPES. Check geography/taxonomy in config.yaml, "
                "or (offline) that the NPPES cache is populated."
            )
        _log(f"seeded {len(providers)} unique providers")

        # 2. Medicare volume (local) --------------------------------------
        for p in providers:
            vol, pay = medicare_volume.enrich_provider(db, p.npi, cpts)
            p.medicare_adr_volume, p.medicare_avg_payment = vol, pay

        # 3. Open Payments (network, optional) ----------------------------
        op_dataset = config.get("open_payments", "dataset_id", default="") or ""
        flag_mfrs = config.get("open_payments", "flag_manufacturers", default=[]) or []
        if op_dataset:
            for p in providers:
                try:
                    total, top = open_payments.fetch_for_npi(
                        db, http, config.endpoint("open_payments"), op_dataset, p.npi,
                        flag_mfrs, offline=offline,
                    )
                    p.open_payments_total, p.top_payers = total, top
                except (FetchError, CacheMiss) as exc:
                    _warn(f"Open Payments fetch failed for NPI {p.npi}: {exc}")

        # 4-6. Facilities: roster, quality, cost --------------------------
        facilities = _build_facilities(config, db, http, providers, cpts, offline)

        # 7. Manual inputs: ABMS + state board ----------------------------
        _merge_manual(config, providers)

        # 8. Procedure evidence (network) ---------------------------------
        evidence = []
        try:
            evidence = pubmed.gather_evidence(
                db, http, config.endpoint("pubmed"), config.region,
                api_key=config.get("api_keys", "pubmed", default="") or None,
                offline=offline,
            )
        except (FetchError, CacheMiss) as exc:
            _warn(f"PubMed evidence unavailable: {exc}")

        # FAIR Health benchmarks (manual) + fallback cost
        benchmarks = fairhealth_manual.load(config.manual_input("fairhealth_csv") or "")
        bench_lookup = fairhealth_manual.benchmark_lookup(benchmarks)

        # 9-10. Assemble rows + score + Pareto ----------------------------
        rows = _assemble_rows(providers, facilities, cpts, bench_lookup)
        score_rows(
            rows,
            cpts=cpts,
            weights=config.quality_weights,
            years_cap=config.years_cap,
            min_completeness=config.min_completeness_to_score,
            disciplinary_penalty=config.disciplinary_penalty,
            open_payments_in_score=config.open_payments_in_score,
        )
        rows = _rank_and_trim(rows, config.shortlist_size)

        # 11. Report -------------------------------------------------------
        bundle = _build_bundle(config, rows, evidence, benchmarks, offline)
        out_path = out_path or f"{config.out_dir}/report_{date.today().isoformat()}.pdf"
        render_pdf(bundle, out_path)
        _log(f"report written: {out_path}")
        return out_path
    finally:
        if http is not None:
            http.close()
        db.close()


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------
def _seed_providers(config: Config, db: DB, http, offline: bool) -> list[Provider]:
    by_npi: dict[str, Provider] = {}
    for taxonomy in config.taxonomies:
        try:
            found = nppes.search_providers(
                db, http, config.endpoint("nppes"),
                taxonomy=taxonomy, state=config.state or "",
                postal_code=None, offline=offline,
            )
        except (FetchError, CacheMiss) as exc:
            _warn(f"NPPES search failed for taxonomy {taxonomy!r}: {exc}")
            continue
        for p in found:
            by_npi.setdefault(p.npi, p)
    return list(by_npi.values())


def _build_facilities(config: Config, db: DB, http, providers, cpts, offline) -> dict[str, Facility]:
    roster_csv = config.manual_input("facility_roster_csv") or ""
    pf_csv = config.manual_input("provider_facility_csv") or ""
    facilities = roster.load_facilities(roster_csv)
    domains = roster.load_facility_domains(roster_csv)
    prov_fac = roster.load_provider_facility(pf_csv)

    # Link providers -> CCN
    for p in providers:
        if p.npi in prov_fac:
            p.primary_facility_ccn = prov_fac[p.npi]

    comp_id = config.get("care_compare", "complication_measure_id", default="")
    readm_id = config.get("care_compare", "readmission_measure_id", default="")
    cc_as_of = config.get("care_compare", "reporting_period", default=None)

    # Enrich each unique facility once (quality local; cost network).
    needed_ccns = {p.primary_facility_ccn for p in providers if p.primary_facility_ccn}
    for ccn in needed_ccns:
        fac = facilities.get(ccn) or Facility(ccn=ccn, name=f"Facility {ccn}")
        comp, readm = care_compare.enrich_facility(db, ccn, comp_id, readm_id)
        fac.complication_measure, fac.readmission_measure = comp, readm
        fac.quality_as_of = cc_as_of
        try:
            fetch_facility_cost(
                db, http, fac, cpts, domains.get(ccn),
                offline=offline,
                discovery_path=config.get("mrf", "discovery_path", default="/cms-hpt.txt"),
                max_bytes=int(config.get("mrf", "max_download_bytes", default=3_000_000_000)),
            )
        except (FetchError, CacheMiss) as exc:
            _warn(f"MRF cost failed for CCN {ccn}: {exc}")
            fac.cost_source = "MRF_UNAVAILABLE"
        facilities[ccn] = fac
    return facilities


def _merge_manual(config: Config, providers: list[Provider]) -> None:
    abms = abms_manual.load(config.manual_input("abms_csv") or "")
    board = state_board_manual.load(config.manual_input("state_board_csv") or "")
    for p in providers:
        if p.npi in abms:
            p.board_certified = abms[p.npi]["board_certified"]
            p.board_name = abms[p.npi]["board_name"]
            # Spine fellowship inferred from taxonomy when not separately provided.
            if p.fellowship_spine is None and p.taxonomy and "spine" in p.taxonomy.lower():
                p.fellowship_spine = True
        if p.npi in board:
            p.license_active = board[p.npi]["license_active"]
            p.disciplinary_flag = board[p.npi]["disciplinary_flag"]
            p.disciplinary_note = board[p.npi]["disciplinary_note"]


def _assemble_rows(providers, facilities, cpts, bench_lookup) -> list[MatrixRow]:
    rows: list[MatrixRow] = []
    for p in providers:
        ccn = p.primary_facility_ccn
        fac = facilities.get(ccn) if ccn else None
        if fac is None:
            fac = Facility(ccn=ccn or "UNKNOWN", name="UNKNOWN (no facility linked)")
        # FAIR Health fallback when MRF gave no cash price (Spec §3.4 / §3.6).
        if fac.cost_source != "MRF" and fac.zip:
            filled = False
            for cpt in cpts:
                est = bench_lookup.get((cpt, fac.zip))
                if est is not None:
                    fac.cash_price[cpt] = est
                    filled = True
            if filled:
                fac.cost_source = "FAIRHEALTH"
        rows.append(MatrixRow(provider=p, facility=fac))
    return rows


def _rank_and_trim(rows: list[MatrixRow], shortlist_size: int) -> list[MatrixRow]:
    """Order for the report: frontier first, then by quality proxy (UNKNOWN last),
    then by cost. We never collapse to a single ranking number — this is only
    presentation order (Spec §6)."""
    def key(r: MatrixRow):
        return (
            0 if r.on_pareto_frontier else 1,
            -(r.quality_proxy_score if r.quality_proxy_score is not None else -1),
            r.cost_estimate if r.cost_estimate is not None else float("inf"),
        )
    return sorted(rows, key=key)[:shortlist_size]


def _build_bundle(config, rows, evidence, benchmarks, offline) -> ReportBundle:
    cs = {
        "title": config.get("report", "title", default="KODEX — ADR Cost vs. Quality Matrix"),
        "procedure_label": config.procedure_label,
        "state": config.state,
        "center_zip": config.center_zip,
        "radius_miles": config.radius_miles,
        "cpt_descriptions": config.cpt_descriptions,
    }
    source_notes = [
        {"source": "NPPES NPI Registry", "as_of": date.today().isoformat(),
         "limitation": "Credential string is self-reported free text; not board verification."},
        {"source": "Medicare Physician & Other Practitioners", "as_of": config.get("care_compare", "reporting_period", default="CY2024"),
         "limitation": "Original Medicare FFS only. ADR patients skew younger — volume is a FLOOR, not a count."},
        {"source": "CMS Open Payments", "as_of": "program-year dependent",
         "limitation": "Transparency signal only; industry ties are common and not inherently bad. Display-only by default."},
        {"source": "Hospital Price Transparency MRFs", "as_of": "per-hospital",
         "limitation": "Facility component only; not the all-in episode. Schemas/compliance vary; UNKNOWN where unavailable."},
        {"source": "CMS Care Compare", "as_of": config.get("care_compare", "reporting_period", default="CY2024"),
         "limitation": "FACILITY-level measures, NOT surgeon-level."},
        {"source": "FAIR Health (manual)", "as_of": "operator-entered",
         "limitation": "Consumer benchmark; used as fallback when an MRF is unavailable."},
        {"source": "ABMS / state board (manual)", "as_of": "operator-entered",
         "limitation": "One-at-a-time manual verification; blank renders as UNKNOWN."},
        {"source": "PubMed E-utilities", "as_of": date.today().isoformat(),
         "limitation": "AGGREGATE procedure evidence only; never attributed to an individual surgeon."},
    ]
    return ReportBundle(
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds") + (" (offline)" if offline else ""),
        config_summary=cs,
        rows=rows,
        evidence=evidence,
        benchmarks=benchmarks,
        source_notes=source_notes,
        weights_used=config.quality_weights,
    )

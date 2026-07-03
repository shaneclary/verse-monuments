"""PipelineProviderSource — REAL candidates from the KODEX connectors.

This is the first non-synthetic ProviderSource: it produces `Candidate`s for a
registry procedure using the exact connectors `kodex run` uses — Medicare volume,
NPPES credentials, operator rosters, Care Compare measures, hospital MRF cost,
FAIR Health fallback — reading from the SQLite cache + bulk tables so it runs
offline. The bridge from those procedure-specific enrichments to the generic
signal ids the scorer understands is `procedure.facility_signal_measures` (facility
signals) plus a fixed surgeon-signal mapping.

Offline by default (reads the cache a prior online run populated). Pass an
HttpClient + offline=False to refresh from the network where reachable.
"""

from __future__ import annotations

from ..config import Config
from ..errors import CacheMiss, FetchError
from ..matching import Candidate, PatientContext
from ..models import Facility, Provider
from ..registry import Procedure, Registry
from . import (
    abms_manual,
    care_compare,
    fairhealth_manual,
    medicare_volume,
    nppes,
    roster,
    state_board_manual,
)
from .mrf_cost import fetch_facility_cost


def _b(v: bool | None) -> float | None:
    return None if v is None else (1.0 if v else 0.0)


def _f(v) -> float | None:
    return float(v) if v is not None else None


class PipelineProviderSource:
    def __init__(self, config: Config, *, offline: bool = True, http=None):
        self.config = config
        self.offline = offline
        self.http = http

    # -- seeding ---------------------------------------------------------
    def _seed(self, db, procedure: Procedure, context: PatientContext) -> list[Provider]:
        cfg = self.config
        cpts = procedure.code_sets.get("cpt", [])
        top_n = int(cfg.get("seeding", "top_n", default=50))
        ranked = db.top_npis_by_volume(cpts, top_n)   # national volume-floor ranking
        providers: list[Provider] = []
        for npi, _vol in ranked:
            p: Provider | None = None
            try:
                p = nppes.fetch_provider_by_npi(
                    db, self.http, cfg.endpoint("nppes"), npi, offline=self.offline
                )
            except (FetchError, CacheMiss):
                p = None
            providers.append(p or Provider(npi=npi, name=f"NPI {npi}"))
        return providers

    # -- signal mapping --------------------------------------------------
    def _map_signals(self, p: Provider, fac: Facility | None, db, meas_map: dict[str, str]) -> dict[str, float | None]:
        signals: dict[str, float | None] = {
            "surgeon_procedure_volume": _f(p.medicare_adr_volume),
            "board_certified": _b(p.board_certified),
            "subspecialty_fellowship": _b(p.fellowship_spine),
            "years_in_practice": _f(p.years_in_practice_proxy),
        }
        for signal_id, measure_id in (meas_map or {}).items():
            signals[signal_id] = care_compare.measure_score(db, fac.ccn, measure_id) if fac else None
        return signals

    def _cost(self, fac: Facility | None, cpts: list[str], benchmarks) -> tuple[float | None, str]:
        if fac is None:
            return None, "no facility linked"
        total, priced = 0.0, False
        for cpt in cpts:
            price = fac.cash_price.get(cpt)
            if price is not None:
                total += price
                priced = True
        if priced and fac.cost_source == "MRF":
            return total, "hospital facility cash price (MRF)"
        if fac.zip:  # FAIR Health fallback when no MRF cash price
            fb_total, fb_any = 0.0, False
            for cpt in cpts:
                est = benchmarks.get((cpt, fac.zip))
                if est is not None:
                    fb_total += est
                    fb_any = True
            if fb_any:
                return fb_total, "FAIR Health benchmark (facility MRF unavailable)"
        return (total if priced else None), ("facility cash price" if priced else "not available")

    # -- main ------------------------------------------------------------
    def candidates(self, procedure: Procedure, registry: Registry, context: PatientContext) -> list[Candidate]:
        cfg = self.config
        cpts = procedure.code_sets.get("cpt", [])
        if not cpts:
            return []
        context = context or PatientContext()

        # Import DB lazily to keep this module import-cheap.
        from ..db import DB

        with DB(cfg.db_path) as db:
            providers = self._seed(db, procedure, context)
            if not providers:
                return []

            abms = abms_manual.load(cfg.manual_input("abms_csv") or "")
            board = state_board_manual.load(cfg.manual_input("state_board_csv") or "")
            roster_csv = cfg.manual_input("facility_roster_csv") or ""
            facilities = roster.load_facilities(roster_csv)
            domains = roster.load_facility_domains(roster_csv)
            prov_fac = roster.load_provider_facility(cfg.manual_input("provider_facility_csv") or "")
            benchmarks = fairhealth_manual.benchmark_lookup(
                fairhealth_manual.load(cfg.manual_input("fairhealth_csv") or "")
            )
            meas_map = procedure.facility_signal_measures

            fac_cache: dict[str, Facility] = {}
            out: list[Candidate] = []
            for p in providers:
                # Surgeon enrichments
                vol, _pay = medicare_volume.enrich_provider(db, p.npi, cpts)
                p.medicare_adr_volume = vol
                if p.npi in abms:
                    p.board_certified = abms[p.npi]["board_certified"]
                if p.fellowship_spine is None and p.taxonomy and "spine" in p.taxonomy.lower():
                    p.fellowship_spine = True
                if p.npi in board:
                    p.disciplinary_flag = board[p.npi]["disciplinary_flag"]

                # Facility (once per CCN): cost via MRF, cached
                ccn = prov_fac.get(p.npi)
                fac = None
                if ccn:
                    fac = fac_cache.get(ccn)
                    if fac is None:
                        fac = facilities.get(ccn) or Facility(ccn=ccn, name=f"Facility {ccn}")
                        try:
                            fetch_facility_cost(
                                db, self.http, fac, cpts, domains.get(ccn),
                                offline=self.offline,
                                discovery_path=cfg.get("mrf", "discovery_path", default="/cms-hpt.txt"),
                                max_bytes=int(cfg.get("mrf", "max_download_bytes", default=3_000_000_000)),
                            )
                        except (FetchError, CacheMiss):
                            fac.cost_source = "MRF_UNAVAILABLE"
                        fac_cache[ccn] = fac

                cost, cost_label = self._cost(fac, cpts, benchmarks)
                loc = None
                if fac and (fac.state or fac.zip):
                    loc = " ".join(x for x in [fac.state, fac.zip] if x)
                elif p.state or p.zip:
                    loc = " ".join(x for x in [p.state, p.zip] if x)
                out.append(Candidate(
                    provider_id=p.npi,
                    provider_name=p.name,
                    facility_name=fac.name if fac else None,
                    location=loc,
                    signals=self._map_signals(p, fac, db, meas_map),
                    cost_estimate=cost,
                    cost_label=cost_label,
                ))
            return out

"""Pydantic v2 schemas for KODEX (Spec §5).

Design rule: every field that can be unknown IS Optional and defaults to None.
The report renders None as ``UNKNOWN``. KODEX never invents a number to fill a
gap — missing data stays missing and is surfaced honestly.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Provider(BaseModel):
    """A surgeon. Identity/volume/payments come from public datasets; board,
    license, and fellowship come from manual-entry adapters (Spec §3.7-3.8)."""

    npi: str
    name: str
    credential: str | None = None
    taxonomy: str | None = None
    address: str | None = None
    state: str | None = None
    zip: str | None = None
    years_in_practice_proxy: int | None = None     # from NPPES enumeration date

    board_certified: bool | None = None            # ABMS manual (§3.7)
    board_name: str | None = None
    fellowship_spine: bool | None = None           # manual / taxonomy
    license_active: bool | None = None             # state board manual (§3.8)
    disciplinary_flag: bool | None = None          # state board manual
    disciplinary_note: str | None = None

    medicare_adr_volume: int | None = None         # Medicare FFS only — a FLOOR, not a count (§3.2)
    medicare_avg_payment: float | None = None
    open_payments_total: float | None = None       # transparency signal (§3.3)
    top_payers: list[str] = Field(default_factory=list)

    primary_facility_ccn: str | None = None        # link to Facility


class Facility(BaseModel):
    """A hospital/ASC. Cost is facility-component-only (MRF); quality measures
    are facility-level, NOT surgeon-level (Spec §3.4-3.5)."""

    ccn: str                                        # CMS Certification Number
    name: str
    state: str | None = None
    zip: str | None = None

    cash_price: dict[str, float] = Field(default_factory=dict)        # {cpt: price}
    negotiated_min: dict[str, float] = Field(default_factory=dict)    # {cpt: price}
    negotiated_max: dict[str, float] = Field(default_factory=dict)    # {cpt: price}
    cost_source: str = "MRF_UNAVAILABLE"            # "MRF" | "MRF_UNAVAILABLE" | "FAIRHEALTH"
    cost_as_of: str | None = None                   # date string for the appendix

    complication_measure: float | None = None       # facility-level, NOT surgeon-level
    readmission_measure: float | None = None
    quality_as_of: str | None = None


class Evidence(BaseModel):
    """One aggregate procedure-evidence item from PubMed (Spec §3.9).

    Informs the PROCEDURE question only — never attributed to a surgeon."""

    pmid: str
    title: str
    year: int | None = None
    journal: str | None = None
    finding: str | None = None


class MatrixRow(BaseModel):
    """One (surgeon × facility) point on the cost-vs-quality matrix (Spec §5/§6)."""

    provider: Provider
    facility: Facility

    cost_estimate: float | None = None              # episode estimate (label components)
    cost_is_facility_only: bool = True
    cost_components: dict[str, float | None] = Field(default_factory=dict)

    quality_proxy_score: float | None = None        # 0-1, None if too sparse
    proxy_components: dict[str, float | None] = Field(default_factory=dict)  # per-signal contribution
    quality_note: str | None = None                 # e.g. "insufficient data to score"

    on_pareto_frontier: bool = False
    data_completeness: float = 0.0                  # 0-1, fraction of signals present


class Benchmark(BaseModel):
    """Geographic cost benchmark from FAIR Health manual entry (Spec §3.6)."""

    cpt: str
    zip: str
    estimate: float
    source: str = "FAIRHEALTH"
    as_of: str | None = None


class ReportBundle(BaseModel):
    """Everything report.py needs to render the deliverable (Spec §9)."""

    generated_at: str
    config_summary: dict
    rows: list[MatrixRow]
    evidence: list[Evidence] = Field(default_factory=list)
    benchmarks: list[Benchmark] = Field(default_factory=list)
    source_notes: list[dict] = Field(default_factory=list)   # {source, as_of, limitation}
    weights_used: dict = Field(default_factory=dict)

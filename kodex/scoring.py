"""Transparent, configurable scoring (Spec §6).

Pure functions, no I/O — so they are deterministic and unit-testable. Every
weight comes from config.yaml; every per-signal contribution is returned so the
report can show the math and nothing is a black box.

Key rules enforced here:
  * Missing signal  -> EXCLUDED, weights renormalized over present signals.
                       Never imputed (Spec §6).
  * Too sparse      -> quality_proxy_score = None, row flagged
                       "insufficient data to score" (completeness < threshold).
  * Disciplinary    -> fixed penalty applied AFTER the weighted sum, clamped to
                       [0,1]. The note is always surfaced regardless of score.
  * Normalization   -> volume + facility measures are min-max across the
                       *shortlist* (relative), because absolute counts are
                       Medicare-FFS-only floors. Years use an absolute cap.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .models import Facility, MatrixRow, Provider

# The six core quality signals that count toward data_completeness. Open Payments
# is deliberately excluded — it is a transparency display, off by default (§3.3).
CORE_SIGNALS = (
    "board_certified",
    "fellowship_spine",
    "medicare_adr_volume",
    "facility_complication",
    "facility_readmission",
    "years_in_practice",
)


def normalize_minmax(value: float, lo: float, hi: float) -> float:
    """Min-max to [0,1]. Degenerate range (hi<=lo) -> 0.5 (neutral): with no
    spread across the shortlist we cannot differentiate, so we neither reward
    nor punish."""
    if hi <= lo:
        return 0.5
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))


@dataclass
class ScoringContext:
    """Shortlist-relative normalization bounds, computed once across all rows."""

    volume_log_lo: float
    volume_log_hi: float
    complication_lo: float
    complication_hi: float
    readmission_lo: float
    readmission_hi: float
    open_payments_lo: float
    open_payments_hi: float
    years_cap: int

    @staticmethod
    def _bounds(values: list[float]) -> tuple[float, float]:
        if not values:
            return (0.0, 0.0)
        return (min(values), max(values))

    @classmethod
    def build(cls, rows: list[MatrixRow], years_cap: int) -> "ScoringContext":
        vols, comps, readms, pays = [], [], [], []
        for r in rows:
            p, f = r.provider, r.facility
            if p.medicare_adr_volume is not None:
                vols.append(math.log1p(max(0, p.medicare_adr_volume)))
            if f.complication_measure is not None:
                comps.append(f.complication_measure)
            if f.readmission_measure is not None:
                readms.append(f.readmission_measure)
            if p.open_payments_total is not None:
                pays.append(p.open_payments_total)
        vlo, vhi = cls._bounds(vols)
        clo, chi = cls._bounds(comps)
        rlo, rhi = cls._bounds(readms)
        plo, phi = cls._bounds(pays)
        return cls(vlo, vhi, clo, chi, rlo, rhi, plo, phi, years_cap)


def subscores(provider: Provider, facility: Facility, ctx: ScoringContext) -> dict[str, float | None]:
    """Each signal mapped to a 0-1 sub-score (pre-weighting). None = missing."""
    p, f = provider, facility
    out: dict[str, float | None] = {}

    out["board_certified"] = (None if p.board_certified is None else (1.0 if p.board_certified else 0.0))
    out["fellowship_spine"] = (None if p.fellowship_spine is None else (1.0 if p.fellowship_spine else 0.0))

    if p.medicare_adr_volume is None:
        out["medicare_adr_volume"] = None
    else:
        out["medicare_adr_volume"] = normalize_minmax(
            math.log1p(max(0, p.medicare_adr_volume)), ctx.volume_log_lo, ctx.volume_log_hi
        )

    # Facility measures: invert so LOWER complication/readmission -> HIGHER score.
    if f.complication_measure is None:
        out["facility_complication"] = None
    else:
        out["facility_complication"] = 1.0 - normalize_minmax(
            f.complication_measure, ctx.complication_lo, ctx.complication_hi
        )
    if f.readmission_measure is None:
        out["facility_readmission"] = None
    else:
        out["facility_readmission"] = 1.0 - normalize_minmax(
            f.readmission_measure, ctx.readmission_lo, ctx.readmission_hi
        )

    # Years: absolute cap then linear scale; a 40-year tenure cannot dominate.
    if p.years_in_practice_proxy is None:
        out["years_in_practice"] = None
    else:
        capped = min(max(0, p.years_in_practice_proxy), ctx.years_cap)
        out["years_in_practice"] = capped / ctx.years_cap if ctx.years_cap else 0.0

    # Open Payments (off by default): less concentration of $ -> slightly higher.
    if p.open_payments_total is None:
        out["open_payments"] = None
    else:
        out["open_payments"] = 1.0 - normalize_minmax(
            p.open_payments_total, ctx.open_payments_lo, ctx.open_payments_hi
        )

    return out


def cost_presence(facility: Facility) -> float:
    """How 'present' is this row's cost, for completeness accounting (§6).
    MRF = full, FAIR Health estimate = half (reduces completeness), missing = 0."""
    return {"MRF": 1.0, "FAIRHEALTH": 0.5}.get(facility.cost_source, 0.0)


def data_completeness(provider: Provider, facility: Facility) -> float:
    """Fraction of signals present: the six core quality signals + cost (§5/§6)."""
    present = sum(1 for s in CORE_SIGNALS if _signal_present(provider, facility, s))
    return (present + cost_presence(facility)) / (len(CORE_SIGNALS) + 1)


def _signal_present(provider: Provider, facility: Facility, signal: str) -> bool:
    mapping = {
        "board_certified": provider.board_certified,
        "fellowship_spine": provider.fellowship_spine,
        "medicare_adr_volume": provider.medicare_adr_volume,
        "facility_complication": facility.complication_measure,
        "facility_readmission": facility.readmission_measure,
        "years_in_practice": provider.years_in_practice_proxy,
    }
    return mapping[signal] is not None


def quality_proxy(
    provider: Provider,
    facility: Facility,
    ctx: ScoringContext,
    weights: dict[str, float],
    *,
    min_completeness: float,
    disciplinary_penalty: float,
    open_payments_in_score: bool,
) -> tuple[float | None, dict[str, float | None], float, str | None]:
    """Return (score|None, per-signal contributions, completeness, note).

    Renormalizes weights over present signals; None when too sparse; disciplinary
    penalty applied after the weighted sum and clamped to [0,1]."""
    subs = subscores(provider, facility, ctx)
    completeness = data_completeness(provider, facility)

    # Which signals participate in the weighted sum.
    scoring_keys = list(CORE_SIGNALS)
    if open_payments_in_score:
        scoring_keys.append("open_payments")

    contributions: dict[str, float | None] = {}
    weight_present = 0.0
    for key in scoring_keys:
        w = float(weights.get(key, 0.0) or 0.0)
        s = subs.get(key)
        if s is None or w <= 0.0:
            contributions[key] = None
            continue
        weight_present += w

    note: str | None = None

    if weight_present <= 0.0:
        # No weighted signal present at all -> cannot score.
        for k in scoring_keys:
            contributions.setdefault(k, None)
        return None, contributions, completeness, "no weighted signals present"

    # Renormalize over present weights, record each signal's contribution.
    weighted = 0.0
    for key in scoring_keys:
        w = float(weights.get(key, 0.0) or 0.0)
        s = subs.get(key)
        if s is None or w <= 0.0:
            continue
        norm_w = w / weight_present
        contrib = norm_w * s
        contributions[key] = contrib
        weighted += contrib

    # Disciplinary penalty AFTER the weighted sum (Spec §6). Always recorded.
    if provider.disciplinary_flag:
        weighted -= disciplinary_penalty
        contributions["_disciplinary_penalty"] = -disciplinary_penalty
    score = max(0.0, min(1.0, weighted))

    if completeness < min_completeness:
        note = f"insufficient data to score (completeness {completeness:.2f} < {min_completeness:.2f})"
        return None, contributions, completeness, note

    return score, contributions, completeness, note


def cost_estimate(facility: Facility, cpts: list[str]) -> tuple[float | None, dict[str, float | None], bool]:
    """Sum facility cash price across the requested CPT bundle (Spec §6 cost axis).

    Returns (total|None, per-cpt components, cost_is_facility_only). Components
    with no MRF price render as UNKNOWN. If NONE of the CPTs priced, total is
    None — KODEX does not invent a number."""
    components: dict[str, float | None] = {}
    total = 0.0
    any_priced = False
    for cpt in cpts:
        price = facility.cash_price.get(cpt)
        components[cpt] = price
        if price is not None:
            total += price
            any_priced = True
    return (total if any_priced else None), components, True


def cost_score(value: float | None, all_values: list[float]) -> float | None:
    """0-1 cost score: lower cash price = better (inverted min-max). For ranking
    only — the matrix X-axis uses raw dollars so humans read $ (Spec §6)."""
    if value is None or not all_values:
        return None
    lo, hi = min(all_values), max(all_values)
    return 1.0 - normalize_minmax(value, lo, hi)


def mark_pareto_frontier(rows: list[MatrixRow]) -> None:
    """Set on_pareto_frontier on each row in place.

    Axes: X = cost (lower better), Y = quality_proxy_score (higher better). A row
    is on the frontier if no OTHER row dominates it — i.e. is cheaper-or-equal AND
    higher-or-equal proxy, and strictly better on at least one axis. Rows missing
    either coordinate cannot be placed and are left off the frontier."""
    placeable = [
        r for r in rows
        if r.cost_estimate is not None and r.quality_proxy_score is not None
    ]
    for r in rows:
        r.on_pareto_frontier = False
    for a in placeable:
        dominated = False
        for b in placeable:
            if b is a:
                continue
            cheaper_eq = b.cost_estimate <= a.cost_estimate
            better_eq = b.quality_proxy_score >= a.quality_proxy_score
            strictly = (b.cost_estimate < a.cost_estimate) or (
                b.quality_proxy_score > a.quality_proxy_score
            )
            if cheaper_eq and better_eq and strictly:
                dominated = True
                break
        a.on_pareto_frontier = not dominated


def score_rows(
    rows: list[MatrixRow],
    *,
    cpts: list[str],
    weights: dict[str, float],
    years_cap: int,
    min_completeness: float,
    disciplinary_penalty: float,
    open_payments_in_score: bool,
) -> list[MatrixRow]:
    """End-to-end scoring of a shortlist: cost, quality proxy, Pareto frontier.
    Mutates and returns the rows."""
    ctx = ScoringContext.build(rows, years_cap)
    for r in rows:
        total, comps, facility_only = cost_estimate(r.facility, cpts)
        r.cost_estimate = total
        r.cost_components = comps
        r.cost_is_facility_only = facility_only

        score, contribs, completeness, note = quality_proxy(
            r.provider,
            r.facility,
            ctx,
            weights,
            min_completeness=min_completeness,
            disciplinary_penalty=disciplinary_penalty,
            open_payments_in_score=open_payments_in_score,
        )
        r.quality_proxy_score = score
        r.proxy_components = contribs
        r.data_completeness = completeness
        r.quality_note = note
    mark_pareto_frontier(rows)
    return rows

"""Scoring is pure + deterministic -> tested first (Spec §10 Phase 2).

These tests pin the spec's hard requirements: missing-signal renormalization,
the disciplinary penalty, None-when-too-sparse, and the Pareto frontier.
"""

from __future__ import annotations

import math

import pytest

from kodex.models import Facility, MatrixRow, Provider
from kodex.scoring import (
    ScoringContext,
    cost_estimate,
    data_completeness,
    mark_pareto_frontier,
    normalize_minmax,
    quality_proxy,
    score_rows,
    subscores,
)

WEIGHTS = {
    "board_certified": 0.25,
    "fellowship_spine": 0.15,
    "medicare_adr_volume": 0.20,
    "facility_complication": 0.20,
    "facility_readmission": 0.10,
    "facility_satisfaction": 0.10,
    "years_in_practice": 0.10,
    "open_payments": 0.00,
}


def _prov(npi="1", **kw) -> Provider:
    return Provider(npi=npi, name=f"Dr {npi}", **kw)


def _fac(ccn="C1", **kw) -> Facility:
    return Facility(ccn=ccn, name=f"Hosp {ccn}", **kw)


def _row(p: Provider, f: Facility) -> MatrixRow:
    return MatrixRow(provider=p, facility=f)


# --------------------------------------------------------------------------
# normalize_minmax
# --------------------------------------------------------------------------
def test_normalize_minmax_basic():
    assert normalize_minmax(5, 0, 10) == 0.5
    assert normalize_minmax(0, 0, 10) == 0.0
    assert normalize_minmax(10, 0, 10) == 1.0


def test_normalize_minmax_degenerate_is_neutral():
    # No spread across the shortlist -> neutral 0.5, neither reward nor punish.
    assert normalize_minmax(7, 7, 7) == 0.5


def test_normalize_minmax_clamps():
    assert normalize_minmax(-5, 0, 10) == 0.0
    assert normalize_minmax(15, 0, 10) == 1.0


# --------------------------------------------------------------------------
# Fully-populated provider scores deterministically
# --------------------------------------------------------------------------
def test_full_signals_weighted_sum():
    # Two-row shortlist so min-max has spread.
    p_hi = _prov(
        "hi", board_certified=True, fellowship_spine=True,
        medicare_adr_volume=100, years_in_practice_proxy=30,
    )
    f_hi = _fac("Chi", complication_measure=1.0, readmission_measure=1.0,
                satisfaction_measure=5.0, cash_price={"22856": 30000}, cost_source="MRF")
    p_lo = _prov(
        "lo", board_certified=False, fellowship_spine=False,
        medicare_adr_volume=0, years_in_practice_proxy=0,
    )
    f_lo = _fac("Clo", complication_measure=5.0, readmission_measure=5.0,
                satisfaction_measure=1.0, cash_price={"22856": 50000}, cost_source="MRF")
    rows = [_row(p_hi, f_hi), _row(p_lo, f_lo)]
    ctx = ScoringContext.build(rows, years_cap=30)

    # p_hi: every sub-score is 1.0 (best in shortlist), all signals present.
    score, contribs, completeness, note = quality_proxy(
        p_hi, f_hi, ctx, WEIGHTS,
        min_completeness=0.4, disciplinary_penalty=0.5, open_payments_in_score=False,
    )
    assert note is None
    assert score == pytest.approx(1.0)
    # completeness: 7 core present + MRF cost = 8/8
    assert completeness == pytest.approx(1.0)

    # p_lo: every sub-score is 0.0 -> weighted 0.0
    score_lo, _, _, _ = quality_proxy(
        p_lo, f_lo, ctx, WEIGHTS,
        min_completeness=0.4, disciplinary_penalty=0.5, open_payments_in_score=False,
    )
    assert score_lo == pytest.approx(0.0)


# --------------------------------------------------------------------------
# Missing signal -> renormalized, never imputed (Spec §6)
# --------------------------------------------------------------------------
def test_missing_signal_renormalizes():
    # Only board_certified (0.25) and fellowship_spine (0.15) present, both True.
    # Renormalized: 0.25/0.40 + 0.15/0.40 = 1.0 -> score 1.0, not 0.40.
    p = _prov("x", board_certified=True, fellowship_spine=True)
    f = _fac("Cx")  # no facility measures, no volume, no years
    ctx = ScoringContext.build([_row(p, f)], years_cap=30)
    score, contribs, completeness, note = quality_proxy(
        p, f, ctx, WEIGHTS,
        min_completeness=0.0,  # disable sparsity gate for this unit
        disciplinary_penalty=0.5, open_payments_in_score=False,
    )
    assert score == pytest.approx(1.0)
    # Present contributions sum to the score; missing signals are None.
    assert contribs["board_certified"] == pytest.approx(0.625)   # 0.25/0.40
    assert contribs["fellowship_spine"] == pytest.approx(0.375)  # 0.15/0.40
    assert contribs["medicare_adr_volume"] is None
    assert contribs["facility_complication"] is None


def test_missing_signal_not_imputed_as_zero():
    # If 'missing == 0' were (wrongly) the behavior, a present-True board cert
    # with everything else missing would score 0.25. Renormalization gives 1.0.
    p = _prov("x", board_certified=True)
    f = _fac("Cx")
    ctx = ScoringContext.build([_row(p, f)], years_cap=30)
    score, _, _, _ = quality_proxy(
        p, f, ctx, WEIGHTS,
        min_completeness=0.0, disciplinary_penalty=0.5, open_payments_in_score=False,
    )
    assert score == pytest.approx(1.0)


# --------------------------------------------------------------------------
# Disciplinary penalty applied AFTER the weighted sum, clamped (Spec §6)
# --------------------------------------------------------------------------
def test_disciplinary_penalty_subtracted_after_sum():
    p = _prov("x", board_certified=True, fellowship_spine=True, disciplinary_flag=True)
    f = _fac("Cx")
    ctx = ScoringContext.build([_row(p, f)], years_cap=30)
    score, contribs, _, _ = quality_proxy(
        p, f, ctx, WEIGHTS,
        min_completeness=0.0, disciplinary_penalty=0.5, open_payments_in_score=False,
    )
    # weighted 1.0 - 0.5 penalty = 0.5
    assert score == pytest.approx(0.5)
    assert contribs["_disciplinary_penalty"] == pytest.approx(-0.5)


def test_disciplinary_penalty_clamped_to_zero():
    p = _prov("x", board_certified=False, fellowship_spine=False, disciplinary_flag=True)
    f = _fac("Cx")
    ctx = ScoringContext.build([_row(p, f)], years_cap=30)
    score, _, _, _ = quality_proxy(
        p, f, ctx, WEIGHTS,
        min_completeness=0.0, disciplinary_penalty=0.5, open_payments_in_score=False,
    )
    # weighted 0.0 - 0.5 = -0.5 -> clamped to 0.0
    assert score == pytest.approx(0.0)


# --------------------------------------------------------------------------
# None when too sparse (Spec §6)
# --------------------------------------------------------------------------
def test_none_when_below_completeness_threshold():
    # Only one core signal present -> completeness = (1 + 0)/8 = 0.125 < 0.4
    p = _prov("x", board_certified=True)
    f = _fac("Cx")  # cost_source default MRF_UNAVAILABLE -> cost_presence 0
    ctx = ScoringContext.build([_row(p, f)], years_cap=30)
    score, _, completeness, note = quality_proxy(
        p, f, ctx, WEIGHTS,
        min_completeness=0.4, disciplinary_penalty=0.5, open_payments_in_score=False,
    )
    assert score is None
    assert completeness < 0.4
    assert note and "insufficient data" in note


def test_no_weighted_signals_present_returns_none():
    p = _prov("x")  # nothing
    f = _fac("Cx")
    ctx = ScoringContext.build([_row(p, f)], years_cap=30)
    score, _, _, note = quality_proxy(
        p, f, ctx, WEIGHTS,
        min_completeness=0.0, disciplinary_penalty=0.5, open_payments_in_score=False,
    )
    assert score is None
    assert note == "no weighted signals present"


# --------------------------------------------------------------------------
# data_completeness accounting
# --------------------------------------------------------------------------
def test_completeness_counts_cost_source():
    p = _prov(
        "x", board_certified=True, fellowship_spine=True, medicare_adr_volume=5,
        years_in_practice_proxy=10,
    )
    f_mrf = _fac("Cm", complication_measure=2.0, readmission_measure=2.0,
                 satisfaction_measure=4.0, cost_source="MRF")
    f_fair = _fac("Cf", complication_measure=2.0, readmission_measure=2.0,
                  satisfaction_measure=4.0, cost_source="FAIRHEALTH")
    f_none = _fac("Cn", complication_measure=2.0, readmission_measure=2.0,
                  satisfaction_measure=4.0, cost_source="MRF_UNAVAILABLE")
    # 7 core present in all three; cost presence 1.0 / 0.5 / 0.0 (denominator 8)
    assert data_completeness(p, f_mrf) == pytest.approx(8 / 8)
    assert data_completeness(p, f_fair) == pytest.approx(7.5 / 8)
    assert data_completeness(p, f_none) == pytest.approx(7 / 8)


# --------------------------------------------------------------------------
# Cost estimate
# --------------------------------------------------------------------------
def test_cost_estimate_sums_present_cpts_only():
    f = _fac("C", cash_price={"22856": 30000, "22858": 5000}, cost_source="MRF")
    total, comps, facility_only = cost_estimate(f, ["22856", "22858", "22857"])
    assert total == pytest.approx(35000)
    assert comps["22857"] is None     # unpriced -> UNKNOWN, not invented
    assert facility_only is True


def test_cost_estimate_none_when_nothing_priced():
    f = _fac("C", cash_price={}, cost_source="MRF_UNAVAILABLE")
    total, comps, _ = cost_estimate(f, ["22856"])
    assert total is None
    assert comps["22856"] is None


# --------------------------------------------------------------------------
# Pareto frontier (Spec §6)
# --------------------------------------------------------------------------
def _scored_row(npi, cost, quality):
    r = MatrixRow(provider=_prov(npi), facility=_fac("C" + npi))
    r.cost_estimate = cost
    r.quality_proxy_score = quality
    return r


def test_pareto_frontier_basic():
    # A: cheap+good (frontier). B: expensive+bad (dominated by A). C: cheap+bad,
    # D: expensive+good — both on frontier (each best on one axis).
    a = _scored_row("A", cost=20000, quality=0.9)
    b = _scored_row("B", cost=50000, quality=0.4)
    c = _scored_row("C", cost=10000, quality=0.3)
    d = _scored_row("D", cost=60000, quality=0.95)
    rows = [a, b, c, d]
    mark_pareto_frontier(rows)
    assert a.on_pareto_frontier is True
    assert b.on_pareto_frontier is False   # A is cheaper AND better
    assert c.on_pareto_frontier is True    # cheapest
    assert d.on_pareto_frontier is True    # highest quality


def test_pareto_excludes_unplaceable_rows():
    a = _scored_row("A", cost=20000, quality=0.9)
    b = MatrixRow(provider=_prov("B"), facility=_fac("CB"))  # no cost/quality
    b.cost_estimate = None
    b.quality_proxy_score = None
    rows = [a, b]
    mark_pareto_frontier(rows)
    assert a.on_pareto_frontier is True
    assert b.on_pareto_frontier is False


def test_pareto_identical_points_both_on_frontier():
    a = _scored_row("A", cost=20000, quality=0.5)
    b = _scored_row("B", cost=20000, quality=0.5)
    mark_pareto_frontier([a, b])
    # Neither strictly dominates the other.
    assert a.on_pareto_frontier is True
    assert b.on_pareto_frontier is True


# --------------------------------------------------------------------------
# End-to-end score_rows
# --------------------------------------------------------------------------
def test_score_rows_end_to_end():
    p1 = _prov("1", board_certified=True, fellowship_spine=True,
               medicare_adr_volume=50, years_in_practice_proxy=20)
    f1 = _fac("C1", complication_measure=1.0, readmission_measure=1.0,
              cash_price={"22856": 28000}, cost_source="MRF")
    p2 = _prov("2", board_certified=True, fellowship_spine=False,
               medicare_adr_volume=10, years_in_practice_proxy=15)
    f2 = _fac("C2", complication_measure=3.0, readmission_measure=2.0,
              cash_price={"22856": 40000}, cost_source="MRF")
    rows = [_row(p1, f1), _row(p2, f2)]
    score_rows(
        rows, cpts=["22856"], weights=WEIGHTS, years_cap=30,
        min_completeness=0.4, disciplinary_penalty=0.5, open_payments_in_score=False,
    )
    # p1 dominates p2 (cheaper and higher quality) -> p1 on frontier, p2 not.
    assert rows[0].cost_estimate == 28000
    assert rows[0].quality_proxy_score is not None
    assert rows[0].quality_proxy_score > rows[1].quality_proxy_score
    assert rows[0].on_pareto_frontier is True
    assert rows[1].on_pareto_frontier is False


def test_log_scaling_used_for_volume():
    # Volume sub-score uses log1p then min-max: 0 and a big number set the range.
    p = _prov("x", medicare_adr_volume=10)
    rows = [
        _row(_prov("a", medicare_adr_volume=0), _fac("Ca")),
        _row(p, _fac("Cx")),
        _row(_prov("b", medicare_adr_volume=1000), _fac("Cb")),
    ]
    ctx = ScoringContext.build(rows, years_cap=30)
    subs = subscores(p, _fac("Cx"), ctx)
    expected = (math.log1p(10) - math.log1p(0)) / (math.log1p(1000) - math.log1p(0))
    assert subs["medicare_adr_volume"] == pytest.approx(expected)

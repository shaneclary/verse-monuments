"""Generalized search scaffolding: registry, lay-term match, scoring, confidence.

These pin the behaviors that make KODEX a general medical-decision tool rather than
an ADR-only one: plain words resolve to procedures, one scorer serves any
procedure, and the CONFIDENCE grade honestly reflects the strength of the data
behind each ranking.
"""

from __future__ import annotations

import textwrap

import pytest

from kodex.connectors.provider_source import SyntheticProviderSource
from kodex.matching import (
    Candidate,
    PatientContext,
    _effective_weights,
    build_result,
    score_candidates,
)
from kodex.registry import Registry
from kodex.search import find_care


@pytest.fixture(scope="module")
def reg() -> Registry:
    return Registry.load()   # data/registry (repo root)


# --------------------------------------------------------------------------
# Registry loads + cross-references validate
# --------------------------------------------------------------------------
def test_registry_loads_and_crossrefs(reg):
    assert {"adr_spine", "total_knee_replacement", "cabg"} <= set(reg.procedures)
    # every procedure signal exists in the catalog; conditions point at real procedures
    for proc in reg.procedures.values():
        for ps in proc.signals:
            assert ps.signal_id in reg.signals
    for cond in reg.conditions.values():
        for pid in cond.pathways:
            assert pid in reg.procedures


def test_registry_validation_rejects_unknown_signal(tmp_path):
    (tmp_path / "procedures").mkdir()
    (tmp_path / "signals.yaml").write_text("signals: {board_certified: {label: B, granularity: surgeon}}\n")
    (tmp_path / "procedures" / "x.yaml").write_text(textwrap.dedent("""
        id: x
        name: X
        signals:
          - {signal_id: does_not_exist, weight: 1.0}
    """))
    with pytest.raises(ValueError):
        Registry.load(tmp_path)


# --------------------------------------------------------------------------
# Lay-term search: people type problems, not CPT codes
# --------------------------------------------------------------------------
@pytest.mark.parametrize("query,expected_pid", [
    ("heart bypass", "cabg"),
    ("new knee", "total_knee_replacement"),
    ("slipped disc surgery", "adr_spine"),
    ("bad knee", "total_knee_replacement"),
    ("clogged arteries", "cabg"),
])
def test_search_resolves_lay_terms(reg, query, expected_pid):
    hits = reg.search(query)
    assert hits, f"no hit for {query!r}"
    assert expected_pid in hits[0].procedure_ids


def test_search_ranks_and_is_empty_on_nonsense(reg):
    assert reg.search("qwertyuiop zxcvbnm") == []


# --------------------------------------------------------------------------
# Confidence grade tracks the strength of the underlying data (the honesty engine)
# --------------------------------------------------------------------------
@pytest.mark.parametrize("pid,expected_grade,surgeon_outcomes", [
    ("cabg", "strong", True),                 # risk-adjusted SURGEON outcomes
    ("total_knee_replacement", "moderate", False),  # risk-adjusted FACILITY outcomes
    ("adr_spine", "limited", False),          # volume floor + facility proxies
])
def test_confidence_grade_reflects_data_strength(reg, pid, expected_grade, surgeon_outcomes):
    proc = reg.procedures[pid]
    cands = SyntheticProviderSource().candidates(proc, reg, PatientContext())
    result = build_result(cands, proc, reg)
    assert result.confidence.grade == expected_grade
    assert result.confidence.has_surgeon_outcomes is surgeon_outcomes


# --------------------------------------------------------------------------
# Generalized scorer: renormalize on missing, None when too sparse, frontier
# --------------------------------------------------------------------------
def test_score_renormalizes_over_present_signals(reg):
    proc = reg.procedures["adr_spine"]
    # Only board_certified present -> renormalized to 1.0 (not diluted by absent signals).
    c = Candidate(provider_id="p", provider_name="P", signals={"board_certified": 1.0}, cost_estimate=1000)
    scored = score_candidates([c], proc, reg, min_completeness=0.0)
    assert scored[0].quality_score == pytest.approx(1.0)


def test_score_none_when_too_sparse(reg):
    proc = reg.procedures["adr_spine"]
    c = Candidate(provider_id="p", provider_name="P", signals={"board_certified": 1.0})  # no cost
    scored = score_candidates([c], proc, reg, min_completeness=0.3)
    assert scored[0].quality_score is None
    assert "insufficient" in (scored[0].note or "")


def test_frontier_marks_nondominated(reg):
    proc = reg.procedures["adr_spine"]
    cheap_good = Candidate(provider_id="a", provider_name="A",
                           signals={"board_certified": 1.0, "surgeon_procedure_volume": 200}, cost_estimate=20000)
    pricey_bad = Candidate(provider_id="b", provider_name="B",
                           signals={"board_certified": 0.0, "surgeon_procedure_volume": 10}, cost_estimate=60000)
    scored = score_candidates([cheap_good, pricey_bad], proc, reg, min_completeness=0.0)
    by_id = {s.candidate.provider_id: s for s in scored}
    assert by_id["a"].on_frontier is True
    assert by_id["b"].on_frontier is False


def test_priority_remap_changes_weights(reg):
    proc = reg.procedures["cabg"]
    base = _effective_weights(proc, PatientContext())
    boosted = _effective_weights(proc, PatientContext(priorities={"outcomes": 2.0}))
    assert boosted["risk_adjusted_surgeon_outcome"] == pytest.approx(base["risk_adjusted_surgeon_outcome"] * 2.0)
    # A non-outcome signal is untouched.
    assert boosted["board_certified"] == pytest.approx(base["board_certified"])


# --------------------------------------------------------------------------
# End-to-end find_care returns a readable, honest result
# --------------------------------------------------------------------------
def test_find_care_end_to_end_plain_language(reg):
    resp = find_care(reg, "slipped disc", context=PatientContext(zip="50309"))
    assert resp.resolved_procedure_id == "adr_spine"
    assert resp.result is not None
    text = resp.result.to_plain_text()
    assert "not medical advice" in text.lower()
    assert "not tell you" in text.lower()
    # Honest about the missing surgeon-level data.
    assert resp.result.confidence.grade == "limited"

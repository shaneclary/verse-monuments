"""Generalized matching — score any procedure's candidates + grade the result.

This is the procedure-agnostic replacement for the ADR-specific scoring path. It
consumes the registry's signal metadata (direction, granularity, risk-adjustment)
so ONE scorer serves every procedure, and it produces a CONFIDENCE grade so a
ranking built on strong data (risk-adjusted surgeon outcomes) is visibly more
trustworthy than one built on a volume floor.

Pure and deterministic — no I/O. Candidates come from a ProviderSource (synthetic
now, real connectors later); this module only scores, ranks, and explains.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .registry import Procedure, Registry
from .scoring import normalize_minmax

# Priority presets let a person say "I care most about X" without touching weights.
# Each remaps the procedure's signal weights by multiplying signal groups.
PRIORITY_GROUPS = {
    "outcomes": {"risk_adjusted_surgeon_outcome", "risk_adjusted_facility_outcome",
                 "facility_complication", "facility_readmission"},
    "experience": {"surgeon_procedure_volume", "center_volume", "subspecialty_fellowship",
                   "years_in_practice", "board_certified"},
    "satisfaction": {"facility_satisfaction"},
}


class PatientContext(BaseModel):
    """What a person brings to the search. All optional — the tool degrades
    gracefully, it never demands personal data to return something useful."""

    zip: str | None = None
    willing_to_travel: bool = False
    insurance_plan: str | None = None
    # Priority emphasis in [0, 2]; 1.0 = neutral. e.g. {"outcomes": 1.5}
    priorities: dict[str, float] = Field(default_factory=dict)
    notes: str | None = None


class Candidate(BaseModel):
    """A provider×facility option for a procedure. `signals` holds RAW values
    keyed by signal id (None = unknown, never invented). Populated by a
    ProviderSource; scored here."""

    provider_id: str
    provider_name: str
    facility_name: str | None = None
    location: str | None = None
    distance_mi: float | None = None
    signals: dict[str, float | None] = Field(default_factory=dict)
    cost_estimate: float | None = None
    cost_label: str = "estimate"


class ScoredCandidate(BaseModel):
    candidate: Candidate
    quality_score: float | None = None
    contributions: dict[str, float | None] = Field(default_factory=dict)
    completeness: float = 0.0
    on_frontier: bool = False
    note: str | None = None


class Confidence(BaseModel):
    """How much weight a person should put on the RANKING itself."""

    grade: Literal["strong", "moderate", "limited", "insufficient"]
    score: float                    # 0-1
    has_surgeon_outcomes: bool
    reasons: list[str] = Field(default_factory=list)


class MatchResult(BaseModel):
    procedure_id: str
    procedure_name: str
    specialty: str
    ranked: list[ScoredCandidate] = Field(default_factory=list)
    confidence: Confidence
    what_we_know: list[str] = Field(default_factory=list)
    what_we_dont_know: list[str] = Field(default_factory=list)
    questions_to_ask: list[str] = Field(default_factory=list)
    comparators: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)

    def to_plain_text(self) -> str:
        return render_plain(self)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def _effective_weights(procedure: Procedure, context: PatientContext) -> dict[str, float]:
    """Procedure weights, remapped by the person's stated priorities."""
    weights = {s.signal_id: float(s.weight) for s in procedure.signals}
    for pref, mult in (context.priorities or {}).items():
        group = PRIORITY_GROUPS.get(pref)
        if not group:
            continue
        for sid in weights:
            if sid in group:
                weights[sid] *= float(mult)
    return weights


def _subscore(value: float | None, direction: str, lo: float, hi: float) -> float | None:
    if value is None:
        return None
    if direction == "bool":
        return 1.0 if value else 0.0
    norm = normalize_minmax(value, lo, hi)
    return norm if direction == "higher_better" else (1.0 - norm)


def score_candidates(
    candidates: list[Candidate],
    procedure: Procedure,
    registry: Registry,
    *,
    context: PatientContext | None = None,
    min_completeness: float = 0.3,
) -> list[ScoredCandidate]:
    """Score every candidate for one procedure. Missing signals are excluded and
    weights renormalized (never imputed); too-sparse candidates score None."""
    context = context or PatientContext()
    weights = _effective_weights(procedure, context)
    sig_meta = {s.id: s for s in registry.signals_for(procedure)}

    # Shortlist-relative min/max per numeric signal.
    bounds: dict[str, tuple[float, float]] = {}
    for sid, meta in sig_meta.items():
        if meta.direction == "bool":
            continue
        vals = [c.signals.get(sid) for c in candidates if c.signals.get(sid) is not None]
        if vals:
            bounds[sid] = (min(vals), max(vals))

    n_signals = len(sig_meta)
    scored: list[ScoredCandidate] = []
    for c in candidates:
        contribs: dict[str, float | None] = {}
        present_weight = 0.0
        present_count = 0
        for sid, meta in sig_meta.items():
            raw = c.signals.get(sid)
            lo, hi = bounds.get(sid, (0.0, 1.0))
            sub = _subscore(raw, meta.direction, lo, hi)
            w = weights.get(sid, 0.0)
            if sub is None or w <= 0:
                contribs[sid] = None
                continue
            present_weight += w
            present_count += 1
            contribs[sid] = (sub, w)  # temp; normalized below

        cost_present = 1 if c.cost_estimate is not None else 0
        completeness = (present_count + cost_present) / (n_signals + 1) if n_signals else 0.0

        if present_weight <= 0:
            scored.append(ScoredCandidate(candidate=c, quality_score=None, contributions={k: None for k in sig_meta},
                                          completeness=completeness, note="no scorable signals"))
            continue

        total = 0.0
        for sid in sig_meta:
            cv = contribs.get(sid)
            if isinstance(cv, tuple):
                sub, w = cv
                contrib = (w / present_weight) * sub
                contribs[sid] = contrib
                total += contrib
        score = max(0.0, min(1.0, total))
        note = None
        if completeness < min_completeness:
            score = None
            note = "insufficient data to rank this option"
        scored.append(ScoredCandidate(candidate=c, quality_score=score, contributions=contribs,
                                      completeness=completeness, note=note))

    _mark_frontier(scored)
    scored.sort(key=lambda s: (
        0 if s.on_frontier else 1,
        -(s.quality_score if s.quality_score is not None else -1),
        s.candidate.cost_estimate if s.candidate.cost_estimate is not None else float("inf"),
    ))
    return scored


def _mark_frontier(scored: list[ScoredCandidate]) -> None:
    """Pareto frontier on (cost lower-better, quality higher-better)."""
    placeable = [s for s in scored
                 if s.candidate.cost_estimate is not None and s.quality_score is not None]
    for s in scored:
        s.on_frontier = False
    for a in placeable:
        dominated = False
        for b in placeable:
            if b is a:
                continue
            cheaper_eq = b.candidate.cost_estimate <= a.candidate.cost_estimate
            better_eq = b.quality_score >= a.quality_score
            strictly = (b.candidate.cost_estimate < a.candidate.cost_estimate) or (b.quality_score > a.quality_score)
            if cheaper_eq and better_eq and strictly:
                dominated = True
                break
        a.on_frontier = not dominated


# ---------------------------------------------------------------------------
# Confidence grading — the honesty engine, generalized
# ---------------------------------------------------------------------------
def grade_confidence(
    scored: list[ScoredCandidate], procedure: Procedure, registry: Registry
) -> Confidence:
    """Grade how much to trust the RANKING, from the strength of the signals that
    actually populated it. A ranking resting on risk-adjusted surgeon outcomes is
    'strong'; one resting on a volume floor + facility proxies is 'limited'."""
    sig_meta = {s.id: s for s in registry.signals_for(procedure)}
    present_ids: set[str] = set()
    for s in scored:
        for sid, contrib in s.contributions.items():
            if contrib is not None:
                present_ids.add(sid)

    has_surgeon_outcomes = any(
        sig_meta[sid].granularity == "surgeon" and sig_meta[sid].risk_adjusted
        for sid in present_ids if sid in sig_meta
    )
    # Evidentiary mass = sum of present signals' baseline strengths, capped at 1.
    mass = min(1.0, sum(sig_meta[sid].strength for sid in present_ids if sid in sig_meta))

    reasons: list[str] = []
    if has_surgeon_outcomes:
        grade = "strong"
        reasons.append("Includes risk-adjusted, surgeon-level outcomes — the strongest available signal.")
    elif any(sig_meta[sid].risk_adjusted for sid in present_ids if sid in sig_meta) and mass >= 0.6:
        grade = "moderate"
        reasons.append("Rests on risk-adjusted facility outcomes plus supporting signals — hospital-level, not surgeon-level.")
    elif mass >= 0.45:
        grade = "limited"
        reasons.append("Rests on credentials, a Medicare volume floor, and whole-hospital measures — a shortlist to ask about, not an outcome ranking.")
    else:
        grade = "insufficient"
        reasons.append("Too few signals are available to rank these options meaningfully.")

    if not has_surgeon_outcomes:
        reasons.append("No public per-surgeon success rate exists for this procedure.")

    return Confidence(grade=grade, score=round(mass, 2),
                      has_surgeon_outcomes=has_surgeon_outcomes, reasons=reasons)


# ---------------------------------------------------------------------------
# Build a full, plain-language result
# ---------------------------------------------------------------------------
def build_result(
    candidates: list[Candidate],
    procedure: Procedure,
    registry: Registry,
    *,
    context: PatientContext | None = None,
) -> MatchResult:
    scored = score_candidates(candidates, procedure, registry, context=context)
    confidence = grade_confidence(scored, procedure, registry)

    sig_meta = {s.id: s for s in registry.signals_for(procedure)}
    present_ids = {sid for s in scored for sid, c in s.contributions.items() if c is not None}
    missing_ids = [sid for sid in sig_meta if sid not in present_ids]

    what_we_know = [f"{sig_meta[sid].label} — {sig_meta[sid].coverage_caveat}" for sid in present_ids if sid in sig_meta]
    what_we_dont = [f"No data for: {sig_meta[sid].label}." for sid in missing_ids]
    if not confidence.has_surgeon_outcomes:
        what_we_dont.insert(0, "Individual surgeon success rates are not publicly available for this procedure.")

    return MatchResult(
        procedure_id=procedure.id,
        procedure_name=procedure.name,
        specialty=procedure.specialty,
        ranked=scored,
        confidence=confidence,
        what_we_know=sorted(what_we_know),
        what_we_dont_know=what_we_dont,
        questions_to_ask=list(procedure.questions_to_ask),
        comparators=list(procedure.comparators),
        caveats=list(procedure.caveats),
    )


# ---------------------------------------------------------------------------
# Plain-language rendering (accessibility) — 1 result -> readable text
# ---------------------------------------------------------------------------
_GRADE_WORDS = {
    "strong": "STRONG — backed by risk-adjusted surgeon outcomes",
    "moderate": "MODERATE — backed by risk-adjusted hospital outcomes",
    "limited": "LIMITED — a shortlist to ask about, not an outcome ranking",
    "insufficient": "INSUFFICIENT — not enough data to rank",
}


def _money(v: float | None) -> str:
    return f"${v:,.0f}" if isinstance(v, (int, float)) else "not available"


def render_plain(r: MatchResult) -> str:
    lines: list[str] = []
    lines.append(f"{r.procedure_name}  ({r.specialty})")
    lines.append(f"How much to trust this ranking: {_GRADE_WORDS[r.confidence.grade]}")
    for reason in r.confidence.reasons:
        lines.append(f"  · {reason}")
    lines.append("")
    lines.append("Best matches (higher quality proxy, lower cost = better):")
    shown = [s for s in r.ranked if s.quality_score is not None] or r.ranked
    for i, s in enumerate(shown[:10], start=1):
        c = s.candidate
        q = f"{s.quality_score:.2f}" if s.quality_score is not None else "unrated"
        star = "★" if s.on_frontier else " "
        loc = f" — {c.location}" if c.location else ""
        lines.append(f" {star}{i}. {c.provider_name} @ {c.facility_name or 'facility TBD'}{loc}")
        lines.append(f"      quality proxy {q} · cost {_money(c.cost_estimate)} ({c.cost_label})")
    lines.append("")
    if r.what_we_dont_know:
        lines.append("What this does NOT tell you:")
        for w in r.what_we_dont_know:
            lines.append(f"  · {w}")
        lines.append("")
    if r.comparators:
        lines.append("Alternatives worth discussing: " + "; ".join(r.comparators))
    if r.questions_to_ask:
        lines.append("Questions to ask at your consult:")
        for qn in r.questions_to_ask:
            lines.append(f"  · {qn}")
    lines.append("")
    lines.append("This is a starting point, not medical advice or a second opinion.")
    return "\n".join(lines)

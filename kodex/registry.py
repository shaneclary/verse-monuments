"""Domain registry — procedures & conditions as DATA, not code.

This is the generalization spine: KODEX started life hardwired to one procedure
(ADR). To help people weigh *any* surgery or specialized-care decision, the
procedure stops being config and becomes a catalog of records loaded from
``data/registry/``:

  signals.yaml            the signals catalog (granularity / risk-adjustment / caveats)
  procedures/<id>.yaml    one record per procedure (codes, taxonomies, weighted signals)
  conditions.yaml         patient-language problems -> the procedures that treat them

Adding a new procedure is a data edit, never a code change. Everything downstream
(search, scoring, confidence grading, plain-language output) is driven by these
records. Real provider/outcome data plugs in later via connectors; the registry
is the shape everything hangs on.
"""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

DEFAULT_REGISTRY_DIR = "data/registry"

Granularity = Literal["surgeon", "facility", "regional"]
Direction = Literal["higher_better", "lower_better", "bool"]


class Signal(BaseModel):
    """One quality signal TYPE and its honest metadata (from signals.yaml)."""

    id: str
    label: str
    granularity: Granularity
    risk_adjusted: bool = False
    direction: Direction = "higher_better"
    source: str = ""
    coverage_caveat: str = ""
    strength: float = 0.3  # baseline evidentiary weight of the signal type (0-1)


class ProcedureSignal(BaseModel):
    """A signal a procedure uses, with its per-procedure scoring weight."""

    signal_id: str
    weight: float = 0.0


class Procedure(BaseModel):
    id: str
    name: str
    lay_terms: list[str] = Field(default_factory=list)
    specialty: str = ""
    body_area: str = ""
    code_sets: dict[str, list[str]] = Field(default_factory=dict)
    provider_taxonomies: list[str] = Field(default_factory=list)
    facility_measures: list[str] = Field(default_factory=list)
    # Bridge from a generic facility signal id -> the concrete CMS measure id that
    # feeds it (e.g. facility_complication -> PSI_90_SAFETY). This is what lets one
    # ProviderSource populate any procedure's facility signals from Care Compare.
    facility_signal_measures: dict[str, str] = Field(default_factory=dict)
    signals: list[ProcedureSignal] = Field(default_factory=list)
    comparators: list[str] = Field(default_factory=list)
    evidence_terms: list[str] = Field(default_factory=list)
    questions_to_ask: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)

    def weight_for(self, signal_id: str) -> float:
        for s in self.signals:
            if s.signal_id == signal_id:
                return s.weight
        return 0.0


class Condition(BaseModel):
    id: str
    name: str
    lay_terms: list[str] = Field(default_factory=list)
    description: str = ""
    pathways: list[str] = Field(default_factory=list)     # procedure ids
    non_surgical_first: bool = False


class SearchHit(BaseModel):
    """A fuzzy match of a person's words to a condition or procedure."""

    kind: Literal["condition", "procedure"]
    id: str
    name: str
    score: float                       # 0-1 match confidence
    matched_on: str                    # the term that matched
    procedure_ids: list[str] = Field(default_factory=list)


class Registry(BaseModel):
    signals: dict[str, Signal] = Field(default_factory=dict)
    procedures: dict[str, Procedure] = Field(default_factory=dict)
    conditions: dict[str, Condition] = Field(default_factory=dict)

    # ---- loading -------------------------------------------------------
    @classmethod
    def load(cls, base_dir: str | Path = DEFAULT_REGISTRY_DIR) -> "Registry":
        base = Path(base_dir)
        if not base.exists():
            raise FileNotFoundError(f"registry directory not found at {base}")

        signals: dict[str, Signal] = {}
        sig_file = base / "signals.yaml"
        if sig_file.exists():
            data = yaml.safe_load(sig_file.read_text(encoding="utf-8")) or {}
            for sid, meta in (data.get("signals") or {}).items():
                signals[sid] = Signal(id=sid, **meta)

        procedures: dict[str, Procedure] = {}
        proc_dir = base / "procedures"
        if proc_dir.exists():
            for f in sorted(proc_dir.glob("*.yaml")):
                raw = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
                proc = Procedure(**raw)
                procedures[proc.id] = proc

        conditions: dict[str, Condition] = {}
        cond_file = base / "conditions.yaml"
        if cond_file.exists():
            data = yaml.safe_load(cond_file.read_text(encoding="utf-8")) or {}
            for raw in data.get("conditions") or []:
                cond = Condition(**raw)
                conditions[cond.id] = cond

        reg = cls(signals=signals, procedures=procedures, conditions=conditions)
        reg._validate()
        return reg

    def _validate(self) -> None:
        # Every procedure signal must exist in the catalog; every condition
        # pathway must point at a real procedure. Fail loudly on a typo.
        for proc in self.procedures.values():
            for ps in proc.signals:
                if ps.signal_id not in self.signals:
                    raise ValueError(
                        f"procedure {proc.id!r} references unknown signal "
                        f"{ps.signal_id!r} (not in signals.yaml)."
                    )
        for cond in self.conditions.values():
            for pid in cond.pathways:
                if pid not in self.procedures:
                    raise ValueError(
                        f"condition {cond.id!r} references unknown procedure {pid!r}."
                    )

    # ---- lookup / search ----------------------------------------------
    def procedure(self, procedure_id: str) -> Procedure:
        return self.procedures[procedure_id]

    def signals_for(self, procedure: Procedure) -> list[Signal]:
        return [self.signals[s.signal_id] for s in procedure.signals if s.signal_id in self.signals]

    def search(self, query: str, *, limit: int = 8) -> list[SearchHit]:
        """Match a layperson's words to conditions and procedures. Combines
        substring hits (a person typing "knee replacement") with fuzzy ratio (a
        person typing "new knee" or a typo). Conditions rank ahead of procedures
        on ties because people describe problems, not operations."""
        q = _norm(query)
        if not q:
            return []
        hits: list[SearchHit] = []

        for cond in self.conditions.values():
            score, term = _best_match(q, [cond.name, *cond.lay_terms])
            if score > 0:
                hits.append(SearchHit(
                    kind="condition", id=cond.id, name=cond.name, score=score,
                    matched_on=term, procedure_ids=list(cond.pathways),
                ))
        for proc in self.procedures.values():
            score, term = _best_match(q, [proc.name, *proc.lay_terms])
            if score > 0:
                hits.append(SearchHit(
                    kind="procedure", id=proc.id, name=proc.name, score=score,
                    matched_on=term, procedure_ids=[proc.id],
                ))

        hits.sort(key=lambda h: (-h.score, 0 if h.kind == "condition" else 1, h.name))
        return hits[:limit]


# ---------------------------------------------------------------------------
# Fuzzy matching helpers (pure)
# ---------------------------------------------------------------------------
def _norm(s: str) -> str:
    return " ".join((s or "").lower().replace("-", " ").split())


def _best_match(query: str, candidates: list[str]) -> tuple[float, str]:
    """Best (score, matched_term) of query against candidate phrases.
    Substring match is strong; otherwise fall back to token/sequence ratio."""
    best_score = 0.0
    best_term = ""
    for cand in candidates:
        c = _norm(cand)
        if not c:
            continue
        if query == c:
            score = 1.0
        elif query in c or c in query:
            # Longer overlap relative to the phrase = stronger.
            score = 0.9 * (min(len(query), len(c)) / max(len(query), len(c))) + 0.1
        else:
            # Token overlap gives partial credit ("new knee" vs "knee replacement").
            qt, ct = set(query.split()), set(c.split())
            overlap = len(qt & ct) / len(qt | ct) if (qt | ct) else 0.0
            ratio = difflib.SequenceMatcher(None, query, c).ratio()
            score = max(overlap, ratio)
            if score < 0.34:
                score = 0.0
        if score > best_score:
            best_score, best_term = score, cand
    return best_score, best_term

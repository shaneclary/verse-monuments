"""Search entry point — plain words in, a ranked, honest, readable answer out.

This is the front door for a person weighing a medical decision. They type what's
wrong in their own words ("bad knee", "heart bypass", "slipped disc"); we resolve
that to a procedure via the registry, pull candidate providers from a
ProviderSource, score + grade + explain them, and hand back a plain-language
result. Real data plugs in behind ProviderSource without changing any of this.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .connectors.provider_source import ProviderSource, SyntheticProviderSource
from .matching import MatchResult, PatientContext, build_result
from .registry import Registry, SearchHit


class CareSearchResponse(BaseModel):
    query: str
    hits: list[SearchHit] = Field(default_factory=list)   # what the person might have meant
    result: MatchResult | None = None                     # best-match ranking for the top hit
    resolved_procedure_id: str | None = None
    note: str | None = None


def find_care(
    registry: Registry,
    query: str,
    *,
    context: PatientContext | None = None,
    source: ProviderSource | None = None,
    limit: int = 8,
) -> CareSearchResponse:
    """Resolve a lay query to the best-matching procedure and rank options for it.

    Returns all near-matches too, so a UI can offer "did you mean…" when the top
    hit is ambiguous."""
    context = context or PatientContext()
    source = source or SyntheticProviderSource()
    hits = registry.search(query, limit=limit)
    if not hits:
        return CareSearchResponse(query=query, note="No matching condition or procedure found.")

    top = hits[0]
    pid = top.procedure_ids[0] if top.procedure_ids else None
    if not pid or pid not in registry.procedures:
        return CareSearchResponse(query=query, hits=hits,
                                  note="Matched a condition with no procedure pathway yet.")

    procedure = registry.procedures[pid]
    candidates = source.candidates(procedure, registry, context)
    result = build_result(candidates, procedure, registry, context=context)
    note = None
    if top.kind == "condition" and len(top.procedure_ids) > 1:
        note = f"'{top.name}' has multiple treatment options; showing {procedure.name}."
    return CareSearchResponse(query=query, hits=hits, result=result,
                              resolved_procedure_id=pid, note=note)

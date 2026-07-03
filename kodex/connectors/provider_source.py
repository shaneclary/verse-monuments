"""Provider source — the pluggable seam where real data attaches later.

Everything upstream (registry, scoring, confidence, plain-language output) is data-
source agnostic. A ProviderSource is the one thing that turns a procedure + a
patient context into a list of Candidate options. Today the only implementation
is synthetic (so the whole tool runs with NO real data); the real sources — NPPES
national seeding, MRF cost, Care Compare, specialty outcome registries — will
implement the exact same ``.candidates()`` contract and drop straight in.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..matching import Candidate, PatientContext
from ..registry import Procedure, Registry


@runtime_checkable
class ProviderSource(Protocol):
    def candidates(
        self, procedure: Procedure, registry: Registry, context: PatientContext
    ) -> list[Candidate]:
        """Return scorable Candidate options for this procedure. Signal values may
        be None (unknown) — never fabricated."""
        ...


# Cities used only to make synthetic output legible; distances are illustrative.
_CITIES = [
    ("Des Moines, IA", 0), ("Rochester, MN", 240), ("Cleveland, OH", 700),
    ("Chicago, IL", 330), ("Houston, TX", 970), ("Los Angeles, CA", 1830),
]


class SyntheticProviderSource:
    """Deterministic, clearly-synthetic candidates for the scaffolding. Produces
    values ONLY for the signals a procedure actually uses, occasionally leaving one
    unknown to exercise renormalization + the UNKNOWN path. No randomness, so
    output is reproducible."""

    def __init__(self, n: int = 6):
        self.n = n

    def candidates(self, procedure, registry, context) -> list[Candidate]:
        sig_ids = [s.signal_id for s in procedure.signals]
        metas = {s.id: s for s in registry.signals_for(procedure)}
        out: list[Candidate] = []
        for i in range(self.n):
            signals: dict[str, float | None] = {}
            for j, sid in enumerate(sig_ids):
                meta = metas.get(sid)
                if meta is None:
                    continue
                base = ((i * 7 + j * 13) % 10) / 10.0  # deterministic spread in [0,1)
                if meta.direction == "bool":
                    signals[sid] = 1.0 if (i + j) % 3 != 0 else 0.0
                elif sid in ("surgeon_procedure_volume", "center_volume"):
                    signals[sid] = round(10 + base * 200, 0)
                elif sid == "facility_satisfaction":
                    signals[sid] = round(1 + base * 4, 1)          # 1-5 stars
                elif sid == "years_in_practice":
                    signals[sid] = float(5 + int(base * 30))
                elif meta.direction == "lower_better":
                    signals[sid] = round(0.5 + base * 3.0, 2)       # rates, lower better
                else:
                    signals[sid] = round(base, 3)
            # Leave one signal unknown on some rows (honest gaps happen).
            if sig_ids and i % 4 == 3:
                signals[sig_ids[i % len(sig_ids)]] = None

            city, dist = _CITIES[i % len(_CITIES)]
            out.append(Candidate(
                provider_id=f"SYN{i:03d}",
                provider_name=f"Dr. Example {chr(65 + i)}",
                facility_name=f"Example {procedure.body_area or 'Medical'} Center {i + 1}",
                location=city,
                distance_mi=float(dist),
                signals=signals,
                cost_estimate=float(25000 + ((i * 37) % 20) * 1500),
                cost_label="SYNTHETIC facility estimate",
            ))
        return out

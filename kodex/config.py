"""Load and validate config.yaml (Spec §7).

The operator's single source of truth. We keep the loaded structure permissive
(a dict-backed wrapper) so the operator can add keys without code changes, but
we expose typed accessors for the values the pipeline relies on and validate the
handful that would silently break a run if malformed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = "config.yaml"


class Config:
    """Thin typed wrapper over the parsed config.yaml dict."""

    def __init__(self, data: dict[str, Any], path: str | None = None):
        self._d = data
        self.path = path
        self._validate()

    # ---- loading -------------------------------------------------------
    @classmethod
    def load(cls, path: str | Path = DEFAULT_CONFIG_PATH) -> "Config":
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(
                f"config.yaml not found at {p}. KODEX needs it to run (Spec §7)."
            )
        with p.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return cls(data, path=str(p))

    def _validate(self) -> None:
        cpts = self.cpt_codes
        if not cpts:
            raise ValueError("config.procedure.cpt_codes is empty — nothing to price (Spec §1).")
        weights = self.quality_weights
        if not weights:
            raise ValueError("config.scoring.quality_weights is empty (Spec §6).")
        # Weights are renormalized at scoring time, but a sane config has them >= 0.
        for k, v in weights.items():
            if v is None or v < 0:
                raise ValueError(f"quality_weights[{k}] must be >= 0, got {v!r}.")

    # ---- generic access ------------------------------------------------
    def get(self, *keys: str, default: Any = None) -> Any:
        node: Any = self._d
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                return default
            node = node[k]
        return node

    @property
    def raw(self) -> dict[str, Any]:
        return self._d

    # ---- typed accessors the pipeline relies on ------------------------
    @property
    def cpt_codes(self) -> list[str]:
        return [str(c) for c in self.get("procedure", "cpt_codes", default=[])]

    @property
    def cpt_descriptions(self) -> dict[str, str]:
        return self.get("procedure", "cpt_descriptions", default={}) or {}

    @property
    def region(self) -> str:
        return self.get("procedure", "region", default="both")

    @property
    def procedure_label(self) -> str:
        return self.get("procedure", "procedure_label", default="ADR")

    @property
    def state(self) -> str | None:
        return self.get("geography", "state")

    @property
    def center_zip(self) -> str | None:
        z = self.get("geography", "center_zip")
        return str(z) if z is not None else None

    @property
    def radius_miles(self) -> float:
        return float(self.get("geography", "radius_miles", default=100))

    @property
    def taxonomies(self) -> list[str]:
        return self.get("provider_taxonomies", default=[]) or []

    @property
    def quality_weights(self) -> dict[str, float]:
        return self.get("scoring", "quality_weights", default={}) or {}

    @property
    def disciplinary_penalty(self) -> float:
        return float(self.get("scoring", "disciplinary_penalty", default=0.5))

    @property
    def min_completeness_to_score(self) -> float:
        return float(self.get("scoring", "min_completeness_to_score", default=0.4))

    @property
    def years_cap(self) -> int:
        return int(self.get("scoring", "years_cap", default=30))

    @property
    def open_payments_in_score(self) -> bool:
        return bool(self.get("scoring", "open_payments_in_score", default=False))

    @property
    def offline(self) -> bool:
        return bool(self.get("run", "offline", default=False))

    @property
    def db_path(self) -> str:
        return self.get("run", "db_path", default="data/kodex.sqlite")

    @property
    def out_dir(self) -> str:
        return self.get("run", "out_dir", default="out")

    @property
    def shortlist_size(self) -> int:
        return int(self.get("report", "shortlist_size", default=20))

    def endpoint(self, name: str) -> str | None:
        return self.get("endpoints", name)

    def manual_input(self, name: str) -> str | None:
        return self.get("manual_inputs", name)

    def bulk_data(self, name: str) -> str | None:
        return self.get("bulk_data", name)

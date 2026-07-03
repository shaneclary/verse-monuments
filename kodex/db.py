"""SQLite cache + working store (Spec §4 offline guarantee, §3.1/§3.2 caching).

Two roles:
  1. ``raw_cache``  — verbatim payloads from network connectors (NPPES, Open
     Payments, PubMed) keyed by (source, key). A second run with --offline reads
     from here, so the report is reproducible with no network.
  2. bulk tables    — Medicare volume + Care Compare measures ingested once from
     CSV and queried locally (these datasets are too big to hit per-NPI).

All writes commit immediately so a long run that dies partway keeps what it had.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import CacheMiss

SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_cache (
    source     TEXT NOT NULL,
    key        TEXT NOT NULL,
    url        TEXT,
    payload    TEXT,            -- raw response body (JSON or text)
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (source, key)
);

CREATE TABLE IF NOT EXISTS medicare_volume (
    npi            TEXT NOT NULL,
    cpt            TEXT NOT NULL,
    year           TEXT NOT NULL,
    tot_srvcs      REAL,
    tot_benes      REAL,
    avg_sbmtd_chrg REAL,
    avg_mdcr_pymt  REAL,
    PRIMARY KEY (npi, cpt, year)
);

CREATE TABLE IF NOT EXISTS care_compare (
    ccn        TEXT NOT NULL,
    measure_id TEXT NOT NULL,
    score      REAL,
    as_of      TEXT,
    PRIMARY KEY (ccn, measure_id)
);

CREATE TABLE IF NOT EXISTS ingest_log (
    dataset  TEXT PRIMARY KEY,
    source_path TEXT,
    rows     INTEGER,
    as_of    TEXT,
    ingested_at TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DB:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "DB":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---- raw response cache -------------------------------------------
    def cache_put(self, source: str, key: str, payload: str, url: str | None = None) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO raw_cache(source, key, url, payload, fetched_at) "
            "VALUES (?,?,?,?,?)",
            (source, key, url, payload, _now()),
        )
        self.conn.commit()

    def cache_get(self, source: str, key: str) -> str | None:
        row = self.conn.execute(
            "SELECT payload FROM raw_cache WHERE source=? AND key=?", (source, key)
        ).fetchone()
        return row["payload"] if row else None

    def cache_get_json(self, source: str, key: str) -> Any | None:
        raw = self.cache_get(source, key)
        return json.loads(raw) if raw is not None else None

    def cache_require(self, source: str, key: str) -> str:
        """Offline-mode read: raise CacheMiss instead of silently returning None."""
        raw = self.cache_get(source, key)
        if raw is None:
            raise CacheMiss(
                f"--offline run needs cached {source!r} key {key!r}, but it is not in "
                f"{self.path}. Run once online first to populate the cache (Spec §4)."
            )
        return raw

    def cache_fetched_at(self, source: str, key: str) -> str | None:
        row = self.conn.execute(
            "SELECT fetched_at FROM raw_cache WHERE source=? AND key=?", (source, key)
        ).fetchone()
        return row["fetched_at"] if row else None

    # ---- bulk: medicare volume ----------------------------------------
    def upsert_medicare(self, rows: list[dict[str, Any]]) -> None:
        self.conn.executemany(
            "INSERT OR REPLACE INTO medicare_volume"
            "(npi, cpt, year, tot_srvcs, tot_benes, avg_sbmtd_chrg, avg_mdcr_pymt) "
            "VALUES (:npi,:cpt,:year,:tot_srvcs,:tot_benes,:avg_sbmtd_chrg,:avg_mdcr_pymt)",
            rows,
        )
        self.conn.commit()

    def medicare_for(self, npi: str, cpts: list[str]) -> list[sqlite3.Row]:
        if not cpts:
            return []
        q = "SELECT * FROM medicare_volume WHERE npi=? AND cpt IN (%s)" % (
            ",".join("?" * len(cpts))
        )
        return self.conn.execute(q, [npi, *cpts]).fetchall()

    def top_npis_by_volume(
        self, cpts: list[str], n: int, year: str | None = None
    ) -> list[tuple[str, float]]:
        """National candidate seeding (Spec §3.2): the N NPIs with the highest
        summed ADR service volume across the requested CPTs. This is the Medicare
        FFS *floor*, not total caseload — the report labels it so. Returns
        (npi, total_volume) descending."""
        if not cpts or n <= 0:
            return []
        placeholders = ",".join("?" * len(cpts))
        params: list[Any] = [*cpts]
        year_clause = ""
        if year:
            year_clause = " AND year=?"
            params.append(year)
        q = (
            "SELECT npi, SUM(COALESCE(tot_srvcs,0)) AS vol FROM medicare_volume "
            f"WHERE cpt IN ({placeholders}){year_clause} "
            "GROUP BY npi ORDER BY vol DESC, npi ASC LIMIT ?"
        )
        params.append(n)
        return [(r["npi"], r["vol"]) for r in self.conn.execute(q, params).fetchall()]

    # ---- bulk: care compare -------------------------------------------
    def upsert_care_compare(self, rows: list[dict[str, Any]]) -> None:
        self.conn.executemany(
            "INSERT OR REPLACE INTO care_compare(ccn, measure_id, score, as_of) "
            "VALUES (:ccn,:measure_id,:score,:as_of)",
            rows,
        )
        self.conn.commit()

    def care_compare_for(self, ccn: str, measure_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM care_compare WHERE ccn=? AND measure_id=?", (ccn, measure_id)
        ).fetchone()

    # ---- ingest bookkeeping -------------------------------------------
    def log_ingest(self, dataset: str, source_path: str, rows: int, as_of: str | None) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO ingest_log(dataset, source_path, rows, as_of, ingested_at) "
            "VALUES (?,?,?,?,?)",
            (dataset, source_path, rows, as_of, _now()),
        )
        self.conn.commit()

    def ingest_info(self, dataset: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM ingest_log WHERE dataset=?", (dataset,)
        ).fetchone()

"""KODEX command-line interface.

  kodex run [--config config.yaml] [--offline] [--out out/report.pdf]
  kodex ingest-medicare <csv> --year CY2024 [--config config.yaml]
  kodex ingest-care-compare <csv> --label complications [--as-of CY2024]

Bulk ingest commands load the big Medicare / Care Compare CSVs into SQLite once;
`run` then queries them locally and produces the PDF (online to refresh the
cache, or --offline to rebuild from cache).
"""

from __future__ import annotations

import argparse
import sys

from . import __version__, pipeline
from .config import Config
from .connectors import care_compare, medicare_volume
from .db import DB


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kodex", description="ADR cost-vs-quality decision matrix.")
    parser.add_argument("--version", action="version", version=f"KODEX {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    rp = sub.add_parser("run", help="run the pipeline and produce the PDF report")
    rp.add_argument("--config", default="config.yaml")
    rp.add_argument("--offline", action="store_true", help="rebuild from SQLite cache, no network")
    rp.add_argument("--out", default=None, help="output PDF path (default out/report_<date>.pdf)")

    mp = sub.add_parser("ingest-medicare", help="ingest the Medicare bulk CSV into SQLite")
    mp.add_argument("csv")
    mp.add_argument("--year", required=True, help="reporting year label, e.g. CY2024")
    mp.add_argument("--config", default="config.yaml")

    cp = sub.add_parser("ingest-care-compare", help="ingest a Care Compare measures CSV")
    cp.add_argument("csv")
    cp.add_argument("--label", required=True, help="dataset label, e.g. complications")
    cp.add_argument("--as-of", default=None)
    cp.add_argument("--config", default="config.yaml")

    args = parser.parse_args(argv)
    cfg = Config.load(args.config)

    if args.cmd == "run":
        offline = args.offline or cfg.offline
        pipeline.run(cfg, offline=offline, out_path=args.out)
        return 0

    if args.cmd == "ingest-medicare":
        with DB(cfg.db_path) as db:
            n = medicare_volume.ingest_csv(db, args.csv, cfg.cpt_codes, args.year)
        print(f"ingested {n} Medicare ADR-CPT rows from {args.csv}")
        return 0

    if args.cmd == "ingest-care-compare":
        with DB(cfg.db_path) as db:
            n = care_compare.ingest_csv(db, args.csv, args.label, args.as_of)
        print(f"ingested {n} Care Compare rows from {args.csv}")
        return 0

    parser.error(f"unknown command {args.cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main())

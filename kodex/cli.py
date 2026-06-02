"""KODEX command-line interface.

  kodex run [--config config.yaml] [--offline] [--out out/report.pdf]
  kodex fetch-bulk [--config config.yaml] [--only NAME ...] [--no-ingest] [--write-config]
  kodex ingest-medicare <csv> --year CY2024 [--config config.yaml]
  kodex ingest-care-compare <csv> --label complications [--as-of CY2024]

`fetch-bulk` resolves the current public datasets from CMS's machine catalogs
(by title, so rotating UUIDs don't break it), downloads the Medicare/Care Compare
CSVs, ingests them into SQLite, and resolves the Open Payments dataset id. The
manual `ingest-*` commands remain for operators who already hold the CSVs.
`run` then queries the local SQLite and produces the PDF (online to refresh the
cache, or --offline to rebuild from cache).
"""

from __future__ import annotations

import argparse
import re
import sys

from . import __version__, pipeline
from .config import Config
from .connectors import care_compare, datasets, medicare_volume
from .connectors.base import HttpClient
from .db import DB


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kodex", description="ADR cost-vs-quality decision matrix.")
    parser.add_argument("--version", action="version", version=f"KODEX {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    rp = sub.add_parser("run", help="run the pipeline and produce the PDF report")
    rp.add_argument("--config", default="config.yaml")
    rp.add_argument("--offline", action="store_true", help="rebuild from SQLite cache, no network")
    rp.add_argument("--out", default=None, help="output PDF path (default out/report_<date>.pdf)")

    fb = sub.add_parser("fetch-bulk", help="resolve + download + ingest the public bulk datasets")
    fb.add_argument("--config", default="config.yaml")
    fb.add_argument(
        "--only", action="append", default=None,
        choices=["medicare", "cc-complications", "cc-readmissions", "open-payments"],
        help="limit to one or more datasets (default: all). Repeatable.",
    )
    fb.add_argument("--no-ingest", action="store_true", help="download only; skip SQLite ingest")
    fb.add_argument(
        "--write-config", action="store_true",
        help="write the resolved Open Payments dataset id back into config.yaml",
    )

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

    if args.cmd == "fetch-bulk":
        return _fetch_bulk(cfg, args)

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


def _err(msg: str) -> None:
    print(f"[kodex] {msg}", file=sys.stderr)


def _fetch_bulk(cfg: Config, args: argparse.Namespace) -> int:
    """Resolve current distributions from CMS catalogs, download the CSVs, ingest
    them, and resolve the Open Payments dataset id. Each dataset is independent:
    a failure on one is reported and the rest proceed (Spec §11 resilience)."""
    wanted = set(args.only) if args.only else {"medicare", "cc-complications", "cc-readmissions", "open-payments"}
    max_bytes = int(cfg.get("mrf", "max_download_bytes", default=3_000_000_000))
    rps = float(cfg.get("rate_limits", "default_rps", default=5))
    failures = 0

    with DB(cfg.db_path) as db, HttpClient(rps=rps) as http:
        # --- Medicare Physician & Other Practitioners (by Provider and Service) ---
        if "medicare" in wanted:
            try:
                year = str(cfg.get("catalogs", "medicare_year", default="") or "")
                dist = datasets.resolve_csv(
                    db, http,
                    cfg.get("catalogs", "cms_data_json", default="https://data.cms.gov/data.json"),
                    cfg.get("catalogs", "medicare_title",
                            default="Medicare Physician & Other Practitioners - by Provider and Service"),
                    year=year or None,
                )
                dest = cfg.bulk_data("medicare_csv") or "data/bulk/medicare_physician_other.csv"
                _err(f"medicare: {dist.dataset_title!r} (modified {dist.modified}) -> {dest}")
                n = datasets.download_csv(http, dist, dest, max_bytes=max_bytes)
                _err(f"medicare: downloaded {n:,} bytes")
                if not args.no_ingest:
                    rows = medicare_volume.ingest_csv(db, dest, cfg.cpt_codes, f"CY{year}" if year else "CY")
                    _err(f"medicare: ingested {rows} ADR-CPT rows")
            except Exception as exc:  # noqa: BLE001 — one dataset must not abort the rest
                failures += 1
                _err(f"medicare: FAILED — {type(exc).__name__}: {exc}")

        # --- Care Compare: complications (PSI-90) and readmissions ---
        cc_jobs = [
            ("cc-complications", "care_compare_complications_title", "Complications and Deaths - Hospital",
             "care_compare_complications_csv", "complications"),
            ("cc-readmissions", "care_compare_readmissions_title", "Unplanned Hospital Visits - Hospital",
             "care_compare_readmissions_csv", "readmissions"),
        ]
        for name, title_key, title_default, path_key, label in cc_jobs:
            if name not in wanted:
                continue
            try:
                dist = datasets.resolve_csv(
                    db, http,
                    cfg.get("catalogs", "provider_data_metastore",
                            default="https://data.cms.gov/provider-data/api/1/metastore/schemas/dataset/items"),
                    cfg.get("catalogs", title_key, default=title_default),
                )
                dest = cfg.bulk_data(path_key) or f"data/bulk/care_compare_{label}.csv"
                _err(f"{name}: {dist.dataset_title!r} (modified {dist.modified}) -> {dest}")
                n = datasets.download_csv(http, dist, dest, max_bytes=max_bytes)
                _err(f"{name}: downloaded {n:,} bytes")
                if not args.no_ingest:
                    as_of = cfg.get("care_compare", "reporting_period", default=None)
                    rows = care_compare.ingest_csv(db, dest, label, as_of)
                    _err(f"{name}: ingested {rows} rows")
            except Exception as exc:  # noqa: BLE001
                failures += 1
                _err(f"{name}: FAILED — {type(exc).__name__}: {exc}")

        # --- Open Payments: resolve the datastore-query dataset id ---
        if "open-payments" in wanted:
            try:
                op_year = str(cfg.get("catalogs", "open_payments_year", default="") or "")
                dist = datasets.resolve_open_payments_id(
                    db, http,
                    cfg.get("catalogs", "open_payments_metastore",
                            default="https://openpaymentsdata.cms.gov/api/1/metastore/schemas/dataset/items"),
                    cfg.get("catalogs", "open_payments_general_title", default="General Payment Data"),
                    year=op_year or None,
                )
                _err(f"open-payments: {dist.dataset_title!r} -> dataset_id = {dist.identifier}")
                if args.write_config and dist.identifier:
                    _write_open_payments_id(args.config, dist.identifier)
                    _err(f"open-payments: wrote dataset_id into {args.config}")
                elif dist.identifier:
                    _err(f"open-payments: set open_payments.dataset_id: \"{dist.identifier}\" in config.yaml "
                         f"(or re-run with --write-config)")
            except Exception as exc:  # noqa: BLE001
                failures += 1
                _err(f"open-payments: FAILED — {type(exc).__name__}: {exc}")

    if failures:
        _err(f"fetch-bulk completed with {failures} dataset failure(s).")
        return 1
    _err("fetch-bulk complete.")
    return 0


def _write_open_payments_id(config_path: str, dataset_id: str) -> None:
    """Targeted line edit of `dataset_id:` under open_payments — preserves the
    file's comments (a full YAML round-trip would strip them)."""
    from pathlib import Path

    text = Path(config_path).read_text(encoding="utf-8")
    new_text, n = re.subn(
        r'(?m)^(\s*dataset_id:\s*).*$',
        lambda m: f'{m.group(1)}"{dataset_id}"',
        text,
        count=1,
    )
    if n == 0:
        raise ValueError(
            f"could not find a `dataset_id:` line in {config_path} to update; "
            f"set open_payments.dataset_id manually to {dataset_id!r}."
        )
    Path(config_path).write_text(new_text, encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())

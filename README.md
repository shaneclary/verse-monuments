# KODEX — Spine Surgery (ADR) Cost-vs-Quality Decision Matrix

> **Note on this repo:** this branch hosts **KODEX**, a standalone offline Python
> pipeline, at the repository root. The earlier "RIPNYC" web project still lives
> in the [`verse-monuments/`](./verse-monuments) subdirectory and is unrelated to
> KODEX.

KODEX is a **decision-support aggregator**, not an outcomes oracle. It pulls
public provider, cost, and quality-signal data, normalizes it, scores it with
transparent and configurable weights, and prints an honest two-axis matrix
(**cost vs. a labeled quality _proxy_**) plus a procedure-evidence summary.

The deliverable for the (offline, no-internet) end user is a **printed/PDF
report** — see [`examples/sample_report.pdf`](./examples/sample_report.pdf) for a
sample built from synthetic data.

## What it is — and is NOT

- **It IS** a pipeline that aggregates obtainable public signals and presents a
  defensible **shortlist to ask about**, with every number sourced and dated.
- **It is NOT** a source of per-surgeon clinical success rates. Those do not
  exist in public, machine-readable form. KODEX **never** prints a fabricated
  per-provider "success rate." Every quality number is a clearly labeled
  **proxy** or a **facility-level** (not surgeon-level) measure.
- **Hard rule:** any data point that cannot be sourced renders as `UNKNOWN` and
  the report says why. No interpolation, no guessing, no invented numbers.
- It does **not** replace a surgical consultation or a second opinion.

## Quality proxy & cost axis

- **Quality proxy (0–1):** a weighted blend of obtainable signals — board
  certification, spine fellowship, a Medicare volume _floor_, facility-level
  complication/readmission measures, facility-level **patient satisfaction
  (HCAHPS)**, and years in practice. Missing signals are **excluded and the
  weights renormalized** (never imputed); too-sparse rows score `UNKNOWN`. A
  disciplinary flag applies a fixed penalty and is always surfaced.
- **No fabricated "success" or "satisfaction":** there is no public per-surgeon
  success rate or satisfaction score, so KODEX never prints one. "Success" maps
  to the labeled quality proxy above; "satisfaction" maps to HCAHPS, which is a
  **whole-hospital** survey — not surgeon- or ADR-specific. Both are labeled as
  such everywhere they appear.
- **Cost axis:** the hospital **facility cash price** for the ADR CPT codes —
  **not** the all-in episode (surgeon fee, anesthesia, implant, imaging, and
  follow-up are extra). Labeled "facility-only" throughout.
- **The matrix** plots cost ($) vs. quality proxy and highlights the **Pareto
  frontier** (rows not beaten on both axes). It deliberately does **not** collapse
  to a single ranking number.

## Install

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e .            # or: pip install httpx 'pydantic>=2' pandas pyyaml weasyprint ijson
pip install pytest          # for the test suite
```

WeasyPrint needs system libraries (pango/cairo) for PDF rendering; see the
[WeasyPrint install docs](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html)
for your OS.

## Configure

Everything is driven by **`config.yaml`** — geography, CPT codes, endpoints, and
scoring weights. To change a weight, endpoint, or the geography, edit only this
file; no code changes. Confirm the items marked `CONFIRM`/`VERIFY` before a real
run (geography, current CPT set, cash-pay assumption).

### Search scope — local vs. national (`seeding.mode`)

- **`state`** — NPPES taxonomy sweep within `geography.state` (a local search).
- **`national_medicare_topn`** — for a client willing to **travel anywhere**:
  rank every ADR provider in the country by the Medicare volume _floor_ and take
  the top `seeding.top_n` (e.g. 100), then enrich each via NPPES. The candidate
  list (surgeon + credentials + volume) is produced automatically; **cost (MRF)
  and facility quality/satisfaction still populate only for facilities you
  roster** (CCN + `mrf_domain`) — you'd roster the handful you'd seriously fly
  to, not all 100. Requires the Medicare table to be ingested first
  (`kodex fetch-bulk`). `geography.state`/radius are ignored in this mode.

## Manual inputs

Some signals have **no free public API** and are entered by the operator into
small CSVs under `data/manual_inputs/` (templates included, headers only):

| File | Signal | Source |
|------|--------|--------|
| `abms.csv` | board certification | ABMS Certification Matters (one-at-a-time) |
| `state_board.csv` | license + disciplinary | state medical board lookups |
| `fairhealth.csv` | geographic cost benchmark / MRF fallback | FAIR Health consumer tool |
| `facility_roster.csv` | shortlisted facilities + CCN + MRF domain | operator-curated |
| `provider_facility.csv` | surgeon → facility (CCN) link | operator-curated |

## Bulk datasets

The large Medicare and Care Compare datasets are **ingested once** into SQLite,
then queried locally.

### Turnkey: `kodex fetch-bulk` (recommended)

One command resolves the **current** public datasets from CMS's machine catalogs
— Medicare (volume floor), Care Compare complications (PSI-90) / readmissions /
**HCAHPS** (satisfaction) — downloads + ingests them, and resolves the Open
Payments dataset id:

```bash
kodex fetch-bulk                      # all datasets, download + ingest
kodex fetch-bulk --write-config       # also persist the resolved Open Payments id
kodex fetch-bulk --only medicare      # one dataset (repeatable); --no-ingest to skip ingest
# datasets: medicare | cc-complications | cc-readmissions | cc-hcahps | open-payments
```

Resolution is **by dataset title, not by UUID** — CMS rotates distribution
identifiers every vintage, so KODEX reads each catalog's index
(`data.cms.gov/data.json`, the Provider Data and Open Payments metastores) and
picks the live distribution whose title matches the `catalogs:` block in
`config.yaml`. If a fetch reports *"no dataset matched"*, a dataset was renamed —
update the title there (no code change). Years are taken from
`catalogs.medicare_year` / `catalogs.open_payments_year`; an unavailable year
**fails loudly** rather than silently pulling a different vintage. Each dataset is
independent — one failure is reported and the rest proceed (exit code is non-zero
if any failed).

> This environment's egress allowlist blocks the CMS/NIH hosts, so `fetch-bulk`
> is run by the operator on a networked machine. The resolvers are unit-tested
> against catalog fixtures so the logic is verified regardless.

### Manual: pre-downloaded CSVs

If you already hold the CSVs, ingest them directly:

```bash
kodex ingest-medicare      data/bulk/medicare_physician_other.csv --year CY2024
kodex ingest-care-compare  data/bulk/complications.csv  --label complications --as-of CY2024
kodex ingest-care-compare  data/bulk/readmissions.csv   --label readmissions --as-of CY2024
```

## Run

```bash
kodex run                  # online: fetch + cache + score + render out/report_<date>.pdf
kodex run --offline        # rebuild the same report from the SQLite cache, no network
```

**Offline guarantee:** every network step caches its response before scoring, so
a second run with `--offline` reproduces the report with no internet. The end
user only ever needs the paper/PDF.

### See it work without any setup

```bash
PYTHONPATH=. python scripts/generate_sample_report.py   # -> out/sample_report.pdf
```

This seeds a throwaway cache + manual inputs with **clearly synthetic** data
(fake NPIs/hospitals), exercises both cost paths (streamed MRF and FAIR Health
fallback), and renders a full report offline.

## Architecture

```
config.yaml                # single source of truth (§7)
kodex/
  models.py                # pydantic schemas (Provider, Facility, Evidence, MatrixRow)
  config.py  db.py errors.py
  connectors/
    nppes.py               # provider directory + credentials (§3.1)
    medicare_volume.py     # ADR volume proxy — Medicare FFS FLOOR (§3.2)
    open_payments.py       # industry/device-maker signal, display-only (§3.3)
    mrf_cost.py            # hospital MRF: cms-hpt.txt discovery + STREAMING parse (§3.4)
    care_compare.py        # facility-level complication/readmission (§3.5)
    datasets.py            # bulk-dataset acquisition: resolve-by-title + download (§3.2/§3.5)
    fairhealth_manual.py abms_manual.py state_board_manual.py roster.py   # manual adapters
    pubmed.py              # aggregate procedure evidence — never per-surgeon (§3.9)
  scoring.py               # pure, deterministic, transparent scoring + Pareto (§6)
  pipeline.py              # the run sequence (§8)
  report.py                # offline HTML -> PDF, print-legible, no color dependency (§9)
scripts/generate_sample_report.py
tests/                     # scoring (test-first), MRF streaming parse, offline pipeline
```

**Stack:** Python 3.11+, `httpx`, `pydantic` v2, `pandas`, `ijson` (streaming),
SQLite (stdlib), WeasyPrint (HTML→PDF). No web server, no cloud — a boring,
offline-friendly batch pipeline.

## Tests

```bash
python -m pytest            # scoring, MRF parsing (incl. memory-flatness), offline pipeline
```

## Known limitations (verify before trusting output)

- **CPT codes** change annually — re-verify the current ADR set (`config.yaml`).
- **Medicare volume is a FLOOR**, badly so for ADR (younger, commercially-insured
  patients) — never present it as total caseload.
- **Facility quality ≠ surgeon quality** — Care Compare is facility-level.
- **Cost is partial** — MRF is the facility component only, not the full episode.
- **MRF schema drift / non-compliance** — the parser degrades to `UNKNOWN`/FAIR
  Health fallback rather than crashing or fabricating.
- **Not a second-opinion substitute** — KODEX surfaces a shortlist to ask about,
  not a verdict.

Section references (§) point to the original build specification.

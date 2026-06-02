"""Offline printable report — THE deliverable (Spec §9).

Renders an HTML template -> PDF (WeasyPrint). The friend has no internet, so the
printout IS the product. Print-legibility matters: the matrix uses marker SHAPES
and numeric labels, never color alone, so it survives a black-and-white printer.

Contents, in spec order:
  1. Plain-language preface (proxies, not outcome guarantees; not a 2nd opinion)
  2. The matrix (shape-coded scatter + table, Pareto frontier highlighted)
  3. Per-provider cards (every signal + source, UNKNOWN where absent, disc. notes)
  4. Cost breakdown (cash price per CPT; what's NOT included; benchmark)
  5. Procedure-evidence summary (aggregate literature; "about the operation")
  6. Sources & dates appendix (each dataset, as-of, known limitation)
"""

from __future__ import annotations

import html
from pathlib import Path

from .models import MatrixRow, ReportBundle

# Human labels for proxy component keys.
_SIGNAL_LABELS = {
    "board_certified": "Board certified",
    "fellowship_spine": "Spine fellowship",
    "medicare_adr_volume": "Medicare ADR volume (FFS floor)",
    "facility_complication": "Facility complication (facility-level)",
    "facility_readmission": "Facility readmission (facility-level)",
    "years_in_practice": "Years in practice (proxy)",
    "open_payments": "Open Payments (display)",
    "_disciplinary_penalty": "Disciplinary penalty",
}


def _u(v) -> str:
    """Render a value, or UNKNOWN when missing (Spec hard rule)."""
    return html.escape(str(v)) if v is not None and v != "" else "<span class='unk'>UNKNOWN</span>"


def _money(v) -> str:
    return f"${v:,.0f}" if isinstance(v, (int, float)) else "<span class='unk'>UNKNOWN</span>"


def _pct(v) -> str:
    return f"{v*100:.0f}%" if isinstance(v, (int, float)) else "<span class='unk'>UNKNOWN</span>"


def _score(v) -> str:
    return f"{v:.2f}" if isinstance(v, (int, float)) else "<span class='unk'>UNKNOWN</span>"


# ---------------------------------------------------------------------------
# Matrix scatter (SVG, shape-coded — no color dependency)
# ---------------------------------------------------------------------------
def build_scatter_svg(rows: list[MatrixRow]) -> str:
    placeable = [
        (i, r) for i, r in enumerate(rows, start=1)
        if r.cost_estimate is not None and r.quality_proxy_score is not None
    ]
    if not placeable:
        return "<p class='unk'>No rows have both a cost and a quality-proxy score, so the matrix cannot be plotted.</p>"

    W, H = 640, 380
    ml, mr, mt, mb = 70, 20, 20, 50
    costs = [r.cost_estimate for _, r in placeable]
    cmin, cmax = min(costs), max(costs)
    if cmax == cmin:
        cmax = cmin + 1  # avoid divide-by-zero

    def x(cost: float) -> float:
        return ml + (cost - cmin) / (cmax - cmin) * (W - ml - mr)

    def y(q: float) -> float:
        return mt + (1 - q) * (H - mt - mb)  # quality 0 at bottom, 1 at top

    parts = [f'<svg viewBox="0 0 {W} {H}" width="100%" xmlns="http://www.w3.org/2000/svg" font-family="sans-serif" font-size="11">']
    # Axes
    parts.append(f'<line x1="{ml}" y1="{mt}" x2="{ml}" y2="{H-mb}" stroke="black"/>')
    parts.append(f'<line x1="{ml}" y1="{H-mb}" x2="{W-mr}" y2="{H-mb}" stroke="black"/>')
    # Y ticks (quality)
    for q in (0.0, 0.25, 0.5, 0.75, 1.0):
        yy = y(q)
        parts.append(f'<line x1="{ml-4}" y1="{yy:.1f}" x2="{ml}" y2="{yy:.1f}" stroke="black"/>')
        parts.append(f'<text x="{ml-8}" y="{yy+3:.1f}" text-anchor="end">{q:.2f}</text>')
    # X ticks (cost)
    for frac in (0.0, 0.5, 1.0):
        cost = cmin + frac * (cmax - cmin)
        xx = x(cost)
        parts.append(f'<line x1="{xx:.1f}" y1="{H-mb}" x2="{xx:.1f}" y2="{H-mb+4}" stroke="black"/>')
        parts.append(f'<text x="{xx:.1f}" y="{H-mb+18:.1f}" text-anchor="middle">${cost:,.0f}</text>')
    # Axis titles
    parts.append(f'<text x="{(ml+W-mr)/2:.0f}" y="{H-6}" text-anchor="middle" font-weight="bold">Cost — cash price, facility-only ($, lower better →)</text>')
    parts.append(f'<text transform="translate(16,{(mt+H-mb)/2:.0f}) rotate(-90)" text-anchor="middle" font-weight="bold">Quality proxy (0–1, higher better ↑)</text>')

    # Frontier polyline (sorted by cost) drawn through filled-square points.
    frontier = sorted(
        [(i, r) for i, r in placeable if r.on_pareto_frontier],
        key=lambda t: t[1].cost_estimate,
    )
    if len(frontier) >= 2:
        pts = " ".join(f"{x(r.cost_estimate):.1f},{y(r.quality_proxy_score):.1f}" for _, r in frontier)
        parts.append(f'<polyline points="{pts}" fill="none" stroke="black" stroke-dasharray="4 3"/>')

    # Points: filled square = on frontier; hollow circle = dominated.
    for i, r in placeable:
        px, py = x(r.cost_estimate), y(r.quality_proxy_score)
        if r.on_pareto_frontier:
            parts.append(f'<rect x="{px-4:.1f}" y="{py-4:.1f}" width="8" height="8" fill="black"/>')
        else:
            parts.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="4" fill="white" stroke="black"/>')
        parts.append(f'<text x="{px+6:.1f}" y="{py-5:.1f}">{i}</text>')

    # Legend (shapes, not colors)
    lx, ly = W - 220, mt + 6
    parts.append(f'<rect x="{lx}" y="{ly}" width="8" height="8" fill="black"/>')
    parts.append(f'<text x="{lx+14}" y="{ly+8}">on Pareto frontier</text>')
    parts.append(f'<circle cx="{lx+4}" cy="{ly+22}" r="4" fill="white" stroke="black"/>')
    parts.append(f'<text x="{lx+14}" y="{ly+26}">dominated</text>')
    parts.append("</svg>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------
def _preface(b: ReportBundle) -> str:
    cs = b.config_summary
    return f"""
    <section class="page">
      <h1>{html.escape(cs.get('title', 'KODEX — ADR Cost vs. Quality Matrix'))}</h1>
      <p class="meta">Generated {html.escape(b.generated_at)} · Procedure:
         {html.escape(cs.get('procedure_label',''))} · Geography:
         {html.escape(str(cs.get('state','?')))} / {html.escape(str(cs.get('center_zip','?')))}
         within {html.escape(str(cs.get('radius_miles','?')))} miles.</p>
      <h2>Read this first</h2>
      <p><strong>What this is.</strong> KODEX is a decision-support aggregator. It pulls
      public provider, cost, and quality-signal data, scores it with transparent and
      configurable weights, and prints a two-axis matrix of cost versus a labeled
      quality <em>proxy</em>, plus a summary of the published evidence on the operation.</p>
      <p><strong>What it is NOT.</strong> It is not a source of per-surgeon clinical success
      rates — those do not exist in public, machine-readable form. Every quality number
      here is a clearly labeled <em>proxy</em> or a <em>facility-level</em> (not surgeon-level)
      measure. Where a data point cannot be sourced it is shown as
      <span class="unk">UNKNOWN</span>; nothing is interpolated or invented.</p>
      <p><strong>Quality axis.</strong> The "quality proxy" is a weighted blend of obtainable
      signals (board certification, spine fellowship, a Medicare volume <em>floor</em>,
      facility-level complication/readmission measures, and years in practice). It is a
      proxy, not an outcome guarantee.</p>
      <p><strong>Cost axis.</strong> Cost is the hospital <em>facility</em> cash price for the
      relevant CPT codes. It is <em>not</em> the all-in episode cost — surgeon professional
      fees, anesthesia, the implant device, imaging, and follow-up are extra (see the Cost
      Breakdown section).</p>
      <p class="warn"><strong>This does not replace a surgical consultation or a second
      opinion.</strong> The strongest thing KODEX offers is a defensible shortlist of
      facilities and surgeons to <em>ask about</em> — not a verdict.</p>
    </section>
    """


def _matrix_section(b: ReportBundle) -> str:
    rows = b.rows
    svg = build_scatter_svg(rows)
    trows = []
    for i, r in enumerate(rows, start=1):
        on = "■ yes" if r.on_pareto_frontier else "○ no"
        note = f" <span class='unk'>({html.escape(r.quality_note)})</span>" if r.quality_note else ""
        trows.append(
            f"<tr><td>{i}</td><td>{html.escape(r.provider.name)}</td>"
            f"<td>{html.escape(r.facility.name)}</td>"
            f"<td>{_money(r.cost_estimate)}{' (facility-only)' if r.cost_estimate is not None else ''}</td>"
            f"<td>{_score(r.quality_proxy_score)}{note}</td>"
            f"<td>{on}</td><td>{_pct(r.data_completeness)}</td></tr>"
        )
    return f"""
    <section class="page">
      <h2>The matrix — cost vs. quality proxy</h2>
      <p>Each point is a surgeon × facility pairing. Lower-and-to-the-left is cheaper;
      higher-up is a stronger quality proxy. Points on the <strong>Pareto frontier</strong>
      (filled squares, connected by the dashed line) are not beaten on both axes by any
      other point — they are the defensible shortlist to ask about.</p>
      {svg}
      <table>
        <thead><tr><th>#</th><th>Surgeon</th><th>Facility</th><th>Cost (cash)</th>
        <th>Quality proxy</th><th>Frontier</th><th>Data completeness</th></tr></thead>
        <tbody>{''.join(trows)}</tbody>
      </table>
      <p class="small">Rows showing <span class="unk">UNKNOWN</span> for quality or cost
      cannot be plotted and are excluded from the frontier (they are still listed for
      transparency).</p>
    </section>
    """


def _component_table(r: MatrixRow) -> str:
    cells = []
    for key, label in _SIGNAL_LABELS.items():
        if key not in r.proxy_components:
            continue
        val = r.proxy_components.get(key)
        cells.append(f"<tr><td>{html.escape(label)}</td><td>{_score(val)}</td></tr>")
    if not cells:
        return ""
    return f"<table class='mini'><thead><tr><th>Proxy component</th><th>Contribution</th></tr></thead><tbody>{''.join(cells)}</tbody></table>"


def _provider_cards(b: ReportBundle) -> str:
    cards = []
    for i, r in enumerate(b.rows, start=1):
        p, f = r.provider, r.facility
        disc = ""
        if p.disciplinary_flag:
            disc = (f"<p class='warn'><strong>⚠ Disciplinary action on record.</strong> "
                    f"{_u(p.disciplinary_note)} (state medical board, manual check)</p>")
        top_pay = "; ".join(p.top_payers) if p.top_payers else None
        cards.append(f"""
        <div class="card">
          <h3>#{i} · {html.escape(p.name)} <span class="small">NPI {_u(p.npi)}</span></h3>
          {disc}
          <div class="cols">
            <div>
              <h4>Surgeon</h4>
              <ul>
                <li>Credential (self-reported, NPPES): {_u(p.credential)}</li>
                <li>Taxonomy: {_u(p.taxonomy)}</li>
                <li>Board certified (ABMS, manual): {_u(p.board_certified)} {('— ' + html.escape(p.board_name)) if p.board_name else ''}</li>
                <li>Spine fellowship: {_u(p.fellowship_spine)}</li>
                <li>License active (state board, manual): {_u(p.license_active)}</li>
                <li>Years in practice (NPPES enumeration proxy): {_u(p.years_in_practice_proxy)}</li>
                <li>Medicare ADR volume (FFS <em>floor</em>, not total): {_u(p.medicare_adr_volume)}</li>
                <li>Medicare avg payment: {_money(p.medicare_avg_payment)}</li>
                <li>Open Payments total (transparency, display-only): {_money(p.open_payments_total)}</li>
                <li>Top paying companies: {_u(top_pay)}</li>
              </ul>
            </div>
            <div>
              <h4>Facility — {html.escape(f.name)} <span class="small">CCN {_u(f.ccn)}</span></h4>
              <ul>
                <li>Location: {_u(f.state)} {_u(f.zip)}</li>
                <li>Cost source: {_u(f.cost_source)}</li>
                <li>Complication measure (<em>facility-level, not surgeon</em>): {_u(f.complication_measure)}</li>
                <li>Readmission measure (<em>facility-level, not surgeon</em>): {_u(f.readmission_measure)}</li>
              </ul>
              <p><strong>Quality proxy: {_score(r.quality_proxy_score)}</strong>
                 · completeness {_pct(r.data_completeness)}
                 {('· ' + html.escape(r.quality_note)) if r.quality_note else ''}</p>
              {_component_table(r)}
            </div>
          </div>
        </div>
        """)
    return f"<section class='page'><h2>Per-provider detail</h2>{''.join(cards)}</section>"


def _cost_section(b: ReportBundle) -> str:
    cpt_desc = b.config_summary.get("cpt_descriptions", {})
    rows = []
    for i, r in enumerate(b.rows, start=1):
        comp_cells = []
        for cpt, price in (r.cost_components or {}).items():
            comp_cells.append(f"{html.escape(cpt)}: {_money(price)}")
        comp = " · ".join(comp_cells) if comp_cells else "<span class='unk'>UNKNOWN</span>"
        rows.append(
            f"<tr><td>{i}</td><td>{html.escape(r.facility.name)}</td>"
            f"<td>{comp}</td><td>{_money(r.cost_estimate)}</td></tr>"
        )
    bench = []
    for bm in b.benchmarks:
        desc = cpt_desc.get(bm.cpt, "")
        bench.append(
            f"<tr><td>{html.escape(bm.cpt)}</td><td>{html.escape(desc)}</td>"
            f"<td>{html.escape(bm.zip)}</td><td>{_money(bm.estimate)}</td>"
            f"<td>{_u(bm.as_of)}</td></tr>"
        )
    bench_tbl = (
        f"<h3>Geographic benchmark (FAIR Health, manual entry)</h3>"
        f"<table><thead><tr><th>CPT</th><th>Description</th><th>ZIP</th><th>Estimate</th><th>As of</th></tr></thead>"
        f"<tbody>{''.join(bench)}</tbody></table>"
        if bench else "<p class='small'>No FAIR Health benchmark entered.</p>"
    )
    return f"""
    <section class="page">
      <h2>Cost breakdown</h2>
      <p class="warn"><strong>The cash price below is the hospital FACILITY fee only.</strong>
      The full episode also includes the surgeon's professional fee, anesthesia, the implant
      device, pre-op imaging, and follow-up — none of which are in these numbers. Treat the
      facility cash price as a floor and a negotiating anchor, not the all-in cost.</p>
      <table>
        <thead><tr><th>#</th><th>Facility</th><th>Per-CPT cash price</th><th>Bundle total (facility-only)</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
      {bench_tbl}
    </section>
    """


def _evidence_section(b: ReportBundle) -> str:
    if not b.evidence:
        items = "<p class='small'>No procedure-evidence summaries were retrieved.</p>"
    else:
        lis = []
        for ev in b.evidence:
            yr = f" ({ev.year})" if ev.year else ""
            jr = f" — {html.escape(ev.journal)}" if ev.journal else ""
            finding = f"<br><span class='small'>{html.escape(ev.finding)}</span>" if ev.finding else ""
            lis.append(
                f"<li><strong>{html.escape(ev.title)}</strong>{yr}{jr} "
                f"<span class='small'>PMID {html.escape(ev.pmid)}</span>{finding}</li>"
            )
        items = f"<ul class='evidence'>{''.join(lis)}</ul>"
    return f"""
    <section class="page">
      <h2>Procedure-evidence summary</h2>
      <p class="warn">This section is about <strong>the operation</strong>, not about any one
      surgeon. The findings are aggregate results from the published literature and must not
      be read as a prediction for a specific provider.</p>
      {items}
    </section>
    """


def _sources_section(b: ReportBundle) -> str:
    rows = []
    for note in b.source_notes:
        rows.append(
            f"<tr><td>{html.escape(str(note.get('source','')))}</td>"
            f"<td>{_u(note.get('as_of'))}</td>"
            f"<td>{html.escape(str(note.get('limitation','')))}</td></tr>"
        )
    weights = b.weights_used or {}
    wrows = "".join(
        f"<tr><td>{html.escape(k)}</td><td>{html.escape(str(v))}</td></tr>" for k, v in weights.items()
    )
    return f"""
    <section class="page">
      <h2>Sources &amp; dates appendix</h2>
      <table>
        <thead><tr><th>Source</th><th>As of</th><th>Known limitation</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
      <h3>Scoring weights used</h3>
      <table><thead><tr><th>Signal</th><th>Weight</th></tr></thead><tbody>{wrows}</tbody></table>
      <p class="small">To change any weight, endpoint, or the geography, the operator edits
      <code>config.yaml</code> and re-runs — no code changes.</p>
    </section>
    """


_CSS = """
@page { size: letter; margin: 2cm; }
body { font-family: 'DejaVu Sans', sans-serif; color: #111; font-size: 11pt; line-height: 1.4; }
h1 { font-size: 20pt; margin-bottom: 2px; }
h2 { font-size: 15pt; border-bottom: 2px solid #111; padding-bottom: 3px; margin-top: 0; }
h3 { font-size: 12.5pt; margin-bottom: 4px; }
h4 { font-size: 11pt; margin: 6px 0 2px; }
.page { page-break-after: always; }
.page:last-child { page-break-after: auto; }
.meta { color: #444; font-size: 9.5pt; }
.small { font-size: 8.5pt; color: #444; }
.unk { color: #555; font-style: italic; }
.warn { border-left: 4px solid #111; padding-left: 8px; background: #f2f2f2; }
table { width: 100%; border-collapse: collapse; margin: 8px 0; font-size: 9pt; }
th, td { border: 1px solid #999; padding: 3px 5px; text-align: left; vertical-align: top; }
th { background: #eee; }
.mini { width: auto; font-size: 8pt; }
.card { border: 1px solid #111; padding: 8px 10px; margin: 8px 0; page-break-inside: avoid; }
.cols { display: flex; gap: 14px; }
.cols > div { flex: 1; }
ul { margin: 2px 0; padding-left: 16px; }
li { margin: 1px 0; }
.evidence li { margin-bottom: 6px; }
code { background: #eee; padding: 0 3px; }
"""


def render_html(bundle: ReportBundle) -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8">
    <style>{_CSS}</style></head><body>
    {_preface(bundle)}
    {_matrix_section(bundle)}
    {_provider_cards(bundle)}
    {_cost_section(bundle)}
    {_evidence_section(bundle)}
    {_sources_section(bundle)}
    </body></html>"""


def render_pdf(bundle: ReportBundle, out_path: str) -> str:
    """Render the bundle to a PDF at out_path. Returns the path."""
    from weasyprint import HTML  # imported lazily so non-PDF use needs no system libs

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    HTML(string=render_html(bundle)).write_pdf(out_path)
    return out_path

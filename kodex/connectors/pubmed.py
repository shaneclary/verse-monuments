"""PubMed E-utilities — procedure evidence layer, AGGREGATE only (Spec §3.9).

Retrieves recent reviews/meta-analyses on ADR outcomes to inform the PROCEDURE
question (cervical vs. lumbar ADR vs. fusion). Summaries are aggregate findings
from the literature.

HARD RULE: this informs the procedure decision, NEVER the provider ranking. Study
results are never attributed to an individual surgeon (enforced by keeping
Evidence entirely separate from Provider/MatrixRow).
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from typing import Any

from ..db import DB
from ..models import Evidence
from .base import HttpClient, cached_text

# Prefer the strongest evidence: reviews, systematic reviews, meta-analyses.
_FILTER = (
    '(systematic[sb] OR "meta-analysis"[Publication Type] OR review[Publication Type])'
)


def build_queries(region: str) -> list[str]:
    region = (region or "both").lower()
    queries: list[str] = []
    if region in ("cervical", "both"):
        queries.append(
            f'("cervical disc arthroplasty" OR "cervical total disc replacement") '
            f'AND (outcome OR complication OR reoperation) AND {_FILTER}'
        )
    if region in ("lumbar", "both"):
        queries.append(
            f'("lumbar total disc replacement" OR "lumbar disc arthroplasty") '
            f'AND (outcome OR complication OR reoperation) AND {_FILTER}'
        )
    return queries


def esearch(
    db: DB, http: HttpClient | None, endpoint: str, term: str,
    *, retmax: int = 10, api_key: str | None = None, offline: bool = False,
) -> list[str]:
    url = endpoint.rstrip("/") + "/esearch.fcgi"
    params: dict[str, Any] = {
        "db": "pubmed", "term": term, "retmax": retmax,
        "retmode": "json", "sort": "relevance",
    }
    if api_key:
        params["api_key"] = api_key
    body = cached_text(
        db, http, source="pubmed_esearch", key=f"{term}|{retmax}", url=url,
        params=params, offline=offline,
    )
    data = json.loads(body)
    return data.get("esearchresult", {}).get("idlist", []) or []


def parse_pubmed_xml(xml_text: str) -> list[Evidence]:
    """Pure parser: efetch XML -> Evidence list (aggregate findings)."""
    out: list[Evidence] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return out
    for art in root.findall(".//PubmedArticle"):
        pmid_el = art.find(".//MedlineCitation/PMID")
        title_el = art.find(".//Article/ArticleTitle")
        journal_el = art.find(".//Article/Journal/Title")
        year_el = art.find(".//Article/Journal/JournalIssue/PubDate/Year")
        abstract_parts = [
            (e.text or "") for e in art.findall(".//Article/Abstract/AbstractText")
        ]
        abstract = " ".join(p for p in abstract_parts if p).strip()
        year = None
        if year_el is not None and (year_el.text or "").isdigit():
            year = int(year_el.text)
        finding = (abstract[:400] + "…") if len(abstract) > 400 else (abstract or None)
        out.append(
            Evidence(
                pmid=(pmid_el.text if pmid_el is not None else "UNKNOWN"),
                title=("".join(title_el.itertext()).strip() if title_el is not None else "UNKNOWN"),
                year=year,
                journal=(journal_el.text if journal_el is not None else None),
                finding=finding,
            )
        )
    return out


def efetch(
    db: DB, http: HttpClient | None, endpoint: str, pmids: list[str],
    *, api_key: str | None = None, offline: bool = False,
) -> list[Evidence]:
    if not pmids:
        return []
    url = endpoint.rstrip("/") + "/efetch.fcgi"
    params: dict[str, Any] = {
        "db": "pubmed", "id": ",".join(pmids), "retmode": "xml",
    }
    if api_key:
        params["api_key"] = api_key
    body = cached_text(
        db, http, source="pubmed_efetch", key=",".join(pmids), url=url,
        params=params, offline=offline,
    )
    return parse_pubmed_xml(body)


def gather_evidence(
    db: DB, http: HttpClient | None, endpoint: str, region: str,
    *, retmax: int = 8, api_key: str | None = None, offline: bool = False,
) -> list[Evidence]:
    """Run the region-appropriate queries and return de-duplicated Evidence."""
    seen: dict[str, Evidence] = {}
    for term in build_queries(region):
        pmids = esearch(db, http, endpoint, term, retmax=retmax, api_key=api_key, offline=offline)
        for ev in efetch(db, http, endpoint, pmids, api_key=api_key, offline=offline):
            seen.setdefault(ev.pmid, ev)
    return list(seen.values())

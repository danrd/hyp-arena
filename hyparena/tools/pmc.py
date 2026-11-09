"""Full texts from the PubMed Central open-access subset (sources experiment, specs/sources-experiment-2026-11-07.yaml; user
decision 2026-11-07: open access only, nothing that bypasses a site's access rules; only extracted fields are stored in the
repositories, the texts stay in the local cache `data/cache/pmc/`, which is not committed).

    excerpt(pmid) -> methods and results text (with table contents) of an open-access paper, or None

PMID -> PMCID by the NCBI ID converter; the text by E-utilities efetch (db=pmc, XML), which returns the body only for articles
PMC allows to be downloaded (open access and similar); otherwise there is no body and the paper is read from its abstract. Sections are picked by their sec-type or title (methods, results; abstract and discussion left out).
"""
from __future__ import annotations

import json
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

import httpx

CACHE = Path(__file__).resolve().parents[2] / "data" / "cache" / "pmc"
LIMIT = 15000
_SEC = re.compile(r"method|material|result|finding|participant|outcome|statistic|patients|subjects", re.I)
_SKIP = re.compile(r"discussion|introduction|background|conclusion|reference|acknowledg|funding|conflict|supplement", re.I)


def _get(url: str, params: dict, tries: int = 4) -> Optional[httpx.Response]:
    for k in range(tries):
        try:
            r = httpx.get(url, params=params, timeout=60)
            if r.status_code == 200:
                return r
            if r.status_code in (400, 404):
                return None
        except httpx.HTTPError:
            pass
        time.sleep(2 ** k)
    return None


def pmcid(pmid: str) -> Optional[str]:
    r = _get("https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/", {"ids": pmid, "format": "json", "tool": "hyp-arena"})
    recs = (r.json().get("records") if r else None) or []
    return recs[0].get("pmcid") if recs and recs[0].get("pmcid") else None


def is_open(pmc: str) -> bool:
    """Open access by Europe PMC's isOpenAccess flag (2026-11-09: the PMC OA web service URL used before answers 404, so
    every paper looked closed)."""
    r = _get("https://www.ebi.ac.uk/europepmc/webservices/rest/search",
             {"query": f"PMCID:{pmc}", "format": "json", "resultType": "lite"})
    try:
        res = (r.json().get("resultList") or {}).get("result") or [] if r else []
    except ValueError:
        return False
    return bool(res) and res[0].get("isOpenAccess") == "Y"


def _text(el) -> str:
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip()


def _sections(xml: str) -> str:
    root = ET.fromstring(xml)
    body = root.find(".//body")
    if body is None:
        return ""
    out = []
    for sec in body.iter("sec"):
        title = sec.findtext("title") or ""
        kind = sec.get("sec-type") or ""
        if _SKIP.search(title + " " + kind) or not _SEC.search(title + " " + kind):
            continue
        for p in sec.findall("p"):
            out.append(_text(p))
        for tw in sec.findall(".//table-wrap"):
            cap = _text(tw.find("caption")) if tw.find("caption") is not None else ""
            rows = [" | ".join(_text(c) for c in tr) for tr in tw.iter("tr")]
            out.append(("Table: " + cap + " " + " / ".join(rows))[:2500])
    seen, uniq = set(), []
    for x in out:
        if x and x not in seen:
            seen.add(x)
            uniq.append(x)
    return "\n".join(uniq)


def excerpt(pmid: str) -> Optional[str]:
    """Methods and results of the open-access full text, at most LIMIT characters; None when not open access."""
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"{pmid}.json"
    if f.exists():
        return json.loads(f.read_text()).get("text")
    pmc = pmcid(pmid)
    text = None
    if pmc:                                                # efetch gives the body only where PMC allows it (open access,
        r = _get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi", {"db": "pmc", "id": pmc, "retmode": "xml", "tool": "hyp-arena"})   # text mining)
        if r is not None:
            try:
                text = _sections(r.text)[:LIMIT] or None
            except ET.ParseError:
                text = None
    f.write_text(json.dumps({"pmid": pmid, "pmcid": pmc, "text": text}))
    return text


_RES = re.compile(r"result|finding|outcome|efficacy|effect", re.I)
RES_LIMIT = 20000


def results_excerpt(pmid: str) -> Optional[str]:
    """The Results sections and every table of the open-access full text (methods left out), at most RES_LIMIT characters;
    None when not open access (2026-11-09: the methods-first excerpt often cut the results tables off)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"{pmid}.results.json"
    if f.exists():
        return json.loads(f.read_text()).get("text")
    pmc = pmcid(pmid)
    text = None
    if pmc:
        r = _get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi", {"db": "pmc", "id": pmc, "retmode": "xml", "tool": "hyp-arena"})
        if r is not None:
            try:
                root = ET.fromstring(r.text)
                body = root.find(".//body")
                paras, tables = [], []
                if body is not None:
                    for sec in body.findall("sec"):
                        title = (sec.findtext("title") or "") + " " + (sec.get("sec-type") or "")
                        if _RES.search(title) and not _SKIP.search(title):
                            paras += [_text(x) for x in sec.iter("p")]
                for tw in root.iter("table-wrap"):
                    cap = _text(tw.find("caption")) if tw.find("caption") is not None else ""
                    rows = [" | ".join(_text(c) for c in tr) for tr in tw.iter("tr")]
                    tables.append(("Table: " + cap + " " + " / ".join(rows))[:4000])
                uniq = lambda xs: list(dict.fromkeys(x for x in xs if x))
                tab = "\n".join(uniq(tables))[:RES_LIMIT // 2]          # tables keep at least half of the room
                text = ("\n".join(uniq(paras))[:RES_LIMIT - len(tab)] + "\n" + tab).strip() or None
            except ET.ParseError:
                text = None
    f.write_text(json.dumps({"pmid": pmid, "pmcid": pmc, "text": text}))
    return text

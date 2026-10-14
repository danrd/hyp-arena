"""Retraction check from the Retraction Watch dataset (Crossref; CSV from GitLab, ~67 MB).

`python -m hyparena.tools.retractions download` saves it to data/cache/ (not in git). The index marks
evidence whose DOI or PMID was retracted. With `as_of`, only retractions dated on or before it count:
at date T a later retraction was not known."""
from __future__ import annotations

import csv
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from hyparena.state import Evidence

URL = "https://gitlab.com/crossref/retraction-watch-data/-/raw/main/retraction_watch.csv"
DEFAULT = Path(__file__).resolve().parents[2] / "data" / "cache" / "retraction_watch.csv"


def _date(value: str) -> Optional[str]:
    try:
        return datetime.strptime(value.split()[0], "%m/%d/%Y").date().isoformat()
    except (ValueError, IndexError):
        return None


class RetractionIndex:
    def __init__(self, by_doi: dict[str, Optional[str]], by_pmid: dict[str, Optional[str]]):
        self.by_doi, self.by_pmid = by_doi, by_pmid

    @classmethod
    def load(cls, path: str | Path = DEFAULT) -> "RetractionIndex":
        by_doi, by_pmid = {}, {}
        csv.field_size_limit(sys.maxsize)
        with open(path, encoding="utf-8", errors="replace", newline="") as f:
            for row in csv.DictReader(f):
                if "Retraction" not in (row.get("RetractionNature") or ""):
                    continue                    # corrections and expressions of concern are not retractions
                when = _date(row.get("RetractionDate") or "")
                doi = (row.get("OriginalPaperDOI") or "").strip().lower()
                pmid = (row.get("OriginalPaperPubMedID") or "").strip()
                if doi and doi not in ("unavailable", "0"):
                    by_doi[doi] = when
                if pmid and pmid != "0":
                    by_pmid[pmid] = when
        return cls(by_doi, by_pmid)

    def retracted(self, ev: Evidence, as_of: Optional[str] = None) -> bool:
        doi = str(ev.extra.get("doi", "")).lower()
        pmid = str(ev.extra.get("pmid", ""))
        for found, when in ((doi in self.by_doi, self.by_doi.get(doi)), (pmid in self.by_pmid, self.by_pmid.get(pmid))):
            if found and (as_of is None or (when is not None and when <= as_of)):
                return True
        return False

    def mark(self, evidence: list[Evidence], as_of: Optional[str] = None) -> list[Evidence]:
        return [e.model_copy(update={"flags": sorted({*e.flags, "retracted"})}) if self.retracted(e, as_of) else e
                for e in evidence]


def download(path: Path = DEFAULT) -> None:
    import httpx
    path.parent.mkdir(parents=True, exist_ok=True)
    with httpx.stream("GET", URL, timeout=300, follow_redirects=True) as r:
        r.raise_for_status()
        with open(path, "wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)
    print(f"saved {path} ({path.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    if sys.argv[1:] == ["download"]:
        download()
    else:
        print(__doc__)

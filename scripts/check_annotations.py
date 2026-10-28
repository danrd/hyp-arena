"""Validate an annotation file against data/validation/extraction/annotation_schema.md: schema, allowed values, verbatim quotes.

    python -m scripts.check_annotations data/validation/extraction/annotated_b.json [--source data/validation/extraction/to_annotate.json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ALLOWED = {"quote_role": {"finding", "background", "speculation"},
           "endpoint": {"lifespan", "healthspan", "biomarker", "disease", "mechanism", "unknown"},
           "effect": {"increase", "decrease", "no_effect", "unknown"},
           "significance": {"significant", "not_significant", "not_stated"},
           "species": {"mouse", "rat", "worm", "fly", "yeast", "human", "other"},
           "sex": {"male", "female", "both", "unspecified"},
           "system": {"in_vivo", "ex_vivo", "in_vitro"}}
FIELDS = set(ALLOWED) | {"quote", "intervention", "strain", "dose", "ambiguous"}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def problems(annotated: dict, source: dict) -> list[str]:
    out = []
    src = source["papers"]
    papers = annotated.get("papers") or []
    if [p.get("pmid") for p in papers] != [p["pmid"] for p in src]:
        out.append("the papers differ from the source (pmids or order)")
        return out
    for p, s in zip(papers, src):
        text = _norm(s["abstract"])
        if not isinstance(p.get("records"), list) or not isinstance(p.get("no_relevant_finding"), bool):
            out.append(f"{p['pmid']}: records (list) and no_relevant_finding (bool) are required")
            continue
        if p["no_relevant_finding"] and p["records"]:
            out.append(f"{p['pmid']}: no_relevant_finding with records")
        for i, r in enumerate(p["records"]):
            miss = FIELDS - set(r)
            if miss:
                out.append(f"{p['pmid']}[{i}]: missing {sorted(miss)}")
                continue
            for k, vals in ALLOWED.items():
                if r[k] not in vals:
                    out.append(f"{p['pmid']}[{i}]: {k}={r[k]!r} not allowed")
            if _norm(r["quote"]) not in text:
                out.append(f"{p['pmid']}[{i}]: the quote is not verbatim in the abstract")
            if r["ambiguous"] is True and not p.get("note"):
                out.append(f"{p['pmid']}[{i}]: ambiguous record needs a note on the paper")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("file")
    ap.add_argument("--source", default="data/validation/extraction/to_annotate.json")
    a = ap.parse_args()
    found = problems(json.loads(Path(a.file).read_text()), json.loads(Path(a.source).read_text()))
    print("\n".join(found) if found else f"ok: {a.file}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())

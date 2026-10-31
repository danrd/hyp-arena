"""Flag candidates for ClinicalTrials.gov trials whose registry text may have been edited after the result
(specs/ctgov-outcomes-2026-10-30.yaml: flags, flag_rules).

    python -m scripts.ctgov_flags            # writes $KG_DIR/hypothesis_sources/ctgov_flags_candidates.yaml

Code only finds candidates; each one is confirmed or rejected by reading (the confirmed flags go into ctgov_flags.yaml).
The registry text belongs to the record but is quoted with result sentences, so output goes to the private repository only.
"""
from __future__ import annotations

import json
import re

import yaml

from scripts.ctgov_outcomes import CAND, INPUTS, KG, LABELS, SUFFIX

OUT = KG / "hypothesis_sources" / f"ctgov_flags_candidates{SUFFIX}.yaml"
PHRASES = [
    r"this (study|trial) (showed|shows|demonstrated|found|revealed)",
    r"\bwe (found|observed|showed|demonstrated)\b",
    r"\b(our|the) (results|findings|data) (showed|show|indicate|indicated|suggest|suggested|demonstrated|revealed)\b",
    r"\b(was|were) significantly (improved|increased|reduced|decreased|higher|lower|better|greater)\b",
    r"\bresulted in (a )?significant",
    r"\bno significant (difference|effect|change)s? (was|were) (found|observed|seen)",
]
OVERLAP_MIN = 0.5
STOP = set("the and for with from into over after before during between baseline change changes measured measure "
           "using use score scores total level levels test week weeks month months year years day days time point "
           "points assessed assessment participants number mean rate".split())


def words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (s or "").lower()) if len(w) >= 3 and w not in STOP}


def overlap(a: set[str], b: set[str]) -> float:
    return len(a & b) / min(len(a), len(b)) if a and b else 0.0


def sentences_with_hits(text: str) -> list[str]:
    out = []
    for s in re.split(r"(?<=[.!?])\s+|\n+", text or ""):
        if any(re.search(p, s, re.I) for p in PHRASES):
            out.append(s.strip())
    return out


def posted_primary(row: dict) -> list[str]:
    r = next((s for s in row["sources"] if s["id"] == "R"), None)
    return re.findall(r"Primary outcome: (.+?) \(", r["text"]) if r else []


def main() -> None:
    cands = {c["source_id"]: c for c in yaml.safe_load(CAND.read_text())["items"]}
    rows = {json.loads(l)["nct"]: json.loads(l) for l in INPUTS.read_text().splitlines()}
    labels = {x["nct"]: x["label"] for x in yaml.safe_load(LABELS.read_text())["items"]}
    out = []
    for nct, row in rows.items():
        c = cands[nct]
        hits = sentences_with_hits(f"{c.get('brief_summary', '')}\n{c.get('detailed_description', '')}")
        reg = [o["measure"] for o in row["primary_outcomes"]]
        post = posted_primary(row)
        mism = None
        if post:
            best = [max((overlap(words(p), words(r)) for r in reg), default=0.0) for p in post]
            if len(post) != len(reg) or min(best) < OVERLAP_MIN:
                mism = {"registered": reg, "posted": post, "best_overlap": [round(b, 2) for b in best]}
        if hits or mism:
            out.append({"nct": nct, "label": labels.get(nct), "result_in_text_sentences": hits, "outcome_mismatch": mism,
                        "confirmed": {"result_in_text": None, "outcome_mismatch": None}})
    OUT.write_text(yaml.safe_dump({"items": out}, allow_unicode=True, sort_keys=False, width=200))
    print(f"{len(rows)} trials; text candidates {sum(bool(x['result_in_text_sentences']) for x in out)}; "
          f"mismatch candidates {sum(bool(x['outcome_mismatch']) for x in out)}; with posted results "
          f"{sum(bool(posted_primary(r)) for r in rows.values())} -> {OUT}")


if __name__ == "__main__":
    main()

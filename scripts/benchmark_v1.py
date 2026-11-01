"""Frozen unit list of the benchmark (specs/benchmark-v2.yaml; v1 kept in data/benchmark/v1_units.json): human registry hypotheses with decisive outcomes.

    python -m scripts.benchmark_v1        # writes data/benchmark/v1_units.json (ids, labels, dates, flags; no texts) and prints its sha256

Reads the label files in $KG_DIR/hypothesis_sources (private: inputs carry publishers' abstracts); writes no text.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from hyparena.outcomes import cutoffs
from scripts.ctgov_outcomes import KG

HS = KG / "hypothesis_sources"
VERSION = "v2"           # v1 (2026-11-01): CT.gov, ISRCTN, DRKS, NTR; v2 (2026-11-01): + ANZCTR
OUT = Path(__file__).resolve().parents[1] / "data" / "benchmark" / f"{VERSION}_units.json"
SOURCES = [("ctgov", "", "ctgov"), ("ctgov_2023", "_2023", "ctgov"), ("isrctn", "", "isrctn"), ("drks", "", "drks"), ("ntr", "", "ntr"), ("anzctr", "", "anzctr")]
DECISIVE = {"positive": 1, "null": 0, "negative": 0}
B2_MODEL = "gpt-4o"


def _yaml(p: Path) -> dict:
    return yaml.safe_load(p.read_text()) if p.exists() else {}


def units() -> list[dict]:
    cut = cutoffs()
    out = []
    for name, suf, stem in SOURCES:
        labels = _yaml(HS / f"{stem}_outcomes{suf}.yaml").get("items", [])
        rows = {json.loads(l)["nct"]: json.loads(l) for l in (HS / f"{stem}_outcome_inputs{suf}.jsonl").read_text().splitlines()}
        cands = {c["source_id"]: c for c in _yaml(HS / f"{stem}_candidates{suf}.yaml").get("items", [])}
        flags = _yaml(HS / f"{stem}_flags{suf}.yaml").get("items", [])
        excl = {f["nct"] for f in flags if f.get("use") == "exclude"}
        sens = {f["nct"] for f in flags if f.get("use") == "sensitivity"}
        for x in labels:
            if x["label"] not in DECISIVE or x["nct"] in excl:
                continue
            c = cands.get(x["nct"], {})
            dates = [s["date"] for s in rows[x["nct"]]["sources"] if s.get("date")] + ([c["results_first_posted"]] if c.get("results_first_posted") else [])
            first = min(dates) if dates else ""
            hc = x.get("human_check") or {}
            out.append({"id": x["nct"], "source": name, "label": DECISIVE[x["label"]], "outcome": x["label"],
                        "written_on": c.get("written_on", ""), "first_outcome_document": first,
                        "human_checked": bool(hc),
                        "recomputed": hc.get("stratum") == "recomputed", "multi_row": bool(hc.get("multi_row")),
                        "edited_after_result": x["nct"] in sens,
                        "b2_clean": bool(first) and first > cut[B2_MODEL]})
    return sorted(out, key=lambda u: (u["source"], u["id"]))


def main() -> None:
    u = units()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"benchmark": VERSION, "b2_model": B2_MODEL, "units": u}, indent=1, ensure_ascii=False) + "\n")
    h = hashlib.sha256(OUT.read_bytes()).hexdigest()
    pos = sum(x["label"] for x in u)
    b2 = [x for x in u if x["b2_clean"]]
    print(f"{OUT}: {len(u)} units, {pos} positive / {len(u) - pos} null+negative; B2 clean: {len(b2)} ({sum(x['label'] for x in b2)} positive); "
          f"human-checked {sum(x['human_checked'] for x in u)}, edited_after_result {sum(x['edited_after_result'] for x in u)}, "
          f"recomputed {sum(x['recomputed'] for x in u)} (multi-row {sum(x['multi_row'] for x in u)}); sha256 {h}")


if __name__ == "__main__":
    main()

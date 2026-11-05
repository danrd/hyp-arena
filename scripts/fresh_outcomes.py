"""Outcome labels for the fresh calibration sample by hand-run Argon (Gemini deep research; user decision 2026-11-05), checked
by code and spot-checked by Claude.

    python -m scripts.fresh_outcomes task     # the task for Argon: trials, their registered primary outcomes, the source texts
    python -m scripts.fresh_outcomes check    # Argon's reply (argon_labels.jsonl) checked: format, labels, sources, verbatim quotes

Pool: CT.gov 2023-2026 "aging itself" candidates (ctgov_candidates_2023.yaml) that are not in the benchmark, were never labelled,
were registered after their primary completion (so the benchmark's prospective rule left them out), and have an outcome
document: posted results, or a result abstract published after the primary completion (scripts/ctgov_outcomes.papers: no
protocols or reviews). Labels follow the rules of the benchmark's labels (hyparena/prompts/label_trial_outcome/v1.j2).
Files live in the private repository: $KG_DIR/hypothesis_sources/calibration/fresh/.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter

import yaml

from scripts.ctgov_outcomes import KG, LABELS_SET, _norm, papers, posted_results, source_id

HS = KG / "hypothesis_sources"
FRESH = HS / "calibration" / "fresh"
INPUTS, TASK, REPLY, SHEET = FRESH / "inputs.jsonl", FRESH / "argon_task.md", FRESH / "argon_labels.jsonl", FRESH / "recheck_sheet.md"

RULES = """For each trial, report what happened to its PRIMARY outcome, from the sources given with the trial only (do not search
for other sources, do not use knowledge outside them).

- label: positive (the primary outcome differed significantly in favour of the intervention against its comparator) | null (no
  significant difference) | negative (significantly worse with the intervention) | mixed (several primary outcomes or arms
  disagree) | not_applicable (no comparison to test: single arm, feasibility, pharmacokinetics, or the primary outcome is a
  description, not an effect) | not_reported (the sources do not give the primary outcome result).
- Significance means the trial's own test (a p-value below its threshold, a confidence interval excluding no effect, or an
  explicit statement); a numerical difference alone is not significance. A within-group change alone (before vs after in the
  treated group) is not a difference against the comparator.
- source: the id of the source you quote (R, P1, P2, ...).
- quote: one or two consecutive sentences, or one line of a results table, copied exactly, character for character, from that
  source, that state the primary outcome result; "" when not_reported.
- note: one short line on anything that made the label uncertain (which outcome is primary, comparator, significance not
  stated), or "".

Reply with JSON Lines only: one line per trial, in the order given, exactly these keys:
{"nct": "NCT...", "label": "...", "source": "P1", "quote": "...", "note": ""}"""


def pool() -> list[dict]:
    bench = {u["id"] for u in json.loads((KG.parent / "hyp-arena" / "data" / "benchmark" / "v2_units.json").read_text())["units"]} \
        if (KG.parent / "hyp-arena").exists() else set()
    cands = yaml.safe_load((HS / "ctgov_candidates_2023.yaml").read_text())["items"]
    labelled = {x["nct"] for x in yaml.safe_load((HS / "ctgov_outcomes_2023.yaml").read_text())["items"]}
    return [c for c in cands if c["source_id"] not in bench and c["source_id"] not in labelled
            and c["primary_completion"] and str(c["written_on"])[:10] > str(c["primary_completion"])[:10]]


def task() -> dict:
    rows = []
    for c in sorted(pool(), key=lambda c: hashlib.sha1(c["source_id"].encode()).hexdigest()):
        sources = []
        if c.get("results_posted"):
            txt = posted_results(c["source_id"])
            if txt:
                sources.append({"id": "R", "kind": "ClinicalTrials.gov posted results", "text": txt})
        for i, p in enumerate(papers(c), 1):
            sources.append({"id": f"P{i}", "kind": f"PubMed abstract, PMID {p['pmid']}, published {p['date']}", "pmid": p["pmid"],
                            "text": p["text"]})
        if sources:
            rows.append({"nct": c["source_id"], "title": c["title"], "interventions": ", ".join(i["name"] for i in c["interventions"]),
                         "primary_outcomes": c["primary_outcomes"], "primary_completion": c["primary_completion"],
                         "sources": sources})
    FRESH.mkdir(parents=True, exist_ok=True)
    INPUTS.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    md = [f"# Outcome labels for {len(rows)} trials (task for Argon, 2026-11-05)\n", RULES, ""]
    for r in rows:
        md.append(f"## {r['nct']}\n\nTitle: {r['title']}\nInterventions: {r['interventions']}\nPrimary completion: {r['primary_completion']}")
        md.append("Primary outcome(s) as registered:")
        md += [f"- {o.get('measure', '')}" + (f" ({o['time_frame']})" if o.get("time_frame") else "") for o in r["primary_outcomes"]]
        for s in r["sources"]:
            md.append(f"\n[{s['id']}] {s['kind']}\n{s['text']}")
        md.append("")
    TASK.write_text("\n".join(md) + "\n")
    return {"trials": len(rows), "with_posted_results": sum(any(s["id"] == "R" for s in r["sources"]) for r in rows),
            "chars": len("\n".join(md))}


def check() -> dict:
    rows = {json.loads(x)["nct"]: json.loads(x) for x in INPUTS.read_text().splitlines() if x.strip()}
    got, problems = {}, []
    for i, line in enumerate(REPLY.read_text().splitlines(), 1):
        line = line.strip().strip(",")
        if not line.startswith("{"):
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            problems.append(f"line {i}: not JSON")
            continue
        n = r.get("nct")
        if n not in rows:
            problems.append(f"line {i}: {n} is not in the task")
            continue
        label = r.get("label") if r.get("label") in LABELS_SET else "unparsed"
        src = next((s for s in rows[n]["sources"] if s["id"] == source_id(r)), None)
        ok = label == "not_reported" or (src is not None and bool(r.get("quote")) and _norm(r["quote"]) in _norm(src["text"]))
        got[n] = {"nct": n, "label": label if ok else "quote_failed", "argon_label": r.get("label"), "source": source_id(r),
                  "quote": r.get("quote", ""), "note": r.get("note", "")}
    missing = sorted(set(rows) - set(got))
    order = sorted(got.values(), key=lambda x: hashlib.sha1(x["nct"].encode()).hexdigest())
    k = -(-len(order) * 3 // 10)
    pick = order[:k] + [x for x in order[k:] if x["label"] in ("mixed", "quote_failed", "unparsed") or x["note"]]
    sheet = [f"# Recheck of Argon's labels: {len(pick)} of {len(order)} (30% in SHA-1 order, plus every mixed, failed or noted "
             "label)", "", "Fill `agree` (yes / no) and `correct label`.", ""]
    for x in pick:
        sheet += [f"## {x['nct']}: {x['label']} (source {x['source']})", f"> {x['quote']}", f"note: {x['note']}",
                  "agree: · correct label: ", ""]
    SHEET.write_text("\n".join(sheet) + "\n")
    (FRESH / "labels.yaml").write_text(yaml.safe_dump({"labelled_by": "Argon (Gemini deep research), checked by code",
                                                       "items": list(got.values())}, allow_unicode=True, sort_keys=False))
    return {"trials": len(rows), "answered": len(got), "missing": missing, "problems": problems,
            "labels": dict(Counter(x["label"] for x in got.values())), "recheck": len(pick)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["task", "check"])
    a = ap.parse_args()
    print(json.dumps(task() if a.cmd == "task" else check(), indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()

"""Outcome labels for the fresh calibration sample by hand-run Argon (Gemini deep research; user decision 2026-11-05), checked
by code and spot-checked by Claude.

    python -m scripts.fresh_outcomes task     # the task for Argon: trials, their registered primary outcomes, the source texts
    python -m scripts.fresh_outcomes check    # Argon's reply (argon_labels.jsonl) checked: format, labels, sources, verbatim quotes
    python -m scripts.fresh_outcomes expand   # the extension (user 2026-11-05): conditions matched as words, not whole strings
    python -m scripts.fresh_outcomes task --set exp_2023 | exp_2000      # its two Argon tasks, by period
    python -m scripts.fresh_outcomes check --set exp_2023 | exp_2000

Extension: the benchmark and the calibration took a trial only when a condition is exactly one of the ageing conditions
(hypothesis_sources_ctgov.CONDITIONS: "aging", "frailty", "sarcopenia", ...). The extension takes a condition that contains one of
those words ("Sarcopenia in Elderly", "Physical Frailty", "Aging Well"), leaves out skin, facial, hair and cosmetic ageing, and
leaves out every trial already in a candidate list, the benchmark, the calibration or the fresh set. Both periods: 2023-2026
(results mostly after the models' training cutoffs: the clean part) and 2000-2022 (results the models may remember: orientation
only), reported apart.

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
EXPANDED = FRESH / "expanded_candidates.yaml"
SETS = {"exp_2023": ("2023-01-01", "2026-10-31"), "exp_2000": ("2000-01-01", "2022-12-31"), "exp_reg": ("2000-01-01", "2026-10-31")}
EXPANDED_REG = FRESH / "expanded_registries.yaml"


def use_set(name: str) -> None:
    """Point the task and check files at an extension set (fresh/<name>/)."""
    global INPUTS, TASK, REPLY, SHEET, LABELS_OUT
    d = FRESH / name
    d.mkdir(parents=True, exist_ok=True)
    INPUTS, TASK, REPLY, SHEET = d / "inputs.jsonl", d / "argon_task.md", d / "argon_labels.jsonl", d / "recheck_sheet.md"
    LABELS_OUT = d / "labels.yaml"


LABELS_OUT = FRESH / "labels.yaml"

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


def expand() -> dict:
    """Candidates of the extension, both periods, written to fresh/expanded_candidates.yaml (no outcome read)."""
    import re
    import scripts.hypothesis_sources_ctgov as h
    word = re.compile(r"\b(aging|ageing|frail\w*|sarcopeni\w*|longevity|senescence|inflammaging)\b", re.I)
    skin = re.compile(r"skin|facial|face|wrinkl|photo|hair|cosmet|anti-?aging", re.I)

    class Words(set):
        def __contains__(self, c):
            return bool(word.search(c)) and not skin.search(c)
    original = h.CONDITIONS
    known = {c["source_id"] for f in ("ctgov_candidates.yaml", "ctgov_candidates_2023.yaml")
             for c in yaml.safe_load((HS / f).read_text())["items"]}
    known |= {u["id"] for u in json.loads((KG.parent / "hyp-arena" / "data" / "benchmark" / "v2_units.json").read_text())["units"]}
    known |= {json.loads(x)["nct"] for x in INPUTS.read_text().splitlines() if x.strip()} if INPUTS.exists() else set()
    sts = h.studies()                                  # the API query uses the original condition list (search expansion)
    h.CONDITIONS = Words()
    out = []
    try:
        for name, (lo, hi) in SETS.items():
            h.FIRST_FROM, h.FIRST_TO = lo, hi
            for st in sts:
                c = h.candidate(st)
                if c is None or c["source_id"] in known or any(x.strip().lower() in original for x in c["conditions"]):
                    continue
                if not c["results_posted"] and not c["result_pmids_listed"]:
                    c["result_pmids_si"] = h.pubmed_si(c["source_id"])
                out.append({**c, "set": name})
    finally:
        h.CONDITIONS = original
    EXPANDED.write_text(yaml.safe_dump({"selection": "extension, see scripts/fresh_outcomes.py (2026-11-05)", "n": len(out),
                                        "items": out}, allow_unicode=True, sort_keys=False))
    return {k: sum(1 for c in out if c["set"] == k) for k in SETS}


def expand_registries() -> dict:
    """ISRCTN, DRKS, NTR and UMIN candidates (found earlier through PubMed secondary ids) that the benchmark's rules left out:
    interventional, a condition containing an ageing word, any registration timing, not in the benchmark or the calibration.
    Mapped to the CT.gov candidate fields; a registry without a completion date takes the later of registration and start as
    the date after which a paper counts (protocols and reviews are left out by title, as for CT.gov)."""
    import re
    word = re.compile(r"\b(aging|ageing|frail\w*|sarcopeni\w*|longevity|senescence|inflammaging)\b", re.I)
    used = {u["id"] for u in json.loads((KG.parent / "hyp-arena" / "data" / "benchmark" / "v2_units.json").read_text())["units"]}
    used |= {u["id"] for st in (1, 2, 3) for u in json.loads((HS / "calibration" / f"units_{st}.json").read_text())}
    strip = lambda t: re.sub(r"<[^>]+>", " ", str(t or "")).strip()
    out = []
    for reg in ("isrctn", "drks", "ntr", "umin"):
        for x in yaml.safe_load((HS / f"{reg}_candidates.yaml").read_text())["items"]:
            sid = x["source_id"]
            conds = " | ".join(x["conditions"]) if isinstance(x.get("conditions"), list) else str(x.get("conditions") or "")
            if sid in used or not word.search(conds):
                continue
            if reg != "isrctn" and "interventional" not in str(x.get("study_type", "")).lower():
                continue
            if reg == "isrctn":
                inter = ", ".join(i.get("name", "") for i in x.get("interventions") or [])
                prim = [{"measure": strip(o.get("measure")), "time_frame": ""} for o in x.get("primary_outcomes") or []]
                after, title, pmids = x.get("overall_end") or x["written_on"], x["title"], x.get("result_pmids") or []
            else:
                inter = str(x.get("arms") or x.get("intervention") or x.get("interventions") or "")
                prim = [{"measure": strip(x.get("primary_outcome")), "time_frame": ""}]
                after = max(d for d in (str(x.get("written_on") or ""), str(x.get("enrolment_start") or ""),
                                        str(x.get("trial_start") or "")) if d) if any((x.get("written_on"), x.get("enrolment_start"), x.get("trial_start"))) else ""
                title = x["title"] if x["title"] != sid else str(x.get("summary") or "")[:200]
                title = next((t.strip() for t in title.split("|") if t.strip() and not t.strip().startswith("Date of")), sid)
                pmids = x.get("pmids") or []
            out.append({"source_id": sid, "registry": reg, "set": "exp_reg", "title": title, "conditions": [conds],
                        "interventions": [{"type": "", "name": inter[:400]}], "primary_outcomes": prim,
                        "primary_completion": after[:10], "written_on": x.get("written_on"), "results_posted": False,
                        "result_pmids_listed": pmids, "result_pmids_si": [], "source_url": x.get("source_url")})
    EXPANDED_REG.write_text(yaml.safe_dump({"selection": "registries extension, scripts/fresh_outcomes.py (2026-11-05)",
                                            "n": len(out), "items": out}, allow_unicode=True, sort_keys=False))
    from collections import Counter
    return dict(Counter(c["registry"] for c in out))


def task(name: str = "") -> dict:
    rows = []
    src = EXPANDED_REG if name == "exp_reg" else EXPANDED
    cands = pool() if not name else [c for c in yaml.safe_load(src.read_text())["items"] if c["set"] == name]
    for c in sorted(cands, key=lambda c: hashlib.sha1(c["source_id"].encode()).hexdigest()):
        sources = []
        if not c.get("primary_completion"):
            continue
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
    LABELS_OUT.write_text(yaml.safe_dump({"labelled_by": "Argon (Gemini deep research), checked by code",
                                                       "items": list(got.values())}, allow_unicode=True, sort_keys=False))
    return {"trials": len(rows), "answered": len(got), "missing": missing, "problems": problems,
            "labels": dict(Counter(x["label"] for x in got.values())), "recheck": len(pick)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["task", "check", "expand", "expand-registries"])
    ap.add_argument("--set", default="", choices=["", *SETS])
    a = ap.parse_args()
    if a.set:
        use_set(a.set)
    out = expand() if a.cmd == "expand" else expand_registries() if a.cmd == "expand-registries" else \
        task(a.set) if a.cmd == "task" else check()
    print(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()

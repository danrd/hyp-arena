"""Level 4 of the checks (specs/evolution/generation-comparison-2026-11-14.yaml): the tasks for the outside model that
writes every arm in a chat (Argon or ChatGPT), the checks of its answers by code, and the collection of the arms for
scripts/evolution/generation_compare.py. Free (PubMed E-utilities only).

    python -m scripts.argon.generation_tasks build-a                    # A: the plain request
    python -m scripts.argon.generation_tasks build-b                    # B: structured generation and the method by the manual
    python -m scripts.argon.generation_tasks build-reports              # the method by the manual on the hypotheses of A
    python -m scripts.argon.generation_tasks build-evolve --arm C       # free evolution of B (C) or of A (D)
    python -m scripts.argon.generation_tasks check --kind a|b|reports|c|d
    python -m scripts.argon.generation_tasks collect                    # -> hypotheses.json for the comparison

Files in longevity-kg reviews/generation-<date>/ (DIR, private): `task_<kind>.json` (sent), `answer_<kind>.json` (put
there), `check_<kind>.json`.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import unicodedata
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KG = Path(os.environ.get("KG_DIR", ROOT.parent / "longevity-kg"))
DIR = Path(os.environ.get("GEN_DIR", KG / "reviews" / "generation-2026-11-14"))
MANUAL = ROOT / "docs" / "method-v3-manual.md"
TOPIC = ("bioelectric signalling in ageing: membrane potential, ion channels, gap junctions and endogenous electric fields "
         "as a lever on ageing and on age-related loss of function")
N = 5
PROFILES = ("evidence", "funding", "frontier")

HYP = {"id": "", "claim": "", "rationale": "", "experiment": "", "relies_on": [{"pmid": "", "title": ""}]}
CARD = {"population": "", "intervention": {"label": "", "type": ""}, "outcome": "",
        "links": [{"id": "c1", "subject": "", "relation": "", "object": "", "role": "outcome | step | premise"}],
        "decisive_experiment": {"system": "", "design": "", "control": "", "endpoint": "", "duration": ""}}
REPORT = {"records": [{"link": "c1", "pmid": "", "title": "", "year": "", "quote": "", "stance": "supports | refutes",
                       "design": "", "n_total": "", "effect": ""}],
          "links": [{"id": "c1", "S": "", "status": ""}],
          "novelty": {"level": "", "nearest_prior": [{"pmid": "", "title": ""}], "why": ""},
          "alternatives": [{"id": "alt1", "text": "", "support_pmids": [""], "on_positive": "eliminated | weakened | unchanged",
                            "on_negative": "eliminated | weakened | unchanged"}],
          "scores": {"balance": "", "I": "", "N": "", "W": "", "feasibility": "", "endpoint": "", "best_design": ""},
          "profiles": {p: {"expected_score": ""} for p in PROFILES},
          "improvements": [{"item": "", "what": "", "expected": ""}]}

A_BASE = (f"Write {N} research hypotheses on the topic below: original, testable, important for ageing and healthy "
          "lifespan. Each has a claim, a rationale (why it should be true) and an experiment that would test it, and "
          "lists the papers it relies on.")

CARD_SPEC = [   # the only difference of B from A: our card specification, nothing about scoring or what the method values
    "In addition, before you write each hypothesis's text, lay it out as a structured card (this is the only extra "
    "requirement):",
    "- intervention: a label and a type (drug, supplement, exercise, device, gene or cell perturbation, ...); population: "
    "species, age and condition.",
    "- the mechanism as an ordered chain of links from the intervention to the outcome: each link is a triple subject - "
    "relation - object, with a short relation verb (activates, inhibits, hyperpolarizes, suppresses, promotes, restores, "
    "improves, reduces, ...) and a role ('step' for a link before the outcome, 'outcome' for the one the hypothesis "
    "promises to change); at least one step before the outcome, at most four.",
    "- outcome: what the hypothesis promises to change, named by its measure.",
    "- decisive experiment: system (human, mouse, rat, cells, ...), design, control or comparator, primary endpoint, duration.",
    "Write the claim, rationale and experiment from the card. The five hypotheses must be different ideas: no two share "
    "both the intervention and the outcome.",
]

COMMON = [
    "Work only from what was published up to the date T given below; a paper after T does not exist.",
    "Every paper you name must be a real PubMed paper: give its PMID and its exact title. A paper you are not sure of is left out.",
    "A quote is copied verbatim from the title or abstract of the paper named (one passage, not sentences joined from different places).",
    "Reply with one JSON object in the format at the end, nothing around it. Labels and the text of the hypotheses in English.",
]


def manual() -> str:
    return MANUAL.read_text(encoding="utf-8")


def _write(kind: str, task: dict) -> Path:
    DIR.mkdir(parents=True, exist_ok=True)
    p = DIR / f"task_{kind}.json"
    p.write_text(json.dumps(task, indent=1, ensure_ascii=False) + "\n")
    return p


def build_a(as_of: str) -> dict:
    task = {"task": "generation_A", "topic": TOPIC, "T": as_of, "n": N,
            "instructions": [A_BASE] + COMMON,
            "answer_format": {"hypotheses": [{**HYP, "id": "A1"}]}}
    _write("a", task)
    return task


def build_b_generate(as_of: str) -> dict:
    """B = A + our card specification (pilot of 2026-11-16): the same request as A, plus the structured card. No manual and
    no hint of what the method values, so B differs from A only by the structure. The steps of the method (scoring) and the
    evolution are separate tasks, for A and B alike."""
    task = {"task": "generation_B", "topic": TOPIC, "T": as_of, "n": N,
            "instructions": [A_BASE] + CARD_SPEC + COMMON,
            "answer_format": {"hypotheses": [{**HYP, "id": "B1", "card": CARD}]}}
    _write("b", task)
    return task


def build_b(as_of: str) -> dict:
    task = {"task": "generation_B", "topic": TOPIC, "T": as_of, "n": N, "manual": manual(),
            "instructions": [
                f"Work by the manual below (method v3). Write {N} hypotheses on the topic in the structured generation mode "
                "(manual section 11a, 'structured'): fill the card template of section 3 for each (intervention, population, "
                "the mechanism as links before the outcome, the outcome, the decisive experiment with system, design, control, "
                "endpoint and duration), then write the text from it (claim, rationale, experiment). The five must be different "
                "ideas, not variants of one (no two share the intervention and the outcome).",
                "Then take each hypothesis through every step of the method as the manual describes them: search PubMed before T "
                "for each link and alternative, read the abstracts and record findings (section 4), weigh them (section 5), the "
                "strength of each link and the gate (section 6), the axes (section 7), the profiles (section 8), the improvement "
                "list (section 11). Use the manual's levels and names; a value you cannot find by the manual's rule is written "
                "'not computed', never guessed.",
                "Do not change a hypothesis after you have scored it."] + COMMON,
            "answer_format": {"hypotheses": [{**HYP, "id": "B1", "card": CARD, "report": REPORT}]}}
    _write("b", task)
    return task


def build_reports(as_of: str) -> dict:
    ans = json.loads((DIR / "answer_a.json").read_text())
    texts = [{k: h.get(k, "") for k in ("id", "claim", "rationale", "experiment", "relies_on")} for h in ans["hypotheses"]]
    task = {"task": "reports_A", "topic": TOPIC, "T": as_of, "manual": manual(), "hypotheses": texts,
            "instructions": [
                "Work by the manual below (method v3). The hypotheses below were written by someone else; do not change them. "
                "For each, build the card (section 3) from its text only, then take it through every step of the method as the "
                "manual describes them (search before T, records, weights, links and gate, axes, profiles, improvement list). "
                "Use the manual's levels and names; a value you cannot find by the manual's rule is 'not computed'."] + COMMON,
            "answer_format": {"reports": [{"id": "A1", "card": CARD, "report": REPORT}]}}
    _write("reports", task)
    return task


def build_evolve(arm: str, as_of: str) -> dict:
    if arm == "C":
        parents = json.loads((DIR / "answer_b.json").read_text())["hypotheses"]
    else:
        hyps = {h["id"]: h for h in json.loads((DIR / "answer_a.json").read_text())["hypotheses"]}
        reps = {r["id"]: r for r in json.loads((DIR / "answer_reports.json").read_text())["reports"]}
        parents = [{**hyps[i], **reps.get(i, {})} for i in hyps]
    task = {"task": f"evolution_{arm}", "topic": TOPIC, "T": as_of, "manual": manual(), "parents": parents,
            "instructions": [
                "Work by the manual below (method v3). Improve each parent hypothesis by free evolution (manual section 11, "
                "'free'): anything may change - claim, mechanism, population, outcome, experiment - to get a better hypothesis; "
                "use its report and improvement list. One version per parent; name what changed and why. A move towards what "
                "is already known is allowed but must be said.",
                "Then take each version through every step of the method again (card, search before T, records, weights, links "
                "and gate, axes, profiles, improvement list). A record of the parent is never copied: the version's records "
                "come from its own reading."] + COMMON,
            "answer_format": {"hypotheses": [{**HYP, "id": f"{arm}1", "parent": "B1" if arm == "C" else "A1",
                                              "changes": [{"what_changed": "", "why": ""}], "card": CARD, "report": REPORT}]}}
    _write(arm.lower(), task)
    return task


# checks

def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKC", s or "").lower())


def _content(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]{4,}", (s or "").lower())}


def title_matches(given: str, real: str) -> bool:
    a, b = _content(given), _content(real)
    return bool(a) and len(a & b) / len(a) >= 0.5


def quote_found(quote: str, title: str, abstract: str) -> str:
    """'whole' when the quote is verbatim in the title or abstract, 'joined' when each of its sentences is but not the
    whole, 'no' otherwise (as the check of earlier reports by the manual)."""
    hay = _norm(title + " " + abstract)
    if _norm(quote) and _norm(quote) in hay:
        return "whole"
    sents = [s for s in re.split(r"(?<=[.;!?])\s+(?=[A-Z(])", quote or "") if len(s) > 15]
    return "joined" if sents and all(_norm(s) in hay for s in sents) else "no"


def _pmids(h: dict) -> list[tuple[str, str, str]]:
    """(pmid, title given, where) of every paper a hypothesis or its report names."""
    rep = h.get("report") or {}
    out = [(p.get("pmid", ""), p.get("title", ""), "relies_on") for p in h.get("relies_on") or []]
    out += [(r.get("pmid", ""), r.get("title", ""), "record") for r in rep.get("records") or []]
    out += [(p.get("pmid", ""), p.get("title", ""), "nearest_prior") for p in (rep.get("novelty") or {}).get("nearest_prior") or []]
    out += [(p, "", "alternative") for a in rep.get("alternatives") or [] for p in a.get("support_pmids") or []]
    return [(str(p).strip(), t, w) for p, t, w in out if str(p).strip().isdigit()]


def card_problems(c: dict) -> list[str]:
    out = []
    if not (c.get("intervention") or {}).get("label"):
        out.append("no intervention")
    if not c.get("outcome"):
        out.append("no outcome")
    links = c.get("links") or []
    if not any(l.get("role") == "step" for l in links):
        out.append("the mechanism is not written as links (no step before the outcome)")
    e = c.get("decisive_experiment") or {}
    out += [f"the experiment has no {k}" for k in ("system", "design", "endpoint") if not e.get(k)]
    return out


def _b_generate_only() -> bool:
    f = DIR / "task_b.json"
    return f.exists() and "report" not in json.loads(f.read_text())["answer_format"]["hypotheses"][0]


def format_problems(kind: str, ans: dict) -> list[str]:
    key = "reports" if kind == "reports" else "hypotheses"
    items = ans.get(key)
    if not isinstance(items, list) or not items:
        return [f'"{key}" must be a non-empty list']
    out = []
    if kind in ("a", "b") and len(items) != N:
        out.append(f"{len(items)} hypotheses, {N} asked")
    for h in items:
        if kind != "reports" and not all(h.get(k) for k in ("claim", "rationale", "experiment")):
            out.append(f"{h.get('id')}: claim, rationale and experiment must be filled")
        if kind != "a" and not (kind == "b" and _b_generate_only()) and not isinstance(h.get("report"), dict):
            out.append(f"{h.get('id')}: no report")
        if kind in ("c", "d") and not h.get("parent"):
            out.append(f"{h.get('id')}: no parent")
    return out


def check(kind: str, as_of: str | None = None) -> dict:
    from hyparena.tools import pubmed
    from scripts.search.bench_search import summaries
    ans = json.loads((DIR / f"answer_{kind}.json").read_text())
    task = json.loads((DIR / f"task_{kind}.json").read_text())
    T = as_of or task["T"]
    items = ans.get("reports" if kind == "reports" else "hypotheses") or []
    cache_f = DIR / "pubmed_cache.json"
    cache = json.loads(cache_f.read_text()) if cache_f.exists() else {}
    named = sorted({p for h in items for p, _, _ in _pmids(h)})
    summaries(named, cache)
    cache_f.write_text(json.dumps(cache, indent=1, ensure_ascii=False) + "\n")
    abstracts = pubmed.fetch([p for p in named if cache.get(p, {}).get("exists")])
    per = {}
    for h in items:
        refs = []
        for p, t, where in _pmids(h):
            s = cache.get(p, {})
            refs.append({"pmid": p, "where": where, "exists": s.get("exists", False),
                         "before_T": bool(s.get("earliest") and s["earliest"] <= T),
                         "title_matches": title_matches(t, s.get("title", "")) if t and s.get("exists") else None})
        quotes = []
        for r in (h.get("report") or {}).get("records") or []:
            a = abstracts.get(str(r.get("pmid", "")).strip()) or {}
            quotes.append(quote_found(r.get("quote", ""), a.get("title", ""), a.get("abstract", "")) if a else "paper not found")
        good = [r for r in refs if r["exists"] and r["before_T"] and r["title_matches"] is not False]
        per[h.get("id")] = {"papers": len(refs), "good": len(good), "missing": sum(not r["exists"] for r in refs),
                            "after_T": sum(r["exists"] and not r["before_T"] for r in refs),
                            "title_wrong": sum(r["title_matches"] is False for r in refs),
                            "quotes": {q: quotes.count(q) for q in set(quotes)},
                            "card_problems": card_problems(h.get("card") or {}) if kind != "a" else [], "refs": refs}
    total = sum(v["papers"] for v in per.values())
    res = {"kind": kind, "T": T, "format_problems": format_problems(kind, ans), "hypotheses": per,
           "papers": total, "share_good": round(sum(v["good"] for v in per.values()) / total, 3) if total else None,
           "quotes": {q: sum(v["quotes"].get(q, 0) for v in per.values()) for q in ("whole", "joined", "no", "paper not found")}}
    (DIR / f"check_{kind}.json").write_text(json.dumps(res, indent=1, ensure_ascii=False) + "\n")
    return {k: v for k, v in res.items() if k != "hypotheses"}


def _text(h: dict) -> str:
    return f"{h['claim']}\n{h['rationale']}\n{h['experiment']}"


def _terms(card: dict) -> list[str]:
    e = card.get("decisive_experiment") or {}
    return [t for t in ((card.get("intervention") or {}).get("label"), card.get("outcome"), e.get("system"), e.get("endpoint")) if t]


def collect(writer_family: str) -> dict:
    a = json.loads((DIR / "answer_a.json").read_text())["hypotheses"]
    reps = {r["id"]: r for r in json.loads((DIR / "answer_reports.json").read_text())["reports"]} \
        if (DIR / "answer_reports.json").exists() else {}
    arms = {"A": [{"id": h["id"], "parent": None, "text": _text(h), "terms": _terms((reps.get(h["id"]) or {}).get("card") or {})} for h in a]}
    for arm, f in (("B", "answer_b.json"), ("C", "answer_c.json"), ("D", "answer_d.json")):
        if (DIR / f).exists():
            arms[arm] = [{"id": h["id"], "parent": h.get("parent"), "text": _text(h), "terms": _terms(h.get("card") or {})}
                         for h in json.loads((DIR / f).read_text())["hypotheses"]]
    data = {"topic": TOPIC, "as_of": json.loads((DIR / "task_a.json").read_text())["T"], "writer_family": writer_family, "arms": arms}
    (DIR / "hypotheses.json").write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    return {arm: len(v) for arm, v in arms.items()}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["build-a", "build-b", "build-b-generate", "build-reports", "build-evolve", "check", "collect"])
    ap.add_argument("--arm", choices=["C", "D"])
    ap.add_argument("--kind", choices=["a", "b", "reports", "c", "d"])
    ap.add_argument("--as-of", default=date.today().isoformat())
    ap.add_argument("--writer-family", default="google", help="google if Argon wrote the answers, openai if ChatGPT")
    a = ap.parse_args(argv)
    if a.cmd == "build-a":
        t = build_a(a.as_of)
    elif a.cmd == "build-b":
        t = build_b(a.as_of)
    elif a.cmd == "build-b-generate":
        t = build_b_generate(a.as_of)
    elif a.cmd == "build-reports":
        t = build_reports(a.as_of)
    elif a.cmd == "build-evolve":
        t = build_evolve(a.arm, a.as_of)
    elif a.cmd == "check":
        print(json.dumps(check(a.kind), indent=1, ensure_ascii=False)); return
    else:
        print(json.dumps(collect(a.writer_family), indent=1)); return
    print(json.dumps({"task": t["task"], "T": t["T"], "characters": len(json.dumps(t, ensure_ascii=False))}, indent=1))


if __name__ == "__main__":
    main()

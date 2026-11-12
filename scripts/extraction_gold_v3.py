# Data note (2026-11-12): the raw calibration runs of methods v2 and v3 before normaliser v10 (run_{s}_v3.json, run_{s}_msearch.json,
# run_1.json) were removed from longevity-kg; the numbers are in the spec named below. Restore them from the git history to re-run.
"""Method v3 extraction against hand-made gold, with the v2 verifier (verify_claim/v5) on the same inputs for comparison.

Two criteria, each fixed before its first call:
- `--gold manual`: specs/extraction-gold-v3-2026-11-04.yaml, verify_claim/v6 on 20 pairs (not passed; the gold mixed relevance
  with extraction);
- `--gold v3`: specs/extraction-gold-v3b-2026-11-04.yaml, verify_claim/v7 on all 45 pairs: relevance on all of them,
  extraction on the 26 the gold marks relevant (not passed on relevance);
- `--gold v8`: specs/extraction-gold-v8-2026-11-04.yaml, verify_claim/v8 on 29 fresh pairs from calibration steps 2-3
  (`pairs` builds them): the same measures.

    python -m scripts.extraction_gold_v3 run --fake                  # free dry run with the fake model (checks the plumbing)
    ALLOW_PAID=1 python -m scripts.extraction_gold_v3 run            # the pairs x the versions of the criterion, DeepSeek V4.1 Flash
    python -m scripts.extraction_gold_v3 score                       # measures from the saved replies, free

Input. The pairs of $KG_DIR/hypothesis_sources/calibration/extraction_gold (labels_manual.jsonl or labels_v3.jsonl); each pair is a claim of a frozen
calibration card (calibration/cards.json) and one paper. The verifier sees that one abstract (fetched from PubMed as in a run, no
search, no date cut, no subgroup check), once with v5 and once with v6. The raw replies are saved next to the gold in the private
repository (they quote the abstracts); this repository gets only the code and the numbers.

Which record is compared. The first record for the gold PMID whose quote is verbatim in the abstract (gold v3: preferring stance
supports or refutes), then quote_role "finding"; the code checks of a run apply (v3_fields: a number phrase not verbatim in the
abstract is dropped with its number; a review keeps design review; the effect class comes from the effect phrase). A pair with
no such record counts as wrong on every field. Relevance (gold v3): the verifier counts a paper as relevant when it returns a
record with stance supports or refutes for it, which is what a run keeps.
"""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path

from scripts.ctgov_outcomes import KG

GOLD_DIR = KG / "hypothesis_sources" / "calibration" / "extraction_gold"
CARDS = KG / "hypothesis_sources" / "calibration" / "cards.json"
CONFIG = "configs/v3-flash.yaml"
FAMILY = "deepseek"
GOLDS = {"manual": {"file": "labels_manual.jsonl", "versions": ("v5", "v6"), "suffix": ""},
         "v3": {"file": "labels_v3.jsonl", "versions": ("v5", "v7"), "suffix": "_g3"},
         "v8": {"file": "labels_v8.jsonl", "versions": ("v5", "v8"), "suffix": "_g8", "task": "task_v8.jsonl"},
         "v9": {"file": "labels_v9.jsonl", "versions": ("v9",), "suffix": "_g9", "task": "task_v9.jsonl",
                "cards": "retrieval/human_cards.json"}}
FIELDS = ("design", "comparison", "n_total", "effect_class")
THRESHOLDS = {"design": 0.8, "comparison": 0.8, "n_total": 0.8, "effect_class": 0.6}   # both specs; never changed after a result
RELEVANCE_THRESHOLD = 0.8
RELEVANCE_CHECK = {"v9"}            # versions run with the second question (verifier.relevance_check)                                                                # gold v3
V5_DESIGN = {"rct": "rct", "open_label_pilot": "non_randomised", "observational": "observational", "review": "review"}


def load_gold(gold: str = "v3") -> list[dict]:
    return [json.loads(x) for x in (GOLD_DIR / GOLDS[gold]["file"]).read_text().splitlines() if x.strip()]


def _run_file(gold: str, v: str, fake: bool) -> Path:
    return GOLD_DIR / f"run_{v}{GOLDS[gold]['suffix']}{'_fake' if fake else ''}.json"


class Capture:
    """Passes calls through and keeps the reply texts, so that records the run would drop (stance "neither") are still seen."""

    def __init__(self, client):
        self.client, self.texts = client, []

    def call(self, **kw):
        r = self.client.call(**kw)
        self.texts.append(r.text)
        return r


def pairs(steps=(2, 3), per_unit: int = 2, out_name: str = "task_v8.jsonl",
          seen_files=("task.jsonl",)) -> list[dict]:
    """Fresh claim-paper pairs for the v8 test (gold v8), from calibration steps 2 and 3 (never looked at for extraction):
    per unit, in SHA-1 order of the claim, one paper the v2 verifier recorded something for under that claim (evidence,
    counterevidence or a refusal) and one paper of the card's search that it recorded nothing for. Papers of the first 45 pairs
    and claims not in the frozen card are left out. Writes task_v8.jsonl (claim and abstract) next to the gold."""
    import hashlib
    from hyparena.tools import pubmed
    cal = GOLD_DIR.parent
    cards = json.loads(CARDS.read_text())
    seen = {json.loads(x)["pmid"] for f in seen_files for x in (GOLD_DIR / f).read_text().splitlines() if x.strip()}
    used = set()                                        # one paper once across the new pairs
    sha = lambda x: hashlib.sha1(x.encode()).hexdigest()
    out = []
    for st in steps:
        for unit, res in sorted(json.loads((cal / f"run_{st}_msearch.json").read_text()).items()):
            if unit not in cards:
                continue
            v = res["items"][0].get("verification") or {}
            searched = [p for p in v.get("searched_pmids") or [] if p not in seen]
            claims = {c["id"]: c for c in cards[unit]["claims"]}
            got = []
            for cv in sorted(v.get("claims", []), key=lambda c: sha(unit + c["id"])):
                if cv["id"] not in claims:
                    continue
                rec = {r["record_id"].replace("PMID:", "") for k in ("evidence", "counterevidence") for r in cv.get(k, [])}
                rec |= {r.get("record_id", "").replace("PMID:", "") for r in cv.get("refusals", [])}
                rec = sorted((p for p in rec if p in searched and p not in used), key=lambda p: sha(unit + p))
                other = sorted((p for p in searched if p not in rec and p not in used), key=lambda p: sha(unit + cv["id"] + p))
                half = per_unit // 2
                if rec and sum(g["kind"] == "recorded" for g in got) < half:
                    got.append({"claim": cv["id"], "pmid": rec[0], "kind": "recorded"}); used.add(rec[0])
                if other and sum(g["kind"] == "not_recorded" for g in got) < half:
                    got.append({"claim": cv["id"], "pmid": other[0], "kind": "not_recorded"}); used.add(other[0])
                if len(got) >= per_unit:
                    break
            for g in got:
                c = claims[g["claim"]]
                out.append({"pair_id": f"{unit}|{g['claim']}|{g['pmid']}", "step": st, "v2_recorded": g["kind"] == "recorded",
                            "claim": f"{c['subject']['label']} — {c['relation']} — {c['object']['label']}",
                            "claim_context": cards[unit].get("claim_plain", ""), "pmid": g["pmid"]})
    abstracts = pubmed.fetch([o["pmid"] for o in out])
    out = [{**o, "title": abstracts[o["pmid"]]["title"], "abstract": abstracts[o["pmid"]]["abstract"]}
           for o in out if abstracts.get(o["pmid"], {}).get("abstract")]
    (GOLD_DIR / out_name).write_text("".join(json.dumps(o, ensure_ascii=False) + "\n" for o in out))
    return out


def pairs_retrieval(per_claim=(("direct", 3), ("related", 3), ("no", 1), (None, 1)), limit: int = 7) -> list[dict]:
    """Fresh pairs for gold v9 from the retrieval calibration (8 human trial claims, their main claim as in
    scripts/retrieval_eval.claims, papers the retrieval strategies found), stratified by Jules' blind relevance label (direct,
    related, no) so that relevant papers of the same kind are well represented; SHA-1 order within a stratum; papers of earlier
    pairs left out. The labels only stratify: the gold is labelled by hand. Writes task_v9.jsonl."""
    import hashlib
    from hyparena.card.models import HypothesisCard
    ret = GOLD_DIR.parent / "retrieval"
    cards = json.loads((ret / "human_cards.json").read_text())
    lab = {(x["claim_id"], x["pmid"]): x["label"] for f in ("labels_part1.jsonl", "labels_part2.jsonl")
           for x in map(json.loads, filter(str.strip, (ret / "relevance" / f).read_text().splitlines()))}
    seen = {json.loads(x)["pmid"] for f in ("task.jsonl", "task_v8.jsonl") for x in (GOLD_DIR / f).read_text().splitlines() if x.strip()}
    sha = lambda x: hashlib.sha1(x.encode()).hexdigest()
    out = []
    for t in map(json.loads, (ret / "relevance" / "task.jsonl").read_text().splitlines()):
        unit = t["claim_id"].split("|")[0]
        if t["group"].startswith("animal") or unit not in cards:
            continue
        card = HypothesisCard.model_validate(cards[unit])
        c = card.outcome_claim or card.claims[0]
        papers = sorted((p for p in t["papers"] if p["pmid"] not in seen and p.get("abstract")), key=lambda p: sha(unit + p["pmid"]))
        got = []
        for label, k in per_claim:
            got += [p for p in papers if lab.get((t["claim_id"], p["pmid"])) == label and p not in got][:k]
        for p in got[:limit]:
            out.append({"pair_id": f"{unit}|{c.id}|{p['pmid']}", "jules": lab.get((t["claim_id"], p["pmid"])),
                        "claim": f"{c.subject.label} — {c.relation} — {c.object.label}", "claim_context": card.claim_plain,
                        "pmid": p["pmid"], "title": p["title"], "abstract": p["abstract"]})
    (GOLD_DIR / "task_v9.jsonl").write_text("".join(json.dumps(o, ensure_ascii=False) + "\n" for o in out))
    return out


def run(fake: bool = False, gold_name: str = "v3", only: tuple = ()) -> None:
    from hyparena.card import verifier
    from hyparena.card.models import HypothesisCard
    from hyparena.card.pipeline import _client
    from hyparena.tools import pubmed
    pubmed.search = lambda *a, **k: []                    # no retrieval: only the gold paper is read
    gold = load_gold(gold_name)
    versions = only or GOLDS[gold_name]["versions"]
    cards = json.loads((GOLD_DIR.parent / GOLDS[gold_name]["cards"]).read_text() if "cards" in GOLDS[gold_name] else CARDS.read_text())
    client, _ = _client(CONFIG, fake, 2 * len(gold) * len(versions))
    for v in versions:
        out_p = _run_file(gold_name, v, fake)
        done = json.loads(out_p.read_text()) if out_p.exists() else {}
        if gold_name == "v3" and v == "v5" and not fake:     # v5 replies of the 20 manual pairs were made on the same input
            done = {**{k: x for k, x in json.loads(_run_file("manual", "v5", False).read_text()).items()
                       if any(g["pair_id"] == k for g in gold)}, **done}
        for g in gold:
            if g["pair_id"] in done:
                continue
            unit, cid, pmid = g["pair_id"].split("|")
            card = HypothesisCard.model_validate(cards[unit])
            claim = next(c for c in card.claims if c.id == cid)
            cap = Capture(client)
            verifier.verify_claim(cap, FAMILY, frozenset(), claim, card, as_of=None, expert_pmids=[(pmid, "gold")],
                                  check_subgroups=False, search="keywords", template_version=v,
                                  relevance_check=v in RELEVANCE_CHECK)
            done[g["pair_id"]] = {"replies": cap.texts}
            out_p.write_text(json.dumps(done, ensure_ascii=False, indent=1))
            print(json.dumps({"version": v, "pair": g["pair_id"], "calls": len(cap.texts)}), flush=True)


def record_for(replies: list[str], pmid: str, source: str, review: bool = False, by_stance: bool = False) -> dict | None:
    """The compared record of a pair, with the code checks of a run applied (fields as EvidenceRecord names them).
    `relevant`: the verifier returned a record with stance supports or refutes."""
    from hyparena.card.models import EvidenceRecord
    from hyparena.card.verifier import _norm, parse_records, v3_fields
    from hyparena.card.llm import parse_fullest
    from hyparena.card.verifier import merge_relevance
    recs, checks = [], []
    for t in reversed(replies):                           # the last parsed reply is the one a run keeps
        value = parse_records(t or "")
        if value and value.get("records"):
            recs = [r for r in value["records"] if isinstance(r, dict)]
            break
    for t in replies:                                     # answers of the second question (relevance_check), if any
        v = parse_fullest(t or "") if '"relevance"' in (t or "") else None
        if v and isinstance(v.get("relevance"), dict):
            checks = [c for c in checks if c.get("pmid") != v["relevance"].get("pmid")] + [v["relevance"]]
    if checks:
        recs = merge_relevance(recs, checks, {pmid: {"title": "", "abstract": source}})
    recs = [r for r in recs if str(r.get("pmid", "")).replace("PMID:", "").strip() == pmid
            and r.get("quote") and _norm(r["quote"]) in _norm(source)]
    if not recs:
        return None
    kept = [r for r in recs if r.get("stance") in ("supports", "refutes")]
    pool = kept if by_stance and kept else recs
    r = next((r for r in pool if r.get("quote_role") == "finding"), pool[0])
    rec = EvidenceRecord(source="PubMed", record_id=f"PMID:{pmid}")
    v3_fields(rec, r, source, review)
    return {"relevant": bool(kept), "design": rec.design, "comparison": rec.comparison, "n_total": rec.n_total, "effect_class": rec.effect_class,
            "effect_reported": rec.effect_reported, "study_type": r.get("study_type") or "other",
            "effect_percent": r.get("effect_percent") if isinstance(r.get("effect_percent"), (int, float)) else None}


def overlaps(a: str, b: str) -> bool:
    from hyparena.card.verifier import _norm
    a, b = _norm(a), _norm(b)
    return bool(a and b and (a in b or b in a))


def measure(gold: list[dict], pred: dict[str, dict | None], v5: bool = False) -> dict:
    """Shares over all gold pairs (no record = wrong). For v5 only the design (mapped from study_type, animal for a
    non-review primary experiment) and whether an effect number was given can be compared: v5 has no other v3 field."""
    n = len(gold)
    hit = Counter()
    eff = {"gold_with_number": 0, "found": 0}
    for g in gold:
        p = pred.get(g["pair_id"])
        hit["record"] += p is not None
        if g["effect_reported"]:
            eff["gold_with_number"] += 1
        if p is None:
            continue
        if v5:
            d = V5_DESIGN.get(p["study_type"], "animal" if p["study_type"] == "primary_experiment" else "other")
            hit["design"] += d == g["design"]
            eff["found"] += bool(g["effect_reported"]) and p["effect_percent"] is not None
            continue
        for f in FIELDS:
            hit[f] += p[f] == g[f]
        eff["found"] += bool(g["effect_reported"]) and overlaps(p["effect_reported"], g["effect_reported"])
    fields = ("design",) if v5 else FIELDS
    out = {"n": n, "with_record": hit["record"], **{f: round(hit[f] / n, 2) for f in fields}, "effect_number": eff}
    if not v5:
        out["status"] = "passed" if all(out[f] >= THRESHOLDS[f] for f in FIELDS) else "not passed"
        out["failed"] = [f for f in FIELDS if out[f] < THRESHOLDS[f]]
    return out


def measure_v3(gold: list[dict], pred: dict[str, dict | None], v5: bool = False) -> dict:
    """Gold v3: relevance on every pair; the extraction fields on the pairs the gold marks relevant (a missing record there
    is wrong on every field). Each field passes at its threshold only when it is also above its constant baseline."""
    rel = [g for g in gold if g["relevant"]]
    said = {g["pair_id"]: bool(pred.get(g["pair_id"]) and pred[g["pair_id"]]["relevant"]) for g in gold}
    tp = sum(said[g["pair_id"]] and g["relevant"] for g in gold)
    out = {"pairs": len(gold), "relevant_gold": len(rel),
           "relevance": {"accuracy": round(sum(said[g["pair_id"]] == g["relevant"] for g in gold) / len(gold), 2),
                         "recall": round(tp / max(1, len(rel)), 2), "precision": round(tp / max(1, sum(said.values())), 2),
                         "baseline": round(max(len(rel), len(gold) - len(rel)) / len(gold), 2)}}
    out["extraction"] = measure(rel, pred, v5=v5)
    out["extraction"].pop("status", None), out["extraction"].pop("failed", None)
    if not v5:
        base = baselines(rel)
        ok = {f: out["extraction"][f] >= THRESHOLDS[f] and out["extraction"][f] > base[f] for f in FIELDS}
        ok["relevance"] = out["relevance"]["accuracy"] >= RELEVANCE_THRESHOLD and out["relevance"]["accuracy"] > out["relevance"]["baseline"]
        out["status"] = "passed" if all(ok.values()) else "not passed"
        out["failed"] = [k for k, v in ok.items() if not v]
        out["formal"] = [f for f in FIELDS if out["extraction"][f] >= THRESHOLDS[f] and not ok[f]]
    return out


def baselines(gold: list[dict]) -> dict:
    """Share of the most common gold value per field: what a constant answer would score."""
    return {f: round(Counter(str(g[f]) for g in gold).most_common(1)[0][1] / len(gold), 2) for f in FIELDS}


def score(fake: bool = False, gold_name: str = "v3", versions: tuple = ()) -> dict:
    from hyparena.tools import pubmed
    gold = load_gold(gold_name)
    tasks = {json.loads(x)["pair_id"]: json.loads(x)
             for x in (GOLD_DIR / GOLDS[gold_name].get("task", "task.jsonl")).read_text().splitlines() if x.strip()}
    abstracts = pubmed.fetch([g["pair_id"].split("|")[2] for g in gold])
    rel = [g for g in gold if g.get("relevant", True)]
    out = {"baselines": baselines(rel), "thresholds": THRESHOLDS}
    for v in versions or GOLDS[gold_name]["versions"]:
        f = _run_file(gold_name, v, fake)
        if not f.exists() and gold_name == "v3":
            f = _run_file("manual", v, fake)               # saved replies of the 20 manual pairs (orientation only)
        runs = json.loads(f.read_text())
        pred = {}
        for g in gold:
            if g["pair_id"] not in runs:
                continue
            pmid = g["pair_id"].split("|")[2]
            a = abstracts.get(pmid) or {"title": tasks[g["pair_id"]]["title"], "abstract": tasks[g["pair_id"]]["abstract"]}
            pred[g["pair_id"]] = record_for(runs[g["pair_id"]].get("replies", []), pmid, a["title"] + " " + a["abstract"],
                                            review=pubmed.is_review(a), by_stance=gold_name in ("v3", "v8", "v9"))
        sub = [g for g in gold if g["pair_id"] in runs]
        out[v] = measure_v3(sub, pred, v5=v == "v5") if gold_name in ("v3", "v8", "v9") else measure(sub, pred, v5=v == "v5")
        if gold_name == "v3" and len(sub) < len(gold):
            out[v]["note"] = f"only {len(sub)} of {len(gold)} pairs have saved replies"
        if v != "v5":
            out[f"{v}_by_pair"] = {g["pair_id"]: {f: [g[f], (pred.get(g["pair_id"]) or {}).get(f)] for f in FIELDS}
                                   for g in rel if g["pair_id"] in runs}
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["pairs", "run", "score"])
    ap.add_argument("--fake", action="store_true", help="the fake model; files get a _fake suffix")
    ap.add_argument("--gold", choices=list(GOLDS), default="v8")
    ap.add_argument("--versions", default="", help="comma-separated, e.g. v6 to rescore saved v6 replies on gold v3")
    a = ap.parse_args()
    if a.cmd == "pairs":
        out = pairs() if a.gold == "v8" else pairs_retrieval()
        print(len(out), Counter(o.get("v2_recorded", o.get("jules")) for o in out))
        return
    if a.cmd == "run":
        if not a.fake and os.environ.get("ALLOW_PAID") != "1":
            raise SystemExit("paid: set ALLOW_PAID=1")
        run(a.fake, a.gold, tuple(x for x in a.versions.split(",") if x))
    else:
        vs = tuple(x for x in a.versions.split(",") if x)
        print(json.dumps(score(a.fake, a.gold, vs), indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()

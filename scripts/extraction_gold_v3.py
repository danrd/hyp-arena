"""Method v3 extraction (verify_claim/v6) against the hand-made gold for numbers, with the v2 verifier (verify_claim/v5) on
the same inputs for comparison. Criterion fixed before the first call: specs/extraction-gold-v3-2026-11-04.yaml.

    python -m scripts.extraction_gold_v3 run --fake                  # free dry run with the fake model (checks the plumbing)
    ALLOW_PAID=1 python -m scripts.extraction_gold_v3 run            # 20 pairs x (v5, v6), DeepSeek V4.1 Flash (configs/v3-flash.yaml)
    python -m scripts.extraction_gold_v3 score                       # measures from the saved replies, free

Input. The 20 pairs of $KG_DIR/hypothesis_sources/calibration/extraction_gold/labels_manual.jsonl; each pair is a claim of a frozen
calibration card (calibration/cards.json) and one paper. The verifier sees that one abstract (fetched from PubMed as in a run, no
search, no date cut, no subgroup check), once with v5 and once with v6. The raw replies are saved next to the gold in the private
repository (they quote the abstracts); this repository gets only the code and the numbers.

Which record is compared. The first record for the gold PMID whose quote is verbatim in the abstract, preferring quote_role
"finding"; the code checks of a run apply (v3_fields: a number phrase not verbatim in the abstract is dropped with its number).
A pair with no such record counts as wrong on every field.
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
VERSIONS = ("v5", "v6")
FIELDS = ("design", "comparison", "n_total", "effect_class")
THRESHOLDS = {"design": 0.8, "comparison": 0.8, "n_total": 0.8, "effect_class": 0.6}   # the spec; never changed after a result
V5_DESIGN = {"rct": "rct", "open_label_pilot": "non_randomised", "observational": "observational", "review": "review"}


def load_gold() -> list[dict]:
    return [json.loads(x) for x in (GOLD_DIR / "labels_manual.jsonl").read_text().splitlines() if x.strip()]


class Capture:
    """Passes calls through and keeps the reply texts, so that records the run would drop (stance "neither") are still seen."""

    def __init__(self, client):
        self.client, self.texts = client, []

    def call(self, **kw):
        r = self.client.call(**kw)
        self.texts.append(r.text)
        return r


def run(fake: bool = False) -> None:
    from hyparena.card import verifier
    from hyparena.card.models import HypothesisCard
    from hyparena.card.pipeline import _client
    from hyparena.tools import pubmed
    pubmed.search = lambda *a, **k: []                    # no retrieval: only the gold paper is read
    gold = load_gold()
    cards = json.loads(CARDS.read_text())
    client, _ = _client(CONFIG, fake, 4 * len(gold) * len(VERSIONS))
    for v in VERSIONS:
        out_p = GOLD_DIR / (f"run_{v}_fake.json" if fake else f"run_{v}.json")
        done = json.loads(out_p.read_text()) if out_p.exists() else {}
        for g in gold:
            if g["pair_id"] in done:
                continue
            unit, cid, pmid = g["pair_id"].split("|")
            card = HypothesisCard.model_validate(cards[unit])
            claim = next(c for c in card.claims if c.id == cid)
            cap = Capture(client)
            verifier.verify_claim(cap, FAMILY, frozenset(), claim, card, as_of=None, expert_pmids=[(pmid, "gold")],
                                  check_subgroups=False, search="keywords", template_version=v)
            done[g["pair_id"]] = {"replies": cap.texts}
            out_p.write_text(json.dumps(done, ensure_ascii=False, indent=1))
            print(json.dumps({"version": v, "pair": g["pair_id"], "calls": len(cap.texts)}), flush=True)


def record_for(replies: list[str], pmid: str, source: str) -> dict | None:
    """The compared record of a pair, with the code checks of a run applied (fields as EvidenceRecord names them)."""
    from hyparena.card.models import EvidenceRecord
    from hyparena.card.verifier import _norm, parse_records, v3_fields
    recs = []
    for t in reversed(replies):                           # the last parsed reply is the one a run keeps
        value = parse_records(t or "")
        if value and value.get("records"):
            recs = [r for r in value["records"] if isinstance(r, dict)]
            break
    recs = [r for r in recs if str(r.get("pmid", "")).replace("PMID:", "").strip() == pmid
            and r.get("quote") and _norm(r["quote"]) in _norm(source)]
    if not recs:
        return None
    r = next((r for r in recs if r.get("quote_role") == "finding"), recs[0])
    rec = EvidenceRecord(source="PubMed", record_id=f"PMID:{pmid}")
    v3_fields(rec, r, source)
    return {"design": rec.design, "comparison": rec.comparison, "n_total": rec.n_total, "effect_class": rec.effect_class,
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


def baselines(gold: list[dict]) -> dict:
    """Share of the most common gold value per field: what a constant answer would score."""
    return {f: round(Counter(str(g[f]) for g in gold).most_common(1)[0][1] / len(gold), 2) for f in FIELDS}


def score(fake: bool = False) -> dict:
    from hyparena.tools import pubmed
    gold = load_gold()
    tasks = {json.loads(x)["pair_id"]: json.loads(x) for x in (GOLD_DIR / "task.jsonl").read_text().splitlines() if x.strip()}
    abstracts = pubmed.fetch([g["pair_id"].split("|")[2] for g in gold])
    out = {"baselines": baselines(gold), "thresholds": THRESHOLDS}
    for v in VERSIONS:
        runs = json.loads((GOLD_DIR / (f"run_{v}_fake.json" if fake else f"run_{v}.json")).read_text())
        pred = {}
        for g in gold:
            pmid = g["pair_id"].split("|")[2]
            a = abstracts.get(pmid) or {"title": tasks[g["pair_id"]]["title"], "abstract": tasks[g["pair_id"]]["abstract"]}
            pred[g["pair_id"]] = record_for(runs.get(g["pair_id"], {}).get("replies", []), pmid, a["title"] + " " + a["abstract"])
        out[v] = measure(gold, pred, v5=v == "v5")
        if v == "v6":
            out["v6_by_pair"] = {g["pair_id"]: {f: [g[f], (pred[g["pair_id"]] or {}).get(f)] for f in FIELDS} for g in gold}
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["run", "score"])
    ap.add_argument("--fake", action="store_true", help="the fake model; files get a _fake suffix")
    a = ap.parse_args()
    if a.cmd == "run":
        if not a.fake and os.environ.get("ALLOW_PAID") != "1":
            raise SystemExit("paid: set ALLOW_PAID=1")
        run(a.fake)
    else:
        print(json.dumps(score(a.fake), indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()

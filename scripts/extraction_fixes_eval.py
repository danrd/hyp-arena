"""L1.17, descriptive and offline (no model calls): what the mutant-genotype rule and the voting of verifier replies would change, on the
saved replies of L1.17 (runs/stage5/l1_17). Measures: same claim status as the gold per paper (sex scope "any" and strict), status flips
(supported <-> refuted), the cell measures. Tuned on these 60 papers, so optimistic: adoption needs a check on new papers."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from hyparena.card.contexts import genotype_in
from scripts import extraction_compare as e
from scripts.extraction_status_impact import status

RUNS = Path("runs/stage5/l1_17")


def drop_mutants(records: list[dict]) -> list[dict]:
    return [r for r in records if not genotype_in(r.get("quote", ""))]


def cells(item: dict, mutant_rule: bool) -> list[dict]:
    return e.record_cells(drop_mutants(item["records"]) if mutant_rule else item["records"], item["compound"])


def combine(a: list[dict], b: list[dict], how: str, c: list[dict] | None = None) -> list[dict]:
    """Cells of two replies: `union` (any), `agree` (same direction in both), `mixed` (union; when the two give different directions for one
    compound-species-sex key, the third reply decides, else the key is dropped)."""
    key = lambda x: (x["compound"], x["species"], x["sex"])
    if how == "union":
        out = {tuple(x.values()): x for x in a + b}
        return list(out.values())
    if how == "agree":
        sb = {tuple(x.values()) for x in b}
        return [x for x in a if tuple(x.values()) in sb]
    da, db = {}, {}
    for x in a:
        da.setdefault(key(x), set()).add(x["direction"])
    for x in b:
        db.setdefault(key(x), set()).add(x["direction"])
    third = {}
    for x in c or []:
        third.setdefault(key(x), set()).add(x["direction"])
    out = []
    for k in set(da) | set(db):
        dirs = (da.get(k, set()) | db.get(k, set())) if not (k in da and k in db) or da[k] == db[k] else (third.get(k, set()) & (da[k] | db[k]))
        out += [{"compound": k[0], "species": k[1], "sex": k[2], "direction": d} for d in dirs]
    return out


def evaluate(pred_by_item: list[list[dict]], data: list[dict], gold: dict) -> dict:
    parts, same_any, same_strict, flips, n = [], 0, 0, 0, 0
    for item, pred in zip(data, pred_by_item):
        g = [c for c in e.gold_cells(gold[item["pmid"]]) if e._same_compound(c["compound"], item["compound"]) and c["species"] == item["species"]]
        if not g:
            continue
        n += 1
        parts.append(e.compare(g, pred))
        sg, sp = status(g, True), status(pred, True)
        same_any += sg == sp
        flips += {sg, sp} == {"supported", "refuted"}
        same_strict += status(g, False) == status(pred, False)
    t = e.totals(parts)
    return {"same_status_any": round(same_any / n, 3), "same_status_strict": round(same_strict / n, 3), "flips": flips,
            "found": t["found_rate"], "correct": t["correct_rate"], "dir_found": t["direction_given_found"], "precision": t["precision"]}


def main() -> None:
    gold = e.load_gold(e.DEFAULT_KG)
    d = {f: json.loads(Path(RUNS, f"{f}.json").read_text()) for f in ("deepseek", "deepseek_rep", "zhipu", "google")}
    base = d["deepseek"]
    rows = {}
    for rule in (False, True):
        tag = " + mutant rule" if rule else ""
        c = {f: [cells(it, rule) for it in d[f]] for f in d}
        rows["deepseek" + tag] = evaluate(c["deepseek"], base, gold)
        rows["zhipu" + tag] = evaluate(c["zhipu"], base, gold)
        rows["deepseek x2, union" + tag] = evaluate([combine(a, b, "union") for a, b in zip(c["deepseek"], c["deepseek_rep"])], base, gold)
        rows["deepseek x2, agree" + tag] = evaluate([combine(a, b, "agree") for a, b in zip(c["deepseek"], c["deepseek_rep"])], base, gold)
        rows["deepseek x2, mixed (zhipu decides)" + tag] = evaluate([combine(a, b, "mixed", z) for a, b, z in zip(c["deepseek"], c["deepseek_rep"], c["zhipu"])], base, gold)
        rows["deepseek + zhipu, union" + tag] = evaluate([combine(a, b, "union") for a, b in zip(c["deepseek"], c["zhipu"])], base, gold)
    dropped = Counter(f for f in d for it in d[f] for r in it["records"] if genotype_in(r.get("quote", "")))
    print("records dropped by the mutant rule per family:", dict(dropped))
    for k, v in rows.items():
        print(f"{k:45s} {v}")


if __name__ == "__main__":
    main()

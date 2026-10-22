"""Evidence-guided evolution of hypotheses over method v2. Parents are the top-ranked hypotheses of a saved v2 result;
a child is a refinement driven by what the verification found (narrow to a context with records, separate the
conditions of a conflict, add a mechanism the premise records support, add the control of an open alternative). Children
go through the same pipeline (card, verification, alternatives, informativeness) and are ranked together with the
parents under the same profiles. Nothing here decides whether a child is good: the criterion is declared in advance
(docs/evolution-experiment.md) and evaluated after the last round, whatever the result.

    python -m hyparena.card.evolve --v2 runs/x.reapplied.json --out runs/evolution/x.json --rounds 3 --parents 4 \
        --children 2 --max-calls 200"""
from __future__ import annotations

import argparse
import copy
import json
import re
import time
from pathlib import Path
from typing import Optional

from hyparena.card.llm import ask
from hyparena.card.models import HypothesisCard, Verification

TEMPLATE = ("evolve_hypothesis", "v1")
KINDS = ("narrow_context", "resolve_conflict", "add_mechanism", "test_alternative")
PROFILE = "evidence_first"


def _words(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (s or "").lower()))


def similar(a: str, b: str, threshold: float = 0.8) -> bool:
    wa, wb = _words(a), _words(b)
    return bool(wa and wb) and len(wa & wb) / len(wa | wb) >= threshold


def _main(item: dict):
    card = item["card"]
    oc = next((c for c in card["claims"] if c["role"] == "outcome"), None)
    cv = next((v for v in item["verification"]["claims"] if oc and v["id"] == oc["id"]), None)
    return oc, cv


def parent_facts(item: dict) -> dict:
    """The verified facts a child may use: statuses, a few quotes, contexts that hold only as analogs, open alternatives."""
    oc, cv = _main(item)
    ver = item["verification"]
    ev = []
    for side, label in (("evidence", "for"), ("counterevidence", "against")):
        for r in (cv or {}).get(side, [])[:2]:
            ev.append({"side": label, "pmid": r.get("record_id", ""), "quote": (r.get("quote") or "")[:220]})
    contexts = []
    for v in ver["claims"]:
        c = v.get("claim")
        if c and c["role"] == "analog" and (v["evidence"] or v["counterevidence"]):
            note = c.get("note", "")
            contexts.append(note.split(" (added")[0].strip() or "another context")
    mech = [f"{v['claim']['subject']['label']} {v['claim']['relation']} {v['claim']['object']['label']}: {v.get('status')}"
            for v in ver["claims"] if v.get("claim") and v["claim"]["role"] in ("mechanism", "premise")][:4]
    alts = [{"id": a["id"], "explanation": a["explanation"], "design": a.get("discriminating_design", "")}
            for a in ver.get("alternatives", []) if a.get("source") in ("checklist", "declared")
            and a.get("status") != "excluded_by_evidence"][:4]
    return {"text": item["text"], "main_claim": f"{oc['subject']['label']} {oc['relation']} {oc['object']['label']}" if oc else "",
            "main_status": (cv or {}).get("status", "unverified"), "n_for": len((cv or {}).get("evidence", [])),
            "n_against": len((cv or {}).get("counterevidence", [])), "evidence": ev,
            "contexts": "; ".join(dict.fromkeys(contexts)), "mechanism": "; ".join(mech) or "none stated",
            "alternatives": alts}


def _validate(value: dict, k: int, parent_text: str, intervention: str) -> list[str]:
    kids = value.get("children")
    if not isinstance(kids, list) or not kids:
        return ['the reply must be an object with a non-empty "children" list']
    problems = []
    for i, c in enumerate(kids[:k]):
        t = (c or {}).get("text", "") if isinstance(c, dict) else ""
        if not isinstance(c, dict) or c.get("kind") not in KINDS or not str(c.get("change", "")).strip():
            problems.append(f"child {i + 1}: kind must be one of {', '.join(KINDS)} and change must be a sentence")
        elif "hypothesis:" not in t.lower() or "decisive experiment:" not in t.lower():
            problems.append(f"child {i + 1}: the text needs the lines 'Hypothesis:' and 'Decisive experiment:'")
        elif intervention and intervention.lower() not in t.lower():
            problems.append(f"child {i + 1}: the intervention {intervention!r} must stay in the text")
        elif similar(t, parent_text):
            problems.append(f"child {i + 1}: copies the parent")
    return problems


def propose(client, family: str, item: dict, k: int, avoid: frozenset = frozenset(), log: Optional[list] = None) -> list[dict]:
    facts = parent_facts(item)
    card = item["card"]
    intervention = (card["pico"]["intervention"][0]["label"] if card["pico"]["intervention"] else "")
    value, _ = ask(client, role="evolve_hypothesis", family=family, template=TEMPLATE[0], version=TEMPLATE[1],
                   variables={**facts, "k": k},
                   validate=lambda v: _validate(v, k, item["text"], intervention), rounds=2, avoid=avoid, log=log)
    out = []
    for c in ((value or {}).get("children") or [])[:k]:
        if isinstance(c, dict) and not _validate({"children": [c]}, 1, item["text"], intervention):
            out.append({"text": c["text"].strip(), "kind": c["kind"], "change": str(c["change"]).strip()})
    return out


def select_parents(res: dict, n: int, used: set[str], profile: str = PROFILE) -> list[str]:
    """The top `n` ranked hypotheses under the profile that have not been parents yet."""
    order = (res.get("ranking") or {}).get(profile, {}).get("order", [])
    ok = {x["id"] for x in res["items"] if x["outcome"] == "ranked" and x.get("verification")}
    return [h for h in order if h in ok and h not in used][:n]


def _rename(obj, mapping: dict[str, str]):
    if isinstance(obj, dict):
        return {k: _rename(v, mapping) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_rename(v, mapping) for v in obj]
    return mapping.get(obj, obj) if isinstance(obj, str) else obj


def append_children(res: dict, child_res: dict, lineage: dict[str, dict], round_no: int) -> list[str]:
    """Add the items of a child run to the pool under fresh ids H-NNNN; `lineage[i]` (by the child run's item index)
    names the parent, the kind and the change. Returns the new ids."""
    n = len(res["items"])
    mapping, new_ids = {}, []
    for i, x in enumerate(child_res["items"]):
        mapping[x["id"]] = f"H-{n + i + 1:04d}"
    for i, x in enumerate(child_res["items"]):
        y = _rename(copy.deepcopy(x), mapping)
        y.update({"origin": "evolved", "round": round_no, **lineage[i]})
        res["items"].append(y)
        new_ids.append(mapping[x["id"]])
    res["calls"] = list(res.get("calls") or []) + list(child_res.get("calls") or [])
    return new_ids


def place_of(res: dict, hid: str, profile: str = PROFILE) -> Optional[int]:
    order = (res.get("ranking") or {}).get(profile, {}).get("order", [])
    return order.index(hid) + 1 if hid in order else None


def criterion(res: dict, profile: str = PROFILE, k: int = 3) -> dict:
    """The criterion declared in docs/evolution-experiment.md: a child in the top k whose P(top-k) is at least that of its parent."""
    P = (res.get("ranking") or {}).get(profile, {})
    by_id = {x["id"]: x for x in res["items"]}
    rows = []
    for x in res["items"]:
        if x.get("origin") != "evolved":
            continue
        par = by_id.get(x.get("parent"))
        place = place_of(res, x["id"], profile)
        pk = (P.get("p_topk") or {}).get(x["id"])
        ppk = (P.get("p_topk") or {}).get(x.get("parent"))
        rows.append({"id": x["id"], "parent": x.get("parent"), "round": x.get("round"), "kind": x.get("kind"), "outcome": x["outcome"],
                     "place": place, "p_topk": pk, "parent_place": place_of(res, x.get("parent"), profile), "parent_p_topk": ppk,
                     "wins": bool(place and place <= k and pk is not None and (ppk or 0) <= pk)})
    return {"profile": profile, "k": k, "children": rows, "success": any(r["wins"] for r in rows),
            "children_in_top_k": sum(1 for r in rows if r["place"] and r["place"] <= k), "n_children": len(rows)}


def evolve(res: dict, config: str, rounds: int = 3, parents: int = 4, children: int = 2, writer: str = "google",
           verifiers: Optional[list[str]] = None, max_calls: int = 200, fake: bool = False, as_of: Optional[str] = None,
           on_stage=lambda m: None, snapshot=None) -> dict:
    """Run the rounds on a saved v2 result; the budget `max_calls` is shared by the proposals and the verification."""
    from hyparena.card.pipeline import _client, reapply_rules, run
    started, spent = time.time(), 0
    res = copy.deepcopy(res)
    as_of = as_of or res["meta"].get("as_of")
    client, _ = _client(config, fake, max_calls)
    used, rounds_log, log = set(), [], []
    for r in range(1, rounds + 1):
        if spent >= max_calls:
            break
        picked = select_parents(res, parents, used)
        if not picked:
            break
        pool_texts = [x["text"] for x in res["items"]]
        texts, lineage = [], []
        for pid in picked:
            item = next(x for x in res["items"] if x["id"] == pid)
            used.add(pid)
            for c in propose(client, writer, item, children, avoid=frozenset(), log=log):
                if any(similar(c["text"], t) for t in pool_texts + texts):
                    continue
                texts.append(c["text"])
                lineage.append({"parent": pid, "kind": c["kind"], "change": c["change"]})
        spent = client.calls
        on_stage(f"раунд {r}: родители {picked}; потомков {len(texts)}; вызовов {spent}")
        if not texts:
            rounds_log.append({"round": r, "parents": picked, "children": [], "calls": spent})
            continue
        child = run(texts, writer=writer, config=config, fake=fake, as_of=as_of, max_calls=max(1, max_calls - spent),
                    verifiers=verifiers, check_alternatives=True, dedup=False, informativeness=True)
        spent += child["meta"]["calls"]
        new_ids = append_children(res, child, lineage, r)
        res = reapply_rules(res)
        rounds_log.append({"round": r, "parents": picked, "children": new_ids, "calls": spent,
                           "places": {h: place_of(res, h) for h in new_ids}})
        on_stage(f"раунд {r}: потомки {new_ids}; места {rounds_log[-1]['places']}; вызовов {spent}")
        if snapshot:
            snapshot(res)
    res["calls"] = list(res.get("calls") or []) + log
    res["meta"]["evolution"] = {"rounds": rounds_log, "parents_per_round": parents, "children_per_parent": children,
                                "writer": writer, "verifiers": verifiers, "calls": spent, "max_calls": max_calls,
                                "seconds": round(time.time() - started), "as_of": as_of, "profile": PROFILE,
                                "criterion": criterion(res)}
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--v2", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--config", default="configs/v2-flash.yaml")
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--parents", type=int, default=4)
    ap.add_argument("--children", type=int, default=2)
    ap.add_argument("--writer", default="google")
    ap.add_argument("--verifiers", default="deepseek")
    ap.add_argument("--max-calls", type=int, default=200)
    ap.add_argument("--fake", action="store_true")
    a = ap.parse_args()
    res = json.loads(Path(a.v2).read_text())
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    save = lambda r: out.write_text(json.dumps(r, ensure_ascii=False, indent=1, default=str))
    res = evolve(res, a.config, a.rounds, a.parents, a.children, a.writer, a.verifiers.split(","), a.max_calls, a.fake,
                 on_stage=lambda m: print(m, flush=True), snapshot=save)
    save(res)
    c = res["meta"]["evolution"]["criterion"]
    print(f"{a.out}; calls {res['meta']['evolution']['calls']}; children {c['n_children']}, in the top {c['k']}: "
          f"{c['children_in_top_k']}; criterion met: {c['success']}")


if __name__ == "__main__":
    main()

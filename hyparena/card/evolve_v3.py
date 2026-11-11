"""Evolution under method v3.3: apply the improvement list of chosen hypotheses (hyparena/card/improvements.py) and score
the result the same way (user decision 2026-11-06: the analysis names what to improve; evolution applies it, on request).

    ALLOW_PAID=1 python -m hyparena.card.evolve_v3 --pool prospective --n 60 --units NCT1,NCT2 [--items rewrite|i1,i3] \
        [--config configs/v3-flash-n10.yaml]
    python -m hyparena.card.evolve_v3 --top 10 --profile frontier [--dry]      # choose by the room to improve (free with --dry)

Choosing (user decision 2026-11-07, replaces the evolution profile): `choose` ranks the hypotheses by their room to improve
under the chosen profile (improvements.room: every computable "fixable by rewriting" item applied together, fixed scales).

For each chosen hypothesis: its improvement items (only the class "rewrite": research items need new data, not a new text)
-> one model call (prompt evolve_v3/v1) writes the improved text from the parent text and the items' facts -> code rejects a
copy of the parent or a change of intervention -> the child goes through the whole pipeline with the parent's date cut
(card, PubMed, alternatives) and the endpoint extraction (two families) -> both are scored by v3.3 and ASPID on fixed
scales (a score does not depend on the rest of the pool). `compare` gives, per pair, the change of every indicator and of
the score under each profile, the expected change of each applied item, the links added, removed or changed.

Limits (stated in the manual): evolution makes no new evidence; P can rise only by fitting the text to what was found, I by
a design that is still to be carried out; the child is written from the verifier's findings and scored by the same
verifier (circular), so a rise is a hint of what to change, not proof that the hypothesis became better.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Optional

from hyparena.card import improvements as imp
from hyparena.card import rules_v3 as r3
from hyparena.card.llm import ask
from hyparena.card.models import ClaimVerification, HypothesisCard

TEMPLATE = ("evolve_v3", "v2")          # tuning; v1 forced a "Mechanism:" line (first run, 2026-11-06)
FREE_TEMPLATE = ("evolve_free", "v1")
MODES = ("tune", "free")                  # user decision 2026-11-07: tuning and free evolution are separate and named


def _words(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (s or "").lower()))


def problems(value: dict, parent: str, intervention: str, allowed: set[str]) -> list[str]:
    out = []
    text = (value or {}).get("text") or ""
    if len(text) < 200:
        out.append("text is missing or too short")
    wp, wc = _words(parent), _words(text)
    if wp and wc and len(wp & wc) / len(wp | wc) > 0.9:
        out.append("the text is almost a copy of the parent: apply the improvements")
    key = [w for w in _words(intervention) if len(w) > 3]
    if key and not any(w in wc for w in key):
        out.append(f"the intervention ({intervention}) must stay the same and be named")
    applied = set((value or {}).get("applied") or [])
    if not applied or not applied <= allowed:
        out.append(f"applied must list the improvements applied, from {sorted(allowed)}")
    return out


def parent_parts(run_item: dict) -> tuple[HypothesisCard, list[ClaimVerification], dict]:
    card = HypothesisCard.model_validate(run_item["card"])
    cvs = [ClaimVerification.model_validate(c) for c in run_item["verification"]["claims"]]
    alts = {a: ClaimVerification.model_validate(v) for a, v in (run_item.get("v3_alternatives") or {}).items()}
    return card, cvs, alts


def propose(client, family: str, parent_text: str, intervention: str, items: list[dict], log: Optional[list] = None,
            novel: Optional[list[str]] = None, feedback: str = "") -> Optional[dict]:
    allowed = {i["id"] for i in items}
    variables = {"parent": parent_text, "items": [{**i, "what": i["what"][1]} for i in items], "novel": novel or [],
                 "feedback": feedback}
    value, _ = ask(client, role="evolve_v3", family=family, template=TEMPLATE[0], version=TEMPLATE[1], variables=variables,
                   validate=lambda v: problems(v, parent_text, intervention, allowed), rounds=2, log=log)
    if value is None or problems(value, parent_text, intervention, allowed):
        return None
    return value


def free_problems(value: dict) -> list[str]:
    out = []
    if len((value or {}).get("text") or "") < 200:
        out.append("text is missing or too short")
    if not isinstance((value or {}).get("cited_pmids", []), list):
        out.append("cited_pmids must be a list of PMIDs")
    return out


def propose_free(client, family: str, parent_text: str, items: list[dict], profile: str, novelty: Optional[str], as_of: str,
                 log: Optional[list] = None) -> Optional[dict]:
    from hyparena.card import aspid_v3
    prof = aspid_v3.load()[profile][0]
    order = " > ".join("{" + ", ".join(t) + "}" if len(t) > 1 else t[0] for t in prof.tiers)
    variables = {"parent": parent_text, "items": [{**i, "what": i["what"][1]} for i in items], "profile": profile,
                 "order": order, "novelty": novelty or "unknown", "novelty_first": "N" in prof.tiers[0], "as_of": as_of}
    value, _ = ask(client, role="evolve_free", family=family, template=FREE_TEMPLATE[0], version=FREE_TEMPLATE[1],
                   variables=variables, validate=free_problems, rounds=2, log=log)
    if value is None or free_problems(value):
        return None
    value["cited_pmids"] = [re.sub(r"\D", "", str(x)) for x in value.get("cited_pmids", []) if re.sub(r"\D", "", str(x))]
    return value


def distance(parent: str, child: str) -> float:
    """1 - Jaccard of content words; above NEW_AFTER the child is marked "a new hypothesis after" the parent."""
    a, b = _words(parent), _words(child)
    return round(1 - len(a & b) / len(a | b), 3) if a | b else 0.0


NEW_AFTER = 0.7


def endpoint(client, text: str) -> Optional[str]:
    """The endpoint category of a text by two families (as specs/estimand-2026-11-06.yaml); None when they disagree."""
    from scripts import estimand_check as ec
    vals = set()
    for fam in ec.FAMILIES:
        value, _ = ask(client, role="verify_claim", family=fam, template="estimand", version="v1", variables={"text": text},
                       validate=ec.problems, rounds=2)
        vals.add(ec.clean(value, text)["endpoint"] if value else None)
    v = vals.pop() if len(vals) == 1 else None
    return v if v not in (None, "not_stated") else None


def _novel_parts(card: HypothesisCard, cvs: list[ClaimVerification]) -> list[str]:
    from hyparena.card import novelty_v34 as nv
    lv = nv.link_levels(card, cvs)
    return [f"{c.subject.label} — {c.relation.replace('_', ' ')} — {c.object.label}" for c in r3.chain(card)
            if lv.get(c.id) in ("analog", "new_link")]


def evolve(run: dict, units: list[str], extras: dict[str, dict], config: str, item_choice: str = "rewrite",
           writer: str = "google", fake: bool = False, max_calls: int = 60, out_path: Optional[Path] = None,
           mode: str = "tune", profile: str = "evidence", retries: int = 1) -> dict:
    """`run` {unit: saved pipeline result}; `extras` {unit: indicator values not in the card (endpoint, trend, ...)}.

    mode "tune" (доработка): only the "fixable by rewriting" items; the parent's new parts must stay; a child that moved towards
    the known (novelty_v34.drift) is sent back to the writer with the reason, `retries` times, and kept with the flag if it
    still drifts. mode "free" (свободная эволюция): everything may change, for the named profile; the writer names its papers
    (counted only if the verifier finds them before the cut-off); drift is flagged, never constrained; a child far from the
    parent (distance > NEW_AFTER) is marked "a new hypothesis after" it. Free mode is for current pools only (the writer
    knows literature past the cut-off)."""
    from hyparena.card import novelty_v34 as nv
    from hyparena.card.pipeline import _client, run as pipeline
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    client, _ = _client(config, fake, (max_calls + 10) * len(units) * (1 + retries) + 10)
    done = json.loads(out_path.read_text()) if out_path and out_path.exists() else {"pairs": {}}
    for u in units:
        if u in done["pairs"]:
            continue
        r = run[u]
        it = r["items"][0]
        card, cvs, alts = parent_parts(it)
        items = imp.items(card, cvs, alts, extras.get(u, {}), it["v3"].get("headroom_I"))
        as_of = r["meta"].get("as_of")
        entry = {"mode": mode, "profile": profile, "all_items": items}
        log: list = []
        if mode == "tune":
            if item_choice == "rewrite":
                chosen = [i for i in items if i["cls"] == "rewrite"]
            else:
                ids = set(item_choice.split(","))
                chosen = [i for i in items if i["id"] in ids and i["cls"] == "rewrite"]
            entry["items"] = chosen
            if not chosen:
                entry["skipped"] = "no rewrite item"
                done["pairs"][u] = entry
                continue
            intervention = card.pico.intervention[0].label if card.pico.intervention else ""
            novel, feedback, attempts = _novel_parts(card, cvs), "", []
            for k in range(retries + 1):
                value = propose(client, writer, it["text"], intervention, chosen, log, novel=novel, feedback=feedback)
                if value is None:
                    break
                child = pipeline([value["text"]], writer="evolution", config=config, as_of=as_of, max_calls=max_calls,
                                 verifiers=["deepseek"], fake=fake)
                ci = child["items"][0]
                dr = nv.drift((card, cvs), parent_parts(ci)[:2]) if ci.get("card") and ci.get("verification") else None
                attempts.append({"value": value, "child_run": child, "drift": dr})
                if not dr or not dr["drift_to_known"]:
                    break
                feedback = "; ".join(dr["reasons"])
            entry["proposal_calls"] = len(log)
            if not attempts:
                entry["skipped"] = "no valid proposal"
                done["pairs"][u] = entry
                continue
            last = attempts[-1]
            entry.update({"child_text": last["value"]["text"], "applied": last["value"]["applied"],
                          "changes": last["value"].get("changes", []), "child_run": last["child_run"],
                          "attempts": len(attempts), "constraint_kept": not (last["drift"] or {}).get("drift_to_known", False)})
        else:
            entry["items"] = items
            value = propose_free(client, writer, it["text"], items, profile, nv.novelty(card, cvs), as_of or "", log)
            entry["proposal_calls"] = len(log)
            if value is None:
                entry["skipped"] = "no valid proposal"
                done["pairs"][u] = entry
                continue
            child = pipeline([value["text"]], writer="evolution_free", config=config, as_of=as_of, max_calls=max_calls,
                             verifiers=["deepseek"], fake=fake)
            ci = child["items"][0]
            found = {rec.get("record_id", "").replace("PMID:", "") for c in (ci.get("verification") or {}).get("claims", [])
                     for rec in c.get("evidence", []) + c.get("counterevidence", [])}
            entry.update({"child_text": value["text"], "applied": [], "changes": value.get("changes", []), "child_run": child,
                          "cited_pmids": value["cited_pmids"], "cited_found": sorted(set(value["cited_pmids"]) & found),
                          "distance": distance(it["text"], value["text"])})
            entry["new_hypothesis_after"] = entry["distance"] > NEW_AFTER
        entry["child_endpoint"] = endpoint(client, entry["child_text"])
        done["pairs"][u] = entry
        if out_path:
            out_path.write_text(json.dumps(done, ensure_ascii=False, default=str))
    if out_path:
        out_path.write_text(json.dumps(done, ensure_ascii=False, default=str))
    return done


def choose(run: dict, extras: dict[str, dict], profile: str, k: int) -> list[dict]:
    """The k hypotheses with the largest room to improve under `profile` (gain > 0), with the gain and the novelty change."""
    rows = []
    for u, r in run.items():
        it = r["items"][0]
        if not it.get("card") or not it.get("verification") or "v3" not in it:
            continue
        card, cvs, alts = parent_parts(it)
        rm = imp.room(card, cvs, alts, extras.get(u, {}), it["v3"].get("headroom_I"))
        if not rm or profile not in rm["score"]:
            continue
        a, b = rm["score"][profile]
        rows.append({"unit": u, "gain": round(b - a, 4), "now": a, "after": b, "N": rm["N"], "applied": rm["applied"],
                     "not_computed": rm["not_computed"]})
    rows.sort(key=lambda x: -x["gain"])
    return [x for x in rows if x["gain"] > 0][:k]


def _chain_texts(card: HypothesisCard) -> dict[str, str]:
    return {c.id: f"{c.link}: {c.subject.label} — {c.relation} — {c.object.label}" for c in r3.chain(card)}


def compare(parent_item: dict, child_item: dict, parent_extras: dict, child_extras: dict, mode: str = "tune",
            parent_logs: Optional[dict] = None, child_logs: Optional[dict] = None, as_of: str = "",
            child_text: str = "", get=None) -> Optional[dict]:
    """Per pair: indicators before and after, the score under each profile before and after (fixed scales), links added,
    removed and changed (S before -> after), and the novelty drift (novelty_v34.drift: flagged, never excluding)."""
    if not child_item.get("card") or not child_item.get("verification") or "v3" not in child_item:
        return None
    from hyparena.card import novelty_v34 as nv
    pc, pcv, pa = parent_parts(parent_item)
    cc, ccv, ca = parent_parts(child_item)
    ep, ec = imp.evaluate(pc, pcv, pa), imp.evaluate(cc, ccv, ca)
    # new_mechanism (v3.9): a link between supported neighbours counted new on PubMed before T (free, only with a date)
    absence = (nv.mechanism_absence(pc, pcv, as_of, get), nv.mechanism_absence(cc, ccv, as_of, get)) if as_of else (None, None)
    dr = nv.drift((pc, pcv), (cc, ccv), absence)
    dr["mechanism_absence"] = list(absence)
    parent_extras = {**parent_extras, "N": dr["N"][0]}
    child_extras = {**child_extras, "N": dr["N"][1]}
    pairs = {"parent": imp.axes(ep, parent_item["v3"].get("headroom_I"), parent_extras),
             "child": imp.axes(ec, child_item["v3"].get("headroom_I"), child_extras)}
    sc = imp.scores(pairs, K=10000)
    ind = {}
    for name, a, b in (("chain_state", ep.chain_state, ec.chain_state), ("I", ep.I, ec.I), ("support_share", ep.support_share, ec.support_share),
                       ("W", ep.scope, ec.scope), ("endpoint_clinical", parent_extras.get("endpoint_clinical"), child_extras.get("endpoint_clinical")),
                       ("N", dr["N"][0], dr["N"][1])):
        ind[name] = [a, b]
    pt, ct = _chain_texts(pc), _chain_texts(cc)
    p_by_text = {v: k for k, v in pt.items()}
    links = {"added": [], "removed": [], "kept": []}
    for k, v in ct.items():
        if v in p_by_text:
            links["kept"].append({"text": v, "S": [ep.links[p_by_text[v]][0], ec.links[k][0]]})
        else:
            links["added"].append({"text": v, "S": ec.links[k][0], "records": ec.links[k][3] + ec.links[k][4] > 0})
    links["removed"] = [{"text": v, "S": ep.links[k][0]} for k, v in pt.items() if v not in set(ct.values())]
    from hyparena.card import evolution_rules as er          # manual section 11: rules every version keeps; the two parts
    score = {p: [sc["parent"].get(p), sc["child"].get(p)] for p in sc["parent"]}
    rules = er.check((pc, pcv, parent_logs or {}), (cc, ccv, child_logs or {}), mode=mode, as_of=as_of,
                     child_experiment_text=child_text, parent_alts=pa, child_alts=ca, scores=score, pubmed=bool(as_of), get=get)
    return {"gate": [ep.gate, ec.gate], "indicators": ind, "score": score, "links": links, "drift": dr,
            "decomposition": er.decompose(pairs["parent"], pairs["child"]), "rules": rules}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pool", choices=["prospective"], default="prospective")
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--units", default="", help="comma-separated unit ids (or choose with --top)")
    ap.add_argument("--top", type=int, default=0, help="choose this many hypotheses by the room to improve")
    ap.add_argument("--profile", default="evidence", help="profile under which the room is computed")
    ap.add_argument("--dry", action="store_true", help="only print the choice (free)")
    ap.add_argument("--mode", choices=MODES, default="tune", help="tune (доработка) or free (свободная эволюция)")
    ap.add_argument("--writer", default="google", help="model family that writes the improved text")
    ap.add_argument("--items", default="rewrite", help="'rewrite' (all fixable items) or item ids, e.g. i1,i3")
    ap.add_argument("--config", default="configs/v3-flash-n10.yaml")
    a = ap.parse_args()
    from scripts.prospective import OUT
    run = json.loads((OUT / f"run_{a.n}.json").read_text())
    sf = OUT / f"scores_{a.n}_v34.json"
    scores = json.loads((sf if sf.exists() else OUT / f"scores_{a.n}.json").read_text())
    extras = {u: {k: scores.get(u, {}).get(k) for k in ("endpoint_clinical", "trend_pubmed", "ai_role", "feasibility")} for u in run}
    units = [u for u in a.units.split(",") if u]
    if a.top:
        picked = choose(run, extras, a.profile, a.top)
        print(json.dumps(picked, indent=1, ensure_ascii=False))
        units = [x["unit"] for x in picked]
    if a.dry or not units:
        return
    if os.environ.get("ALLOW_PAID") != "1":
        raise SystemExit("paid: set ALLOW_PAID=1")
    out = OUT / (f"evolution_{a.n}.json" if a.mode == "tune" else f"evolution_free_{a.n}.json")
    res = evolve(run, units, extras, a.config, a.items, writer=a.writer, out_path=out, mode=a.mode, profile=a.profile)
    print(json.dumps({u: {k: v for k, v in e.items() if k in ("skipped", "applied")} for u, e in res["pairs"].items()}, indent=1))


if __name__ == "__main__":
    main()

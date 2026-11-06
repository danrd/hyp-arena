"""Evolution under method v3.3: apply the improvement list of chosen hypotheses (hyparena/card/improvements.py) and score
the result the same way (user decision 2026-11-06: the analysis names what to improve; evolution applies it, on request).

    ALLOW_PAID=1 python -m hyparena.card.evolve_v3 --pool prospective --n 60 --units NCT1,NCT2 [--items rewrite|i1,i3] \
        [--config configs/v3-flash-n10.yaml]

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

TEMPLATE = ("evolve_v3", "v1")


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


def propose(client, family: str, parent_text: str, intervention: str, items: list[dict], log: Optional[list] = None) -> Optional[dict]:
    allowed = {i["id"] for i in items}
    variables = {"parent": parent_text, "items": [{**i, "what": i["what"][1]} for i in items]}
    value, _ = ask(client, role="evolve_v3", family=family, template=TEMPLATE[0], version=TEMPLATE[1], variables=variables,
                   validate=lambda v: problems(v, parent_text, intervention, allowed), rounds=2, log=log)
    if value is None or problems(value, parent_text, intervention, allowed):
        return None
    return value


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


def evolve(run: dict, units: list[str], extras: dict[str, dict], config: str, item_choice: str = "rewrite",
           writer: str = "google", fake: bool = False, max_calls: int = 60, out_path: Optional[Path] = None) -> dict:
    """`run` {unit: saved pipeline result}; `extras` {unit: indicator values not in the card (endpoint, trend, ...)}."""
    from hyparena.card.pipeline import _client, run as pipeline
    client, _ = _client(config, fake, max_calls * len(units) + 10)
    done = json.loads(out_path.read_text()) if out_path and out_path.exists() else {"pairs": {}}
    for u in units:
        if u in done["pairs"]:
            continue
        r = run[u]
        it = r["items"][0]
        card, cvs, alts = parent_parts(it)
        items = imp.items(card, cvs, alts, extras.get(u, {}), it["v3"].get("headroom_I"))
        if item_choice == "rewrite":
            chosen = [i for i in items if i["cls"] == "rewrite"]
        else:
            ids = set(item_choice.split(","))
            chosen = [i for i in items if i["id"] in ids and i["cls"] == "rewrite"]
        entry = {"items": chosen, "all_items": items}
        if not chosen:
            entry["skipped"] = "no rewrite item"
            done["pairs"][u] = entry
            continue
        log: list = []
        intervention = card.pico.intervention[0].label if card.pico.intervention else ""
        value = propose(client, writer, it["text"], intervention, chosen, log)
        entry["proposal_calls"] = len(log)
        if value is None:
            entry["skipped"] = "no valid proposal"
            done["pairs"][u] = entry
            continue
        entry.update({"child_text": value["text"], "applied": value["applied"], "changes": value.get("changes", [])})
        as_of = r["meta"].get("as_of")
        entry["child_run"] = pipeline([value["text"]], writer="evolution", config=config, as_of=as_of, max_calls=max_calls,
                                      verifiers=["deepseek"], fake=fake)
        entry["child_endpoint"] = endpoint(client, value["text"])
        done["pairs"][u] = entry
        if out_path:
            out_path.write_text(json.dumps(done, ensure_ascii=False, default=str))
    if out_path:
        out_path.write_text(json.dumps(done, ensure_ascii=False, default=str))
    return done


def _chain_texts(card: HypothesisCard) -> dict[str, str]:
    return {c.id: f"{c.link}: {c.subject.label} — {c.relation} — {c.object.label}" for c in r3.chain(card)}


def compare(parent_item: dict, child_item: dict, parent_extras: dict, child_extras: dict) -> Optional[dict]:
    """Per pair: indicators before and after, the score under each profile before and after (fixed scales), links added,
    removed and changed (S before -> after)."""
    if not child_item.get("card") or not child_item.get("verification") or "v3" not in child_item:
        return None
    pc, pcv, pa = parent_parts(parent_item)
    cc, ccv, ca = parent_parts(child_item)
    ep, ec = imp.evaluate(pc, pcv, pa), imp.evaluate(cc, ccv, ca)
    pairs = {"parent": imp.axes(ep, parent_item["v3"].get("headroom_I"), parent_extras),
             "child": imp.axes(ec, child_item["v3"].get("headroom_I"), child_extras)}
    sc = imp.scores(pairs, K=10000)
    ind = {}
    for name, a, b in (("P", ep.P, ec.P), ("I", ep.I, ec.I), ("support_share", ep.support_share, ec.support_share),
                       ("W", ep.scope, ec.scope), ("endpoint_clinical", parent_extras.get("endpoint_clinical"), child_extras.get("endpoint_clinical"))):
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
    return {"gate": [ep.gate, ec.gate], "indicators": ind, "score": {p: [sc["parent"].get(p), sc["child"].get(p)] for p in sc["parent"]},
            "links": links}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pool", choices=["prospective"], default="prospective")
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--units", required=True, help="comma-separated unit ids")
    ap.add_argument("--items", default="rewrite", help="'rewrite' (all fixable items) or item ids, e.g. i1,i3")
    ap.add_argument("--config", default="configs/v3-flash-n10.yaml")
    a = ap.parse_args()
    if os.environ.get("ALLOW_PAID") != "1":
        raise SystemExit("paid: set ALLOW_PAID=1")
    from scripts.prospective import OUT
    run = json.loads((OUT / f"run_{a.n}.json").read_text())
    scores = json.loads((OUT / f"scores_{a.n}.json").read_text())
    extras = {u: {k: scores.get(u, {}).get(k) for k in ("endpoint_clinical", "trend_pubmed", "ai_role")} for u in run}
    out = OUT / f"evolution_{a.n}.json"
    res = evolve(run, a.units.split(","), extras, a.config, a.items, out_path=out)
    print(json.dumps({u: {k: v for k, v in e.items() if k in ("skipped", "applied")} for u, e in res["pairs"].items()}, indent=1))


if __name__ == "__main__":
    main()

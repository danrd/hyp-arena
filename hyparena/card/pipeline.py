"""Method v2 end to end: texts → normalizer → admission → verifier → statuses and evidence profile → indicators
→ aggregation under each preference profile (docs/rules-method.md).

    ALLOW_PAID=1 python -m hyparena.card.pipeline --paste hypotheses.txt --writer openai --out runs/v2.json
    python -m hyparena.card.pipeline --paste hypotheses.txt --fake --out runs/v2.json        # no model calls
    ... --expert expert.yaml      # expert layer (card spec 7a): sources, opinions, pairwise choices, own hypotheses"""
from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from hyparena.aspid import InfeasiblePreferences, load_profiles
from hyparena import diagnostics, diversity
from hyparena.card import alternatives, entities, proximity
from hyparena.card import expert as ex
from hyparena.card import indicators as ind
from hyparena.card.models import HypothesisCard, Verification
from hyparena.card.normalizer import normalize
from hyparena.card.lifespan import late_start
from hyparena.card.rank import rank
from hyparena.card.rules import STRAIN_ANALOG, add_disease_analogs, add_strain_analogs, admit, finalize
from hyparena.card.verifier import verify
from hyparena.llm.fake import FakeLLMClient
from hyparena.llm.providers import DEFAULT_CONFIG, GuardedClient, build_client, load_config


def _client(config: str, fake: bool, max_calls: int):
    if fake:
        fams = [s.family for s in load_config(config).models if s.enabled]
        return GuardedClient(FakeLLMClient(0), rpm=0, max_calls=max_calls), fams
    client, pool, _ = build_client(config, max_calls=max_calls)
    return client, [j.family for j in pool]


def _record_indicator_set(res: dict) -> None:
    """A recomputed result carries the indicator set it was computed with (saved runs list their own)."""
    res["meta"]["indicators"] = [{"id": s.id, "kind": s.kind, "levels": list(s.levels), "bounds": list(s.bounds), "note": s.note}
                                 for s in ind.INDICATORS]
    res["meta"]["indicator_set"] = {"sha256": ind.set_hash(ind.INDICATORS, load_profiles()), "ids": [s.id for s in ind.INDICATORS]}


def reapply_rules(res: dict, K: int = 10000, k_top: int = 3, new_rules: bool = True, ex_restore: Optional[dict] = None) -> dict:
    """A saved v2 result with the rules applied again, without model calls and without touching the sources: the
    records, the cards and the saved `extra` stay as they were; `sex_scope` is read from the hypothesis text, the
    protocol strata are marked, statuses, profiles, indicators and the ranking are recomputed. `new_rules=False`
    leaves out the scope and the strata: it reproduces a run made before them (a check of this function)."""
    import copy
    from hyparena.card import contexts
    from hyparena.card.rules import mark_strata, set_sex_scope
    from hyparena.tools import pubmed
    res = copy.deepcopy(res)
    ex_restore = ex_restore or {}
    triples = []
    for x in res["items"]:
        if not x.get("verification"):
            continue
        card = HypothesisCard.model_validate(x["card"])
        ver = Verification.model_validate(x["verification"])
        if new_rules:
            set_sex_scope(card, x["text"])
            for cv in ver.claims:
                mark_strata(cv.evidence + cv.counterevidence)
                for r in cv.evidence + cv.counterevidence:      # the context labels again, abstracts from the cache
                    pm = r.record_id.replace("PMID:", "") if r.record_id.startswith("PMID:") else ""
                    f = pubmed.CACHE / f"{pm}.json"
                    a = json.loads(f.read_text()) if pm and f.exists() else {}
                    contexts.flag(r, (a.get("title", "") + " " + a.get("abstract", "")).strip(), r.strain if r.source != "PubMed" else "")
            ver = add_disease_analogs(card, ver, ex_restore.get(card.id, frozenset()))
        ver = finalize(card, ver)
        x["card"], x["verification"] = card.model_dump(by_alias=True), ver.model_dump(by_alias=True)
        triples.append((card, ver, x.get("extra") or {}))
    ranking = rank(triples, K=K, k_top=k_top) if triples else None
    for x in res["items"]:
        if not x.get("verification") or ranking is None:
            continue
        cid = x["card"]["id"]
        x["outcome"] = ("filtered" if cid in ranking.filtered else "known_result" if cid in ranking.known_results else "ranked")
        x["indicators"] = ranking.values.get(cid)
    view = lambda r: {"order": r.order, "expected": r.expected, "std": r.std, "quantiles": r.quantiles,
                      "p_topk": r.p_topk, "p_best": r.p_best, "pairwise": r.pairwise,
                      "rank_acceptability": r.rank_acceptability, "central_weights": r.central_weights,
                      "confidence": r.confidence, "meta": r.meta}
    res["ranking"] = {n: view(r) for n, r in ranking.by_profile.items()} if ranking else {}
    res["robust"] = ranking.robust if ranking else []
    res["filtered"] = ranking.filtered if ranking else {}
    res["known_results"] = ranking.known_results if ranking else []
    res.update(unranked_lists(res["items"]))
    res["meta"]["reapplied"] = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "new_rules": new_rules}
    _record_indicator_set(res)
    res["top_distinct"] = diversity.top_distinct(res)
    res["meta"]["diagnostics"] = diagnostics.pool_diagnostics(res["items"], res["ranking"], [i["id"] for i in res["meta"]["indicators"]])
    return res


def _extra(card: HypothesisCard, as_of: Optional[str] = None) -> dict:
    """Values from other components: human safety data of the interventions (ChEMBL phase and first approval,
    ClinicalTrials.gov as of T) for path_to_human; late_start from the age at start and the median table."""
    out = {}
    safety = entities.human_safety(card, as_of)
    if safety is not None:
        out["human_safety"] = safety
    start = late_start(card)
    if start is not None:
        out["late_start"] = list(start) if isinstance(start, tuple) else start
    return out


def run(texts: list[str], writer: str = "unknown", config: str = "configs/v2.yaml", fake: bool = False,
        as_of: Optional[str] = None, K: int = 10000, k_top: int = 3, max_calls: int = 400, workers: int = 4,
        normalizer_family: str = "google", on_stage=lambda msg: None, expert=None,
        verifiers: Optional[list[str]] = None, cards: Optional[list[Optional[dict]]] = None,
        check_alternatives: bool = True, dedup: bool = True, informativeness: bool = False,
        spec: Optional[str] = None) -> dict:
    """`spec`: a committed file in specs/ fixed before the run (hyparena/prespec.py); its hash goes into the meta, and a
    parameter that differs from the spec stops the run. `expert`: path to an expert file (hyparena/card/expert.py) or an ExpertLayer. `verifiers`: the families
    that verify (default: every family of the config). `cards`: declared cards from an earlier run, one per
    text (None where normalization failed); the normalizer is then skipped, so a change of the verifier is
    compared on the same cards. `check_alternatives`: one call per gate-passing hypothesis over the abstracts
    already read, and a dedicated search per open alternative for P(top-k) >= 0.5 (spec 8c). `dedup`: a card
    that duplicates an earlier one (spec 8b) is not verified and gets the outcome `duplicate`."""
    from hyparena import prespec
    iset = ind.set_hash(ind.INDICATORS, load_profiles())
    spec_entry = prespec.begin(spec, {"as_of": as_of, "K": K, "k_top": k_top, "max_calls": max_calls,
                                      "indicators_sha256": iset}) if spec else None
    started = time.time()
    layer = expert if isinstance(expert, ex.ExpertLayer) else ex.load(expert)
    origins = ["external"] * len(texts) + ["expert"] * len(layer.hypotheses)
    texts = list(texts) + list(layer.hypotheses)
    client, families = _client(config, fake, max_calls)
    log: list = []
    checker = next((f for f in (verifiers or families) if f != writer), (verifiers or families)[0])
    pool = ThreadPoolExecutor(max_workers=workers)
    items = []

    def one(idx_text):
        i, text = idx_text
        cid = f"H-{i:04d}"
        # the normalizer is a parser, not a judge: one strong family for every text (independence does not apply)
        norm_family = normalizer_family if normalizer_family in families else families[0]
        if cards is not None:
            saved = cards[i - 1]
            card = HypothesisCard.model_validate(saved) if saved else None
            problems = [] if card else ["no card in the earlier run"]
        else:
            card, problems = normalize(client, norm_family, text, cid, log=log)
        return {"id": cid, "text": text, "card": card, "problems": problems, "origin": origins[i - 1]}

    items = list(pool.map(one, enumerate(texts, start=1)))
    on_stage(f"карточки: {sum(1 for x in items if x['card'])} из {len(items)}; вызовов: {client.calls}")
    triples = []
    for x in items:
        card = x["card"]
        if card is None:
            x["outcome"] = "normalization_failed"
            continue
        x["unresolved_compounds"] = entities.resolve_card(card)
        adm = admit(card)
        x["admission"] = adm
        if adm.decision != "accepted":
            x["outcome"] = adm.decision
        elif "unmapped_relation" in adm.flags:               # outcome still `other` after the re-parse (spec 5)
            x["outcome"] = "unparsed"
    # typed proximity among the admitted cards (spec 8b): duplicates are not verified twice, competitors become
    # alternatives of each other
    admitted = [x["card"] for x in items if "outcome" not in x]
    rels = proximity.relations(admitted, proximity.analog_keys, proximity.default_embedder())
    dup_of = proximity.duplicates(rels, [c.id for c in admitted]) if dedup else {}
    rivals = proximity.competitors(rels)
    by_card = {c.id: c for c in admitted}
    for x in items:
        if "outcome" not in x and x["card"].id in dup_of:
            x["outcome"], x["duplicate_of"] = "duplicate", dup_of[x["card"].id]
    for x in items:              # collapsed before АСПИД: only the original is ranked; repeats are metadata, not merit
        if x["card"] is not None:
            x["repeats"] = sum(1 for h in dup_of.values() if h == x["card"].id)
    for x in items:
        if "outcome" in x:
            continue
        card = x["card"]
        ver = verify(client, verifiers or families, writer, card, as_of=as_of, log=log, map_fn=pool.map,
                     expert_sources=ex.sources(layer, card.id), fallback_families=families,
                     disease_restore=ex.restored_records(layer, card.id))
        ver.alternatives += alternatives.competitor_rows(
            [by_card[h] for h in rivals.get(card.id, []) if h not in dup_of])
        x["verification"] = finalize(card, ver)
        if check_alternatives and x["verification"].evidence_profile.gate == "pass":
            alternatives.check(client, checker, card, x["verification"], avoid=frozenset({writer}), log=log)
        x["extra"] = _extra(card, as_of)
        if informativeness and x["verification"].evidence_profile.gate == "pass":      # one call: alternatives the experiment discriminates
            from hyparena.card.informativeness import discriminated
            info = discriminated(client, checker, x["text"], card, x["verification"], avoid=frozenset({writer}), log=log)
            if info is not None:
                x["extra"].update({"informativeness": info["n"], "informativeness_detail": info})
        triples.append((card, x["verification"], x["extra"]))
        on_stage(f"{card.id} проверена; вызовов: {client.calls}")
    pool.shutdown()
    gap = []
    try:
        ranking = rank(triples, K=K, k_top=k_top, prefer=ex.preferences(layer)) if triples else None
    except InfeasiblePreferences as e:                  # criterion_gap: report the conflict, rank without the choices
        gap = [vars(c) for c in e.conflicting]
        ranking = rank(triples, K=K, k_top=k_top)
    for x in items:
        if "outcome" in x:
            continue
        cid = x["card"].id
        x["outcome"] = ("filtered" if ranking and cid in ranking.filtered else "known_result"
                        if ranking and cid in ranking.known_results else "ranked")
        if ranking and cid in ranking.values:
            x["indicators"] = ranking.values[cid]
    # a dedicated search per open checklist alternative, only for strong hypotheses (spec 8c, before debates)
    strong = {h for r in (ranking.by_profile.values() if ranking else []) for h, p in r.p_topk.items() if p >= 0.5}
    for x in items:
        if check_alternatives and x.get("verification") and x["card"].id in strong and x["outcome"] == "ranked":
            alternatives.deep_check(client, checker, x["card"], x["verification"], as_of=as_of,
                                    avoid=frozenset({writer}), log=log)
    view = lambda r: {"order": r.order, "expected": r.expected, "std": r.std, "quantiles": r.quantiles,
                      "p_topk": r.p_topk, "p_best": r.p_best, "pairwise": r.pairwise,
                      "rank_acceptability": r.rank_acceptability, "central_weights": r.central_weights,
                      "confidence": r.confidence, "meta": r.meta}
    profiles = {name: view(r) for name, r in ranking.by_profile.items()} if ranking else {}
    autonomous = {name: view(r) for name, r in ranking.autonomous.items()} if ranking else {}
    result = {"meta": {"created": time.strftime("%Y-%m-%dT%H:%M:%S"), "seconds": round(time.time() - started),
                     "calls": client.calls, "failures": client.failures, "families": families, "writer": writer,
                     "verifiers": verifiers or families, "config": config, "cards_reused": cards is not None,
                     "as_of": as_of, "fake": fake, "k_top": k_top, **({"spec": spec_entry} if spec_entry else {}),
                     "indicator_set": {"sha256": iset, "ids": [s.id for s in ind.INDICATORS]},
                     "profiles": {n: {"tiers": p.tiers, "version": p.version, "description": p.description}
                                  for n, p in load_profiles().items()},
                     "indicators": [{"id": s.id, "kind": s.kind, "levels": list(s.levels), "bounds": list(s.bounds),
                                     "note": s.note} for s in ind.INDICATORS]},
            "items": [{"id": x["id"], "text": x["text"], "origin": x["origin"], "outcome": x["outcome"],
                       "duplicate_of": x.get("duplicate_of"), "repeats": x.get("repeats", 0),
                       "problems": x["problems"], "expert": ex.opinions(layer, x["id"]),
                       "card": x["card"].model_dump(by_alias=True) if x["card"] else None,
                       "admission": x["admission"].model_dump() if x.get("admission") else None,
                       "verification": x["verification"].model_dump(by_alias=True) if x.get("verification") else None,
                       "indicators": x.get("indicators"), "extra": x.get("extra"),
                       "unresolved_compounds": x.get("unresolved_compounds", [])} for x in items],
            "ranking": profiles, "robust": ranking.robust if ranking else [],
            **unranked_lists(items),
            "proximity": [r.as_dict() for r in rels], "variant_groups": proximity.variant_groups(rels),
            "ranking_autonomous": autonomous, "criterion_gap": gap,
            "expert_skipped": [vars(c) for c in ranking.expert_skipped] if ranking else [],
            "filtered": ranking.filtered if ranking else {}, "known_results": ranking.known_results if ranking else [],
            "calls": log}
    result["top_distinct"] = diversity.top_distinct(result, result["proximity"])
    result["meta"]["diagnostics"] = diagnostics.pool_diagnostics(result["items"], result["ranking"], [s.id for s in ind.INDICATORS])
    return result


OUTCOMES = ("ranked", "filtered", "known_result", "duplicate", "needs_refinement", "not_a_hypothesis", "unparsed",
            "normalization_failed")


def unranked_lists(items: list[dict]) -> dict:
    """No hypothesis disappears silently (spec 10): every input has exactly one outcome; those not ranked are
    listed with the reason, and the counts and shares are reported."""
    bad = [x["id"] for x in items if x.get("outcome") not in OUTCOMES]
    if bad:
        raise ValueError(f"hypotheses without an outcome: {bad}")
    card = lambda x: x["card"] if isinstance(x["card"], dict) else (x["card"].model_dump(by_alias=True) if x["card"] else {})
    adm = lambda x: x["admission"] if isinstance(x.get("admission"), dict) else (x["admission"].model_dump() if x.get("admission") else {})

    def outcome_claim(x):
        return next((c for c in card(x).get("claims", []) if c.get("role") == "outcome"), {})
    counts = {o: sum(x["outcome"] == o for x in items) for o in OUTCOMES}
    return {
        "awaiting_refinement": [{"id": x["id"], "missing_critical": adm(x).get("missing_critical", [])}
                                for x in items if x["outcome"] == "needs_refinement"],
        "unparsed": [{"id": x["id"], "flag": "unmapped_relation", "note": outcome_claim(x).get("note", ""),
                      "source_span": outcome_claim(x).get("source_span", "")}
                     for x in items if x["outcome"] == "unparsed"],
        "directions": [{"id": x["id"], "reason": adm(x).get("reason", "")}
                       for x in items if x["outcome"] == "not_a_hypothesis"],
        "normalization_failed": [{"id": x["id"], "problems": x.get("problems", [])}
                                 for x in items if x["outcome"] == "normalization_failed"],
        "duplicates": [{"id": x["id"], "duplicate_of": x.get("duplicate_of")}
                       for x in items if x["outcome"] == "duplicate"],
        "outcome_counts": counts,
        "outcome_shares": {o: round(n / len(items), 3) for o, n in counts.items()} if items else {},
    }


def refresh_curated(res: dict, K: int = 10000, k_top: int = 3) -> dict:
    """Recompute a saved v2 result after a change of the curated sources or the rules, without model calls:
    the DrugAge records of every verified claim are rebuilt (as of the run's date), statuses, profiles and
    the ranking recomputed. Records from the literature keep the extractor's fields; the code checks on them
    (the compound named in the quote, context flags, the stance of lifespan findings) are applied again."""
    from hyparena.card.verifier import curated, recheck
    as_of = res["meta"]["as_of"]
    triples = []
    verified = [HypothesisCard.model_validate(x["card"]) for x in res["items"] if x.get("verification")]
    rels = proximity.relations(verified, proximity.analog_keys, proximity.default_embedder())
    rivals, by_card = proximity.competitors(rels), {c.id: c for c in verified}
    for x in res["items"]:
        if not x.get("verification"):
            continue
        card = HypothesisCard.model_validate(x["card"])
        ver = Verification.model_validate(x["verification"])
        ver.alternatives = [a for a in ver.alternatives if a.source != "proximity"] + alternatives.competitor_rows(
            [by_card[h] for h in rivals.get(card.id, [])])
        ver.claims = [cv for cv in ver.claims if not (cv.claim and cv.claim.note.startswith(STRAIN_ANALOG))]
        for cv in ver.claims:                                 # their records come back from the rebuilt sources
            cv.refusals = [r for r in cv.refusals if not (r.type == "inherited_mismatch" and "counted for analog" in r.notes)]
        by_id = {c.id: c for c in [*card.claims, *card.declared_alternatives]}
        for cv in ver.claims:
            claim = cv.claim or by_id.get(cv.id)
            if claim is None:
                continue
            support, against = curated(claim, card, as_of)
            pub_for, pub_against = recheck(claim, card, [r for r in cv.evidence if r.source == "PubMed"],
                                           [r for r in cv.counterevidence if r.source == "PubMed"])
            cv.evidence = [r for r in cv.evidence if r.source not in ("DrugAge", "PubMed")] + pub_for + support
            cv.counterevidence = [r for r in cv.counterevidence if r.source not in ("DrugAge", "PubMed")] + pub_against + against
        ver = finalize(card, add_strain_analogs(card, add_disease_analogs(card, ver)))
        x["verification"] = ver.model_dump(by_alias=True)
        x["extra"] = _extra(card, as_of)                      # path_to_human inputs as of the run's date
        triples.append((card, ver, x["extra"]))
    ranking = rank(triples, K=K, k_top=k_top) if triples else None
    for x in res["items"]:
        if not x.get("verification") or ranking is None:
            continue
        cid = x["card"]["id"]
        x["outcome"] = ("filtered" if cid in ranking.filtered else "known_result" if cid in ranking.known_results
                        else "ranked")
        x["indicators"] = ranking.values.get(cid)
    res["ranking"] = {name: {"order": r.order, "expected": r.expected, "std": r.std, "p_topk": r.p_topk,
                             "p_best": r.p_best, "meta": r.meta} for name, r in ranking.by_profile.items()} if ranking else {}
    res["robust"] = ranking.robust if ranking else []
    res["filtered"] = ranking.filtered if ranking else {}
    res["known_results"] = ranking.known_results if ranking else []
    res.update(unranked_lists(res["items"]))
    res["proximity"], res["variant_groups"] = [r.as_dict() for r in rels], proximity.variant_groups(rels)
    res["meta"]["refreshed"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _record_indicator_set(res)
    res["top_distinct"] = diversity.top_distinct(res, res["proximity"])
    res["meta"]["diagnostics"] = diagnostics.pool_diagnostics(res["items"], res["ranking"], [i["id"] for i in res["meta"]["indicators"]])
    return res


OUTCOME_SCORE = {"known_result": 3.0, "ranked": 2.0, "duplicate": 1.0, "needs_refinement": 1.0, "not_a_hypothesis": 1.0,
                 "unparsed": 1.0, "normalization_failed": 1.0, "filtered": 0.0}


def as_ladder_result(res: dict, ids: list[str], profile: str = "evidence_first", step: str = "v2") -> dict:
    """A v2 result in the format the ladder evaluations read (negatives, backtest): one combined score per
    hypothesis. Order: known result (a supported finding in the same context) > ranked, by the expected value
    under `profile` > not admitted > filtered by the gate. `ids[i]` names the i-th input text."""
    ranking = res["ranking"].get(profile) or {}
    hyps = {}
    for hid, x in zip(ids, res["items"]):
        score = OUTCOME_SCORE.get(x["outcome"], 1.0)
        if x["outcome"] == "ranked":
            score += ranking.get("expected", {}).get(x["id"], 0.0)
        out_claim = next((c for c in (x["verification"] or {}).get("claims", [])
                          if c["id"] == next((k["id"] for k in (x["card"] or {}).get("claims", []) if k["role"] == "outcome"), None)), {})
        hyps[hid] = {"status": x["outcome"], "combined": score, "card_id": x["id"],
                     "outcome_status": out_claim.get("status"),
                     "gate_reason": ((x["verification"] or {}).get("evidence_profile") or {}).get("gate_reason", "")}
    return {"criteria": [], "step": step, "profile": profile, "families": res["meta"]["families"],
            "calls": res["meta"]["calls"], "as_of": res["meta"]["as_of"],
            "tokens": {"all": {"tokens_in": sum(c.get("tokens_in") or 0 for c in res["calls"] if c.get("kind") == "llm"),
                               "tokens_out": sum(c.get("tokens_out") or 0 for c in res["calls"] if c.get("kind") == "llm")}},
            "hypotheses": _with_duplicates(hyps, res)}


def _with_duplicates(hyps: dict, res: dict) -> dict:
    """A duplicate takes the score and status of the card it duplicates."""
    by_card = {v["card_id"]: v for v in hyps.values()}
    dup = {x["id"]: x.get("duplicate_of") for x in res["items"] if x["outcome"] == "duplicate"}
    for h, v in hyps.items():
        rep = by_card.get(dup.get(v["card_id"]))
        if rep is not None:
            hyps[h] = {**rep, "card_id": v["card_id"], "duplicate_of": rep["card_id"]}
    return hyps


def main() -> None:
    from hyparena.showcase import split_hypotheses
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--paste", required=True, help="text file with hypotheses (numbered or separated by blank lines)")
    ap.add_argument("--writer", default="unknown")
    ap.add_argument("--config", default="configs/v2.yaml")
    ap.add_argument("--normalizer-family", default="google")
    ap.add_argument("--fake", action="store_true")
    ap.add_argument("--as-of", default=None)
    ap.add_argument("--K", type=int, default=10000)
    ap.add_argument("--k-top", type=int, default=3)
    ap.add_argument("--max-calls", type=int, default=400)
    ap.add_argument("--expert", default=None, help="expert file (YAML, see hyparena/card/expert.py)")
    ap.add_argument("--verifiers", default=None, help="comma-separated families that verify (default: all)")
    ap.add_argument("--cards-from", default=None, help="an earlier v2 result whose cards are reused (no normalizer)")
    ap.add_argument("--informativeness", action="store_true", help="one call per hypothesis: alternatives the decisive experiment discriminates")
    ap.add_argument("--spec", default=None, help="committed spec in specs/ fixed before the run (hash goes into the meta)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    texts = split_hypotheses(Path(args.paste).read_text(encoding="utf-8"))
    res = run(texts, args.writer, args.config, args.fake, args.as_of, args.K, args.k_top, args.max_calls,
              normalizer_family=args.normalizer_family, on_stage=lambda m: print(m, flush=True), expert=args.expert,
              verifiers=args.verifiers.split(",") if args.verifiers else None, informativeness=args.informativeness,
              cards=[x["card"] for x in json.loads(Path(args.cards_from).read_text())["items"]] if args.cards_from else None,
              spec=args.spec)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    for x in res["items"]:
        print(f"{x['id']} {x['outcome']:<22} {x['text'][:70]}")
    for name, p in res["ranking"].items():
        print(name, [(h, round(p["expected"][h], 3), round(p["p_topk"][h], 2)) for h in p["order"]])
    print(f"robust: {res['robust']}; calls: {res['meta']['calls']}; {res['meta']['seconds']} s; {args.out}")


if __name__ == "__main__":
    main()

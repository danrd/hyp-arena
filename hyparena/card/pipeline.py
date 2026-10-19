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
from hyparena.card import expert as ex
from hyparena.card import indicators as ind
from hyparena.card.models import HypothesisCard, Verification
from hyparena.card.normalizer import normalize
from hyparena.card.rank import rank
from hyparena.card.rules import admit, finalize
from hyparena.card.verifier import verify
from hyparena.llm.fake import FakeLLMClient
from hyparena.llm.providers import DEFAULT_CONFIG, GuardedClient, build_client, load_config
from hyparena.tools import drug_phase


def _client(config: str, fake: bool, max_calls: int):
    if fake:
        fams = [s.family for s in load_config(config).models if s.enabled]
        return GuardedClient(FakeLLMClient(0), rpm=0, max_calls=max_calls), fams
    client, pool, _ = build_client(config, max_calls=max_calls)
    return client, [j.family for j in pool]


def _extra(card: HypothesisCard) -> dict:
    """Values from other components: translational distance from the max clinical phase of the compounds (a
    combination is as advanced as its least advanced component)."""
    comps = [i for i in card.pico.intervention if i.type == "compound"]
    if comps and len(comps) == len(card.pico.intervention):
        phases = [drug_phase.max_phase(i.label) for i in comps]
        if all(p is not None for p in phases):
            return {"max_phase": min(phases)}
    return {}


def run(texts: list[str], writer: str = "unknown", config: str = "configs/v2.yaml", fake: bool = False,
        as_of: Optional[str] = None, K: int = 10000, k_top: int = 3, max_calls: int = 400, workers: int = 4,
        normalizer_family: str = "google", on_stage=lambda msg: None, expert=None) -> dict:
    """`expert`: path to an expert file (hyparena/card/expert.py) or an ExpertLayer."""
    started = time.time()
    layer = expert if isinstance(expert, ex.ExpertLayer) else ex.load(expert)
    origins = ["external"] * len(texts) + ["expert"] * len(layer.hypotheses)
    texts = list(texts) + list(layer.hypotheses)
    client, families = _client(config, fake, max_calls)
    log: list = []
    pool = ThreadPoolExecutor(max_workers=workers)
    items = []

    def one(idx_text):
        i, text = idx_text
        cid = f"H-{i:04d}"
        # the normalizer is a parser, not a judge: one strong family for every text (independence does not apply)
        norm_family = normalizer_family if normalizer_family in families else families[0]
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
        adm = admit(card)
        x["admission"] = adm
        if adm.decision != "accepted":
            x["outcome"] = adm.decision
            continue
        ver = verify(client, families, writer, card, as_of=as_of, log=log, map_fn=pool.map,
                     expert_sources=ex.sources(layer, card.id))
        x["verification"] = finalize(card, ver)
        x["extra"] = _extra(card)
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
    view = lambda r: {"order": r.order, "expected": r.expected, "std": r.std, "quantiles": r.quantiles,
                      "p_topk": r.p_topk, "p_best": r.p_best, "pairwise": r.pairwise,
                      "rank_acceptability": r.rank_acceptability, "central_weights": r.central_weights,
                      "confidence": r.confidence, "meta": r.meta}
    profiles = {name: view(r) for name, r in ranking.by_profile.items()} if ranking else {}
    autonomous = {name: view(r) for name, r in ranking.autonomous.items()} if ranking else {}
    return {"meta": {"created": time.strftime("%Y-%m-%dT%H:%M:%S"), "seconds": round(time.time() - started),
                     "calls": client.calls, "failures": client.failures, "families": families, "writer": writer,
                     "as_of": as_of, "fake": fake, "k_top": k_top,
                     "profiles": {n: {"tiers": p.tiers, "version": p.version, "description": p.description}
                                  for n, p in load_profiles().items()},
                     "indicators": [{"id": s.id, "kind": s.kind, "levels": list(s.levels), "bounds": list(s.bounds),
                                     "note": s.note} for s in ind.INDICATORS]},
            "items": [{"id": x["id"], "text": x["text"], "origin": x["origin"], "outcome": x["outcome"],
                       "problems": x["problems"], "expert": ex.opinions(layer, x["id"]),
                       "card": x["card"].model_dump(by_alias=True) if x["card"] else None,
                       "admission": x["admission"].model_dump() if x.get("admission") else None,
                       "verification": x["verification"].model_dump(by_alias=True) if x.get("verification") else None,
                       "indicators": x.get("indicators"), "extra": x.get("extra")} for x in items],
            "ranking": profiles, "robust": ranking.robust if ranking else [],
            "ranking_autonomous": autonomous, "criterion_gap": gap,
            "expert_skipped": [vars(c) for c in ranking.expert_skipped] if ranking else [],
            "filtered": ranking.filtered if ranking else {}, "known_results": ranking.known_results if ranking else [],
            "calls": log}


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
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    texts = split_hypotheses(Path(args.paste).read_text(encoding="utf-8"))
    res = run(texts, args.writer, args.config, args.fake, args.as_of, args.K, args.k_top, args.max_calls,
              normalizer_family=args.normalizer_family, on_stage=lambda m: print(m, flush=True), expert=args.expert)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    for x in res["items"]:
        print(f"{x['id']} {x['outcome']:<22} {x['text'][:70]}")
    for name, p in res["ranking"].items():
        print(name, [(h, round(p["expected"][h], 3), round(p["p_topk"][h], 2)) for h in p["order"]])
    print(f"robust: {res['robust']}; calls: {res['meta']['calls']}; {res['meta']['seconds']} s; {args.out}")


if __name__ == "__main__":
    main()

"""tournament: choose pairs, pick independent judges, judge (pairs in parallel), refit ratings per axis."""
from __future__ import annotations

from collections import Counter
from typing import Optional

from hyparena.llm.judges import JudgeSpec, pick_judges
from hyparena.llm.structured import ask_json
from hyparena.rating import combined, elo_ratings, fit_bt, select_pairs, select_pairs_coscientist
from hyparena.schema import verdict_example
from hyparena.state import GraphState, Hypothesis, JudgeVerdict, Match, Provenance, usable


def _validator(names: list[str]):
    def validate(value: dict) -> list[str]:
        return [f"`{c}` must be 1 or 2." for c in names if value.get(c) not in (1, 2)]
    return validate


def _review_notes(h: Hypothesis) -> str:
    notes = [n for r in h.reviews for n in r.notes]
    return "; ".join(notes) if notes else "none"


def _shown(h: Hypothesis, n_evidence: int) -> dict:
    """What a judge sees of one hypothesis: the original text, the declared card, the retrieved
    evidence (excerpts with dates), and the reviewers' remarks."""
    return {"text": h.text, "review_notes": _review_notes(h),
            "card": h.card.filled() if h.card else {}, "gaps": h.card.gaps if h.card else [],
            "evidence": usable(h.evidence)[:n_evidence]}


def _disagree(verdicts: list[JudgeVerdict], names: list[str]) -> bool:
    return any(len({v.winner[c] for v in verdicts if c in v.winner}) > 1 for c in names)


def _aggregate(verdicts: list[JudgeVerdict], tiebreak: Optional[JudgeVerdict],
               names: list[str]) -> dict[str, Optional[str]]:
    winners: dict[str, Optional[str]] = {}
    for ax in names:
        ranked = Counter(v.winner[ax] for v in verdicts if ax in v.winner).most_common(2)
        if not ranked:
            winners[ax] = None
        elif len(ranked) == 2 and ranked[0][1] == ranked[1][1]:
            winners[ax] = tiebreak.winner.get(ax) if tiebreak is not None else None
        else:
            winners[ax] = ranked[0][0]
    return winners


def make_tournament(ctx):
    cfg = ctx.cfg

    def ask_verdict(state, rng, judge: JudgeSpec, ha: Hypothesis, hb: Hypothesis, mode: str) -> JudgeVerdict:
        first, second = (hb, ha) if rng.random() < 0.5 else (ha, hb)     # random A/B order
        plan = state["plan"]
        n = cfg.evidence_to_judges
        template, version = (f"cs_{mode}", "v1") if cfg.judge_view == "coscientist" else (mode, "v3")
        out = ask_json(
            ctx, role=mode, family=judge.family, template=template, version=version,
            phase="debate" if mode == "debate" else "rank", validate=_validator(plan.names),
            variables={"goal": state["goal"], "plan": plan, "feedback": state.get("feedback", {}),
                       "first": _shown(first, n), "second": _shown(second, n),
                       "example": verdict_example(plan.criteria)})
        prov = out.provenance or Provenance(family=judge.family, model_version=judge.model_version, role=mode)
        if not out.ok:
            return JudgeVerdict(provenance=prov, order=[first.id, second.id], parse_ok=False)
        v = out.value
        return JudgeVerdict(provenance=prov, order=[first.id, second.id], parse_ok=True,
                            rationale=str(v.get("rationale", "")),
                            winner={c: (first.id if v[c] == 1 else second.id) for c in plan.names})

    def judge_pair(task) -> Optional[Match]:
        state, ha, hb, debate = task
        names = state["plan"].names
        if ctx.tokens_used() >= cfg.max_tokens:          # budget spent: no new matches (finer than per cycle)
            ctx.log.write({"event": "budget_skip", "a": ha.id, "b": hb.id})
            return None
        hyps, pool = state["hypotheses"], ctx.judge_pool
        rng = ctx.rng_for("match", state.get("cycle", 0), ha.id, hb.id)   # reproducible per pair
        judges = pick_judges(pool, ha, hb, hyps, cfg.lineage_mode, 1 if debate else cfg.judges_per_match, rng)
        if not judges:
            ctx.log.write({"event": "judge_shortfall", "a": ha.id, "b": hb.id})
            return None
        mode = "debate" if debate else "compare"
        verdicts = [ask_verdict(state, rng, j, ha, hb, mode) for j in judges]
        tiebreak = None
        if not debate and _disagree(verdicts, names):
            extra = pick_judges(pool, ha, hb, hyps, cfg.lineage_mode, cfg.extra_judges, rng,
                                exclude={j.family for j in judges})
            verdicts += [ask_verdict(state, rng, j, ha, hb, "compare") for j in extra]
            if _disagree(verdicts, names):
                final = pick_judges(pool, ha, hb, hyps, cfg.lineage_mode, 1, rng)
                if final:
                    tiebreak = ask_verdict(state, rng, final[0], ha, hb, "debate")
                    verdicts.append(tiebreak)
        decided = [v for v in verdicts if v.parse_ok]
        if not decided:
            return None
        return Match(a=ha.id, b=hb.id, mode="debate" if debate else "single", judges=verdicts,
                     contested=_disagree(decided, names),
                     winners=_aggregate(decided, tiebreak if tiebreak is not None and tiebreak.parse_ok else None,
                                        names))

    def fit(ids, matches, names):
        rate = elo_ratings if cfg.rating == "elo" else fit_bt
        return {c: rate(ids, matches, c) for c in names}

    def tournament(state: GraphState) -> dict:
        hyps, plan = state["hypotheses"], state["plan"]
        ids = [h.id for h in hyps.values() if h.status == "active"]
        old = state.get("matches", [])
        ratings = fit(ids, old, plan.names)
        if len(ids) < 2:
            return {"ratings": ratings}
        top_k = max(2, int(len(ids) * cfg.top_frac))
        n_matches = max(4, int(cfg.matches_per_item * len(ids)))
        rng = ctx.rng_for("pairs", state.get("cycle", 0))
        if cfg.pairing == "coscientist":
            pairs = select_pairs_coscientist(ids, ratings, plan.weights, {h: hyps[h].cluster for h in ids}, rng,
                                             n_matches)
        else:
            pairs = select_pairs(ids, ratings, plan.weights, rng, n_matches, top_k, cfg.swiss_share, cfg.z)
        score, _ = combined(ratings, plan.weights, ids)
        top = {ids[i] for i in sorted(range(len(ids)), key=lambda i: -score[i])[: cfg.debate_top]}
        tasks = [(state, hyps[a], hyps[b], a in top and b in top) for a, b in pairs]
        new = [m for m in ctx.map(judge_pair, tasks) if m is not None]
        ratings = fit(ids, old + new, plan.names)
        score, _ = combined(ratings, plan.weights, ids)
        ranked = [ids[i] for i in sorted(range(len(ids)), key=lambda i: -score[i])]
        return {"matches": new, "ratings": ratings,
                "top_history": state.get("top_history", []) + [ranked[:top_k]]}
    return tournament

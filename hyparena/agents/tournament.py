"""tournament: choose pairs, pick independent judges, judge, and refit ratings per axis."""
from __future__ import annotations

from collections import Counter
from typing import Optional

from hyparena.llm.judges import JudgeSpec, pick_judges
from hyparena.llm.structured import ask_json
from hyparena.rating import combined, fit_bt, select_pairs
from hyparena.state import AXES, GraphState, Hypothesis, JudgeVerdict, Match


def _validate(value: dict) -> list[str]:
    return [f"`{ax}` must be 1 or 2." for ax in AXES if value.get(ax) not in (1, 2)]


def _review_notes(h: Hypothesis) -> str:
    notes = [n for r in h.reviews for n in r.notes]
    return "; ".join(notes) if notes else "none"


def _disagree(verdicts: list[JudgeVerdict]) -> bool:
    return any(len({v.winner[ax] for v in verdicts if ax in v.winner}) > 1 for ax in AXES)


def _aggregate(verdicts: list[JudgeVerdict], tiebreak: Optional[JudgeVerdict]) -> dict[str, Optional[str]]:
    winners: dict[str, Optional[str]] = {}
    for ax in AXES:
        votes = Counter(v.winner[ax] for v in verdicts if ax in v.winner)
        ranked = votes.most_common(2)
        if not ranked:
            winners[ax] = None
        elif len(ranked) == 2 and ranked[0][1] == ranked[1][1]:
            winners[ax] = tiebreak.winner.get(ax) if tiebreak is not None else None
        else:
            winners[ax] = ranked[0][0]
    return winners


def make_tournament(ctx):
    cfg = ctx.cfg

    def ask_verdict(state: GraphState, judge: JudgeSpec, ha: Hypothesis, hb: Hypothesis,
                    mode: str) -> JudgeVerdict:
        first, second = (hb, ha) if ctx.rng.random() < 0.5 else (ha, hb)    # random A/B order
        out = ask_json(
            ctx, role=mode, family=judge.family, template=mode, version="v1",
            phase="debate" if mode == "debate" else "rank", validate=_validate,
            variables={"goal": state["goal"], "plan": state["plan"],
                       "feedback": state.get("feedback", {}),
                       "first": {"text": first.text, "review_notes": _review_notes(first)},
                       "second": {"text": second.text, "review_notes": _review_notes(second)}})
        prov = out.provenance
        if not out.ok or prov is None:
            return JudgeVerdict(provenance=prov or _fallback_prov(judge, mode),
                                order=[first.id, second.id], parse_ok=False)
        v = out.value
        return JudgeVerdict(provenance=prov, order=[first.id, second.id], parse_ok=True,
                            rationale=str(v.get("rationale", "")),
                            winner={ax: (first.id if v[ax] == 1 else second.id) for ax in AXES})

    def _fallback_prov(judge: JudgeSpec, mode: str):
        from hyparena.state import Provenance
        return Provenance(family=judge.family, model_version=judge.model_version, role=mode)

    def judge_pair(state: GraphState, ha: Hypothesis, hb: Hypothesis, debate: bool) -> Optional[Match]:
        hyps, pool, rng = state["hypotheses"], ctx.judge_pool, ctx.rng
        judges = pick_judges(pool, ha, hb, hyps, cfg.lineage_mode, 1 if debate else cfg.judges_per_match, rng)
        if not judges:
            ctx.log.write({"event": "judge_shortfall", "a": ha.id, "b": hb.id})
            return None
        mode = "debate" if debate else "compare"
        verdicts = [ask_verdict(state, j, ha, hb, mode) for j in judges]
        tiebreak = None
        if not debate and _disagree(verdicts):
            extra = pick_judges(pool, ha, hb, hyps, cfg.lineage_mode, cfg.extra_judges, rng,
                                exclude={j.family for j in judges})
            verdicts += [ask_verdict(state, j, ha, hb, "compare") for j in extra]
            if _disagree(verdicts):
                final = pick_judges(pool, ha, hb, hyps, cfg.lineage_mode, 1, rng)
                if final:
                    tiebreak = ask_verdict(state, final[0], ha, hb, "debate")
                    verdicts.append(tiebreak)
        decided = [v for v in verdicts if v.parse_ok]
        if not decided:
            return None
        return Match(a=ha.id, b=hb.id, mode="debate" if debate else "single", judges=verdicts,
                     contested=_disagree(decided), winners=_aggregate(decided, tiebreak if tiebreak and tiebreak.parse_ok else None))

    def tournament(state: GraphState) -> dict:
        hyps, plan = state["hypotheses"], state["plan"]
        ids = [h.id for h in hyps.values() if h.status == "active"]
        old = state.get("matches", [])
        ratings = {ax: fit_bt(ids, old, ax) for ax in AXES}
        if len(ids) < 2:
            return {"ratings": ratings}
        top_k = max(2, int(len(ids) * cfg.top_frac))
        n_matches = max(4, int(cfg.matches_per_item * len(ids)))
        pairs = select_pairs(ids, ratings, plan.axis_weights, ctx.rng, n_matches, top_k,
                             cfg.swiss_share, cfg.z)
        score, _ = combined(ratings, plan.axis_weights, ids)
        top = {ids[i] for i in sorted(range(len(ids)), key=lambda i: -score[i])[: cfg.debate_top]}
        new = [m for a, b in pairs
               if (m := judge_pair(state, hyps[a], hyps[b], a in top and b in top)) is not None]
        ratings = {ax: fit_bt(ids, old + new, ax) for ax in AXES}
        score, _ = combined(ratings, plan.axis_weights, ids)
        ranked = [ids[i] for i in sorted(range(len(ids)), key=lambda i: -score[i])]
        return {"matches": new, "ratings": ratings,
                "top_history": state.get("top_history", []) + [ranked[:top_k]]}
    return tournament

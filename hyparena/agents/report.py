"""report: Pareto front over the two axes, then a diversified list of the best hypotheses."""
from __future__ import annotations

from hyparena.rating import combined
from hyparena.state import AXES, GraphState


def pareto_front(points: dict[str, tuple[float, float]]) -> list[str]:
    front = []
    for h, (p, f) in points.items():
        dominated = any(p2 >= p and f2 >= f and (p2 > p or f2 > f)
                        for g, (p2, f2) in points.items() if g != h)
        if not dominated:
            front.append(h)
    return front


def make_report(ctx):
    def report(state: GraphState) -> dict:
        hyps, ratings, plan = state.get("hypotheses", {}), state.get("ratings", {}), state["plan"]
        ids = [h.id for h in hyps.values() if h.status == "active" and ratings.get("promise", {}).get(h.id)]
        if not ids:
            return {"report": {"front": [], "shown": [], "tokens": ctx.tracer.summary()}}
        points = {i: (ratings["promise"][i].score, ratings["feasibility"][i].score) for i in ids}
        score, _ = combined(ratings, plan.axis_weights, ids)
        by_id = dict(zip(ids, score))
        shown, clusters = [], set()
        for i in sorted(ids, key=lambda i: -by_id[i]):          # best first, one per cluster
            c = hyps[i].cluster
            if c is not None and c in clusters:
                continue
            clusters.add(c)
            h = hyps[i]
            shown.append({"id": i, "text": h.text, "record": h.record.model_dump() if h.record else None,
                          "ratings": {ax: ratings[ax][i].model_dump() for ax in AXES},
                          "provenance": h.provenance.model_dump(), "parents": h.parents,
                          "reviews": [r.model_dump() for r in h.reviews],
                          "matches": sum(1 for m in state.get("matches", []) if i in (m.a, m.b))})
            if len(shown) >= ctx.cfg.report_size:
                break
        return {"report": {"front": pareto_front(points), "shown": shown, "cycles": state.get("cycle", 0),
                           "tokens": ctx.tracer.summary()}}
    return report

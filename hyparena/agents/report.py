"""report: Pareto front over the two axes, a diversified list of the best hypotheses, and a research
overview written from them (the Meta-review agent's final output in Co-Scientist)."""
from __future__ import annotations

from hyparena.rating import combined
from hyparena.state import GraphState, usable


def pareto_front(points: dict[str, tuple[float, ...]]) -> list[str]:
    """Ids not dominated on all criteria at once (any number of criteria)."""
    def dominates(a, b):
        return all(x >= y for x, y in zip(a, b)) and any(x > y for x, y in zip(a, b))
    return [h for h, p in points.items() if not any(dominates(q, p) for g, q in points.items() if g != h)]


def make_report(ctx):
    def report(state: GraphState) -> dict:
        hyps, ratings, plan = state.get("hypotheses", {}), state.get("ratings", {}), state["plan"]
        names = plan.names
        # Created but never evaluated (for example by evolution in a cycle after which the run stopped early).
        pending = [h.id for h in hyps.values() if h.status in ("new", "normalized")
                   or (h.status == "active" and names and h.id not in ratings.get(names[0], {}))]
        first = ratings.get(names[0], {}) if names else {}
        ids = [h.id for h in hyps.values() if h.status == "active" and first.get(h.id)]
        if not ids:
            return {"report": {"front": [], "shown": [], "pending": pending, "overview": "",
                               "tokens": ctx.tracer.summary()}}
        points = {i: tuple(ratings[c][i].score for c in names) for i in ids}
        score, _ = combined(ratings, plan.weights, ids)
        by_id = dict(zip(ids, score))
        shown, clusters = [], set()
        for i in sorted(ids, key=lambda i: -by_id[i]):          # best first, one per cluster
            c = hyps[i].cluster
            if c is not None and c in clusters:
                continue
            clusters.add(c)
            h = hyps[i]
            shown.append({"id": i, "text": h.text, "card": h.card.model_dump() if h.card else None,
                          "combined": float(by_id[i]),
                          "ratings": {c: ratings[c][i].model_dump() for c in names},
                          "evidence": [e.model_dump() for e in usable(h.evidence)],
                          "retracted_evidence": [e.record_id for e in h.evidence if not e.usable],
                          "provenance": h.provenance.model_dump(), "parents": h.parents,
                          "reviews": [r.model_dump() for r in h.reviews],
                          "matches": sum(1 for m in state.get("matches", []) if i in (m.a, m.b))})
            if len(shown) >= ctx.cfg.report_size:
                break
        reply, prov = ctx.call(
            role="research_overview", family=ctx.utility_family(), template="research_overview",
            version="v2", phase="meta",
            variables={"goal": state["goal"], "plan": plan,
                       "items": [{"id": s["id"], "text": s["text"][:3000],
                                  "scores": {c: round(s["ratings"][c]["score"], 2) for c in names},
                                  "evidence": [f"{e['record_id']} ({e['publication_date']}): {e['title']}"
                                               for e in s["evidence"][:5]]} for s in shown]})
        return {"report": {"front": pareto_front(points), "shown": shown, "pending": pending,
                           "cycles": state.get("cycle", 0),
                           "overview": reply.text.strip(), "overview_provenance": prov.model_dump(),
                           "tokens": ctx.tracer.summary()}}
    return report

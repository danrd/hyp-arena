"""retrieve: literature evidence per hypothesis, before review and ranking.

Queries come from the card (the normalizer's suggestions; the claim as a fallback). Results respect
RunConfig.as_of. Evidence is attached to the hypothesis and read by reviewers and judges."""
from __future__ import annotations

from hyparena.state import GraphState, Hypothesis


def make_retrieve(ctx):
    cfg = ctx.cfg

    def queries(h: Hypothesis) -> list[str]:
        qs = list(h.card.search_queries) if h.card else []
        if not qs:
            qs = [(h.card.get("claim") if h.card else "") or h.text.split("\n", 1)[0]]
        return [q[:300] for q in qs if q.strip()]

    def one(h: Hypothesis) -> Hypothesis:
        seen, found = set(), []
        with ctx.tracer.span("retrieve", "search"):
            for q in queries(h):
                for ev in ctx.search.search(q, limit=cfg.evidence_per_query, as_of=cfg.as_of):
                    key = (ev.source, ev.record_id)
                    if key not in seen:
                        seen.add(key)
                        found.append(ev)
        ctx.log.write({"event": "retrieved", "id": h.id, "n": len(found), "as_of": cfg.as_of,
                       "queries": queries(h)})
        return h.model_copy(update={"evidence": found[: cfg.evidence_max]})

    def retrieve(state: GraphState) -> dict:
        todo = [h for h in state.get("hypotheses", {}).values() if h.status == "normalized" and not h.evidence]
        return {"hypotheses": {h.id: h for h in ctx.map(one, todo)}}
    return retrieve

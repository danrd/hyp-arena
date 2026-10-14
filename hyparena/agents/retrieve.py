"""retrieve: literature evidence per hypothesis, before review and ranking.

Queries come from the card (the normalizer's suggestions; the claim as a fallback). Results respect
RunConfig.as_of. Retracted records (Retraction Watch, as known at as_of) are kept for audit but flagged,
and reviewers and judges see only usable evidence."""
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
        if ctx.retractions is not None:
            found = ctx.retractions.mark(found, cfg.as_of)
        found = [e for e in found if e.usable][: cfg.evidence_max] + [e for e in found if not e.usable]
        ctx.log.write({"event": "retrieved", "id": h.id, "n": len(found), "as_of": cfg.as_of,
                       "retracted": [e.record_id for e in found if not e.usable],
                       "by_source": {s: sum(1 for e in found if e.source == s) for s in {e.source for e in found}},
                       "queries": queries(h)})
        return h.model_copy(update={"evidence": found})

    def retrieve(state: GraphState) -> dict:
        todo = [h for h in state.get("hypotheses", {}).values() if h.status == "normalized" and not h.evidence]
        return {"hypotheses": {h.id: h for h in ctx.map(one, todo)}}
    return retrieve

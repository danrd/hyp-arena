"""evolve: new hypotheses from the top of the ranking. Parents are never changed."""
from __future__ import annotations

from hyparena.agents.generate import next_id
from hyparena.rating import combined
from hyparena.state import GraphState, Hypothesis

STRATEGIES = ("feasibility", "combination", "inspiration", "simplification", "divergent")
PARENTS = {"feasibility": 1, "simplification": 1, "combination": 2, "inspiration": 2, "divergent": 2}


def make_evolve(ctx):
    def evolve(state: GraphState) -> dict:
        hyps, plan = state["hypotheses"], state["plan"]
        ids = [h.id for h in hyps.values() if h.status == "active"]
        if len(ids) < 2 or not state.get("ratings"):
            return {}
        score, _ = combined(state["ratings"], plan.axis_weights, ids)
        top = [ids[i] for i in sorted(range(len(ids)), key=lambda i: -score[i])[:6]]
        new: dict[str, Hypothesis] = {}
        for _ in range(ctx.cfg.evolve_per_cycle):
            strategy = ctx.rotate("evolve_strategy", list(STRATEGIES))
            parents = ctx.rng.sample(top, min(PARENTS[strategy], len(top)))
            family = ctx.rotate("generate_family", ctx.generator_families)
            reply, prov = ctx.call(
                role="evolve", family=family, template="evolve", version="v1", phase="evolve",
                strategy=strategy,
                variables={"goal": state["goal"], "strategy": strategy,
                           "parents": [hyps[p] for p in parents],
                           "feedback": state.get("feedback", {})})
            hid = next_id(state, len(new))
            new[hid] = Hypothesis(id=hid, text=reply.text.strip(), provenance=prov, parents=parents)
        return {"hypotheses": new}
    return evolve

"""generate: new hypotheses as free-form text, one strategy and one generator family per hypothesis."""
from __future__ import annotations

from hyparena.state import GraphState, Hypothesis

STRATEGIES = ("literature", "debate", "assumptions", "expansion")


def next_id(state: GraphState, offset: int = 0) -> str:
    return f"h{len(state.get('hypotheses', {})) + offset + 1:04d}"


def make_generate(ctx):
    def generate(state: GraphState) -> dict:
        new: dict[str, Hypothesis] = {}
        plan, goal = state["plan"], state["goal"]
        known_titles = [h.text[:80] for h in state.get("hypotheses", {}).values()][:20]
        for _ in range(ctx.cfg.gen_per_cycle):
            family = ctx.rotate("generate_family", ctx.generator_families)
            strategy = ctx.rotate("generate_strategy", list(STRATEGIES))
            passages = ctx.search.search(goal) if strategy == "literature" else []
            reply, prov = ctx.call(
                role="generate", family=family, template="generate", version="v1", phase="generate",
                strategy=strategy,
                variables={"goal": goal, "plan": plan, "strategy": strategy, "passages": passages,
                           "known_titles": known_titles, "feedback": state.get("feedback", {})})
            hid = next_id(state, len(new))
            new[hid] = Hypothesis(id=hid, text=reply.text.strip(), provenance=prov)
        return {"hypotheses": new}
    return generate

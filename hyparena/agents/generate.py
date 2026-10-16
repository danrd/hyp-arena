"""generate: new hypotheses as free-form text, one strategy and one generator family per hypothesis."""
from __future__ import annotations

from hyparena.state import GraphState, Hypothesis, usable

STRATEGIES = ("literature", "debate", "assumptions", "expansion")


def next_id(state: GraphState, offset: int = 0) -> str:
    return f"h{len(state.get('hypotheses', {})) + offset + 1:04d}"


def make_generate(ctx):
    def generate(state: GraphState) -> dict:
        if ctx.cfg.gen_cycles and state.get("cycle", 0) > ctx.cfg.gen_cycles:
            return {}
        plan, goal = state["plan"], state["goal"]
        known_titles = [h.text.split("\n", 1)[0][:100] for h in state.get("hypotheses", {}).values()][:30]
        # Assignments are fixed here, in order, so the parallel calls below do not change them.
        tasks = [(next_id(state, i), ctx.rotate("generate_family", ctx.generator_families),
                  ctx.rotate("generate_strategy", list(STRATEGIES))) for i in range(ctx.cfg.gen_per_cycle)]

        def one(task) -> Hypothesis:
            hid, family, strategy = task
            passages = usable(ctx.search.search(goal, limit=ctx.cfg.evidence_per_query, as_of=ctx.cfg.as_of)) if strategy == "literature" else []
            reply, prov = ctx.call(
                role="generate", family=family, template="generate", version="v3", phase="generate",
                strategy=strategy,
                variables={"goal": goal, "plan": plan, "strategy": strategy, "passages": passages,
                           "known_titles": known_titles, "feedback": state.get("feedback", {})})
            return Hypothesis(id=hid, text=reply.text.strip(), provenance=prov)

        made = [h for h in ctx.map(one, tasks) if h.text]
        return {"hypotheses": {h.id: h for h in made}}
    return generate

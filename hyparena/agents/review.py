"""review: initial -> full (with search) -> deep verification. Survivors become `active`."""
from __future__ import annotations

from hyparena.llm.structured import ask_json
from hyparena.state import GraphState, Hypothesis, Review

SCORE_KEYS = ("correctness", "novelty", "quality")


def _numbers(value: dict) -> list[str]:
    return [f"`{k}` must be a number from 0 to 10." for k in SCORE_KEYS
            if not isinstance(value.get(k), (int, float))]


def _deep_validate(value: dict) -> list[str]:
    return [] if isinstance(value.get("fundamental_flaw"), bool) else ["`fundamental_flaw` must be true or false."]


def make_review(ctx):
    cfg = ctx.cfg

    def reviewer(h: Hypothesis) -> str:
        """Next reviewer family, never the writer's (reviews are read by the judges)."""
        others = [f for f in ctx.generator_families if f != h.provenance.family]
        return ctx.rotate("reviewer", others or ctx.generator_families)

    def review_one(h: Hypothesis, state: GraphState) -> Hypothesis:
        common = {"goal": state["goal"], "plan": state["plan"], "text": h.text,
                  "feedback": state.get("feedback", {})}
        reviews: list[Review] = []

        def reject():
            return h.model_copy(update={"reviews": reviews, "status": "rejected"})

        init = ask_json(ctx, role="review_initial", family=reviewer(h), template="review_initial",
                        version="v1", variables=common, phase="review", validate=_numbers)
        if init.value is None:
            return reject()
        s = init.value
        passed = s.get("safety_ok", True) is not False and s["correctness"] >= cfg.min_correctness
        reviews.append(Review(kind="initial", provenance=init.provenance, passed=passed,
                              scores={k: float(s[k]) for k in SCORE_KEYS},
                              notes=[str(n) for n in s.get("notes", [])]))
        if not passed:
            return reject()

        query = (h.record.claim if h.record and h.record.claim else h.text)[:300]
        full = ask_json(ctx, role="review_full", family=reviewer(h), template="review_full",
                        version="v1", variables={**common, "passages": ctx.search.search(query)},
                        phase="review", validate=_numbers)
        if full.value is None:
            return reject()
        s = full.value
        passed = s["correctness"] >= cfg.min_correctness and s["novelty"] >= cfg.min_novelty
        reviews.append(Review(kind="full", provenance=full.provenance, passed=passed,
                              scores={k: float(s[k]) for k in SCORE_KEYS},
                              notes=[str(n) for n in s.get("notes", [])],
                              citations=[str(c) for c in s.get("citations", [])]))
        if not passed:
            return reject()

        deep = ask_json(ctx, role="review_deep", family=reviewer(h), template="review_deep",
                        version="v1", variables={"text": h.text}, phase="review",
                        validate=_deep_validate)
        flawed = bool(deep.value and deep.value.get("fundamental_flaw"))
        if deep.value is not None:
            reviews.append(Review(kind="deep", provenance=deep.provenance, passed=not flawed,
                                  notes=[str(n) for n in deep.value.get("notes", [])]))
        return h.model_copy(update={"reviews": reviews, "status": "rejected" if flawed else "active"})

    def review(state: GraphState) -> dict:
        todo = [h for h in state.get("hypotheses", {}).values() if h.status == "normalized"]
        return {"hypotheses": {h.id: review_one(h, state) for h in todo}}   # sequential for now
    return review

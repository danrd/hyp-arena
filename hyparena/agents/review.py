"""review: initial -> full (against the retrieved evidence) -> deep verification. Survivors become `active`.

Reviewers never come from the writer's family, also when the client falls back to another family:
the reviews are read by the judges."""
from __future__ import annotations

from hyparena.llm.structured import ask_json
from hyparena.state import GraphState, Hypothesis, Review, usable

SCORE_KEYS = ("correctness", "novelty", "quality")


def _numbers(value: dict) -> list[str]:
    return [f"`{k}` must be a number from 0 to 10." for k in SCORE_KEYS
            if not isinstance(value.get(k), (int, float))]


def _deep_validate(value: dict) -> list[str]:
    return [] if isinstance(value.get("fundamental_flaw"), bool) else ["`fundamental_flaw` must be true or false."]


def make_review(ctx):
    cfg = ctx.cfg

    def reviewers(h: Hypothesis) -> list[str]:
        """The three reviewer families for `h`, assigned in order before the parallel work starts."""
        others = [f for f in ctx.generator_families if f != h.provenance.family] or ctx.generator_families
        return [ctx.rotate("reviewer", others) for _ in range(3)]

    def review_one(task) -> Hypothesis:
        h, state, (fam_initial, fam_full, fam_deep) = task
        avoid = (h.provenance.family,)
        common = {"goal": state["goal"], "plan": state["plan"], "text": h.text,
                  "feedback": state.get("feedback", {})}
        reviews: list[Review] = []

        def reject():
            return h.model_copy(update={"reviews": reviews, "status": "rejected"})

        init = ask_json(ctx, role="review_initial", family=fam_initial, template="review_initial",
                        version="v1", variables=common, phase="review", validate=_numbers, avoid=avoid)
        if init.value is None:
            return reject()
        s = init.value
        passed = s.get("safety_ok", True) is not False and s["correctness"] >= cfg.min_correctness
        reviews.append(Review(kind="initial", provenance=init.provenance, passed=passed,
                              scores={k: float(s[k]) for k in SCORE_KEYS},
                              notes=[str(n) for n in s.get("notes", [])]))
        if not passed:
            return reject()

        evidence = usable(h.evidence)
        full = ask_json(ctx, role="review_full", family=fam_full, template="review_full", version="v3",
                        variables={**common, "evidence": evidence, "as_of": cfg.as_of}, phase="review",
                        validate=_numbers, avoid=avoid)
        if full.value is None:
            return reject()
        s = full.value
        # novelty is judged against the retrieved evidence, so without evidence it cannot reject
        passed = s["correctness"] >= cfg.min_correctness and (not evidence or s["novelty"] >= cfg.min_novelty)
        reviews.append(Review(kind="full", provenance=full.provenance, passed=passed,
                              scores={k: float(s[k]) for k in SCORE_KEYS},
                              notes=[str(n) for n in s.get("notes", [])],
                              citations=[str(c) for c in s.get("citations", [])]))
        if not passed:
            return reject()

        deep = ask_json(ctx, role="review_deep", family=fam_deep, template="review_deep", version="v1",
                        variables={"text": h.text}, phase="review", validate=_deep_validate, avoid=avoid)
        flawed = bool(deep.value and deep.value.get("fundamental_flaw"))
        if deep.value is not None:
            reviews.append(Review(kind="deep", provenance=deep.provenance, passed=not flawed,
                                  notes=[str(n) for n in deep.value.get("notes", [])]))
        return h.model_copy(update={"reviews": reviews, "status": "rejected" if flawed else "active"})

    def review(state: GraphState) -> dict:
        todo = [(h, state, reviewers(h)) for h in state.get("hypotheses", {}).values()
                if h.status == "normalized"]
        return {"hypotheses": {h.id: h for h in ctx.map(review_one, todo)}}
    return review

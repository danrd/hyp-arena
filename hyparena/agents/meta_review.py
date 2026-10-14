"""meta_review: summarize recurring review and judging patterns into feedback for the next cycle."""
from __future__ import annotations

from collections import Counter

from hyparena.llm.structured import ask_json
from hyparena.state import GraphState

AGENTS = ("generate", "review", "compare", "evolve")


def _validate(value: dict) -> list[str]:
    return [f"`{k}` must be a string." for k in AGENTS if not isinstance(value.get(k), str)]


def make_meta_review(ctx):
    def meta_review(state: GraphState) -> dict:
        notes = Counter(n for h in state.get("hypotheses", {}).values() for r in h.reviews for n in r.notes)
        rationales = [v.rationale for m in state.get("matches", [])[-20:] for v in m.judges if v.rationale]
        if not notes and not rationales:
            return {}
        out = ask_json(ctx, role="meta_review", family=ctx.utility_family(), template="meta_review",
                       version="v1", phase="meta", validate=_validate,
                       variables={"goal": state["goal"],
                                  "review_notes": [n for n, _ in notes.most_common(15)],
                                  "rationales": rationales[:15]})
        if out.value is None:
            return {}
        return {"feedback": {k: out.value[k] for k in AGENTS if isinstance(out.value.get(k), str)}}
    return meta_review

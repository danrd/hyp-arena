"""parse_goal: research goal (free text) -> plan configuration."""
from __future__ import annotations

from hyparena.llm.structured import ask_json
from hyparena.state import GraphState, PlanConfig


def _validate(value: dict) -> list[str]:
    notes = []
    if not isinstance(value.get("preferences"), str):
        notes.append("`preferences` must be a string.")
    for key in ("attributes", "constraints"):
        if not isinstance(value.get(key), list):
            notes.append(f"`{key}` must be a list.")
    return notes


def make_parse_goal(ctx):
    def parse_goal(state: GraphState) -> dict:
        out = ask_json(ctx, role="parse_goal", family=ctx.utility_family(), template="parse_goal",
                       version="v1", variables={"goal": state["goal"]}, phase="other",
                       validate=_validate)
        criteria = {"criteria": ctx.criteria.criteria, "criteria_version": ctx.criteria.version,
                    "importance": ctx.criteria.importance}
        if out.value is None:
            return {"plan": PlanConfig(preferences=state["goal"], **criteria)}
        v = out.value
        return {"plan": PlanConfig(preferences=str(v.get("preferences", "")),
                                   attributes=[str(a) for a in v.get("attributes", []) or []],
                                   constraints=[str(c) for c in v.get("constraints", []) or []],
                                   **criteria)}
    return parse_goal

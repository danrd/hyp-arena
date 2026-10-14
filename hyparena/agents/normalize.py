"""normalize: free text -> structured record. The original text is kept; gaps are listed."""
from __future__ import annotations

from hyparena.llm.structured import ask_json
from hyparena.state import GraphState, NormalizedRecord

REQUIRED = ("claim", "mechanism", "prediction", "experiment", "falsification")


def _validate(value: dict) -> list[str]:
    return [f"The field `{k}` is empty; fill it only if the text states it."
            for k in REQUIRED if not str(value.get(k, "")).strip()]


def make_normalize(ctx):
    def normalize(state: GraphState) -> dict:
        updated = {}
        for h in state.get("hypotheses", {}).values():
            if h.status != "new":
                continue
            out = ask_json(ctx, role="normalize", family=ctx.utility_family(), template="normalize",
                           version="v1", variables={"text": h.text}, phase="normalize",
                           validate=_validate, rounds=ctx.cfg.normalize_rounds)
            v = out.value or {}
            record = NormalizedRecord(
                **{k: str(v.get(k, "")) for k in
                   ("claim", "mechanism", "prediction", "experiment", "falsification", "known")},
                assumptions=[str(a) for a in v.get("assumptions", []) or []],
                gaps=[k for k in REQUIRED if not str(v.get(k, "")).strip()])
            updated[h.id] = h.model_copy(update={"record": record, "status": "normalized"})
        return {"hypotheses": updated}
    return normalize

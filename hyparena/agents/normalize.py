"""normalize: free text -> hypothesis card (schema from configs/card.yaml). The text is kept; nothing is
invented: unstated required fields are listed in `gaps`. Also asks for literature search queries."""
from __future__ import annotations

from hyparena.llm.structured import ask_json
from hyparena.state import Card, GraphState, Hypothesis


def make_normalize(ctx):
    schema = ctx.card_schema

    def validate(value: dict) -> list[str]:
        notes = [f"The field `{k}` is missing or empty; fill it if the text states it, otherwise leave it empty."
                 for k in schema.required if value.get(k) in (None, "", [])]
        if not isinstance(value.get("search_queries"), list) or not value.get("search_queries"):
            notes.append("`search_queries` must be a non-empty list of short keyword queries.")
        return notes

    def one(task) -> Hypothesis:
        h, family = task
        out = ask_json(ctx, role="normalize", family=family, template="normalize", version="v2",
                       variables={"text": h.text, "schema": schema,
                                  "example": schema.example_json({"search_queries": []})},
                       phase="normalize", validate=validate, rounds=ctx.cfg.normalize_rounds)
        v = out.value or {}
        fields = {}
        for f in schema.fields:
            raw = v.get(f.name)
            if f.type == "list":
                fields[f.name] = [str(x) for x in raw] if isinstance(raw, list) else ([str(raw)] if raw else [])
            else:
                fields[f.name] = str(raw) if raw not in (None, []) else ""
        card = Card(schema_version=schema.version, fields=fields,
                    gaps=[k for k in schema.required if fields.get(k) in ("", [])],
                    search_queries=[str(q) for q in v.get("search_queries", []) or []][:4])
        return h.model_copy(update={"card": card, "status": "normalized"})

    def normalize(state: GraphState) -> dict:
        todo = [(h, ctx.utility_family()) for h in state.get("hypotheses", {}).values() if h.status == "new"]
        return {"hypotheses": {h.id: h for h in ctx.map(one, todo)}}
    return normalize

"""Structured replies: ask for JSON, validate it, and ask again with the reasons when it is wrong.

Built on agent_kit.refine.loop. Templates receive `history_text` (the earlier answers and why they
were not accepted) and are expected to show it when it is not empty."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Optional

from agent_kit.refine import RefineResult, loop

from hyparena.state import Provenance


def parse_json(text: str) -> Optional[dict]:
    """The last JSON object in the text (a debate transcript may precede it), or None."""
    decoder = json.JSONDecoder()
    starts = [i for i, ch in enumerate(text) if ch == "{"]
    for start in reversed(starts):
        try:
            value, _ = decoder.raw_decode(text[start:])
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None


@dataclass
class Structured:
    value: Optional[dict]
    provenance: Optional[Provenance]
    result: RefineResult

    @property
    def ok(self) -> bool:
        return self.value is not None and self.result.accepted


def ask_json(ctx, *, role: str, family: str, template: str, version: str, variables: dict[str, Any],
             phase: str, validate: Callable[[dict], list[str]], rounds: int = 2,
             strategy: str = "", avoid: tuple[str, ...] = ()) -> Structured:
    """Call, parse as JSON, validate; on complaints ask again with them. Returns the best attempt
    (a value that reads, then the fewest complaints) together with the provenance of that call."""
    calls: list[Provenance] = []

    def ask(call: dict[str, Any]) -> str:
        reply, prov = ctx.call(role=role, family=family, template=template, version=version,
                               variables={**variables, "history_text": call.get("history_text", "")},
                               phase=phase, strategy=strategy, avoid=avoid)
        calls.append(prov)
        return reply.text

    def review(_task, value):
        if value is None:
            return ["The reply did not contain a valid JSON object."], 1, 0
        notes = validate(value)
        return notes, len(notes), 0

    result = loop(None, ask, review, parse_json, rounds=rounds)
    best = result.best
    provenance = calls[best.number - 1] if best is not None and best.number <= len(calls) else None
    return Structured(value=best.value if best is not None else None, provenance=provenance,
                      result=result)

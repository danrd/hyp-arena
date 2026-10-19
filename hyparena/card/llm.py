"""One structured LLM call: render a template, parse the JSON, validate it, and ask again with the reasons
when it does not pass (at most `rounds` attempts). Every attempt is appended to `log` when given."""
from __future__ import annotations

import json
import time
from typing import Callable, Optional

from hyparena.llm.prompts import render
from hyparena.llm.structured import parse_json


def parse_fullest(text: str) -> Optional[dict]:
    """The top-level JSON object with the most keys (a reply may add a second, partial object after the
    answer; taking the last one would lose the answer)."""
    decoder, found, i = json.JSONDecoder(), [], text.find("{")
    while i >= 0:
        try:
            value, end = decoder.raw_decode(text, i)
        except ValueError:
            i = text.find("{", i + 1)
            continue
        if isinstance(value, dict):
            found.append(value)
        i = text.find("{", end)
    return max(found, key=len) if found else None


def ask(client, *, role: str, family: str, template: str, version: str, variables: dict,
        validate: Optional[Callable[[dict], list[str]]] = None, rounds: int = 2, avoid=frozenset(),
        log: Optional[list] = None) -> tuple[Optional[dict], str]:
    """(value, family that answered); value is None if no attempt produced valid JSON. The last parsed value
    is returned even when it still has problems; callers re-check what matters to them."""
    history, best, fam = "", None, family
    for attempt in range(rounds):
        prompt = render(template, version, **variables, history_text=history)
        started = time.time()
        reply = client.call(role=role, family=family, prompt=prompt, avoid=frozenset(avoid))
        value = parse_fullest(reply.text)
        problems = ["The reply did not contain a valid JSON object."] if value is None else (validate(value) if validate else [])
        if log is not None:
            log.append({"kind": "llm", "role": role, "template": f"{template}/{version}", "attempt": attempt + 1,
                        "asked_family": family, "family": reply.family, "model": reply.model_id,
                        "seconds": round(time.time() - started, 1), "tokens_in": reply.tokens_in,
                        "tokens_out": reply.tokens_out, "prompt": prompt, "reply": reply.text, "error": reply.error,
                        "problems": problems})
        if value is not None:
            best, fam = value, reply.family
        if value is not None and not problems:
            return value, fam
        history = ("Your previous answer was not accepted:\n" + reply.text[:3000] +
                   "\n\nProblems:\n- " + "\n- ".join(problems[:12]) + "\n\nReply again with the corrected JSON object only.")
    return best, fam


def dumps(x) -> str:
    return json.dumps(x, ensure_ascii=False)

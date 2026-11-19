"""Check proposed synonym admission on synthetic controls, without an LLM."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json


def key(a: str, b: str) -> frozenset[str]:
    return frozenset((" ".join(a.casefold().split()), " ".join(b.casefold().split())))


@dataclass(frozen=True)
class Example:
    name: str
    target: str
    measured: str
    proposed: str
    direction: str
    expected: bool
    article: str = "comparison-a"
    same_contrast: bool = True
    valid_quote: bool = True


def admit(row: Example, aliases: set, local_definitions: dict, *, expanded: bool) -> str | None:
    if not row.valid_quote or not row.same_contrast:
        return None
    pair = key(row.target, row.measured)
    literal = len(pair) == 1
    verified_expansion = expanded and (
        (row.proposed == "exact_alias" and pair in aliases)
        or (row.proposed == "defined_here" and pair in local_definitions.get(row.article, set()))
    )
    return row.direction if literal or verified_expansion else None


def check():
    aliases = {key("gait speed", "walking speed")}
    local = {"comparison-a": {key("percentage reepithelialization", "percentage reduction in wound area")}}
    examples = [
        Example("literal-benefit", "gait speed", "gait speed", "exact_alias", "benefit", True),
        Example("literal-null", "gait speed", "gait speed", "exact_alias", "null", True),
        Example("literal-harm", "gait speed", "gait speed", "exact_alias", "harm", True),
        Example("alias-benefit", "gait speed", "walking speed", "exact_alias", "benefit", True),
        Example("alias-null", "gait speed", "walking speed", "exact_alias", "null", True),
        Example("alias-harm", "gait speed", "walking speed", "exact_alias", "harm", True),
        Example("alias-reversed", "walking speed", "gait speed", "exact_alias", "null", True),
        Example("local-defined", "percentage reepithelialization", "percentage reduction in wound area",
                "defined_here", "benefit", True),
        Example("local-reversed", "percentage reduction in wound area", "percentage reepithelialization",
                "defined_here", "harm", True),
        Example("different-paper", "percentage reepithelialization", "percentage reduction in wound area",
                "defined_here", "benefit", False, article="comparison-b"),
        Example("unverified-global-alias", "percentage reepithelialization", "percentage reduction in wound area",
                "exact_alias", "benefit", False),
        Example("another-contrast", "gait speed", "walking speed", "exact_alias", "benefit", False, same_contrast=False),
        Example("same-name-another-contrast", "gait speed", "gait speed", "exact_alias", "null", False, same_contrast=False),
        Example("unverified-quote", "gait speed", "walking speed", "exact_alias", "benefit", False, valid_quote=False),
        Example("adjacent", "gait speed", "grip strength", "exact_alias", "benefit", False),
        Example("surrogate", "verbal recall", "serum IL-6", "exact_alias", "harm", False),
        Example("component", "physical performance composite", "walking speed", "narrower", "benefit", False),
        Example("composite", "walking speed", "physical performance composite", "broader", "benefit", False),
        Example("time-to-close", "time to closure", "percentage reduction in wound area", "related", "benefit", False),
        Example("unsure", "functional outcome", "performance index", "unknown", "null", False),
    ]
    stats = {}
    for expanded in (False, True):
        counts = Counter()
        for row in examples:
            result = admit(row, aliases, local, expanded=expanded)
            if expanded:
                assert (result is not None) == row.expected, row
            if result is not None:
                assert row.direction == result
                counts[result] += 1
                counts["false_accept"] += not row.expected
            elif row.expected:
                counts["miss"] += 1
        stats["verified_expansion" if expanded else "literal"] = dict(counts)
    return {"controls": len(examples), "eligible": sum(row.expected for row in examples), "results": stats}


if __name__ == "__main__":
    print(json.dumps(check(), indent=2))

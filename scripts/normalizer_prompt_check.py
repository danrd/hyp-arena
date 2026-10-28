"""Check of a normalizer prompt rule: v5 (current) against v6 (names and bracketed descriptors) on the telegraphic texts of L1.9.

    ALLOW_PAID=1 python -m scripts.normalizer_prompt_check run --out runs/stage5/prompt_check     # 75 normalizer calls
    python -m scripts.normalizer_prompt_check report --dir runs/stage5/prompt_check

Arms (the normalizer is the google family of configs/v2-flash.yaml; the dose/age canonicalization and the abbreviation table are on in all arms):
  T, v5 twice and T, v6 twice: the 15 telegraphic texts (data/validation/l1_9_texts.json, field T);
  O, v6 once: the 15 original texts (field O_full), against the saved original cards O1 and O2 of L1.8 (v5) as the reference.
Measures per run of T (reference: the main claim of the saved original card O1): unresolved compounds (fewer is better), cards whose first claim is the
outcome claim, cards with the same number of claims as the reference, and agreement with the reference on subject, relation, object and context of
the outcome claim. Adoption rule (fixed before the run, see docs/rules-method.md): for both repeats v6 is not worse than the v5 repeat on any of the
four counts or the mean facet agreement, the sum of items gained over the two repeats on (outcome-first + same claim count + subject agreement) is at least 2,
and on the original texts v6 agrees with O1 on every facet not below the agreement of O2 with O1 minus 0.05."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from hyparena.card.canonical import canonicalize
from hyparena.card.models import HypothesisCard

TEXTS = Path("data/validation/l1_9_texts.json")
L18 = "runs/stage5/l1_8"
FACETS = ("subject", "relation", "object", "context")


def _norm(v) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(v or "").lower())


def main_claim(card: dict) -> dict:
    return next((c for c in card["claims"] if c.get("role") == "outcome"), card["claims"][0])


def facets(card: dict) -> dict:
    c = main_claim(card)
    q = c.get("qualifiers") or {}
    return {"subject": _norm(c["subject"]["label"]), "relation": c["relation"], "object": _norm(c["object"]["label"]),
            "context": tuple(_norm(q.get(k)) for k in ("species", "strain", "sex", "dose", "age_at_start", "measure"))}


def measures(cards: list, ref: list[dict], unresolved: list[int] | None = None) -> dict:
    """`cards`: card dicts (None where normalization failed), `ref`: the reference cards, same order."""
    n = len(ref)
    out = {"n": n, "failed": sum(c is None for c in cards), "unresolved": sum(unresolved or [0]),
           "outcome_first": sum(1 for c in cards if c and c["claims"][0].get("role") == "outcome"),
           "same_claim_count": sum(1 for c, r in zip(cards, ref) if c and len(c["claims"]) == len(r["claims"]))}
    for f in FACETS:
        out[f"agree_{f}"] = sum(1 for c, r in zip(cards, ref) if c and facets(c)[f] == facets(r)[f])
    out["mean_facet_agreement"] = round(sum(out[f"agree_{f}"] for f in FACETS) / (len(FACETS) * n), 3)
    return out


def adopt(before: list[dict], after: list[dict], guard_after: dict, guard_repeat: dict) -> dict:
    """The adoption rule on the measures of the two v5 repeats, the two v6 repeats and the original-text guard (dicts of facet -> share)."""
    worse = []
    for b, a in zip(before, after):
        if a["unresolved"] > b["unresolved"]:
            worse.append("unresolved")
        for k in ("outcome_first", "same_claim_count", "mean_facet_agreement"):
            if a[k] < b[k]:
                worse.append(k)
    gain = sum((a[k] - b[k]) for b, a in zip(before, after) for k in ("outcome_first", "same_claim_count", "agree_subject"))
    guard = {f: guard_after[f] >= guard_repeat[f] - 0.05 for f in FACETS}
    ok = not worse and gain >= 2 and all(guard.values())
    return {"worse_on": sorted(set(worse)), "gain_items": gain, "guard": guard, "adopt": ok}


def _cards(client, version: str, texts: list[str], tag: str) -> list:
    from hyparena.card.normalizer import normalize
    out = []
    for i, t in enumerate(texts, start=1):
        card, _ = normalize(client, "google", t, f"H-{i:04d}", version=version)
        if card is not None:
            canonicalize(card)
        out.append(card.model_dump(mode="json") if card else None)
    return out


def cmd_run(out: str) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from hyparena.card.pipeline import _client
    d = json.loads(TEXTS.read_text())
    client, _ = _client("configs/v2-flash.yaml", False, 150)
    T = [r["T"] for r in d["items"]]
    O = [r["O_full"] for r in d["items"]]
    jobs = {"T_v5_a": ("v5", T), "T_v5_b": ("v5", T), "T_v6_a": ("v6", T), "T_v6_b": ("v6", T), "O_v6": ("v6", O)}
    Path(out).mkdir(parents=True, exist_ok=True)

    def one(name):
        version, texts = jobs[name]
        cards = _cards(client, version, texts, name)
        Path(out, f"{name}.json").write_text(json.dumps(cards, ensure_ascii=False, indent=1))
        return name

    with ThreadPoolExecutor(3) as pool:
        for name in pool.map(one, jobs):
            print(name, flush=True)
    print("calls", client.calls)


def _unresolved(cards: list) -> list[int]:
    from hyparena.card.entities import resolve_card
    return [len(resolve_card(HypothesisCard.model_validate(c))) if c else 0 for c in cards]


def _saved(name: str) -> list[dict]:
    out = []
    for x in json.loads(Path(L18, f"{name}.json").read_text())["items"]:
        c = HypothesisCard.model_validate(x["card"])
        canonicalize(c)
        out.append(c.model_dump(mode="json"))
    return out


def cmd_report(dirname: str) -> dict:
    load = lambda n: json.loads(Path(dirname, f"{n}.json").read_text())
    o1, o2 = _saved("O1"), _saved("O2")
    arms = {n: load(n) for n in ("T_v5_a", "T_v5_b", "T_v6_a", "T_v6_b")}
    m = {n: measures(c, o1, _unresolved(c)) for n, c in arms.items()}
    guard_after = measures(load("O_v6"), o1)
    guard_repeat = measures(o2, o1)
    share = lambda g: {f: g[f"agree_{f}"] / g["n"] for f in FACETS}
    out = {"measures": m, "guard_v6_vs_O1": share(guard_after), "repeat_O2_vs_O1": share(guard_repeat),
           "decision": adopt([m["T_v5_a"], m["T_v5_b"]], [m["T_v6_a"], m["T_v6_b"]], share(guard_after), share(guard_repeat))}
    print(json.dumps(out, indent=1))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--out", required=True)
    q = sub.add_parser("report")
    q.add_argument("--dir", required=True)
    a = ap.parse_args()
    cmd_run(a.out) if a.cmd == "run" else cmd_report(a.dir)


if __name__ == "__main__":
    main()

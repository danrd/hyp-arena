"""Second check of the normalizer prompt v6 against v5 with a refined measure, on 15 new ITP regimens.

    ALLOW_PAID=1 python -m scripts.normalizer_prompt_check2 texts     # 15 calls: telegraphic rewrites of 15 new regimens (deepseek)
    ALLOW_PAID=1 python -m scripts.normalizer_prompt_check2 run --out runs/stage5/prompt_check2     # about 105 normalizer calls
    python -m scripts.normalizer_prompt_check2 report --dir runs/stage5/prompt_check2

Why a second check (docs/rules-method.md, "Проверка правила в промпте нормализатора (v6)"): the first check measured the claim count against a reference card that itself
contained the bracketed-descriptor claim the rule forbids, and counted unresolved compounds on a run where a v5 card failed. Refined, declared before the run:
  * unresolved compounds as a rate over the cards that parsed (failed cards reported apart);
  * descriptor claims: cards with a non-outcome claim built on a bracketed descriptor of the text (fewer is better; independent of a reference card);
  * as before: first claim is the outcome claim, subject / relation / object / context agreement with the reference card of the original text.
Arms: T (the 15 telegraphic texts) with v5 twice and v6 twice; O (the original texts) with v5 twice (the reference and its repeat) and v6 once (the guard).
Adoption rule: in both repeats v6 is not worse than v5 by more than one card on any count measure (failed cards, descriptor-claim cards, first-claim-is-outcome, subject
agreement) and not worse by more than 0.02 on the unresolved rate and on the mean facet agreement; the items gained over the two repeats on (first-claim-is-outcome +
subject agreement + descriptor-claim cards avoided) are at least 3; and on the original texts v6 agrees with the reference on every facet not below the repeat of v5 minus 0.05.
Otherwise v6 is not adopted and TEMPLATE stays v5."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from scripts import normalizer_prompt_check as base
from scripts.style_check import PROMPT, STYLES

TEXTS = Path("data/validation/prompt2_texts.json")
FACETS = base.FACETS
ABBR_WORDS = {"ppm", "food", "diet", "feed", "water", "mo"}


def select(n: int = 15) -> list[dict]:
    """Ranked ITP regimens of distinct compounds not used in L1.8, L1.9, L1.10, ordered by a salted hash of the text."""
    labels = json.loads(Path("data/backtest/itp_2010-12-31_labels.json").read_text())
    used = {r["id"] for r in json.loads(Path("data/validation/l1_9_texts.json").read_text())["items"]}
    rows = []
    for half in ("dev", "test"):
        res = json.loads(Path(f"runs/stage4/itp2010_{half}.json").read_text())
        for pid, x in zip(res["meta"].get("ids") or [], res["items"]):
            if x["outcome"] == "ranked" and pid in labels and pid not in used:
                rows.append({"id": pid, "compound": labels[pid]["compound"], "O_full": x["text"], "O": x["text"].split("\n\n")[0].strip()})
    rows.sort(key=lambda r: hashlib.sha1(("prompt2:" + r["O_full"]).encode()).hexdigest())
    seen, out = set(), []
    for r in rows:
        k = re.sub(r"[^a-z0-9]+", "", r["compound"].lower())
        if k not in seen:
            seen.add(k)
            out.append(r)
        if len(out) == n:
            break
    return out


def descriptor_words(text: str) -> set[str]:
    return {w.lower() for b in re.findall(r"\(([^)]*)\)", text) for w in re.findall(r"[A-Za-z0-9]{3,}", b)} - ABBR_WORDS


def has_descriptor_claim(card: dict, text: str) -> bool:
    """A non-outcome claim whose span or object is built on a word of a bracketed descriptor of the text (class or target of the intervention)."""
    words = descriptor_words(text)
    if not words:
        return False
    for c in card["claims"]:
        if c.get("role") == "outcome":
            continue
        blob = f"{c.get('source_span', '')} {c['object']['label']}".lower()
        if any(w in blob for w in words):
            return True
    return False


def measures(cards: list, texts: list[str], ref: list[dict], unresolved: list[int]) -> dict:
    base_m = base.measures(cards, ref, unresolved)
    parsed = sum(c is not None for c in cards)
    base_m["unresolved_rate"] = round(base_m["unresolved"] / max(1, parsed), 3)
    base_m["descriptor_claim_cards"] = sum(1 for c, t in zip(cards, texts) if c and has_descriptor_claim(c, t))
    return base_m


def adopt(before: list[dict], after: list[dict], guard_after: dict, guard_repeat: dict) -> dict:
    worse = []
    gain = 0
    for b, a in zip(before, after):
        if a["failed"] > b["failed"] + 1:
            worse.append("failed")
        if a["descriptor_claim_cards"] > b["descriptor_claim_cards"] + 1:
            worse.append("descriptor_claim_cards")
        for k in ("outcome_first", "agree_subject"):
            if a[k] < b[k] - 1:
                worse.append(k)
        if a["unresolved_rate"] > b["unresolved_rate"] + 0.02:
            worse.append("unresolved_rate")
        if a["mean_facet_agreement"] < b["mean_facet_agreement"] - 0.02:
            worse.append("mean_facet_agreement")
        gain += (a["outcome_first"] - b["outcome_first"]) + (a["agree_subject"] - b["agree_subject"]) + (b["descriptor_claim_cards"] - a["descriptor_claim_cards"])
    guard = {f: guard_after[f] >= guard_repeat[f] - 0.05 for f in FACETS}
    return {"worse_on": sorted(set(worse)), "gain_items": gain, "guard": guard, "adopt": not worse and gain >= 3 and all(guard.values())}


def cmd_texts() -> None:
    from hyparena.card.pipeline import _client
    rows = select()
    client, _ = _client("configs/v2-flash.yaml", False, 30)
    for r in rows:
        reply = client.call(role="restyle", family="deepseek", prompt=PROMPT.format(style=STYLES["T"], text=r["O"]), avoid=frozenset())
        if reply.error or not reply.text.strip():
            raise SystemExit(f"restyle failed for {r['id']}: {reply.error}")
        r["T"] = reply.text.strip()
    TEXTS.write_text(json.dumps({"items": rows}, ensure_ascii=False, indent=1))
    print("calls", client.calls)


def cmd_run(out: str) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from hyparena.card.pipeline import _client
    rows = json.loads(TEXTS.read_text())["items"]
    client, _ = _client("configs/v2-flash.yaml", False, 200)
    T, O = [r["T"] for r in rows], [r["O_full"] for r in rows]
    jobs = {"T_v5_a": ("v5", T), "T_v5_b": ("v5", T), "T_v6_a": ("v6", T), "T_v6_b": ("v6", T),
            "O_v5_a": ("v5", O), "O_v5_b": ("v5", O), "O_v6": ("v6", O)}
    Path(out).mkdir(parents=True, exist_ok=True)

    def one(name):
        version, texts = jobs[name]
        Path(out, f"{name}.json").write_text(json.dumps(base._cards(client, version, texts, name), ensure_ascii=False, indent=1))
        return name

    with ThreadPoolExecutor(3) as pool:
        for name in pool.map(one, jobs):
            print(name, flush=True)
    print("calls", client.calls)


def cmd_report(dirname: str) -> dict:
    rows = json.loads(TEXTS.read_text())["items"]
    load = lambda n: json.loads(Path(dirname, f"{n}.json").read_text())
    ref, ref_rep = load("O_v5_a"), load("O_v5_b")
    texts_T = [r["T"] for r in rows]
    m = {n: measures(load(n), texts_T, ref, base._unresolved(load(n))) for n in ("T_v5_a", "T_v5_b", "T_v6_a", "T_v6_b")}
    share = lambda g: {f: g[f"agree_{f}"] / g["n"] for f in FACETS}
    out = {"measures": m, "guard_v6_vs_ref": share(base.measures(load("O_v6"), ref)), "repeat_v5_vs_ref": share(base.measures(ref_rep, ref)),
           "decision": adopt([m["T_v5_a"], m["T_v5_b"]], [m["T_v6_a"], m["T_v6_b"]], share(base.measures(load("O_v6"), ref)), share(base.measures(ref_rep, ref)))}
    print(json.dumps(out, indent=1))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("texts")
    r = sub.add_parser("run")
    r.add_argument("--out", required=True)
    q = sub.add_parser("report")
    q.add_argument("--dir", required=True)
    a = ap.parse_args()
    {"texts": cmd_texts, "run": lambda: cmd_run(a.out), "report": lambda: cmd_report(a.dir)}[a.cmd]()


if __name__ == "__main__":
    main()

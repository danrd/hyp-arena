"""Paired check of name dependence of the verifier: the same saved prompt with and without the compound's names.

    python -m scripts.blind_check plan   --runs runs/stage4/itp2010_dev.reapplied.json runs/stage4/itp2010_test.reapplied.json
    ALLOW_PAID=1 python -m scripts.blind_check run --runs ... --out runs/stage5/blind_itp2010.json --max-calls 140
    python -m scripts.blind_check report --in runs/stage5/blind_itp2010.json

The saved runs keep the exact prompt and reply of every verifier call. Arm O is that saved reply. Arm B asks the same
model the same prompt with every name of the intervention (the label, the PubChem title, the synonyms) replaced by one
code, so the model cannot recall the compound's result by name. Arm R asks the unchanged prompt again: the difference
between R and O is sampling noise, the difference between B and O is noise plus the effect of the names. Only the fields
the rules read are compared (which papers give a record, stance, effect, endpoint, quote role). Residual leaks that this
does not remove: a compound recognised from its mechanism, dose or strain, and names the table does not list."""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

CODE = "Compound-X"
FIELDS = ("stance", "effect", "endpoint", "quote_role")
GENERIC = {"acid", "extract", "oil", "diet", "food", "vitamin", "mouse", "mice"}


def target_names(prompt: str) -> list[str]:
    """Every name the code knows for the prompt's intervention: the labels in the prompt, the PubChem title and synonyms."""
    from hyparena.tools import compounds as cp
    labels = set()
    m = re.search(r"^Intervention: (.+?)(?: \(|\.\s|$)", prompt, re.M)
    if m:
        labels.add(m.group(1).strip())
    for m in re.finditer(r"^Claim \S+ \([a-z_]+\): (.+?) — ", prompt, re.M):
        labels.add(m.group(1).strip())
    names = set(labels)
    for lab in list(labels):
        for part in re.split(r" \+ | and ", lab):
            c = cp.lookup(part.strip())
            if c is not None:
                names |= {c.name, *c.synonyms}
    return sorted((n for n in names if len(n) >= 4 and n.lower() not in GENERIC), key=len, reverse=True)


def mask(prompt: str, names: list[str]) -> tuple[str, int]:
    """The prompt with every name (case-insensitive, whole token) replaced by one code; the number of replacements."""
    total = 0
    for n in names:
        prompt, k = re.subn(rf"(?<![A-Za-z0-9]){re.escape(n)}(?![A-Za-z0-9])", CODE, prompt, flags=re.I)
        total += k
    return prompt, total


def collect(runs: list[str]) -> list[dict]:
    from hyparena.card.verifier import parse_records
    out = []
    for p in runs:
        res = json.loads(Path(p).read_text())
        for i, c in enumerate(x for x in res["calls"] if x.get("role") == "verify_claim"):
            names = target_names(c["prompt"])
            masked, n = mask(c["prompt"], names)
            left = sum(len(re.findall(rf"(?<![A-Za-z0-9]){re.escape(x)}(?![A-Za-z0-9])", masked, flags=re.I)) for x in names)
            out.append({"run": Path(p).name, "n": i, "model": c["model"], "template": c["template"], "names": names,
                        "replaced": n, "left": left, "prompt": c["prompt"], "masked": masked,
                        "orig": (parse_records(c["reply"]) or {"records": []})["records"], "orig_reply": c["reply"]})
    return out


def _records(text: str) -> list[dict]:
    from hyparena.card.verifier import parse_records
    return (parse_records(text) or {"records": []})["records"]


def run(runs: list[str], out: str, config: str, max_calls: int, replay: bool = True) -> dict:
    from hyparena.card.pipeline import _client
    items = collect(runs)
    client, _ = _client(config, False, max_calls)

    def ask(prompt: str) -> str:
        return client.call(role="verify_claim", family="deepseek", prompt=prompt, avoid=frozenset()).text

    jobs = [("blind", it["masked"]) for it in items] + ([("replay", it["prompt"]) for it in items] if replay else [])
    with ThreadPoolExecutor(4) as pool:
        replies = list(pool.map(lambda j: ask(j[1]), jobs))
    for (arm, _), text in zip(jobs, replies):
        pass
    for k, it in enumerate(items):
        it["blind_reply"] = replies[k]
        it["blind"] = _records(replies[k])
        if replay:
            it["replay_reply"] = replies[len(items) + k]
            it["replay"] = _records(replies[len(items) + k])
    res = {"items": items, "calls": client.calls, "config": config, "model": items[0]["model"] if items else None}
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(res, ensure_ascii=False, indent=1))
    return res


def compare(a: list[list[dict]], b: list[list[dict]]) -> dict:
    """Agreement of two arms over paired calls: which papers give a record, and the fields on the papers both give."""
    same_set, both_empty, shared, agree = 0, 0, 0, Counter()
    for x, y in zip(a, b):
        px = {str(r.get("pmid")): r for r in x}
        py = {str(r.get("pmid")): r for r in y}
        same_set += set(px) == set(py)
        both_empty += not px and not py
        for p in set(px) & set(py):
            shared += 1
            for f in FIELDS:
                agree[f] += px[p].get(f) == py[p].get(f)
    n_union = sum(len({str(r.get("pmid")) for r in x} | {str(r.get("pmid")) for r in y}) for x, y in zip(a, b))
    n_inter = sum(len({str(r.get("pmid")) for r in x} & {str(r.get("pmid")) for r in y}) for x, y in zip(a, b))
    return {"calls": len(a), "same_paper_set": same_set, "both_empty": both_empty, "paper_overlap": f"{n_inter}/{n_union}",
            "shared_records": shared, **{f"{f}_agree": agree[f] for f in FIELDS}}


def report(path: str) -> dict:
    d = json.loads(Path(path).read_text())
    it = d["items"]
    O, B = [x["orig"] for x in it], [x["blind"] for x in it]
    R = [x.get("replay") for x in it] if it and "replay" in it[0] else None
    out = {"model": d["model"], "calls_paid": d["calls"], "pairs": len(it), "names_masked": sum(x["replaced"] for x in it),
           "names_left_in_masked_prompts": sum(x["left"] for x in it), "orig_records": sum(map(len, O)),
           "blind_vs_orig": compare(B, O)}
    if R:
        out["replay_vs_orig"] = compare(R, O)
        out["blind_vs_replay"] = compare(B, R)
    arms = {"orig": O, "blind": B, **({"replay": R} if R else {})}
    out["stance_counts"] = {k: dict(Counter(r.get("stance") for x in v for r in x)) for k, v in arms.items()}
    out["effect_counts"] = {k: dict(Counter(r.get("effect") for x in v for r in x)) for k, v in arms.items()}
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--runs", nargs="+", required=True)
    r = sub.add_parser("run")
    r.add_argument("--runs", nargs="+", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--config", default="configs/v2-flash.yaml")
    r.add_argument("--max-calls", type=int, default=140)
    r.add_argument("--no-replay", action="store_true")
    q = sub.add_parser("report")
    q.add_argument("--in", dest="inp", required=True)
    a = ap.parse_args()
    if a.cmd == "plan":
        items = collect(a.runs)
        print(f"{len(items)} saved verifier calls; paid calls for blind + replay arms: {2 * len(items)}")
        print(f"names replaced: {sum(x['replaced'] for x in items)}; names left in masked prompts: {sum(x['left'] for x in items)}; "
              f"prompts where nothing was replaced: {sum(1 for x in items if x['replaced'] == 0)}")
        print(f"calls with a non-empty saved reply: {sum(1 for x in items if x['orig'])} ({sum(len(x['orig']) for x in items)} records)")
        for x in items[:2]:
            print("\nnames:", x["names"][:6]); i = x["masked"].index("Hypothesis"); print(x["masked"][i:i + 700])
    elif a.cmd == "run":
        res = run(a.runs, a.out, a.config, a.max_calls, not a.no_replay)
        print(a.out, "calls", res["calls"])
    else:
        print(json.dumps(report(a.inp), indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()

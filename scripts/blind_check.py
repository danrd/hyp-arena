"""Paired check of name dependence of the verifier: the same saved prompt with and without the compound's names.

    python -m scripts.blind_check plan   --runs runs/stage4/itp2010_dev.reapplied.json runs/stage4/itp2010_test.reapplied.json
    ALLOW_PAID=1 python -m scripts.blind_check run --runs ... --out runs/stage5/blind_itp2010.json --max-calls 140
    python -m scripts.blind_check report --in runs/stage5/blind_itp2010.json

    # acceptance of a candidate verifier (L1.13): the same saved prompts, no masking
    ALLOW_PAID=1 python -m scripts.blind_check candidate --runs ... --config configs/v2-gpt5.yaml --family openai --mini --out runs/stage5/cand_gpt5.json
    ALLOW_PAID=1 python -m scripts.blind_check candidate --runs ... --config configs/v2-gpt5.yaml --family openai --resume runs/stage5/cand_gpt5.json --out runs/stage5/cand_gpt5.json
    python -m scripts.blind_check candidate-report --in runs/stage5/cand_gpt5.json [--mini] [--test L1.13|L1.14|L1.15|L1.16]

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


# ---- status-level agreement (L1.14): what the pipeline would count, not the raw fields ----

def counted_keys(records: list[dict]) -> set[tuple]:
    """The records that can move a claim status, as (pmid, kind, side). A lifespan finding with a known direction counts by its
    effect direction (the code sets its stance from it, `verify_claim/v4`); any other record counts only with stance supports or refutes."""
    out = set()
    for r in records:
        pmid = str(r.get("pmid"))
        if r.get("endpoint") == "lifespan" and r.get("quote_role") == "finding" and r.get("effect") in ("increase", "decrease", "no_effect"):
            out.add((pmid, "L", r["effect"]))
        elif r.get("stance") in ("supports", "refutes"):
            out.add((pmid, "S", r["stance"]))
    return out


def status_compare(a: list[list[dict]], b: list[list[dict]]) -> dict:
    """Agreement of two arms on the counted records: share of calls with the same set, and the pooled Jaccard of the sets."""
    same, inter, union = 0, 0, 0
    for x, y in zip(a, b):
        kx, ky = counted_keys(x), counted_keys(y)
        same += kx == ky
        inter += len(kx & ky)
        union += len(kx | ky)
    return {"calls": len(a), "same_counted_set": same, "call_rate": same / max(1, len(a)), "counted_union": union,
            "jaccard": inter / union if union else None}


# ---- acceptance of a candidate verifier (specs/validation-criteria.yaml, L1.13) ----

def mini_indices(items: list[dict], k: int = 4) -> list[int]:
    """The mini-sample: the first k calls whose saved reply has records and the first k whose reply is empty (deterministic)."""
    full = [i for i, it in enumerate(items) if it["orig"]][:k]
    empty = [i for i, it in enumerate(items) if not it["orig"]][:k]
    return sorted(full + empty)


def run_candidate(runs: list[str], out: str, config: str, family: str, max_calls: int, mini: bool = False, resume: str | None = None) -> dict:
    """Ask the candidate the saved (unmasked) prompts; `mini` asks only the mini-sample; `resume` keeps the answers already saved."""
    from hyparena.card.pipeline import _client
    items = collect(runs)
    done = {}
    if resume and Path(resume).exists():
        done = {a["i"]: a for a in json.loads(Path(resume).read_text())["answers"]}
    todo = [i for i in (mini_indices(items) if mini else range(len(items))) if i not in done]
    client, _ = _client(config, False, max_calls)

    def one(i: int) -> dict:
        r = client.call(role="verify_claim", family=family, prompt=items[i]["prompt"], avoid=frozenset())
        return {"i": i, "text": r.text, "tokens_in": r.tokens_in, "tokens_out": r.tokens_out, "error": r.error, "model": r.model_id}

    with ThreadPoolExecutor(4) as pool:
        for a in pool.map(one, todo):
            done[a["i"]] = a
    res = {"config": config, "family": family, "calls_this_run": client.calls, "n_items": len(items), "mini": mini,
           "orig": {str(i): it["orig"] for i, it in enumerate(items)},
           "answers": [done[i] for i in sorted(done)]}
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(res, ensure_ascii=False, indent=1))
    return res


def _status_verdict(out: dict, cmp_: dict, st: dict, t: dict, all_answered: bool, n_valid: int, n_trunc: int) -> dict:
    n = max(1, out["answered"])
    sh = cmp_["shared_records"]
    out.update(cmp_)
    out["status_level"] = st
    out["effect_rate"] = cmp_["effect_agree"] / sh if sh else None
    out["stance_rate_reported"] = cmp_["stance_agree"] / sh if sh else None
    out["set_rate_reported"] = cmp_["same_paper_set"] / max(1, cmp_["calls"])
    v = {"all_answered": all_answered, "valid_ok": n_valid / n >= t["valid_rate_min"] if "valid_rate_min" in t else True,
         "truncated_ok": n_trunc / n <= t["truncated_rate_max"] if "truncated_rate_max" in t else True,
         "counted_union_enough": st["counted_union"] >= t["counted_union_min"],
         "call_rate_ok": st["call_rate"] >= t["call_rate_min"],
         "jaccard_ok": st["jaccard"] is not None and st["jaccard"] >= t["jaccard_min"]}
    if "effect_agree_min" in t:
        v["enough_shared_records"] = sh >= t["shared_records_min"]
        v["effect_ok"] = bool(sh) and out["effect_rate"] >= t["effect_agree_min"]
    out["verdict"] = v
    out["status"] = ("uninformative" if not v["counted_union_enough"] or not v["all_answered"] or not v.get("enough_shared_records", True)
                     else "pass" if all(v.values()) else "fail")
    return out


def candidate_verdict(path: str, thresholds: dict, mini: bool = False) -> dict:
    """Metrics of a candidate against the saved replies of the reference verifier and the verdict against the thresholds fixed in advance."""
    d = json.loads(Path(path).read_text())
    cap = thresholds["completion_token_cap"]
    ans = d["answers"]
    valid = [a for a in ans if a["text"] and not a["error"] and __import__("hyparena.card.verifier", fromlist=["parse_records"]).parse_records(a["text"]) is not None]
    truncated = [a for a in ans if (a["tokens_out"] or 0) >= 0.98 * cap]
    out = {"answered": len(ans), "valid": len(valid), "truncated": len(truncated),
           "tokens_out_median": sorted(a["tokens_out"] or 0 for a in ans)[len(ans) // 2] if ans else None,
           "tokens_out_total": sum(a["tokens_out"] or 0 for a in ans), "tokens_in_total": sum(a["tokens_in"] or 0 for a in ans)}
    if mini:
        m = thresholds["mini_sample"]
        out["verdict"] = {"valid_ok": out["valid"] >= m["valid_min"], "truncated_ok": out["truncated"] <= m["truncated_max"]}
        out["accepted_for_full_run"] = all(out["verdict"].values())
        return out
    pairs = [(_records(a["text"]) if a in valid else [], d["orig"][str(a["i"])]) for a in ans]
    cmp_ = compare([p[0] for p in pairs], [p[1] for p in pairs])
    sh = cmp_["shared_records"]
    if "call_rate_min" in thresholds:                  # L1.14 / L1.15 / L1.16: agreement on the records that move a status
        return _status_verdict(out, cmp_, status_compare([p[0] for p in pairs], [p[1] for p in pairs]), thresholds,
                               len(ans) == d["n_items"], len(valid), len(truncated))
    out.update(cmp_)
    out["stance_rate"] = cmp_["stance_agree"] / sh if sh else None
    out["effect_rate"] = cmp_["effect_agree"] / sh if sh else None
    out["set_rate"] = cmp_["same_paper_set"] / max(1, cmp_["calls"])
    t = thresholds
    v = {"all_answered": len(ans) == d["n_items"], "valid_ok": len(valid) / max(1, len(ans)) >= t["valid_rate_min"],
         "truncated_ok": len(truncated) / max(1, len(ans)) <= t["truncated_rate_max"], "enough_shared_records": sh >= t["shared_records_min"],
         "stance_ok": bool(sh) and out["stance_rate"] >= t["stance_agree_min"], "effect_ok": bool(sh) and out["effect_rate"] >= t["effect_agree_min"],
         "set_ok": out["set_rate"] >= t["set_agree_min"]}
    out["verdict"] = v
    out["status"] = ("uninformative" if not v["enough_shared_records"] or not v["all_answered"]
                     else "pass" if all(v.values()) else "fail")
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
    c = sub.add_parser("candidate", help="ask a candidate verifier the saved prompts (paid)")
    c.add_argument("--runs", nargs="+", required=True)
    c.add_argument("--out", required=True)
    c.add_argument("--config", required=True)
    c.add_argument("--family", required=True)
    c.add_argument("--max-calls", type=int, default=80)
    c.add_argument("--mini", action="store_true", help="only the mini-sample (4 calls with records, 4 with empty replies)")
    c.add_argument("--resume", default=None)
    cr = sub.add_parser("candidate-report")
    cr.add_argument("--in", dest="inp", required=True)
    cr.add_argument("--mini", action="store_true")
    cr.add_argument("--criteria", default="specs/validation-criteria.yaml")
    cr.add_argument("--test", default="L1.13", help="L1.13 raw fields; L1.14, L1.15, L1.16 records that move a status")
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
    elif a.cmd == "candidate":
        res = run_candidate(a.runs, a.out, a.config, a.family, a.max_calls, a.mini, a.resume)
        print(a.out, "answers", len(res["answers"]), "calls this run", res["calls_this_run"])
    elif a.cmd == "candidate-report":
        import yaml
        t = next(x for x in yaml.safe_load(Path(a.criteria).read_text())["tests"] if x["id"] == a.test)["thresholds"]
        print(json.dumps(candidate_verdict(a.inp, t, a.mini), indent=2, ensure_ascii=False))
    else:
        print(json.dumps(report(a.inp), indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()

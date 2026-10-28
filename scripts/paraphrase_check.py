"""L1.8: invariance of the card, the statuses and the places to paraphrasing of the hypothesis text.

    python -m scripts.paraphrase_check select                                  # no calls: 15 ITP texts, writes data/validation/l1_8_texts.json
    ALLOW_PAID=1 python -m scripts.paraphrase_check paraphrase                 # 10 calls: the model paraphrases of the first 10 texts
    ALLOW_PAID=1 python -m scripts.paraphrase_check run --out runs/stage5/l1_8  # three pipeline runs (as of 2010-12-31)
    python -m scripts.paraphrase_check report --dir runs/stage5/l1_8

The criterion and procedure are in specs/validation-criteria.yaml (L1.8), committed before the first call.
Arms: O1 and O2 (the same original texts, normalized and verified twice) and P (the paraphrases). Agreement is computed
for P against O1 and for O2 against O1; P passes a measure if it is not below the repeat agreement minus 0.05.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

TEXTS = Path("data/validation/l1_8_texts.json")
AS_OF = "2010-12-31"
N, N_MODEL = 15, 10
TOL = 0.05
PARAPHRASE_PROMPT = (
    "Rewrite the research hypothesis below in different words and with a different sentence structure. Keep every factual element "
    "exactly: the name of the compound, the dose, the age at which treatment starts, the species and strain, which sexes, the "
    "endpoint and the direction of the effect. Do not add, drop or soften any claim, do not add background. Return only the "
    "rewritten text, with no preamble.\n\nHypothesis:\n{text}\n")


def _norm(v) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(v or "").lower())


def select() -> list[dict]:
    """15 ranked ITP regimens of distinct compounds, ordered by a hash of the text (deterministic); the first 10 get model paraphrases, the last 5 manual ones."""
    labels = json.loads(Path("data/backtest/itp_2010-12-31_labels.json").read_text())
    rows = []
    for half in ("dev", "test"):
        res = json.loads(Path(f"runs/stage4/itp2010_{half}.json").read_text())
        ids = res["meta"].get("ids") or []
        for pid, x in zip(ids, res["items"]):
            if x["outcome"] == "ranked" and pid in labels:
                rows.append({"id": pid, "compound": labels[pid]["compound"], "text": x["text"]})
    rows.sort(key=lambda r: hashlib.sha1(r["text"].encode()).hexdigest())
    seen, out = set(), []
    for r in rows:
        if _norm(r["compound"]) not in seen:
            seen.add(_norm(r["compound"]))
            out.append(r)
        if len(out) == N:
            break
    for i, r in enumerate(out):
        r["source"] = "model" if i < N_MODEL else "manual"
    return out


def main_index(card: dict) -> int:
    """Index of the outcome claim (the main one); the first claim when none has the role. L1.8 and L1.9 took the first claim, which is a
    premise when the normalizer lists a mechanism first (INT-767d): fixed here for the repeat of both checks."""
    return next((i for i, c in enumerate(card["claims"]) if c.get("role") == "outcome"), 0)


def facets(card: dict) -> dict:
    """Four facets of the main claim: subject, relation, object, context (the qualifiers of the claim)."""
    c = card["claims"][main_index(card)]
    q = c.get("qualifiers") or {}
    return {"subject": _norm(c["subject"]["label"]), "relation": c["relation"], "object": _norm(c["object"]["label"]),
            "context": tuple(_norm(q.get(k)) for k in ("species", "strain", "sex", "dose", "age_at_start", "measure"))}


def _span(place: str) -> tuple[int, int]:
    a, _, b = place.partition("-")
    return int(a), int(b or a)


def summarize(res: dict) -> dict:
    """Per hypothesis (by order of the texts): outcome, status of the main claim, place range, facets."""
    from hyparena.snapshot import places
    P = res["ranking"].get("evidence_first")
    pl = places({"expected": P["expected"], "std": P.get("std") or {}, "K": P.get("K") or res["meta"].get("K") or 10000, "order": P["order"]}) if P and P["order"] else {}
    out = []
    for x in res["items"]:
        cl = (x.get("verification") or {}).get("claims") or []
        k = main_index(x["card"]) if x.get("card") else 0
        out.append({"outcome": x["outcome"], "status": cl[k]["status"] if len(cl) > k else None, "place": pl.get(x["id"]),
                    "facets": facets(x["card"]) if x.get("card") else None})
    return {"items": out}


def agreement(a: dict, b: dict) -> dict:
    n = len(a["items"])
    res = {k: 0 for k in ("subject", "relation", "object", "context", "status", "place")}
    for x, y in zip(a["items"], b["items"]):
        for k in ("subject", "relation", "object", "context"):
            res[k] += bool(x["facets"] and y["facets"] and x["facets"][k] == y["facets"][k])
        res["status"] += x["status"] == y["status"] and x["outcome"] == y["outcome"]
        if x["place"] and y["place"]:
            (a0, a1), (b0, b1) = _span(x["place"]), _span(y["place"])
            res["place"] += max(a0, b0) <= min(a1, b1)          # the ranges overlap: the same place under the tie rule
        else:
            res["place"] += x["outcome"] == y["outcome"] and not x["place"] and not y["place"]
    return {k: v / n for k, v in res.items()}


def verdict(p_vs_o1: dict, o2_vs_o1: dict) -> dict:
    per = {k: {"paraphrase": round(p_vs_o1[k], 3), "repeat": round(o2_vs_o1[k], 3), "ok": p_vs_o1[k] >= o2_vs_o1[k] - TOL} for k in p_vs_o1}
    return {"measures": per, "status": "pass" if all(v["ok"] for v in per.values()) else "fail"}


def cmd_paraphrase() -> None:
    from hyparena.card.pipeline import _client
    d = json.loads(TEXTS.read_text())
    client, _ = _client("configs/v2-flash.yaml", False, 20)
    for r in d["items"]:
        if r["source"] == "model" and not r.get("paraphrase"):
            reply = client.call(role="paraphrase", family="deepseek", prompt=PARAPHRASE_PROMPT.format(text=r["text"]), avoid=frozenset())
            if reply.error or not reply.text.strip():
                raise SystemExit(f"paraphrase failed for {r['id']}: {reply.error}")
            r["paraphrase"] = reply.text.strip()
    TEXTS.write_text(json.dumps(d, ensure_ascii=False, indent=1))
    print("calls", client.calls)


def cmd_run(out: str, max_calls: int) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from hyparena.card import pipeline
    d = json.loads(TEXTS.read_text())
    arms = {"O1": [r["text"] for r in d["items"]], "O2": [r["text"] for r in d["items"]], "P": [r["paraphrase"] for r in d["items"]]}
    Path(out).mkdir(parents=True, exist_ok=True)

    def one(name):
        res = pipeline.run(arms[name], config="configs/v2-flash.yaml", as_of=AS_OF, max_calls=max_calls, verifiers=["deepseek"], dedup=False)
        Path(out, f"{name}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
        return name, res["meta"]["calls"]

    with ThreadPoolExecutor(3) as pool:
        for name, calls in pool.map(one, arms):
            print(name, "calls", calls, flush=True)


def cmd_report(dirname: str) -> dict:
    s = {n: summarize(json.loads(Path(dirname, f"{n}.json").read_text())) for n in ("O1", "O2", "P")}
    out = verdict(agreement(s["P"], s["O1"]), agreement(s["O2"], s["O1"]))
    print(json.dumps(out, indent=1))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("select")
    sub.add_parser("paraphrase")
    r = sub.add_parser("run")
    r.add_argument("--out", required=True)
    r.add_argument("--max-calls", type=int, default=400)
    q = sub.add_parser("report")
    q.add_argument("--dir", required=True)
    a = ap.parse_args()
    if a.cmd == "select":
        items = select()
        TEXTS.parent.mkdir(parents=True, exist_ok=True)
        TEXTS.write_text(json.dumps({"as_of": AS_OF, "items": items}, ensure_ascii=False, indent=1))
        for r_ in items:
            print(r_["id"], r_["source"], r_["compound"], "|", r_["text"][:90].replace("\n", " "))
    elif a.cmd == "paraphrase":
        cmd_paraphrase()
    elif a.cmd == "run":
        cmd_run(a.out, a.max_calls)
    else:
        cmd_report(a.dir)


if __name__ == "__main__":
    main()

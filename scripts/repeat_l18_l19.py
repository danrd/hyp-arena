"""L1.8b and L1.9b: the repeat of the paraphrase and style checks after the normalizer fixes (canonical qualifiers, abbreviations, organism as
the object, route words, Greek letters; prompt v6), on 15 regimens not used in L1.8, L1.9 or the prompt checks.

    python -m scripts.repeat_l18_l19 select                       # no calls: data/validation/l1_8b_texts.json (5 manual paraphrases are added by hand)
    ALLOW_PAID=1 python -m scripts.repeat_l18_l19 texts           # 40 calls: 10 model paraphrases, the hype and terse styles of all 15
    ALLOW_PAID=1 python -m scripts.repeat_l18_l19 run --out runs/stage5/l1_8b    # five pipeline runs: O1, O2, P, H, T
    python -m scripts.repeat_l18_l19 report --dir runs/stage5/l1_8b

Measures and thresholds are those of L1.8 and L1.9 (specs/validation-criteria.yaml, L1.8b and L1.9b): the main claim is the outcome claim.
The Co-Scientist baseline (L0) is not repeated; its numbers come from the first run of L1.9."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from scripts import paraphrase_check as pc
from scripts import style_check as sc

TEXTS = Path("data/validation/l1_8b_texts.json")
AS_OF = "2010-12-31"
USED = ("data/validation/l1_8_texts.json", "data/validation/prompt2_texts.json")


def select(n: int = 15) -> list[dict]:
    labels = json.loads(Path("data/backtest/itp_2010-12-31_labels.json").read_text())
    used = {r["id"] for f in USED for r in json.loads(Path(f).read_text())["items"]}
    used_c = {re.sub(r"[^a-z0-9]+", "", labels[i]["compound"].lower()) for i in used if i in labels}
    rows = []
    for half in ("dev", "test"):
        res = json.loads(Path(f"runs/stage4/itp2010_{half}.json").read_text())
        for pid, x in zip(res["meta"].get("ids") or [], res["items"]):
            if x["outcome"] == "ranked" and pid in labels and pid not in used:
                rows.append({"id": pid, "compound": labels[pid]["compound"], "text": x["text"]})
    rows.sort(key=lambda r: hashlib.sha1(("l18b:" + r["text"]).encode()).hexdigest())
    seen, out = set(used_c), []
    for r in rows:
        k = re.sub(r"[^a-z0-9]+", "", r["compound"].lower())
        if k not in seen:
            seen.add(k)
            out.append(r)
        if len(out) == n:
            break
    for i, r in enumerate(out):
        r["source"] = "model" if i < pc.N_MODEL else "manual"
        r["O"] = sc.first_paragraph(r["text"])
    return out


def cmd_texts() -> None:
    from hyparena.card.pipeline import _client
    d = json.loads(TEXTS.read_text())
    missing = [r["id"] for r in d["items"] if r["source"] == "manual" and not r.get("paraphrase")]
    if missing:
        raise SystemExit(f"manual paraphrases missing: {missing}")
    client, _ = _client("configs/v2-flash.yaml", False, 60)
    for r in d["items"]:
        if r["source"] == "model" and not r.get("paraphrase"):
            r["paraphrase"] = client.call(role="paraphrase", family="deepseek", prompt=pc.PARAPHRASE_PROMPT.format(text=r["text"]), avoid=frozenset()).text.strip()
        for k, desc in sc.STYLES.items():
            if not r.get(k):
                r[k] = client.call(role="restyle", family="deepseek", prompt=sc.PROMPT.format(style=desc, text=r["O"]), avoid=frozenset()).text.strip()
    if any(not r.get(k) for r in d["items"] for k in ("paraphrase", "H", "T")):
        raise SystemExit("an empty reply: run again (answers already saved are kept)")
    TEXTS.write_text(json.dumps(d, ensure_ascii=False, indent=1))
    print("calls", client.calls)


def cmd_run(out: str, max_calls: int = 400) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from hyparena.card import pipeline
    d = json.loads(TEXTS.read_text())
    arms = {"O1": [r["text"] for r in d["items"]], "O2": [r["text"] for r in d["items"]], "P": [r["paraphrase"] for r in d["items"]],
            "H": [r["H"] for r in d["items"]], "T": [r["T"] for r in d["items"]]}
    Path(out).mkdir(parents=True, exist_ok=True)

    def one(name):
        if Path(out, f"{name}.json").exists():
            return name, "kept"
        res = pipeline.run(arms[name], config="configs/v2-flash.yaml", as_of=AS_OF, max_calls=max_calls, verifiers=["deepseek"], dedup=False)
        Path(out, f"{name}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
        return name, res["meta"]["calls"]

    with ThreadPoolExecutor(3) as pool:
        for name, calls in pool.map(one, arms):
            print(name, "calls", calls, flush=True)


def cmd_report(dirname: str) -> dict:
    s = {n: pc.summarize(json.loads(Path(dirname, f"{n}.json").read_text())) for n in ("O1", "O2", "P")}
    l18 = pc.verdict(pc.agreement(s["P"], s["O1"]), pc.agreement(s["O2"], s["O1"]))
    o1, o2 = sc._ours_scores(Path(dirname, "O1.json")), sc._ours_scores(Path(dirname, "O2.json"))
    h, t = sc._ours_scores(Path(dirname, "H.json")), sc._ours_scores(Path(dirname, "T.json"))
    l19 = sc.verdict({"O-H": sc.tau(o1, h), "O-T": sc.tau(o1, t), "H-T": sc.tau(h, t)}, sc.tau(o1, o2))
    out = {"L1.8b": l18, "L1.9b": l19}
    print(json.dumps(out, indent=1))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("select")
    sub.add_parser("texts")
    r = sub.add_parser("run")
    r.add_argument("--out", required=True)
    q = sub.add_parser("report")
    q.add_argument("--dir", required=True)
    a = ap.parse_args()
    if a.cmd == "select":
        items = select()
        TEXTS.write_text(json.dumps({"as_of": AS_OF, "items": items}, ensure_ascii=False, indent=1))
        for x in items:
            print(x["id"], x["source"], "|", x["O"])
    elif a.cmd == "texts":
        cmd_texts()
    elif a.cmd == "run":
        cmd_run(a.out)
    else:
        cmd_report(a.dir)


if __name__ == "__main__":
    main()

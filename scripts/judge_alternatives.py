"""d of the proposed alternatives judged from the registry text (specs/informativeness-check-2026-11-08.yaml, fix_d).
Paid (DeepSeek V4.1 Flash through CometAPI), one call per trial.

    ALLOW_PAID=1 python -m scripts.judge_alternatives run --part dev|holdout   # -> prospective/judge_alternatives_<part>.json
    ALLOW_PAID=1 python -m scripts.judge_alternatives pool --pool calibration   # every unit -> <pool>/judge_alternatives_v2.json
    python -m scripts.judge_alternatives merge                                  # prospective dev + holdout -> judge_alternatives_v2.json
    python -m scripts.judge_alternatives score --part dev|holdout               # weighted kappa with Argon (pack 6), free
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os

from scripts.pack6_analysis import D, SUP, wkappa
from scripts.pack6_informativeness import DIR as ARGON
from scripts.v34_check import PROS, parts

CONFIG = "configs/v3-flash-n10.yaml"
TEMPLATE = ("judge_alternatives", os.environ.get("JUDGE_VERSION", "v2"))   # v1 = the first dev run
LEVELS = ("eliminated", "weakened", "unchanged")


def split() -> dict[str, list[str]]:
    ids = sorted(json.loads((ARGON / "pack_6_key.json").read_text()),
                 key=lambda h: hashlib.sha1(f"judge|{h}".encode()).hexdigest())
    return {"dev": ids[:29], "holdout": ids[29:]}


def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())


def apply_rules(reply: dict, text: str, ids: list[str]) -> dict:
    """Code rules on the reply: closed levels; an 'eliminated' without a verbatim registry phrase becomes 'weakened'."""
    out, t = {}, _norm(text)
    for a in (reply or {}).get("alternatives") or []:
        if not isinstance(a, dict) or a.get("id") not in ids:
            continue
        dp, dn = a.get("d_positive"), a.get("d_negative")
        dp, dn = (x if x in LEVELS else "unchanged" for x in (dp, dn))
        feat = a.get("separating_feature") or ""
        verbatim = bool(feat) and _norm(feat) in t
        notes = []
        for k in ("dp", "dn"):
            if (dp if k == "dp" else dn) == "eliminated" and not verbatim:
                notes.append(f"{k} eliminated -> weakened (phrase not verbatim)")
                dp, dn = (("weakened", dn) if k == "dp" else (dp, "weakened"))
        if dp == dn == "eliminated":
            notes.append("eliminated by both -> negative weakened")
            dn = "weakened"
        out[a["id"]] = {"d_positive": dp, "d_negative": dn, "separating_feature": feat if verbatim else None, "notes": notes}
    return out


def run(part: str) -> dict:
    if os.environ.get("ALLOW_PAID") != "1":
        raise SystemExit("paid: set ALLOW_PAID=1")
    from hyparena.card.llm import ask
    from hyparena.card.pipeline import _client
    run_ = json.loads((PROS / "run_60.json").read_text())
    texts = {json.loads(l)["id"]: json.loads(l)["text"] for l in (PROS / "texts_60.jsonl").read_text().splitlines() if l.strip()}
    out_p = PROS / f"judge_alternatives_{part}_{TEMPLATE[1]}.json"
    done = json.loads(out_p.read_text()) if out_p.exists() else {}
    ids = [h for h in split()[part] if h not in done]
    client, _ = _client(CONFIG, False, len(ids) * 3 + 5)
    for h in ids:
        card, _, _ = parts(run_[h]["items"][0])
        alts = [{"id": a.id, "claim": f"{a.subject.label} - {a.relation.replace('_', ' ')} - {a.object.label}",
                 "rationale": a.rationale} for a in card.proposed_alternatives]
        log: list = []
        value, fam = ask(client, role="judge_alternatives", family="deepseek", template=TEMPLATE[0], version=TEMPLATE[1],
                         variables={"registry_text": texts[h], "claim_plain": card.claim_plain, "alternatives": alts},
                         validate=lambda v: [] if isinstance(v.get("alternatives"), list) else ['an "alternatives" list'],
                         rounds=2, log=log)
        done[h] = {"family": fam, "d": apply_rules(value, texts[h], [a["id"] for a in alts]),
                   "tokens_in": sum(x.get("tokens_in", 0) or 0 for x in log), "tokens_out": sum(x.get("tokens_out", 0) or 0 for x in log),
                   "raw": value}
        out_p.write_text(json.dumps(done, indent=1, ensure_ascii=False) + "\n")
    tin = sum(v["tokens_in"] for v in done.values())
    tout = sum(v["tokens_out"] for v in done.values())
    return {"trials": len(done), "tokens_in": tin, "tokens_out": tout, "usd_offpeak": round(tin * 0.15e-6 + tout * 0.6e-6, 4)}


def score(part: str) -> dict:
    judged = json.loads((PROS / f"judge_alternatives_{part}_{TEMPLATE[1]}.json").read_text())
    ans = {t["id"]: {a["id"]: a for a in t["alternatives"]} for t in json.loads((ARGON / "pack_6_answer.json").read_text())["trials"]}
    key = json.loads((ARGON / "pack_6_key.json").read_text())
    new, old, n_elim, n_drop = [], [], 0, 0
    I_new, I_arg = [], []
    from scipy.stats import spearmanr
    for h, j in judged.items():
        s_new = s_arg = 0.0
        for aid, ka in key[h]["alternatives"].items():
            a = ans[h].get(aid)
            d = j["d"].get(aid)
            if not a or not d:
                continue
            nd = max(D[d["d_positive"]], D[d["d_negative"]])
            ad = max(D[a["d_positive"]], D[a["d_negative"]])
            od = max(D[ka["on_positive"]], D[ka["on_negative"]])
            new.append((nd, ad))
            old.append((od, ad))
            n_elim += nd == 1.0
            n_drop += any("not verbatim" in x for x in d["notes"])
            s_new += ka["a_v36"] * nd
            s_arg += ka["a_v36"] * ad
        I_new.append(min(1.0, s_new / 1.5))
        I_arg.append(min(1.0, s_arg / 1.5))
    return {"part": part, "trials": len(judged), "alternatives": len(new),
            "weighted_kappa_new": wkappa(new), "weighted_kappa_old_same_trials": wkappa(old),
            "eliminated_new": n_elim, "eliminated_downgraded_not_verbatim": n_drop,
            "I_with_our_a_spearman_new_vs_argon_d": round(float(spearmanr(I_new, I_arg).statistic), 3)}


def pool_run(pool: str) -> dict:
    """judge_alternatives/v2 on every scored unit of the calibration pool (the method's d since 2026-11-08)."""
    if os.environ.get("ALLOW_PAID") != "1":
        raise SystemExit("paid: set ALLOW_PAID=1")
    from hyparena.card.llm import ask
    from hyparena.card.pipeline import _client
    from scripts.v34_check import CAL
    assert pool == "calibration"
    texts = {}
    for s_ in (1, 2, 3, 4, 5):
        for l in (CAL / f"texts_{s_}.jsonl").read_text().splitlines():
            if l.strip():
                d = json.loads(l)
                texts[d["id"]] = d["text"]
    out_p = CAL / "judge_alternatives_v2.json"
    done = json.loads(out_p.read_text()) if out_p.exists() else {}
    todo = []
    for s_ in (1, 2, 3, 4, 5):
        for h, r in json.loads((CAL / f"run_{s_}_v10.json").read_text()).items():
            it = r["items"][0]
            if h not in done and it.get("card") and it.get("verification") and "v3" in it and h in texts:
                todo.append((h, it))
    client, _ = _client(CONFIG, False, len(todo) * 3 + 5)
    for h, it in todo:
        card, _, _ = parts(it)
        alts = [{"id": a.id, "claim": f"{a.subject.label} - {a.relation.replace('_', ' ')} - {a.object.label}",
                 "rationale": a.rationale} for a in card.proposed_alternatives]
        if not alts:
            done[h] = {"d": {}, "tokens_in": 0, "tokens_out": 0}
            continue
        log: list = []
        value, fam = ask(client, role="judge_alternatives", family="deepseek", template="judge_alternatives", version="v2",
                         variables={"registry_text": texts[h], "claim_plain": card.claim_plain, "alternatives": alts},
                         validate=lambda v: [] if isinstance(v.get("alternatives"), list) else ['an "alternatives" list'],
                         rounds=2, log=log)
        done[h] = {"family": fam, "d": apply_rules(value, texts[h], [a["id"] for a in alts]),
                   "tokens_in": sum(int(x.get("tokens_in") or 0) for x in log), "tokens_out": sum(int(x.get("tokens_out") or 0) for x in log)}
        out_p.write_text(json.dumps(done, indent=1, ensure_ascii=False) + "\n")
    tin, tout = sum(v["tokens_in"] for v in done.values()), sum(v["tokens_out"] for v in done.values())
    return {"units": len(done), "usd_offpeak": round(tin * 0.15e-6 + tout * 0.6e-6, 4)}


def merge() -> dict:
    out = {}
    for part in ("dev", "holdout"):
        for h, v in json.loads((PROS / f"judge_alternatives_{part}_v2.json").read_text()).items():
            out[h] = {"d": v["d"], "tokens_in": v["tokens_in"], "tokens_out": v["tokens_out"]}
    (PROS / "judge_alternatives_v2.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return {"units": len(out)}


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] in ("pool", "merge"):
        print(json.dumps(pool_run(sys.argv[3]) if sys.argv[1] == "pool" else merge(), indent=1))
        raise SystemExit
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "score"])
    ap.add_argument("--part", choices=["dev", "holdout"], required=True)
    a = ap.parse_args()
    print(json.dumps(run(a.part) if a.cmd == "run" else score(a.part), indent=1))

"""Level 4 of the checks: generation compared (specs/evolution/generation-comparison-2026-11-14.yaml, manual
docs/validation/generation-arena.md). The hypotheses of the arms (A: an outside model in a chat; B: the same model by the
manual; C: B after free evolution; D: A after free evolution) are put into one form, judged blind by models of other
families (pairwise in both orders, and by a rubric), and the win shares are computed with bootstrap intervals.

    python -m scripts.evolution.generation_compare dry   --dir DIR                # calls and the price, no call
    ALLOW_PAID=1 python -m scripts.evolution.generation_compare format --dir DIR  # one form for every text
    ALLOW_PAID=1 python -m scripts.evolution.generation_compare judge  --dir DIR  # pairwise and rubric judges
    python -m scripts.evolution.generation_compare score  --dir DIR               # win shares, intervals, the rule
    add --fake to use the fake LLM (free)

DIR (private, in longevity-kg) holds `hypotheses.json` written by `scripts/argon/generation_tasks.py collect`:
{"topic": ..., "as_of": ..., "writer_family": ..., "arms": {"A": [{"id", "parent", "text", "terms"}], ...}}.
Writes `formatted.json`, `judgements.json`, `score.json` there.
"""
from __future__ import annotations

import argparse
import json
import random
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

from hyparena.card.llm import ask
from hyparena.llm.client import estimate_tokens
from hyparena.llm.prompts import render

CONFIG = "configs/judges-generation.yaml"
CRITERIA = ("novelty", "grounding", "testability", "specificity", "significance")
LIMIT = 1200                       # characters of claim + rationale + experiment
TARGET = 1000                      # what the rewriter is asked to aim at (models overshoot a stated limit)
OUT_TOKENS = {"judge_pair": 300, "judge_rubric": 200, "format_hypothesis": 450}
TESTED = (("B", "A", "cross"), ("BS", "A", "cross"), ("C", "B", "matched"), ("D", "A", "matched"))
# the judge's question: v1 five criteria and overall, plus a rubric per hypothesis; v2 (pilot of 2026-11-16) one question,
# which hypothesis to investigate first (plausibility, evidence for and against, benefit to people, the nearest convincing
# experiment), novelty not asked (code measures it), no rubric. Set by the config's "judge" block.
MODE = {"pair_version": "v1", "rubric": True, "rewrite": True}


def set_mode(cfg: dict) -> None:
    MODE.update({"pair_version": "v1", "rubric": True, "rewrite": True, **(cfg.get("judge") or {})})


def _criteria() -> tuple:
    return CRITERIA if MODE["pair_version"] == "v1" else ()
REPORTED = (("C", "A", "cross"),)
STOP = set("a an the of in on to for and or with by from at as is are be was were that this these those it its into "
           "than then which who whom whose under over between within without via not no".split())


def load(d: Path) -> dict:
    return json.loads((d / "hypotheses.json").read_text())


def judges(cfg: dict, data: dict) -> list[str]:
    rewriter = cfg.get("rewriter") if MODE.get("rewrite", True) else None   # without rewriting the rewriter's family judges too
    return [m["family"] for m in cfg["models"] if m.get("enabled", True)
            and m["family"] not in (data.get("writer_family"), rewriter)]


def pairs(arms: dict) -> list[tuple[str, str, str, str]]:
    """(comparison, id of X, id of Y): every cross pair of two arms, or each version with its parent."""
    out = []
    for x, y, kind in TESTED + REPORTED:
        if x not in arms or y not in arms:
            continue
        if kind == "cross":
            out += [(f"{x}>{y}", hx["id"], hy["id"]) for hx in arms[x] for hy in arms[y]]
        else:
            ids_y = {h["id"] for h in arms[y]}
            out += [(f"{x}>{y}", hx["id"], hx["parent"]) for hx in arms[x] if hx.get("parent") in ids_y]
    return [(c, a, b, "") for c, a, b in out]


# one form

def _words(s: str) -> set[str]:
    return {w[:6] for w in re.findall(r"[a-z][a-z0-9-]{2,}", s.lower()) if w not in STOP}


def meaning_kept(original: dict, formatted: dict) -> list[str]:
    """Problems of a rewritten text: a key term of the original (intervention, outcome, the experiment's system and
    endpoint; or, without them, the longest content words of the claim) missing, or the length over the limit."""
    text = " ".join(formatted.get(k, "") for k in ("claim", "rationale", "experiment"))
    have = _words(text)
    terms = [t for t in original.get("terms") or [] if t]
    if not terms:
        terms = sorted(_words(original["text"].split("\n")[0]), key=len, reverse=True)[:8]
    missing = [t for t in terms if not (_words(t) & have)]
    out = []
    if len(missing) > len(terms) // 4:
        out.append("These terms of the original are missing: " + ", ".join(missing[:8]) + ".")
    if len(text) > LIMIT * 1.1:
        out.append(f"The text has {len(text)} characters; at most {LIMIT}.")
    if any(not formatted.get(k) for k in ("claim", "rationale", "experiment")):
        out.append("Each of claim, rationale and experiment must be filled.")
    return out


def shortened(original: dict) -> dict:
    """The fallback form: the first sentences of the original, cut to the limit (marked as such)."""
    sents = re.split(r"(?<=[.!?])\s+", " ".join(original["text"].split()))
    third = max(1, len(sents) // 3)
    parts = [" ".join(sents[:third]), " ".join(sents[third:2 * third]), " ".join(sents[2 * third:])]
    def cut(p: str, n: int) -> str:                 # whole sentences up to n characters, at least the first one cut at a word
        out = ""
        for s_ in re.split(r"(?<=[.!?])\s+", p):
            if len(out) + len(s_) + 1 > n:
                break
            out = (out + " " + s_).strip()
        return out or p[:n].rsplit(" ", 1)[0]
    parts = [cut(p, LIMIT // 3) for p in parts]
    return {"claim": parts[0], "rationale": parts[1], "experiment": parts[2], "shortened_by_rule": True}


REF = re.compile(r"\s*\((?:PMID|PMIDs)[:\s]*[\d,;\s]+\)|\bPMIDs?[:\s]*\d{6,9}(?:[,;\s]+\d{6,9})*|\s*\[\d+(?:[,\u2013\-]\s*\d+)*\]"
                 r"|\s*\([A-Z][A-Za-z'\-]+(?: et al\.?| and [A-Z][A-Za-z'\-]+)?,? (?:19|20)\d\d[a-z]?(?:; [^)]{0,80})?\)")


def unreferenced(h: dict) -> dict:
    """The writer's own claim, rationale and experiment, with references cut by code (PMIDs, numbered and author-year
    citations): the form judged when nothing is rewritten (pilot of 2026-11-17)."""
    out, cut = {}, 0
    for k in ("claim", "rationale", "experiment"):
        t, n = REF.subn("", h.get(k) or "")
        out[k], cut = " ".join(t.split()), cut + n
    return {**out, "references_cut": cut, "rewritten": False}


def judged_text(f: dict) -> str:
    return f"Claim: {f['claim']}\nRationale: {f['rationale']}\nExperiment: {f['experiment']}"


def do_format(d: Path, client, cfg: dict) -> dict:
    data = load(d)
    if not MODE.get("rewrite", True):
        done = {h["id"]: unreferenced(h) for arm in data["arms"].values() for h in arm}
        (d / "formatted.json").write_text(json.dumps(done, indent=1, ensure_ascii=False) + "\n")
        return {"formatted": len(done), "rewritten": 0, "references_cut": sum(v["references_cut"] for v in done.values())}
    out_f = d / "formatted.json"
    done = json.loads(out_f.read_text()) if out_f.exists() else {}
    hyps = [h for arm in data["arms"].values() for h in arm]

    def one(h):
        if h["id"] in done:
            return h["id"], done[h["id"]]
        # only the rewriter's family: a judge family never rewrites (2026-11-17); v2 aims below the limit
        others = frozenset(m["family"] for m in cfg["models"] if m["family"] != cfg["rewriter"])
        v, fam = ask(client, role="format_hypothesis", family=cfg["rewriter"], template="format_hypothesis", version="v2",
                     variables={"text": h["text"], "limit": LIMIT, "target": TARGET}, validate=lambda v: meaning_kept(h, v),
                     rounds=3, avoid=others)
        if v is None or meaning_kept(h, v):
            return h["id"], {**shortened(h), "problems": meaning_kept(h, v or {}), "family": fam}
        return h["id"], {k: v[k] for k in ("claim", "rationale", "experiment")} | {"family": fam}
    with ThreadPoolExecutor(4) as ex:
        for i, v in ex.map(one, hyps):
            done[i] = v
    out_f.write_text(json.dumps(done, indent=1, ensure_ascii=False) + "\n")
    return {"formatted": len(done), "shortened_by_rule": sum(1 for v in done.values() if v.get("shortened_by_rule"))}


# judges

def pair_problems(v: dict) -> list[str]:
    bad = [k for k in _criteria() + ("overall",) if v.get(k) not in ("1", "2", "tie")]
    return [f'"{k}" must be "1", "2" or "tie"' for k in bad]


def rubric_problems(v: dict) -> list[str]:
    out = []
    for k in CRITERIA:
        try:
            if not 1 <= int(v.get(k)) <= 10:
                out.append(f'"{k}" must be 1-10')
        except (TypeError, ValueError):
            out.append(f'"{k}" must be a number 1-10')
    return out


def jobs(data: dict, fams: list[str]) -> list[tuple]:
    out = []
    for c, a, b, _ in pairs(data["arms"]):
        for fam in fams:
            out += [("pair", c, a, b, fam, "ab"), ("pair", c, a, b, fam, "ba")]
    if MODE["rubric"]:
        for arm in data["arms"].values():
            for h in arm:
                out += [("rubric", "", h["id"], "", fam, "") for fam in fams]
    return out


def job_key(j) -> str:
    return "|".join(j)


def prompt_of(j, data: dict, formatted: dict) -> tuple[str, dict]:
    kind, c, a, b, fam, order = j
    if kind == "pair":
        first, second = (a, b) if order == "ab" else (b, a)
        return "judge_pair", {"topic": data["topic"], "first": judged_text(formatted[first]), "second": judged_text(formatted[second])}
    return "judge_rubric", {"topic": data["topic"], "text": judged_text(formatted[a])}


def do_judge(d: Path, client, cfg: dict) -> dict:
    data = load(d)
    formatted = json.loads((d / "formatted.json").read_text())
    out_f = d / "judgements.json"
    done = json.loads(out_f.read_text()) if out_f.exists() else {}
    avoid = frozenset(f for f in (data.get("writer_family"), cfg.get("rewriter")) if f)

    def one(j):
        k = job_key(j)
        if k in done:
            return k, done[k]
        tpl, variables = prompt_of(j, data, formatted)
        v, got = ask(client, role=tpl, family=j[4], template=tpl,
                     version=MODE["pair_version"] if tpl == "judge_pair" else "v1", variables=variables,
                     validate=pair_problems if tpl == "judge_pair" else rubric_problems, rounds=2, avoid=avoid)
        ok = v is not None and not (pair_problems(v) if tpl == "judge_pair" else rubric_problems(v))
        return k, ({**v, "family": got} if ok else None)
    js = jobs(data, judges(cfg, data))
    with ThreadPoolExecutor(int(cfg.get("concurrency", 4))) as ex:
        for k, v in ex.map(one, js):
            done[k] = v
    out_f.write_text(json.dumps(done, indent=1, ensure_ascii=False) + "\n")
    return {"judgements": len(done), "failed": sum(1 for v in done.values() if v is None)}


# score

def pair_outcomes(data: dict, done: dict, fams: list[str], key: str = "overall") -> list[dict]:
    """One outcome per (pair, judge): 1 when X won in both orders, 0 when Y did, 0.5 otherwise (a tie or two different answers)."""
    out = []
    for c, a, b, _ in pairs(data["arms"]):
        for fam in fams:
            ab, ba = done.get(f"pair|{c}|{a}|{b}|{fam}|ab"), done.get(f"pair|{c}|{a}|{b}|{fam}|ba")
            if not ab or not ba:
                continue
            x_ab, x_ba = ab[key] == "1", ba[key] == "2"        # X is shown first in "ab", second in "ba"
            y_ab, y_ba = ab[key] == "2", ba[key] == "1"
            s = 1.0 if x_ab and x_ba else 0.0 if y_ab and y_ba else 0.5
            out.append({"comparison": c, "x": a, "y": b, "family": fam, "score": s})
    return out


def win_share(rows: list[dict]) -> float | None:
    return round(sum(r["score"] for r in rows) / len(rows), 3) if rows else None


def bootstrap(rows: list[dict], n: int = 2000, seed: int = 0) -> list[float] | None:
    """95% interval, resampling the hypotheses of each side (a pair is kept as often as both its ends are drawn)."""
    if not rows:
        return None
    xs, ys = sorted({r["x"] for r in rows}), sorted({r["y"] for r in rows})
    rng, vals = random.Random(seed), []
    for _ in range(n):
        wx = defaultdict(int); wy = defaultdict(int)
        for _ in xs:
            wx[rng.choice(xs)] += 1
        for _ in ys:
            wy[rng.choice(ys)] += 1
        num = den = 0.0
        for r in rows:
            w = wx[r["x"]] * wy[r["y"]]
            num += w * r["score"]; den += w
        if den:
            vals.append(num / den)
    vals.sort()
    return [round(vals[int(0.025 * len(vals))], 3), round(vals[int(0.975 * len(vals)) - 1], 3)] if vals else None


def do_score(d: Path, cfg: dict) -> dict:
    data = load(d)
    done = json.loads((d / "judgements.json").read_text())
    fams = judges(cfg, data)
    rows = pair_outcomes(data, done, fams)
    res = {"judges": fams, "comparisons": {}, "rubric": {}}
    for x, y, kind in TESTED + REPORTED:
        c = f"{x}>{y}"
        rs = [r for r in rows if r["comparison"] == c]
        if not rs:
            continue
        per_family = {f: win_share([r for r in rs if r["family"] == f]) for f in fams}
        share = win_share(rs)
        majority = sum(1 for v in per_family.values() if v is not None and v > 0.5) > len([v for v in per_family.values() if v is not None]) / 2
        per_criterion = {k: win_share([r for r in pair_outcomes(data, done, fams, k) if r["comparison"] == c]) for k in _criteria()}
        res["comparisons"][c] = {"kind": kind, "tested": (x, y, kind) in TESTED, "win_share": share, "ci95": bootstrap(rs),
                                 "per_family": per_family, "per_criterion": per_criterion, "pairs": len({(r["x"], r["y"]) for r in rs}),
                                 "outcomes": len(rs), "wins": bool(share is not None and share > 0.5 and majority)}
    for arm, hs in data["arms"].items():
        scores = defaultdict(list)
        for h in hs:
            for f in fams:
                v = done.get(f"rubric||{h['id']}||{f}|")
                if v:
                    for k in CRITERIA:
                        scores[k].append(int(v[k]))
        res["rubric"][arm] = {k: round(sum(v) / len(v), 2) for k, v in scores.items() if v}
    formatted = json.loads((d / "formatted.json").read_text())
    ln = {h: len(judged_text(f)) for h, f in formatted.items()}
    for c, v in res["comparisons"].items():         # does the longer text win? (Spearman of outcome and length difference)
        rs = [r for r in rows if r["comparison"] == c]
        if len(rs) >= 4:
            from scipy.stats import spearmanr
            diff = [ln[r["x"]] - ln[r["y"]] for r in rs]
            rho = spearmanr(diff, [r["score"] for r in rs]).statistic
            v["length"] = {"mean_x": round(sum(ln[r["x"]] for r in rs) / len(rs)), "mean_y": round(sum(ln[r["y"]] for r in rs) / len(rs)),
                           "spearman_outcome_vs_length_difference": None if rho != rho else round(float(rho), 3)}
    res["rule"] = {c: v["wins"] for c, v in res["comparisons"].items() if v["tested"]}
    (d / "score.json").write_text(json.dumps(res, indent=1, ensure_ascii=False) + "\n")
    return res


# dry run

def do_dry(d: Path, cfg: dict) -> dict:
    data = load(d)
    prices = yaml.safe_load(Path("configs/prices.yaml").read_text())["models"]
    model_of = {m["family"]: m["model"] for m in cfg["models"]}
    formatted = json.loads((d / "formatted.json").read_text()) if (d / "formatted.json").exists() else \
        {h["id"]: (shortened(h) if MODE.get("rewrite", True) else unreferenced(h)) for arm in data["arms"].values() for h in arm}
    by_family = defaultdict(lambda: {"calls": 0, "tokens_in": 0, "tokens_out": 0})
    for h in (h for arm in data["arms"].values() for h in arm if MODE.get("rewrite", True)):
        f = by_family[cfg["rewriter"]]
        f["calls"] += 1; f["tokens_in"] += estimate_tokens(render("format_hypothesis", "v2", text=h["text"], limit=LIMIT, target=TARGET, history_text=""))
        f["tokens_out"] += OUT_TOKENS["format_hypothesis"]
    for j in jobs(data, judges(cfg, data)):
        tpl, variables = prompt_of(j, data, formatted)
        f = by_family[j[4]]
        ver = MODE["pair_version"] if tpl == "judge_pair" else "v1"
        f["calls"] += 1; f["tokens_in"] += estimate_tokens(render(tpl, ver, **variables, history_text="")); f["tokens_out"] += OUT_TOKENS[tpl]
    total = 0.0
    for fam, f in by_family.items():
        p = prices.get(model_of.get(fam, ""), {})
        f["model"] = model_of.get(fam)
        f["usd"] = round(f["tokens_in"] / 1e6 * p.get("in", 0) + f["tokens_out"] / 1e6 * p.get("out", 0), 3) if p else None
        total += f["usd"] or 0
    return {"by_family": dict(by_family), "usd_total": round(total, 3),
            "note": "tokens in estimated from the rendered prompts (4 characters a token); out from fixed budgets; a retry adds up to one call"}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["dry", "format", "judge", "score"])
    ap.add_argument("--dir", required=True)
    ap.add_argument("--config", default=CONFIG)
    ap.add_argument("--fake", action="store_true")
    a = ap.parse_args(argv)
    d, cfg = Path(a.dir), yaml.safe_load(Path(a.config).read_text())
    set_mode(cfg)
    if a.cmd == "dry":
        print(json.dumps(do_dry(d, cfg), indent=1)); return
    if a.cmd == "score":
        print(json.dumps(do_score(d, cfg), indent=1, ensure_ascii=False)); return
    if a.cmd == "format" and not MODE.get("rewrite", True):     # nothing is rewritten: no client, no call
        print(json.dumps(do_format(d, None, cfg), indent=1)); return
    from hyparena.pipeline import _client
    data = load(d)
    n = sum(len(v) for v in data["arms"].values())
    client, _ = _client(a.config, a.fake, 2 * (n + len(jobs(data, judges(cfg, data)))) + 10)
    print(json.dumps(do_format(d, client, cfg) if a.cmd == "format" else do_judge(d, client, cfg), indent=1))


if __name__ == "__main__":
    main()

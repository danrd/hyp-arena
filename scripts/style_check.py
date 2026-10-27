"""L1.9: invariance of the places to the style of the hypothesis text, next to the Elo baseline (L0).

    python -m scripts.style_check texts                                  # needs ALLOW_PAID=1: 30 calls, the "hype" and "terse" rewrites
    ALLOW_PAID=1 python -m scripts.style_check run --out runs/stage5/l1_9   # two pipeline runs (H, T) and four L0 runs
    python -m scripts.style_check report --dir runs/stage5/l1_9

The 15 texts and the arms O1 and O2 (original style, twice) are those of L1.8 (data/validation/l1_8_texts.json, runs/stage5/l1_8).
Our method: Kendall tau-b between the expected scores of the profile evidence_first of the same 15 hypotheses in two styles;
the three style pairs (O1, H, T) must each not fall below tau(O1, O2) minus 0.05. The baseline (L0, one family, Elo, seeds 0 and 1 for
the original style) is reported next to it with no threshold. The criterion is in specs/validation-criteria.yaml (L1.9).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from scipy.stats import kendalltau

L18 = Path("data/validation/l1_8_texts.json")
TEXTS = Path("data/validation/l1_9_texts.json")
AS_OF = "2010-12-31"
TOL = 0.05
GOAL = "Identify the most promising and feasible hypotheses on interventions that extend lifespan."
STYLES = {
    "H": "a promotional, confident, enthusiastic style, with strong adjectives and a marketing tone (for example 'a breakthrough', 'remarkable')",
    "T": "a terse, telegraphic lab-notebook style: fragments, abbreviations and no full sentences",
}
PROMPT = ("Rewrite the research hypothesis below in {style}. Keep every factual element exactly: the name of the compound, the dose, the age "
          "at which treatment starts, the species and strain, which sexes, the endpoint and the direction of the effect. Do not add, drop or "
          "soften any claim and do not add background. Return only the rewritten text, with no preamble.\n\nHypothesis:\n{text}\n")


def first_paragraph(text: str) -> str:
    return text.split("\n\n")[0].strip()


def cmd_texts() -> None:
    from hyparena.card.pipeline import _client
    d = json.loads(L18.read_text())
    client, _ = _client("configs/v2-flash.yaml", False, 40)
    out = {"as_of": AS_OF, "items": []}
    for r in d["items"]:
        row = {"id": r["id"], "O": first_paragraph(r["text"]), "O_full": r["text"]}
        for k, desc in STYLES.items():
            reply = client.call(role="restyle", family="deepseek", prompt=PROMPT.format(style=desc, text=row["O"]), avoid=frozenset())
            if reply.error or not reply.text.strip():
                raise SystemExit(f"restyle {k} failed for {r['id']}: {reply.error}")
            row[k] = reply.text.strip()
        out["items"].append(row)
    TEXTS.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("calls", client.calls)


def dataset(d: dict, style: str, path: Path) -> Path:
    items = [{"id": i, "title": r["id"], "claim": r[style]} for i, r in enumerate(d["items"], start=1)]
    path.write_text(json.dumps({"source": {"family": "unknown", "model": "unknown", "strategy": "style-check", "as_of": AS_OF,
                                           "options": {"dedup": False, "lang": "en"}}, "hypotheses": items}, ensure_ascii=False, indent=1))
    return path


def cmd_run(out: str, max_calls: int) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from hyparena.card import pipeline
    d = json.loads(TEXTS.read_text())
    Path(out).mkdir(parents=True, exist_ok=True)

    def ours(style):
        res = pipeline.run([r[style] for r in d["items"]], config="configs/v2-flash.yaml", as_of=AS_OF, max_calls=max_calls,
                           verifiers=["deepseek"], dedup=False)
        Path(out, f"{style}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
        return style, res["meta"]["calls"]

    def l0(arm):
        style, seed = arm
        ds = dataset(d, style, Path(out) / f"l0_{style}.dataset.json")
        dst = Path(out) / f"L0_{style}_s{seed}.json"
        cmd = [sys.executable, "-m", "hyparena.live", "run", "--import-file", str(ds), "--ladder", "L0", "--seed", str(seed), "--as-of", AS_OF,
               "--goal", GOAL, "--cycles", "4", "--matches", "3", "--max-calls", "300", "--config", "configs/paid-test.yaml",
               "--search", "europepmc", "--max-tokens", "300000", "--out", str(dst)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        return str(dst), r.returncode

    with ThreadPoolExecutor(3) as pool:
        for name, calls in pool.map(ours, ["H", "T"]):
            print("ours", name, "calls", calls, flush=True)
        for name, rc in pool.map(l0, [("O", 0), ("O", 1), ("H", 0), ("T", 0)]):
            print("L0", name, "exit", rc, flush=True)


def _ours_scores(path: Path) -> list[float]:
    res = json.loads(path.read_text())
    e = res["ranking"]["evidence_first"]["expected"]
    return [e.get(x["id"]) if e.get(x["id"]) is not None else -1.0 for x in res["items"]]


def _l0_scores(path: Path, n: int) -> list[float]:
    h = json.loads(path.read_text())["hypotheses"]
    return [float(h[f"imp{i:03d}"].get("combined") or 0.0) for i in range(1, n + 1)]


def tau(a: list[float], b: list[float]) -> float:
    return float(kendalltau(a, b).statistic)


def verdict(taus: dict, repeat: float) -> dict:
    per = {k: {"tau": round(v, 3), "ok": v >= repeat - TOL} for k, v in taus.items()}
    return {"repeat_tau": round(repeat, 3), "pairs": per, "status": "pass" if all(v["ok"] for v in per.values()) else "fail"}


def cmd_report(dirname: str, l18dir: str = "runs/stage5/l1_8") -> dict:
    n = len(json.loads(TEXTS.read_text())["items"])
    o1, o2 = _ours_scores(Path(l18dir, "O1.json")), _ours_scores(Path(l18dir, "O2.json"))
    h, t = _ours_scores(Path(dirname, "H.json")), _ours_scores(Path(dirname, "T.json"))
    ours = verdict({"O-H": tau(o1, h), "O-T": tau(o1, t), "H-T": tau(h, t)}, tau(o1, o2))
    out = {"ours": ours}
    try:
        lo = {s: _l0_scores(Path(dirname, f"L0_{s}.json"), n) for s in ("O_s0", "O_s1", "H_s0", "T_s0")}
        out["baseline_L0"] = {"repeat_tau": round(tau(lo["O_s0"], lo["O_s1"]), 3),
                              "pairs": {"O-H": round(tau(lo["O_s0"], lo["H_s0"]), 3), "O-T": round(tau(lo["O_s0"], lo["T_s0"]), 3),
                                        "H-T": round(tau(lo["H_s0"], lo["T_s0"]), 3)}, "note": "reported next to ours, no threshold"}
    except FileNotFoundError as e:
        out["baseline_L0"] = f"missing: {e.filename}"
    print(json.dumps(out, indent=1))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("texts")
    r = sub.add_parser("run")
    r.add_argument("--out", required=True)
    r.add_argument("--max-calls", type=int, default=400)
    q = sub.add_parser("report")
    q.add_argument("--dir", required=True)
    a = ap.parse_args()
    {"texts": cmd_texts, "run": lambda: cmd_run(a.out, a.max_calls), "report": lambda: cmd_report(a.dir)}[a.cmd]()


if __name__ == "__main__":
    main()

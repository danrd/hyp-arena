"""L1.18: can a cheaper normalizer replace Gemini 3.5 Flash with hidden reasoning (specs/normalizer-acceptance-2026-10-30.yaml)?

    python -m scripts.normalizer_acceptance subset                 # no calls: groups g001-g010 of the 2026-10-29 negative groups
    ALLOW_PAID=1 python -m scripts.normalizer_acceptance run       # the repeat of the reference and candidates A and B (method v2 on each group)
    python -m scripts.normalizer_acceptance report

Reference: run r0 of the negative-sampling test (Gemini with reasoning, configs/v2-flash.yaml). Noise: the same configuration run again from
scratch (new cards). Measures of L1.8 (scripts/paraphrase_check.py): subject, relation, object, context of the main claim, status and outcome,
place; a candidate is accepted when every measure against the reference is at least the noise minus 0.05."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from scripts import paraphrase_check as pc

DATA = Path("data/negatives/drugage-2026-10-29")
SUB = Path("runs/normalizer_acceptance/data")
OUT = Path("runs/normalizer_acceptance")
REF = Path("runs/neg_2026_10_29/v2-evidence_first-r0")
GROUPS = [f"g{i:03d}" for i in range(1, 11)]
ARMS = {"rep": "configs/v2-flash.yaml", "a": "configs/v2-flash-gemini-nothink.yaml", "b": "configs/v2-flash-deepseek-norm.yaml"}
TOL = 0.05
MEASURES = ("subject", "relation", "object", "context", "status", "place")


def subset() -> None:
    SUB.mkdir(parents=True, exist_ok=True)
    labels = json.loads((DATA / "labels.json").read_text())
    (SUB / "labels.json").write_text(json.dumps({g: labels[g] for g in GROUPS}, ensure_ascii=False, indent=1))
    for g in GROUPS:
        (SUB / f"{g}.json").write_text((DATA / f"{g}.json").read_text())


def run() -> None:
    for arm, cfg in ARMS.items():
        subprocess.run([sys.executable, "-m", "hyparena.negatives", "v2", "--data", str(SUB), "--config", cfg, "--verifiers", "deepseek",
                        "--tag", f"nrm-{arm}", "--out-dir", str(OUT), "--max-calls", "200"], check=True)


def pooled(a_dir: Path, b_dir: Path) -> dict:
    tot, n = {k: 0.0 for k in MEASURES}, 0
    for g in GROUPS:
        a = pc.summarize(json.loads((a_dir / f"{g}.v2.json").read_text()))
        b = pc.summarize(json.loads((b_dir / f"{g}.v2.json").read_text()))
        k = len(a["items"])
        for m, v in pc.agreement(a, b).items():
            tot[m] += v * k
        n += k
    return {m: round(v / n, 3) for m, v in tot.items()} | {"n": n}


def report() -> dict:
    noise = pooled(OUT / "v2-evidence_first-nrm-rep", REF)
    out = {"noise_rep_vs_r0": noise}
    for arm in ("a", "b"):
        m = pooled(OUT / f"v2-evidence_first-nrm-{arm}", REF)
        ok = {k: m[k] >= noise[k] - TOL for k in MEASURES}
        out[arm] = {"vs_r0": m, "ok": ok, "accepted": all(ok.values())}
    acc = [a for a in ("b", "a") if out[a]["accepted"]]
    out["decision"] = {"b": "DeepSeek normalizer", "a": "Gemini without reasoning"}[acc[0]] if acc else "keep Gemini with reasoning"
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["subset", "run", "report"])
    a = ap.parse_args()
    if a.cmd == "subset":
        subset()
    elif a.cmd == "run":
        run()
    else:
        print(json.dumps(report(), indent=1))


if __name__ == "__main__":
    main()

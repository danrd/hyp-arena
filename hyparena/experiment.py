"""Run the comparison grid: ladder steps x seeds x token budgets, one result file per run.

    python -m hyparena.experiment --pool data/backtest/itp_<T>.json --as-of <T> \
        --steps L0,L4 --seeds 0,1,2 --budgets 150000,300000 --out-dir runs/exp            # prints the commands
    ... --execute                                                                       # runs them

Prints the commands by default (nothing is spent); --execute runs them one by one, skips results that
already exist (so an interrupted grid continues), and writes a manifest. Budgets are estimated tokens; a
run stops at the first cycle boundary past its budget, so compare by the spend recorded in each result.
Then: python -m hyparena.backtest compare --labels ... --a runs/exp/L0_b150000_s*.json --b runs/exp/L4_b150000_s*.json"""
from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path


def commands(args) -> list[tuple[Path, list[str]]]:
    out = []
    for step in args.steps.split(","):
        for budget in args.budgets.split(","):
            for seed in args.seeds.split(","):
                path = Path(args.out_dir) / f"{step}_b{budget}_s{seed}.json"
                cmd = [sys.executable, "-m", "hyparena.live", "run", "--import-file", args.pool,
                       "--ladder", step, "--seed", seed, "--max-tokens", budget, "--cycles", str(args.cycles),
                       "--max-calls", str(args.max_calls), "--config", args.config, "--search", args.search,
                       "--out", str(path)]
                if args.as_of:
                    cmd += ["--as-of", args.as_of]
                if args.fake:
                    cmd.append("--fake")
                out.append((path, cmd))
    return out


def execute(runs: list[tuple[Path, list[str]]], run: bool, manifest_path: Path) -> None:
    """Print the commands, or with `run` execute them one by one: results that exist are skipped (an
    interrupted grid continues), failures are reported, and a manifest is written."""
    manifest = {"runs": []}
    for path, cmd in runs:
        line = " ".join(shlex.quote(c) for c in cmd)
        if not run:
            print(line)
            continue
        if path.exists():
            print(f"skip (exists): {path}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            print(f"run: {path}", flush=True)
            done = subprocess.run(cmd, capture_output=True, text=True)
            if done.returncode != 0 or not path.exists():
                print(f"  failed (exit {done.returncode}): {done.stdout[-400:]} {done.stderr[-400:]}")
        manifest["runs"].append({"result": str(path), "exists": path.exists(), "command": line})
    if run:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2))
        print(f"manifest: {manifest_path}")
    else:
        print(f"\n{len(runs)} runs (dry run; add --execute to run them)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pool", required=True)
    ap.add_argument("--as-of", default=None)
    ap.add_argument("--steps", default="L0,L4")
    ap.add_argument("--seeds", default="0,1,2")
    ap.add_argument("--budgets", default="150000")
    ap.add_argument("--cycles", type=int, default=10, help="upper bound; the budget is meant to bind")
    ap.add_argument("--max-calls", type=int, default=2000)
    ap.add_argument("--config", default="configs/paid-test.yaml")
    ap.add_argument("--search", default="europepmc")
    ap.add_argument("--out-dir", default="runs/exp")
    ap.add_argument("--fake", action="store_true", help="fake LLM in every run (tests the grid, no cost)")
    ap.add_argument("--execute", action="store_true", help="run the commands (default: print them)")
    args = ap.parse_args()
    execute(commands(args), args.execute, Path(args.out_dir) / "manifest.json")


if __name__ == "__main__":
    main()

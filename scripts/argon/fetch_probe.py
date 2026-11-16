"""Can the outside model read our files from GitHub by link? A free probe before the prompts and the core of the code are
given to it as links instead of an attachment. The task names raw files of this public repository at one fixed commit and
asks, for each file, its number of lines and a few lines verbatim by number (one near the end, so that a cut-off read shows).
The lines cannot be guessed from the file names, so a model that did not read the file fails; code checks the answer.

    python -m scripts.argon.fetch_probe build [--commit SHA]   # task.json (to send) and expected.json (kept back)
    python -m scripts.argon.fetch_probe check                  # answer.json against expected.json

Files in longevity-kg reviews/fetch-probe-2026-11-16/ (PROBE_DIR).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KG = Path(os.environ.get("KG_DIR", ROOT.parent / "longevity-kg"))
DIR = Path(os.environ.get("PROBE_DIR", KG / "reviews" / "fetch-probe-2026-11-16"))
REPO = "danrd/hyp-arena"
FILES = ["hyparena/prompts/verify_claim/v21.j2",      # a prompt of the reader
         "hyparena/scoring/rules_v3.py",              # the core of the rules
         "hyparena/reports/report_html.py"]           # the longest file (about 110 KB): is a long read cut?
COVER = ("Please complete the task in the JSON below. Work on your own, in this chat only, and reply with one JSON object in "
         "the format given under \"answer_format\", with nothing around it.")


def _norm(s: str) -> str:
    return " ".join(s.split())


def _pick(lines: list[str]) -> list[int]:
    """Three line numbers (1-based) at about 10%, 50% and 95% of the file, each moved to the nearest line with at least
    25 non-space characters, so that the line is specific."""
    out = []
    for frac in (0.10, 0.50, 0.95):
        i = int(len(lines) * frac)
        cands = (j for d in range(len(lines)) for j in (i + d, i - d))
        out.append(next(j + 1 for j in cands
                        if 0 <= j < len(lines) and len(_norm(lines[j])) >= 25 and j + 1 not in out))
    return out


def _file_at(commit: str, path: str) -> str:
    return subprocess.run(["git", "show", f"{commit}:{path}"], cwd=ROOT, check=True, capture_output=True, text=True).stdout


def build(commit: str) -> dict:
    files, expected = [], {}
    for p in FILES:
        lines = _file_at(commit, p).split("\n")
        if lines and lines[-1] == "":
            lines = lines[:-1]
        nums = _pick(lines)
        url = f"https://raw.githubusercontent.com/{REPO}/{commit}/{p}"
        files.append({"url": url, "lines": nums})
        expected[url] = {"n_lines": len(lines), "lines": {str(n): lines[n - 1] for n in nums}}
    task = {"task": "fetch_probe", "commit": commit, "cover": COVER,
            "instructions": [
                "Open each link below (raw text files of a public GitHub repository at one fixed commit) and read the file.",
                "For each file give the number of lines it has and copy the lines with the numbers asked, verbatim (line 1 "
                "is the first line of the file).",
                "If you cannot open a link, or can read only part of a file, say so in 'status' and leave the lines empty; "
                "never reconstruct a line from memory or from the file name.",
                "Reply with one JSON object in the format at the end, nothing around it."],
            "files": files,
            "answer_format": {"files": [{"url": "", "status": "read whole | read part | could not open", "n_lines": "",
                                         "lines": {"<number>": ""}}]}}
    DIR.mkdir(parents=True, exist_ok=True)
    (DIR / "task.json").write_text(json.dumps(task, indent=1) + "\n")
    (DIR / "expected.json").write_text(json.dumps(expected, indent=1, ensure_ascii=False) + "\n")
    return task


def check() -> dict:
    exp = json.loads((DIR / "expected.json").read_text())
    ans = {f.get("url"): f for f in json.loads((DIR / "answer.json").read_text()).get("files", [])}
    per = {}
    for url, e in exp.items():
        a = ans.get(url) or {}
        got = {str(k): v for k, v in (a.get("lines") or {}).items()}
        per[url.rsplit("/", 1)[-1]] = {
            "status": a.get("status"), "n_lines": f"{a.get('n_lines')} / {e['n_lines']}",
            "lines_exact": sum(_norm(got.get(n, "")) == _norm(t) for n, t in e["lines"].items()),
            "lines_asked": len(e["lines"])}
    res = {"files": per, "all_exact": all(v["lines_exact"] == v["lines_asked"] for v in per.values())}
    (DIR / "check.json").write_text(json.dumps(res, indent=1) + "\n")
    return res


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["build", "check"])
    ap.add_argument("--commit", default=None)
    a = ap.parse_args(argv)
    if a.cmd == "build":
        commit = a.commit or subprocess.run(["git", "rev-parse", "origin/main"], cwd=ROOT, check=True, capture_output=True,
                                            text=True).stdout.strip()
        t = build(commit)
        print(json.dumps({k: t[k] for k in ("task", "commit", "files")}, indent=1))
    else:
        print(json.dumps(check(), indent=1))


if __name__ == "__main__":
    main()

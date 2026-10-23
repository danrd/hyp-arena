"""Specifications fixed before the data are read (test plan A4).

A run that is meant to be judged by a criterion names a spec file (`specs/*.yaml`). `stamp` refuses a spec that is not
committed or has uncommitted changes, and writes into the run's meta the content hash, the commit that holds it and the
UTC time of the stamp, taken before the run reads any data. `verify` recomputes the hash from the commit, checks the
commit is in the history and is older than the stamp. The hash is taken over the parsed content, so comments and key
order do not change it. It proves the order of commit and run, not that nobody wrote the spec after seeing data
elsewhere."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml


class SpecNotCommitted(RuntimeError):
    pass


def digest(text: str) -> str:
    """sha256 of the canonical JSON of the parsed YAML."""
    return hashlib.sha256(json.dumps(yaml.safe_load(text), sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode()).hexdigest()


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=check)


def load(path: str | Path) -> dict:
    return yaml.safe_load(Path(path).read_text())


def stamp(path: str | Path, repo: str | Path = ".") -> dict:
    """The meta entry for a run on this spec; raises `SpecNotCommitted` unless the file is committed and unchanged."""
    path, repo = Path(path), Path(repo)
    rel = str(path.resolve().relative_to(repo.resolve()))
    if _git(repo, "ls-files", "--error-unmatch", rel, check=False).returncode:
        raise SpecNotCommitted(f"{rel} is not tracked by git: commit the spec before the run")
    if _git(repo, "status", "--porcelain", "--", rel).stdout.strip():
        raise SpecNotCommitted(f"{rel} has uncommitted changes: commit the spec before the run")
    commit, committed_at = _git(repo, "log", "-1", "--format=%H %cI", "--", rel).stdout.split()
    return {"file": rel, "sha256": digest(path.read_text()), "commit": commit, "committed_at": committed_at,
            "stamped_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def conflicts(spec: dict, given: dict) -> list[str]:
    """Parameters of a run that differ from the spec's (only keys the spec names are compared)."""
    return [f"{k}: run {v!r}, spec {spec[k]!r}" for k, v in given.items() if k in spec and v != spec[k]]


def begin(path: str | Path, given: dict, repo: str | Path = ".") -> dict:
    """Start of a run on a spec: the meta entry, after the parameters of the run are checked against the spec.
    Called before the run reads any data."""
    bad = conflicts(load(path), given)
    if bad:
        raise ValueError(f"the run differs from {path}: " + "; ".join(bad))
    entry = stamp(path, repo)
    if "indicators_sha256" in given:                  # the indicator set of the run is recorded next to the spec hash
        entry["indicators_sha256"] = given["indicators_sha256"]
    return entry


def verify(entry: dict, repo: str | Path = ".") -> list[str]:
    """Problems with a run's `meta.spec` entry; an empty list means the order is as declared."""
    repo, out = Path(repo), []
    commit, rel = entry.get("commit", ""), entry.get("file", "")
    shown = _git(repo, "show", f"{commit}:{rel}", check=False) if commit else None
    if shown is None or shown.returncode:
        return [f"commit {commit[:10] or '?'} does not hold {rel or '?'} in this repository"]
    if digest(shown.stdout) != entry.get("sha256"):
        out.append("the spec at that commit does not match the hash in the run")
    shallow = _git(repo, "rev-parse", "--is-shallow-repository", check=False).stdout.strip() == "true"
    if not shallow and _git(repo, "merge-base", "--is-ancestor", commit, "HEAD", check=False).returncode:
        out.append("the commit is not in the history of HEAD")
    when = _git(repo, "show", "-s", "--format=%cI", commit).stdout.strip()
    if datetime.fromisoformat(when) > datetime.fromisoformat(entry["stamped_at"]):
        out.append(f"the spec was committed ({when}) after the run started ({entry['stamped_at']})")
    return out


def check_run(path: str | Path, repo: str | Path = ".") -> list[str]:
    spec = (json.loads(Path(path).read_text()).get("meta") or {}).get("spec")
    return verify(spec, repo) if spec else ["the run names no spec"]


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("stamp", help="print the meta entry for a committed spec").add_argument("spec")
    sub.add_parser("check", help="verify the spec entry in saved runs (exit 1 on a problem)").add_argument("runs", nargs="+")
    a = ap.parse_args(argv)
    if a.cmd == "stamp":
        print(json.dumps(stamp(a.spec), indent=1))
        return 0
    bad = 0
    for r in a.runs:
        problems = check_run(r)
        bad += bool(problems)
        print(f"{r}: " + ("ok" if not problems else "; ".join(problems)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

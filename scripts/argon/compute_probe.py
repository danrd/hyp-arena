"""Can the outside model run our code? A free probe: the scoring code of the method (the modules hyparena/scoring/rules_v32.py
needs, at one commit), a runner and six cases (three made up, from the tests' worked example; three real units of the
calibration run with the current method) go to the outside model as one zip archive; it runs the runner and returns its
output. Code compares every number with the output of the same archive run here (kept back).

    python -m scripts.argon.compute_probe build    # files.zip and task.json (to send), expected.json (kept back)
    python -m scripts.argon.compute_probe check    # answer.json against expected.json

Files in longevity-kg reviews/compute-probe-2026-11-17/ (PROBE_DIR).
"""
from __future__ import annotations

import argparse
import glob
import io
import json
import os
import random
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KG = Path(os.environ.get("KG_DIR", ROOT.parent / "longevity-kg"))
DIR = Path(os.environ.get("PROBE_DIR", KG / "reviews" / "compute-probe-2026-11-17"))
MODULES = ["hyparena/__init__.py", "hyparena/alternatives/__init__.py", "hyparena/alternatives/threats.py",
           "hyparena/card/__init__.py", "hyparena/card/contexts.py", "hyparena/card/models.py",
           "hyparena/reading/__init__.py", "hyparena/reading/effect_class.py", "hyparena/reading/review_kind.py",
           "hyparena/scoring/__init__.py", "hyparena/scoring/rules.py", "hyparena/scoring/rules_v3.py",
           "hyparena/scoring/rules_v32.py", "hyparena/scoring/v3_levels.py"]
TOL = 1e-3

RUNNER = '''"""Run the method's scoring (hyparena/scoring/rules_v32.evaluate, the current rules) on the cases of cases.json and print
the results as JSON. Needs Python 3.11; pydantic 2 and PyYAML come from wheels/ when missing. No network: the approved-drug lookup is switched off.

    python probe_run.py cases.json > result.json
"""
import json
import platform
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _vendor() -> None:
    """Without network: when pydantic 2 is missing, unpack the wheels shipped in wheels/<machine>/ into _vendor/ and use them."""
    try:
        import pydantic
        if int(pydantic.VERSION.split(".")[0]) >= 2:
            return
    except ImportError:
        pass
    machine = {"amd64": "x86_64", "arm64": "aarch64"}.get(platform.machine().lower(), platform.machine().lower())
    wheels = sorted((HERE / "wheels" / machine).glob("*.whl"))
    if not wheels:
        raise SystemExit(f"no wheels for {machine} in wheels/")
    target = HERE / "_vendor"
    for w in wheels:
        zipfile.ZipFile(w).extractall(target)
    sys.path.insert(0, str(target))
    for m in [m for m in sys.modules if m == "pydantic" or m.startswith(("pydantic.", "pydantic_core", "typing_extensions"))]:
        del sys.modules[m]


def _scipy_stub() -> bool:
    """scipy gives only the Beta interval shown next to a link's strength, which this probe does not print; when scipy is
    missing a stub returns NaN for it, so that no printed number depends on scipy."""
    try:
        import scipy.stats  # noqa: F401
        return False
    except ImportError:
        import types
        nan = float("nan")
        stats = types.ModuleType("scipy.stats")
        stats.beta = types.SimpleNamespace(ppf=lambda *a, **k: nan, mean=lambda *a, **k: nan, interval=lambda *a, **k: (nan, nan))
        scipy = types.ModuleType("scipy")
        scipy.stats = stats
        sys.modules["scipy"], sys.modules["scipy.stats"] = scipy, stats
        return True


_vendor()
SCIPY_STUB = _scipy_stub()
sys.path.insert(0, str(HERE))
from hyparena.card.models import ClaimVerification, HypothesisCard   # noqa: E402
from hyparena.scoring import rules_v3 as r3, rules_v32 as r32       # noqa: E402

r3.established_by_approval = lambda claim, card: False


def run(case: dict) -> dict:
    card = HypothesisCard.model_validate(case["card"])
    cvs = [ClaimVerification.model_validate(c) for c in case["verifications"]]
    alts = {k: ClaimVerification.model_validate(v) for k, v in (case.get("alternatives") or {}).items()}
    e = r32.evaluate(card, cvs, alts, v36=True)
    claims = {c.id: c for c in card.claims}
    weights = {}
    for cv in cvs:
        c = claims.get(cv.id)
        if c is None:
            continue
        for side, recs in (("for", cv.evidence), ("against", cv.counterevidence)):
            for r in recs:
                weights[f"{cv.id}|{side}|{r.record_id}"] = round(r32.record_weight_v36(r, c, side == "against"), 4)
    return {"gate": e.gate, "chain_state": round(e.chain_state, 4), "I": round(e.I, 4), "scope": e.scope,
            "links": {k: {"S": round(v[0], 4), "F": round(v[3], 4)} for k, v in e.links.items()},
            "record_weights": weights}


if __name__ == "__main__":
    cases = json.loads(Path(sys.argv[1] if len(sys.argv) > 1 else "cases.json").read_text())
    print(json.dumps({c["id"]: run(c) for c in cases}, indent=1, ensure_ascii=False))
'''

INSTRUCTIONS = [
    "The attached archive files.zip holds part of a Python code base (the package 'hyparena'), a runner probe_run.py and "
    "the input cases.json.",
    "Unpack it and run, in the unpacked folder: python probe_run.py cases.json. It needs Python 3.11; pydantic 2 and PyYAML "
    "are shipped in wheels/ and the runner unpacks them itself when they are missing (no pip, no network needed).",
    "Return the runner's output exactly as printed (a JSON object, one entry per case) under 'output'.",
    "You must actually execute the code. If you cannot run Python, or the run fails, say so in 'status' and give the error "
    "message in 'error'; never compute the numbers by hand or estimate them.",
    "Reply with one JSON object in the format at the end, nothing around it. Escape every quote inside strings, or attach "
    "the reply as a .json file."]


def _file_at(commit: str, path: str) -> str:
    return subprocess.run(["git", "show", f"{commit}:{path}"], cwd=ROOT, check=True, capture_output=True, text=True).stdout


def _cases() -> list[dict]:
    sys.path.insert(0, str(ROOT))
    from hyparena.card.models import ClaimVerification
    from scripts.common.v34_check import CAL
    from tests.test_analyze import _case
    from tests.test_rules_v3 import rec
    dump = lambda cid, card, cvs, alts: {"id": cid, "card": card.model_dump(mode="json"),
                                         "verifications": [x.model_dump(mode="json") for x in cvs],
                                         "alternatives": {k: v.model_dump(mode="json") for k, v in alts.items()}}
    c, cvs, alts = _case()
    out = [dump("S1", c, cvs, alts),
           dump("S2", c, cvs + [ClaimVerification(id="c2", evidence=[rec(5, "animal", n=40, effect="large")])], alts),
           dump("S3", c, cvs + [ClaimVerification(id="c2", counterevidence=[rec(5, "animal", n=40, effect="none")])], alts)]
    runs, units = {}, {}
    for f in sorted(glob.glob(str(CAL / "run_*_cur.json"))):
        runs.update(json.loads(Path(f).read_text()))
    for s in range(1, 6):
        units.update({u["id"]: u for u in json.loads((CAL / f"units_{s}.json").read_text())})
    cand = [h for h, r in runs.items() if r["items"] and r["items"][0].get("card") and units.get(h, {}).get("label") in (0, 1)]
    random.Random(17).shuffle(cand)
    k = 0
    for h in cand:
        it = runs[h]["items"][0]
        if sum(len(x.get("evidence", [])) + len(x.get("counterevidence", [])) for x in it["verification"]["claims"]) < 5:
            continue
        k += 1
        out.append({"id": f"R{k}", "card": it["card"], "verifications": it["verification"]["claims"],
                    "alternatives": it.get("v3_alternatives") or {}})
        if k == 3:
            break
    return out


WHEELS = Path(os.environ.get("WHEELS_DIR", ""))   # pip download dir: <manylinux2014_x86_64|..._aarch64>/*.whl


def build(commit: str) -> dict:
    DIR.mkdir(parents=True, exist_ok=True)
    cases = json.dumps(_cases(), ensure_ascii=False)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in MODULES:
            z.writestr(p, _file_at(commit, p))
        z.writestr("probe_run.py", RUNNER)
        if WHEELS.is_dir():                                    # pydantic 2 and PyYAML for Python 3.11, per machine
            for w in sorted(WHEELS.glob("*/*.whl")):
                z.write(w, f"wheels/{w.parent.name.replace('manylinux2014_', '')}/{w.name}")
        z.writestr("cases.json", cases)
    (DIR / "files.zip").write_bytes(buf.getvalue())
    with tempfile.TemporaryDirectory() as tmp:                 # the expected output: the same archive, run alone
        zipfile.ZipFile(DIR / "files.zip").extractall(tmp)
        res = subprocess.run([sys.executable, "-I", "probe_run.py", "cases.json"], cwd=tmp, check=True,
                             capture_output=True, text=True)
    (DIR / "expected.json").write_text(res.stdout)
    task = {"task": "compute_probe", "commit": commit, "instructions": INSTRUCTIONS,
            "answer_format": {"status": "ran | could not run | failed", "python_version": "", "error": "", "output": {}}}
    (DIR / "task.json").write_text(json.dumps(task, indent=1) + "\n")
    return {"cases": len(json.loads(cases)), "zip_kb": round(len(buf.getvalue()) / 1024, 1)}


def _flat(d, prefix=""):
    if isinstance(d, dict):
        for k, v in d.items():
            yield from _flat(v, f"{prefix}{k}/")
    else:
        yield prefix.rstrip("/"), d


def check() -> dict:
    exp = dict(_flat(json.loads((DIR / "expected.json").read_text())))
    ans = json.loads((DIR / "answer.json").read_text())
    got = dict(_flat(ans.get("output") or {}))
    same, diff = 0, []
    for k, v in exp.items():
        g = got.get(k)
        ok = (abs(float(g) - float(v)) <= TOL) if isinstance(v, (int, float)) and isinstance(g, (int, float)) else g == v
        same += ok
        if not ok:
            diff.append({"key": k, "expected": v, "got": g})
    res = {"status": ans.get("status"), "values": len(exp), "same": same, "missing": sum(k not in got for k in exp),
           "extra": sorted(set(got) - set(exp))[:20], "diff": diff[:50], "all_same": same == len(exp)}
    (DIR / "check.json").write_text(json.dumps(res, indent=1, ensure_ascii=False) + "\n")
    return {k: v for k, v in res.items() if k != "diff"} | {"diff_shown": len(res["diff"])}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["build", "check"])
    ap.add_argument("--commit", default=None)
    a = ap.parse_args(argv)
    if a.cmd == "build":
        commit = a.commit or subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True,
                                            text=True).stdout.strip()
        print(json.dumps(build(commit), indent=1))
    else:
        print(json.dumps(check(), indent=1))


if __name__ == "__main__":
    main()
